"""Analysis utilities — counterfactual, validation, what-if parsing.

Extracted from the CLI layer with print() calls stripped.
"""

import copy
import json
import logging
from pathlib import Path
from typing import Any

from competitions.worldcup.src import state
from competitions.worldcup.src.knockout import run_full_simulation

logger = logging.getLogger(__name__)


KNOWN_SIGNALS = [
    "elo", "refined_elo",
    "rolling_form", "squad_value", "rest_days", "market_odds",
]


def parse_what_if(what_if_path: str, teams: dict) -> dict:
    """Parse and validate --what-if JSON override file.

    Returns validated overrides dict, or raises ValueError on invalid content.
    """
    if not Path(what_if_path).exists():
        raise FileNotFoundError(f"Override file not found: {what_if_path}")

    with open(what_if_path, encoding="utf-8") as f:
        try:
            overrides: dict[str, Any] = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in override file: {e}")

    if not isinstance(overrides, dict):
        raise ValueError("Override file must contain a JSON object")

    allowed_keys = {"elo_changes", "blend_weights", "xg_overrides"}
    unknown = set(overrides.keys()) - allowed_keys
    if unknown:
        raise ValueError(
            f"Unknown override keys: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(allowed_keys))}"
        )

    validated: dict[str, Any] = {}

    if "elo_changes" in overrides:
        elo = overrides["elo_changes"]
        if not isinstance(elo, dict):
            raise ValueError("elo_changes must be a dict mapping team -> rating")
        for team, rating in elo.items():
            if team not in teams:
                raise ValueError(f"Unknown team in elo_changes: '{team}'")
            if not isinstance(rating, (int, float)):
                raise ValueError(f"Invalid Elo value for '{team}': must be a number")
            if rating <= 0:
                raise ValueError(f"Elo rating for '{team}' must be positive (got {rating})")
        validated["elo_changes"] = elo

    if "blend_weights" in overrides:
        bw = overrides["blend_weights"]
        if not isinstance(bw, dict):
            raise ValueError("blend_weights must be a dict mapping signal -> weight")
        if sum(bw.values()) == 0:
            raise ValueError("blend_weights must not sum to 0")
        validated["blend_weights"] = bw

    if "xg_overrides" in overrides:
        xg = overrides["xg_overrides"]
        if not isinstance(xg, dict):
            raise ValueError("xg_overrides must be a dict mapping match_id -> overrides")
        for mid, val in xg.items():
            if not isinstance(val, dict):
                raise ValueError(f"xg_overrides['{mid}'] must be a dict with home_xg and away_xg")
            if "home_xg" not in val or "away_xg" not in val:
                raise ValueError(f"xg_overrides['{mid}'] must have 'home_xg' and 'away_xg' keys")
            if val["home_xg"] <= 0 or val["away_xg"] <= 0:
                raise ValueError(f"xg_overrides['{mid}'] values must be positive")
        validated["xg_overrides"] = xg

    return validated


def parse_weights(weights_str: str, known_signals: list[str] | None = None) -> dict[str, float]:
    """Parse K=V,K=V weight string, validate, normalize to sum 1.0.

    Args:
        weights_str: "elo=0.4,market_odds=0.3,squad_value=0.3"
        known_signals: list of known signal names for validation.
                       Defaults to KNOWN_SIGNALS.

    Returns:
        {signal_name: normalized_weight} summing to 1.0

    Raises:
        ValueError on invalid format, unknown signals, all-zero weights.
    """
    if known_signals is None:
        known_signals = KNOWN_SIGNALS

    weights: dict[str, float] = {}
    pairs = weights_str.split(",")
    for pair in pairs:
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"Invalid format '{pair}'. Use K=V syntax (e.g., elo=0.4).")
        key, val_str = pair.split("=", 1)
        key = key.strip()
        val_str = val_str.strip()
        if not key:
            raise ValueError(f"Empty key in '{pair}'.")
        if key not in known_signals:
            raise ValueError(
                f"Unknown signal '{key}'. Available: {', '.join(sorted(known_signals))}"
            )
        try:
            val = float(val_str)
        except ValueError:
            raise ValueError(f"Invalid weight value '{val_str}' for signal '{key}'.")
        if val < 0:
            raise ValueError(f"Negative weight {val} for signal '{key}'.")
        weights[key] = val

    if not weights:
        raise ValueError("Must specify at least one key=value pair.")

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Weights must sum to > 0.")

    if abs(total - 1.0) > 1e-9:
        logger.info("Weights normalized to sum 1.0 (was %.4f)", total)
        weights = {k: v / total for k, v in weights.items()}

    return weights


