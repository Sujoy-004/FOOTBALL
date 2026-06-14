"""Entry point for the World Cup Dynamic Predictor.

Loads state, enters a continuous polling loop (default 60s interval),
and handles graceful shutdown via SIGINT/SIGTERM.
"""

import json
import logging
import os
import signal
import sys
import time

from src import elo, output, state
from src.constants import API_TIMEOUT, POLL_INTERVAL
from src.fetcher import fetch_raw_matches, process_matches
from src.simulation import run_simulation


_running = True


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


def _run_iteration(teams, bracket, played, api_key, aliases, last_sim_time, last_request_time, prev_probs=None):
    """Run one fetch -> process -> simulate -> print cycle.

    Returns (updated_last_sim_time, updated_last_request_time, probs).
    """
    # Rate limiter: ensure minimum interval since last API call
    now = time.time()
    if last_request_time > 0 and now - last_request_time < POLL_INTERVAL:
        _next_poll_sleep(POLL_INTERVAL - (now - last_request_time))

    now = time.time()

    # Hourly re-sim check: if >3600s since last sim with no new matches, refresh
    if last_sim_time > 0 and now - last_sim_time > 3600:
        output.print_auto_refresh()
        probs = run_simulation(teams, bracket, played, iterations=50000)
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

    # Update Elo and state for new matches
    if new_matches:
        for m in new_matches:
            output.print_match_alert(m)
            current_elos = {name: data["elo"] for name, data in teams.items()}
            ratings_update = elo.update_ratings(
                m["team_a"], m["team_b"], m["winner"], current_elos
            )
            elo_updates = {}
            for team_name, new_rating in ratings_update.items():
                old_rating = current_elos[team_name]
                elo_updates[team_name] = {"old": old_rating, "new": new_rating}
                teams[team_name]["elo"] = new_rating
            output.print_elo_changes(elo_updates)
            played[m["match_id"]] = m
            state.save_teams(teams)
            state.save_played(played)
    else:
        output.print_heartbeat()

    # Simulate and print results
    sim_start = time.time()
    probs = run_simulation(teams, bracket, played, iterations=50000)
    sim_elapsed = time.time() - sim_start
    output.print_simulation_duration(sim_elapsed)
    output.print_probability_table(probs, prev_probs)
    if prev_probs is not None:
        output.print_delta_summary(probs, prev_probs)

    return time.time(), last_request_time, probs


def validate_api_key() -> str:
    """Validate FOOTBALL_API_KEY env var is set and returns a non-403 status.

    Returns:
        str: The API key value.

    Exits 1 if key is missing or returns HTTP 403.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        output.print_error("FOOTBALL_API_KEY not set. Get a free key at https://www.football-data.org/")
        sys.exit(1)

    import requests
    try:
        resp = requests.get(
            "https://api.football-data.org/v4/competitions/WC",
            headers={"X-Auth-Token": api_key},
            timeout=10,
        )
        if resp.status_code == 403:
            output.print_error("Invalid FOOTBALL_API_KEY (HTTP 403). Check your key at https://www.football-data.org/")
            sys.exit(1)
        if resp.status_code != 200:
            print(f"Warning: API availability check returned {resp.status_code}, continuing...", file=sys.stderr)
    except Exception:
        print("Warning: API availability check failed, continuing...", file=sys.stderr)

    return api_key


def main() -> None:
    """Load state, then enter continuous polling loop until signal."""
    # Windows Console Host ANSI initialization (Python 3.10/3.11 quirk)
    if sys.platform == "win32":
        os.system("")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    try:
        teams = state.load_teams()
        bracket = state.load_bracket()
        played = state.load_played()
        api_key = validate_api_key()
        aliases = state.load_aliases()

        output.print_header(teams, bracket, played, aliases)

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
            teams, bracket, played, api_key, aliases,
            last_sim_time, last_request_time, prev_probs,
        )

        # Continuous polling loop
        while _running:
            _next_poll_sleep(POLL_INTERVAL)
            if not _running:
                break
            last_sim_time, last_request_time, prev_probs = _run_iteration(
                teams, bracket, played, api_key, aliases,
                last_sim_time, last_request_time, prev_probs,
            )

        # Shutdown path
        final_probs = run_simulation(teams, bracket, played, iterations=50000)
        output.print_shutdown_banner(final_probs)

        state.save_teams(teams)
        state.save_played(played)

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
