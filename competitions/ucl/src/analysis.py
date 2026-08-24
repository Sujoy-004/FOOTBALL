"""Analysis utilities for UCL — counterfactual, validation, what-if, weights.

Extracted from the CLI layer with print() calls stripped.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from football_core.provider import FixtureSchedule

from competitions.ucl.result import SimulationResult

logger = logging.getLogger(__name__)


def parse_weights(weights_str: str | None) -> dict[str, float] | None:
    """Parse --weights CLI override string into {name: weight} dict.

    Format: "elo=0.4,market=0.3,form=0.2,squad=0.1"
    Auto-normalizes to sum 1.0.

    Returns None if weights_str is None (no override).
    Raises ValueError on malformed input.
    """
    if weights_str is None:
        return None

    weights: dict[str, float] = {}
    pairs = weights_str.split(",")
    for pair in pairs:
        pair = pair.strip()
        if "=" not in pair:
            raise ValueError(
                f"Invalid --weights format '{pair}'. Use K=V format "
                f"(e.g., elo=0.4,market=0.3)"
            )
        key, val_str = pair.split("=", 1)
        key = key.strip()
        val_str = val_str.strip()
        if not key:
            raise ValueError(f"Empty key in --weights '{pair}'")
        try:
            val = float(val_str)
        except ValueError:
            raise ValueError(
                f"Non-numeric weight value '{val_str}' for signal '{key}'"
            )
        if val < 0:
            raise ValueError(f"Negative weight {val} for signal '{key}'")
        weights[key] = val

    if not weights:
        raise ValueError("--weights must specify at least one key=value pair")

    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:
        logger.info("--weights sum=%.4f != 1.0 — auto-normalizing", total)
        weights = {k: v / total for k, v in weights.items()}

    return weights


def parse_what_if(what_if_list: list[str] | None) -> list[dict]:
    """Parse --what-if arguments into structured modifications.

    Each argument has format: TEAM.PARAM=VALUE
    Supported params: elo (float)

    Returns list of dicts: [{team, param, value}, ...]
    Returns empty list if what_if_list is None or empty.
    Raises ValueError on malformed input.
    """
    if not what_if_list:
        return []

    supported_params = {"elo"}
    modifications: list[dict] = []

    for arg in what_if_list:
        if "." not in arg or "=" not in arg:
            raise ValueError(
                f"Invalid --what-if format '{arg}'. "
                f"Use TEAM.PARAM=VALUE format (e.g., 'Arsenal.elo=1960')."
            )

        dot_idx = arg.index(".")
        eq_idx = arg.index("=", dot_idx)

        if dot_idx == 0 or eq_idx <= dot_idx + 1:
            raise ValueError(
                f"Invalid --what-if format '{arg}'. "
                f"Team name must not be empty."
            )

        team = arg[:dot_idx]
        param = arg[dot_idx + 1:eq_idx]
        value_str = arg[eq_idx + 1:]

        if not param:
            raise ValueError(f"Empty parameter in --what-if '{arg}'.")

        if param not in supported_params:
            supported_str = ", ".join(sorted(supported_params))
            raise ValueError(
                f"Unsupported parameter '{param}' in --what-if '{arg}'. "
                f"Supported parameters: {supported_str}"
            )

        try:
            value = float(value_str)
        except ValueError:
            raise ValueError(
                f"Non-numeric value '{value_str}' for parameter "
                f"'{param}' in --what-if '{arg}'."
            )

        if value < 0:
            raise ValueError(
                f"Negative value {value} for parameter "
                f"'{param}' in --what-if '{arg}'. Elo must be positive."
            )

        modifications.append({"team": team, "param": param, "value": value})

    return modifications


def run_counterfactual(
    what_if_changes: list[dict],
    elo_ratings: dict[str, float],
    fixtures_schedule: FixtureSchedule,
    seed: int,
    n_iterations: int,
    args,
    data_dir: str,
) -> tuple[SimulationResult, list[str]]:
    """Run counterfactual simulation with modified parameters.

    Returns (counterfactual SimulationResult, list of change descriptions).
    """
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
                change_descriptions.append(
                    f"{team}.elo={value} (was {old_val:.0f}, +{delta})"
                )
            else:
                change_descriptions.append(
                    f"{team}.elo={value} (was {old_val:.0f}, {delta})"
                )

    from competitions.ucl.src.orchestrator import run_simulation

    result = run_simulation(
        fixtures_schedule, modified_elos, seed + 1, n_iterations,
        args, data_dir,
    )

    return result, change_descriptions


def run_validation_suite(
    args,
    elo_ratings: dict[str, float],
    fixtures_schedule: FixtureSchedule,
    data_dir: str,
) -> dict:
    """Execute validation pipeline using ValidationSuite.

    Returns combined validation report from all requested tiers.
    Raises ValueError on invalid input.
    """
    from competitions.ucl.src.validation_suite import ValidationSuite
    from competitions.ucl.src.orchestrator import build_signal_engine

    engine = build_signal_engine(elo_ratings, parse_weights(getattr(args, "weights", None)))

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

    replay_data: list[list[dict]] | None = None
    replay_data_path = getattr(args, "replay_data", None)
    if replay_data_path:
        try:
            with open(replay_data_path) as f:
                raw = json.load(f)
            if isinstance(raw, list):
                if raw and isinstance(raw[0], list):
                    replay_data = raw
                else:
                    replay_data = [raw]
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValueError(f"Error loading replay data: {e}")

    tier = getattr(args, "tier", "all")

    if tier == "all":
        report = suite.run_all(replay_matchdays=replay_data)
    elif tier == "cross-tournament":
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
    elif tier == "walk-forward":
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
    elif tier == "replay":
        if not replay_data:
            raise ValueError("--replay-data PATH required for --tier replay")
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
        raise ValueError(f"Unknown tier '{tier}'")

    return report



def save_validation_baseline(
    baseline_path: str,
    uncalibrated_report: dict | None,
    calibrated_report: dict | None,
) -> dict:
    """Save or update validation baseline JSON with before/after data.

    Returns the updated/fresh baseline dict.
    """
    existing: dict = {"baseline": None, "calibrated": []}
    if os.path.exists(baseline_path):
        try:
            with open(baseline_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            existing = {"baseline": None, "calibrated": []}

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
        }
        existing.setdefault("calibrated", []).append(cal_entry)

    os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
    with open(baseline_path, "w") as f:
        json.dump(existing, f, indent=2)

    return existing
