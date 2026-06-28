"""ucl-predict CLI entry point — UCL 2025/26 Monte Carlo predictor.

Single-run tool (D-01): runs MC simulation, assembles SimulationResult,
prints formatted output, optionally exports JSON.

Architecture (D-15, D-16, D-17):
- Imports simulation internals (simulation.py, knockout.py) for orchestration.
- Imports SimulationResult from result.py (the abstract contract).
- Display layer (display.py) imports ONLY result.py — never simulation.py.

Usage:
    python -m competitions.ucl.main -n 10000 -s 42 -o results.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import asdict

from competitions.ucl.display import (
    print_summary,
    print_league_table,
    print_playoff_rounds,
    print_knockout_bracket,
    print_odds,
)
from competitions.ucl.result import SimulationResult
from competitions.ucl.src.simulation import run_monte_carlo, simulate_league_phase
from competitions.ucl.src.knockout import (
    build_r16_bracket,
    simulate_knockout_tree,
    simulate_playoff_round,
    track_knockout_stages,
)
from competitions.ucl.src.elo_fetcher import fetch_team_elos

# Enable ANSI color support on Windows
os.system("")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments (D-02 through D-05)."""
    parser = argparse.ArgumentParser(
        prog="ucl-predict",
        description="UEFA Champions League 2025/26 Monte Carlo predictor.",
    )
    parser.add_argument(
        "-n", "--iterations", type=int, default=10000,
        metavar="N", help="Number of Monte Carlo iterations (default: 10000)",
    )
    parser.add_argument(
        "-s", "--seed", type=int, default=None,
        metavar="N", help="Random seed for reproducible simulation",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        metavar="FILE", help="Write JSON output to FILE (stdout still prints text)",
    )
    return parser.parse_args(argv)


def build_simulation_result(
    fixtures: dict,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
) -> SimulationResult:
    """Run MC simulation + one representative bracket iteration, return SimulationResult.

    Parameters
    ----------
    fixtures:
        UCL fixture schedule dict from fixtures.json.
    elo_ratings:
        {team_name: Elo} for all 36 teams.
    seed:
        Random seed for reproducible simulation.
    n_iterations:
        Number of Monte Carlo iterations.

    Returns
    -------
    SimulationResult
        Fully populated result contract with MC probabilities + bracket snapshot.
    """
    # ── 1. Run Monte Carlo for aggregated probabilities ──
    mc_result = run_monte_carlo(
        fixtures,
        elo_ratings=elo_ratings,
        n_iterations=n_iterations,
        seed=seed,
    )

    # ── 2. Run one representative iteration for bracket display ──
    # Use the same seed so the first iteration is deterministic
    rng = random.Random(seed)
    standings = simulate_league_phase(fixtures, elo_ratings, rng)

    # Pre-load data files to avoid per-call disk I/O
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
    )
    pairings_path = os.path.join(data_dir, "playoff_pairings.json")
    bracket_path = os.path.join(data_dir, "bracket_rules.json")

    import json as _json
    with open(pairings_path) as f:
        pairings_data = _json.load(f)
    with open(bracket_path) as f:
        bracket_data = _json.load(f)

    playoff_result = simulate_playoff_round(
        standings, elo_ratings, rng,
        pairings_data=pairings_data,
    )
    bracket = build_r16_bracket(
        standings, playoff_result,
        bracket_data=bracket_data,
    )
    tree_result = simulate_knockout_tree(bracket, elo_ratings, rng)
    stages = track_knockout_stages(standings, tree_result)

    # ── 3. Assemble SimulationResult ──
    return SimulationResult(
        snapshot_date=mc_result["snapshot_date"],
        n_iterations=mc_result["n_iterations"],
        seed=mc_result["seed"],
        standings=standings,
        teams=mc_result["teams"],
        playoff_ties=playoff_result["ties"],
        playoff_winners=playoff_result["winners"],
        bracket_rounds=tree_result["rounds"],
        bracket_champion=tree_result["champion"],
        stages=stages,
    )


def main() -> None:
    """Entry point: parse args, run simulation, display results, optionally export JSON."""
    args = _parse_args()

    # Resolve data directory
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
    )
    fixtures_path = os.path.join(data_dir, "fixtures.json")
    with open(fixtures_path) as f:
        fixtures = json.load(f)

    # Extract team names from fixtures and fetch Elo ratings
    team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
    elo_ratings = fetch_team_elos(team_names)

    # Determine seed
    seed = args.seed if args.seed is not None else random.randrange(10000)

    # Run simulation
    result = build_simulation_result(
        fixtures, elo_ratings, seed, args.iterations,
    )

    # Display results in D-06 tournament chronology order
    print_summary(result)
    print_league_table(result)
    print_playoff_rounds(result)
    print_knockout_bracket(result)
    print_odds(result)

    # JSON export (if --output given)
    if args.output:
        with open(args.output, "w") as f:
            json.dump(asdict(result), f, indent=2)
        print(f"JSON written to {args.output}")


if __name__ == "__main__":
    main()
