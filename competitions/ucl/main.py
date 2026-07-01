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
import logging
import os
import random
import sys
from dataclasses import asdict
from datetime import datetime, timezone

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
from football_core.provider import FixtureSchedule, FixtureProviderError

logger = logging.getLogger(__name__)

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
    parser.add_argument(
        "--validate", action="store_true",
        help="Cross-check predictions against real BSD match results",
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        metavar="KEY", help="BSD API key (default: BSD_API_KEY env var)",
    )
    parser.add_argument(
        "--fixture-source", type=str, default="auto",
        choices=["auto", "repo", "bsd"],
        help="Fixture source: auto (try BSD, fallback repo), "
             "repo (force repo), bsd (force BSD, fail if unavailable)",
    )
    return parser.parse_args(argv)


def build_simulation_result(
    fixtures: FixtureSchedule,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> SimulationResult:
    """Run MC simulation + one representative bracket iteration, return SimulationResult.

    Parameters
    ----------
    fixtures:
        UCL FixtureSchedule from provider chain.
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
    # Convert FixtureSchedule to legacy dict format for engine compatibility
    fixtures_dict = {"schedule": asdict(fixtures)}

    # ── 1. Run Monte Carlo for aggregated probabilities ──
    mc_result = run_monte_carlo(
        fixtures_dict,
        elo_ratings=elo_ratings,
        n_iterations=n_iterations,
        seed=seed,
        played_matches=played_matches,
    )

    # ── 2. Run one representative iteration for bracket display ──
    # Use the same seed so the first iteration is deterministic
    rng = random.Random(seed)
    standings = simulate_league_phase(fixtures_dict, elo_ratings, rng, played_matches=played_matches)

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


def run_validation(
    simulation_result: SimulationResult,
    real_matches: list[dict],
    elo_ratings: dict[str, float],
) -> dict:
    """Cross-check simulation predictions against real match outcomes.

    For each real match, computes home-win probability from Elo ratings
    via expected_score() (same foundation as the simulation engine),
    then computes Brier, Log Loss, accuracy, and calibration ECE.

    Parameters
    ----------
    simulation_result:
        Frozen SimulationResult from MC simulation (validation field will be set by caller).
    real_matches:
        List of normalized BSD match dicts from fetch_ucl_matches().
    elo_ratings:
        {team_name: Elo} dict used in the simulation.

    Returns
    -------
    dict
        Validation result dict matching D-09 schema, ready for JSON enrichment.
    """
    from football_core.evaluation import compute_metrics, calibration_curve
    from football_core.elo import expected_score

    predictions: list[float] = []
    actuals: list[float] = []
    odds_predictions: list[float] = []
    odds_actuals: list[float] = []

    for match in real_matches:
        team_a = match["team_a"]
        team_b = match["team_b"]

        home_elo = elo_ratings.get(team_a, 1500.0)
        away_elo = elo_ratings.get(team_b, 1500.0)
        pred_home_win = expected_score(home_elo, away_elo)

        # Determine actual outcome
        if match.get("is_draw"):
            actual = 0.5
        elif match.get("winner") == team_a:
            actual = 1.0
        elif match.get("winner") == team_b:
            actual = 0.0
        else:
            continue  # skip matches with undetermined outcome

        predictions.append(pred_home_win)
        actuals.append(actual)

        # Extract market odds for comparison if available (D-03)
        if "odds" in match:
            odds_predictions.append(match["odds"]["home"])
            odds_actuals.append(actual)

    # Compute prediction metrics
    prediction_metrics = compute_metrics(predictions, actuals)
    calibration = calibration_curve(predictions, actuals)

    # Build result dict matching D-09 schema
    result: dict = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "n_matches_fetched": len(real_matches),
        "n_matches_matched": len(predictions),
        "n_odds_available": len(odds_predictions),
        "prediction_metrics": {
            "brier": round(prediction_metrics["brier"], 6),
            "log_loss": round(prediction_metrics["log_loss"], 6),
            "accuracy": round(prediction_metrics["accuracy"], 6),
            "n": prediction_metrics["n"],
        },
        "calibration": calibration,
    }

    # Add market odds metrics if available
    if odds_predictions:
        odds_metrics = compute_metrics(odds_predictions, odds_actuals)
        result["market_odds_metrics"] = {
            "brier": round(odds_metrics["brier"], 6),
            "log_loss": round(odds_metrics["log_loss"], 6),
            "n": odds_metrics["n"],
        }

    return result


def main() -> None:
    """Entry point: parse args, run simulation, display results, optionally export JSON."""
    args = _parse_args()

    # Resolve data directory
    data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
    )
    fixtures_path = os.path.join(data_dir, "fixtures.json")

    # Resolve fixture provider based on --fixture-source flag
    api_key = args.api_key or os.environ.get("BSD_API_KEY")
    fixture_source = args.fixture_source

    # Build teams_data from repo fixtures (needed for BSD provider construction)
    with open(fixtures_path) as f:
        repo_fixtures = json.load(f)
    teams_data = repo_fixtures["schedule"]["teams"]

    if fixture_source == "repo" or (fixture_source == "auto" and not api_key):
        from competitions.ucl.src.provider import RepoFixtureProvider
        provider = RepoFixtureProvider(fixtures_path=fixtures_path)
        fixtures_schedule = provider.load()
    else:
        from competitions.ucl.src.provider import BSDFixtureProvider, RepoFixtureProvider
        team_aliases_path = os.path.join(data_dir, "team_aliases.json")
        with open(team_aliases_path) as f:
            team_aliases = json.load(f)

        bsd_provider = BSDFixtureProvider(
            api_key=api_key,
            aliases=team_aliases,
            cache_dir=data_dir,
            teams_data=teams_data,
        )

        if fixture_source == "auto":
            try:
                fixtures_schedule = bsd_provider.load()
            except FixtureProviderError as e:
                logger.warning(
                    "BSD unavailable (%s) — falling back to RepoFixtureProvider", e,
                )
                provider = RepoFixtureProvider(fixtures_path=fixtures_path)
                fixtures_schedule = provider.load()
        else:
            fixtures_schedule = bsd_provider.load()

    # Extract team names from fixtures and fetch Elo ratings
    team_names = [t.name for t in fixtures_schedule.teams]
    elo_ratings = fetch_team_elos(team_names)

    # Determine seed
    seed = args.seed if args.seed is not None else random.randrange(10000)

    # Run simulation
    result = build_simulation_result(
        fixtures_schedule, elo_ratings, seed, args.iterations,
    )

    # Display results in D-06 tournament chronology order
    print_summary(result)
    print_league_table(result)
    print_playoff_rounds(result)
    print_knockout_bracket(result)
    print_odds(result)

    # Validation (Phase 4, D-01 through D-03)
    if args.validate:
        api_key = args.api_key or os.environ.get("BSD_API_KEY")
        if not api_key:
            print("Error: BSD_API_KEY not set. Provide --api-key or set BSD_API_KEY env var.")
            sys.exit(1)

        from competitions.ucl.src.fetcher import fetch_ucl_matches

        team_aliases_path = os.path.join(data_dir, "team_aliases.json")
        with open(team_aliases_path) as f:
            team_aliases = json.load(f)
        real_matches = fetch_ucl_matches(
            api_key, team_aliases, asdict(fixtures_schedule),
        )

        # Cross-check predictions vs real outcomes using expected_score from Elo
        validation_result = run_validation(result, real_matches, elo_ratings)

        # Store in result for JSON enrichment (frozen dataclass workaround)
        object.__setattr__(result, "validation", validation_result)

        # Print summary table to stdout
        from competitions.ucl.display import print_validation_summary
        print_validation_summary(validation_result)

        # Enrich JSON if --output given
        if args.output:
            output = asdict(result)
            with open(args.output, "w") as f:
                json.dump(output, f, indent=2)
            print(f"JSON enriched with validation: {args.output}")

    # JSON export (existing) — only if NOT already written with validation
    elif args.output:
        with open(args.output, "w") as f:
            json.dump(asdict(result), f, indent=2)
        print(f"JSON written to {args.output}")


if __name__ == "__main__":
    main()
