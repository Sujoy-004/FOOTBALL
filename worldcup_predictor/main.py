"""Entry point for the World Cup Dynamic Predictor.

Loads state, enters a continuous polling loop (default 60s interval),
and handles graceful shutdown via SIGINT/SIGTERM.
"""

import argparse
import json
import logging
import os
import random
import signal
import sys
import time

from dotenv import load_dotenv

from src import elo, elo_sync, output, state
from src.constants import API_TIMEOUT, ELO_SYNC_INTERVAL_HOURS, POLL_INTERVAL
from src.fetcher import build_historic_url, fetch_raw_matches, process_group_matches, process_matches
from src.knockout import resolve_knockout_slot_teams, run_full_simulation
from src.simulation import run_simulation
from src.output import print_sync_results, print_staleness_warning, print_drift_flags


_running = True
_elo_last_sync_time: float = 0.0
"""Tracks when Elo sync last completed. 0.0 = never synced. Used for 24h interval checks and wake-from-sleep detection (D-02, D-03)."""


def _run_elo_sync(teams: dict[str, dict]) -> None:
    """Run Elo sync from eloratings.net with cache fallback per D-15/D-19/D-20.

    On first-ever run with no cache and sync failure, prints a clear error
    and continues with teams.json fallback (D-20). On subsequent failures,
    falls back to cached values (D-19).

    Updates _elo_last_sync_time on any successful sync, even if no corrections
    were needed, so the periodic 24h timer advances correctly.
    """
    global _elo_last_sync_time
    start = time.time()
    corrections = elo_sync.sync_elo_from_eloratings(teams)
    elapsed = time.time() - start

    if corrections is None:
        # Fetch failed (D-15, D-19, D-20)
        cache = state.load_eloratings_cache()
        if not cache and _elo_last_sync_time == 0.0:
            # D-20: First run, no cache, network failure
            output.print_error(
                "Cannot initialize Elo ratings — eloratings.net unreachable "
                "and no cached values exist. Using teams.json initial values."
            )
        return

    # Sync succeeded — update timer even if no drift (D-02, D-03)
    _elo_last_sync_time = time.time()

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
    return parser.parse_args(argv)


def _signal_handler(signum, frame):
    """Set running flag to False — loop will finish current iteration then exit."""
    global _running
    _running = False
    print()
    print("Shutdown requested — finishing current iteration...")


