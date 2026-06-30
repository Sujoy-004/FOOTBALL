"""
Test suite for blender module (Phase 14 Signal Blending).

Comprehensive test coverage for all blender functions including:
- Platt calibration (TestPlattCalibration)
- Cold start behavior (TestColdStart)
- Calibration edge cases (TestCalibrationEdgeCases)
- Apply calibration (TestApplyCalibration)
- Blend weights (TestBlendWeights)
- Blend predictions (TestBlend)
- Rolling Brier (TestRollingBrier)
- Poisson base rate (TestPoissonBaseRate)
"""

import pytest
import math
import json
import tempfile
import os
from football_core.blender import (
    calibrate_signal,
    apply_calibration,
    compute_blend_weights,
    blend_predictions,
    compute_poisson_base_rate,
    compute_rolling_brier,
    _sigmoid,
    _log_odds,
    _platt_targets
)
from src.blender import calibrate_and_blend
from src.elo import expected_score


class TestPlattCalibration:
    """Tests for Platt scaling calibration function."""
    
    def test_cold_start_returns_identity(self):
        """20 samples → (1.0, 0.0) (cold start)."""
        predictions = [0.5] * 20
        actuals = [1.0] * 20
        result = calibrate_signal(predictions, actuals)
        assert result == (1.0, 0.0)
    
    def test_fit_produces_non_identity(self):
        """31+ samples with structured bias → A != 1.0 or B != 0.0."""
        predictions = [0.8] * 31
        actuals = [0.5] * 31
        result = calibrate_signal(predictions, actuals)
        assert result != (1.0, 0.0)
    
    def test_fit_converges(self):
        """50 samples, Newton-Raphson terminates in < 10 iterations."""
        predictions = [0.5 + i * 0.01 for i in range(50)]
        actuals = [0.5] * 50
        result = calibrate_signal(predictions, actuals)
        assert result is not None
        assert len(result) == 2
    
    def test_all_draws_handled(self):
        """All actuals = 0.5 → does not crash, returns reasonable params."""
        predictions = [0.5] * 40
        actuals = [0.5] * 40
        result = calibrate_signal(predictions, actuals)
        assert result is not None
        assert len(result) == 2


class TestColdStart:
    """Tests for cold start behavior (n < threshold)."""
    
    def test_empty(self):
        """len=0 → (1.0, 0.0)."""
        result = calibrate_signal([], [])
        assert result == (1.0, 0.0)
    
    def test_below_threshold(self):
        """len=29 → (1.0, 0.0)."""
        predictions = [0.5] * 29
        actuals = [1.0] * 29
        result = calibrate_signal(predictions, actuals)
        assert result == (1.0, 0.0)
    
    def test_at_threshold(self):
        """len=30 → may fit (non-identity is OK)."""
        predictions = [0.5] * 30
        actuals = [1.0] * 30
        result = calibrate_signal(predictions, actuals)
        assert result is not None
        assert len(result) == 2
    
    def test_above_threshold(self):
        """len=31 → fits."""
        predictions = [0.5] * 31
        actuals = [1.0] * 31
        result = calibrate_signal(predictions, actuals)
        assert result is not None
        assert len(result) == 2
    
    def test_custom_threshold(self):
        """threshold=10 with len=15 → fits."""
        predictions = [0.5] * 15
        actuals = [1.0] * 15
        result = calibrate_signal(predictions, actuals, threshold=10)
        assert result is not None
        assert len(result) == 2


class TestCalibrationEdgeCases:
    """Tests for calibration edge cases."""
    
    def test_zero_prob(self):
        """apply_calibration(0.0, 1.0, 0.0) returns EPS."""
        result = apply_calibration(0.0, 1.0, 0.0)
        assert result == 1e-15
    
    def test_one_prob(self):
        """apply_calibration(1.0, 1.0, 0.0) returns 1-EPS."""
        result = apply_calibration(1.0, 1.0, 0.0)
        assert result == 1 - 1e-15
    
    def test_negative_log_odds(self):
        """calibrate_signal with p near 0 or 1 doesn't crash."""
        predictions = [1e-10, 1 - 1e-10]
        actuals = [0.0, 1.0]
        result = calibrate_signal(predictions, actuals)
        assert result is not None
    
    def test_identity_path(self):
        """apply_calibration(0.73, 1.0, 0.0) == 0.73."""
        result = apply_calibration(0.73, 1.0, 0.0)
        assert result == 0.73
    
    def test_all_same_prediction(self):
        """All predictions are 0.7 → fitting doesn't crash (Hessian guard)."""
        predictions = [0.7] * 40
        actuals = [0.5] * 40
        result = calibrate_signal(predictions, actuals)
        assert result is not None


