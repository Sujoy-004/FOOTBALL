"""Orchestration engine — reusable functions extracted from the CLI layer.

All print() calls are stripped. Functions return structured dicts
for the web layer to format.
"""

import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import constants, elo, elo_sync, state
from src.constants import (
    ELO_SYNC_INTERVAL_HOURS, POLL_INTERVAL,
    ODDS_CACHE_TTL_HOURS, CATBOOST_CACHE_TTL_HOURS, ODDS_CACHE_FILE, CATBOOST_CACHE_FILE,
    FORM_CACHE_FILE, LINEUP_CACHE_FILE,
    DEFENSIVE_CACHE_FILE, MANAGER_EFFECT_CACHE_FILE, AVAILABILITY_CACHE_FILE,
    MANAGER_CACHE_FILE, MANAGER_CACHE_TTL_HOURS,
    AVAILABILITY_CACHE_TTL_HOURS,
    ELO_ODDS_CACHE_FILE, TEAM_SYNERGY_CACHE_FILE, ROLLING_FORM_CACHE_FILE,
    SQUAD_VALUE_CACHE_FILE, REST_DAYS_CACHE_FILE,
)
from football_core.signal import PredictionContext, BlendedPrediction
from src.fetcher import build_historic_url, fetch_raw_matches, process_group_matches, process_matches
from src.knockout import resolve_knockout_slot_teams, run_full_simulation
from src.predictors.odds import fetch_and_cache_odds
from src.predictors.catboost import fetch_and_cache_catboost
from src.predictors.form import compute_form_signal
from src.predictors.lineup import compute_lineup_signal

logger = logging.getLogger(__name__)


def build_signal_engine(
    odds_cache: dict | None = None,
    cb_cache: dict | None = None,
    form_cache: dict | None = None,
    lineup_cache: dict | None = None,
    defensive_cache: dict | None = None,
    manager_cache: dict | None = None,
    availability_cache: dict | None = None,
    elo_odds_cache: dict | None = None,
    team_synergy_cache: dict | None = None,
    rolling_form_cache: dict | None = None,
    squad_value_cache: dict | None = None,
    rest_days_cache: dict | None = None,
    weights: dict[str, float] | None = None,
    weights_path: str | None = None,
) -> Any:
    """Build an EnsembleEngine with all 13 WC signals wrapping their caches."""
    from football_core.blender import EnsembleEngine
    from football_core.signal import Signal, SignalOutput, PredictionContext

    _caches = {
        "market_odds": (odds_cache or {}).get("matches", {}),
        "catboost": (cb_cache or {}).get("matches", {}),
        "form": (form_cache or {}).get("matches", {}),
        "lineup_strength": (lineup_cache or {}).get("matches", {}),
        "defensive_quality": (defensive_cache or {}).get("matches", {}),
        "manager_effect": (manager_cache or {}).get("matches", {}),
        "availability": (availability_cache or {}).get("matches", {}),
        "elo_odds": (elo_odds_cache or {}).get("matches", {}),
        "team_synergy": (team_synergy_cache or {}).get("matches", {}),
        "rolling_form": (rolling_form_cache or {}).get("matches", {}),
        "squad_value": (squad_value_cache or {}).get("matches", {}),
        "rest_days": (rest_days_cache or {}).get("matches", {}),
    }

    class _CacheSignal(Signal):
        name: str = ""

        def __init__(self, name: str, cache: dict) -> None:
            self.name = name
            self._cache = cache

        def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
            mid = match.get("match_id", "")
            entry = self._cache.get(mid) if self._cache else None
            if entry:
                prob = entry.get("probability", 1 / 3)
                draw_prob = 0.25
                return SignalOutput(prob, draw_prob, 1.0 - prob - draw_prob)
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

    class _EloSignal(Signal):
        name: str = "elo"

        def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
            from football_core.elo import expected_score
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")
            elo_ratings = context.elo_ratings or {}
            home = elo_ratings.get(team_a, 1500)
            away = elo_ratings.get(team_b, 1500)
            home_prob = expected_score(home, away, home_advantage=100)
            draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35
            away_prob = 1.0 - home_prob - draw_prob
            return SignalOutput(home_prob, draw_prob, away_prob)

    signals: list[Signal] = [_EloSignal()]
    for name, cache in _caches.items():
        signals.append(_CacheSignal(name, cache))

    if weights is not None:
        return EnsembleEngine(signals, weights=weights)
    if weights_path is not None:
        return EnsembleEngine(signals, weights_path=weights_path)
    return EnsembleEngine(signals)


