"""Simulation mode orchestrator for UCL.

Routes between simulate, replay, and live modes per D-05.
Each mode resolves played_matches from its source, then delegates
to the simulation engine which is mode-agnostic.

Extended in Phase 10 (Plan 02) to support Glicko-1 rating system
uncertainty propagation via the *rating_system* parameter.

Usage:
    from competitions.ucl.src.orchestrator import run_simulation
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from football_core.provider import FixtureSchedule

from competitions.ucl.result import SimulationResult
from competitions.ucl.src.calibrate import _EmptyResultProvider

logger = logging.getLogger(__name__)


def _get_config_dir() -> str:
    """Return absolute path to competitions/ucl/config/ directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
    )


def load_calibration() -> dict | None:
    """Load temperature calibration from config/calibration.json."""
    cal_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
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


def load_cache_ttls(data_dir: str) -> dict[str, int]:
    """Load per-signal cache TTLs from config/cache_ttls.json."""
    config_path = os.path.join(data_dir, "..", "config", "cache_ttls.json")
    try:
        with open(config_path) as f:
            return dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"odds": 12, "catboost": 24}


def build_signal_engine(
    elo_ratings: dict[str, float],
    weights_override: dict[str, float] | None = None,
) -> Any:
    """Build EnsembleEngine with 8 pre-configured signals and calibrated weights."""
    from football_core.blender import EnsembleEngine
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


def build_simulation_result(
    fixtures: FixtureSchedule,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
    rating_system=None,
    progress_cb: callable | None = None,
) -> SimulationResult:
    """Run MC simulation + one representative bracket iteration, return SimulationResult."""
    fixtures_dict = {"schedule": asdict(fixtures)}

    using_glicko = rating_system is not None
    if using_glicko:
        from competitions.ucl.src.simulation import run_monte_carlo_glicko
        mc_result = run_monte_carlo_glicko(
            fixtures_dict,
            rating_system,
            n_iterations=n_iterations,
            seed=seed,
            played_matches=played_matches,
            progress_cb=progress_cb,
        )
    else:
        from competitions.ucl.src.simulation import run_monte_carlo
        mc_result = run_monte_carlo(
            fixtures_dict,
            elo_ratings=elo_ratings,
            n_iterations=n_iterations,
            seed=seed,
            played_matches=played_matches,
            progress_cb=progress_cb,
        )

    rng = random.Random(seed)
    bracket_elos = rating_system.to_elo_dict() if using_glicko else elo_ratings
    from competitions.ucl.src.simulation import simulate_league_phase
    standings = simulate_league_phase(fixtures_dict, bracket_elos, rng, played_matches=played_matches)

    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
    )
    pairings_path = os.path.join(data_dir, "playoff_pairings.json")
    bracket_path = os.path.join(data_dir, "bracket_rules.json")

    with open(pairings_path) as f:
        pairings_data = json.load(f)
    with open(bracket_path) as f:
        bracket_data = json.load(f)

    from competitions.ucl.src.knockout import (
        build_r16_bracket, simulate_playoff_round,
        simulate_knockout_tree, track_knockout_stages,
    )

    playoff_result = simulate_playoff_round(
        standings, bracket_elos, rng,
        pairings_data=pairings_data,
    )
    bracket = build_r16_bracket(
        standings, playoff_result,
        bracket_data=bracket_data,
        rng=rng,
    )
    tree_result = simulate_knockout_tree(bracket, bracket_elos, rng)
    stages = track_knockout_stages(standings, tree_result)

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
    """Cross-check simulation predictions against real match outcomes."""
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

        if match.get("is_draw"):
            actual = 0.5
        elif match.get("winner") == team_a:
            actual = 1.0
        elif match.get("winner") == team_b:
            actual = 0.0
        else:
            continue

        predictions.append(pred_home_win)
        actuals.append(actual)

        if "odds" in match:
            odds_predictions.append(match["odds"]["home"])
            odds_actuals.append(actual)

    prediction_metrics = compute_metrics(predictions, actuals)
    calibration = calibration_curve(predictions, actuals)

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

    if odds_predictions:
        odds_metrics = compute_metrics(odds_predictions, odds_actuals)
        result["market_odds_metrics"] = {
            "brier": round(odds_metrics["brier"], 6),
            "log_loss": round(odds_metrics["log_loss"], 6),
            "n": odds_metrics["n"],
        }

    return result


def resolve_played_matches(
    args,
    data_dir: str,
    fixtures_schedule: FixtureSchedule,
) -> dict[tuple[str, str], tuple[int, int]] | None:
    """Resolve played_matches based on CLI mode."""
    if args.mode == "replay":
        if not args.replay_data:
            logger.error("--replay-data PATH required for replay mode")
            sys.exit(1)
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider
        provider = ReplayMatchResultProvider(args.replay_data)
        return provider.load()

    elif args.mode == "live":
        api_key = args.api_key or os.environ.get("BSD_API_KEY")
        if not api_key:
            logger.error("BSD_API_KEY required for live mode")
            sys.exit(1)
        from competitions.ucl.src.result_provider import BSDMatchResultProvider
        team_aliases_path = os.path.join(data_dir, "team_aliases.json")
        with open(team_aliases_path) as f:
            team_aliases = json.load(f)
        provider = BSDMatchResultProvider(
            api_key, team_aliases, asdict(fixtures_schedule),
        )
        return provider.load()

    results_path = os.path.join(data_dir, "results.json")
    if os.path.exists(results_path):
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider
        provider = ReplayMatchResultProvider(results_path)
        return provider.load()

    return None


def run_simulation(
    fixtures_schedule: FixtureSchedule,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
    args,
    data_dir: str,
    rating_system=None,
) -> object:
    """Orchestrate the full simulation: resolve mode, run MC, return result."""
    played_matches = resolve_played_matches(args, data_dir, fixtures_schedule)

    return build_simulation_result(
        fixtures_schedule, elo_ratings, seed, n_iterations,
        played_matches=played_matches,
        rating_system=rating_system,
    )