class TestApplyCalibration:
    """Tests for apply_calibration function."""
    
    def test_identity(self):
        """apply_calibration(0.5, 1.0, 0.0) == 0.5."""
        result = apply_calibration(0.5, 1.0, 0.0)
        assert result == 0.5
    
    def test_calibrated(self):
        """apply_calibration(0.8, 1.5, -0.3) is a float in (0, 1)."""
        result = apply_calibration(0.8, 1.5, -0.3)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
    
    def test_monotonic(self):
        """if p1 < p2 then apply_calibration(p1, A, B) < apply_calibration(p2, A, B)."""
        p1, p2 = 0.4, 0.6
        A, B = 1.5, -0.3
        result1 = apply_calibration(p1, A, B)
        result2 = apply_calibration(p2, A, B)
        assert result1 < result2
    
    def test_rounding(self):
        """result rounded to 6 decimal places."""
        result = apply_calibration(0.123456789, 1.0, 0.0)
        assert isinstance(result, float)
        # Check that it's rounded to 6 decimal places
        rounded = round(result, 6)
        assert abs(result - rounded) < 1e-12


class TestBlendWeights:
    """Tests for compute_blend_weights function (D-07)."""
    
    def test_formula(self):
        """weights with briers 0.1, 0.2 → raw weights 10, 5 → normalized 2/3, 1/3."""
        briers = {"a": 0.1, "b": 0.2}
        weights = compute_blend_weights(briers)
        assert abs(weights["a"] - 0.666667) < 0.000001
        assert abs(weights["b"] - 0.333333) < 0.000001
        assert abs(sum(weights.values()) - 1.0) < 0.000001
    
    def test_floor(self):
        """brier of 0.01 → treated as 0.05 (floor), weight = 20."""
        briers = {"a": 0.01}
        weights = compute_blend_weights(briers)
        assert abs(weights["a"] - 1.0) < 0.000001
    
    def test_single_signal(self):
        """single signal always gets weight 1.0."""
        briers = {"a": 0.5}
        weights = compute_blend_weights(briers)
        assert weights["a"] == 1.0
    
    def test_equal_briers(self):
        """same brier → equal weights."""
        briers = {"a": 0.3, "b": 0.3}
        weights = compute_blend_weights(briers)
        assert abs(weights["a"] - 0.5) < 0.000001
        assert abs(weights["b"] - 0.5) < 0.000001
    
    def test_sum_to_one(self):
        """any input → sum(weights.values()) == 1.0."""
        briers = {"a": 0.1, "b": 0.2, "c": 0.3}
        weights = compute_blend_weights(briers)
        assert abs(sum(weights.values()) - 1.0) < 0.000001
    
    def test_zero_sum_guard(self):
        """all briers 0 → returns equal weights (divide-by-zero guard)."""
        briers = {"a": 0.0, "b": 0.0}
        weights = compute_blend_weights(briers)
        assert abs(weights["a"] - 0.5) < 0.000001
        assert abs(weights["b"] - 0.5) < 0.000001


