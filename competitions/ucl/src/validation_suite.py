"""Three-tier tournament validation framework for UCL predictions.

Tier 2: Walk-forward match-level validation
Tier 3: Replay validation (diagnostic)
Tier 1: Cross-tournament backtest (Plan 09-03)

Consumes blended predictions from EnsembleEngine and produces
structured validation reports with standardized metrics.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from football_core.evaluation import (
    multi_class_brier,
    multi_class_ece,
    multi_class_log_loss,
)
from football_core.signal import PredictionContext


@dataclass
class ValidationResult:
    """Structured container for a single validation run result."""

    tier: str  # "walk_forward" | "replay" | "cross_tournament"
    date: str  # ISO date of validation run
    n_matches: int
    n_seasons: int
    metrics: dict  # log_loss, brier, ece
    details: dict | None = None  # Per-season or per-matchday breakdowns
    baseline: bool = False  # True if this is the uncalibrated baseline


class ValidationSuite:
    """Orchestrates the three-tier tournament validation framework.

    Parameters
    ----------
    engine : EnsembleEngine
        Configured signal ensemble for evaluating match predictions.
    seasons_data : dict
        Nested dict of {season_id: {matches: [...], teams: [...], standings: [...]}}
        where each match dict has team_a, team_b, winner, is_draw fields.
    """

    def __init__(self, engine: Any, seasons_data: dict[str, dict]) -> None:
        self.engine = engine
        self.seasons = seasons_data
        self._season_ids = sorted(seasons_data.keys())

    # ── Tier 2: Walk-Forward Match-Level Validation ─────────────────────

    def walk_forward_splits(
        self, window: int = 3,
    ) -> list[tuple[list[str], str]]:
        """Generate (source_seasons, eval_season) tuples for walk-forward CV.

        First split uses seasons[0:window] as source, seasons[window] as eval.
        Sliding window until no more eval seasons remain.

        Parameters
        ----------
        window : int
            Number of seasons in each training window (default 3).

        Returns
        -------
        list[tuple[list[str], str]]
            List of (source_ids, eval_id) tuples.
        """
        ids = self._season_ids
        splits: list[tuple[list[str], str]] = []
        for i in range(window, len(ids)):
            source = ids[i - window : i]
            eval_season = ids[i]
            splits.append((source, eval_season))
        return splits

    def run_tier_2_walk_forward(self, window: int = 3) -> ValidationResult:
        """Run walk-forward match-level validation across season windows.

        For each (source, eval) split:
        - Collect matches from source seasons as training context
        - For each match in eval season, get blended prediction via engine
        - Score predictions vs actual outcomes using multi-class metrics

        Parameters
        ----------
        window : int
            Walk-forward window size (default 3).

        Returns
        -------
        ValidationResult
            Aggregated walk-forward metrics with per-season breakdown.
        """
        splits = self.walk_forward_splits(window)
        if not splits:
            return ValidationResult(
                tier="walk_forward",
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                n_matches=0,
                n_seasons=0,
                metrics={"log_loss": 0.0, "brier": 0.0, "ece": 0.0},
                details={"per_season": [], "n_folds": 0},
            )

        all_probs: list[list[float]] = []
        all_actuals: list[int] = []
        per_season: list[dict] = []

        for source_ids, eval_id in splits:
            eval_season = self.seasons[eval_id]
            eval_matches = eval_season.get("matches", [])

            # Build source match data for context
            source_matches: list[dict] = []
            for sid in source_ids:
                source_matches.extend(self.seasons[sid].get("matches", []))

            # Build a minimal played_results list from source matches
            played_results = [
                {
                    "team_a": m["team_a"],
                    "team_b": m["team_b"],
                    "winner": m.get("winner"),
                    "is_draw": m.get("is_draw", False),
                    "home_score": m.get("home_score", 0),
                    "away_score": m.get("away_score", 0),
                }
                for m in source_matches
                if m.get("winner") is not None
            ]

            # Build elo_ratings from season data (or use default)
            elo_ratings: dict[str, float] = {}
            for m in source_matches + eval_matches:
                for team_key in ("team_a", "team_b"):
                    team = m.get(team_key, "")
                    if team and team not in elo_ratings:
                        # Default Elo if not provided in standings
                        elo_ratings[team] = 1500.0

            # Merge from standings data if available
            for sid in source_ids + [eval_id]:
                standings = self.seasons[sid].get("standings", [])
                for entry in standings:
                    team = entry.get("team", "")
                    elo = entry.get("elo")
                    if team and elo is not None:
                        elo_ratings[team] = float(elo)

            context = PredictionContext(
                fixtures=eval_matches,
                elo_ratings=elo_ratings,
                played_results=played_results,
            )

            # Evaluate each match in eval season
            season_probs: list[list[float]] = []
            season_actuals: list[int] = []
            for match in eval_matches:
                if match.get("winner") is None and not match.get("is_draw"):
                    continue  # Skip unplayed matches

                try:
                    bp = self.engine.evaluate(match, context)
                except Exception:
                    continue

                probs = [bp.home_prob, bp.draw_prob, bp.away_prob]

                # Determine actual outcome: 0=home, 1=draw, 2=away
                if match.get("is_draw"):
                    actual = 1
                elif match.get("winner") == match.get("team_a"):
                    actual = 0
                elif match.get("winner") == match.get("team_b"):
                    actual = 2
                else:
                    continue

                season_probs.append(probs)
                season_actuals.append(actual)

            if season_probs:
                season_log_loss = multi_class_log_loss(season_probs, season_actuals)
                season_brier = multi_class_brier(season_probs, season_actuals)
                season_ece = multi_class_ece(season_probs, season_actuals)

                per_season.append({
                    "season_id": eval_id,
                    "log_loss": round(season_log_loss, 6),
                    "brier": round(season_brier, 6),
                    "ece": round(season_ece, 6),
                    "n_matches": len(season_probs),
                })
                all_probs.extend(season_probs)
                all_actuals.extend(season_actuals)

        if not all_probs:
            return ValidationResult(
                tier="walk_forward",
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                n_matches=0,
                n_seasons=len(splits),
                metrics={"log_loss": 0.0, "brier": 0.0, "ece": 0.0},
                details={"per_season": per_season, "n_folds": len(splits)},
            )

        # Aggregate metrics across all seasons (macro-average of per-season)
        agg_log_loss = multi_class_log_loss(all_probs, all_actuals)
        agg_brier = multi_class_brier(all_probs, all_actuals)
        agg_ece = multi_class_ece(all_probs, all_actuals)

        return ValidationResult(
            tier="walk_forward",
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            n_matches=len(all_probs),
            n_seasons=len(self._season_ids),
            metrics={
                "log_loss": round(agg_log_loss, 6),
                "brier": round(agg_brier, 6),
                "ece": round(agg_ece, 6),
            },
            details={
                "per_season": per_season,
                "n_folds": len(splits),
            },
        )

    # ── Tier 3: Replay Validation ────────────────────────────────────────

    def run_tier_3_replay(
        self, replay_matchdays: list[list[dict]],
    ) -> ValidationResult:
        """Run replay validation by stepping through matchdays chronologically.

        For each matchday index d:
        - Inject real results from matchdays 0..d as played matches
        - Simulate remaining fixtures (matchdays d+1..N-1)
        - Record calibration over all simulated decision points

        Parameters
        ----------
        replay_matchdays : list[list[dict]]
            Ordered list of matchdays, each containing match dicts with
            team_a, team_b, winner, is_draw, home_score, away_score.

        Returns
        -------
        ValidationResult
            Replay validation result with calibration metrics.
        """
        n_matchdays = len(replay_matchdays)
        if n_matchdays == 0:
            return ValidationResult(
                tier="replay",
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                n_matches=0,
                n_seasons=0,
                metrics={"ece": 0.0, "n_decision_points": 0},
                details={"per_matchday": [], "calibration_bins": []},
            )

        all_confidences: list[float] = []
        all_correct: list[bool] = []
        per_matchday: list[dict] = []

        for d in range(n_matchdays - 1):
            # Played matches from matchdays 0..d
            played_matches: list[dict] = []
            for md_idx in range(d + 1):
                played_matches.extend(replay_matchdays[md_idx])

            # Remaining fixtures (matchdays d+1 .. N-1) — teams known, result unknown
            remaining_fixtures: list[dict] = []
            for md_idx in range(d + 1, n_matchdays):
                remaining_fixtures.extend(replay_matchdays[md_idx])

            # Build elo_ratings from played match data
            elo_ratings: dict[str, float] = {}
            for m in played_matches:
                for team_key in ("team_a", "team_b"):
                    team = m.get(team_key, "")
                    if team and team not in elo_ratings:
                        elo_ratings[team] = 1500.0

            context = PredictionContext(
                fixtures=remaining_fixtures,
                elo_ratings=elo_ratings,
                played_results=[
                    {
                        "team_a": m["team_a"],
                        "team_b": m["team_b"],
                        "winner": m.get("winner"),
                        "is_draw": m.get("is_draw", False),
                        "home_score": m.get("home_score", 0),
                        "away_score": m.get("away_score", 0),
                    }
                    for m in played_matches
                ],
            )

            # Evaluate remaining fixtures
            md_probs: list[list[float]] = []
            md_actuals: list[int] = []
            for match in remaining_fixtures:
                if match.get("winner") is None and not match.get("is_draw"):
                    continue
                try:
                    bp = self.engine.evaluate(match, context)
                except Exception:
                    continue

                probs = [bp.home_prob, bp.draw_prob, bp.away_prob]
                if match.get("is_draw"):
                    actual = 1
                elif match.get("winner") == match.get("team_a"):
                    actual = 0
                elif match.get("winner") == match.get("team_b"):
                    actual = 2
                else:
                    continue

                md_probs.append(probs)
                md_actuals.append(actual)

            if md_probs:
                md_ece = multi_class_ece(md_probs, md_actuals)
                per_matchday.append({
                    "matchday_index": d,
                    "n_simulated": len(md_probs),
                    "ece": round(md_ece, 6),
                })

                # Collect all confidence/correct pairs for overall calibration
                for probs, actual in zip(md_probs, md_actuals):
                    pred_class = int(np.argmax(probs))
                    all_confidences.append(max(probs))
                    all_correct.append(pred_class == actual)

        n_decision_points = len(all_confidences)

        if n_decision_points == 0:
            return ValidationResult(
                tier="replay",
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                n_matches=0,
                n_seasons=0,
                metrics={"ece": 0.0, "n_decision_points": 0},
                details={"per_matchday": per_matchday, "calibration_bins": []},
            )

        # Compute overall calibration bins
        from football_core.evaluation import calibration_curve

        # Convert binary accuracy/confidence to calibration curve format
        n_bins = min(10, max(3, n_decision_points // 10))
        bins: list[dict] = []
        for i in range(n_bins):
            lo, hi = i / n_bins, (i + 1) / n_bins
            bin_confs = [
                c for c, _ in zip(all_confidences, all_correct)
                if lo <= c < hi or (i == n_bins - 1 and c == 1.0)
            ]
            bin_correct = [
                ok for c, ok in zip(all_confidences, all_correct)
                if lo <= c < hi or (i == n_bins - 1 and c == 1.0)
            ]
            if bin_confs:
                mean_conf = sum(bin_confs) / len(bin_confs)
                acc = sum(1 for ok in bin_correct) / len(bin_correct)
                bins.append({
                    "bin_start": round(lo, 2),
                    "bin_end": round(hi, 2),
                    "count": len(bin_confs),
                    "mean_confidence": round(mean_conf, 4),
                    "accuracy": round(acc, 4),
                })

        overall_ece = 0.0
        total_count = sum(b["count"] for b in bins)
        if total_count > 0:
            for b in bins:
                overall_ece += (b["count"] / total_count) * abs(
                    b["mean_confidence"] - b["accuracy"]
                )

        return ValidationResult(
            tier="replay",
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            n_matches=n_decision_points,
            n_seasons=1,
            metrics={
                "ece": round(overall_ece, 6),
                "n_decision_points": n_decision_points,
            },
            details={
                "per_matchday": per_matchday,
                "calibration_bins": bins,
            },
        )

    # ── Stubs for Tier 1 (Plan 09-03) ────────────────────────────────────

    def run_tier_1_cross_tournament(self) -> ValidationResult:
        """Cross-tournament backtest (Tier 1) — implemented in Plan 09-03."""
        raise NotImplementedError(
            "Tier 1 (cross-tournament) is implemented in Plan 09-03. "
            "Complete Plan 09-02 first, then run 09-03 to add this method."
        )

    def run_all(self, replay_matchdays: list[list[dict]] | None = None,
                window: int = 3) -> dict:
        """Run all three tiers — implemented in Plan 09-03."""
        raise NotImplementedError(
            "run_all() is implemented in Plan 09-03. "
            "Complete Plan 09-02 first, then run 09-03 to add this method."
        )

    def save_baseline(self, output_dir: str | None = None) -> str:
        """Save baseline report — implemented in Plan 09-03."""
        raise NotImplementedError(
            "save_baseline() is implemented in Plan 09-03. "
            "Complete Plan 09-02 first, then run 09-03 to add this method."
        )
