"""Tests for the UCL ensemble strategy selector + Market+Elo composite signal."""

import pytest

from football_core.signal import PredictionContext
from football_core.signals.market_odds import MarketOddsSignal
from football_core.signals.refined_elo import RefinedEloSignal

from competitions.ucl.src.ensemble import (
    MARKET_ELO_EQUAL_WEIGHTS,
    STRATEGIES,
    MarketEloSignal,
    build_strategy_engine,
    load_prior_weights,
)

PRIOR_FILE_WEIGHTS = {"market_odds": 0.539480, "refined_elo": 0.460520}


def _match_with_odds():
    return {
        "match_id": "T1",
        "team_a": "Alpha",
        "team_b": "Beta",
        "odds_home": 2.0,
        "odds_draw": 3.5,
        "odds_away": 4.0,
    }


def _match_without_odds():
    return {k: v for k, v in _match_with_odds().items() if not k.startswith("odds_")}


def _context():
    return PredictionContext(fixtures=[], elo_ratings={"Alpha": 2000.0, "Beta": 1800.0})


def _registered_signals(engine):
    return engine._registry.list()


# ── Strategy selector ────────────────────────────────────────────────────


class TestStrategySelector:
    def test_known_strategies_tuple_contains_production_and_candidates(self):
        assert STRATEGIES == ("production", "market_elo_equal", "market_elo_prior")

    def test_equal_strategy_default_weights(self):
        engine = build_strategy_engine("market_elo_equal", elo_ratings={})
        assert engine.weights == {"market_elo": 1.0}
        assert _registered_signals(engine) == ["market_elo"]
        sig = engine._registry.get("market_elo")
        assert sig.weights == MARKET_ELO_EQUAL_WEIGHTS

    def test_prior_strategy_builds(self):
        engine = build_strategy_engine("market_elo_prior", elo_ratings={})
        assert engine.weights == {"market_elo": 1.0}
        assert _registered_signals(engine) == ["market_elo"]

    def test_bad_strategy_raises_value_error(self):
        for bad in ("bogus", "production"):
            with pytest.raises(ValueError):
                build_strategy_engine(bad, elo_ratings={})

    def test_orchestrator_production_default_is_five_signals(self):
        from competitions.ucl.src.orchestrator import build_signal_engine

        engine = build_signal_engine(elo_ratings={})
        assert set(_registered_signals(engine)) == {
            "market_odds",
            "refined_elo",
            "rolling_form",
            "rest_days",
            "squad_value",
        }

    def test_orchestrator_market_elo_equal_registers_market_elo(self):
        from competitions.ucl.src.orchestrator import build_signal_engine

        engine = build_signal_engine(elo_ratings={}, strategy="market_elo_equal")
        assert "market_elo" in _registered_signals(engine)
        assert engine.weights == {"market_elo": 1.0}

    def test_orchestrator_unknown_strategy_raises(self):
        from competitions.ucl.src.orchestrator import build_signal_engine

        with pytest.raises(ValueError):
            build_signal_engine(elo_ratings={}, strategy="bogus")


# ── Market+Elo composition ───────────────────────────────────────────────


