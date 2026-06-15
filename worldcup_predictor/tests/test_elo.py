"""Tests for the Elo rating engine.

Covers expected_score and update_ratings with 9 test cases:
equal ratings, table values, 400-gap, standard update, underdog win,
custom K, large gap, invalid winner, and no-mutation contract.
"""

import pytest

from src.elo import apply_elo_update, compute_k_factor, expected_score, update_ratings


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

    def test_draw_equal_ratings(self):
        """Draw with equal ratings → both change by same amount toward 0.5."""
        elos = {"A": 2000, "B": 2000}
        result = update_ratings("A", "B", None, elos, K=60)
        assert result["A"] == result["B"]  # symmetric
        assert result["A"] == 2000.0       # 2000 + 60*(0.5-0.5) = 2000

    def test_draw_favored_team_loses_elo(self):
        """Draw when A is heavily favored → A loses Elo, B gains."""
        elos = {"A": 2200, "B": 1800}
        result = update_ratings("A", "B", None, elos, K=60)
        e_a = expected_score(2200, 1800)
        assert result["A"] < 2200  # A underperformed
        assert result["B"] > 1800  # B overperformed
        expected_a = 2200 + 60 * (0.5 - e_a)
        expected_b = 1800 + 60 * (0.5 - (1 - e_a))
        assert round(result["A"], 1) == round(expected_a, 1)
        assert round(result["B"], 1) == round(expected_b, 1)

    def test_apply_elo_update_mutates_teams(self):
        """apply_elo_update mutates teams dict in-place and returns changes."""
        teams = {"Arg": {"elo": 2100}, "Nig": {"elo": 1800}}
        match = {"team_a": "Arg", "team_b": "Nig", "winner": "Arg"}
        updates = apply_elo_update(match, teams)
        assert teams["Arg"]["elo"] > 2100
        assert teams["Nig"]["elo"] < 1800
        assert updates["Arg"]["old"] == 2100
        assert updates["Arg"]["new"] == teams["Arg"]["elo"]

    def test_apply_elo_update_draw(self):
        """apply_elo_update works with winner=None (draw)."""
        teams = {"Arg": {"elo": 2100}, "Nig": {"elo": 1800}}
        match = {"team_a": "Arg", "team_b": "Nig", "winner": None}
        e_a = expected_score(2100, 1800)
        apply_elo_update(match, teams)
        expected = 2100 + 60 * (0.5 - e_a)
        assert round(teams["Arg"]["elo"], 1) == round(expected, 1)


# ─── compute_k_factor tests ────────────────────────────────────────────────


class TestComputeKFactor:
    """Tests for the compute_k_factor function."""

    def test_gd_0(self):
        """GD=0 (draw) → G=1.0, returns base_K unchanged."""
        assert compute_k_factor(0, 60) == 60.0

    def test_gd_1(self):
        """GD=1 (one-goal win) → G=1.0, returns base_K unchanged."""
        assert compute_k_factor(1, 60) == 60.0

    def test_gd_2(self):
        """GD=2 → G=1.5, returns 1.5 * base_K."""
        assert compute_k_factor(2, 60) == 90.0

    def test_gd_3(self):
        """GD=3 → G=(11+3)/8 = 1.75, returns 1.75 * 60 = 105.0."""
        assert compute_k_factor(3, 60) == 105.0

    def test_gd_7(self):
        """GD=7 → G=(11+7)/8 = 2.25, returns 2.25 * 60 = 135.0."""
        assert compute_k_factor(7, 60) == 135.0

    def test_custom_base_k(self):
        """Custom base_K=40, GD=2 → G=1.5, returns 1.5 * 40 = 60.0."""
        assert compute_k_factor(2, 40) == 60.0