def run_counterfactual(
    baseline_teams: dict,
    baseline_groups: dict,
    baseline_bracket: list[dict],
    annex_c: dict,
    played: dict,
    played_groups: dict,
    overrides: dict,
    seed: int,
    iterations: int,
) -> tuple[dict, list[str]]:
    """Run counterfactual simulation with overrides applied.

    Returns (cf_result, change_descriptions).
    """
    teams = copy.deepcopy(baseline_teams)
    groups = copy.deepcopy(baseline_groups)
    bracket = copy.deepcopy(baseline_bracket)

    change_descriptions: list[str] = []

    elo_changes = overrides.get("elo_changes", {})
    for team, new_rating in elo_changes.items():
        old = teams[team]["elo"]
        teams[team]["elo"] = new_rating
        delta = new_rating - old
        change_descriptions.append(f"{team}.elo: {int(old)} -> {int(new_rating)} ({delta:+d})")

    blend_params: dict | None = None
    if "blend_weights" in overrides:
        blend_params = {"weights": overrides["blend_weights"]}
        change_descriptions.append(f"blend_weights: {overrides['blend_weights']}")

    xg_overrides = overrides.get("xg_overrides", None)

    cf_result = run_full_simulation(
        teams, groups, bracket, annex_c, played,
        iterations=iterations, seed=seed + 1, played_groups=played_groups,
        blend_params=blend_params,
        xg_overrides=xg_overrides,
    )

    return cf_result, change_descriptions


def _find_actual_champion(bracket: list[dict], played: dict) -> str | None:
    """Trace bracket tree to find the actual tournament champion."""
    for match in bracket:
        if match.get("round") in ("FINAL", "final", "Final"):
            mid = match.get("match_id", "")
            if mid in played:
                return played[mid].get("winner")
    return None


def run_calibrated_validation(
    teams: dict,
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    played: dict,
    played_groups: dict,
    data_dir: str,
    iterations: int = 50000,
) -> dict:
    """Run tournament validation against the actual outcome (Brier/log-loss/accuracy).

    Calibration is now a single canonical ensemble — there is no separate
    "calibrated" simulation leg, so ``calibrated``/``delta`` are always None.
    """
    from football_core.evaluation import brier_score, log_loss

    def _compute_metrics(result: dict, actual_champion: str | None) -> dict:
        metrics: dict[str, float | None] = {
            "brier": None, "log_loss": None, "champion_acc": None,
        }
        if actual_champion:
            cp = result.get(actual_champion, {}).get("champion", 0.0)
            metrics["brier"] = brier_score(cp, 1.0)
            metrics["log_loss"] = log_loss(cp, 1.0)
            ranked = sorted(result, key=lambda n: result[n]["champion"], reverse=True)
            metrics["champion_acc"] = 1.0 if ranked[0] == actual_champion else 0.0
        return metrics

    actual_champion = _find_actual_champion(bracket, played)

    n_matches = 0
    for mid, m in played.items():
        if isinstance(m, dict) and m.get("winner"):
            n_matches += 1

    if n_matches == 0:
        return {
            "baseline": {"brier": None, "log_loss": None, "champion_acc": None},
            "calibrated": None,
            "delta": None,
            "n_matches": 0,
            "calibration_available": False,
        }

    baseline = run_full_simulation(
        teams, groups, bracket, annex_c, played,
        iterations=iterations, seed=42, played_groups=played_groups,
    )
    baseline_metrics = _compute_metrics(baseline, actual_champion)

    return {
        "baseline": baseline_metrics,
        "calibrated": None,
        "delta": None,
        "n_matches": n_matches,
        "calibration_available": False,
    }