class TestMarketEloComposition:
    def test_blend_with_odds_matches_weighted_average(self):
        match = _match_with_odds()
        ctx = _context()
        signal = MarketEloSignal()
        out = signal.predict(match, ctx)

        m = MarketOddsSignal().predict(match, ctx)
        e = RefinedEloSignal().predict(match, ctx)
        raw_h = 0.5 * m.home_prob + 0.5 * e.home_prob
        raw_d = 0.5 * m.draw_prob + 0.5 * e.draw_prob
        raw_a = 0.5 * m.away_prob + 0.5 * e.away_prob
        total = raw_h + raw_d + raw_a

        assert abs(out.home_prob - raw_h / total) < 1e-6
        assert abs(out.draw_prob - raw_d / total) < 1e-6
        assert abs(out.away_prob - raw_a / total) < 1e-6
        assert abs(out.home_prob + out.draw_prob + out.away_prob - 1.0) < 1e-6

    def test_missing_odds_returns_exact_elo(self):
        match = _match_without_odds()
        ctx = _context()
        signal = MarketEloSignal()
        out = signal.predict(match, ctx)
        elo = RefinedEloSignal().predict(match, ctx)

        assert abs(out.home_prob - elo.home_prob) < 1e-9
        assert abs(out.draw_prob - elo.draw_prob) < 1e-9
        assert abs(out.away_prob - elo.away_prob) < 1e-9

        prov = signal.last_provenance()
        assert prov["usable_odds"] is False
        assert prov["market_odds"] is None
        assert prov["used_signals"] == ["refined_elo"]
        assert prov["weights"] == {"refined_elo": 1.0}

    def test_provenance_with_odds_equal_weights(self):
        signal = MarketEloSignal()
        signal.predict(_match_with_odds(), _context())
        prov = signal.last_provenance()

        assert prov["usable_odds"] is True
        assert prov["market_odds"] is not None
        assert sorted(prov["market_odds"].keys()) == ["away", "draw", "home"]
        assert prov["used_signals"] == ["market_odds", "refined_elo"]
        assert prov["weights"] == {"market_odds": 0.5, "refined_elo": 0.5}
        elo = RefinedEloSignal().predict(_match_with_odds(), _context())
        assert prov["refined_elo"] == {
            "home": elo.home_prob,
            "draw": elo.draw_prob,
            "away": elo.away_prob,
        }

    def test_provenance_reflects_configured_weights(self):
        custom = {"market_odds": 0.7, "refined_elo": 0.3}
        signal = MarketEloSignal(custom)
        signal.predict(_match_with_odds(), _context())
        prov = signal.last_provenance()
        assert prov["weights"] == custom

    def test_determinism_and_provenance_reset(self):
        signal = MarketEloSignal()
        ctx = _context()
        match = _match_with_odds()
        a = signal.predict(match, ctx)
        b = signal.predict(match, ctx)

        assert a.home_prob == b.home_prob
        assert a.draw_prob == b.draw_prob
        assert a.away_prob == b.away_prob
        assert signal.last_provenance() != {}

        signal.reset_provenance()
        assert signal.last_provenance() == {}

    def test_does_not_mutate_match_or_context(self):
        signal = MarketEloSignal()
        match = _match_with_odds()
        ctx = _context()
        match_before = dict(match)
        match["odds_home"] = 2.0

        signal.predict(match, ctx)
        assert match == match_before
        assert ctx.elo_ratings == {"Alpha": 2000.0, "Beta": 1800.0}


# ── Prior weights loader ─────────────────────────────────────────────────


class TestPriorWeightsLoader:
    def test_load_prior_weights(self):
        weights, source = load_prior_weights()
        assert source == "market_elo_prior_weights.json"
        assert weights is not None
        assert weights["market_odds"] == PRIOR_FILE_WEIGHTS["market_odds"]
        assert weights["refined_elo"] == PRIOR_FILE_WEIGHTS["refined_elo"]

    def test_prior_strategy_engine_signal_uses_file_weights(self):
        engine = build_strategy_engine("market_elo_prior", elo_ratings={})
        sig = engine._registry.get("market_elo")
        assert sig.weights == PRIOR_FILE_WEIGHTS
        assert sig.weights != MARKET_ELO_EQUAL_WEIGHTS


# ── Backward compatibility ───────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_production_strategy_uniform_fallback_builds(self):
        from competitions.ucl.src.orchestrator import build_signal_engine

        engine = build_signal_engine(elo_ratings={}, strategy="production")
        assert set(_registered_signals(engine)) == {
            "market_odds",
            "refined_elo",
            "rolling_form",
            "rest_days",
            "squad_value",
        }
        assert sum(engine.weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_market_elo_strategies_build_via_orchestrator(self):
        from competitions.ucl.src.orchestrator import build_signal_engine

        equal = build_signal_engine(elo_ratings={}, strategy="market_elo_equal")
        prior = build_signal_engine(elo_ratings={}, strategy="market_elo_prior")
        assert equal.weights == {"market_elo": 1.0}
        assert prior.weights == {"market_elo": 1.0}