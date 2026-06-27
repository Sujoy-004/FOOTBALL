"""Entry point for the World Cup Dynamic Predictor.

Loads state, enters a continuous polling loop (default 60s interval),
and handles graceful shutdown via SIGINT/SIGTERM.
"""

import argparse
import copy
import json
import logging
import math
import os
import random
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src import constants
from src import elo, elo_sync, output, state
from src.constants import API_TIMEOUT, ELO_SYNC_INTERVAL_HOURS, POLL_INTERVAL
from src.constants import ODDS_CACHE_TTL_HOURS, CATBOOST_CACHE_TTL_HOURS, ODDS_CACHE_FILE, CATBOOST_CACHE_FILE
from src.fetcher import build_historic_url, fetch_raw_matches, process_group_matches, process_matches
from src.knockout import resolve_knockout_slot_teams, run_full_simulation
from src.output import print_sync_results, print_staleness_warning, print_drift_flags
from src.predictors.odds import fetch_and_cache_odds
from src.predictors.catboost import fetch_and_cache_catboost
from src.predictors.form import compute_form_signal
from src.predictors.lineup import compute_lineup_signal
from src.constants import FORM_CACHE_FILE, LINEUP_CACHE_FILE


@dataclass
class RunState:
    """Mutable state for the polling loop.

    Replaces 8 module-level globals and all ``global`` keywords.
    A single module-level instance ``_state`` is shared by all functions.
    """
    running: bool = True
    elo_last_sync_time: float = 0.0
    last_gov_time: float = 0.0
    ai_preview_enabled: bool = False
    match_detail_enabled: str | None = None
    prev_signal_data: dict | None = None


_state = RunState()


def _should_run_gov() -> bool:
    """Check if governance should run this cycle.

    Governance runs at startup (when last_gov_time == 0.0) and
    hourly thereafter (D-16).

    Returns:
        True if governance should run, False otherwise.
    """
    now = time.time()
    if _state.last_gov_time == 0.0:
        return True
    if now - _state.last_gov_time >= constants.GOVERNANCE_INTERVAL_SECONDS:
        return True
    return False


def _merge_signals_into_history(
    data_dir: Path | str | None = None,
) -> None:
    """Merge retained signal data into prediction_history entries.

    CRITICAL DATA FLOW: Without this, evaluate_all_matches(signal_name="market_odds")
    returns n_matches=0 because prediction_history only has elo signals.

    For each prediction_history entry that lacks market_odds or catboost signals,
    looks up the match_id in the permanent prediction ledger (Phase 14a).
    If a signal is available for that match, adds it to the entry's signals dict.
    Saves updated history atomically via save_prediction_history().

    Args:
        data_dir: Per-league data directory. Defaults to constants.DATA_DIR.
    """
    history = state.load_prediction_history(data_dir)
    if not history:
        return
    ledger = state.load_prediction_ledger(data_dir)
    if not ledger:
        return
    changed = False
    for entry in history:
        signals = entry.get("signals", {})
        if not isinstance(signals, dict):
            continue
        mid = entry.get("match_id", "")
        match_signals = ledger.get(mid, {})
        if "market_odds" in match_signals and "market_odds" not in signals:
            signals["market_odds"] = dict(match_signals["market_odds"])
            changed = True
        if "catboost" in match_signals and "catboost" not in signals:
            signals["catboost"] = dict(match_signals["catboost"])
            changed = True
        if "form" in match_signals and "form" not in signals:
            signals["form"] = dict(match_signals["form"])
            changed = True
        if "lineup_strength" in match_signals and "lineup_strength" not in signals:
            signals["lineup_strength"] = dict(match_signals["lineup_strength"])
            changed = True
    if changed:
        state.save_prediction_history(history, data_dir)


def _run_calibrate_and_blend(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    odds_cache: dict,
    cb_cache: dict,
    form_cache: dict | None = None,
    lineup_cache: dict | None = None,
    data_dir: Path | str | None = None,
) -> dict | None:
    """Orchestrate calibration + blending via blender.calibrate_and_blend().

    Loads data from disk, delegates to pure-function pipeline in blender.py,
    persists calibration params.

    Args:
        data_dir: Per-league data directory. Defaults to constants.DATA_DIR.

    Returns blend_params dict (for simulation) or None (graceful degradation).
    """
    try:
        from src.blender import calibrate_and_blend
        from src.state import load_prediction_history, save_calibration_params

        history = load_prediction_history(data_dir)
        if not history:
            return None

        elo_ratings = {name: data["elo"] for name, data in teams.items()}
        blend_params = calibrate_and_blend(
            history=history,
            signal_keys=["elo", "market_odds", "catboost", "form", "lineup_strength"],
            elo_ratings=elo_ratings,
            groups_data=groups,
            bracket_data=bracket,
            odds_cache=odds_cache or {},
            cb_cache=cb_cache or {},
            form_cache=form_cache or {},
            lineup_cache=lineup_cache or {},
        )
        if blend_params and blend_params.get("calibration_params"):
            save_calibration_params(blend_params["calibration_params"], data_dir)
        n_matches = len(blend_params.get("match_probs", {})) if blend_params else 0
        n_signals = len(blend_params.get("blend_weights", {})) if blend_params else 0
        if blend_params:
            print(f"Blending active: {n_matches} matches, {n_signals} signals")
        else:
            print("Blending inactive (insufficient data)")
        return blend_params
    except Exception:
        return None


