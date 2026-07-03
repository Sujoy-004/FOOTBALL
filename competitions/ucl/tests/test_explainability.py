"""Tests for signal contribution breakdown — Phase 11, Plan 11-01.

Covers:
    - compute_signal_contributions() computation and edge cases
    - print_signal_breakdown() display formatting
    - Integration with main output pipeline
"""

from __future__ import annotations

import io
import sys
from typing import Any

import pytest

from football_core.blender import compute_signal_contributions
from football_core.signal import BlendedPrediction
from competitions.ucl import display


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_blended_prediction(
    home: float = 0.5,
    draw: float = 0.3,
    away: float = 0.2,
    signal_breakdown: dict[str, dict[str, float]] | None = None,
    weights: dict[str, float] | None = None,
) -> BlendedPrediction:
    """Create a BlendedPrediction with uniform signal breakdown if none given."""
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


def _capture(func, *args, **kwargs) -> str:
    """Capture stdout from a display function."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


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


# ── TestSignalBreakdownDisplay ──────────────────────────────────────────────


class TestSignalBreakdownDisplay:
    """Tests for print_signal_breakdown()."""

    def test_output_contains_prediction_breakdown_header(self):
        """Output contains section header."""
        output = _capture(
            display.print_signal_breakdown,
            {"elo": 0.5, "market": 0.3},
            "Arsenal",
            68.8,
        )
        assert "==== Prediction Breakdown ===" in output

    def test_shows_champion_team_and_prob(self):
        """Champion team name and probability appear in output."""
        output = _capture(
            display.print_signal_breakdown,
            {"elo": 0.5, "market": 0.3},
            "Arsenal",
            68.8,
        )
        assert "Arsenal" in output
        assert "68.8%" in output

    def test_positive_contributions_formatted_with_plus(self):
        """Positive contributions display with '+' prefix."""
        output = _capture(
            display.print_signal_breakdown,
            {"elo": 31.2, "market": 22.4},
            "Arsenal",
            53.6,
        )
        assert "+31.2%" in output or "+31.2" in output

    def test_negative_contributions_formatted_with_minus(self):
        """Negative contributions display with '-' prefix (among positive ones)."""
        output = _capture(
            display.print_signal_breakdown,
            {"good": 30.0, "bad": -5.0},
            "Arsenal",
            68.8,
        )
        assert "-" in output
        assert "good" in output
        assert "bad" in output

    def test_empty_contributions_does_not_crash(self):
        """Empty contributions dict does not crash and shows placeholder."""
        output = _capture(
            display.print_signal_breakdown,
            {},
            "Arsenal",
            68.8,
        )
        assert "No signal contribution data available" in output or "Prediction Breakdown" in output

    def test_total_matches_champion_prob(self):
        """Total line shows champion_prob."""
        output = _capture(
            display.print_signal_breakdown,
            {"elo": 0.5, "market": 0.3},
            "Arsenal",
            68.8,
        )
        assert "68.8%" in output

    def test_all_signals_appear_in_output(self):
        """Every signal in the contributions dict appears."""
        contribs = {"elo": 31.2, "market": 22.4, "form": 5.1, "squad": 3.2, "rest": 1.0}
        output = _capture(
            display.print_signal_breakdown,
            contribs,
            "Arsenal",
            62.9,
        )
        for sig in contribs:
            assert sig in output, f"Signal '{sig}' not found in output"

    def test_sorted_by_abs_contribution_descending(self):
        """Signals are sorted by absolute contribution value descending."""
        contribs = {"small": 1.0, "medium": 10.0, "large": 50.0}
        output = _capture(
            display.print_signal_breakdown,
            contribs,
            "Arsenal",
            61.0,
        )
        # Check order by finding positions
        positions = {}
        for sig in ("large", "medium", "small"):
            pos = output.find(sig)
            assert pos >= 0, f"Signal '{sig}' not found"
            positions[sig] = pos
        assert positions["large"] < positions["medium"] < positions["small"], (
            "Signals not sorted by absolute value descending"
        )


# ── TestIntegration ─────────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests for signal breakdown in main output pipeline.

    These tests verify the module-level integration works correctly.
    """

    def test_compute_signal_contributions_integration(self):
        """End-to-end: fake data flows through both functions without error."""
        bp = _make_blended_prediction(
            home=0.6, draw=0.25, away=0.15,
            signal_breakdown={
                "elo": {"home": 0.6, "draw": 0.25, "away": 0.15, "weight": 0.5},
                "market": {"home": 0.5, "draw": 0.3, "away": 0.2, "weight": 0.3},
            },
            weights={"elo": 0.5, "market": 0.3},
        )
        match = _make_team_match("Arsenal", "Chelsea")

        contributions = compute_signal_contributions(
            [bp], "Arsenal", {"elo": 0.5, "market": 0.3},
            match_fixtures=[match],
        )
        assert isinstance(contributions, dict)
        assert len(contributions) > 0

        # Display should not crash
        output = _capture(
            display.print_signal_breakdown,
            contributions,
            "Arsenal",
            60.0,
        )
        assert "Prediction Breakdown" in output

    def test_missing_champion_team_handling(self):
        """Can handle case where bracket_champion is None."""
        contributions = compute_signal_contributions(
            [_make_blended_prediction()], None, {"elo": 1.0},
        )
        # Should not crash; returns empty dict for None target
        assert isinstance(contributions, dict)
