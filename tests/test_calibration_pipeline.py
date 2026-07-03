"""Tests for temperature scaling calibration and Brent's method optimization.

Tests cover:
    - temperature_scale(): identity, flattening, sharpening, edge cases
    - _brent_minimize(): convergence on quadratics, abs functions
    - CalibrationPipeline: fit(), transform(), predict(), save(), load()
    - MatchOutcome: result property, outcome_index
    - multiclass_log_loss: positive loss for valid inputs
    - Import verification
"""

import json
import math
import os
import sys
import tempfile

import pytest

from football_core.blender import (
    CalibrationPipeline,
    _brent_minimize,
    multiclass_log_loss,
    temperature_scale,
)
from football_core.evaluation import MatchOutcome
from football_core.signal import BlendedPrediction


# ═══════════════════════════════════════════════════════════════════════════════
# ── MatchOutcome Tests ──────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestMatchOutcome:
    def test_home_win(self):
        o = MatchOutcome(2, 0)
        assert o.result == 1.0
        assert o.outcome_index == 0

    def test_away_win(self):
        o = MatchOutcome(0, 3)
        assert o.result == 0.0
        assert o.outcome_index == 2

    def test_draw(self):
        o = MatchOutcome(1, 1)
        assert o.result == 0.5
        assert o.outcome_index == 1

    def test_high_score_home_win(self):
        o = MatchOutcome(5, 3)
        assert o.result == 1.0
        assert o.outcome_index == 0

    def test_high_score_away_win(self):
        o = MatchOutcome(2, 4)
        assert o.result == 0.0
        assert o.outcome_index == 2


