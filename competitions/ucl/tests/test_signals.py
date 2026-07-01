"""Tests for signal implementations — RefinedEloSignal and MarketOddsSignal."""

from football_core.signal import Signal, SignalOutput, PredictionContext
from football_core.signals.refined_elo import RefinedEloSignal
from football_core.signals.market_odds import MarketOddsSignal


class TestRefinedEloSignal:
    """Verify RefinedEloSignal behavior."""

    def test_conforms_to_protocol(self):
        assert isinstance(RefinedEloSignal(), Signal)

    def test_predict_returns_signal_output(self, sample_match_data, sample_prediction_context):
        sig = RefinedEloSignal()
        result = sig.predict(sample_match_data, sample_prediction_context)
        assert isinstance(result, SignalOutput)

    def test_predict_equal_elos(self):
        sig = RefinedEloSignal(home_advantage=0)
        match = {"team_a": "TeamA", "team_b": "TeamB"}
        ctx = PredictionContext(fixtures=[], elo_ratings={"TeamA": 1500.0, "TeamB": 1500.0})
        result = sig.predict(match, ctx)
        assert abs(result.home_prob - 0.5) < 0.1

    def test_predict_strong_home_favorite(self):
        sig = RefinedEloSignal()
        match = {"team_a": "Strong", "team_b": "Weak"}
        ctx = PredictionContext(fixtures=[], elo_ratings={"Strong": 2000.0, "Weak": 1500.0})
        result = sig.predict(match, ctx)
        assert result.home_prob > result.away_prob

    def test_predict_uses_home_advantage(self):
        sig = RefinedEloSignal()
        match = {"team_a": "A", "team_b": "B"}
        ctx = PredictionContext(fixtures=[], elo_ratings={"A": 1500.0, "B": 1500.0})
        result = sig.predict(match, ctx)
        assert result.home_prob > 0.5

    def test_configurable_k_factor(self):
        sig = RefinedEloSignal(k_factor=40)
        assert sig._k_factor == 40

    def test_predict_output_sum_near_one(self, sample_match_data, sample_prediction_context):
        sig = RefinedEloSignal()
        result = sig.predict(sample_match_data, sample_prediction_context)
        total = result.home_prob + result.draw_prob + result.away_prob
        assert abs(total - 1.0) < 1e-10


class TestMarketOddsSignal:
    """Verify MarketOddsSignal behavior."""

    def test_conforms_to_protocol(self):
        assert isinstance(MarketOddsSignal(), Signal)

    def test_predict_with_valid_odds(self):
        sig = MarketOddsSignal()
        match = {"match_id": "M1", "odds_home": 2.0, "odds_draw": 3.5, "odds_away": 4.0}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        assert isinstance(result, SignalOutput)

    def test_predict_vig_removed(self):
        sig = MarketOddsSignal()
        match = {"match_id": "M1", "odds_home": 2.0, "odds_draw": 3.5, "odds_away": 4.0}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        total = result.home_prob + result.draw_prob + result.away_prob
        assert abs(total - 1.0) < 1e-10

    def test_predict_missing_odds_returns_uniform(self):
        sig = MarketOddsSignal()
        match = {"match_id": "M1"}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        assert abs(result.home_prob - 1 / 3) < 1e-10

    def test_predict_some_odds_missing_returns_uniform(self):
        sig = MarketOddsSignal()
        match = {"match_id": "M1", "odds_home": 2.0}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        assert abs(result.home_prob - 1 / 3) < 1e-10

    def test_predict_with_negative_odds_returns_uniform(self):
        sig = MarketOddsSignal()
        match = {"match_id": "M1", "odds_home": -1.0, "odds_draw": 3.5, "odds_away": 4.0}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        assert abs(result.home_prob - 1 / 3) < 1e-10
