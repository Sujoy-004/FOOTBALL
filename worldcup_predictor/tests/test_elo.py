"""Tests for the Elo rating engine.

Covers expected_score and update_ratings with 9 test cases:
equal ratings, table values, 400-gap, standard update, underdog win,
custom K, large gap, invalid winner, and no-mutation contract.
"""

import pytest

from src.elo import expected_score, update_ratings


# ─── expected_score tests ────────────────────────────────────────────────


class TestExpectedScore:
    """Tests for the expected_score function."""

    def test_equal_ratings(self):
        """Equal ratings should return 0.5 exactly."""
        assert expected_score(1500, 1500) == 0.5

    def test_table_values(self):
        """Should match eloratings.net expected score table (3 decimal places)."""
        assert round(expected_score(1600, 1500), 3) == 0.640
        assert round(expected_score(1500, 1600), 3) == 0.360

    def test_400_point_gap(self):
        """400-point gap should give expected score of ~0.909."""
        assert round(expected_score(1900, 1500), 3) == 0.909


# ─── update_ratings tests ────────────────────────────────────────────────


class TestUpdateRatings:
    """Tests for the update_ratings function."""

    def test_standard_update(self):
        """Argentina(2100) beats Nigeria(1800) → Arg ~2109, Nig ~1791."""
        elos = {"Argentina": 2100, "Nigeria": 1800, "France": 2050}
        result = update_ratings("Argentina", "Nigeria", "Argentina", elos, K=60)
        assert round(result["Argentina"], 0) == 2109
        assert round(result["Nigeria"], 0) == 1791
        # Unchanged team should not appear in result
        assert "France" not in result

    def test_underdog_wins(self):
        """Nigeria(1800) beats Argentina(2100) → larger swing for underdog."""
        elos = {"Argentina": 2100, "Nigeria": 1800}
        result = update_ratings("Argentina", "Nigeria", "Nigeria", elos, K=60)
        assert round(result["Nigeria"], 0) == 1851
        assert round(result["Argentina"], 0) == 2049

    def test_custom_k_factor(self):
        """K=40 produces changes that are 2/3 of K=60 changes."""
        elos = {"Argentina": 2100, "Nigeria": 1800}
        result = update_ratings("Argentina", "Nigeria", "Argentina", elos, K=40)
        assert round(result["Argentina"], 0) == 2106

    def test_large_elo_gap(self):
        """800+ point gap should not crash and return reasonable values."""
        elos = {"Strong": 2300, "Weak": 1500}
        result = update_ratings("Strong", "Weak", "Strong", elos, K=60)
        assert 0 < result["Strong"] < 3000
        assert 0 < result["Weak"] < 3000

    def test_invalid_winner_raises_error(self):
        """Winner that is neither team_a nor team_b should raise ValueError."""
        elos = {"A": 2000, "B": 1900}
        with pytest.raises(ValueError, match="must be"):
            update_ratings("A", "B", "C", elos)

    def test_does_not_mutate_input(self):
        """update_ratings should NOT modify the input elos dict (immutability)."""
        elos = {"A": 2000, "B": 1900}
        before_a = elos["A"]
        update_ratings("A", "B", "A", elos, K=60)
        assert elos["A"] == before_a  # unchanged
