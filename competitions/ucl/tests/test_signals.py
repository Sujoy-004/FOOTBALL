"""Tests for all signal implementations."""

import math

from football_core.signal import Signal, SignalOutput, PredictionContext
from football_core.signals.refined_elo import RefinedEloSignal
from football_core.signals.market_odds import MarketOddsSignal
from football_core.signals.rolling_form import RollingFormSignal
from football_core.signals.squad_value import SquadValueSignal
from football_core.signals.rest_days import RestDaysSignal
from football_core.result_provider import MatchResultProvider


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


class TestRollingFormSignal:
    """Verify RollingFormSignal behavior."""

    def test_conforms_to_protocol(self, empty_result_provider):
        assert isinstance(RollingFormSignal(empty_result_provider), Signal)

    def test_default_windows(self, empty_result_provider):
        sig = RollingFormSignal(empty_result_provider)
        assert sig._windows == [3, 5, 10]

    def test_accepts_provider(self, empty_result_provider):
        sig = RollingFormSignal(empty_result_provider)
        assert sig._result_provider is empty_result_provider

    def test_predict_no_results(self, empty_result_provider):
        sig = RollingFormSignal(empty_result_provider)
        match = {"team_a": "A", "team_b": "B", "event_date": "2026-10-01"}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        assert abs(result.home_prob - 0.5) < 0.1

    def test_predict_all_wins_home(self):
        class _AllWinsProvider:
            def get_team_results(self, team, before_date, limit=10):
                if team == "HomeTeam":
                    return [
                        {"event_date": "2026-09-01", "winner": "HomeTeam", "is_draw": False},
                        {"event_date": "2026-08-25", "winner": "HomeTeam", "is_draw": False},
                    ]
                return [
                    {"event_date": "2026-09-01", "winner": "Other", "is_draw": False},
                    {"event_date": "2026-08-25", "winner": "Other", "is_draw": False},
                ]

        sig = RollingFormSignal(_AllWinsProvider())
        match = {"team_a": "HomeTeam", "team_b": "AwayTeam", "event_date": "2026-10-01"}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        assert result.home_prob > result.away_prob

    def test_predict_output_sum_near_one(self, empty_result_provider):
        sig = RollingFormSignal(empty_result_provider)
        match = {"team_a": "A", "team_b": "B", "event_date": "2026-10-01"}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        total = result.home_prob + result.draw_prob + result.away_prob
        assert abs(total - 1.0) < 1e-10


class TestSquadValueSignal:
    """Verify SquadValueSignal behavior."""

    def test_conforms_to_protocol(self):
        assert isinstance(SquadValueSignal(), Signal)

    def test_predict_equal_values(self):
        sig = SquadValueSignal()
        match = {"team_a": "A", "team_b": "B"}
        ctx = PredictionContext(
            fixtures=[],
            elo_ratings={},
            squad_values={"A": 500.0, "B": 500.0},
        )
        result = sig.predict(match, ctx)
        assert abs(result.home_prob - result.away_prob) < 0.01

    def test_predict_home_favorite(self):
        sig = SquadValueSignal()
        match = {"team_a": "Rich", "team_b": "Poor"}
        ctx = PredictionContext(
            fixtures=[],
            elo_ratings={},
            squad_values={"Rich": 1200.0, "Poor": 100.0},
        )
        result = sig.predict(match, ctx)
        assert result.home_prob > result.away_prob

    def test_log_transform_compresses(self):
        sig = SquadValueSignal()
        ratio_raw = 1200.0 / 100.0
        ratio_log = math.log(1200.0) / math.log(100.0)
        assert ratio_log < ratio_raw

    def test_predict_with_context_values(self):
        sig = SquadValueSignal()
        match = {"team_a": "A", "team_b": "B"}
        ctx = PredictionContext(
            fixtures=[],
            elo_ratings={},
            squad_values={"A": 1000.0, "B": 500.0},
        )
        result = sig.predict(match, ctx)
        assert result.home_prob > result.away_prob

    def test_predict_output_sum_near_one(self):
        sig = SquadValueSignal()
        match = {"team_a": "A", "team_b": "B"}
        ctx = PredictionContext(
            fixtures=[],
            elo_ratings={},
            squad_values={"A": 800.0, "B": 600.0},
        )
        result = sig.predict(match, ctx)
        total = result.home_prob + result.draw_prob + result.away_prob
        assert abs(total - 1.0) < 1e-10

    def test_predict_missing_team_falls_back(self):
        sig = SquadValueSignal()
        match = {"team_a": "Unknown", "team_b": "Known"}
        ctx = PredictionContext(
            fixtures=[],
            elo_ratings={},
            squad_values={"Known": 500.0},
        )
        result = sig.predict(match, ctx)
        assert isinstance(result, SignalOutput)
        total = result.home_prob + result.draw_prob + result.away_prob
        assert abs(total - 1.0) < 1e-10


class TestRestDaysSignal:
    """Verify RestDaysSignal behavior."""

    def test_conforms_to_protocol(self):
        assert isinstance(RestDaysSignal(), Signal)

    def test_predict_equal_rest(self):
        sig = RestDaysSignal()
        match = {"team_a": "A", "team_b": "B", "event_date": "2026-10-01"}
        ctx = PredictionContext(
            fixtures=[], elo_ratings={},
        )
        result = sig.predict(match, ctx)
        assert abs(result.home_prob - 1 / 3) < 0.01

    def test_predict_home_advantage_rest(self):
        sig = RestDaysSignal()
        match = {"team_a": "A", "team_b": "B", "event_date": "2026-10-01"}
        ctx = PredictionContext(
            fixtures=[
                {"team_a": "A", "team_b": "X", "event_date": "2026-09-20"},
            ],
            elo_ratings={},
        )
        result = sig.predict(match, ctx)
        assert result.home_prob > result.away_prob

    def test_compute_rest_days_no_prior(self):
        sig = RestDaysSignal()
        days = sig._compute_rest_days("Team", "2026-10-01", [])
        assert days == 7

    def test_compute_rest_days_correct_diff(self):
        sig = RestDaysSignal()
        fixtures = [
            {"team_a": "Team", "team_b": "Other", "event_date": "2026-09-24"},
        ]
        days = sig._compute_rest_days("Team", "2026-10-01", fixtures)
        assert days == 7

    def test_predict_away_advantage_rest(self):
        sig = RestDaysSignal()
        match = {"team_a": "A", "team_b": "B", "event_date": "2026-10-01"}
        ctx = PredictionContext(
            fixtures=[
                {"team_a": "B", "team_b": "X", "event_date": "2026-09-20"},
            ],
            elo_ratings={},
        )
        result = sig.predict(match, ctx)
        assert result.away_prob > result.home_prob

    def test_predict_output_sum_near_one(self):
        sig = RestDaysSignal()
        match = {"team_a": "A", "team_b": "B", "event_date": "2026-10-01"}
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = sig.predict(match, ctx)
        total = result.home_prob + result.draw_prob + result.away_prob
        assert abs(total - 1.0) < 1e-10
