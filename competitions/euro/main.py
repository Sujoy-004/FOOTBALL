"""Entry point for UEFA Euro 2024 Dynamic Predictor.

Loads state, enters a continuous polling loop, handles graceful shutdown.
Imports generic modules from worldcup_predictor.src and provides Euro-specific code.
"""

import argparse
import copy
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

import competitions.euro  # noqa: F401 — ensures worldcup_predictor is on sys.path
from src import elo, state
from src.constants import (
    API_TIMEOUT, POLL_INTERVAL,
    ODDS_CACHE_TTL_HOURS, CATBOOST_CACHE_TTL_HOURS,
    ODDS_CACHE_FILE, CATBOOST_CACHE_FILE,
)
from src.fetcher import fetch_raw_matches, process_group_matches, process_matches
from src.predictors.odds import fetch_and_cache_odds
from src.predictors.catboost import fetch_and_cache_catboost

from competitions.euro import config, display
from competitions.euro.simulation import run_full_simulation, resolve_knockout_slot_teams


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="euro-predict",
        description="UEFA Euro 2024 Dynamic Predictor — live tournament odds.",
    )
    parser.add_argument("--once", action="store_true", dest="once",
                        help="Run a single fetch->simulate->print cycle, then exit")
    parser.add_argument("--seed", type=int, default=None, metavar="N",
                        help="Random seed for reproducible simulation")
    return parser.parse_args(argv)


def _load_data(data_dir: Path) -> tuple:
    """Load all Euro competition data files."""
    with open(data_dir / "teams.json", encoding="utf-8") as f:
        teams = json.load(f)
    with open(data_dir / "groups.json", encoding="utf-8") as f:
        groups = json.load(f)
    with open(data_dir / "bracket.json", encoding="utf-8") as f:
        bracket = json.load(f)
    return teams, groups, bracket


def _run_elo_sync(teams: dict, data_dir: Path) -> None:
    from src import elo_sync
    corrections = elo_sync.sync_elo_from_eloratings(teams, data_dir=data_dir,
                                                     url="https://www.eloratings.net/Europe.tsv")
    if corrections:
        for c in corrections:
            print(f"  Elo correction: {c.get('team', '?')} -> {c.get('new_value', '?')}")


def _run_iteration(teams, groups, bracket, played, played_groups, api_key,
                   last_sim_time, last_request_time, prev_probs=None, seed=None, data_dir=None):
    """Run one fetch -> process -> simulate -> print cycle."""
    from src import state
    from src.constants import ODDS_CACHE_FILE, CATBOOST_CACHE_FILE, ODDS_CACHE_TTL_HOURS, CATBOOST_CACHE_TTL_HOURS
    from src.fetcher import fetch_raw_matches, process_matches, process_group_matches
    from src.predictors.odds import fetch_and_cache_odds
    from src.predictors.catboost import fetch_and_cache_catboost

    now = time.time()
    last_request_time = time.time()
    raw = fetch_raw_matches(api_key, league_id=config.DEFAULT_LEAGUE_ID)

    new_matches = []
    if raw:
        try:
            new_matches = process_matches(raw, teams, bracket, {}, set(played.keys()))
        except Exception:
            pass

    if new_matches:
        for m in new_matches:
            display.print_match_alert(m)
            elo.apply_elo_update(m, teams)
            played[m["match_id"]] = m
            state.save_teams(teams, data_dir)
            state.save_played(played, data_dir)
    else:
        display.print_heartbeat()

    new_group_matches = []
    if raw:
        try:
            played_bsd_ids: set[str] = set()
            new_group_matches = process_group_matches(
                raw, teams, groups, {}, set(played_groups.keys()), played_bsd_ids,
            )
        except Exception:
            pass

    if new_group_matches:
        for m in new_group_matches:
            display.print_match_alert(m)
            elo.apply_elo_update(m, teams)
            played_groups[m["match_id"]] = m
            state.save_played_groups(played_groups, data_dir)
        state.save_teams(teams, data_dir)

    all_new = list(new_matches or []) + list(new_group_matches or [])
    if all_new:
        existing = state.load_prediction_history(data_dir)
        existing_mids = {e.get("match_id", "") for e in existing} if existing else set()
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
                "match_id": mid, "timestamp": now_iso,
                "team_a": t_a, "team_b": t_b, "actual": actual_a,
                "signals": {"elo": {"probability": round(p_a, 4), "version": "v1",
                                    "timestamp": now_iso, "available": True}},
            }
            state.append_prediction_history(entry, data_dir)

    odds_cache = state.load_signal_cache(ODDS_CACHE_FILE, data_dir)
    if raw and not state.is_cache_valid(odds_cache, ODDS_CACHE_TTL_HOURS):
        try:
            odds_cache = fetch_and_cache_odds(api_key, raw, {}, groups, ODDS_CACHE_TTL_HOURS)
            state.save_signal_cache(odds_cache, ODDS_CACHE_FILE, data_dir)
        except Exception:
            pass

    cb_cache = state.load_signal_cache(CATBOOST_CACHE_FILE, data_dir)
    if not state.is_cache_valid(cb_cache, CATBOOST_CACHE_TTL_HOURS):
        try:
            cb_cache = fetch_and_cache_catboost(api_key, {}, groups, bracket,
                                                 CATBOOST_CACHE_TTL_HOURS,
                                                 league_id=config.DEFAULT_LEAGUE_ID)
            state.save_signal_cache(cb_cache, CATBOOST_CACHE_FILE, data_dir)
        except Exception:
            pass

    sim_start = time.time()
    probs = run_full_simulation(
        teams, groups, bracket, played,
        played_groups=played_groups,
        iterations=config.SIMULATION_ITERATIONS,
        seed=seed,
    )
    display.print_simulation_duration(time.time() - sim_start)
    display.print_probability_table(probs, prev_probs)

    try:
        snapshot = {"timestamp": datetime.now(timezone.utc).isoformat(), "probabilities": probs}
        state.append_probability_log(snapshot, data_dir=data_dir)
    except Exception:
        pass

    return time.time(), last_request_time, probs


