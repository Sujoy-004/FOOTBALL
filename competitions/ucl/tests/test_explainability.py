"""Tests for signal contribution computation — Phase 11, Plan 11-01."""

from __future__ import annotations

from typing import Any

import pytest

from football_core.blender import compute_signal_contributions
from football_core.signal import BlendedPrediction


def _make_blended_prediction(
    home: float = 0.5,
    draw: float = 0.3,
    away: float = 0.2,
    signal_breakdown: dict[str, dict[str, float]] | None = None,
    weights: dict[str, float] | None = None,
) -> BlendedPrediction:
    if signal_breakdown is None:
        signal_breakdown = {
            "elo": {"home": 0.6, "draw": 0.25, "away": 0.15, "weight": 0.5},
            "market": {"home": 0.5, "draw": 0.3, "away": 0.2, "weight": 0.3},
            "form": {"home": 0.4, "draw": 0.35, "away": 0.25, "weight": 0.2},
        }
    if weights is None:
        weights = {"elo": 0.5, "market": 0.3, "form": 0.2}
    return BlendedPrediction(
        home_prob=home,
        draw_prob=draw,
        away_prob=away,
        signal_breakdown=signal_breakdown,
        weights_applied=weights,
    )


def _make_team_match(team_a: str, team_b: str, match_id: str = "M01") -> dict:
    return {"team_a": team_a, "team_b": team_b, "match_id": match_id}


# ── TestContributionComputation ─────────────────────────────────────────────