def _run_elo_sync(
    teams: dict[str, dict],
    data_dir: Path | str | None = None,
) -> None:
    """Run Elo sync from eloratings.net with cache fallback per D-15/D-19/D-20.

    On first-ever run with no cache and sync failure, prints a clear error
    and continues with teams.json fallback (D-20). On subsequent failures,
    falls back to cached values (D-19).

    Updates elo_last_sync_time on any successful sync, even if no corrections
    were needed, so the periodic 24h timer advances correctly.

    Args:
        teams: Team data dict.
        data_dir: Per-league data directory. Defaults to constants.DATA_DIR.
    """
    start = time.time()
    corrections = elo_sync.sync_elo_from_eloratings(teams, data_dir=data_dir)
    elapsed = time.time() - start

    if corrections is None:
        # Fetch failed (D-15, D-19, D-20)
        cache = state.load_eloratings_cache(data_dir)
        if not cache and _state.elo_last_sync_time == 0.0:
            # D-20: First run, no cache, network failure
            output.print_error(
                "Cannot initialize Elo ratings — eloratings.net unreachable "
                "and no cached values exist. Using teams.json initial values."
            )
        return

    # Sync succeeded — update timer even if no drift (D-02, D-03)
    _state.elo_last_sync_time = time.time()

    if corrections:
        print_sync_results(corrections, elapsed)
        flagged = [c for c in corrections if c.get("reason") == "overwrite_drift_gt_30"]
        if flagged:
            print_drift_flags(flagged)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list (None = use sys.argv). Exposed for testing.

    Returns:
        Namespace with once (bool), no_color (bool), seed (int | None).
    """
    parser = argparse.ArgumentParser(
        prog="wc-predict",
        description="World Cup Dynamic Predictor — live tournament odds in your terminal.",
        epilog=(
            "By default, the tool runs continuously, polling the Football-Data.org "
            "API every 60 seconds and re-simulating after each new match. "
            "Press Ctrl+C for a graceful shutdown with final probabilities."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        dest="once",
        help="Run a single fetch\u2192simulate\u2192print cycle, then exit",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        dest="no_color",
        help="Disable ANSI color output (overrides terminal auto-detection)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Random seed for reproducible simulation (same seed + same data = same results)",
    )
    parser.add_argument(
        "--ai-preview",
        action="store_true",
        dest="ai_preview",
        help="Display BSD AI prediction previews after simulation output (Phase 18)",
    )
    parser.add_argument(
        "--match-detail",
        type=str,
        nargs="?",
        const="table",
        default=None,
        help="Display per-match signal breakdown. Use --match-detail to show table, --match-detail MATCH_ID to show focus card (Phase 20)",
    )
    parser.add_argument(
        "--league",
        type=int,
        default=None,
        metavar="ID",
        help="BSD league ID (default: 27 for World Cup; see --list-leagues for all 65)",
    )
    parser.add_argument(
        "--list-leagues",
        action="store_true",
        dest="list_leagues",
        help="Print all available league IDs and names, then exit",
    )
    return parser.parse_args(argv)


def _signal_handler(signum, frame):
    """Set running flag to False — loop will finish current iteration then exit."""
    _state.running = False
    print()
    print("Shutdown requested — finishing current iteration...")


def _next_poll_sleep(interval: float) -> None:
    """Sleep for interval seconds in 0.5s increments, checking running flag."""
    deadline = time.time() + interval
    while _state.running and time.time() < deadline:
        time.sleep(0.5)


def _compute_group_display(groups, teams, played_groups):
    """Run a single deterministic group simulation iteration for display.

    Uses seed=0 for reproducibility. This is fast (~0.01s) — one iteration
    of 72 group matches is negligible compared to the 50K main simulation.

    Args:
        groups: Group definitions dict.
        teams: Team data dict.
        played_groups: Dict of played group match results.

    Returns:
        Tuple of (standings, third_ranked) from compute_standings() and
        rank_third_placed(). Returns ({}, []) if groups is empty.
    """
    if not groups:
        return {}, []
    from src.groups import (
        compute_standings, rank_third_placed,
        precompute_matchup_lambdas, simulate_group_matches,
    )
    elo = {n: d["elo"] for n, d in teams.items()}
    lambdas = precompute_matchup_lambdas(groups, elo, base_rate=constants.EXPECTED_GOALS_BASE_RATE)
    results = simulate_group_matches(
        groups, teams, elo, random.Random(0),
        fair_play=False, matchup_lambdas=lambdas,
        played_groups=played_groups or {},
        base_rate=constants.EXPECTED_GOALS_BASE_RATE,
    )
    standings = compute_standings(results, elo)
    return standings, rank_third_placed(standings)


def _run_historical_catch_up(
    api_key: str,
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    aliases: dict[str, list[str]],
    played_groups: dict[str, dict],
    played: dict[str, dict],
    elo_applied: set[str] | None = None,
    league_id: int = 27,
    data_dir: Path | str | None = None,
) -> tuple[dict[str, dict], dict[str, dict], set[str]]:
    """Fetch all finished matches from WC_START to today, ingest any not yet played.

    Handles both group matches (via process_group_matches for dedup/alias logic)
    and knockout matches (via iterative bracket resolution using resolve_knockout_slot_teams).
    Applies Elo rating updates to newly-ingested matches in chronological
    (completed_at, match_id) order.

    Args:
        elo_applied: Set of match_ids that already have Elo applied (restart guard).
        league_id: BSD league ID for URL construction and fetch filtering.
        data_dir: Per-league data directory. Defaults to constants.DATA_DIR.

    Returns (updated played_groups, updated played, updated elo_applied).
    """
    historic_url = build_historic_url(league_id=league_id)
    raw = fetch_raw_matches(api_key, api_url=historic_url, league_id=league_id)
    if not raw:
        return played_groups, played, elo_applied or set()

    if elo_applied is None:
        elo_applied = set()

    total_new = 0
    new_matches_all: list[dict] = []

    # ── Group match catch-up ──
    played_bsd_event_ids: set[str] = set()
    new_group = process_group_matches(
        raw, teams, groups, aliases,
        set(played_groups.keys()), played_bsd_event_ids,
    )
    if new_group:
        for m in new_group:
            output.print_match_alert(m)
            played_groups[m["match_id"]] = m
        state.save_played_groups(played_groups, data_dir)
        new_matches_all.extend(new_group)
        total_new += len(new_group)

    # ── Knockout match catch-up ──
    knockout_events = [
        e for e in raw
        if e.get("status") == "finished" and e.get("group_name") is None
    ]
    if knockout_events:
        alias_lookup: dict[str, str] = {}
        for match in bracket:
            if match.get("team_a"):
                alias_lookup[match["team_a"].strip().lower()] = match["team_a"]
            if match.get("team_b"):
                alias_lookup[match["team_b"].strip().lower()] = match["team_b"]
        for canonical, variants in aliases.items():
            alias_lookup[canonical.strip().lower()] = canonical
            for variant in variants:
                alias_lookup[variant.strip().lower()] = canonical

        def _normalize(name: str) -> str | None:
            return alias_lookup.get(name.strip().lower())

        new_knockout_matches: list[dict] = []
        changed = True
        while changed:
            changed = False
            slot_teams = resolve_knockout_slot_teams(
                groups, teams, played_groups, bracket, annex_c, dict(played)
            )
            teams_to_id: dict[frozenset[str], str] = {}
            for mid, st in slot_teams.items():
                teams_to_id[frozenset([st["team_a"], st["team_b"]])] = mid

            for event in knockout_events:
                bsd_id = str(event.get("id", ""))
                if bsd_id in played_bsd_event_ids:
                    continue
                home_norm = _normalize(event.get("home_team", ""))
                away_norm = _normalize(event.get("away_team", ""))
                if home_norm is None or away_norm is None:
                    played_bsd_event_ids.add(bsd_id)
                    continue
                event_key = frozenset([home_norm, away_norm])
                match_id = teams_to_id.get(event_key)
                if match_id is None:
                    continue
                if match_id in played:
                    played_bsd_event_ids.add(bsd_id)
                    continue
                home_score = event.get("home_score", 0)
                away_score = event.get("away_score", 0)
                if home_score > away_score:
                    winner = home_norm
                elif away_score > home_score:
                    winner = away_norm
                else:
                    # Draw or PK shootout (D-01, D-06)
                    bsd_winner = event.get("winner")
                    if bsd_winner:
                        # PK shootout — equal scores but BSD has winner
                        bsd_winner_lower = bsd_winner.strip().lower()
                        home_lower = event.get("home_team", "").strip().lower()
                        away_lower = event.get("away_team", "").strip().lower()
                        if bsd_winner_lower == home_lower:
                            winner = home_norm
                        else:
                            winner = away_norm
                    else:
                        # True draw
                        winner = None
                match_entry = {
                    "match_id": match_id,
                    "team_a": home_norm,
                    "team_b": away_norm,
                    "winner": winner,
                    "is_draw": (winner is None),
                    "home_score": home_score,
                    "away_score": away_score,
                    "completed_at": event.get("event_date", ""),
                }
                played[match_id] = match_entry
                new_knockout_matches.append(match_entry)
                total_new += 1
                changed = True
                played_bsd_event_ids.add(bsd_id)

        if new_knockout_matches:
            state.save_played(played, data_dir)
            new_matches_all.extend(new_knockout_matches)

    if total_new:
        print(f"Historical catch-up: ingested {total_new} prior match(es)")

    # ── Apply Elo updates in chronological order ──
    new_matches_all.sort(key=lambda m: (m["completed_at"], m["match_id"]))
    elo_updated = False
    for m in new_matches_all:
        if m["match_id"] in elo_applied:
            continue
        elo_applied.add(m["match_id"])
        elo_updates = elo.apply_elo_update(m, teams)
        if elo_updates:
            elo_updated = True
    if elo_updated:
        state.save_teams(teams, data_dir)

    return played_groups, played, elo_applied


def _run_draw_backfill(
    teams: dict[str, dict],
    played: dict[str, dict],
    played_groups: dict[str, dict],
    elo_applied: set[str],
    data_dir: Path | str | None = None,
) -> set[str]:
    """One-shot backfill: replay all historical draws through fixed Elo pipeline.

    Scans played.json and played_groups.json for matches where home_score == away_score
    that are NOT already in elo_applied. Replays them chronologically through
    apply_elo_update(), logs to elo_update_log.json, and returns updated elo_applied.

    Args:
        teams: Team data dict (mutated in-place with Elo updates).
        played: Played knockout matches dict.
        played_groups: Played group matches dict.
        elo_applied: Set of match_ids that already have Elo applied.
        data_dir: Per-league data directory. Defaults to constants.DATA_DIR.

    Returns:
        Updated elo_applied set with backfilled match_ids added.
    """
    from src import elo, state

    candidates: list[dict] = []

    for match_dict in [played, played_groups]:
        for mid, m in match_dict.items():
            if m.get("home_score", 0) == m.get("away_score", 0):
                if mid not in elo_applied:
                    if m.get("is_draw", True):
                        entry = dict(m)
                        entry["winner"] = None
                        candidates.append(entry)
                    else:
                        candidates.append(dict(m))

    if not candidates:
        return elo_applied

    candidates.sort(key=lambda x: (x.get("completed_at", ""), x.get("match_id", "")))

    log = state.load_elo_update_log(data_dir)
    backfilled: set[str] = set()

    for m in candidates:
        mid = m["match_id"]
        if mid in elo_applied:
            continue
        elo_updates = elo.apply_elo_update(m, teams)
        for team_name, change in elo_updates.items():
            log.append({
                "timestamp": datetime.now().isoformat(),
                "team": team_name,
                "old_value": change["old"],
                "new_value": change["new"],
                "source": "elo_engine",
                "reason": "historical draw backfill",
                "drift_magnitude": round(abs(change["new"] - change["old"]), 1),
            })
        elo_applied.add(mid)
        backfilled.add(mid)

    state.save_elo_applied(elo_applied, data_dir)
    state.save_teams(teams, data_dir)
    state.save_elo_update_log(log, data_dir)

    if backfilled:
        print(f"Draw backfill: applied Elo to {len(backfilled)} historical draw(s)")

    return elo_applied


def _record_eval_baseline(
    teams: dict[str, dict],
    played: dict[str, dict],
    played_groups: dict[str, dict],
    data_dir: Path | str | None = None,
) -> None:
    """Record baseline evaluation report using the evaluation framework.

    Delegates to evaluation.evaluate_all_matches() and persists the report.
    Replaces the ad-hoc Brier/log-loss computation from Phase 12.

    Args:
        data_dir: Per-league data directory. Defaults to constants.DATA_DIR.
    """
    from src.evaluation import evaluate_all_matches
    from src.state import save_eval_baseline_report, load_prediction_history

    history = load_prediction_history(data_dir=data_dir)
    report = evaluate_all_matches(teams, played, played_groups, signal_name="elo", history=history)
    save_eval_baseline_report(report, data_dir)

    if report["n_matches"] > 0:
        m = report["metrics"]
        print(f"Baseline: Brier={m['brier']:.4f}, LogLoss={m['log_loss']:.4f}, "
              f"Acc={m['accuracy']:.3f}, ECE={report['calibration']['ece']:.4f} "
              f"({report['n_matches']} matches)")
    else:
        print("Baseline: no matches to evaluate")


# ── Signal data helpers (Phase 20-03) ──────────────────────────────────────


def _collect_matches_from_groups(groups: dict) -> list[dict]:
    """Collect all upcoming matches from groups.

    Skips played matches using played_groups. Returns group matches
    with team_a/team_b orientation.

    Args:
        groups: Group definitions dict.

    Returns:
        List of match dicts.
    """
    matches = []
    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups
    if isinstance(groups_data, dict):
        for group_letter in groups_data:
            group = groups_data[group_letter]
            if isinstance(group, dict):
                for m in group.get("matches", []):
                    if isinstance(m, dict) and not m.get("winner"):
                        m["group"] = group_letter
                        matches.append(m)
    return matches


def _collect_matches_from_bracket(bracket: list[dict], played: dict) -> list[dict]:
    """Collect upcoming knockout matches from bracket.

    Only includes matches with resolved team names (string team_a/team_b).
    Unresolved slot references (dict placeholders) are skipped.

    Args:
        bracket: Bracket match list.
        played: Dict of played knockout matches.

    Returns:
        List of upcoming bracket match dicts.
    """
    matches = []
    for m in bracket:
        if isinstance(m, dict) and m.get("match_id", "") not in played:
            home = m.get("home", "")
            away = m.get("away", "")
            if not isinstance(home, str) or not isinstance(away, str):
                continue
            m = dict(m)
            m["team_a"] = home
            m["team_b"] = away
            matches.append(m)
    return matches


def _gather_signal_data(
    teams: dict,
    groups: dict,
    bracket: list[dict],
    odds_cache: dict | None,
    cb_cache: dict | None,
    form_cache: dict | None,
    lineup_cache: dict | None,
    xg_overrides: dict | None,
    played: dict,
    played_groups: dict | None = None,
    blend_params: dict | None = None,
) -> list[dict]:
    """Build per-match signal data for the match detail table.

    Args:
        teams: Team data dict with Elo ratings.
        groups: Group definitions dict.
        bracket: Bracket match list.
        odds_cache: Odds signal cache.
        cb_cache: CatBoost signal cache.
        form_cache: Form signal cache.
        lineup_cache: Lineup strength cache.
        xg_overrides: xG overrides dict.
        played: Played knockout matches.
        played_groups: Played group matches.
        blend_params: Optional result from calibrate_and_blend() for
                      correct Brier-weighted blend. Falls back to Elo
                      when unavailable.

    Returns:
        List of match data dicts with signals.
    """
    odds_m = (odds_cache or {}).get("matches", {})
    cb_m = (cb_cache or {}).get("matches", {})
    form_m = (form_cache or {}).get("matches", {})
    lineup_m = (lineup_cache or {}).get("matches", {})

    played_mids: set = set()
    for g in (played_groups or {}).values():
        if isinstance(g, dict):
            mid = g.get("match_id")
            if mid:
                played_mids.add(mid)

    all_matches = _collect_matches_from_groups(groups)
    all_matches += _collect_matches_from_bracket(bracket, played)

    result = []
    for match in all_matches:
        mid = match.get("match_id", "")
        t_a = match.get("team_a", "")
        t_b = match.get("team_b", "")
        if not mid or not t_a or not t_b:
            continue

        elo_prob = elo.expected_score(teams[t_a]["elo"], teams[t_b]["elo"]) if t_a in teams and t_b in teams else 0.5
        odds_prob = None
        if mid in odds_m and isinstance(odds_m[mid], dict):
            odds_prob = odds_m[mid].get("probability")
        cb_prob = None
        if mid in cb_m and isinstance(cb_m[mid], dict):
            cb_prob = cb_m[mid].get("probability")
        form_prob = None
        if mid in form_m and isinstance(form_m[mid], dict):
            form_prob = form_m[mid].get("probability")
        lineup_prob = None
        if mid in lineup_m and isinstance(lineup_m[mid], dict):
            lineup_prob = lineup_m[mid].get("probability")

        xg_val = None
        if xg_overrides and mid in xg_overrides:
            xg_val = xg_overrides[mid]

        # Compute blended from calibrate_and_blend match_probs when available
        # Falls back to Elo if no blend_params (same as simulation does).
        match_probs = (blend_params or {}).get("match_probs", {})
        blended = match_probs.get(mid, elo_prob)

        result.append({
            "match_id": mid,
            "team_a": t_a,
            "team_b": t_b,
            "signals": {
                "elo": elo_prob,
                "odds": odds_prob,
                "catboost": cb_prob,
                "form": form_prob,
                "lineup": lineup_prob,
                "xg": xg_val,
            },
            "blended": round(blended, 4),
        })

    return result


def _run_iteration(teams, groups, bracket, annex_c, played, played_groups, api_key, aliases, last_sim_time, last_request_time, prev_probs=None, seed=None, league_id=27, data_dir=None):
    """Run one fetch -> process -> simulate -> print cycle.

    Args:
        teams: Team data dict.
        groups: Group definitions dict (from groups.json).
        bracket: Bracket match list.
        annex_c: Annex C lookup table.
        played: Dict of played knockout matches.
        played_groups: Dict of played group matches (from played_groups.json).
        api_key: Football-Data.org API key.
        aliases: Team alias mappings.
        last_sim_time: Timestamp of last simulation.
        last_request_time: Timestamp of last API request.
        prev_probs: Previous iteration probabilities for delta display.
        seed: int or None. Passed to run_full_simulation() for reproducible Monte Carlo.
        league_id: BSD league ID for fetch filtering.
        data_dir: Per-league data directory. Defaults to constants.DATA_DIR.

    Returns (updated_last_sim_time, updated_last_request_time, probs).
    """
    played_groups = played_groups or {}

    # ── Periodic Elo sync check (D-02, D-03) ──
    if _state.elo_last_sync_time > 0:
        hours_since_sync = (time.time() - _state.elo_last_sync_time) / 3600
        if hours_since_sync >= ELO_SYNC_INTERVAL_HOURS:
            _run_elo_sync(teams, data_dir=data_dir)

    # ── Staleness warning (D-16) ──
    if _state.elo_last_sync_time > 0:
        staleness_hours = (time.time() - _state.elo_last_sync_time) / 3600
        if staleness_hours >= 24:
            print_staleness_warning(staleness_hours)

    # Rate limiter: ensure minimum interval since last API call
    now = time.time()
    if last_request_time > 0 and now - last_request_time < POLL_INTERVAL:
        _next_poll_sleep(POLL_INTERVAL - (now - last_request_time))

    now = time.time()

    # Hourly re-sim check: if >3600s since last sim with no new matches, refresh
    if last_sim_time > 0 and now - last_sim_time > 3600:
        output.print_auto_refresh()
        probs = run_full_simulation(teams, groups, bracket, annex_c, played, played_groups=played_groups, iterations=50000, seed=seed)
        # Group standings display per D-15: show on hourly refresh
        standings, third_ranked = _compute_group_display(groups, teams, played_groups)
        output.print_group_standings(standings, third_ranked)
        output.print_third_place_bubble(third_ranked)
        output.print_probability_table(probs)
        return now, last_request_time, probs

    # Fetch matches from API
    last_request_time = time.time()
    raw = fetch_raw_matches(api_key, api_url=constants.api_url_for_league(league_id), league_id=league_id)

    # Process new matches
    new_matches = []
    if raw:
        try:
            new_matches = process_matches(raw, teams, bracket, aliases, set(played.keys()))
        except Exception as e:
            print(f"Warning: Fetcher error: {e}", file=sys.stderr)

    # Update Elo and state for new knockout matches
    if new_matches:
        for m in new_matches:
            output.print_match_alert(m)
            elo_updates = elo.apply_elo_update(m, teams)
            output.print_elo_changes(elo_updates)
            played[m["match_id"]] = m
            state.save_teams(teams, data_dir)
            state.save_played(played, data_dir)
    else:
        output.print_heartbeat()

    # Process new group matches (INTG-01)
    new_group_matches = []
    if raw:
        try:
            played_bsd_event_ids: set[str] = set()
            new_group_matches = process_group_matches(
                raw, teams, groups, aliases,
                set(played_groups.keys()), played_bsd_event_ids,
            )
        except Exception as e:
            print(f"Warning: Group fetcher error: {e}", file=sys.stderr)

    if new_group_matches:
        for m in new_group_matches:
            output.print_match_alert(m)
            elo_updates = elo.apply_elo_update(m, teams)
            output.print_elo_changes(elo_updates)
            played_groups[m["match_id"]] = m
            state.save_played_groups(played_groups, data_dir)
        state.save_teams(teams, data_dir)

    # ── Per-iteration prediction_history creation for new matches (Defect B Gap 2) ──
    all_new = list(new_matches or []) + list(new_group_matches or [])
    if all_new:
        try:
            existing_mids = set()
            existing_history = state.load_prediction_history(data_dir)
            if existing_history:
                existing_mids = {e.get("match_id", "") for e in existing_history}
            now_iso = datetime.now(timezone.utc).isoformat()
            for m in all_new:
                mid = m.get("match_id", "")
                if not mid or mid in existing_mids:
                    continue
                t_a = m.get("team_a", "")
                t_b = m.get("team_b", "")
                if t_a not in teams or t_b not in teams:
                    continue
                p_a = elo.expected_score(teams[t_a]["elo"], teams[t_b]["elo"])
                winner = m.get("winner")
                if winner is None:
                    actual_a = 0.5
                elif winner == t_a:
                    actual_a = 1.0
                elif winner == t_b:
                    actual_a = 0.0
                else:
                    continue
                entry = {
                    "match_id": mid,
                    "timestamp": now_iso,
                    "team_a": t_a,
                    "team_b": t_b,
                    "actual": actual_a,
                    "signals": {
                        "elo": {
                            "probability": round(p_a, 4),
                            "version": "v1",
                            "timestamp": now_iso,
                            "available": True,
                        }
                    },
                }
                state.append_prediction_history(entry, data_dir)
        except Exception:
            print("Warning: Failed to create prediction_history entries for new matches", file=sys.stderr)

    # ── Signal cache refresh, merge into prediction_history ──
    signal_warnings: list[str] = []

    # Refresh odds from existing events (no extra API call — reuses raw data)
    odds_cache = state.load_signal_cache(ODDS_CACHE_FILE, data_dir)
    if raw and not state.is_cache_valid(odds_cache, ODDS_CACHE_TTL_HOURS):
        try:
            odds_cache = fetch_and_cache_odds(
                api_key, raw, aliases, groups, ODDS_CACHE_TTL_HOURS
            )
            state.save_signal_cache(odds_cache, ODDS_CACHE_FILE, data_dir)
        except Exception as e:
            print(f"Warning: Odds fetch failed: {e}", file=sys.stderr)
            if not odds_cache or not odds_cache.get("matches"):
                signal_warnings.append("Market odds unavailable — no cached data")

    # Refresh CatBoost (dedicated API call only if cache expired)
    cb_cache = state.load_signal_cache(CATBOOST_CACHE_FILE, data_dir)
    if not state.is_cache_valid(cb_cache, CATBOOST_CACHE_TTL_HOURS):
        try:
            cb_cache = fetch_and_cache_catboost(
                api_key, aliases, groups, bracket, CATBOOST_CACHE_TTL_HOURS,
                league_id=league_id,
            )
            state.save_signal_cache(cb_cache, CATBOOST_CACHE_FILE, data_dir)
        except Exception as e:
            print(f"Warning: CatBoost fetch failed: {e}", file=sys.stderr)
            if not cb_cache or not cb_cache.get("matches"):
                signal_warnings.append("CatBoost predictions unavailable — no cached data")

    # ── Build xG overrides dict from CatBoost cache (Phase 18) ──
    xg_overrides: dict[str, tuple[float, float]] = {}
    if cb_cache and cb_cache.get("matches"):
        for mid, entry in cb_cache["matches"].items():
            home_xg = entry.get("expected_home_goals")
            away_xg = entry.get("expected_away_goals")
            if home_xg is not None and away_xg is not None:
                xg_overrides[mid] = (home_xg, away_xg)

    # ── Context signal computation: form + lineup (Phase 15) ──
    form_cache = {}
    try:
        form_cache = compute_form_signal(
            teams, groups, bracket=bracket,
            played=played, played_groups=played_groups,
        )
        state.save_signal_cache(form_cache, FORM_CACHE_FILE, data_dir)
    except Exception as e:
        print(f"Warning: Form signal computation failed: {e}", file=sys.stderr)
        if not form_cache or not form_cache.get("matches"):
            signal_warnings.append("Form signal unavailable — no cached data")

    lineup_cache = {}
    try:
        lineup_cache = compute_lineup_signal(groups, bracket=bracket)
        state.save_signal_cache(lineup_cache, LINEUP_CACHE_FILE, data_dir)
    except Exception as e:
        print(f"Warning: Lineup signal computation failed: {e}", file=sys.stderr)
        if not lineup_cache or not lineup_cache.get("matches"):
            signal_warnings.append("Lineup strength unavailable — no cached data")

    # ══ Architecture Q4+Q5: Capture pre-mutation state ══
    # Capture prev_history for data_version change detection.
    # Must happen BEFORE _merge_signals_into_history().
    _prev_history = state.load_prediction_history(data_dir)
    _prev_cal_params = state.load_calibration_params(data_dir)

    # Merge signal cache data into prediction_history entries
    _merge_signals_into_history(data_dir=data_dir)

    # ── Calibrate, blend, inject into simulation (Phase 14) ──
    blend_params = _run_calibrate_and_blend(
        teams, groups, bracket, odds_cache, cb_cache,
        form_cache=form_cache, lineup_cache=lineup_cache,
        data_dir=data_dir,
    )

    # ── Attach version IDs to prediction_history entries (D-05) ──
    # Tracks which data/model/run produced each entry's state.
    # Only sets version on entries that don't yet have it (Pitfall 2: avoid bloat).
    # Version IDs are entry-level attributes, not signal-level (Pitfall 1).
    try:
        from src.governance import _maybe_update_versions
        from src.state import load_versions, save_versions, load_prediction_history, save_prediction_history, load_calibration_params

        current_versions = load_versions(data_dir)
        new_cal_params = load_calibration_params(data_dir)
        calibration_changed = _prev_cal_params != new_cal_params  # Architecture Q5

        # Determine signal keys from current prediction_history
        ph = load_prediction_history(data_dir)
        ph_signal_keys = sorted(
            k for entry in ph
            if isinstance(entry.get("signals"), dict)
            for k in entry["signals"]
        ) if ph else []

        updated_versions = _maybe_update_versions(
            old_versions=current_versions,
            prev_history=_prev_history or [],
            new_history=ph,
            prev_signal_keys=list(set(
                k for entry in (_prev_history or [])
                if isinstance(entry.get("signals"), dict)
                for k in entry["signals"]
            )),
            new_signal_keys=list(set(ph_signal_keys)),
            calibration_changed=calibration_changed,
        )
        save_versions(updated_versions, data_dir)

        # Attach version IDs to entries that don't have them yet
        devices = load_prediction_history(data_dir)
        modified = False
        for entry in devices:
            if "data_version" not in entry:
                entry["data_version"] = updated_versions.get("data_version", "D0")
                entry["model_version"] = updated_versions.get("model_version", "M0")
                entry["run_version"] = updated_versions.get("run_version", "R0")
                modified = True
        if modified:
            save_prediction_history(devices, data_dir)
    except Exception as e:
        print(f"Version tracking failed: {e}", file=sys.stderr)

    # Count unavailable matches per signal for aggregated warnings (D-09)
    odds_matches = odds_cache.get("matches", {}) if odds_cache else {}
    odds_unavailable = sum(
        1 for m in odds_matches.values() if not m.get("available", False)
    )
    if odds_unavailable:
        signal_warnings.append(
            f"⚠ Market odds unavailable for {odds_unavailable} match(es)"
        )
    cb_matches = cb_cache.get("matches", {}) if cb_cache else {}
    cb_unavailable = sum(
        1 for m in cb_matches.values() if not m.get("available", False)
    )
    if cb_unavailable:
        signal_warnings.append(
            f"⚠ CatBoost predictions unavailable for {cb_unavailable} match(es)"
        )

    form_matches = form_cache.get("matches", {}) if form_cache else {}
    form_unavailable = sum(
        1 for m in form_matches.values() if not m.get("available", False)
    )
    if form_unavailable:
        signal_warnings.append(
            f"⚠ Form signal unavailable for {form_unavailable} match(es)"
        )
    lineup_matches = lineup_cache.get("matches", {}) if lineup_cache else {}
    lineup_unavailable = sum(
        1 for m in lineup_matches.values() if not m.get("available", False)
    )
    if lineup_unavailable:
        signal_warnings.append(
            f"⚠ Lineup strength unavailable for {lineup_unavailable} match(es)"
        )

    # Print aggregated warnings once per poll cycle (D-09)
    for warning in signal_warnings:
        print(warning)

    # ── Model Governance (Phase 16) ──
    if _should_run_gov():
        try:
            from src.governance import _run_governance
            from src.state import load_versions, load_prediction_history
            from src.output import print_governance_dashlet

            gov_entries = load_prediction_history(data_dir)
            gov_versions = load_versions(data_dir)
            gov_signal_keys = sorted(
                k for entry in gov_entries
                if isinstance(entry.get("signals"), dict)
                for k in entry["signals"]
            ) if gov_entries else ["elo", "market_odds", "catboost", "form", "lineup_strength"]

            snapshot = _run_governance(
                entries=gov_entries,
                versions=gov_versions,
                signal_keys=list(set(gov_signal_keys)),
                blend_weights=blend_params.get("blend_weights", {}) if blend_params else {},
                data_dir=data_dir,
            )
            drift_details = snapshot.get("drift_details") or []
            drift_results_dict: dict[str, dict] = {}
            for d in drift_details:
                drift_results_dict[d.get("signal", "?")] = d
            print_governance_dashlet(
                versions=gov_versions,
                status=snapshot.get("drift_status", "HEALTHY").replace("_", " "),
                n_matches=len(gov_entries),
                per_signal_brier=snapshot.get("per_signal_brier", {}),
                blend_weights=blend_params.get("blend_weights", {}) if blend_params else {},
                drift_results=drift_results_dict if drift_results_dict else None,
            )
            _state.last_gov_time = time.time()
        except Exception as e:
            print(f"Governance check failed: {e}", file=sys.stderr)

    # D-15: group standings display behavior
    #   - New group match ingested → show
    #   - Hourly refresh → show (handled above in hourly block)
    #   - Regular heartbeat (no new matches) → skip
    show_group_display = bool(new_group_matches)

    # Simulate and print results
    sim_start = time.time()
    probs = run_full_simulation(teams, groups, bracket, annex_c, played, played_groups=played_groups, iterations=50000, seed=seed, blend_params=blend_params, xg_overrides=xg_overrides)
    sim_elapsed = time.time() - sim_start
    output.print_simulation_duration(sim_elapsed)

    # Group standings (D-15: only on new matches or hourly, skip on heartbeat)
    if show_group_display:
        standings, third_ranked = _compute_group_display(groups, teams, played_groups)
        output.print_group_standings(standings, third_ranked)
        output.print_third_place_bubble(third_ranked)

    output.print_probability_table(probs, prev_probs)
    if _state.ai_preview_enabled:
        output.print_ai_previews(played, played_groups)
    if prev_probs is not None:
        output.print_delta_summary(probs, prev_probs)

    # Probability log snapshot (Phase 20)
    try:
        snapshot = {"timestamp": datetime.now(timezone.utc).isoformat(), "probabilities": probs}
        state.append_probability_log(snapshot, data_dir=data_dir)
    except Exception:
        import sys as _sys
        print("Warning: Failed to save probability log snapshot", file=_sys.stderr)

    # ── Match detail table / focus card display (Phase 20-03) ──
    if _state.match_detail_enabled:
        try:
            matches_data = _gather_signal_data(
                teams, groups, bracket,
                odds_cache, cb_cache, form_cache, lineup_cache,
                xg_overrides, played, played_groups,
                blend_params=blend_params,
            )
            if _state.match_detail_enabled == "table":
                output.print_match_detail_table(matches_data, _state.prev_signal_data)
            else:
                target_mid = _state.match_detail_enabled
                for md in matches_data:
                    if md["match_id"] == target_mid:
                        # Find match entry for context/stats if played
                        match_entry = None
                        if target_mid in played:
                            match_entry = played[target_mid]
                        elif target_mid in (played_groups or {}):
                            match_entry = (played_groups or {}).get(target_mid)
                        # Build prev_signals for delta
                        prev_data = None
                        if _state.prev_signal_data:
                            prev_data = next((d for d in _state.prev_signal_data if d["match_id"] == target_mid), None)
                        focus_data = dict(md)
                        if prev_data:
                            focus_data["prev_signals"] = prev_data["signals"]
                            focus_data["blended_delta"] = md["blended"] - prev_data["blended"]
                        output.print_focus_card(focus_data, match_entry)
                        break
            _state.prev_signal_data = matches_data
        except Exception:
            import sys as _sys2
            print("Warning: Failed to display match detail table", file=_sys2.stderr)

    return time.time(), last_request_time, probs


def validate_api_key() -> str:
    """Validate BSD_API_KEY env var is set and returns a non-401 status.

    Returns:
        str: The API key value.

    Exits 1 if key is missing or returns HTTP 401.
    """
    api_key = os.environ.get("BSD_API_KEY")
    if not api_key:
        output.print_error("BSD_API_KEY not set. Get a free key at https://sports.bzzoiro.com/register/")
        sys.exit(1)

    import requests
    try:
        resp = requests.get(
            "https://sports.bzzoiro.com/api/leagues/",
            headers={"Authorization": f"Token {api_key}"},
            timeout=10,
        )
        if resp.status_code == 401:
            output.print_error("Invalid BSD_API_KEY (HTTP 401). Check your key at https://sports.bzzoiro.com/account/")
            sys.exit(1)
        if resp.status_code != 200:
            print(f"Warning: API availability check returned {resp.status_code}, continuing...", file=sys.stderr)
    except Exception:
        print("Warning: API availability check failed, continuing...", file=sys.stderr)

    return api_key


def _migrate_legacy_data(data_dir: Path | str, league_id: int) -> None:
    """One-shot non-destructive migration from data/ to data/{league_id}/.

    Only runs when league_id == 27 (legacy layout). Copies league-scoped
    state files from data/ to data/27/ if data/27/played.json doesn't exist.
    Original data/*.json files are never deleted (D-07).

    Args:
        data_dir: Base data directory (constants.DATA_DIR, typically data/).
        league_id: Resolved league ID to migrate to.
    """
    import shutil

    if league_id != 27:
        return  # Only migrate from legacy 27 layout

    # Ensure Path for / operator (tests may pass str)
    data_dir = Path(data_dir) if isinstance(data_dir, str) else data_dir
    target_dir = data_dir / str(league_id)
    guard_file = target_dir / "played.json"
    if guard_file.exists():
        return  # Idempotent: already migrated (D-08)

    league_scoped_files: list[str] = [
        "played.json", "played_groups.json", "teams.json",
        "predictions_ledger.json", "prediction_history.json",
        "catboost_cache.json", "odds_cache.json", "form_cache.json",
        "lineup_cache.json", "elo_applied.json", "elo_update_log.json",
        "calibration_params.json", "versions.json",
        "probability_log.json",
    ]

    target_dir.mkdir(parents=True, exist_ok=True)
    migrated = 0
    for filename in league_scoped_files:
        src = data_dir / filename
        if src.exists():
            shutil.copy2(src, target_dir / filename)
            migrated += 1

    # Also migrate runs/ subdirectory
    src_runs = data_dir / "runs"
    if src_runs.exists():
        dst_runs = target_dir / "runs"
        dst_runs.mkdir(exist_ok=True)
        for f in src_runs.iterdir():
            if f.is_file():
                shutil.copy2(f, dst_runs / f.name)

    if migrated:
        logging.getLogger(__name__).info(
            "Migrated %d files from data/ to data/%d/", migrated, league_id
        )


def _merge_probability_log(data_dir: Path | str, league_data_dir: Path | str) -> None:
    """Merge root probability_log history into league data dir (data/27/ canonical).

    For existing installs: root entries that don't exist in the league dir
    (deduplicated by ISO timestamp) are appended to the league copy. Root is
    never modified. Idempotent on subsequent runs — only new (by timestamp)
    root entries are merged.

    Args:
        data_dir: Base data directory (constants.DATA_DIR, typically data/).
        league_data_dir: Per-league data directory (data/<league_id>/).
    """
    from src.constants import PROBABILITY_LOG_FILE

    root_path = Path(data_dir) / PROBABILITY_LOG_FILE
    league_path = Path(league_data_dir) / PROBABILITY_LOG_FILE

    if not root_path.exists():
        return

    try:
        with open(root_path, encoding="utf-8") as f:
            root_log: list[dict] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    if not root_log:
        return

    if league_path.exists():
        try:
            with open(league_path, encoding="utf-8") as f:
                league_log: list[dict] = json.load(f)
        except (json.JSONDecodeError, OSError):
            league_log = []
    else:
        league_log = []

    existing_timestamps = {e["timestamp"] for e in league_log if isinstance(e, dict) and "timestamp" in e}
    new_entries = [e for e in root_log if isinstance(e, dict) and e.get("timestamp") not in existing_timestamps]

    if not new_entries:
        return

    league_log.extend(new_entries)

    import tempfile
    league_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(league_path.parent), prefix="prob_log.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(league_log, f, indent=2)
        os.replace(tmp, str(league_path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    logging.getLogger(__name__).info(
        "Merged %d probability log entries from data/ to data/%d/",
        len(new_entries), 27,
    )


def _resolve_league_id(args: argparse.Namespace) -> tuple[int, Path]:
    """Resolve league_id with precedence: CLI --league > config.json > default 27.

    Args:
        args: Parsed CLI arguments from _parse_args().

    Returns:
        Tuple of (league_id: int, league_data_dir: Path).
    """
    # Ensure DATA_DIR is a Path for parent access (tests may set str)
    base_data_dir = Path(constants.DATA_DIR) if isinstance(constants.DATA_DIR, str) else constants.DATA_DIR
    config_path = base_data_dir.parent / "config.json"
    league_id = constants.DEFAULT_LEAGUE_ID  # 27

    # 1. Load config.json if it exists
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            league_id = int(config.get("league_id", constants.DEFAULT_LEAGUE_ID))
        except (json.JSONDecodeError, ValueError, TypeError):
            logging.warning(
                "Corrupt config.json at %s, falling back to league %d",
                config_path, constants.DEFAULT_LEAGUE_ID,
            )
            league_id = constants.DEFAULT_LEAGUE_ID
    else:
        # Auto-create config.json with default (D-11)
        # Use atomic write pattern: write to temp, then rename
        import tempfile
        config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_path.parent),
            prefix="config.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"league_id": constants.DEFAULT_LEAGUE_ID}, f, indent=2)
            os.replace(tmp_path, str(config_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # 2. CLI override (D-10: CLI > config.json > 27)
    if args.league is not None:
        league_id = args.league

    # Per RECOMMENDATION: do NOT persist CLI --league into config.json.
    # Config.json is for persisted preference; CLI is for one-off override.

    league_data_dir = base_data_dir / str(league_id)
    return league_id, league_data_dir


def main() -> None:
    """Load state, then enter continuous polling loop until signal."""
    args = _parse_args()

    _state.ai_preview_enabled = args.ai_preview
    _state.match_detail_enabled = args.match_detail

    # Handle --list-leagues early: print catalog and exit (D-02)
    if args.list_leagues:
        for lid, name in sorted(constants.LEAGUES.items()):
            print(f"{lid:>4}: {name}")
        sys.exit(0)

    # Resolve league_id with precedence: CLI > config.json > 27
    league_id, league_data_dir = _resolve_league_id(args)
    # Windows Console Host ANSI initialization (Python 3.10/3.11 quirk)
    if sys.platform == "win32":
        os.system("")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    load_dotenv()

    try:
        # ── One-time migration (D-05 through D-08) ──
        _migrate_legacy_data(Path(constants.DATA_DIR), league_id)

        # ── Probability log merge (D-20: data/27 is canonical) ──
        # Merge any root entries into data/27/ that don't already exist there
        # (by timestamp). Idempotent. Root copy becomes stale after merge.
        _merge_probability_log(Path(constants.DATA_DIR), league_data_dir)

        teams = state.load_teams(data_dir=league_data_dir)            # per-league
        bracket = state.load_bracket()                                 # shared — no data_dir
        played = state.load_played(data_dir=league_data_dir)           # per-league
        played_groups = state.load_played_groups(data_dir=league_data_dir)  # per-league
        groups = state.load_groups()                                   # shared
        annex_c = state.load_annex_c()                                 # shared
        api_key = validate_api_key()
        aliases = state.load_aliases()                                 # shared (team_aliases)

        # ── Historical catch-up: fetch all finished matches from tournament
        #     start to today. Runs unconditionally on every startup — existing
        #     match_id dedup in process_group_matches prevents re-ingestion.
        #     Elo updates are applied chronologically with (completed_at, match_id)
        #     ordering, guarded by elo_applied_ids to prevent double-counting.
        __elo_applied = state.load_elo_applied(data_dir=league_data_dir)
        played_groups, played, __elo_applied = _run_historical_catch_up(
            api_key, teams, groups, bracket, annex_c, aliases,
            played_groups, played, elo_applied=__elo_applied,
            league_id=league_id, data_dir=league_data_dir,
        )
        state.save_elo_applied(__elo_applied, data_dir=league_data_dir)

        # ── Historical draw backfill ──
        # One-shot: replays all historical draws through fixed Elo pipeline (D-14, D-15)
        __elo_applied = _run_draw_backfill(teams, played, played_groups, __elo_applied,
                                           data_dir=league_data_dir)

        # ── Baseline metrics ──
        # Record one-shot Brier/log-loss baseline for Phase 12b (D-18)
        _record_eval_baseline(teams, played, played_groups,
                              data_dir=league_data_dir)

        # ── Prediction history migration (one-shot, before signal fetch) ──
        n_migrated = state.migrate_prediction_history(data_dir=league_data_dir)
        if n_migrated:
            print(f"Prediction history migrated: {n_migrated} entries to compound format")

        # ── Seed CatBoost cache at startup (dedicated API call) ──
        try:
            cb_cache = fetch_and_cache_catboost(
                api_key, aliases, groups, bracket, CATBOOST_CACHE_TTL_HOURS,
                league_id=league_id,
            )
            state.save_signal_cache(cb_cache, CATBOOST_CACHE_FILE, league_data_dir)
        except Exception as e:
            print(f"Warning: initial CatBoost fetch failed: {e}", file=sys.stderr)

        # ── Merge CatBoost into prediction_history — even if cache is partial ──
        _merge_signals_into_history(data_dir=league_data_dir)

        # ── Warm Poisson base rate cache (V2-09) ──
        try:
            from src.blender import compute_poisson_base_rate
            rate = compute_poisson_base_rate()
            if rate != constants.EXPECTED_GOALS_BASE_RATE:
                print(f"Poisson base rate: {rate:.4f} (from historical data)")
            else:
                print(f"Poisson base rate: {constants.EXPECTED_GOALS_BASE_RATE:.2f} (default)")
        except Exception:
            pass

        # ── Startup Elo sync per D-01, D-18 ──
        # Runs after historical catch-up (Pitfall 7: catch-up first, then sync)
        # and before the first simulation. Always fetches fresh Elo values.
        _run_elo_sync(teams, data_dir=league_data_dir)

        # Apply --no-color before any console output (D-05)
        if args.no_color:
            output.NO_COLOR = True

        output.print_header(teams, bracket, played, aliases, groups, annex_c)

        # ── Governance startup ──
        from src.state import load_versions, load_prediction_history
        from src.governance import _run_governance
        from src.output import print_governance_dashlet

        gov_entries = load_prediction_history(data_dir=league_data_dir)
        gov_versions = load_versions(data_dir=league_data_dir)
        startup_snapshot = _run_governance(
            entries=gov_entries,
            versions=gov_versions,
            signal_keys=["elo", "market_odds", "catboost", "form", "lineup_strength"],
            blend_weights={},
            startup=True,
            teams=teams,
            data_dir=league_data_dir,
        )
        startup_drift = startup_snapshot.get("drift_details") or []
        startup_drift_dict: dict[str, dict] = {}
        for d in startup_drift:
            startup_drift_dict[d.get("signal", "?")] = d
        print_governance_dashlet(
            versions=gov_versions,
            status=startup_snapshot.get("drift_status", "COLD_START").replace("_", " "),
            n_matches=len(gov_entries),
            per_signal_brier=startup_snapshot.get("per_signal_brier", {}),
            blend_weights={},
            drift_results=startup_drift_dict if startup_drift_dict else None,
            backtest_summary=startup_snapshot.get("backtest_summary"),
        )
        _state.last_gov_time = time.time()

        # ── --once mode: single iteration, immediate exit (D-01, D-02) ──
        if args.once:
            _run_iteration(
                teams, groups, bracket, annex_c, played, played_groups, api_key, aliases,
                last_sim_time=0.0, last_request_time=0.0,
                prev_probs=None, seed=args.seed,
                league_id=league_id, data_dir=league_data_dir,
            )
            sys.exit(0)

        # Register signal handlers
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, _signal_handler)  # Windows CTRL_BREAK_EVENT

        last_sim_time = 0.0
        last_request_time = 0.0
        prev_probs = None

        # First poll fires immediately
        last_sim_time, last_request_time, prev_probs = _run_iteration(
            teams, groups, bracket, annex_c, played, played_groups, api_key, aliases,
            last_sim_time, last_request_time, prev_probs,
            seed=args.seed, league_id=league_id, data_dir=league_data_dir,
        )

        # Continuous polling loop
        while _state.running:
            _next_poll_sleep(POLL_INTERVAL)
            if not _state.running:
                break
            last_sim_time, last_request_time, prev_probs = _run_iteration(
                teams, groups, bracket, annex_c, played, played_groups, api_key, aliases,
                last_sim_time, last_request_time, prev_probs,
                seed=args.seed, league_id=league_id, data_dir=league_data_dir,
            )

        # Shutdown path
        shutdown_odds = state.load_signal_cache(ODDS_CACHE_FILE, league_data_dir)
        shutdown_cb = state.load_signal_cache(CATBOOST_CACHE_FILE, league_data_dir)
        shutdown_blend = _run_calibrate_and_blend(
            teams, groups, bracket, shutdown_odds, shutdown_cb,
            data_dir=league_data_dir,
        )
        final_probs = run_full_simulation(teams, groups, bracket, annex_c, played, played_groups=played_groups, iterations=50000, seed=args.seed, blend_params=shutdown_blend)
        output.print_shutdown_banner(final_probs)

        state.save_teams(teams, data_dir=league_data_dir)
        state.save_played(played, data_dir=league_data_dir)
        state.save_played_groups(played_groups, data_dir=league_data_dir)

    except ValueError as e:
        output.print_error(f"Data error: {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        output.print_error(f"File not found: {e}. Run with valid state files.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        output.print_error(f"Corrupt JSON file: {e}. Check data/ directory.")
        sys.exit(1)


if __name__ == "__main__":
    main()