# ═══════════════════════════════════════════════════════════════════════════════
# ── Temperature Scale Tests ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemperatureScale:
    """Verify simplex temperature scaling: q_i = p_i^α / Σⱼ p_j^α, α = 1/T."""

    def make_pred(self, home=0.5, draw=0.3, away=0.2):
        return BlendedPrediction(home, draw, away, {"sig": {}}, {"sig": 1.0})

    def test_identity_temperature_one(self):
        """T=1.0 must return probabilities within 1e-10 of input."""
        pred = self.make_pred(0.7, 0.2, 0.1)
        result = temperature_scale(pred, 1.0)
        assert abs(result.home_prob - 0.7) < 1e-10
        assert abs(result.draw_prob - 0.2) < 1e-10
        assert abs(result.away_prob - 0.1) < 1e-10

    def test_output_sums_to_one(self):
        """Output probabilities must sum to 1.0 ± 1e-9."""
        pred = self.make_pred(0.6, 0.25, 0.15)
        for T in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 5.0, 10.0]:
            result = temperature_scale(pred, T)
            total = result.home_prob + result.draw_prob + result.away_prob
            assert abs(total - 1.0) < 1e-9, f"T={T}: sum={total}"

    def test_flatten_overconfident(self):
        """T>1 flattens distribution (reduces overconfidence)."""
        pred = self.make_pred(0.9, 0.05, 0.05)
        result = temperature_scale(pred, 2.0)
        # Extreme 0.9 should be pulled toward 1/3
        assert result.home_prob < 0.9, f"home_prob not flattened: {result.home_prob}"
        assert result.draw_prob > 0.05
        assert result.away_prob > 0.05
        # All classes should be closer to 1/3
        assert abs(result.home_prob - 1 / 3) < abs(0.9 - 1 / 3)

    def test_sharpen_near_uniform(self):
        """T<1 sharpens distribution (increases confidence)."""
        pred = self.make_pred(0.4, 0.35, 0.25)
        result = temperature_scale(pred, 0.5)  # α = 2.0
        # Most probable class should get more probability
        assert result.home_prob > 0.4, f"home not sharpened: {result.home_prob}"

    def test_large_t_near_uniform(self):
        """Very large T approaches uniform distribution."""
        pred = self.make_pred(0.9, 0.07, 0.03)
        result = temperature_scale(pred, 100.0)
        # Should be close to 1/3 for all
        assert abs(result.home_prob - 1 / 3) < 0.05
        assert abs(result.draw_prob - 1 / 3) < 0.05
        assert abs(result.away_prob - 1 / 3) < 0.05

    def test_infinity_t_is_uniform(self):
        """T=inf must give exactly uniform."""
        pred = self.make_pred(0.9, 0.05, 0.05)
        result = temperature_scale(pred, float('inf'))
        assert abs(result.home_prob - 1 / 3) < 1e-10
        assert abs(result.draw_prob - 1 / 3) < 1e-10
        assert abs(result.away_prob - 1 / 3) < 1e-10

    def test_negative_t_raises(self):
        """Negative T must raise ValueError."""
        pred = self.make_pred()
        with pytest.raises(ValueError, match="Temperature must be positive"):
            temperature_scale(pred, -1.0)

    def test_zero_t_raises(self):
        """Zero T must raise ValueError."""
        pred = self.make_pred()
        with pytest.raises(ValueError, match="Temperature must be positive"):
            temperature_scale(pred, 0.0)

    def test_zero_prob_inputs(self):
        """Zero probability inputs should not cause division-by-zero or NaN."""
        pred = self.make_pred(1.0, 0.0, 0.0)
        result = temperature_scale(pred, 2.0)
        assert math.isfinite(result.home_prob)
        assert math.isfinite(result.draw_prob)
        assert math.isfinite(result.away_prob)
        assert abs(result.home_prob + result.draw_prob + result.away_prob - 1.0) < 1e-10

    def test_preserves_signal_breakdown(self):
        """signal_breakdown and weights_applied must be preserved unchanged."""
        breakdown = {"sig1": {"home": 0.6, "draw": 0.25, "away": 0.15, "weight": 1.0}}
        weights = {"sig1": 1.0}
        pred = BlendedPrediction(0.6, 0.25, 0.15, breakdown, weights)
        result = temperature_scale(pred, 2.0)
        assert result.signal_breakdown == breakdown
        assert result.weights_applied == weights

    def test_multiple_class_ordering_preserved(self):
        """Simplex scaling must preserve class ordering (rankings unchanged)."""
        pred = self.make_pred(0.7, 0.2, 0.1)
        for T in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 5.0]:
            result = temperature_scale(pred, T)
            # Rankings: home > draw > away must be preserved
            assert result.home_prob >= result.draw_prob >= result.away_prob, \
                f"T={T}: ordering violated {result}"

    def test_very_small_t(self):
        """T very close to 0 (very sharp) should still work."""
        pred = self.make_pred(0.5, 0.3, 0.2)
        result = temperature_scale(pred, 0.2)  # α = 5.0
        assert math.isfinite(result.home_prob)
        assert result.home_prob >= 0.5  # Should be more extreme
        assert abs(result.home_prob + result.draw_prob + result.away_prob - 1.0) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# ── Brent's Method Tests ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrentMinimize:
    """Verify 1D minimization via Brent's method."""

    def test_simple_quadratic(self):
        """Minimize (x-2)^2 in [0, 5] → should find ~2.0."""
        result = _brent_minimize(lambda x: (x - 2) ** 2, 0, 5)
        assert abs(result - 2.0) < 1e-4

    def test_positive_quadratic(self):
        """Minimize (x-2.5)^2 in [0, 5] → should find ~2.5."""
        result = _brent_minimize(lambda x: (x - 2.5) ** 2, 0, 5)
        assert abs(result - 2.5) < 1e-4

    def test_negative_minimum(self):
        """Minimize (x+1)^2 in [-5, 5] → should find ~-1.0."""
        result = _brent_minimize(lambda x: (x + 1) ** 2, -5, 5)
        assert abs(result - (-1.0)) < 1e-4

    def test_x_squared(self):
        """Minimize x^2 in [-3, 3] → should find ~0.0."""
        result = _brent_minimize(lambda x: x ** 2, -3, 3)
        assert abs(result) < 1e-4

    def test_abs_function(self):
        """Minimize |x-1.5| in [0, 5] → should find ~1.5."""
        result = _brent_minimize(lambda x: abs(x - 1.5), 0, 5)
        assert abs(result - 1.5) < 1e-4

    def test_abs_at_zero(self):
        """Minimize |x| in [-2, 3] → should find ~0.0."""
        result = _brent_minimize(lambda x: abs(x), -2, 3)
        assert abs(result) < 1e-4

    def test_fourth_degree(self):
        """Minimize (x-3)^4 in [0, 6] → should find ~3.0."""
        result = _brent_minimize(lambda x: (x - 3) ** 4, 0, 6)
        assert abs(result - 3.0) < 1e-4

    def test_edge_bracket(self):
        """Minimize near left bracket edge."""
        result = _brent_minimize(lambda x: (x - 0.2) ** 2, 0.1, 10.0)
        assert abs(result - 0.2) < 1e-4

    def test_converges_within_max_iter(self):
        """Must not exceed max_iter evaluations."""
        eval_count = [0]

        def counted(x):
            eval_count[0] += 1
            return (x - 2) ** 2

        _brent_minimize(counted, 0, 5, max_iter=50)
        # 3 initial + evaluations per iteration
        assert eval_count[0] <= 55