class TestContributionComputation:
    """Tests for compute_signal_contributions()."""

    def test_empty_predictions_returns_empty_dict(self):
        """Empty blended_predictions returns empty dict."""
        result = compute_signal_contributions([], "Arsenal", {"elo": 1.0})
        assert result == {}

    def test_empty_weights_returns_empty_dict(self):
        """Empty weights returns empty dict."""
        bp = _make_blended_prediction()
        result = compute_signal_contributions([bp], "Arsenal", {})
        assert result == {}

    def test_team_not_in_matches_returns_empty_dict(self):
        """Target team with no matches returns empty dict when match_fixtures provided."""
        bp = _make_blended_prediction()
        match = _make_team_match("Man City", "Bayern")
        result = compute_signal_contributions(
            [bp], "Arsenal", {"elo": 1.0},
            match_fixtures=[match],
        )
        assert result == {}

    def test_basic_contributions_with_match_fixtures(self):
        """Contributions computed correctly for target team's matches."""
        bp = _make_blended_prediction(
            home=0.6, draw=0.25, away=0.15,
            signal_breakdown={
                "elo": {"home": 0.7, "draw": 0.2, "away": 0.1, "weight": 0.5},
                "market": {"home": 0.5, "draw": 0.3, "away": 0.2, "weight": 0.5},
            },
            weights={"elo": 0.5, "market": 0.5},
        )
        match = _make_team_match("Arsenal", "Chelsea")
        result = compute_signal_contributions(
            [bp], "Arsenal", {"elo": 0.5, "market": 0.5},
            match_fixtures=[match],
        )
        assert "elo" in result
        assert "market" in result
        # Arsenal is home: elo contribution = 0.5 * (0.7 - 1/3) ≈ 0.1833
        # market contribution = 0.5 * (0.5 - 1/3) ≈ 0.0833
        assert abs(result["elo"] - 0.1833) < 0.01
        assert abs(result["market"] - 0.0833) < 0.01

    def test_away_match_direction(self):
        """Away matches use away probability for target team."""
        bp = _make_blended_prediction(
            home=0.3, draw=0.25, away=0.45,
            signal_breakdown={
                "elo": {"home": 0.3, "draw": 0.25, "away": 0.45, "weight": 1.0},
            },
            weights={"elo": 1.0},
        )
        match = _make_team_match("Chelsea", "Arsenal")
        result = compute_signal_contributions(
            [bp], "Arsenal", {"elo": 1.0},
            match_fixtures=[match],
        )
        # Arsenal is away: elo contribution = 1.0 * (0.45 - 1/3) ≈ 0.1167
        assert abs(result["elo"] - 0.1167) < 0.01

    def test_single_signal_dominates(self):
        """Dominant signal's contribution reflects its weight."""
        bp_home = _make_blended_prediction(
            home=0.8, draw=0.15, away=0.05,
            signal_breakdown={
                "strong": {"home": 0.8, "draw": 0.15, "away": 0.05, "weight": 0.9},
                "weak": {"home": 0.5, "draw": 0.3, "away": 0.2, "weight": 0.1},
            },
            weights={"strong": 0.9, "weak": 0.1},
        )
        match = _make_team_match("Arsenal", "Chelsea")
        result = compute_signal_contributions(
            [bp_home], "Arsenal", {"strong": 0.9, "weak": 0.1},
            match_fixtures=[match],
        )
        # Strong signal contributes much more
        assert abs(result["strong"]) > abs(result["weak"]) * 3

    def test_negative_contribution(self):
        """Signals below uniform baseline produce negative contributions."""
        bp = _make_blended_prediction(
            home=0.2, draw=0.3, away=0.5,
            signal_breakdown={
                "bad": {"home": 0.2, "draw": 0.3, "away": 0.5, "weight": 1.0},
            },
            weights={"bad": 1.0},
        )
        match = _make_team_match("Arsenal", "Chelsea")
        result = compute_signal_contributions(
            [bp], "Arsenal", {"bad": 1.0},
            match_fixtures=[match],
        )
        # bad gives home=0.2, below uniform=0.333 → negative contribution
        assert result["bad"] < 0

    def test_multiple_matches_accumulate(self):
        """Contributions from multiple matches accumulate."""
        bp1 = _make_blended_prediction(
            home=0.7, draw=0.2, away=0.1,
            signal_breakdown={
                "elo": {"home": 0.7, "draw": 0.2, "away": 0.1, "weight": 1.0},
            },
            weights={"elo": 1.0},
        )
        bp2 = _make_blended_prediction(
            home=0.3, draw=0.25, away=0.45,
            signal_breakdown={
                "elo": {"home": 0.3, "draw": 0.25, "away": 0.45, "weight": 1.0},
            },
            weights={"elo": 1.0},
        )
        matches = [
            _make_team_match("Arsenal", "Chelsea", "M01"),
            _make_team_match("Liverpool", "Arsenal", "M02"),
        ]
        result = compute_signal_contributions(
            [bp1, bp2], "Arsenal", {"elo": 1.0},
            match_fixtures=matches,
        )
        # bp1: Arsenal is home → 1.0 * (0.7 - 1/3) = 0.3667
        # bp2: Arsenal is away → 1.0 * (0.45 - 1/3) = 0.1167
        # total ≈ 0.4833
        assert abs(result["elo"] - 0.4833) < 0.01

    def test_without_match_fixtures_fallback(self):
        """Without match_fixtures, function computes across all matches (no crash)."""
        bp = _make_blended_prediction()
        result = compute_signal_contributions(
            [bp], "Arsenal", {"elo": 0.5, "market": 0.3, "form": 0.2},
        )
        assert "elo" in result
        assert "market" in result
        assert len(result) > 0

    def test_mismatched_fixtures_length(self):
        """Mismatched fixture list length falls back to global mode."""
        bp = _make_blended_prediction()
        result = compute_signal_contributions(
            [bp], "Arsenal", {"elo": 1.0},
            match_fixtures=[],  # empty vs 1 prediction
        )
        assert len(result) > 0  # falls back gracefully

    def test_missing_signal_in_breakdown(self):
        """Signal in weights but not in breakdown is skipped (no KeyError)."""
        bp = _make_blended_prediction(
            signal_breakdown={
                "elo": {"home": 0.6, "draw": 0.25, "away": 0.15, "weight": 1.0},
            },
        )
        match = _make_team_match("Arsenal", "Chelsea")
        result = compute_signal_contributions(
            [bp], "Arsenal", {"elo": 1.0, "missing_signal": 0.5},
            match_fixtures=[match],
        )
        assert "missing_signal" not in result or result["missing_signal"] == 0.0

    def test_missing_champion_team_handling(self):
        """Can handle case where bracket_champion is None."""
        contributions = compute_signal_contributions(
            [_make_blended_prediction()], None, {"elo": 1.0},
        )
        assert isinstance(contributions, dict)

