"""Structured report generation for UCL predictions.

Builds a comprehensive JSON report matching the RESPONSE.md decomposition
pattern, including simulation metadata, champion probabilities, signal
breakdown, validation metrics, and counterfactual results.

Usage:
    from competitions.ucl.report import build_report
    report = build_report(result, blended_predictions, engine)
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from competitions.ucl.result import SimulationResult
from football_core.blender import EnsembleEngine, compute_signal_contributions
from football_core.signal import BlendedPrediction


def build_report(
    result: SimulationResult,
    blended_predictions: list[BlendedPrediction] | None = None,
    engine: EnsembleEngine | None = None,
    counterfactual_results: list[tuple[SimulationResult, list[str]]] | None = None,
    match_fixtures: list[dict] | None = None,
) -> dict[str, Any]:
    """Build structured summary report matching RESPONSE.md pattern.

    Args:
        result: Primary SimulationResult from MC simulation.
        blended_predictions: List of BlendedPrediction from EnsembleEngine.
        engine: EnsembleEngine for signal weights (optional).
        counterfactual_results: List of (SimulationResult, change_descriptions)
            tuples from _run_counterfactual().
        match_fixtures: Match fixtures list for signal contribution computation.

    Returns:
        Dict with sections: simulation, champion, qualification,
        signal_breakdown, validation, counterfactuals.
    """
    # ── Simulation metadata ──
    report: dict[str, Any] = {
        "simulation": {
            "snapshot_date": result.snapshot_date,
            "n_iterations": result.n_iterations,
            "seed": result.seed,
        },
    }

    # ── Champion section ──
    if result.bracket_champion:
        champion_team = result.bracket_champion
        champion_prob = result.teams.get(champion_team, {}).get("champion_prob", 0.0)

        # Top-5 teams by champion probability
        sorted_teams = sorted(
            result.teams.items(),
            key=lambda x: -x[1].get("champion_prob", 0.0),
        )[:5]
        top_5 = [
            {"team": team_name, "probability": round(team_data.get("champion_prob", 0.0), 6)}
            for team_name, team_data in sorted_teams
        ]

        report["champion"] = {
            "team": champion_team,
            "probability": round(champion_prob, 6),
            "top_5": top_5,
        }
    else:
        report["champion"] = None

    # ── Qualification section ──
    top_8 = []
    playoff = []
    for entry in result.standings:
        zone = entry.get("zone", "")
        if zone == "top_8":
            top_8.append(entry.get("team", ""))
        elif zone == "playoff":
            playoff.append(entry.get("team", ""))
    report["qualification"] = {
        "top_8": top_8,
        "playoff": playoff,
    }

    # ── Signal breakdown section ──
    signal_section: dict[str, Any] = {}
    if engine is not None:
        signal_section["ensemble_weights"] = dict(engine.weights)

    if blended_predictions and engine is not None and result.bracket_champion:
        contributions = compute_signal_contributions(
            blended_predictions,
            result.bracket_champion,
            engine.weights,
            match_fixtures=match_fixtures,
        )
        # Normalize contributions to sum to champion probability
        if contributions and result.bracket_champion:
            total_raw = sum(contributions.values())
            champ_prob = result.teams[result.bracket_champion].get("champion_prob", 0.0) * 100
            if abs(total_raw) > 1e-9:
                contributions = {
                    sig: round(val / total_raw * champ_prob, 1)
                    for sig, val in contributions.items()
                }
        signal_section["contributions"] = contributions

    report["signal_breakdown"] = signal_section

    # ── Validation section ──
    report["validation"] = result.validation

    # ── Counterfactuals section ──
    if counterfactual_results:
        cf_list = []
        baseline_champ_prob = (
            result.teams[result.bracket_champion].get("champion_prob", 0.0)
            if result.bracket_champion else 0.0
        )

        for cf_result, cf_changes in counterfactual_results:
            cf_entry: dict[str, Any] = {
                "changes": cf_changes,
            }
            if cf_result.bracket_champion:
                cf_champ_prob = cf_result.teams.get(
                    cf_result.bracket_champion, {},
                ).get("champion_prob", 0.0)
                cf_entry["champion"] = {
                    "team": cf_result.bracket_champion,
                    "probability": round(cf_champ_prob, 6),
                }
                cf_entry["delta_from_baseline"] = round(
                    cf_champ_prob - baseline_champ_prob, 6,
                )
            cf_list.append(cf_entry)

        report["counterfactuals"] = cf_list
    else:
        report["counterfactuals"] = None

    return report


def write_report(
    report: dict,
    output_path: str,
) -> None:
    """Write report dict to JSON file atomically.

    Writes to a temporary file first, then renames to prevent partial writes.

    Args:
        report: Report dict from build_report().
        output_path: Destination file path.
    """
    # Write to temp file, then rename for atomicity
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="report_", dir=os.path.dirname(output_path) or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, output_path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
