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
import signal
import sys
import time as _time_module
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

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
from competitions.ucl.src.live_state import (
    load_ucl_cache,
    save_ucl_cache,
    ucl_is_cache_valid,
)
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

    # --validate-calibrated without --validate is a standalone operation
    if args.validate_calibrated and args.validate:
        print(
            "Error: --validate-calibrated and --validate are incompatible. "
            "Use --validate-calibrated alone for calibrated validation, "
            "or --validate alone for uncalibrated.",
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
    """Build EnsembleEngine with 8 pre-configured signals and calibrated weights.

    Signals 1-5 use no external data (fallback to uniform when missing).
    Signals 6-8 require context.manager_data / context.player_data from BSD API
    and gracefully fall back to uniform when unavailable.

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
    from football_core.signals.availability import AvailabilitySignal
    from football_core.signals.manager_effect import ManagerEffectSignal
    from football_core.signals.defensive_quality import DefensiveQualitySignal
    from football_core.signals.player_form import PlayerFormSignal
    from football_core.signals.team_synergy import TeamSynergySignal

    signals = [
        RefinedEloSignal(),
        MarketOddsSignal(),
        RollingFormSignal(result_provider=_EmptyResultProvider()),
        SquadValueSignal(),
        RestDaysSignal(),
        AvailabilitySignal(),
        ManagerEffectSignal(),
        DefensiveQualitySignal(),
        PlayerFormSignal(),
        TeamSynergySignal(),
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
        "--watch", action="store_true",
        help="Enable continuous polling loop. Requires --mode live.",
    )
    data_group.add_argument(
        "--once", action="store_true",
        help="Single-cycle live execution: fetch, process, display, exit. Requires --mode live.",
    )
    data_group.add_argument(
        "--poll-interval", type=int, default=60,
        help="Polling interval in seconds (default: 60). Requires --mode live --watch.",
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
    analysis_group.add_argument(
        "--validate-calibrated", action="store_true",
        help="Run validation pipeline with temperature calibration applied. "
             "Re-runs Phase 9 validation tiers with calibrated probabilities "
             "and produces before/after comparison table. Requires calibration "
             "config to exist (run --calibrate-temp first).",
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

    # ── Calibration & Uncertainty (Phase 10) ──
    cal_group = parser.add_argument_group("Calibration & Uncertainty options")
    cal_group.add_argument(
        "--calibrated", type=str, default=None,
        nargs="?", const="auto",
        choices=["auto", "on", "off"],
        help="Control temperature calibration: 'on' (force calibration), "
             "'off' (skip calibration), or 'auto' (use config if available, "
             "default).  'auto' enables calibration when T != 1.0 in config.",
    )
    cal_group.add_argument(
        "--show-ci", type=str, default=None,
        nargs="?", const="auto",
        choices=["auto", "on", "off"],
        help="Control confidence interval display: 'on' (always show), "
             "'off' (never show), or 'auto' (show when calibration is active, "
             "default).",
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
        Dict with calibration metadata if config exists and is valid, None otherwise.
        Keys: T, alpha, log_loss, log_loss_before, n_samples, ece (optional).
        Returns None if file doesn't exist or is unreadable.
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
        result: dict = {}
        if "T" in data:
            result["T"] = float(data["T"])
        if "alpha" in data:
            result["alpha"] = float(data["alpha"])
            result.setdefault("T", 1.0 / result["alpha"])
        if "log_loss" in data and data["log_loss"] is not None:
            result["log_loss"] = float(data["log_loss"])
        if "log_loss_before" in data and data["log_loss_before"] is not None:
            result["log_loss_before"] = float(data["log_loss_before"])
        if "n_samples" in data:
            result["n_samples"] = int(data["n_samples"])
        if "ece" in data and data["ece"] is not None:
            result["ece"] = float(data["ece"])
        return result if "T" in result else None
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
        )
    else:
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


def _run_calibrated_validation(
    args: argparse.Namespace,
    elo_ratings: dict[str, float],
    fixtures_schedule: FixtureSchedule,
    data_dir: str,
) -> dict:
    """Run validation pipeline with temperature calibration applied.

    Loads calibration config, builds the standard validation suite, then
    applies temperature scaling to each match prediction before scoring.
    Produces a validation report with calibrated metrics.

    Parameters
    ----------
    args:
        Parsed CLI arguments.
    elo_ratings:
        {team: Elo} ratings for all teams.
    fixtures_schedule:
        Loaded fixture schedule from provider.
    data_dir:
        Path to competition data directory.

    Returns
    -------
    dict
        Calibrated validation report in same format as _run_validation_suite.
        Returns None if calibration config is not available.
    """
    # 1. Load calibration config
    raw_cal = _load_calibration()
    if raw_cal is None or "T" not in raw_cal:
        print("Error: --validate-calibrated requires calibration config. "
              "Run --calibrate-temp first.", file=sys.stderr)
        return None

    T = raw_cal["T"]
    from football_core.blender import temperature_scale

    # 2. Build the standard validation pipeline
    from competitions.ucl.src.validation_suite import ValidationSuite

    engine = _build_signal_engine(elo_ratings, parse_weights(args.weights))

    # 3. Build seasons_data from available sources
    fixture_dict = {"schedule": asdict(fixtures_schedule)}
    team_names = [t["name"] for t in fixture_dict["schedule"]["teams"]]

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

    standings_data = [
        {"team": t, "position": i + 1, "elo": elo_ratings.get(t, 1500.0)}
        for i, t in enumerate(team_names)
    ]

    seasons_data: dict[str, dict] = {
        current_season_id: {
            "matches": matches,
            "teams": team_names,
            "standings": standings_data,
        },
    }

    suite = ValidationSuite(engine, seasons_data)

    # Load replay data for Tier 3 calibration analysis
    replay_data: list[list[dict]] | None = None
    if args.replay_data:
        try:
            with open(args.replay_data) as f:
                raw = json.load(f)
            if isinstance(raw, list):
                if raw and isinstance(raw[0], list):
                    replay_data = raw
                else:
                    replay_data = [raw]
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load replay data: {e}", file=sys.stderr)

    # 4. Run validation tiers
    if args.tier == "all":
        report = suite.run_all(replay_matchdays=replay_data)
    elif args.tier == "walk-forward":
        result = suite.run_tier_2_walk_forward()
        report = {
            "phase": 10,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "uncalibrated": False,
            "calibrated": True,
            "calibration_T": T,
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
            "phase": 10,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "uncalibrated": False,
            "calibrated": True,
            "calibration_T": T,
            "calibration": {
                "ece": result.metrics.get("ece", 0.0),
                "n_decision_points": result.metrics.get("n_decision_points", 0),
            },
            "n_matches_total": result.n_matches,
            "n_seasons": result.n_seasons,
        }
        if result.details:
            report["replay_details"] = result.details
    elif args.tier == "cross-tournament":
        result = suite.run_tier_1_cross_tournament()
        report = {
            "phase": 10,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "uncalibrated": False,
            "calibrated": True,
            "calibration_T": T,
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
    else:
        print(f"Error: unknown tier '{args.tier}'", file=sys.stderr)
        sys.exit(1)

    # 5. Apply calibration to the report metrics by adjusting predictions
    # NOTE: The ValidationSuite evaluates matches using the base engine
    # without calibration. For a proper calibrated validation, we modify
    # the engine to apply temperature scaling at evaluation time.
    # Since engine.evaluate() returns BlendedPrediction, we wrap it.
    original_evaluate = engine.evaluate

    def _calibrated_evaluate(match, context):
        bp = original_evaluate(match, context)
        return temperature_scale(bp, T)

    engine.evaluate = _calibrated_evaluate  # type: ignore[assignment]

    # Re-run with calibrated engine
    try:
        if args.tier == "all" or args.tier == "walk-forward":
            cal_result = suite.run_tier_2_walk_forward()
            if "match_level" in report:
                report["match_level"]["log_loss"] = cal_result.metrics.get("log_loss", 0.0)
                report["match_level"]["brier"] = cal_result.metrics.get("brier", 0.0)
                report["match_level"]["ece"] = cal_result.metrics.get("ece", 0.0)
            report["n_matches_total"] = cal_result.n_matches

        if args.tier == "all" or args.tier == "replay":
            if replay_data:
                cal_result = suite.run_tier_3_replay(replay_data)
                if "calibration" in report:
                    report["calibration"]["ece"] = cal_result.metrics.get("ece", 0.0)
                    report["calibration"]["n_decision_points"] = (
                        cal_result.metrics.get("n_decision_points", 0)
                    )

        if args.tier == "all" or args.tier == "cross-tournament":
            cal_result = suite.run_tier_1_cross_tournament()
            if "tournament_level" in report:
                report["tournament_level"]["trps"] = cal_result.metrics.get("trps", 0.0)
                report["tournament_level"]["champion_accuracy"] = (
                    cal_result.metrics.get("champion_accuracy", 0.0)
                )
                report["tournament_level"]["stage_accuracy"] = (
                    cal_result.metrics.get("stage_accuracy", 0.0)
                )
    except Exception as e:
        print(f"Warning: Calibrated validation failed: {e}", file=sys.stderr)

    # Restore original evaluate
    engine.evaluate = original_evaluate

    return report


def _save_validation_baseline(
    baseline_path: str,
    uncalibrated_report: dict | None,
    calibrated_report: dict | None,
) -> dict:
    """Save or update validation baseline JSON with before/after data.

    Creates ``baseline.json`` at the given path with structure:
    {
      "baseline": {log_loss, ece, trps, timestamp, source},
      "calibrated": [{log_loss, ece, trps, timestamp, calibration_T, use_glicko}]
    }

    Parameters
    ----------
    baseline_path:
        Path to the baseline JSON file.
    uncalibrated_report:
        Uncalibrated validation report (from Phase 9 or current run).
    calibrated_report:
        Calibrated validation report (from --validate-calibrated).

    Returns
    -------
    dict
        The updated/fresh baseline dict.
    """
    # Try loading existing baseline
    existing: dict = {"baseline": None, "calibrated": []}
    if os.path.exists(baseline_path):
        try:
            with open(baseline_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            existing = {"baseline": None, "calibrated": []}

    # Update baseline if we have fresh uncalibrated data
    if uncalibrated_report is not None:
        ml = uncalibrated_report.get("match_level") or {}
        tl = uncalibrated_report.get("tournament_level") or {}
        existing["baseline"] = {
            "log_loss": ml.get("log_loss"),
            "ece": ml.get("ece", uncalibrated_report.get("calibration", {}).get("ece")),
            "trps": tl.get("trps"),
            "brier": ml.get("brier"),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "phase_09_validation",
        }

    # Append calibrated entry
    if calibrated_report is not None:
        ml = calibrated_report.get("match_level") or {}
        tl = calibrated_report.get("tournament_level") or {}
        cal_entry = {
            "log_loss": ml.get("log_loss"),
            "ece": ml.get("ece", calibrated_report.get("calibration", {}).get("ece")),
            "trps": tl.get("trps"),
            "brier": ml.get("brier"),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "calibration_T": calibrated_report.get("calibration_T"),
            "use_glicko": False,
        }
        existing.setdefault("calibrated", []).append(cal_entry)

    # Write to disk
    os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
    with open(baseline_path, "w") as f:
        json.dump(existing, f, indent=2)

    return existing


def _load_cache_ttls(data_dir: str) -> dict[str, int]:
    """Load per-signal cache TTLs from config/cache_ttls.json.

    Returns dict with defaults: {"odds": 12, "catboost": 24}.
    """
    config_path = os.path.join(data_dir, "..", "config", "cache_ttls.json")
    try:
        with open(config_path) as f:
            return dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"odds": 12, "catboost": 24}


def _merge_signals_into_history(
    matches: list[dict],
    signal_caches: dict[str, dict],
    prediction_history: list[dict],
) -> list[dict]:
    """Merge signal cache data into prediction_history for each match.

    Args:
        matches: List of BSD match event dicts (finished matches).
        signal_caches: {cache_key: {match_id: signal_data}} from cache files.
        prediction_history: Existing history list (mutated in-place for new entries).

    Returns:
        Updated prediction_history with new entries appended.
    """
    existing_mids = {e.get("match_id", "") for e in prediction_history if isinstance(e, dict)}

    for match in matches:
        mid = match.get("match_id", "")
        if not mid or mid in existing_mids:
            continue

        signals: dict[str, Any] = {}
        for cache_key, cache_data in signal_caches.items():
            if isinstance(cache_data, dict):
                match_signal = cache_data.get(mid)
                if match_signal is not None:
                    signals[cache_key] = match_signal

        entry: dict[str, Any] = {
            "match_id": mid,
            "home_team": match.get("home_team", ""),
            "away_team": match.get("away_team", ""),
            "home_score": match.get("home_score"),
            "away_score": match.get("away_score"),
            "signals": signals,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        prediction_history.append(entry)
        existing_mids.add(mid)

    return prediction_history


def _next_poll_sleep(interval: float, state: SimpleNamespace) -> None:
    """Sleep in 0.5s increments, checking running flag for responsive shutdown."""
    deadline = _time_module.time() + interval
    while state.running and _time_module.time() < deadline:
        _time_module.sleep(0.5)


def _historical_catch_up(
    data_dir: str,
    elo_ratings: dict[str, float],
    played: dict[str, dict],
    elo_applied: list[str],
) -> tuple[dict[str, dict], list[str]]:
    """Fetch all prior finished BSD matches on first run and process chronologically.

    Returns updated (played, elo_applied).
    """
    if played:
        return played, elo_applied

    from competitions.ucl.src.fetcher import fetch_raw_matches
    from competitions.ucl.src.live_state import save_ucl_played, save_ucl_elo_applied
    from competitions.ucl.src.elo_updater import apply_elo_update

    backoff = [1, 2, 4]
    raw = None
    for attempt, delay in enumerate(backoff):
        try:
            raw = fetch_raw_matches(data_dir=data_dir)
            if raw:
                break
        except Exception as e:
            logger.warning("BSD fetch failed (attempt %d/3): %s", attempt + 1, e)
            if attempt < len(backoff) - 1:
                _time_module.sleep(delay)
            continue

    if not raw:
        logger.warning("Historical catch-up: no data from BSD API")
        return played, elo_applied

    finished = [m for m in raw if m.get("status") == "finished"]
    finished.sort(key=lambda m: m.get("event_date", ""))

    ingested = 0
    for match in finished:
        mid = match.get("match_id", "")
        if not mid or mid in played:
            continue
        update = apply_elo_update(match, elo_ratings, elo_applied)
        if update:
            played[mid] = match
            ingested += 1

    if ingested:
        save_ucl_played(played, data_dir)
        save_ucl_elo_applied(elo_applied, data_dir)
        print(f"Historical catch-up: ingested {ingested} prior match(es)")

    return played, elo_applied


def _run_iteration(
    args: argparse.Namespace,
    data_dir: str,
    elo_ratings: dict[str, float],
    played: dict[str, dict],
    elo_applied: list[str],
    prediction_history: list[dict],
    state: SimpleNamespace,
) -> tuple[dict | None, dict[str, float] | None]:
    """Run one live monitor cycle: fetch -> process -> simulate -> display."""
    from competitions.ucl.src.live_state import save_ucl_played, save_ucl_elo_appended, save_ucl_prediction_history
    from competitions.ucl.src.elo_updater import apply_elo_update, sync_elo_from_clubelo
    from competitions.ucl.display import print_match_alert, print_elo_changes, print_heartbeat, print_simulation_duration, print_delta
    from competitions.ucl.src.fetcher import fetch_raw_matches
    from competitions.ucl.src.simulation import run_monte_carlo
    from competitions.ucl.result import SimulationResult

    try:
        raw = fetch_raw_matches(data_dir=data_dir)
    except Exception as e:
        logger.warning("BSD fetch failed: %s", e)
        print_heartbeat(
            datetime.now().strftime("%H:%M:%S"),
            args.poll_interval, 0,
        )
        return state.prev_probs, None

    new_matches: list[dict] = []
    if raw:
        for match in raw:
            mid = match.get("match_id", "")
            if not mid or mid in played:
                continue
            if match.get("status") != "finished":
                continue
            update = apply_elo_update(match, elo_ratings, elo_applied)
            if update:
                played[mid] = match
                new_matches.append(match)
                print_match_alert(match)
                print_elo_changes([update])

    if new_matches:
        save_ucl_played(played, data_dir)
        save_ucl_elo_applied(elo_applied, data_dir)

    # ClubElo sync (24h)
    if state.elo_last_sync_time == 0 or _time_module.time() - state.elo_last_sync_time > 86400:
        try:
            corrections = sync_elo_from_clubelo(
                {"_": {"elo": 1500}}, [], data_dir=data_dir,
            )
            if corrections:
                state.elo_last_sync_time = _time_module.time()
        except Exception as e:
            logger.warning("ClubElo sync failed: %s", e)

    if not new_matches:
        print_heartbeat(
            datetime.now().strftime("%H:%M:%S"),
            args.poll_interval, 0,
        )
        return state.prev_probs, None

    # Run MC simulation
    _sim_start = _time_module.time()
    try:
        from competitions.ucl.src.simulation import run_monte_carlo
        result = run_monte_carlo(
            teams=list(elo_ratings.keys()),
            elo_ratings=elo_ratings,
            n_iterations=args.iterations,
            seed=args.seed or 42,
        )
    except Exception as e:
        logger.error("Simulation failed: %s", e)
        return state.prev_probs, None
    sim_elapsed = _time_module.time() - _sim_start
    print_simulation_duration(sim_elapsed)

    return None, None


def main() -> None:
    """Entry point: parse args, run simulation, display results, optionally export JSON."""
    _ensure_utf8_mode()
    args = _parse_args()

    # --watch / --once / --poll-interval validation
    if args.watch and args.mode != "live":
        print("Error: --watch requires --mode live", file=sys.stderr)
        sys.exit(1)
    if args.once and args.mode != "live":
        print("Error: --once requires --mode live", file=sys.stderr)
        sys.exit(1)
    if args.poll_interval < 10:
        print(f"Warning: --poll-interval minimum is 10 seconds (got {args.poll_interval})", file=sys.stderr)
        args.poll_interval = 10

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

    # Run simulation via orchestrator (D-05: mode routing in orchestrator.py)
    from competitions.ucl.src.orchestrator import run_simulation

    logger.info("Running simulation: %d iterations, seed=%d", args.iterations, seed)
    import time as _time
    _sim_start = _time.time()
    result = run_simulation(
        fixtures_schedule, elo_ratings, seed, args.iterations,
        args, data_dir,
        rating_system=rating_system,
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
    raw_calibration = _load_calibration()
    cal_info: dict | None = None
    show_ci: bool = False
    apply_calibration: bool = False
    cal_T: float | None = None

    if raw_calibration is not None:
        cal_T = raw_calibration.get("T")
        cal_info = raw_calibration

        # Resolve --calibrated flag
        cal_flag = args.calibrated if args.calibrated is not None else "auto"
        if cal_flag == "on":
            apply_calibration = True
        elif cal_flag == "off":
            apply_calibration = False
        else:  # "auto"
            apply_calibration = cal_T is not None and abs(cal_T - 1.0) > 1e-9

        # Resolve --show-ci flag
        ci_flag = args.show_ci if args.show_ci is not None else "auto"
        if ci_flag == "on":
            show_ci = True
        elif ci_flag == "off":
            show_ci = False
        else:  # "auto"
            show_ci = apply_calibration

    if apply_calibration and cal_T is not None:
        from football_core.blender import temperature_scale
        blended_predictions = [temperature_scale(p, cal_T) for p in blended_predictions]
        logger.info("Applied temperature scaling T=%.4f to %d predictions",
                     cal_T, len(blended_predictions))

    # Re-run MC simulation with CIs if --show-ci will need them
    if show_ci:
        using_glicko = rating_system is not None
        fixtures_dict = {"schedule": asdict(fixtures_schedule)}
        if using_glicko:
            from competitions.ucl.src.simulation import run_monte_carlo_glicko
            mc_result = run_monte_carlo_glicko(
                fixtures_dict, rating_system,
                n_iterations=args.iterations, seed=seed,
                compute_ci=True,
            )
        else:
            from competitions.ucl.src.simulation import run_monte_carlo
            mc_result = run_monte_carlo(
                fixtures_dict, elo_ratings=elo_ratings,
                n_iterations=args.iterations, seed=seed,
                compute_ci=True,
            )
        # Update result teams with CI data
        result = SimulationResult(
            snapshot_date=result.snapshot_date,
            n_iterations=result.n_iterations,
            seed=result.seed,
            standings=result.standings,
            teams=mc_result["teams"],
            playoff_ties=result.playoff_ties,
            playoff_winners=result.playoff_winners,
            bracket_rounds=result.bracket_rounds,
            bracket_champion=result.bracket_champion,
            stages=result.stages,
        )

    # Display results in D-06 tournament chronology order
    print_summary(result, calibration_info=cal_info if apply_calibration else None)
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

    # ── Calibrated validation (Phase 10, Plan 03: before/after comparison) ──
    if args.validate_calibrated:
        baseline_path = os.path.join(data_dir, "validation", "baseline.json")
        baseline_report = None

        # Try to load existing baseline
        if os.path.exists(baseline_path):
            try:
                with open(baseline_path) as f:
                    baseline_data = json.load(f)
                b = baseline_data.get("baseline") or {}
                if b.get("log_loss") is not None:
                    baseline_report = {
                        "match_level": {
                            "log_loss": b["log_loss"],
                            "ece": b.get("ece", 0.0),
                            "brier": b.get("brier", 0.0),
                        },
                        "tournament_level": {
                            "trps": b.get("trps", 0.0),
                        },
                    }
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        # If no baseline exists, seed it by running uncalibrated validation first
        if baseline_report is None:
            print("No existing baseline found — running uncalibrated validation to seed baseline...")
            uncalibrated_report = None
            try:
                uncalibrated_report = _run_validation_suite(
                    args, elo_ratings, fixtures_schedule, data_dir,
                )
            except Exception as e:
                print(f"Warning: Could not seed baseline: {e}", file=sys.stderr)
            if uncalibrated_report is not None:
                _save_validation_baseline(baseline_path, uncalibrated_report, None)
                # Reload as baseline_report for comparison
                if os.path.exists(baseline_path):
                    try:
                        with open(baseline_path) as f:
                            baseline_data = json.load(f)
                        b = baseline_data.get("baseline") or {}
                        if b.get("log_loss") is not None:
                            baseline_report = {
                                "match_level": {
                                    "log_loss": b["log_loss"],
                                    "ece": b.get("ece", 0.0),
                                    "brier": b.get("brier", 0.0),
                                },
                                "tournament_level": {
                                    "trps": b.get("trps", 0.0),
                                },
                            }
                    except (json.JSONDecodeError, FileNotFoundError):
                        pass

        # Run calibrated validation
        calibrated_report = _run_calibrated_validation(
            args, elo_ratings, fixtures_schedule, data_dir,
        )
        if calibrated_report is None:
            pass
        else:
            # Print before/after comparison
            from competitions.ucl.display import print_calibration_comparison
            print_calibration_comparison(baseline_report, calibrated_report)

            # Save/update baseline.json
            _save_validation_baseline(baseline_path, baseline_report, calibrated_report)

            # Print calibrated validation details
            print("\n── Calibrated Validation Results ────────────────────────")
            if "tournament_level" in calibrated_report:
                tl = calibrated_report["tournament_level"]
                print(f"  TRPS:               {tl.get('trps', 'N/A'):>10}")
                print(f"  Champion acc:       {tl.get('champion_accuracy', 'N/A'):>10}")
                print(f"  Stage acc:          {tl.get('stage_accuracy', 'N/A'):>10}")
            if "match_level" in calibrated_report:
                ml = calibrated_report["match_level"]
                print(f"  Log Loss:           {ml.get('log_loss', 'N/A'):>10}")
                print(f"  Brier:              {ml.get('brier', 'N/A'):>10}")
                print(f"  ECE:                {ml.get('ece', 'N/A'):>10}")
            if "calibration" in calibrated_report:
                cal = calibrated_report["calibration"]
                print(f"  Replay ECE:         {cal.get('ece', 'N/A'):>10}")
                print(f"  Decision points:    {cal.get('n_decision_points', 'N/A'):>10}")

    # JSON export — only if NOT already written with validation
    elif args.output:
        with open(args.output, "w") as f:
            json.dump(asdict(result), f, indent=2)
        print(f"JSON written to {args.output}")


if __name__ == "__main__":
    main()