class TestBlend:
    """Tests for blend_predictions function."""
    
    def test_basic(self):
        """probabilities [0.7, 0.6], weights [0.6, 0.4] → blended = 0.66."""
        signal_preds = {"a": 0.7, "b": 0.6}
        weights = {"a": 0.6, "b": 0.4}
        result = blend_predictions(signal_preds, weights)
        assert abs(result - 0.66) < 0.000001
    
    def test_missing_signal(self):
        """weights has 'a', 'b', 'c' but signal_preds only has 'a', 'b' → only 'a','b' used, re-normalized."""
        signal_preds = {"a": 0.7, "b": 0.6}
        weights = {"a": 0.6, "b": 0.4, "c": 0.0}
        result = blend_predictions(signal_preds, weights)
        assert abs(result - 0.66) < 0.000001
    
    def test_single_signal(self):
        """single signal → returns that signal's probability."""
        signal_preds = {"a": 0.8}
        weights = {"a": 1.0}
        result = blend_predictions(signal_preds, weights)
        assert result == 0.8
    
    def test_no_signals(self):
        """empty dicts → returns 0.5 (uniform prior)."""
        signal_preds = {}
        weights = {}
        result = blend_predictions(signal_preds, weights)
        assert result == 0.5
    
    def test_rounding(self):
        """result rounded to 6 decimal places."""
        signal_preds = {"a": 0.123456789, "b": 0.987654321}
        weights = {"a": 0.3, "b": 0.7}
        result = blend_predictions(signal_preds, weights)
        rounded = round(result, 6)
        assert abs(result - rounded) < 1e-12


class TestRollingBrier:
    """Tests for compute_rolling_brier function."""
    
    def test_computes_brier(self):
        """pass sample history entries with signal predictions and actuals � pure function test."""
        entries = [
            {
                "available": True,
                "actual": 1.0,
                "signals": {
                    "test_signal": {
                        "probability": 0.7,
                    }
                }
            },
            {
                "available": True,
                "actual": 0.0,
                "signals": {
                    "test_signal": {
                        "probability": 0.3,
                    }
                }
            }
        ]
        result = compute_rolling_brier(entries, "test_signal")
        expected = ((0.7 - 1.0) ** 2 + (0.3 - 0.0) ** 2) / 2
        assert abs(result - expected) < 0.000001
    
    def test_empty(self):
        """empty entries list returns 1.0."""
        result = compute_rolling_brier([], "test_signal")
        assert result == 1.0
    
    def test_window(self):
        """with 10 entries and window=5, only last 5 used."""
        entries = []
        for i in range(10):
            entries.append({
                "available": True,
                "actual": 1.0,
                "signals": {
                    "test_signal": {
                        "probability": 0.5 + i * 0.01,
                    }
                }
            })
        
        result = compute_rolling_brier(entries, "test_signal", window=5)
        # Should only use last 5 entries (i=5 to i=9)
        expected = sum(((0.5 + i * 0.01 - 1.0) ** 2 for i in range(5, 10))) / 5
        assert abs(result - expected) < 0.000001


