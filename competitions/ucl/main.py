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
    print_calibration_summary,
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


def _get_config_dir() -> str:
    """Return absolute path to competitions/ucl/config/ directory.

    Used for standardized config file resolution (signal_weights.json, etc.).
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config",
    )


def _setup_logging(verbose: bool) -> None:
    """Configure logging based on --verbose flag.

    In verbose mode: DEBUG level to stderr with timestamp format.
    In normal mode: WARNING level (suppress info/debug).
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _validate_args(args: argparse.Namespace) -> None:
    """Validate CLI argument combinations. Exits with error on invalid combos."""
    if args.calibrate and args.what_if_list:
        print(
            "Error: --calibrate and --what-if are incompatible. "
            "Calibration is a standalone operation that does not run simulation.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.report and args.calibrate:
        print(
            "Error: --report requires a simulation run. "
            "Cannot combine with --calibrate (standalone mode).",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.mode == "replay" and not args.replay_data:
        print(
            "Error: --mode replay requires --replay-data PATH",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.mode == "live" and not args.api_key and not os.environ.get("BSD_API_KEY"):
        print(
            "Error: --mode live requires BSD_API_KEY (set via --api-key or env var)",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.calibrate and not args.replay_data:
        print(
            "Error: --calibrate requires --replay-data PATH",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.calibrate_temp and not args.replay_data:
        print(
            "Error: --calibrate-temp requires --replay-data PATH",
            file=sys.stderr,
        )
        sys.exit(1)


class _EmptyResultProvider:
    """Minimal stub for RollingFormSignal — no historical results available."""
    def get_team_results(self, team: str, before_date: str | None = None, limit: int = 10) -> list[dict]:
        return []

def _ensure_utf8_mode() -> None:
    """Configure stdout/stderr for UTF-8 on Windows.

    Python on Windows defaults to the system's active code page (e.g., 437 or 1252),
    which cannot encode characters outside the legacy charset. This function:
      1. Reconfigures stdout/stderr to use UTF-8 encoding.
      2. Is a no-op on non-Windows platforms or if already UTF-8.

    Called once at the top of main() before any output is produced.
    """
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # Python < 3.7 does not have reconfigure(); fall back silently.
            pass


# Enable ANSI color support on Windows 10+ via ENABLE_VIRTUAL_TERMINAL_PROCESSING.
# The `os.system("")` call loads the VT-processing feature into the console's
# output mode, allowing \033[ escape sequences to work in cmd.exe / PowerShell.
# Without this, ANSI codes appear as raw text. Safe no-op on non-Windows.
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

    logger.debug("Building ensemble engine with %d signals: %s",
                 len(signals), [s.name for s in signals])

    weights_path = os.path.join(
        _get_config_dir(),
        "signal_weights.json",
    )

    if weights_override is not None:
        logger.debug("Using direct weight override: %s", weights_override)
        return EnsembleEngine(signals, weights=weights_override)
    if os.path.exists(weights_path):
        logger.debug("Loading weights from: %s", weights_path)
        return EnsembleEngine(signals, weights_path=weights_path)
    logger.debug("No weights found — using uniform fallback")
    return EnsembleEngine(signals)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments (D-02 through D-05)."""
    parser = argparse.ArgumentParser(
        prog="ucl-predict",
        description="UEFA Champions League 2025/26 Monte Carlo predictor.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Simulation control ──
    sim_group = parser.add_argument_group("Simulation options")
    sim_group.add_argument(
        "-n", "--iterations", type=int, default=10000,
        metavar="N", help="Number of Monte Carlo iterations (default: 10000)",
    )
    sim_group.add_argument(
        "-s", "--seed", type=int, default=None,
        metavar="N", help="Random seed for reproducible simulation",
    )
    sim_group.add_argument(
        "--use-glicko", action="store_true",
        help="Enable Bayesian/Glicko-1 uncertainty propagation. "
             "Samples team strengths from N(μ, σ²) per MC iteration "
             "instead of using fixed point estimates.",
    )
    sim_group.add_argument(
        "--calibrated", type=str, default=None,
        nargs="?", const="auto",
        choices=["auto", "on", "off"],
        metavar="MODE",
        help="Force calibration on/off. 'auto' (default): apply calibration "
             "when config/calibration.json exists and T != 1.0. "
             "'on': force calibration on. 'off': skip calibration for this run.",
    )
    sim_group.add_argument(
        "--show-ci", type=str, default=None,
        nargs="?", const="auto",
        choices=["auto", "on", "off"],
        metavar="MODE",
        help="Show confidence intervals on champion probabilities. "
             "'auto' (default): on when calibration is active, off otherwise. "
             "'on': always show. 'off': always hide.",
    )
    sim_group.add_argument(
        "-o", "--output", type=str, default=None,
        metavar="FILE", help="Write JSON output to FILE (stdout still prints text)",
    )

    # ── Data source ──
    data_group = parser.add_argument_group("Data source options")
    data_group.add_argument(
        "--fixture-source", type=str, default="auto",
        choices=["auto", "repo", "bsd"],
        help="Fixture source: auto (try BSD, fallback repo), "
             "repo (force repo), bsd (force BSD, fail if unavailable)",
    )
    data_group.add_argument(
        "--api-key", type=str, default=None,
        metavar="KEY", help="BSD API key (default: BSD_API_KEY env var)",
    )
    data_group.add_argument(
        "--mode", type=str, default="simulate",
        choices=["simulate", "replay", "live"],
        help="Simulation mode: simulate (default), replay, or live",
    )
    data_group.add_argument(
        "--replay-data", type=str, default=None,
        metavar="FILE",
        help="JSON file with played match results (required for replay mode)",
    )

    # ── Analysis ──
    analysis_group = parser.add_argument_group("Analysis options")
    analysis_group.add_argument(
        "--validate", action="store_true",
        help="Cross-check predictions against real BSD match results",
    )
    analysis_group.add_argument(
        "--tier",
        choices=["cross-tournament", "walk-forward", "replay", "all"],
        default="all",
        help="Validation tier to run (default: all tiers)",
    )
    analysis_group.add_argument(
        "--what-if", type=str, default=None,
        action="append", dest="what_if_list",
        metavar="TEAM.PARAM=VALUE",
        help="Run counterfactual analysis: modify a parameter and re-run simulation. "
             "Repeatable for multiple changes. "
             "Supported: Elo only (--what-if Arsenal.elo=1960). "
             "Example: --what-if 'Arsenal.elo=1960' --what-if 'RealMadrid.elo=2100'",
    )
    analysis_group.add_argument(
        "--report", type=str, default=None,
        metavar="FILE",
        help="Write structured report to FILE (JSON with simulation, signal breakdown, "
             "validation, and counterfactual results)",
    )
    analysis_group.add_argument(
        "--calibrate", action="store_true",
        help="Run weight calibration offline using replay data (requires --replay-data)",
    )
    analysis_group.add_argument(
        "--calibrate-temp", type=str, default=None,
        metavar="FILE",
        help="Run temperature calibration on replay data and save to config/calibration.json. "
             "Requires --replay-data FILE. Fits simplex temperature scaling (T parameter) "
             "by minimizing multiclass log-loss via Brent's method.",
    )

    # ── Signals ──
    signal_group = parser.add_argument_group("Signal options")
    signal_group.add_argument(
        "--weights", type=str, default=None,
        metavar="K=V,K=V",
        help="Override blend weights: --weights elo=0.4,market=0.3,form=0.2,squad=0.1 "
             "(auto-normalized, warns if sum != 1.0)",
    )
    signal_group.add_argument(
        "--show-breakdown", type=str, default=None,
        nargs="?", const="summary",
        choices=["summary", "match"],
        help="Show signal breakdown: 'summary' (default) for avg weights, "
             "'match' for per-match signal probabilities",
    )

    # ── Diagnostics ──
    diagnostic_group = parser.add_argument_group("Diagnostic options")
    diagnostic_group.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging to stderr. Shows signal evaluation times, "
             "provider selection, MC iteration progress.",
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


def _load_calibration() -> dict | None:
    """Load temperature calibration from config file.

    Returns:
        Dict with calibration data if calibration file exists and is valid,
        None otherwise.  Dict keys: T, alpha, log_loss, log_loss_before,
        n_samples.
    """
    cal_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config",
        "calibration.json",
    )
    if not os.path.exists(cal_path):
        return None

    try:
        with open(cal_path) as f:
            data = json.load(f)
        # Normalise to canonical keys
        result: dict = {
            "T": 1.0,
            "alpha": 1.0,
            "log_loss": None,
            "log_loss_before": None,
            "n_samples": 0,
            "ece": None,
        }
        if "T" in data:
            result["T"] = float(data["T"])
            result["alpha"] = 1.0 / result["T"]
        elif "alpha" in data:
            result["alpha"] = float(data["alpha"])
            result["T"] = 1.0 / result["alpha"]

        result["log_loss"] = data.get("log_loss")
        result["log_loss_before"] = data.get("log_loss_before")
        result["n_samples"] = data.get("n_samples", 0)
        result["ece"] = data.get("ece")

        return result
    except (json.JSONDecodeError, KeyError, ValueError, ZeroDivisionError):
        pass

    return None


def build_simulation_result(
    fixtures: FixtureSchedule,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
    rating_system=None,
    compute_ci: bool = False,
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
    played_matches:
        Pre-played match results for replay/live mode.
    rating_system:
        Optional :class:`~football_core.glicko.RatingSystem` for
        Glicko-1 uncertainty propagation.  When provided, runs
        :func:`run_monte_carlo_glicko` instead of :func:`run_monte_carlo`.
    compute_ci:
        If True, compute bootstrap CIs on champion probabilities
        (default False).  Passed through to the MC loop.

    Returns
    -------
    SimulationResult
        Fully populated result contract with MC probabilities + bracket snapshot.
    """
    # Convert FixtureSchedule to legacy dict format for engine compatibility
    fixtures_dict = {"schedule": asdict(fixtures)}

    # ── 1. Run Monte Carlo for aggregated probabilities ──
    using_glicko = rating_system is not None
    if using_glicko:
        from competitions.ucl.src.simulation import run_monte_carlo_glicko

        mc_result = run_monte_carlo_glicko(
            fixtures_dict,
            rating_system,
            n_iterations=n_iterations,
            seed=seed,
            played_matches=played_matches,
            compute_ci=compute_ci,
        )
    else:
        mc_result = run_monte_carlo(
            fixtures_dict,
            elo_ratings=elo_ratings,
            n_iterations=n_iterations,
            seed=seed,
            played_matches=played_matches,
            compute_ci=compute_ci,
        )

    # ── 2. Run one representative iteration for bracket display ──
    # Use the same seed so the first iteration is deterministic
    rng = random.Random(seed)
    bracket_elos = rating_system.to_elo_dict() if using_glicko else elo_ratings
    standings = simulate_league_phase(fixtures_dict, bracket_elos, rng, played_matches=played_matches)

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
        standings, bracket_elos, rng,
        pairings_data=pairings_data,
    )
    bracket = build_r16_bracket(
        standings, playoff_result,
        bracket_data=bracket_data,
    )
    tree_result = simulate_knockout_tree(bracket, bracket_elos, rng)
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
    _ensure_utf8_mode()
    args = _parse_args()

    # ── Phase 11: Logging setup and argument validation ──
    _setup_logging(args.verbose)
    _validate_args(args)

    # ── Temperature calibration mode (offline, standalone — Phase 10) ──
    if args.calibrate_temp:
        if not args.replay_data:
            print(
                "Error: --calibrate-temp requires --replay-data PATH",
                file=sys.stderr,
            )
            sys.exit(1)

        from football_core.blender import CalibrationPipeline, temperature_scale
        from football_core.evaluation import MatchOutcome

        # Load replay data
        with open(args.replay_data) as f:
            replay_raw = json.load(f)

        # Flatten matchday structure if needed
        if isinstance(replay_raw, list) and replay_raw and isinstance(replay_raw[0], list):
            all_matches = [m for md in replay_raw for m in md]
        else:
            all_matches = replay_raw if isinstance(replay_raw, list) else []

        if not all_matches:
            print("Error: No matches found in replay data.", file=sys.stderr)
            sys.exit(1)

        # Build EnsembleEngine and evaluate all matches
        elo_ratings = fetch_team_elos(
            list(set(m.get("team_a", "") for m in all_matches)
                 | set(m.get("team_b", "") for m in all_matches))
        )
        engine = _build_signal_engine(elo_ratings)
        signal_context = PredictionContext(
            fixtures=all_matches,
            elo_ratings=elo_ratings,
            played_results=[],
        )

        predictions: list = []
        outcomes: list = []
        skipped = 0

        for match in all_matches:
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")
            if not team_a or not team_b:
                skipped += 1
                continue

            # Get blended prediction
            pred = engine.evaluate(match, signal_context)
            predictions.append(pred)

            # Get actual outcome
            home_score = match.get("home_score", 0) or match.get("goals_home", 0)
            away_score = match.get("away_score", 0) or match.get("goals_away", 0)
            if isinstance(home_score, str):
                home_score = int(home_score.split("-")[0]) if "-" in home_score else int(home_score)
            if isinstance(away_score, str):
                away_score = int(away_score.split("-")[1]) if "-" in away_score else int(away_score)
            outcomes.append(MatchOutcome(int(home_score), int(away_score)))

        if skipped:
            print(f"Warning: skipped {skipped} matches with missing team data", file=sys.stderr)

        if len(predictions) < 5:
            print(
                f"Error: Only {len(predictions)} valid matches — need at least 5 for calibration.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Fit CalibrationPipeline
        pipe = CalibrationPipeline()
        alpha = pipe.fit(predictions, outcomes)

        # Save to config/calibration.json
        config_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config",
        )
        os.makedirs(config_dir, exist_ok=True)
        cal_path = os.path.join(config_dir, "calibration.json")
        pipe.save(cal_path)

        print(
            f"Calibrated: α={alpha:.4f} (T={pipe.T_:.4f}) "
            f"log-loss improved from {pipe.log_loss_before_:.4f} to {pipe.log_loss_:.4f}"
        )
        print(f"Calibration config saved to: {cal_path}")
        return

    # ── Weight calibration mode (offline, standalone — D-03, D-07) ──
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

    rating_system = None
    if getattr(args, 'use_glicko', False):
        # Glicko path: fetch ratings as RatingSystem with uncertainty
        from competitions.ucl.src.elo_fetcher import fetch_team_ratings
        rating_system = fetch_team_ratings(team_names)
        elo_ratings = rating_system.to_elo_dict()  # point estimates for signal blending
        logger.info("Using Glicko-1 rating system with %d teams", len(team_names))
    else:
        elo_ratings = fetch_team_elos(team_names)

    # Determine seed
    seed = args.seed if args.seed is not None else random.randrange(10000)

    # ── Phase 10, Plan 03: Resolve compute_ci before simulation ──
    cal_data_for_ci = _load_calibration()
    cal_active_for_ci = (
        cal_data_for_ci is not None
        and abs(cal_data_for_ci["T"] - 1.0) > 1e-9
    )

    compute_ci = False
    if args.show_ci == "on":
        compute_ci = True
    elif args.show_ci == "auto" or args.show_ci is None:
        if cal_active_for_ci:
            compute_ci = True
    if args.calibrated == "on":
        compute_ci = True

    # Run simulation via orchestrator (D-05: mode routing in orchestrator.py)
    from competitions.ucl.src.orchestrator import run_simulation

    logger.info("Running simulation: %d iterations, seed=%d", args.iterations, seed)
    import time as _time
    _sim_start = _time.time()
    result = run_simulation(
        fixtures_schedule, elo_ratings, seed, args.iterations,
        args, data_dir,
        rating_system=rating_system,
        compute_ci=compute_ci,
    )
    _sim_duration = _time.time() - _sim_start
    logger.info("Simulation complete: %.2f seconds", _sim_duration)

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
    logger.info("Evaluating %d match signals...", len(signal_matches))
    _eval_start = _time.time()
    blended_predictions = [engine.evaluate(m, signal_context) for m in signal_matches]
    _eval_duration = _time.time() - _eval_start
    logger.debug("Signal evaluation: %d matches in %.2f seconds (%.0f ms/match)",
                 len(signal_matches), _eval_duration,
                 _eval_duration / max(len(signal_matches), 1) * 1000)

    # ── Phase 10: Apply temperature calibration at prediction time ──
    cal_active = cal_active_for_ci
    if cal_active:
        from football_core.blender import temperature_scale
        blended_predictions = [temperature_scale(p, cal_data_for_ci["T"]) for p in blended_predictions]
        logger.info("Applied temperature scaling T=%.4f to %d predictions",
                     cal_data_for_ci["T"], len(blended_predictions))

    if args.calibrated == "off":
        cal_active = False
        # Re-evaluate without calibration to get uncalibrated predictions
        blended_predictions = [engine.evaluate(m, signal_context) for m in signal_matches]

    # ── Resolve --show-ci display flag ──
    show_ci = False
    if args.show_ci == "on":
        show_ci = True
    elif args.show_ci == "auto" or args.show_ci is None:
        if cal_active:
            show_ci = True

    # Display results in D-06 tournament chronology order
    print_summary(result)
    if cal_active and cal_data_for_ci is not None:
        print_calibration_summary(cal_data_for_ci)
    print_league_table(result)
    print_playoff_rounds(result)
    print_knockout_bracket(result)
    print_odds(result, show_ci=show_ci)

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
