"""Tests for BlendedPrediction, EnsembleEngine, and compute_log_loss_weights."""

import dataclasses
import json
import math

import pytest

from football_core.signal import (
    BlendedPrediction,
    Signal,
    SignalOutput,
    PredictionContext,
    SignalRegistry,
)
from football_core.blender import EnsembleEngine, compute_log_loss_weights, compute_blend_weights


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_stub_signal(
    name: str,
    home: float = 0.4,
    draw: float = 0.3,
    away: float = 0.3,
) -> Signal:
    """Return a minimal Signal-conforming object with deterministic outputs."""
    _name = name
    _home = home
    _draw = draw
    _away = away

    class StubSignal:
        n = _name

        @property
        def name(self):
            return self.n

        def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
            return SignalOutput(_home, _draw, _away)

    return StubSignal()


# ── TestBlendedPrediction ────────────────────────────────────────────────────


class TestBlendedPrediction:
    """Verify BlendedPrediction dataclass fields and construction."""

    def test_fields_exist(self):
        fields = dataclasses.fields(BlendedPrediction)
        assert len(fields) == 5

    def test_field_names(self):
        names = [f.name for f in dataclasses.fields(BlendedPrediction)]
        assert names == [
            "home_prob",
            "draw_prob",
            "away_prob",
            "signal_breakdown",
            "weights_applied",
        ]

    def test_construction_and_values(self):
        bp = BlendedPrediction(
            home_prob=0.5,
            draw_prob=0.3,
            away_prob=0.2,
            signal_breakdown={"sig_a": {"home": 0.5, "draw": 0.3, "away": 0.2, "weight": 1.0}},
            weights_applied={"sig_a": 1.0},
        )
        assert bp.home_prob == 0.5
        assert bp.draw_prob == 0.3
        assert bp.away_prob == 0.2
        assert bp.signal_breakdown["sig_a"]["home"] == 0.5
        assert bp.weights_applied["sig_a"] == 1.0

    def test_breakdown_dict_structure(self):
        bp = BlendedPrediction(
            home_prob=0.6,
            draw_prob=0.25,
            away_prob=0.15,
            signal_breakdown={
                "sig_a": {"home": 0.6, "draw": 0.25, "away": 0.15, "weight": 0.7},
                "sig_b": {"home": 0.5, "draw": 0.3, "away": 0.2, "weight": 0.3},
            },
            weights_applied={"sig_a": 0.7, "sig_b": 0.3},
        )
        for name, entry in bp.signal_breakdown.items():
            assert "home" in entry
            assert "draw" in entry
            assert "away" in entry
            assert "weight" in entry
            assert isinstance(entry["home"], float)
            assert isinstance(entry["draw"], float)
            assert isinstance(entry["away"], float)
            assert isinstance(entry["weight"], float)

    def test_signal_breakdown_is_dict(self):
        bp = BlendedPrediction(0.5, 0.3, 0.2, {}, {})
        assert isinstance(bp.signal_breakdown, dict)
        assert isinstance(bp.weights_applied, dict)


# ── TestEnsembleEngine ──────────────────────────────────────────────────────