def merge_signals_into_history(data_dir: Path | str | None = None) -> None:
    """Merge signal cache data into prediction_history entries."""
    history = state.load_prediction_history(data_dir)
    if not history:
        return

    _cache_files: list[tuple[str, str]] = [
        ("odds_cache.json", "market_odds"),
        ("catboost_cache.json", "catboost"),
        ("form_cache.json", "form"),
        ("lineup_cache.json", "lineup_strength"),
        ("defensive_cache.json", "defensive_quality"),
        ("manager_effect_cache.json", "manager_effect"),
        ("availability_cache.json", "availability"),
        ("elo_odds_cache.json", "elo_odds"),
        ("team_synergy_cache.json", "team_synergy"),
        ("rolling_form_cache.json", "rolling_form"),
        ("squad_value_cache.json", "squad_value"),
        ("rest_days_cache.json", "rest_days"),
    ]

    caches: dict[str, dict] = {}
    for fname, sname in _cache_files:
        cache = state.load_signal_cache(fname, data_dir)
        if cache and cache.get("matches"):
            caches[sname] = cache["matches"]

    if not caches:
        return

    changed = False
    for entry in history:
        signals = entry.get("signals", {})
        if not isinstance(signals, dict):
            continue
        mid = entry.get("match_id", "")
        for sname, matches in caches.items():
            if sname not in signals and mid in matches:
                signals[sname] = dict(matches[mid])
                changed = True
    if changed:
        state.save_prediction_history(history, data_dir)


def run_calibrate_and_blend(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    odds_cache: dict,
    cb_cache: dict,
    form_cache: dict | None = None,
    lineup_cache: dict | None = None,
    defensive_cache: dict | None = None,
    manager_cache: dict | None = None,
    availability_cache: dict | None = None,
    elo_odds_cache: dict | None = None,
    team_synergy_cache: dict | None = None,
    rolling_form_cache: dict | None = None,
    squad_value_cache: dict | None = None,
    rest_days_cache: dict | None = None,
    data_dir: Path | str | None = None,
) -> dict | None:
    """Orchestrate calibration + blending via blender.calibrate_and_blend().

    Returns blend_params dict (for simulation) or None (graceful degradation).
    """
    try:
        from src.blender import calibrate_and_blend
        from src.state import load_prediction_history, save_calibration_params

        history = load_prediction_history(data_dir)
        if not history:
            return None

        elo_ratings = {name: data["elo"] for name, data in teams.items()}
        signal_keys = ["elo", "market_odds", "catboost", "form", "lineup_strength"]
        if defensive_cache:
            signal_keys.append("defensive_quality")
        if manager_cache:
            signal_keys.append("manager_effect")
        if availability_cache:
            signal_keys.append("availability")
        signal_keys.extend(["elo_odds", "team_synergy", "rolling_form", "squad_value", "rest_days"])

        blend_params = calibrate_and_blend(
            history=history,
            signal_keys=signal_keys,
            elo_ratings=elo_ratings,
            groups_data=groups,
            bracket_data=bracket,
            odds_cache=odds_cache or {},
            cb_cache=cb_cache or {},
            form_cache=form_cache or {},
            lineup_cache=lineup_cache or {},
            defensive_cache=defensive_cache or {},
            manager_cache=manager_cache or {},
            availability_cache=availability_cache or {},
            elo_odds_cache=elo_odds_cache or {},
            team_synergy_cache=team_synergy_cache or {},
            rolling_form_cache=rolling_form_cache or {},
            squad_value_cache=squad_value_cache or {},
            rest_days_cache=rest_days_cache or {},
        )
        if blend_params and blend_params.get("calibration_params"):
            save_calibration_params(blend_params["calibration_params"], data_dir)
        return blend_params
    except Exception:
        return None


def run_elo_sync(
    teams: dict[str, dict],
    elo_last_sync_time: float = 0.0,
    data_dir: Path | str | None = None,
) -> tuple[float, list | None]:
    """Run Elo sync from eloratings.net with cache fallback.

    Returns:
        (updated_elo_last_sync_time, corrections_or_None)
    """
    start = time.time()
    corrections = elo_sync.sync_elo_from_eloratings(teams, data_dir=data_dir)
    elapsed = time.time() - start

    if corrections is None:
        cache = state.load_eloratings_cache(data_dir)
        if not cache and elo_last_sync_time == 0.0:
            logger.warning(
                "Cannot initialize Elo ratings — eloratings.net unreachable "
                "and no cached values exist. Using teams.json initial values."
            )
        return elo_last_sync_time, None

    new_sync_time = time.time()

    flagged = []
    if corrections:
        flagged = [c for c in corrections if c.get("reason") == "overwrite_drift_gt_30"]

    return new_sync_time, corrections