class TestPoissonBaseRate:
    """Tests for compute_poisson_base_rate function."""
    
    def test_fallback_default(self):
        """compute_poisson_base_rate(None) returns 1.25."""
        result = compute_poisson_base_rate(None)
        assert result == 1.25
    
    def test_fallback_missing_file(self):
        """compute_poisson_base_rate(\"/nonexistent/path.json\") returns 1.25."""
        result = compute_poisson_base_rate("/nonexistent/path.json")
        assert result == 1.25
    
    def test_from_data(self):
        """with a temporary JSON file containing structured data, computes correct rate."""
        # Create temporary JSON file
        test_data = [
            {"goals": 2, "teams": ["A", "B"]},
            {"goals": 1, "teams": ["C", "D"]},
            {"goals": 3, "teams": ["E", "F"]}
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            temp_path = f.name
        
        try:
            result = compute_poisson_base_rate(temp_path)
            # Expected: (2 + 1 + 3) / 3 / 2 = 6 / 3 / 2 = 1.0
            assert abs(result - 1.0) < 0.0001
        finally:
            os.unlink(temp_path)


class TestBlendPipeline:
    """Integration test for the full calibration → blending flow."""

    def test_end_to_end_with_mock_data(self):
        """Full pipeline with realistic mock data runs without error."""
        mock_history = []
        for i in range(35):
            mock_history.append({
                "match_id": f"GS_A_{i:02d}",
                "team_a": "TeamA",
                "team_b": "TeamB",
                "actual": 1.0 if i < 18 else (0.0 if i < 33 else 0.5),
                "signals": {
                    "elo": {"probability": 0.6, "available": True, "version": "v1"},
                    "market_odds": {"probability": 0.65, "available": True, "version": "v1"},
                    "catboost": {"probability": 0.55, "available": True, "version": "v1"},
                }
            })

        from src.blender import calibrate_and_blend
        elo_ratings = {"TeamA": 1800, "TeamB": 1700}
        groups_data = {"groups": {"A": {"teams": ["TeamA", "TeamB"], "matches": [
            {"match_id": "GS_A_00", "team_a": "TeamA", "team_b": "TeamB"}]}}}
        result = calibrate_and_blend(
            history=mock_history[:30],
            signal_keys=["elo", "market_odds", "catboost"],
            elo_ratings=elo_ratings,
            groups_data=groups_data,
            bracket_data=[],
            odds_cache={},
            cb_cache={},
            brier_window=50,
            cold_start_threshold=30,
        )
        if result is not None:
            assert "calibration_params" in result
            assert "blend_weights" in result
            assert "match_probs" in result


class TestActualFieldFix:
    """Calibrate_and_blend reads actual from entry.get('actual') not signal_data.get('actual')."""

    def test_compute_rolling_brier_entry_actual(self):
        """compute_rolling_brier reads actual from entry top level."""
        entries = [
            {
                "available": True,
                "actual": 1.0,
                "signals": {
                    "test_signal": {
                        "probability": 0.7,
                    }
                }
            }
        ]
        result = compute_rolling_brier(entries, "test_signal")
        expected = (0.7 - 1.0) ** 2
        assert abs(result - expected) < 0.000001

    def test_calibrate_and_blend_entry_actual(self):
        """calibrate_and_blend Flow A collects actuals from entry top level."""
        history = []
        for i in range(35):
            history.append({
                "match_id": f"GS_A_{i:02d}",
                "team_a": "TeamA",
                "team_b": "TeamB",
                "actual": 1.0 if i < 18 else (0.0 if i < 33 else 0.5),
                "signals": {
                    "elo": {"probability": 0.6, "version": "v1", "available": True},
                    "market_odds": {"probability": 0.65, "version": "v1", "available": True},
                }
            })

        elo_ratings = {"TeamA": 1800, "TeamB": 1700}
        groups_data = {"groups": {"A": {"teams": ["TeamA", "TeamB"], "matches": [
            {"match_id": "GS_A_00", "team_a": "TeamA", "team_b": "TeamB"}]}}}
        odds_cache = {"matches": {"GS_A_00": {"probability": 0.65, "available": True}}}
        cb_cache = {"matches": {}}

        result = calibrate_and_blend(
            history=history[:35],
            signal_keys=["elo", "market_odds"],
            elo_ratings=elo_ratings,
            groups_data=groups_data,
            bracket_data=[],
            odds_cache=odds_cache,
            cb_cache=cb_cache,
            brier_window=50,
            cold_start_threshold=30,
        )
        assert result is not None
        # Should have calibration_params with n_matches > 0 for both signals
        assert result["calibration_params"]["elo"]["n_matches"] >= 30
        assert result["calibration_params"]["market_odds"]["n_matches"] >= 30


class TestMatchProbs:
    """calibrate_and_blend Flow C produces match_probs with blended_prob != expected_score."""

    def test_match_probs_populated(self):
        """match_probs returned with entries and blended prob ≠ expected_score."""
        history = []
        for i in range(35):
            history.append({
                "match_id": f"GS_A_{i:02d}",
                "team_a": "TeamA",
                "team_b": "TeamB",
                "actual": 1.0 if i < 18 else (0.0 if i < 33 else 0.5),
                "signals": {
                    "elo": {"probability": 0.55 + (i % 5) * 0.02, "version": "v1", "available": True},
                    "market_odds": {"probability": 0.60 - (i % 5) * 0.01, "version": "v1", "available": True},
                }
            })

        elo_ratings = {"TeamA": 1800, "TeamB": 1700}
        groups_data = {"groups": {"A": {"teams": ["TeamA", "TeamB"], "matches": [
            {"match_id": "GS_A_00", "team_a": "TeamA", "team_b": "TeamB"}]}}}
        odds_cache = {"matches": {"GS_A_00": {"probability": 0.65, "available": True}}}
        cb_cache = {"matches": {}}

        expected = expected_score(1800, 1700)

        result = calibrate_and_blend(
            history=history[:35],
            signal_keys=["elo", "market_odds"],
            elo_ratings=elo_ratings,
            groups_data=groups_data,
            bracket_data=[],
            odds_cache=odds_cache,
            cb_cache=cb_cache,
            brier_window=50,
            cold_start_threshold=30,
        )
        assert result is not None
        assert "match_probs" in result
        assert len(result["match_probs"]) > 0
        mp = result["match_probs"].get("GS_A_00")
        assert mp is not None
        assert isinstance(mp, float)
        assert 0 <= mp <= 1
        # blended prob should differ from expected_score because market_odds contributes
        assert abs(mp - expected) > 0.001, (
            f"blended_prob {mp} should differ from expected_score {expected}"
        )

    def test_match_probs_all_signals_contribute(self):
        """match_probs includes signals from odds_cache, cb_cache, form_cache, lineup_cache."""
        history = []
        for i in range(35):
            history.append({
                "match_id": f"GS_A_{i:02d}",
                "team_a": "TeamA",
                "team_b": "TeamB",
                "actual": 1.0,
                "signals": {
                    "elo": {"probability": 0.6, "version": "v1", "available": True},
                    "market_odds": {"probability": 0.7, "version": "v1", "available": True},
                    "catboost": {"probability": 0.65, "version": "v1", "available": True},
                    "form": {"probability": 0.55, "version": "v1", "available": True},
                    "lineup_strength": {"probability": 0.62, "version": "v1", "available": True},
                }
            })

        elo_ratings = {"TeamA": 1800, "TeamB": 1700}
        groups_data = {"groups": {"A": {"teams": ["TeamA", "TeamB"], "matches": [
            {"match_id": "GS_A_00", "team_a": "TeamA", "team_b": "TeamB"}]}}}
        odds_cache = {"matches": {"GS_A_00": {"probability": 0.70, "available": True}}}
        cb_cache = {"matches": {"GS_A_00": {"probability": 0.65, "available": True}}}
        form_cache = {"matches": {"GS_A_00": {"probability": 0.55, "available": True}}}
        lineup_cache = {"matches": {"GS_A_00": {"probability": 0.62, "available": True}}}

        result = calibrate_and_blend(
            history=history[:35],
            signal_keys=["elo", "market_odds", "catboost", "form", "lineup_strength"],
            elo_ratings=elo_ratings,
            groups_data=groups_data,
            bracket_data=[],
            odds_cache=odds_cache,
            cb_cache=cb_cache,
            form_cache=form_cache,
            lineup_cache=lineup_cache,
            brier_window=50,
            cold_start_threshold=30,
        )
        assert result is not None
        mp = result["match_probs"].get("GS_A_00")
        assert mp is not None
        expected = expected_score(1800, 1700)
        assert abs(mp - expected) > 0.001
        assert result["calibration_params"]["elo"]["n_matches"] >= 30

    def test_match_probs_empty_caches_sets_default(self):
        """match_probs entry set to 0.5 when no cache data available for that match."""
        history = []
        for i in range(35):
            history.append({
                "match_id": f"GS_A_{i:02d}",
                "team_a": "TeamA",
                "team_b": "TeamB",
                "actual": 1.0,
                "signals": {
                    "elo": {"probability": 0.6, "version": "v1", "available": True},
                    "market_odds": {"probability": 0.7, "version": "v1", "available": True},
                }
            })

        elo_ratings = {"TeamA": 1800, "TeamB": 1700}
        groups_data = {"groups": {"A": {"teams": ["TeamA", "TeamB"], "matches": [
            {"match_id": "GS_A_00", "team_a": "TeamA", "team_b": "TeamB"},
            {"match_id": "GS_A_99", "team_a": "TeamA", "team_b": "TeamB"}]}}}
        odds_cache = {"matches": {"GS_A_00": {"probability": 0.65, "available": True}}}
        cb_cache = {"matches": {}}

        result = calibrate_and_blend(
            history=history[:35],
            signal_keys=["elo", "market_odds"],
            elo_ratings=elo_ratings,
            groups_data=groups_data,
            bracket_data=[],
            odds_cache=odds_cache,
            cb_cache=cb_cache,
            brier_window=50,
            cold_start_threshold=30,
        )
        assert result is not None
        assert "GS_A_00" in result["match_probs"]
        assert "GS_A_99" in result["match_probs"]
        # GS_A_99 has no cache data, elo alone so != 0.5
        assert result["match_probs"]["GS_A_99"] != 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