def main() -> None:
    args = _parse_args()
    data_dir = config.DATA_DIR
    league_data_dir = data_dir / str(config.DEFAULT_LEAGUE_ID)
    league_data_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        os.system("")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    load_dotenv()

    api_key = os.environ.get("BSD_API_KEY")
    if not api_key:
        print("BSD_API_KEY not set. Euro predictor will run with Elo-only simulation.")
        api_key = ""

    teams, groups, bracket = _load_data(data_dir)
    played = state.load_played(data_dir=league_data_dir)
    played_groups = state.load_played_groups(data_dir=league_data_dir)

    display.print_header()

    _run_elo_sync(teams, data_dir)

    if args.once:
        _run_iteration(teams, groups, bracket, played, played_groups, api_key,
                       last_sim_time=0.0, last_request_time=0.0,
                       prev_probs=None, seed=args.seed, data_dir=league_data_dir)
        sys.exit(0)

    def _signal_handler(signum, frame):
        print()
        print("Shutdown requested — finishing current iteration...")
        _state.running = False

    class _RunState:
        running = True

    _state = _RunState()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, _signal_handler)

    last_sim_time = 0.0
    last_request_time = 0.0
    prev_probs = None

    last_sim_time, last_request_time, prev_probs = _run_iteration(
        teams, groups, bracket, played, played_groups, api_key,
        last_sim_time, last_request_time, prev_probs,
        seed=args.seed, data_dir=league_data_dir,
    )

    while _state.running:
        time.sleep(config.POLL_INTERVAL)
        if not _state.running:
            break
        last_sim_time, last_request_time, prev_probs = _run_iteration(
            teams, groups, bracket, played, played_groups, api_key,
            last_sim_time, last_request_time, prev_probs,
            seed=args.seed, data_dir=league_data_dir,
        )

    final_probs = run_full_simulation(
        teams, groups, bracket, played,
        played_groups=played_groups,
        iterations=config.SIMULATION_ITERATIONS,
        seed=args.seed,
    )
    display.print_shutdown_banner(final_probs)
    state.save_teams(teams, data_dir=league_data_dir)
    state.save_played(played, data_dir=league_data_dir)
    state.save_played_groups(played_groups, data_dir=league_data_dir)


if __name__ == "__main__":
    main()