# ═══════════════════════════════════════════════════════════════════════════════
# ── CalibrationPipeline Tests ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestCalibrationPipeline:
    """Verify CalibrationPipeline lifecycle."""

    def make_preds(self) -> tuple[list[BlendedPrediction], list[MatchOutcome]]:
        """Default test data with mixed correct/wrong predictions."""
        preds = [
            BlendedPrediction(0.5, 0.3, 0.2, {}, {}),
            BlendedPrediction(0.3, 0.4, 0.3, {}, {}),
            BlendedPrediction(0.2, 0.3, 0.5, {}, {}),
            BlendedPrediction(0.45, 0.35, 0.2, {}, {}),
            BlendedPrediction(0.2, 0.35, 0.45, {}, {}),
            BlendedPrediction(0.4, 0.35, 0.25, {}, {}),
            BlendedPrediction(0.35, 0.25, 0.4, {}, {}),
            BlendedPrediction(0.5, 0.3, 0.2, {}, {}),
            BlendedPrediction(0.3, 0.35, 0.35, {}, {}),
            BlendedPrediction(0.35, 0.35, 0.3, {}, {}),
        ]
        outcomes = [
            MatchOutcome(2, 0),
            MatchOutcome(1, 1),
            MatchOutcome(0, 2),
            MatchOutcome(1, 0),
            MatchOutcome(0, 1),
            MatchOutcome(3, 1),
            MatchOutcome(1, 2),
            MatchOutcome(1, 1),
            MatchOutcome(2, 0),
            MatchOutcome(0, 1),
        ]
        return preds, outcomes

    def test_fit_returns_float(self):
        """fit() must return a float in [min_alpha, max_alpha]."""
        pipe = CalibrationPipeline()
        preds, outcomes = self.make_preds()
        alpha = pipe.fit(preds, outcomes)
        assert isinstance(alpha, float)
        assert 0.1 <= alpha <= 10.0

    def test_fit_sets_attributes(self):
        """After fit(), alpha_, T_, log_loss_, log_loss_before_, n_samples_ set."""
        pipe = CalibrationPipeline()
        preds, outcomes = self.make_preds()
        pipe.fit(preds, outcomes)

        assert pipe.alpha_ is not None
        assert pipe.T_ is not None
        assert pipe.log_loss_ is not None
        assert pipe.log_loss_before_ is not None
        assert pipe.n_samples_ == len(preds)

    def test_transform_returns_list(self):
        """transform() must return list of calibrated predictions."""
        pipe = CalibrationPipeline()
        preds, outcomes = self.make_preds()
        pipe.fit(preds, outcomes)
        calibrated = pipe.transform(preds)
        assert len(calibrated) == len(preds)
        for c in calibrated:
            assert isinstance(c, BlendedPrediction)
            assert abs(c.home_prob + c.draw_prob + c.away_prob - 1.0) < 1e-10

    def test_predict_single(self):
        """predict() must calibrate a single prediction."""
        pipe = CalibrationPipeline()
        preds, outcomes = self.make_preds()
        pipe.fit(preds, outcomes)
        pred = BlendedPrediction(0.5, 0.3, 0.2, {}, {})
        calibrated = pipe.predict(pred)
        assert isinstance(calibrated, BlendedPrediction)
        assert abs(calibrated.home_prob + calibrated.draw_prob + calibrated.away_prob - 1.0) < 1e-10

    def test_save_creates_json(self):
        """save() must create valid JSON with alpha and T keys."""
        pipe = CalibrationPipeline()
        preds, outcomes = self.make_preds()
        pipe.fit(preds, outcomes)

        tmpfile = os.path.join(tempfile.gettempdir(), "test_cal_pipeline.json")
        try:
            pipe.save(tmpfile)
            with open(tmpfile) as f:
                data = json.load(f)
            assert "alpha" in data
            assert "T" in data
            assert "log_loss" in data
            assert "n_samples" in data
        finally:
            if os.path.exists(tmpfile):
                os.remove(tmpfile)

    def test_load_restores_alpha(self):
        """load() must restore same alpha within save precision."""
        pipe = CalibrationPipeline()
        preds, outcomes = self.make_preds()
        alpha = pipe.fit(preds, outcomes)

        tmpfile = os.path.join(tempfile.gettempdir(), "test_cal_pipeline.json")
        try:
            pipe.save(tmpfile)
            pipe2 = CalibrationPipeline()
            pipe2.load(tmpfile)
            assert abs(pipe2.alpha_ - alpha) < 1e-5
            assert abs(pipe2.T_ - pipe.T_) < 1e-5
        finally:
            if os.path.exists(tmpfile):
                os.remove(tmpfile)

    def test_load_legacy_t_key(self):
        """load() must handle files with only 'T' key (legacy format)."""
        tmpfile = os.path.join(tempfile.gettempdir(), "test_legacy_cal.json")
        try:
            with open(tmpfile, "w") as f:
                json.dump({"T": 2.0}, f)
            pipe = CalibrationPipeline()
            pipe.load(tmpfile)
            assert abs(pipe.T_ - 2.0) < 1e-10
            assert abs(pipe.alpha_ - 0.5) < 1e-10
        finally:
            if os.path.exists(tmpfile):
                os.remove(tmpfile)

    def test_load_missing_keys_raises(self):
        """load() must raise ValueError on missing keys."""
        tmpfile = os.path.join(tempfile.gettempdir(), "test_bad_cal.json")
        try:
            with open(tmpfile, "w") as f:
                json.dump({"foo": "bar"}, f)
            pipe = CalibrationPipeline()
            with pytest.raises(ValueError, match="must contain"):
                pipe.load(tmpfile)
        finally:
            if os.path.exists(tmpfile):
                os.remove(tmpfile)

    def test_transform_unfitted_raises(self):
        """transform() must raise RuntimeError before fit()."""
        pipe = CalibrationPipeline()
        with pytest.raises(RuntimeError, match="fit"):
            pipe.transform([BlendedPrediction(0.5, 0.3, 0.2, {}, {})])

    def test_predict_unfitted_raises(self):
        """predict() must raise RuntimeError before fit()."""
        pipe = CalibrationPipeline()
        with pytest.raises(RuntimeError, match="fit"):
            pipe.predict(BlendedPrediction(0.5, 0.3, 0.2, {}, {}))

    def test_save_unfitted_raises(self):
        """save() must raise RuntimeError before fit()."""
        pipe = CalibrationPipeline()
        with pytest.raises(RuntimeError, match="fit"):
            pipe.save("/tmp/nonexistent.json")

    def test_empty_data_raises(self):
        """fit() must raise ValueError on empty data."""
        pipe = CalibrationPipeline()
        with pytest.raises(ValueError, match="empty"):
            pipe.fit([], [])

    def test_mismatched_lengths_raises(self):
        """fit() must raise ValueError on mismatched data lengths."""
        pipe = CalibrationPipeline()
        pred = BlendedPrediction(0.5, 0.3, 0.2, {}, {})
        outcome = MatchOutcome(1, 0)
        with pytest.raises(ValueError, match="same length"):
            pipe.fit([pred, pred], [outcome])

    def test_overconfident_data_flattens(self):
        """Overconfident but wrong predictions should produce T > 1 (α < 1)."""
        preds = [
            BlendedPrediction(0.8, 0.1, 0.1, {}, {}),
            BlendedPrediction(0.1, 0.8, 0.1, {}, {}),
            BlendedPrediction(0.1, 0.1, 0.8, {}, {}),
            BlendedPrediction(0.7, 0.2, 0.1, {}, {}),
            BlendedPrediction(0.1, 0.2, 0.7, {}, {}),
        ]
        outcomes = [
            MatchOutcome(0, 2),  # away (not home!)
            MatchOutcome(2, 0),  # home (not draw!)
            MatchOutcome(1, 1),  # draw (not away!)
            MatchOutcome(1, 1),  # draw (not home!)
            MatchOutcome(1, 0),  # home (not away!)
        ]
        pipe = CalibrationPipeline()
        pipe.fit(preds, outcomes)
        assert pipe.T_ >= 1.0, f"Expected T >= 1 for overconfident data, got T={pipe.T_:.4f}"

    def test_init_bounds_validation(self):
        """Constructor validates min/max alpha bounds."""
        with pytest.raises(ValueError, match="min_alpha must be positive"):
            CalibrationPipeline(min_alpha=0)
        with pytest.raises(ValueError, match="max_alpha.*min_alpha"):
            CalibrationPipeline(min_alpha=5.0, max_alpha=1.0)

    def test_custom_bounds(self):
        """Custom alpha bounds should be respected."""
        pipe = CalibrationPipeline(min_alpha=0.5, max_alpha=5.0)
        assert pipe.min_alpha == 0.5
        assert pipe.max_alpha == 5.0


