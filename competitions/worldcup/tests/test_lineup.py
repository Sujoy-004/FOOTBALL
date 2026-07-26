"""Tests for lineup.py — delegates to core LineupStrengthSignal.

All tests use inline fixtures (no real data files).
"""

import pytest

from src.predictors.lineup import compute_lineup_signal, _process_match
from football_core.signals.lineup import LineupStrengthSignal
from football_core.signal import PredictionContext


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def team_values():
    """Synthetic team market values in EUR."""
    return {
        "France": 1520000000,
        "England": 1200000000,
        "Brazil": 1050000000,
        "Argentina": 950000000,
        "Panama": 7500000,
    }


@pytest.fixture
def sample_groups():
    """Groups dict with one group of 2 teams and 1 match."""
    return {
        "groups": {
            "A": {
                "teams": ["France", "Panama"],
                "matches": [
                    {
                        "match_id": "GS_A_01",
                        "team_a": "France",
                        "team_b": "Panama",
                        "winner": None,
                        "score_a": None,
                        "score_b": None,
                    },
                ],
            }
        }
    }


# ─── _process_match Tests ───────────────────────────────────────────


def _make_context(squad_values=None):
    return PredictionContext(fixtures=[], elo_ratings={}, squad_values=squad_values)


class TestProcessMatch:
    """_process_match: single match processing via LineupStrengthSignal."""

    def test_basic(self, team_values):
        """Two teams with values → valid probability."""
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=team_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "France", "team_b": "Panama"}, signal, context, now, result, team_values)
        entry = result["GS_A_01"]
        assert entry["available"] is True
        assert entry["probability"] is not None
        assert 0 < entry["probability"] < 1

    def test_stronger_home(self, team_values):
        """Higher-value home team vs lower-value → p > 0.5."""
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=team_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "France", "team_b": "Panama"}, signal, context, now, result, team_values)
        assert result["GS_A_01"]["probability"] > 0.5

    def test_lower_value_home_underdog(self, team_values):
        """Lower-value home team vs higher-value → p < 0.5."""
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=team_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "Panama", "team_b": "France"}, signal, context, now, result, team_values)
        assert result["GS_A_01"]["probability"] < 0.5

    def test_equal_values(self, team_values):
        """Same value for both teams → p = 0.5."""
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=team_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "France", "team_b": "France"}, signal, context, now, result, team_values)
        assert result["GS_A_01"]["probability"] == 0.5

    def test_available_flag(self, team_values):
        """Both teams in team_values → available=True."""
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=team_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "France", "team_b": "England"}, signal, context, now, result, team_values)
        assert result["GS_A_01"]["available"] is True

    def test_missing_home(self, team_values):
        """Home team not in team_values → available=False with reason."""
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=team_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "Atlantis", "team_b": "France"}, signal, context, now, result, team_values)
        assert result["GS_A_01"]["available"] is False
        assert "team_value_not_found" in result["GS_A_01"]["reason"]

    def test_missing_away(self, team_values):
        """Away team not in team_values → available=False with reason."""
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=team_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "France", "team_b": "Atlantis"}, signal, context, now, result, team_values)
        assert result["GS_A_01"]["available"] is False
        assert "team_value_not_found" in result["GS_A_01"]["reason"]

    def test_non_positive_values(self, team_values):
        """Non-positive market value → available=False."""
        bad_values = dict(team_values)
        bad_values["France"] = 0
        signal = LineupStrengthSignal(k=0.35)
        context = _make_context(squad_values=bad_values)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        result = {}
        _process_match("GS_A_01", {"team_a": "France", "team_b": "Panama"}, signal, context, now, result, bad_values)
        assert result["GS_A_01"]["available"] is False
        assert "non_positive_value" in result["GS_A_01"]["reason"]


# ─── Lineup Signal (Integration) Tests ───────────────────────────────


class TestLineupComputeSignal:
    """compute_lineup_signal: full pipeline integration."""

    def test_basic_integration(self, team_values, sample_groups):
        """Basic signal computation via full pipeline."""
        result = compute_lineup_signal(
            groups=sample_groups,
            team_values=team_values,
            bracket=[],
        )
        assert "matches" in result
        assert "GS_A_01" in result["matches"]
        entry = result["matches"]["GS_A_01"]
        assert entry["available"] is True
        assert 0 < entry["probability"] < 1

    def test_unresolved_bracket_slot_skipped(self, team_values):
        """Bracket entry with None team_a/team_b → skipped gracefully."""
        groups = {"groups": {}}
        bracket = [
            {"match_id": "QF_1", "team_a": None, "team_b": None, "winner": None},
        ]
        result = compute_lineup_signal(
            groups=groups,
            team_values=team_values,
            bracket=bracket,
        )
        assert "QF_1" not in result["matches"]

    def test_resolved_bracket_included(self, team_values):
        """Bracket entry with resolved teams → included."""
        groups = {"groups": {}}
        bracket = [
            {"match_id": "R16_1", "team_a": "France", "team_b": "England", "winner": None},
        ]
        result = compute_lineup_signal(
            groups=groups,
            team_values=team_values,
            bracket=bracket,
        )
        assert "R16_1" in result["matches"]
        assert result["matches"]["R16_1"]["available"] is True

    def test_has_timestamp_keys(self, team_values, sample_groups):
        """Result dict has fetched_at and expires_at keys."""
        result = compute_lineup_signal(
            groups=sample_groups,
            team_values=team_values,
            bracket=[],
        )
        assert "fetched_at" in result
        assert "expires_at" in result


# ─── Cache Dict Tests ────────────────────────────────────────────────


class TestLineupCacheDict:
    """Lineup signal output from compute_lineup_signal."""

    def test_returns_matches(self, team_values, sample_groups):
        """compute_lineup_signal returns matches in cache dict."""
        result = compute_lineup_signal(
            groups=sample_groups,
            team_values=team_values,
            bracket=[],
        )
        assert "matches" in result
        assert len(result["matches"]) >= 1

    def test_signal_key_in_output(self, team_values, sample_groups):
        """Each match entry has probability key."""
        result = compute_lineup_signal(
            groups=sample_groups,
            team_values=team_values,
            bracket=[],
        )
        for mid, entry in result.get("matches", {}).items():
            assert "probability" in entry
