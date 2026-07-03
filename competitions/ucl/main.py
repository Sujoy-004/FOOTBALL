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
    print_signal_breakdown,
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
from football_core.signal import PredictionContext
from football_core.blender import EnsembleEngine, compute_signal_contributions

logger = logging.getLogger(__name__)


class _EmptyResultProvider:
    """Minimal stub for RollingFormSignal — no historical results available."""
    def get_team_results(self, team: str, before_date: str | None = None, limit: int = 10) -> list[dict]:
        return []

# Enable ANSI color support on Windows
os.system("")


def _build_signal_engine(
    elo_ratings: dict[str, float],
    weights_override: dict[str, float] | None = None,
) -> EnsembleEngine:
    """Build EnsembleEngine with 5 pre-configured signals and calibrated weights.

    Args:
        elo_ratings: {team: elo} dict for PredictionContext.
        weights_override: Optional --weights CLI override dict.

    Returns:
        Configured EnsembleEngine ready for evaluate() calls.
    """
    from football_core.signals.refined_elo import RefinedEloSignal
    from football_core.signals.market_odds import MarketOddsSignal
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signals.squad_value import SquadValueSignal
    from football_core.signals.rest_days import RestDaysSignal

    signals = [
        RefinedEloSignal(),
        MarketOddsSignal(),
        RollingFormSignal(result_provider=_EmptyResultProvider()),
        SquadValueSignal(),
        RestDaysSignal(),
    ]

    weights_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config",
        "signal_weights.json",
    )

    if weights_override is not None:
        return EnsembleEngine(signals, weights=weights_override)
    if os.path.exists(weights_path):
        return EnsembleEngine(signals, weights_path=weights_path)
    return EnsembleEngine(signals)


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
        "--tier",
        choices=["cross-tournament", "walk-forward", "replay", "all"],
        default="all",
        help="Validation tier to run (default: all tiers)",
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
    parser.add_argument(
        "--mode", type=str, default="simulate",
        choices=["simulate", "replay", "live"],
        help="Simulation mode: simulate (default), replay, or live",
    )
    parser.add_argument(
        "--replay-data", type=str, default=None,
        metavar="FILE",
        help="JSON file with played match results (required for replay mode)",
    )
    parser.add_argument(
        "--calibrate", action="store_true",
        help="Run weight calibration offline using replay data (requires --replay-data)",
    )
    parser.add_argument(
        "--weights", type=str, default=None,
        metavar="K=V,K=V",
        help="Override blend weights: --weights elo=0.4,market=0.3,form=0.2,squad=0.1 "
             "(auto-normalized, warns if sum != 1.0)",
    )
    parser.add_argument(
        "--show-breakdown", type=str, default=None,
        nargs="?", const="summary",
        choices=["summary", "match"],
        help="Show signal breakdown: 'summary' (default) for avg weights, "
             "'match' for per-match signal probabilities",
    )
    parser.add_argument(
        "--what-if", type=str, default=None,
        action="append", dest="what_if_list",
        metavar="TEAM.PARAM=VALUE",
        help="Run counterfactual analysis: modify a parameter and re-run simulation. "
             "Repeatable for multiple changes. "
             "Supported: Elo only (--what-if Arsenal.elo=1960). "
             "Example: --what-if 'Arsenal.elo=1960' --what-if 'RealMadrid.elo=2100'",
    )
    parser.add_argument(
        "--report", type=str, default=None,
        metavar="FILE",
        help="Write structured report to FILE (JSON with simulation, signal breakdown, "
             "validation, and counterfactual results)",
    )
    return parser.parse_args(argv)


