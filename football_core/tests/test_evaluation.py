"""Tests for evaluation.py metrics — extracted from WC test_evaluation.py."""

import math
import pytest
from football_core.evaluation import (
    brier_score, log_loss, compute_metrics,
    calibration_curve, expected_calibration_error,
)


class TestBrierScore:
    def test_perfect(self):
        assert brier_score(1.0, 1.0) == 0.0

    def test_worst(self):
        assert brier_score(0.0, 1.0) == 1.0

    def test_half(self):
        assert brier_score(0.5, 1.0) == 0.25

    def test_draw(self):
        assert brier_score(0.6, 0.5) == pytest.approx(0.01)

    def test_wrong_favorite(self):
        assert brier_score(0.8, 0.0) == pytest.approx(0.64)


class TestLogLoss:
    def test_perfect(self):
        assert log_loss(0.99, 1.0) == pytest.approx(0.01005, rel=0.01)

    def test_worst(self):
        assert log_loss(0.01, 1.0) == pytest.approx(4.605, rel=0.01)

    def test_clamping_no_inf(self):
        result = log_loss(0.0, 1.0)
        assert math.isfinite(result)
        assert result > 0

    def test_draw(self):
        result = log_loss(0.5, 0.5)
        assert result == pytest.approx(0.693, rel=0.01)

    def test_draw_extreme(self):
        result = log_loss(0.99, 0.5)
        assert result > 0
        assert math.isfinite(result)


class TestComputeMetrics:
    def test_empty(self):
        result = compute_metrics([], [])
        assert result["n"] == 0

    def test_all_perfect(self):
        result = compute_metrics([1.0, 1.0, 1.0], [1.0, 1.0, 1.0])
        assert result["brier"] == 0.0
        assert result["accuracy"] == 1.0

    def test_mixed(self):
        result = compute_metrics([0.8, 0.3], [1.0, 0.0])
        assert result["n"] == 2
        assert result["accuracy"] == 1.0

    def test_includes_draw(self):
        result = compute_metrics([0.6, 0.5], [1.0, 0.5])
        assert result["n"] == 2
        assert result["accuracy"] == 0.75


class TestCalibrationCurve:
    def test_perfect_calibration(self):
        preds = [0.0, 0.0, 1.0, 1.0]
        actuals = [0.0, 0.0, 1.0, 1.0]
        cal = calibration_curve(preds, actuals, n_bins=10)
        assert len(cal["bins"]) == 10
        assert cal["ece"] == pytest.approx(0.0, abs=0.001)

    def test_miscalibrated(self):
        preds = [0.9, 0.9, 0.1, 0.1]
        actuals = [0.0, 0.0, 1.0, 1.0]
        cal = calibration_curve(preds, actuals, n_bins=10)
        assert cal["ece"] > 0.0

    def test_single_bin(self):
        preds = [0.5, 0.5, 0.5]
        actuals = [1.0, 0.0, 0.5]
        cal = calibration_curve(preds, actuals, n_bins=1)
        assert cal["bins"][0]["count"] == 3

    def test_bin_boundary(self):
        preds = [0.0, 0.5, 1.0]
        actuals = [0.0, 0.5, 1.0]
        cal = calibration_curve(preds, actuals, n_bins=10)
        assert cal["bins"][0]["count"] == 1
        assert cal["bins"][5]["count"] == 1
        assert cal["bins"][9]["count"] == 1


class TestExpectedCalibrationError:
    def test_perfect(self):
        cal = {"bins": [
            {"count": 5, "mean_predicted": 0.2, "fraction_positives": 0.2},
            {"count": 5, "mean_predicted": 0.8, "fraction_positives": 0.8},
        ]}
        assert expected_calibration_error(cal) == 0.0

    def test_imperfect(self):
        cal = {"bins": [
            {"count": 5, "mean_predicted": 0.2, "fraction_positives": 0.3},
            {"count": 5, "mean_predicted": 0.8, "fraction_positives": 0.7},
        ]}
        assert expected_calibration_error(cal) == pytest.approx(0.1)

    def test_empty(self):
        assert expected_calibration_error({"bins": []}) == 0.0