class TestEnsembleEngine:
    """Verify EnsembleEngine blending behavior."""

    def _make_default_context(self) -> PredictionContext:
        return PredictionContext(fixtures=[], elo_ratings={})

    def test_blends_three_signals(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        sig_c = _make_stub_signal("c", 0.4, 0.35, 0.25)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b, sig_c],
            weights={"a": 0.5, "b": 0.3, "c": 0.2},
        )
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)

        expected_h = 0.5 * 0.6 + 0.3 * 0.5 + 0.2 * 0.4
        expected_d = 0.5 * 0.25 + 0.3 * 0.3 + 0.2 * 0.35
        expected_a = 0.5 * 0.15 + 0.3 * 0.2 + 0.2 * 0.25
        total = expected_h + expected_d + expected_a
        expected_h /= total
        expected_d /= total
        expected_a /= total

        assert abs(result.home_prob - round(expected_h, 6)) < 1e-10
        assert abs(result.draw_prob - round(expected_d, 6)) < 1e-10
        assert abs(result.away_prob - round(expected_a, 6)) < 1e-10
        assert abs(result.home_prob + result.draw_prob + result.away_prob - 1.0) < 1e-10

    def test_missing_signal_renormalizes(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        sig_c = _make_stub_signal("c", 0.4, 0.35, 0.25)

        # Build registry with only a and b; engine has weights for a, b, c
        reg = SignalRegistry()
        reg.register(sig_a)
        reg.register(sig_b)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights={"a": 0.5, "b": 0.3, "c": 0.2},
        )
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)

        # Weight for 'c' is dropped; a and b renormalized: a=0.5/0.8=0.625, b=0.3/0.8=0.375
        w_a = 0.5 / 0.8
        w_b = 0.3 / 0.8
        expected_h = w_a * 0.6 + w_b * 0.5
        expected_d = w_a * 0.25 + w_b * 0.3
        expected_a = w_a * 0.15 + w_b * 0.2
        total = expected_h + expected_d + expected_a
        expected_h /= total
        expected_d /= total
        expected_a /= total

        assert abs(result.home_prob - round(expected_h, 6)) < 1e-10
        assert abs(result.draw_prob - round(expected_d, 6)) < 1e-10
        assert abs(result.away_prob - round(expected_a, 6)) < 1e-10

    def test_all_signals_fail_returns_uniform(self):
        engine = EnsembleEngine(signals=[], weights={})
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)
        assert abs(result.home_prob - 1 / 3) < 1e-10
        assert abs(result.draw_prob - 1 / 3) < 1e-10
        assert abs(result.away_prob - 1 / 3) < 1e-10
        assert result.signal_breakdown == {}
        assert result.weights_applied == {}

    def test_empty_registry_returns_uniform(self):
        engine = EnsembleEngine(signals=[])
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)
        assert abs(result.home_prob - 1 / 3) < 1e-10
        assert abs(result.draw_prob - 1 / 3) < 1e-10
        assert abs(result.away_prob - 1 / 3) < 1e-10

    def test_weights_not_in_signals_ignored(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        engine = EnsembleEngine(
            signals=[sig_a],
            weights={"a": 0.7, "nonexistent": 0.3},
        )
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)
        # Only 'a' has weight; nonexistent is ignored
        assert abs(result.home_prob - round(0.6, 6)) < 1e-10
        assert abs(result.draw_prob - round(0.25, 6)) < 1e-10
        assert abs(result.away_prob - round(0.15, 6)) < 1e-10

    def test_zero_weights_filtered(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights={"a": 0.7, "b": 0.0},
        )
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)
        # b has weight 0.0 → filtered, a gets weight 1.0
        assert abs(result.home_prob - round(0.6, 6)) < 1e-10
        assert abs(result.draw_prob - round(0.25, 6)) < 1e-10
        assert abs(result.away_prob - round(0.15, 6)) < 1e-10

    def test_negative_weights_filtered(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights={"a": 0.7, "b": -0.1},
        )
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)
        # b has negative weight → filtered from norm_weights in _blend
        assert abs(result.home_prob - round(0.6, 6)) < 1e-10
        assert abs(result.draw_prob - round(0.25, 6)) < 1e-10
        assert abs(result.away_prob - round(0.15, 6)) < 1e-10

    def test_three_outcome_independent_blend(self):
        """Verify all 3 outcomes are blended independently."""
        sig_a = _make_stub_signal("a", 0.7, 0.1, 0.2)
        sig_b = _make_stub_signal("b", 0.1, 0.7, 0.2)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights={"a": 0.5, "b": 0.5},
        )
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)

        # Each outcome is its own weighted average, then renormalized
        raw_h = 0.5 * 0.7 + 0.5 * 0.1
        raw_d = 0.5 * 0.1 + 0.5 * 0.7
        raw_a = 0.5 * 0.2 + 0.5 * 0.2
        tot = raw_h + raw_d + raw_a
        assert abs(result.home_prob - round(raw_h / tot, 6)) < 1e-10
        assert abs(result.draw_prob - round(raw_d / tot, 6)) < 1e-10
        assert abs(result.away_prob - round(raw_a / tot, 6)) < 1e-10
        assert abs(result.home_prob + result.draw_prob + result.away_prob - 1.0) < 1e-10

    def test_evaluate_returns_blended_prediction(self):
        sig = _make_stub_signal("sig", 0.5, 0.3, 0.2)
        engine = EnsembleEngine(signals=[sig])
        ctx = self._make_default_context()
        result = engine.evaluate({"match_id": "M1"}, ctx)
        assert isinstance(result, BlendedPrediction)

    def test_weights_property(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights={"a": 0.7, "b": 0.3},
        )
        w = engine.weights
        assert w == {"a": 0.7, "b": 0.3}

    def test_weights_property_isolation(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        engine = EnsembleEngine(
            signals=[sig_a],
            weights={"a": 1.0},
        )
        w = engine.weights
        w["a"] = 999.0
        assert engine.weights["a"] == 1.0


# ── TestComputeLogLossWeights ────────────────────────────────────────────────


class TestComputeLogLossWeights:
    """Verify compute_log_loss_weights delegates to compute_blend_weights correctly."""

    def test_basic_inverse(self):
        weights = compute_log_loss_weights({"a": 0.5, "b": 1.0})
        # w_a = (1/0.5) / (1/0.5 + 1/1.0) = 2/(2+1) = 2/3 ≈ 0.666667
        # w_b = 1/3 ≈ 0.333333
        assert abs(weights["a"] - round(2 / 3, 6)) < 1e-10
        assert abs(weights["b"] - round(1 / 3, 6)) < 1e-10

    def test_sums_to_one(self):
        weights = compute_log_loss_weights({"a": 0.3, "b": 0.6, "c": 1.2, "d": 0.8})
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-10

    def test_empty_dict(self):
        weights = compute_log_loss_weights({})
        assert weights == {}

    def test_single_signal(self):
        weights = compute_log_loss_weights({"a": 0.5})
        assert abs(weights["a"] - 1.0) < 1e-10

    def test_large_disparity(self):
        weights = compute_log_loss_weights({"a": 0.1, "b": 2.0})
        # w_a = (1/0.1) / (1/0.1 + 1/2.0) = 10 / (10 + 0.5) = 10/10.5 ≈ 0.952381
        expected_a = round(10.0 / 10.5, 6)
        expected_b = round(0.5 / 10.5, 6)
        assert abs(weights["a"] - expected_a) < 1e-10
        assert abs(weights["b"] - expected_b) < 1e-10

    def test_same_log_losses(self):
        weights = compute_log_loss_weights({"a": 0.5, "b": 0.5, "c": 0.5})
        uniform = round(1 / 3, 6)
        assert abs(weights["a"] - uniform) < 1e-10
        assert abs(weights["b"] - uniform) < 1e-10
        assert abs(weights["c"] - uniform) < 1e-10

    def test_delegates_to_compute_blend_weights(self):
        log_losses = {"a": 0.5, "b": 1.0}
        direct = compute_log_loss_weights(log_losses)
        delegated = compute_blend_weights(log_losses)
        assert direct == delegated


# ── TestWeightLoading ────────────────────────────────────────────────────────


class TestWeightLoading:
    """Verify weight loading from JSON config file."""

    def test_load_from_json(self, tmp_path):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        config = {"weights": {"a": 0.7, "b": 0.3}}
        config_path = tmp_path / "weights.json"
        with open(config_path, "w") as f:
            json.dump(config, f)

        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights_path=str(config_path),
        )
        assert engine.weights == {"a": 0.7, "b": 0.3}

    def test_load_from_json_missing_file(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        with pytest.raises(FileNotFoundError):
            EnsembleEngine(
                signals=[sig_a],
                weights_path="/nonexistent/path/weights.json",
            )

    def test_weights_takes_precedence(self, tmp_path):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        config = {"weights": {"a": 0.2}}
        config_path = tmp_path / "weights.json"
        with open(config_path, "w") as f:
            json.dump(config, f)

        engine = EnsembleEngine(
            signals=[sig_a],
            weights={"a": 0.9},
            weights_path=str(config_path),
        )
        # Direct weights dict takes precedence
        assert engine.weights == {"a": 0.9}

    def test_uniform_when_no_weights(self):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        engine = EnsembleEngine(signals=[sig_a, sig_b])
        assert engine.weights == {"a": 0.5, "b": 0.5}

    def test_uniform_when_no_weights_no_signals(self):
        engine = EnsembleEngine(signals=[])
        assert engine.weights == {}

    def test_load_from_json_with_zero_weights_filtered(self, tmp_path):
        """Zero weights in JSON config should be filtered during init."""
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        config = {"weights": {"a": 0.7, "b": 0.0}}
        config_path = tmp_path / "weights.json"
        with open(config_path, "w") as f:
            json.dump(config, f)

        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights_path=str(config_path),
        )
        # b with weight 0.0 is filtered out during __init__
        assert "b" not in engine.weights
        assert engine.weights == {"a": 0.7}