def parse_weights(weights_str: str | None) -> dict[str, float] | None:
    """Parse --weights CLI override string into {name: weight} dict.

    Format: "elo=0.4,market=0.3,form=0.2,squad=0.1"
    Auto-normalizes to sum 1.0. Emits warning to stderr if sum != 1.0.

    Returns None if weights_str is None (no override).
    Raises SystemExit on malformed input.
    """
    if weights_str is None:
        return None

    weights: dict[str, float] = {}
    pairs = weights_str.split(",")
    for pair in pairs:
        pair = pair.strip()
        if "=" not in pair:
            print(
                f"Error: invalid --weights format '{pair}'. Use K=V format "
                f"(e.g., elo=0.4,market=0.3)",
                file=sys.stderr,
            )
            sys.exit(1)
        key, val_str = pair.split("=", 1)
        key = key.strip()
        val_str = val_str.strip()
        if not key:
            print(f"Error: empty key in --weights '{pair}'", file=sys.stderr)
            sys.exit(1)
        try:
            val = float(val_str)
        except ValueError:
            print(
                f"Error: non-numeric weight value '{val_str}' for signal '{key}'",
                file=sys.stderr,
            )
            sys.exit(1)
        if val < 0:
            print(
                f"Error: negative weight {val} for signal '{key}'",
                file=sys.stderr,
            )
            sys.exit(1)
        weights[key] = val

    if not weights:
        print("Error: --weights must specify at least one key=value pair", file=sys.stderr)
        sys.exit(1)

    # Auto-normalize per D-05
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:
        print(
            f"Warning: --weights sum={total:.4f} != 1.0 — auto-normalizing",
            file=sys.stderr,
        )
        weights = {k: v / total for k, v in weights.items()}

    return weights