def historical_catch_up(
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
) -> tuple[dict[str, dict], dict[str, dict], set[str], int]:
    """Fetch finished matches from tournament start, ingest unplayed ones.

    Returns (updated_played_groups, updated_played, updated_elo_applied, n_ingested).
    """
    historic_url = build_historic_url(league_id=league_id)
    raw = fetch_raw_matches(api_key, api_url=historic_url, league_id=league_id)
    if not raw:
        return played_groups, played, elo_applied or set(), 0

    if elo_applied is None:
        elo_applied = set()

    total_new = 0
    new_matches_all: list[dict] = []

    played_bsd_event_ids: set[str] = set()
    new_group = process_group_matches(
        raw, teams, groups, aliases,
        set(played_groups.keys()), played_bsd_event_ids,
    )
    if new_group:
        for m in new_group:
            played_groups[m["match_id"]] = m
        state.save_played_groups(played_groups, data_dir)
        new_matches_all.extend(new_group)
        total_new += len(new_group)

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
            known_winners = {
                mid: data["winner"] for mid, data in played.items()
                if data.get("winner")
            }
            slot_teams = resolve_knockout_slot_teams(
                groups, teams, played_groups, bracket, annex_c, known_winners
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
                    bsd_winner = event.get("winner")
                    if bsd_winner:
                        bsd_winner_lower = bsd_winner.strip().lower()
                        home_lower = event.get("home_team", "").strip().lower()
                        away_lower = event.get("away_team", "").strip().lower()
                        if bsd_winner_lower == home_lower:
                            winner = home_norm
                        else:
                            winner = away_norm
                    else:
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

    return played_groups, played, elo_applied, total_new


def draw_backfill(
    teams: dict[str, dict],
    played: dict[str, dict],
    played_groups: dict[str, dict],
    elo_applied: set[str],
    data_dir: Path | str | None = None,
) -> tuple[set[str], int]:
    """One-shot backfill: replay historical draws through fixed Elo pipeline.

    Returns (updated_elo_applied, n_backfilled).
    """
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
        return elo_applied, 0

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

    return elo_applied, len(backfilled)


def collect_matches_from_groups(groups: dict) -> list[dict]:
    """Collect all upcoming matches from groups."""
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


def collect_matches_from_bracket(bracket: list[dict], played: dict) -> list[dict]:
    """Collect upcoming knockout matches from bracket."""
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


def gather_signal_data(
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
    defensive_cache: dict | None = None,
    manager_cache: dict | None = None,
    availability_cache: dict | None = None,
    elo_odds_cache: dict | None = None,
    team_synergy_cache: dict | None = None,
    rolling_form_cache: dict | None = None,
    squad_value_cache: dict | None = None,
    rest_days_cache: dict | None = None,
) -> list[dict]:
    """Build per-match signal data for the match detail table."""
    odds_m = (odds_cache or {}).get("matches", {})
    cb_m = (cb_cache or {}).get("matches", {})
    form_m = (form_cache or {}).get("matches", {})
    lineup_m = (lineup_cache or {}).get("matches", {})
    defensive_m = (defensive_cache or {}).get("matches", {})
    manager_m = (manager_cache or {}).get("matches", {})
    availability_m = (availability_cache or {}).get("matches", {})
    elo_odds_m = (elo_odds_cache or {}).get("matches", {})
    team_synergy_m = (team_synergy_cache or {}).get("matches", {})
    rolling_form_m = (rolling_form_cache or {}).get("matches", {})
    squad_value_m = (squad_value_cache or {}).get("matches", {})
    rest_days_m = (rest_days_cache or {}).get("matches", {})

    played_mids: set = set()
    for g in (played_groups or {}).values():
        if isinstance(g, dict):
            mid = g.get("match_id")
            if mid:
                played_mids.add(mid)

    all_matches = collect_matches_from_groups(groups)
    all_matches += collect_matches_from_bracket(bracket, played)

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
        defensive_prob = None
        if mid in defensive_m and isinstance(defensive_m[mid], dict):
            defensive_prob = defensive_m[mid].get("probability")
        manager_prob = None
        if mid in manager_m and isinstance(manager_m[mid], dict):
            manager_prob = manager_m[mid].get("probability")
        availability_prob = None
        if mid in availability_m and isinstance(availability_m[mid], dict):
            availability_prob = availability_m[mid].get("probability")
        elo_odds_prob = None
        if mid in elo_odds_m and isinstance(elo_odds_m[mid], dict):
            elo_odds_prob = elo_odds_m[mid].get("probability")
        team_synergy_prob = None
        if mid in team_synergy_m and isinstance(team_synergy_m[mid], dict):
            team_synergy_prob = team_synergy_m[mid].get("probability")
        rolling_form_prob = None
        if mid in rolling_form_m and isinstance(rolling_form_m[mid], dict):
            rolling_form_prob = rolling_form_m[mid].get("probability")
        squad_value_prob = None
        if mid in squad_value_m and isinstance(squad_value_m[mid], dict):
            squad_value_prob = squad_value_m[mid].get("probability")
        rest_days_prob = None
        if mid in rest_days_m and isinstance(rest_days_m[mid], dict):
            rest_days_prob = rest_days_m[mid].get("probability")

        xg_val = None
        if xg_overrides and mid in xg_overrides:
            xg_val = xg_overrides[mid]

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
                "defensive_quality": defensive_prob,
                "manager_effect": manager_prob,
                "availability": availability_prob,
                "elo_odds": elo_odds_prob,
                "team_synergy": team_synergy_prob,
                "rolling_form": rolling_form_prob,
                "squad_value": squad_value_prob,
                "rest_days": rest_days_prob,
                "xg": xg_val,
            },
            "blended": round(blended, 4),
        })

    return result


