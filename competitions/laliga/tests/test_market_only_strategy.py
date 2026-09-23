"""Phase 12I — LaLiga selectable ``market_only`` strategy tests.

Covers strategy selection, odds-present blending against ``remove_vig``,
missing/partial/malformed-odds fallback to uniform, determinism, isolation
from the production five-signal engine, and the ``run_mc_simulation`` wiring.
"""
from __future__ import annotations

import math

import pytest

from football_core.predictors.odds import remove_vig
from football_core.signal import PredictionContext

from competitions.laliga.src.ensemble import STRATEGIES, build_strategy_engine
from competitions.laliga.src.pipeline import build_signal_engine
from competitions.laliga.src.simulation import run_mc_simulation

UNIFORM = (1 / 3, 1 / 3, 1 / 3)


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


def _registered(engine):
    return engine._registry.list()


def _assert_uniform(bp):
    expected = tuple(round(v, 6) for v in UNIFORM)  # engine emits 6-dp precision
    assert (bp.home_prob, bp.draw_prob, bp.away_prob) == expected


def _market_only_engine():
    return build_signal_engine({}, strategy="market_only")


# ── 1. strategy selection ────────────────────────────────────────────────


class TestStrategySelection:
    def test_strategies_tuple_lists_market_only(self):
        assert STRATEGIES == ("production", "market_only")

    def test_build_strategy_engine_market_only(self):
        engine = build_strategy_engine("market_only")
        assert engine.weights == {"market_odds": 1.0}
        assert _registered(engine) == ["market_odds"]

    def test_build_signal_engine_market_only(self):
        engine = build_signal_engine({}, strategy="market_only")
        assert engine.weights == {"market_odds": 1.0}
        assert _registered(engine) == ["market_odds"]


# ── 2. odds-present prediction ───────────────────────────────────────────


class TestOddsPresent:
    def test_blend_equals_remove_vig_at_engine_precision(self):
        engine = _market_only_engine()
        bp = engine.evaluate(_match_with_odds(), _context())
        rv = remove_vig(2.0, 3.5, 4.0)
        assert bp.home_prob == round(rv["home"], 6)
        assert bp.draw_prob == round(rv["draw"], 6)
        assert bp.away_prob == round(rv["away"], 6)

    def test_blend_sums_to_one(self):
        bp = _market_only_engine().evaluate(_match_with_odds(), _context())
        assert bp.home_prob + bp.draw_prob + bp.away_prob == pytest.approx(1.0, abs=1e-6)

    def test_blend_not_uniform(self):
        bp = _market_only_engine().evaluate(_match_with_odds(), _context())
        assert (bp.home_prob, bp.draw_prob, bp.away_prob) != pytest.approx(UNIFORM, abs=1e-9)


# ── 3. missing-odds fallback ─────────────────────────────────────────────


class TestOddsMissing:
    def test_no_odds_uniform(self):
        _assert_uniform(_market_only_engine().evaluate(_match_without_odds(), _context()))

    def test_odds_home_none_uniform(self):
        match = _match_with_odds()
        match["odds_home"] = None
        _assert_uniform(_market_only_engine().evaluate(match, _context()))

    def test_partial_odds_set_uniform(self):
        match = _match_with_odds()
        del match["odds_away"]
        _assert_uniform(_market_only_engine().evaluate(match, _context()))


# ── 4. malformed odds ────────────────────────────────────────────────────


class TestMalformedOdds:
    @pytest.mark.parametrize("bad", ["2.0", 0, -1, float("nan")])
    def test_non_positive_or_non_numeric_odds_uniform(self, bad):
        match = _match_with_odds()
        match["odds_home"] = bad
        _assert_uniform(_market_only_engine().evaluate(match, _context()))

    def test_inf_odds_passes_gate_and_computes_non_uniform(self):
        # Reality check: float('inf') is a float and inf > 0, so it passes the
        # MarketOddsSignal gate; remove_vig treats 1/inf as 0.0 and returns a
        # valid (if degenerate) non-uniform output. Assert that actual behavior
        # rather than assuming it falls back to uniform.
        match = _match_with_odds()
        match["odds_home"] = float("inf")
        bp = _market_only_engine().evaluate(match, _context())
        assert (bp.home_prob, bp.draw_prob, bp.away_prob) != pytest.approx(UNIFORM, abs=1e-9)
        rv = remove_vig(float("inf"), 3.5, 4.0)
        assert bp.home_prob == round(rv["home"], 6)
        assert bp.draw_prob == round(rv["draw"], 6)