def _parse_what_if(what_if_list: list[str] | None) -> list[dict]:
    """Parse --what-if arguments into structured modifications.

    Each argument has format: TEAM.PARAM=VALUE
    Supported params: elo (float)

    Returns list of dicts: [{team, param, value}, ...]
    Returns empty list if what_if_list is None or empty.

    Raises SystemExit on malformed input with clear error messages.
    """
    if not what_if_list:
        return []

    supported_params = {"elo"}
    modifications: list[dict] = []

    for arg in what_if_list:
        # Check format: must contain a dot and an equals sign
        if "." not in arg or "=" not in arg:
            print(
                f"Error: invalid --what-if format '{arg}'. "
                f"Use TEAM.PARAM=VALUE format (e.g., 'Arsenal.elo=1960').",
                file=sys.stderr,
            )
            sys.exit(1)

        # Split on the FIRST dot and the FIRST equals
        dot_idx = arg.index(".")
        eq_idx = arg.index("=", dot_idx)

        if dot_idx == 0 or eq_idx <= dot_idx + 1:
            print(
                f"Error: invalid --what-if format '{arg}'. "
                f"Team name must not be empty.",
                file=sys.stderr,
            )
            sys.exit(1)

        team = arg[:dot_idx]
        param = arg[dot_idx + 1:eq_idx]
        value_str = arg[eq_idx + 1:]

        if not param:
            print(
                f"Error: empty parameter in --what-if '{arg}'.",
                file=sys.stderr,
            )
            sys.exit(1)

        if param not in supported_params:
            supported_str = ", ".join(sorted(supported_params))
            print(
                f"Error: unsupported parameter '{param}' in --what-if '{arg}'. "
                f"Supported parameters: {supported_str}",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            value = float(value_str)
        except ValueError:
            print(
                f"Error: non-numeric value '{value_str}' for parameter "
                f"'{param}' in --what-if '{arg}'.",
                file=sys.stderr,
            )
            sys.exit(1)

        if value < 0:
            print(
                f"Error: negative value {value} for parameter "
                f"'{param}' in --what-if '{arg}'. Elo must be positive.",
                file=sys.stderr,
            )
            sys.exit(1)

        modifications.append({"team": team, "param": param, "value": value})

    return modifications


def _run_counterfactual(
    what_if_changes: list[dict],
    elo_ratings: dict[str, float],
    fixtures_schedule: FixtureSchedule,
    seed: int,
    n_iterations: int,
    args: argparse.Namespace,
    data_dir: str,
) -> tuple[SimulationResult, list[str]]:
    """Run counterfactual simulation with modified parameters.

    Deep-copies elo_ratings, applies modifications, and re-runs the
    full MC simulation with adjusted seed (base_seed + 1).

    Args:
        what_if_changes: List of {team, param, value} dicts from _parse_what_if().
        elo_ratings: Base {team: elo} dict (not mutated).
        fixtures_schedule: FixtureSchedule for the tournament.
        seed: Base random seed for reproducibility.
        n_iterations: Number of MC iterations.
        args: Parsed CLI args (passed through to build_simulation_result).
        data_dir: Path to competition data directory.

    Returns:
        Tuple of (counterfactual SimulationResult, list of change description strings).
    """
    # Deep-copy to avoid mutating original
    modified_elos = dict(elo_ratings)

    change_descriptions: list[str] = []
    for change in what_if_changes:
        team = change["team"]
        param = change["param"]
        value = change["value"]

        if param == "elo":
            old_val = modified_elos.get(team, 1500.0)
            modified_elos[team] = value
            delta = int(value - old_val)
            if delta >= 0:
                change_descriptions.append(f"{team}.elo={value} (was {old_val:.0f}, +{delta})")
            else:
                change_descriptions.append(f"{team}.elo={value} (was {old_val:.0f}, {delta})")

    # Re-run simulation with modified Elo and adjusted seed
    from competitions.ucl.src.orchestrator import run_simulation

    result = run_simulation(
        fixtures_schedule, modified_elos, seed + 1, n_iterations,
        args, data_dir,
    )

    return result, change_descriptions


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


def _run_validation_suite(
    args: argparse.Namespace,
    elo_ratings: dict[str, float],
    fixtures_schedule: FixtureSchedule,
    data_dir: str,
) -> dict:
    """Execute validation pipeline using ValidationSuite.

    Parameters
    ----------
    args :
        Parsed CLI arguments.
    elo_ratings :
        {team: Elo} ratings for all teams.
    fixtures_schedule :
        Loaded fixture schedule from provider.
    data_dir :
        Path to competition data directory.

    Returns
    -------
    dict
        Combined validation report from all requested tiers.
    """
    from competitions.ucl.src.validation_suite import ValidationSuite

    engine = _build_signal_engine(elo_ratings, parse_weights(args.weights))

    # Build seasons_data from available sources
    fixture_dict = {"schedule": asdict(fixtures_schedule)}
    team_names = [t["name"] for t in fixture_dict["schedule"]["teams"]]

    # Use the fixture schedule to construct a minimal season data
    current_season_id = "current"
    matches: list[dict] = []
    for md in fixture_dict["schedule"]["matchdays"]:
        for m in md:
            matches.append({
                "match_id": m.get("match_id", ""),
                "team_a": m.get("team_a", ""),
                "team_b": m.get("team_b", ""),
                "winner": None,
                "is_draw": False,
                "home_score": 0,
                "away_score": 0,
            })

    standings = [
        {"team": t, "position": i + 1, "elo": elo_ratings.get(t, 1500.0)}
        for i, t in enumerate(team_names)
    ]

    seasons_data: dict[str, dict] = {
        current_season_id: {
            "matches": matches,
            "teams": team_names,
            "standings": standings,
        },
    }

    suite = ValidationSuite(engine, seasons_data)

    # Load replay data if available
    replay_data: list[list[dict]] | None = None
    if args.replay_data:
        try:
            with open(args.replay_data) as f:
                raw = json.load(f)
            # Handle both flat list and nested matchday structure
            if isinstance(raw, list):
                if raw and isinstance(raw[0], list):
                    replay_data = raw
                else:
                    # Flat list — wrap in single matchday
                    replay_data = [raw]
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading replay data: {e}", file=sys.stderr)
            sys.exit(1)

    # Run requested tier(s)
    if args.tier == "all":
        report = suite.run_all(replay_matchdays=replay_data)
    elif args.tier == "cross-tournament":
        result = suite.run_tier_1_cross_tournament()
        report = {
            "phase": 9,
            "date": result.date,
            "uncalibrated": True,
            "tournament_level": {
                "trps": result.metrics.get("trps", 0.0),
                "champion_accuracy": result.metrics.get("champion_accuracy", 0.0),
                "stage_accuracy": result.metrics.get("stage_accuracy", 0.0),
            },
            "n_matches_total": result.n_matches,
            "n_seasons": result.n_seasons,
        }
        if result.details:
            report["cross_tournament_details"] = result.details
    elif args.tier == "walk-forward":
        result = suite.run_tier_2_walk_forward()
        report = {
            "phase": 9,
            "date": result.date,
            "uncalibrated": True,
            "match_level": {
                "log_loss": result.metrics.get("log_loss", 0.0),
                "brier": result.metrics.get("brier", 0.0),
                "ece": result.metrics.get("ece", 0.0),
            },
            "n_matches_total": result.n_matches,
            "n_seasons": result.n_seasons,
        }
        if result.details:
            report["walk_forward_details"] = result.details
    elif args.tier == "replay":
        if not replay_data:
            print("Error: --replay-data PATH required for --tier replay",
                  file=sys.stderr)
            sys.exit(1)
        result = suite.run_tier_3_replay(replay_data)
        report = {
            "phase": 9,
            "date": result.date,
            "uncalibrated": True,
            "calibration": {
                "ece": result.metrics.get("ece", 0.0),
                "n_decision_points": result.metrics.get("n_decision_points", 0),
            },
            "n_matches_total": result.n_matches,
            "n_seasons": result.n_seasons,
        }
        if result.details:
            report["replay_details"] = result.details
    else:
        print(f"Error: unknown tier '{args.tier}'", file=sys.stderr)
        sys.exit(1)

    return report


def main() -> None:
    """Entry point: parse args, run simulation, display results, optionally export JSON."""
    args = _parse_args()

    # ── Calibration mode (offline, standalone — D-03, D-07) ──
    if args.calibrate:
        if not args.replay_data:
            print(
                "Error: --calibrate requires --replay-data PATH",
                file=sys.stderr,
            )
            sys.exit(1)

        if getattr(args, 'season', None):
            print(
                "Error: --season convenience flag not yet implemented. Use --replay-data.",
                file=sys.stderr,
            )
            sys.exit(1)

        from competitions.ucl.src.calibrate import run_calibration

        result = run_calibration(replay_data_path=args.replay_data)
        print(f"Calibration complete. {result['n_matches']} matches processed.")
        print(f"Computed weights for {len(result['weights'])} signals:")
        for sig, w in sorted(result["weights"].items()):
            print(f"  {sig}: {w:.4f}")
        return

    # ── Parse --weights override ──
    parsed_weights = parse_weights(args.weights)

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

    # Run simulation via orchestrator (D-05: mode routing in orchestrator.py)
    from competitions.ucl.src.orchestrator import run_simulation

    result = run_simulation(
        fixtures_schedule, elo_ratings, seed, args.iterations,
        args, data_dir,
    )

    # ── Phase 8: Signal blending ──
    engine = _build_signal_engine(elo_ratings, parsed_weights)
    signal_matches: list[dict] = []
    for matchday in fixtures_schedule.matchdays:
        for match in matchday:
            signal_matches.append({
                "team_a": match.team_a,
                "team_b": match.team_b,
                "match_id": match.match_id,
            })
    signal_context = PredictionContext(
        fixtures=signal_matches,
        elo_ratings=elo_ratings,
        played_results=[],
    )
    blended_predictions = [engine.evaluate(m, signal_context) for m in signal_matches]

    # Display results in D-06 tournament chronology order
    print_summary(result)
    print_league_table(result)
    print_playoff_rounds(result)
    print_knockout_bracket(result)
    print_odds(result)

    # ── Phase 11: Signal contribution breakdown (always-on) ──
    champion_team = result.bracket_champion
    if champion_team and champion_team in result.teams:
        champion_prob = result.teams[champion_team].get("champion_prob", 0.0) * 100
        contributions = {}
        if blended_predictions:
            contributions = compute_signal_contributions(
                blended_predictions, champion_team, engine.weights,
                match_fixtures=signal_matches,
            )
        print_signal_breakdown(contributions, champion_team, champion_prob)

    # ── Phase 11: Counterfactual analysis (--what-if) ──
    counterfactual_results: list[tuple[SimulationResult, list[str]]] = []
    if args.what_if_list:
        what_if_changes = _parse_what_if(args.what_if_list)
        if what_if_changes:
            cf_result, cf_descriptions = _run_counterfactual(
                what_if_changes, elo_ratings, fixtures_schedule,
                seed, args.iterations, args, data_dir,
            )
            counterfactual_results.append((cf_result, cf_descriptions))
            from competitions.ucl.display import print_counterfactual_comparison
            print_counterfactual_comparison(result, cf_result, cf_descriptions)

    # ── Phase 11: Report generation (--report) ──
    if args.report:
        from competitions.ucl.report import build_report, write_report

        report = build_report(
            result,
            blended_predictions=blended_predictions,
            engine=engine,
            counterfactual_results=counterfactual_results if counterfactual_results else None,
            match_fixtures=signal_matches,
        )
        write_report(report, args.report)
        print(f"Report written to {args.report}")

    # ── Signal breakdown display (Phase 8, D-07) ──
    if args.show_breakdown:
        from competitions.ucl.display import show_breakdown, print_value_plays
        show_breakdown(blended_predictions, mode=args.show_breakdown)
        print_value_plays(blended_predictions)

    # Validation (Phase 9 — three-tier validation suite)
    if args.validate:
        # Run the validation suite (no API key required — uses local data)
        try:
            validation_report = _run_validation_suite(
                args, elo_ratings, fixtures_schedule, data_dir,
            )
        except Exception as e:
            print(f"Warning: Validation suite failed: {e}", file=sys.stderr)
            validation_report = None

        if validation_report:
            # Print summary
            print("\n── Validation Suite Results ──────────────────────────────")

            if "tournament_level" in validation_report:
                tl = validation_report["tournament_level"]
                print(f"  TRPS:               {tl.get('trps', 'N/A'):>10}")
                print(f"  Champion accuracy:  {tl.get('champion_accuracy', 'N/A'):>10}")
                print(f"  Stage accuracy:     {tl.get('stage_accuracy', 'N/A'):>10}")

            if "match_level" in validation_report:
                ml = validation_report["match_level"]
                print(f"  Log Loss:           {ml.get('log_loss', 'N/A'):>10}")
                print(f"  Brier:              {ml.get('brier', 'N/A'):>10}")
                print(f"  ECE:                {ml.get('ece', 'N/A'):>10}")

            if "calibration" in validation_report:
                cal = validation_report["calibration"]
                print(f"  Replay ECE:         {cal.get('ece', 'N/A'):>10}")
                print(f"  Decision points:    {cal.get('n_decision_points', 'N/A'):>10}")

            # Save report if --output given
            if args.output:
                with open(args.output, "w") as f:
                    json.dump(validation_report, f, indent=2)
                print(f"Validation report saved to: {args.output}")

        # Also run old-style BSD validation if API key available (Phase 4 compat)
        api_key = args.api_key or os.environ.get("BSD_API_KEY")
        if api_key:
            try:
                from competitions.ucl.src.fetcher import fetch_ucl_matches

                team_aliases_path = os.path.join(data_dir, "team_aliases.json")
                with open(team_aliases_path) as f:
                    team_aliases = json.load(f)
                real_matches = fetch_ucl_matches(
                    api_key, team_aliases, asdict(fixtures_schedule),
                )

                # Cross-check predictions vs real outcomes using expected_score from Elo
                validation_result = run_validation(result, real_matches, elo_ratings)

                # Store in result for JSON enrichment
                object.__setattr__(result, "validation", validation_result)

                # Print summary table to stdout
                from competitions.ucl.display import print_validation_summary
                print_validation_summary(validation_result)
            except Exception:
                pass  # BSD validation is optional; don't crash

    # JSON export — only if NOT already written with validation
    elif args.output:
        with open(args.output, "w") as f:
            json.dump(asdict(result), f, indent=2)
        print(f"JSON written to {args.output}")


if __name__ == "__main__":
    main()
