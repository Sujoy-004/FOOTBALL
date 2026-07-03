"""Tests for evaluation.py metrics — extracted from WC test_evaluation.py."""

import math

import numpy as np
import pytest
from football_core.evaluation import (
    brier_score, log_loss, compute_metrics,
    calibration_curve, expected_calibration_error,
    trps, validate_tournament_matrix,
    multi_class_log_loss, multi_class_brier, multi_class_ece,
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


class TestTRPS:
    """Tests for Tournament Rank Probability Score (TRPS)."""

    def test_perfect_prediction(self):
        """Perfect prediction should yield TRPS ≈ 0.0."""
        R, T = 4, 4
        # Perfect: each team assigned probability 1.0 at its actual rank
        perfect_matrix = np.zeros((R, T))
        for t in range(T):
            perfect_matrix[t, t] = 1.0  # Team t predicted to finish at rank t+1
        actual_ranks = np.array([1, 2, 3, 4])
        score = trps(perfect_matrix, actual_ranks)
        assert score == pytest.approx(0.0, abs=1e-10)

    def test_imperfect_prediction(self):
        """Worst prediction (inverted ranks) should score significantly > 0."""
        R, T = 4, 4
        inverted_matrix = np.zeros((R, T))
        for t in range(T):
            inverted_matrix[R - 1 - t, t] = 1.0  # Predicted opposite rank
        actual_ranks = np.array([1, 2, 3, 4])
        score = trps(inverted_matrix, actual_ranks)
        assert score > 0.1

    def test_rank_weights_consistency(self):
        """Uniform weights via explicit ones should match default (None)."""
        R, T = 4, 3
        matrix = np.array([
            [0.5, 0.6, 0.1],
            [0.3, 0.2, 0.3],
            [0.1, 0.1, 0.3],
            [0.1, 0.1, 0.3],
        ])
        actual_ranks = np.array([1, 2, 3])
        default_score = trps(matrix, actual_ranks, rank_weights=None)
        explicit_score = trps(matrix, actual_ranks, rank_weights=np.ones(R - 1))
        assert default_score == pytest.approx(explicit_score, abs=1e-10)

    def test_rank_weights_effect(self):
        """Different rank weights should produce different scores."""
        R, T = 4, 3
        matrix = np.array([
            [0.5, 0.6, 0.1],
            [0.3, 0.2, 0.3],
            [0.1, 0.1, 0.3],
            [0.1, 0.1, 0.3],
        ])
        actual_ranks = np.array([1, 2, 3])
        uniform = trps(matrix, actual_ranks, np.ones(R - 1))
        champion_weighted = trps(matrix, actual_ranks, np.array([5.0, 1.0, 1.0]))
        assert champion_weighted != pytest.approx(uniform, abs=1e-10)

    def test_different_matrix_shapes(self):
        """TRPS works with different tournament sizes."""
        # 8-team tournament
        R, T = 8, 8
        matrix = np.eye(R) * 0.5 + np.ones((R, T)) * (0.5 / R)
        actual_ranks = np.array([1, 3, 2, 5, 4, 7, 6, 8])
        score = trps(matrix, actual_ranks)
        assert 0.0 <= score <= 1.0

    def test_larger_matrix(self):
        """TRPS scaled to a 36-team tournament (UCL size)."""
        R, T = 36, 36
        # Slightly informed predictions: diagonal bias
        rng = np.random.default_rng(42)
        matrix = rng.dirichlet(np.ones(R), T).T
        actual_ranks = np.arange(1, T + 1)
        score = trps(matrix, actual_ranks)
        assert 0.0 <= score <= 1.0


class TestValidateTournamentMatrix:
    """Tests for TRPS input validation."""

    def test_valid_matrix_passes(self):
        """Well-formed matrix should not raise."""
        matrix = np.eye(4)
        ranks = np.array([1, 2, 3, 4])
        # Should not raise
        validate_tournament_matrix(matrix, ranks)

    def test_raises_on_1d_matrix(self):
        """1D matrix should raise ValueError."""
        matrix = np.array([0.25, 0.25, 0.25, 0.25])
        ranks = np.array([1])
        with pytest.raises(ValueError, match="2D"):
            validate_tournament_matrix(matrix, ranks)

    def test_raises_on_wrong_column_count(self):
        """Mismatched actual_ranks length should raise."""
        matrix = np.eye(4)
        ranks = np.array([1, 2, 3])  # Only 3 teams for 4-column matrix
        with pytest.raises(ValueError, match="length"):
            validate_tournament_matrix(matrix, ranks)

    def test_raises_on_bad_column_sums(self):
        """Columns not summing to 1.0 should raise."""
        matrix = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        ranks = np.array([1, 2, 3])
        with pytest.raises(ValueError, match="sum to 1.0"):
            validate_tournament_matrix(matrix, ranks)

    def test_raises_on_rank_range(self):
        """Ranks outside [1, R] should raise."""
        matrix = np.eye(4)
        ranks = np.array([1, 2, 3, 5])  # 5 > R=4
        with pytest.raises(ValueError, match="range"):
            validate_tournament_matrix(matrix, ranks)

    def test_raises_on_single_rank(self):
        """Less than 2 ranks should raise."""
        matrix = np.ones((1, 4))
        ranks = np.array([1, 1, 1, 1])
        with pytest.raises(ValueError, match="at least 2"):
            validate_tournament_matrix(matrix, ranks)


class TestMultiClassLogLoss:
    """Tests for multi-class log loss."""

    def test_perfect_prediction(self):
        """Perfect predictions yield log loss ≈ 0.0."""
        probs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        actuals = [0, 1, 2]
        loss = multi_class_log_loss(probs, actuals)
        assert loss == pytest.approx(0.0, abs=1e-10)

    def test_imperfect_prediction(self):
        """Wrong predictions yield positive log loss."""
        probs = [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
        actuals = [0, 2]
        loss = multi_class_log_loss(probs, actuals)
        assert loss > 0.0

    def test_empty_returns_zero(self):
        """Empty input returns 0.0."""
        assert multi_class_log_loss([], []) == 0.0

    def test_clamping_prevents_inf(self):
        """Zero probability is clamped to avoid infinite loss."""
        probs = [[0.0, 0.0, 1.0]]
        actuals = [0]  # Predicted 0 probability for actual class
        loss = multi_class_log_loss(probs, actuals)
        assert math.isfinite(loss)
        assert loss > 0


class TestMultiClassBrier:
    """Tests for multi-class Brier score."""

    def test_perfect_prediction(self):
        """Perfect predictions yield Brier ≈ 0.0."""
        probs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        actuals = [0, 1]
        score = multi_class_brier(probs, actuals)
        assert score == pytest.approx(0.0, abs=1e-10)

    def test_worst_prediction(self):
        """Completely wrong prediction yields score > 0."""
        probs = [[0.0, 1.0, 0.0]]  # Predicted draw
        actuals = [0]  # Actual home win
        score = multi_class_brier(probs, actuals)
        assert score == pytest.approx(2.0 / 3.0, abs=1e-10)

    def test_empty_returns_zero(self):
        """Empty input returns 0.0."""
        assert multi_class_brier([], []) == 0.0


class TestMultiClassECE:
    """Tests for multi-class Expected Calibration Error."""

    def test_perfect_calibration(self):
        """Perfectly calibrated predictions yield ECE ≈ 0.0."""
        probs = [[0.9, 0.05, 0.05], [0.8, 0.1, 0.1], [0.7, 0.2, 0.1]]
        actuals = [0, 0, 0]
        ece = multi_class_ece(probs, actuals, n_bins=5)
        assert 0.0 <= ece <= 1.0

    def test_miscalibrated(self):
        """Overconfident wrong predictions yield positive ECE."""
        probs = [[0.9, 0.05, 0.05], [0.85, 0.1, 0.05]]
        actuals = [1, 2]  # Wrong predictions with high confidence
        ece = multi_class_ece(probs, actuals, n_bins=5)
        assert ece > 0.0

    def test_returns_float_in_range(self):
        """ECE always returns a float between 0.0 and 1.0."""
        probs = [[0.6, 0.3, 0.1], [0.4, 0.4, 0.2], [0.3, 0.3, 0.4]]
        actuals = [0, 1, 2]
        ece = multi_class_ece(probs, actuals)
        assert isinstance(ece, float)
        assert 0.0 <= ece <= 1.0

    def test_empty_returns_zero(self):
        """Empty input returns 0.0."""
        assert multi_class_ece([], []) == 0.0

    def test_single_bin_with_few_samples(self):
        """Small sample triggers adaptive binning, never errors."""
        probs = [[0.6, 0.2, 0.2], [0.5, 0.3, 0.2]]
        actuals = [0, 1]
        ece = multi_class_ece(probs, actuals)
        assert 0.0 <= ece <= 1.0