def _next_poll_sleep(interval: float) -> None:
    """Sleep for interval seconds in 0.5s increments, checking _running flag."""
    deadline = time.time() + interval
    while _running and time.time() < deadline:
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
    lambdas = precompute_matchup_lambdas(groups, elo)
    results = simulate_group_matches(
        groups, teams, elo, random.Random(0),
        fair_play=False, matchup_lambdas=lambdas,
        played_groups=played_groups or {},
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
) -> tuple[dict[str, dict], dict[str, dict], set[str]]:
    """Fetch all finished matches from WC_START to today, ingest any not yet played.

    Handles both group matches (via process_group_matches for dedup/alias logic)
    and knockout matches (via iterative bracket resolution using resolve_knockout_slot_teams).
    Applies Elo rating updates to newly-ingested matches in chronological
    (completed_at, match_id) order.

    Args:
        elo_applied: Set of match_ids that already have Elo applied (restart guard).

    Returns (updated played_groups, updated played, updated elo_applied).
    """
    historic_url = build_historic_url()
    raw = fetch_raw_matches(api_key, api_url=historic_url)
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
        state.save_played_groups(played_groups)
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
                if home_score == away_score:
                    played_bsd_event_ids.add(bsd_id)
                    continue
                winner = home_norm if home_score > away_score else away_norm
                match_entry = {
                    "match_id": match_id,
                    "team_a": home_norm,
                    "team_b": away_norm,
                    "winner": winner,
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
            state.save_played(played)
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
        state.save_teams(teams)

    return played_groups, played, elo_applied


def _run_iteration(teams, groups, bracket, annex_c, played, played_groups, api_key, aliases, last_sim_time, last_request_time, prev_probs=None, seed=None):
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

    Returns (updated_last_sim_time, updated_last_request_time, probs).
    """
    played_groups = played_groups or {}

    # ── Periodic Elo sync check (D-02, D-03) ──
    global _elo_last_sync_time
    if _elo_last_sync_time > 0:
        hours_since_sync = (time.time() - _elo_last_sync_time) / 3600
        if hours_since_sync >= ELO_SYNC_INTERVAL_HOURS:
            _run_elo_sync(teams)

    # ── Staleness warning (D-16) ──
    if _elo_last_sync_time > 0:
        staleness_hours = (time.time() - _elo_last_sync_time) / 3600
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
    raw = fetch_raw_matches(api_key)

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
            state.save_teams(teams)
            state.save_played(played)
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
            state.save_played_groups(played_groups)
        state.save_teams(teams)

    # D-15: group standings display behavior
    #   - New group match ingested → show
    #   - Hourly refresh → show (handled above in hourly block)
    #   - Regular heartbeat (no new matches) → skip
    show_group_display = bool(new_group_matches)

    # Simulate and print results
    sim_start = time.time()
    probs = run_full_simulation(teams, groups, bracket, annex_c, played, played_groups=played_groups, iterations=50000, seed=seed)
    sim_elapsed = time.time() - sim_start
    output.print_simulation_duration(sim_elapsed)

    # Group standings (D-15: only on new matches or hourly, skip on heartbeat)
    if show_group_display:
        standings, third_ranked = _compute_group_display(groups, teams, played_groups)
        output.print_group_standings(standings, third_ranked)
        output.print_third_place_bubble(third_ranked)

    output.print_probability_table(probs, prev_probs)
    if prev_probs is not None:
        output.print_delta_summary(probs, prev_probs)

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


def main() -> None:
    """Load state, then enter continuous polling loop until signal."""
    args = _parse_args()

    # Windows Console Host ANSI initialization (Python 3.10/3.11 quirk)
    if sys.platform == "win32":
        os.system("")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    load_dotenv()

    try:
        teams = state.load_teams()
        bracket = state.load_bracket()
        played = state.load_played()
        played_groups = state.load_played_groups()
        groups = state.load_groups()
        annex_c = state.load_annex_c()
        api_key = validate_api_key()
        aliases = state.load_aliases()

        # ── Historical catch-up: fetch all finished matches from tournament
        #     start to today. Runs unconditionally on every startup — existing
        #     match_id dedup in process_group_matches prevents re-ingestion.
        #     Elo updates are applied chronologically with (completed_at, match_id)
        #     ordering, guarded by elo_applied_ids to prevent double-counting.
        __elo_applied = state.load_elo_applied()
        played_groups, played, __elo_applied = _run_historical_catch_up(
            api_key, teams, groups, bracket, annex_c, aliases,
            played_groups, played, elo_applied=__elo_applied,
        )
        state.save_elo_applied(__elo_applied)

        # ── Startup Elo sync per D-01, D-18 ──
        # Runs after historical catch-up (Pitfall 7: catch-up first, then sync)
        # and before the first simulation. Always fetches fresh Elo values.
        _run_elo_sync(teams)

        # Apply --no-color before any console output (D-05)
        if args.no_color:
            output.NO_COLOR = True

        output.print_header(teams, bracket, played, aliases, groups, annex_c)

        # ── --once mode: single iteration, immediate exit (D-01, D-02) ──
        if args.once:
            _run_iteration(
                teams, groups, bracket, annex_c, played, played_groups, api_key, aliases,
                last_sim_time=0.0, last_request_time=0.0,
                prev_probs=None, seed=args.seed,
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
            seed=args.seed,
        )

        # Continuous polling loop
        while _running:
            _next_poll_sleep(POLL_INTERVAL)
            if not _running:
                break
            last_sim_time, last_request_time, prev_probs = _run_iteration(
                teams, groups, bracket, annex_c, played, played_groups, api_key, aliases,
                last_sim_time, last_request_time, prev_probs,
                seed=args.seed,
            )

        # Shutdown path
        final_probs = run_full_simulation(teams, groups, bracket, annex_c, played, played_groups=played_groups, iterations=50000, seed=args.seed)
        output.print_shutdown_banner(final_probs)

        state.save_teams(teams)
        state.save_played(played)
        state.save_played_groups(played_groups)

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