# ── TestEnsembleEngineEvaluateWithContext ────────────────────────────────────


class TestEnsembleEngineEvaluateWithContext:
    """Integration-style tests using sample_match_data / sample_prediction_context."""

    def test_evaluate_with_real_context(self, sample_match_data, sample_prediction_context):
        sig = _make_stub_signal("sig", 0.5, 0.3, 0.2)
        engine = EnsembleEngine(signals=[sig])
        result = engine.evaluate(sample_match_data, sample_prediction_context)
        assert isinstance(result, BlendedPrediction)
        assert abs(result.home_prob + result.draw_prob + result.away_prob - 1.0) < 1e-10

    def test_signal_breakdown_includes_all_signals(
        self, sample_match_data, sample_prediction_context
    ):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights={"a": 0.6, "b": 0.4},
        )
        result = engine.evaluate(sample_match_data, sample_prediction_context)
        assert "a" in result.signal_breakdown
        assert "b" in result.signal_breakdown
        assert "home" in result.signal_breakdown["a"]
        assert "weight" in result.signal_breakdown["a"]

    def test_probs_sum_to_one(self, sample_match_data, sample_prediction_context):
        sig_a = _make_stub_signal("a", 0.5, 0.3, 0.2)
        sig_b = _make_stub_signal("b", 0.4, 0.35, 0.25)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b],
            weights={"a": 0.5, "b": 0.5},
        )
        result = engine.evaluate(sample_match_data, sample_prediction_context)
        assert abs(result.home_prob + result.draw_prob + result.away_prob - 1.0) < 1e-10

    def test_weights_applied_reflects_renormalization(
        self, sample_match_data, sample_prediction_context
    ):
        sig_a = _make_stub_signal("a", 0.6, 0.25, 0.15)
        sig_b = _make_stub_signal("b", 0.5, 0.3, 0.2)
        sig_c = _make_stub_signal("c", 0.4, 0.35, 0.25)
        engine = EnsembleEngine(
            signals=[sig_a, sig_b, sig_c],
            weights={"a": 0.5, "b": 0.3, "c": 0.2},
        )
        result = engine.evaluate(sample_match_data, sample_prediction_context)
        # All signals active; weights should be normalized
        applied = result.weights_applied
        assert abs(sum(applied.values()) - 1.0) < 1e-10
        assert abs(applied["a"] - round(0.5, 6)) < 1e-10
        assert abs(applied["b"] - round(0.3, 6)) < 1e-10
        assert abs(applied["c"] - round(0.2, 6)) < 1e-10