# ── 5. determinism ───────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_match_evaluated_twice_identical(self):
        engine = _market_only_engine()
        match, ctx = _match_with_odds(), _context()
        a, b = engine.evaluate(match, ctx), engine.evaluate(match, ctx)
        assert (a.home_prob, a.draw_prob, a.away_prob) == (b.home_prob, b.draw_prob, b.away_prob)

    def test_two_fresh_engines_identical(self):
        a = _market_only_engine().evaluate(_match_with_odds(), _context())
        b = _market_only_engine().evaluate(_match_with_odds(), _context())
        assert (a.home_prob, a.draw_prob, a.away_prob) == (b.home_prob, b.draw_prob, b.away_prob)


# ── 6. strategy isolation ────────────────────────────────────────────────


class TestStrategyIsolation:
    def test_pipeline_matches_strategy_engine(self):
        match, ctx = _match_with_odds(), _context()
        via_pipeline = build_signal_engine({}, strategy="market_only").evaluate(match, ctx)
        via_selector = build_strategy_engine("market_only", elo_ratings={}).evaluate(match, ctx)
        assert (via_pipeline.home_prob, via_pipeline.draw_prob, via_pipeline.away_prob) == (
            via_selector.home_prob, via_selector.draw_prob, via_selector.away_prob,
        )
        assert via_pipeline.signal_breakdown == via_selector.signal_breakdown

    def test_missing_odds_produces_no_other_signals(self):
        bp = _market_only_engine().evaluate(_match_without_odds(), _context())
        assert list(bp.signal_breakdown) == ["market_odds"]
        assert bp.signal_breakdown["market_odds"]["weight"] == 1.0
        assert bp.weights_applied == {"market_odds": 1.0}


# ── 7. production unchanged ──────────────────────────────────────────────


class TestProductionUnchanged:
    def test_default_strategy_registers_five_signals(self):
        engine = build_signal_engine({})
        assert set(_registered(engine)) == {
            "market_odds", "refined_elo", "rolling_form", "rest_days", "squad_value",
        }

    def test_default_weights_loaded_from_config(self):
        engine = build_signal_engine({})
        for name in ("rolling_form", "rest_days", "squad_value", "market_odds", "refined_elo"):
            assert engine.weights.get(name, 0) > 0
        assert sum(engine.weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_explicit_production_strategy_unchanged(self):
        engine = build_signal_engine({}, strategy="production")
        assert set(_registered(engine)) == {
            "market_odds", "refined_elo", "rolling_form", "rest_days", "squad_value",
        }


# ── 8. unknown strategy ──────────────────────────────────────────────────


class TestUnknownStrategy:
    @pytest.mark.parametrize("bad", ["bogus", ""])
    def test_build_strategy_engine_raises(self, bad):
        with pytest.raises(ValueError) as exc:
            build_strategy_engine(bad)
        assert "market_only" in str(exc.value)
        assert bad in str(exc.value)

    def test_build_signal_engine_raises(self):
        with pytest.raises(ValueError) as exc:
            build_signal_engine({}, strategy="bogus")
        assert "market_only" in str(exc.value)


# ── 9. simulation wiring ─────────────────────────────────────────────────


class TestSimulationWiring:
    def test_run_mc_simulation_market_only(self):
        teams = ["A", "B", "C", "D"]
        fixtures = [
            {"match_id": f"m{i}", "team_a": t1, "team_b": t2, "matchday": 1,
             "status": "scheduled"}
            for i, (t1, t2) in enumerate(
                [("A", "B"), ("C", "D"), ("A", "C"), ("B", "D"), ("A", "D"), ("B", "C")]
            )
        ]
        elo = {t: 1500.0 + i for i, t in enumerate(teams)}
        out = run_mc_simulation(
            "ignored", n_iterations=50, seed=1, elo_ratings_override=elo,
            played_map={}, playable_fixtures=fixtures, team_names=teams,
            strategy="market_only",
        )
        assert out["mode"] == "simulation"
        assert out["n_iterations"] == 50
        assert out["signals"] == {
            "market_odds": {
                "n_matches": 6, "available": 6, "available_pct": 100.0,
                "avg_probability": 0.3333, "weight": 1.0,
            }
        }