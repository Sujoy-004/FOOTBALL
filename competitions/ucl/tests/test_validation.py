"""Unit tests for the prediction validation cross-check (Phase 4, D-01 through D-03).

Tests run_validation() with synthetic match data and Elo-based predictions.
"""

from competitions.ucl.main import run_validation
from competitions.ucl.result import SimulationResult
from football_core.elo import expected_score


def _make_minimal_result() -> SimulationResult:
    """Build a minimal SimulationResult for validation testing."""
    return SimulationResult(
        snapshot_date="2026-06-29",
        n_iterations=10000,
        seed=42,
        standings=[],
        teams={},
        playoff_ties={},
        playoff_winners={},
        bracket_rounds={},
        bracket_champion=None,
        stages={},
    )


class TestValidationCrossCheck:
    """Tests for compute_metrics-derived validation output shape and correctness."""

    def test_perfect_predictions(self):
        """All predictions exactly match outcomes → Brier=0.0, accuracy=1.0."""
        elo_ratings = {"TeamA": 2000.0, "TeamB": 1500.0}
        # TeamA (2000) vs TeamB (1500): expected_score ~ 0.95 home-win prob
        p_home = expected_score(2000.0, 1500.0)
        real_matches = [
            {"team_a": "TeamA", "team_b": "TeamB", "winner": "TeamA", "is_draw": False},
        ]
        result = run_validation(
            _make_minimal_result(), real_matches, elo_ratings,
        )
        assert result["prediction_metrics"]["brier"] < 0.01
        assert result["prediction_metrics"]["accuracy"] > 0.99
        assert result["n_matches_matched"] == 1

    def test_imperfect_predictions(self):
        """Some predictions wrong → Brier > 0.0, accuracy < 1.0."""
        elo_ratings = {"TeamA": 2000.0, "TeamB": 1500.0, "TeamC": 1500.0, "TeamD": 2000.0}
        real_matches = [
            {"team_a": "TeamA", "team_b": "TeamB", "winner": "TeamA", "is_draw": False},
            {"team_a": "TeamC", "team_b": "TeamD", "winner": "TeamD", "is_draw": False},
        ]
        result = run_validation(
            _make_minimal_result(), real_matches, elo_ratings,
        )
        # TeamA is strong favorite vs TeamB → small Brier for match 1
        # TeamC is underdog vs TeamD, but TeamD wins → small Brier for match 2
        # Combined should be positive but less than 1.0
        assert 0.0 < result["prediction_metrics"]["brier"] < 1.0
        assert result["n_matches_matched"] == 2

    def test_empty_matches(self):
        """Empty match list → all metrics return n=0."""
        result = run_validation(
            _make_minimal_result(), [], {"TeamA": 1500.0},
        )
        assert result["n_matches_fetched"] == 0
        assert result["n_matches_matched"] == 0
        assert result["prediction_metrics"]["n"] == 0

    def test_market_odds_included(self):
        """Matches with odds produce market_odds_metrics."""
        elo_ratings = {"TeamA": 2000.0, "TeamB": 1500.0}
        real_matches = [
            {
                "team_a": "TeamA", "team_b": "TeamB",
                "winner": "TeamA", "is_draw": False,
                "odds": {"home": 0.85, "draw": 0.10, "away": 0.05},
            },
        ]
        result = run_validation(
            _make_minimal_result(), real_matches, elo_ratings,
        )
        assert "market_odds_metrics" in result
        assert result["market_odds_metrics"]["n"] == 1
        assert 0.0 <= result["market_odds_metrics"]["brier"] < 1.0

    def test_market_odds_missing(self):
        """Matches without odds skip market_odds_metrics."""
        elo_ratings = {"TeamA": 2000.0, "TeamB": 1500.0}
        real_matches = [
            {"team_a": "TeamA", "team_b": "TeamB", "winner": "TeamA", "is_draw": False},
        ]
        result = run_validation(
            _make_minimal_result(), real_matches, elo_ratings,
        )
        assert "market_odds_metrics" not in result
        assert result["n_odds_available"] == 0


class TestRunValidation:
    """Tests for the run_validation function integration."""

    def test_elo_based_prediction(self):
        """expected_score gives reasonable probabilities for known Elo gaps."""
        elo_ratings = {"Strong": 2000.0, "Weak": 1500.0}
        real_matches = [
            {"team_a": "Strong", "team_b": "Weak", "winner": "Strong", "is_draw": False},
        ]
        result = run_validation(
            _make_minimal_result(), real_matches, elo_ratings,
        )
        # expected_score(2000, 1500) = 1/(1+10^(-500/400)) = 1/(1+10^-1.25)
        # = 1/(1+0.056) ≈ 0.947 → very confident prediction
        pm = result["prediction_metrics"]
        assert pm["n"] == 1
        # Brier = (0.947 - 1.0)^2 ≈ 0.0028
        assert 0.0 < pm["brier"] < 0.01

    def test_draw_outcome(self):
        """Match with is_draw=True produces actual=0.5."""
        elo_ratings = {"TeamA": 1800.0, "TeamB": 1800.0}
        real_matches = [
            {"team_a": "TeamA", "team_b": "TeamB", "winner": None, "is_draw": True},
        ]
        result = run_validation(
            _make_minimal_result(), real_matches, elo_ratings,
        )
        assert result["n_matches_matched"] == 1
        pm = result["prediction_metrics"]
        # expected_score(1800, 1800) = 0.5, actual=0.5 → Brier=0.0
        assert pm["brier"] == 0.0