def compute_group_display(
    groups: dict,
    teams: dict[str, dict],
    played_groups: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """Run a single deterministic group simulation iteration for display.

    Returns (standings, third_ranked).
    """
    if not groups:
        return [], []
    from src.groups import (
        compute_standings, rank_third_placed,
        precompute_matchup_lambdas, simulate_group_matches,
    )
    elo_dict = {n: d["elo"] for n, d in teams.items()}
    lambdas = precompute_matchup_lambdas(groups, elo_dict, base_rate=constants.EXPECTED_GOALS_BASE_RATE)
    results = simulate_group_matches(
        groups, teams, elo_dict, random.Random(0),
        fair_play=False, matchup_lambdas=lambdas,
        played_groups=played_groups or {},
        base_rate=constants.EXPECTED_GOALS_BASE_RATE,
    )
    standings = compute_standings(results, elo_dict)
    return standings, rank_third_placed(standings)


def run_poll_cycle(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    played: dict[str, dict],
    played_groups: dict[str, dict],
    api_key: str,
    aliases: dict[str, list[str]],
    last_sim_time: float = 0.0,
    last_request_time: float = 0.0,
    prev_probs: dict | None = None,
    seed: int | None = None,
    league_id: int = 27,
    data_dir: Path | str | None = None,
    elo_last_sync_time: float = 0.0,
    last_gov_time: float = 0.0,
    ai_preview_enabled: bool = False,
    match_detail_enabled: str | None = None,
    prev_signal_data: list[dict] | None = None,
) -> dict:
    """Run one fetch -> process -> simulate -> print cycle.

    Returns a dict with all data that was previously printed.
    """
    played_groups = played_groups or {}
    signal_warnings: list[str] = []

    if elo_last_sync_time > 0:
        hours_since_sync = (time.time() - elo_last_sync_time) / 3600
        if hours_since_sync >= ELO_SYNC_INTERVAL_HOURS:
            elo_last_sync_time, _ = run_elo_sync(teams, elo_last_sync_time, data_dir=data_dir)

    if elo_last_sync_time > 0:
        staleness_hours = (time.time() - elo_last_sync_time) / 3600
        if staleness_hours >= 24:
            signal_warnings.append(f"Staleness: Elo ratings {staleness_hours:.0f}h old")

    now = time.time()
    if last_request_time > 0 and now - last_request_time < POLL_INTERVAL:
        sleep_secs = POLL_INTERVAL - (now - last_request_time)
        time.sleep(sleep_secs)

    now = time.time()

    if last_sim_time > 0 and now - last_sim_time > 3600:
        probs = run_full_simulation(teams, groups, bracket, annex_c, played, played_groups=played_groups, iterations=50000, seed=seed)
        standings, third_ranked = compute_group_display(groups, teams, played_groups)
        return {
            "simulation": probs,
            "new_matches": [],
            "signal_warnings": signal_warnings + ["Auto-refresh: hourly re-simulation"],
            "blend_params": None,
            "governance": None,
            "elo_sync": None,
            "match_detail": None,
            "group_standings": {"standings": standings, "third_ranked": third_ranked},
            "sim_elapsed": 0.0,
            "last_sim_time": now,
            "last_request_time": last_request_time,
            "probs": probs,
        }

    last_request_time = time.time()
    raw = fetch_raw_matches(api_key, api_url=constants.api_url_for_league(league_id), league_id=league_id)

    new_matches = []
    if raw:
        try:
            new_matches = process_matches(raw, teams, bracket, aliases, set(played.keys()))
        except Exception as e:
            signal_warnings.append(f"Fetcher error: {e}")

    new_match_alerts: list[dict] = []
    if new_matches:
        for m in new_matches:
            new_match_alerts.append({
                "match_id": m["match_id"],
                "team_a": m["team_a"],
                "team_b": m["team_b"],
                "winner": m.get("winner"),
            })
            elo_updates = elo.apply_elo_update(m, teams)
            played[m["match_id"]] = m
            state.save_teams(teams, data_dir)
            state.save_played(played, data_dir)

    new_group_matches = []
    if raw:
        try:
            played_bsd_event_ids: set[str] = set()
            new_group_matches = process_group_matches(
                raw, teams, groups, aliases,
                set(played_groups.keys()), played_bsd_event_ids,
            )
        except Exception as e:
            signal_warnings.append(f"Group fetcher error: {e}")

    new_group_alerts: list[dict] = []
    if new_group_matches:
        for m in new_group_matches:
            new_group_alerts.append({
                "match_id": m["match_id"],
                "team_a": m["team_a"],
                "team_b": m["team_b"],
                "winner": m.get("winner"),
            })
            elo_updates = elo.apply_elo_update(m, teams)
            played_groups[m["match_id"]] = m
            state.save_played_groups(played_groups, data_dir)
        state.save_teams(teams, data_dir)

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
            signal_warnings.append("Failed to create prediction_history entries for new matches")

    odds_cache = state.load_signal_cache(ODDS_CACHE_FILE, data_dir)
    if raw and not state.is_cache_valid(odds_cache, ODDS_CACHE_TTL_HOURS):
        try:
            odds_cache = fetch_and_cache_odds(
                api_key, raw, aliases, groups, ODDS_CACHE_TTL_HOURS
            )
            state.save_signal_cache(odds_cache, ODDS_CACHE_FILE, data_dir)
        except Exception as e:
            signal_warnings.append(f"Odds fetch failed: {e}")
            if not odds_cache or not odds_cache.get("matches"):
                signal_warnings.append("Market odds unavailable — no cached data")

    cb_cache = state.load_signal_cache(CATBOOST_CACHE_FILE, data_dir)
    if not state.is_cache_valid(cb_cache, CATBOOST_CACHE_TTL_HOURS):
        try:
            cb_cache = fetch_and_cache_catboost(
                api_key, aliases, groups, bracket, CATBOOST_CACHE_TTL_HOURS,
                league_id=league_id,
            )
            state.save_signal_cache(cb_cache, CATBOOST_CACHE_FILE, data_dir)
        except Exception as e:
            signal_warnings.append(f"CatBoost fetch failed: {e}")
            if not cb_cache or not cb_cache.get("matches"):
                signal_warnings.append("CatBoost predictions unavailable — no cached data")

    xg_overrides: dict[str, tuple[float, float]] = {}
    if cb_cache and cb_cache.get("matches"):
        for mid, entry in cb_cache["matches"].items():
            home_xg = entry.get("expected_home_goals")
            away_xg = entry.get("expected_away_goals")
            if home_xg is not None and away_xg is not None:
                xg_overrides[mid] = (home_xg, away_xg)

    form_cache = {}
    try:
        form_cache = compute_form_signal(
            teams, groups, bracket=bracket,
            played=played, played_groups=played_groups,
        )
        state.save_signal_cache(form_cache, FORM_CACHE_FILE, data_dir)
    except Exception as e:
        signal_warnings.append(f"Form signal computation failed: {e}")
        if not form_cache or not form_cache.get("matches"):
            signal_warnings.append("Form signal unavailable — no cached data")

    lineup_cache = {}
    try:
        lineup_cache = compute_lineup_signal(groups, bracket=bracket)
        state.save_signal_cache(lineup_cache, LINEUP_CACHE_FILE, data_dir)
    except Exception as e:
        signal_warnings.append(f"Lineup signal computation failed: {e}")
        if not lineup_cache or not lineup_cache.get("matches"):
            signal_warnings.append("Lineup strength unavailable — no cached data")

    elo_odds_cache = {}
    try:
        from src.predictors.elo_odds import compute_elo_odds_signal
        elo_odds_cache = compute_elo_odds_signal(teams, groups, bracket=bracket)
        state.save_signal_cache(elo_odds_cache, ELO_ODDS_CACHE_FILE, data_dir)
    except Exception as e:
        signal_warnings.append(f"Elo odds signal computation failed: {e}")
        if not elo_odds_cache or not elo_odds_cache.get("matches"):
            signal_warnings.append("Elo odds signal unavailable — no cached data")

    team_synergy_cache = {}
    try:
        from src.predictors.team_synergy import compute_team_synergy_signal
        team_synergy_cache = compute_team_synergy_signal(teams, groups, played=played, played_groups=played_groups, bracket=bracket)
        state.save_signal_cache(team_synergy_cache, TEAM_SYNERGY_CACHE_FILE, data_dir)
    except Exception as e:
        signal_warnings.append(f"Team synergy signal computation failed: {e}")
        if not team_synergy_cache or not team_synergy_cache.get("matches"):
            signal_warnings.append("Team synergy signal unavailable — no cached data")

    rolling_form_cache = {}
    try:
        from src.predictors.rolling_form import compute_rolling_form_signal
        rolling_form_cache = compute_rolling_form_signal(teams, groups, played=played, played_groups=played_groups, bracket=bracket)
        state.save_signal_cache(rolling_form_cache, ROLLING_FORM_CACHE_FILE, data_dir)
    except Exception as e:
        signal_warnings.append(f"Rolling form signal computation failed: {e}")
        if not rolling_form_cache or not rolling_form_cache.get("matches"):
            signal_warnings.append("Rolling form signal unavailable — no cached data")

    squad_value_cache = {}
    try:
        from src.predictors.squad_value import compute_squad_value_signal
        squad_value_cache = compute_squad_value_signal(groups, bracket=bracket)
        state.save_signal_cache(squad_value_cache, SQUAD_VALUE_CACHE_FILE, data_dir)
    except Exception as e:
        signal_warnings.append(f"Squad value signal computation failed: {e}")
        if not squad_value_cache or not squad_value_cache.get("matches"):
            signal_warnings.append("Squad value signal unavailable — no cached data")

    rest_days_cache = {}
    try:
        from src.predictors.rest_days import compute_rest_days_signal
        rest_days_cache = compute_rest_days_signal(groups, bracket=bracket)
        state.save_signal_cache(rest_days_cache, REST_DAYS_CACHE_FILE, data_dir)
    except Exception as e:
        signal_warnings.append(f"Rest days signal computation failed: {e}")
        if not rest_days_cache or not rest_days_cache.get("matches"):
            signal_warnings.append("Rest days signal unavailable — no cached data")

    defensive_cache = {}
    manager_cache = {}
    if api_key:
        manager_cache_data = state.load_signal_cache(MANAGER_CACHE_FILE, data_dir)
        if not state.is_cache_valid(manager_cache_data, MANAGER_CACHE_TTL_HOURS):
            try:
                from src.predictors.manager_signals import fetch_and_cache_manager_signals
                defensive_cache, manager_cache = fetch_and_cache_manager_signals(
                    api_key, groups, bracket=bracket, league_id=league_id,
                    cache_ttl_hours=MANAGER_CACHE_TTL_HOURS,
                )
                state.save_signal_cache(defensive_cache, DEFENSIVE_CACHE_FILE, data_dir)
                state.save_signal_cache(manager_cache, MANAGER_EFFECT_CACHE_FILE, data_dir)
            except Exception as e:
                signal_warnings.append(f"Manager signals fetch failed: {e}")
                if not defensive_cache or not defensive_cache.get("matches"):
                    signal_warnings.append("Defensive quality unavailable — no cached data")
                if not manager_cache or not manager_cache.get("matches"):
                    signal_warnings.append("Manager effect unavailable — no cached data")
        else:
            defensive_cache = state.load_signal_cache(DEFENSIVE_CACHE_FILE, data_dir)
            manager_cache = state.load_signal_cache(MANAGER_EFFECT_CACHE_FILE, data_dir)

    availability_cache = {}
    if api_key:
        availability_cache = state.load_signal_cache(AVAILABILITY_CACHE_FILE, data_dir)
        if not state.is_cache_valid(availability_cache, AVAILABILITY_CACHE_TTL_HOURS):
            try:
                from src.predictors.availability import fetch_and_cache_availability_signal
                availability_cache = fetch_and_cache_availability_signal(
                    api_key, groups, bracket=bracket, league_id=league_id,
                    cache_ttl_hours=AVAILABILITY_CACHE_TTL_HOURS,
                )
                state.save_signal_cache(availability_cache, AVAILABILITY_CACHE_FILE, data_dir)
            except Exception as e:
                signal_warnings.append(f"Availability signal fetch failed: {e}")
                if not availability_cache or not availability_cache.get("matches"):
                    signal_warnings.append("Availability signal unavailable — no cached data")

    _ledger_pairs: list[tuple[str, str, dict]] = []
    for cache, name in [(odds_cache, "market_odds"), (cb_cache, "catboost"),
                         (form_cache, "form"), (lineup_cache, "lineup_strength"),
                         (defensive_cache, "defensive_quality"),
                         (manager_cache, "manager_effect"),
                         (availability_cache, "availability"),
                         (elo_odds_cache, "elo_odds"),
                         (team_synergy_cache, "team_synergy"),
                         (rolling_form_cache, "rolling_form"),
                         (squad_value_cache, "squad_value"),
                         (rest_days_cache, "rest_days")]:
        if cache and cache.get("matches"):
            for mid, entry in cache["matches"].items():
                _ledger_pairs.append((mid, name, entry))
    if _ledger_pairs:
        state.ledger_batch_upsert(_ledger_pairs, data_dir)

    _prev_history = state.load_prediction_history(data_dir)
    _prev_cal_params = state.load_calibration_params(data_dir)

    merge_signals_into_history(data_dir=data_dir)

    blend_params = None
    try:
        engine = build_signal_engine(
            odds_cache=odds_cache, cb_cache=cb_cache,
            form_cache=form_cache, lineup_cache=lineup_cache,
            defensive_cache=defensive_cache, manager_cache=manager_cache,
            availability_cache=availability_cache,
            elo_odds_cache=elo_odds_cache, team_synergy_cache=team_synergy_cache,
            rolling_form_cache=rolling_form_cache, squad_value_cache=squad_value_cache,
            rest_days_cache=rest_days_cache,
        )
        elo_ratings = {name: data["elo"] for name, data in teams.items()}
        all_matches = collect_matches_from_groups(groups)
        all_matches += collect_matches_from_bracket(bracket, played)
        context = PredictionContext(
            fixtures=all_matches,
            elo_ratings=elo_ratings,
            played_results=list(played.values()) + list((played_groups or {}).values()),
            team_aliases=aliases,
        )
        match_probs: dict[str, float] = {}
        blend_weights: dict[str, float] = {}
        predictions: list[BlendedPrediction] = []
        for m in all_matches:
            mid = m.get("match_id", "")
            if not mid:
                continue
            bp = engine.evaluate(m, context)
            predictions.append(bp)
            match_probs[mid] = bp.home_prob
        blend_weights = dict(engine.weights)
        blend_params = {
            "match_probs": match_probs,
            "blend_weights": blend_weights,
            "calibration_params": {},
        }
    except Exception:
        blend_params = None

    try:
        from src.governance import _maybe_update_versions
        from src.state import load_versions, save_versions, load_prediction_history, save_prediction_history, load_calibration_params

        current_versions = load_versions(data_dir)
        new_cal_params = load_calibration_params(data_dir)
        calibration_changed = _prev_cal_params != new_cal_params

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
        signal_warnings.append(f"Version tracking failed: {e}")

    odds_matches = odds_cache.get("matches", {}) if odds_cache else {}
    odds_unavailable = sum(
        1 for m in odds_matches.values() if not m.get("available", False)
    )
    if odds_unavailable:
        signal_warnings.append(f"Market odds unavailable for {odds_unavailable} match(es)")
    cb_matches = cb_cache.get("matches", {}) if cb_cache else {}
    cb_unavailable = sum(
        1 for m in cb_matches.values() if not m.get("available", False)
    )
    if cb_unavailable:
        signal_warnings.append(f"CatBoost predictions unavailable for {cb_unavailable} match(es)")
    form_matches = form_cache.get("matches", {}) if form_cache else {}
    form_unavailable = sum(
        1 for m in form_matches.values() if not m.get("available", False)
    )
    if form_unavailable:
        signal_warnings.append(f"Form signal unavailable for {form_unavailable} match(es)")
    lineup_matches = lineup_cache.get("matches", {}) if lineup_cache else {}
    lineup_unavailable = sum(
        1 for m in lineup_matches.values() if not m.get("available", False)
    )
    if lineup_unavailable:
        signal_warnings.append(f"Lineup strength unavailable for {lineup_unavailable} match(es)")
    defensive_matches = defensive_cache.get("matches", {}) if defensive_cache else {}
    defensive_unavailable = sum(
        1 for m in defensive_matches.values() if not m.get("available", False)
    )
    if defensive_unavailable:
        signal_warnings.append(f"Defensive quality unavailable for {defensive_unavailable} match(es)")
    manager_matches = manager_cache.get("matches", {}) if manager_cache else {}
    manager_unavailable = sum(
        1 for m in manager_matches.values() if not m.get("available", False)
    )
    if manager_unavailable:
        signal_warnings.append(f"Manager effect unavailable for {manager_unavailable} match(es)")
    availability_matches = availability_cache.get("matches", {}) if availability_cache else {}
    availability_unavailable = sum(
        1 for m in availability_matches.values() if not m.get("available", False)
    )
    if availability_unavailable:
        signal_warnings.append(f"Availability signal unavailable for {availability_unavailable} match(es)")
    elo_odds_matches = elo_odds_cache.get("matches", {}) if elo_odds_cache else {}
    elo_odds_unavailable = sum(
        1 for m in elo_odds_matches.values() if not m.get("available", False)
    )
    if elo_odds_unavailable:
        signal_warnings.append(f"Elo odds signal unavailable for {elo_odds_unavailable} match(es)")
    team_synergy_matches = team_synergy_cache.get("matches", {}) if team_synergy_cache else {}
    team_synergy_unavailable = sum(
        1 for m in team_synergy_matches.values() if not m.get("available", False)
    )
    if team_synergy_unavailable:
        signal_warnings.append(f"Team synergy signal unavailable for {team_synergy_unavailable} match(es)")
    rolling_form_matches = rolling_form_cache.get("matches", {}) if rolling_form_cache else {}
    rolling_form_unavailable = sum(
        1 for m in rolling_form_matches.values() if not m.get("available", False)
    )
    if rolling_form_unavailable:
        signal_warnings.append(f"Rolling form signal unavailable for {rolling_form_unavailable} match(es)")
    squad_value_matches = squad_value_cache.get("matches", {}) if squad_value_cache else {}
    squad_value_unavailable = sum(
        1 for m in squad_value_matches.values() if not m.get("available", False)
    )
    if squad_value_unavailable:
        signal_warnings.append(f"Squad value signal unavailable for {squad_value_unavailable} match(es)")
    rest_days_matches = rest_days_cache.get("matches", {}) if rest_days_cache else {}
    rest_days_unavailable = sum(
        1 for m in rest_days_matches.values() if not m.get("available", False)
    )
    if rest_days_unavailable:
        signal_warnings.append(f"Rest days signal unavailable for {rest_days_unavailable} match(es)")

    governance_result = None
    if last_gov_time == 0.0 or (time.time() - last_gov_time >= constants.GOVERNANCE_INTERVAL_SECONDS):
        try:
            from src.governance import _run_governance
            from src.state import load_versions as _lv, load_prediction_history as _lph

            gov_entries = _lph(data_dir)
            gov_versions = _lv(data_dir)
            gov_signal_keys = sorted(
                k for entry in gov_entries
                if isinstance(entry.get("signals"), dict)
                for k in entry["signals"]
            ) if gov_entries else ["elo", "market_odds", "catboost", "form", "lineup_strength"]

            governance_result = _run_governance(
                entries=gov_entries,
                versions=gov_versions,
                signal_keys=list(set(gov_signal_keys)),
                blend_weights=blend_params.get("blend_weights", {}) if blend_params else {},
                data_dir=data_dir,
            )
            last_gov_time = time.time()
        except Exception as e:
            signal_warnings.append(f"Governance check failed: {e}")

    show_group_display = bool(new_group_matches)

    sim_start = time.time()
    probs = run_full_simulation(
        teams, groups, bracket, annex_c, played,
        played_groups=played_groups, iterations=50000, seed=seed,
        blend_params=blend_params, xg_overrides=xg_overrides,
    )
    sim_elapsed = time.time() - sim_start

    group_data = None
    if show_group_display:
        standings, third_ranked = compute_group_display(groups, teams, played_groups)
        group_data = {"standings": standings, "third_ranked": third_ranked}

    try:
        snapshot = {"timestamp": datetime.now(timezone.utc).isoformat(), "probabilities": probs}
        state.append_probability_log(snapshot, data_dir=data_dir)
    except Exception:
        signal_warnings.append("Failed to save probability log snapshot")

    match_detail_data = None
    if match_detail_enabled:
        try:
            matches_data = gather_signal_data(
                teams, groups, bracket,
                odds_cache, cb_cache, form_cache, lineup_cache,
                xg_overrides, played, played_groups,
                blend_params=blend_params,
                defensive_cache=defensive_cache,
                manager_cache=manager_cache,
                availability_cache=availability_cache,
                elo_odds_cache=elo_odds_cache,
                team_synergy_cache=team_synergy_cache,
                rolling_form_cache=rolling_form_cache,
                squad_value_cache=squad_value_cache,
                rest_days_cache=rest_days_cache,
            )
            match_detail_data = {
                "all_matches": matches_data,
                "mode": match_detail_enabled,
            }
            if match_detail_enabled != "table":
                target_mid = match_detail_enabled
                for md in matches_data:
                    if md["match_id"] == target_mid:
                        match_entry = None
                        if target_mid in played:
                            match_entry = played[target_mid]
                        elif target_mid in (played_groups or {}):
                            match_entry = (played_groups or {}).get(target_mid)
                        prev_data = None
                        if prev_signal_data:
                            prev_data = next((d for d in prev_signal_data if d["match_id"] == target_mid), None)
                        focus_data = dict(md)
                        if prev_data:
                            focus_data["prev_signals"] = prev_data["signals"]
                            focus_data["blended_delta"] = md["blended"] - prev_data["blended"]
                        match_detail_data["focus"] = focus_data
                        match_detail_data["match_entry"] = match_entry
            prev_signal_data = matches_data
        except Exception:
            signal_warnings.append("Failed to display match detail table")

    return {
        "simulation": probs,
        "new_matches": {"knockout": new_match_alerts, "group": new_group_alerts},
        "signal_warnings": signal_warnings,
        "blend_params": blend_params,
        "governance": governance_result,
        "elo_sync": None,
        "match_detail": match_detail_data,
        "group_standings": group_data,
        "sim_elapsed": sim_elapsed,
        "last_sim_time": time.time(),
        "last_request_time": last_request_time,
        "probs": probs,
        "elo_last_sync_time": elo_last_sync_time,
        "last_gov_time": last_gov_time,
        "prev_signal_data": prev_signal_data,
    }
