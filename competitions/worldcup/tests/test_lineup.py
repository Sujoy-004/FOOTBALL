"""Tests for lineup.py — market value log-ratio signal computation.

All tests use inline fixtures (no real data files). Ledger operations
are monkeypatched to avoid real disk writes.
"""

import pytest

from src.predictors.lineup import (
    _compute_match_lineup_signal,
    _sigmoid,
    compute_lineup_signal,
)


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


# ─── Sigmoid Tests ───────────────────────────────────────────────────


class TestSigmoid:
    """Shared sigmoid function."""

    def test_sigmoid_zero(self):
        """sigmoid(0) == 0.5."""
        assert _sigmoid(0) == 0.5

    def test_sigmoid_positive(self):
        """sigmoid(1) > 0.5."""
        assert _sigmoid(1) > 0.5

    def test_sigmoid_negative(self):
        """sigmoid(-1) < 0.5."""
        assert _sigmoid(-1) < 0.5

    def test_sigmoid_symmetric(self):
        """sigmoid(-x) == 1 - sigmoid(x)."""
        assert abs(_sigmoid(-2) - (1 - _sigmoid(2))) < 1e-10

    def test_sigmoid_overflow_positive(self):
        """Large positive input returns 1.0."""
        assert _sigmoid(1000) == 1.0

    def test_sigmoid_overflow_negative(self):
        """Large negative input returns 0.0."""
        assert _sigmoid(-1000) == 0.0


# ─── Lineup Signal Tests ─────────────────────────────────────────────


class TestLineupSignal:
    """_compute_match_lineup_signal: single match lineup strength."""

    def test_basic(self, team_values):
        """Two teams with values → valid probability."""
        result = _compute_match_lineup_signal("France", "Panama", team_values, k=0.35)
        assert result["available"] is True
        assert result["probability"] is not None
        assert 0 < result["probability"] < 1

    def test_stronger_home(self, team_values):
        """Higher-value home team vs lower-value → p > 0.5."""
        result = _compute_match_lineup_signal("France", "Panama", team_values, k=0.35)
        assert result["probability"] > 0.5

    def test_lower_value_home_underdog(self, team_values):
        """Lower-value home team vs higher-value → p < 0.5."""
        result = _compute_match_lineup_signal("Panama", "France", team_values, k=0.35)
        assert result["probability"] < 0.5

    def test_equal_values(self, team_values):
        """Same value for both teams → p = 0.5."""
        # Use same team as both home and away
        result = _compute_match_lineup_signal("France", "France", team_values, k=0.35)
        assert result["probability"] == 0.5

    def test_available_flag(self, team_values):
        """Both teams in team_values → available=True."""
        result = _compute_match_lineup_signal("France", "England", team_values, k=0.35)
        assert result["available"] is True

    def test_extreme_ratio_clamped(self, team_values):
        """Very large value ratio → p close to 1 but still < 1."""
        # France (1.52B) vs Panama (7.5M) → ratio ≈ 203
        result = _compute_match_lineup_signal("France", "Panama", team_values, k=0.35)
        # ln(203) ≈ 5.31, sigmoid(0.35 * 5.31) = sigmoid(1.86) ≈ 0.865
        # Should be < 1 due to clamping
        assert result["probability"] < 1.0
        assert result["probability"] > 0.8


# ─── Lineup Edge Cases ───────────────────────────────────────────────


class TestLineupEdgeCases:
    """_compute_match_lineup_signal: error handling."""

    def test_missing_home(self, team_values):
        """Home team not in team_values → available=False with reason."""
        result = _compute_match_lineup_signal("Atlantis", "France", team_values, k=0.35)
        assert result["available"] is False
        assert "team_value_not_found" in result["reason"]
        assert "Atlantis" in result["reason"]

    def test_missing_away(self, team_values):
        """Away team not in team_values → available=False with reason."""
        result = _compute_match_lineup_signal("France", "Atlantis", team_values, k=0.35)
        assert result["available"] is False
        assert "team_value_not_found" in result["reason"]
        assert "Atlantis" in result["reason"]

    def test_both_missing(self, team_values):
        """Both teams not in team_values → available=False."""
        result = _compute_match_lineup_signal("Atlantis", "Olympus", team_values, k=0.35)
        assert result["available"] is False

    def test_non_positive_values(self, team_values):
        """Non-positive market value → available=False."""
        bad_values = dict(team_values)
        bad_values["France"] = 0
        result = _compute_match_lineup_signal("France", "Panama", bad_values, k=0.35)
        assert result["available"] is False
        assert "non_positive_value" in result["reason"]

    def test_negative_values(self, team_values):
        """Negative market value → available=False."""
        bad_values = dict(team_values)
        bad_values["France"] = -100
        result = _compute_match_lineup_signal("France", "Panama", bad_values, k=0.35)
        assert result["available"] is False
        assert "non_positive_value" in result["reason"]


# ─── Lineup Signal (Integration) Tests ───────────────────────────────


class TestLineupComputeSignal:
    """compute_lineup_signal: full pipeline integration."""

    def test_basic_integration(self, team_values, sample_groups, monkeypatch):
        """Basic signal computation via full pipeline."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
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

    def test_unresolved_bracket_slot_skipped(self, team_values, monkeypatch):
        """Bracket entry with None team_a/team_b → skipped gracefully."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
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

    def test_resolved_bracket_included(self, team_values, monkeypatch):
        """Bracket entry with resolved teams → included."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
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

    def test_has_timestamp_keys(self, team_values, sample_groups, monkeypatch):
        """Result dict has fetched_at and expires_at keys."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
        result = compute_lineup_signal(
            groups=sample_groups,
            team_values=team_values,
            bracket=[],
        )
        assert "fetched_at" in result
        assert "expires_at" in result


# ─── Ledger Tests ────────────────────────────────────────────────────


class TestLineupLedger:
    """Ledger upsert from compute_lineup_signal."""

    def test_ledger_upsert_called(self, team_values, sample_groups, monkeypatch):
        """compute_lineup_signal calls ledger_upsert for each match."""
        ledger_calls = []
        monkeypatch.setattr(
            "src.state.ledger_upsert",
            lambda mid, key, entry: ledger_calls.append((mid, key)),
        )
        compute_lineup_signal(
            groups=sample_groups,
            team_values=team_values,
            bracket=[],
        )
        assert len(ledger_calls) >= 1

    def test_ledger_key_lineup_strength(self, team_values, sample_groups, monkeypatch):
        """Ledger upsert uses signal key 'lineup_strength'."""
        ledger_calls = []
        monkeypatch.setattr(
            "src.state.ledger_upsert",
            lambda mid, key, entry: ledger_calls.append((mid, key)),
        )
        compute_lineup_signal(
            groups=sample_groups,
            team_values=team_values,
            bracket=[],
        )
        assert all(key == "lineup_strength" for _, key in ledger_calls)