# ═══════════════════════════════════════════════════════════════════════════════
# ── Multiclass Log-Loss Tests ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestMulticlassLogLoss:
    def test_returns_positive_float(self):
        """multiclass_log_loss must return a positive float for valid inputs."""
        preds = [
            BlendedPrediction(0.5, 0.3, 0.2, {}, {}),
            BlendedPrediction(0.3, 0.4, 0.3, {}, {}),
        ]
        outcomes = [
            MatchOutcome(1, 0),
            MatchOutcome(0, 0),
        ]
        loss = multiclass_log_loss(preds, outcomes)
        assert isinstance(loss, float)
        assert loss > 0

    def test_empty_returns_zero(self):
        """Empty predictions must return 0.0."""
        assert multiclass_log_loss([], []) == 0.0

    def test_mismatched_lengths_raises(self):
        """Mismatched lengths must raise ValueError."""
        pred = BlendedPrediction(0.5, 0.3, 0.2, {}, {})
        outcome = MatchOutcome(1, 0)
        with pytest.raises(ValueError, match="same length"):
            multiclass_log_loss([pred], [outcome, outcome])

    def test_perfect_predictions_low_loss(self):
        """Perfect predictions should have very low log-loss."""
        preds = [
            BlendedPrediction(0.99, 0.005, 0.005, {}, {}),
            BlendedPrediction(0.005, 0.99, 0.005, {}, {}),
            BlendedPrediction(0.005, 0.005, 0.99, {}, {}),
        ]
        outcomes = [
            MatchOutcome(2, 0),  # home win
            MatchOutcome(0, 0),  # draw
            MatchOutcome(0, 2),  # away win
        ]
        loss = multiclass_log_loss(preds, outcomes)
        assert loss < 0.05  # -log(0.99) ≈ 0.01005

    def test_wrong_predictions_high_loss(self):
        """Wrong confident predictions should have high log-loss."""
        preds = [
            BlendedPrediction(0.99, 0.005, 0.005, {}, {}),
        ]
        outcomes = [
            MatchOutcome(0, 2),  # away win, not home!
        ]
        loss = multiclass_log_loss(preds, outcomes)
        assert loss > 4.0  # -log(0.005) ≈ 5.3


# ═══════════════════════════════════════════════════════════════════════════════
# ── Import Tests ────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestImports:
    """Verify all public API imports work."""

    def test_import_temperature_scale(self):
        from football_core.blender import temperature_scale
        assert callable(temperature_scale)

    def test_import_calibration_pipeline(self):
        from football_core.blender import CalibrationPipeline
        assert CalibrationPipeline is not None

    def test_import_brent_minimize(self):
        from football_core.blender import _brent_minimize
        assert callable(_brent_minimize)

    def test_import_match_outcome(self):
        from football_core.evaluation import MatchOutcome
        assert MatchOutcome is not None

    def test_import_multiclass_log_loss(self):
        from football_core.blender import multiclass_log_loss
        assert callable(multiclass_log_loss)
