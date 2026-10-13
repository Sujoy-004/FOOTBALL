"""Tests for evaluation.py metrics — extracted from WC test_evaluation.py."""

import math

import numpy as np
import pytest
from football_core.evaluation import (
    brier_score, log_loss, compute_metrics,
    calibration_curve, expected_calibration_error,
    trps, tournament_trps, validate_tournament_matrix,
    multi_class_log_loss, multi_class_brier, multi_class_ece,
    ranked_probability_score, ordered_brier,
    classwise_ece, calibration_slope_intercept,
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

    def test_empty_returns_none_metrics(self):
        """Empty input yields None metrics, never a fabricated perfect 0.0."""
        result = compute_metrics([], [])
        assert result["brier"] is None
        assert result["log_loss"] is None
        assert result["accuracy"] is None
        assert result["n"] == 0

    def test_length_mismatch_returns_none_metrics(self):
        """Length-mismatched input yields None metrics, not a computed value."""
        result = compute_metrics([0.8, 0.3], [1.0])
        assert result["brier"] is None
        assert result["log_loss"] is None
        assert result["accuracy"] is None
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


class TestRankedProbabilityScore:
    """Tests for the match-level ranked probability score (D-13)."""

    def test_perfect_prediction(self):
        """One-hot prediction at the actual outcome scores 0.0."""
        assert ranked_probability_score([1.0, 0.0, 0.0], 0) == 0.0
        assert ranked_probability_score([0.0, 1.0, 0.0], 1) == 0.0
        assert ranked_probability_score([0.0, 0.0, 1.0], 2) == 0.0

    def test_fully_wrong_one_hot(self):
        """One-hot prediction at a wrong outcome scores 1.0."""
        assert ranked_probability_score([0.0, 0.0, 1.0], 0) == 1.0
        assert ranked_probability_score([1.0, 0.0, 0.0], 2) == 1.0

    def test_uniform_mid(self):
        """Uniform prediction vs away win: (1/9 + 4/9) / 2 = 5/18."""
        assert ranked_probability_score([1 / 3, 1 / 3, 1 / 3], 2) == pytest.approx(5 / 18)

    def test_ordered_brier_is_half_rps(self):
        """ordered_brier == ranked_probability_score(...) / 2 for K=3."""
        probs = [0.6, 0.3, 0.1]
        assert ordered_brier(probs, 0) == pytest.approx(
            ranked_probability_score(probs, 0) / 2
        )

    def test_tournament_trps_is_trps(self):
        """tournament_trps is the same object as trps (D-13 alias)."""
        assert tournament_trps is trps

    def test_raises_on_wrong_length(self):
        """Non-3 probability vector raises ValueError."""
        with pytest.raises(ValueError):
            ranked_probability_score([0.5, 0.5], 0)

    def test_raises_on_bad_sum(self):
        """Probabilities not summing to ~1.0 raise ValueError."""
        with pytest.raises(ValueError):
            ranked_probability_score([0.5, 0.2, 0.1], 0)

    def test_raises_on_bad_index(self):
        """actual_index outside [0, 2] raises ValueError."""
        with pytest.raises(ValueError):
            ranked_probability_score([0.2, 0.5, 0.3], 5)


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

    def test_empty_raises(self):
        """Empty input raises ValueError, never returns a perfect 0.0."""
        with pytest.raises(ValueError):
            multi_class_log_loss([], [])

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

    def test_empty_raises(self):
        """Empty input raises ValueError, never returns a perfect 0.0."""
        with pytest.raises(ValueError):
            multi_class_brier([], [])


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

    def test_empty_raises(self):
        """Empty input raises ValueError, never returns a perfect 0.0."""
        with pytest.raises(ValueError):
            multi_class_ece([], [])

    def test_single_bin_with_few_samples(self):
        """Small sample triggers adaptive binning, never errors."""
        probs = [[0.6, 0.2, 0.2], [0.5, 0.3, 0.2]]
        actuals = [0, 1]
        ece = multi_class_ece(probs, actuals)
        assert 0.0 <= ece <= 1.0

    def test_ece_tracks_bin_accuracy_given_fixed_confidence(self):
        """ECE must depend on actual bin accuracy, not just confidence.

        Same 0.75 confidence in every trial; only the hit rate changes.
        A well-calibrated model (accuracy == confidence == 0.75) scores 0
        even though it is wrong 25% of the time; a half-accurate model
        scores the full |confidence - accuracy| gap.
        """
        probs = [[0.75, 0.125, 0.125]] * 100

        well_calibrated = [0] * 75 + [2] * 25  # accuracy 0.75 == confidence
        half_accurate = [0] * 50 + [2] * 50    # accuracy 0.50 <  confidence

        ece_calibrated = multi_class_ece(probs, well_calibrated)
        ece_half = multi_class_ece(probs, half_accurate)

        # confidence == accuracy in every bin -> no calibration error
        assert ece_calibrated == pytest.approx(0.0, abs=1e-6)
        # accuracy gap is what matters: |0.75 - 0.50| = 0.25
        assert ece_half == pytest.approx(0.25, abs=1e-6)
        # regression guard: the old implementation always returned
        # 1 - mean_confidence = 0.25 regardless of accuracy, so it would
        # have returned the SAME value for the calibrated input.
        assert ece_calibrated != pytest.approx(0.25, abs=1e-6)

    def test_ece_hand_computed_two_bin_formula(self):
        """ECE equals the weighted mean of |mean_confidence - accuracy|.

        50 trials at confidence 0.90 with 60% accuracy and 50 trials at
        confidence 0.55 with 80% accuracy:
            ECE = .5*|.90-.60| + .5*|.55-.80| = .15 + .125 = .275
        """
        probs = [[0.9, 0.05, 0.05]] * 50 + [[0.55, 0.225, 0.225]] * 50
        actuals = [0] * 30 + [2] * 20 + [0] * 40 + [1] * 10
        ece = multi_class_ece(probs, actuals)
        assert ece == pytest.approx(0.275, abs=1e-6)

    def test_ece_uses_confidence_not_class_guessing(self):
        """n >= 100 keeps the requested 10-bin grid; empty bins are skipped."""
        n = 100
        probs = [[0.4, 0.4, 0.2]] * n   # confidence 0.4 with a tie in argmax
        actuals = [0] * (n // 2) + [2] * (n - n // 2)  # argmax=0, hit rate 0.5
        ece = multi_class_ece(probs, actuals)
        assert ece == pytest.approx(abs(0.4 - 0.5), abs=1e-6)


class TestClasswiseECE:
    """Tests for per-class expected calibration error (D-10 / D-11)."""

    @staticmethod
    def _dirichlet_population(n: int, seed: int = 1234) -> tuple[list[list[float]], list[int]]:
        """Well-calibrated population: Dirichlet probs, actuals drawn from them."""
        rng = np.random.default_rng(seed)
        probs = rng.dirichlet([1.0, 1.0, 1.0], size=n)
        u = rng.random(n)
        actuals = (u[:, None] < np.cumsum(probs, axis=1)).argmax(axis=1)
        return probs.tolist(), actuals.tolist()

    def test_well_calibrated_all_classes_near_zero(self):
        """A calibrated population yields ECE ~ 0 for every class."""
        probs, actuals = self._dirichlet_population(10_000)
        result = classwise_ece(probs, actuals)
        assert result["withheld"] == []
        for cls in ("home", "draw", "away"):
            assert result[cls] is not None
            assert result[cls] == pytest.approx(0.0, abs=0.05)
        assert result["macro"] == pytest.approx(0.0, abs=0.05)

    def test_per_class_miscalibration_moves_only_that_class(self):
        """Shifting only the home predictions inflates only the home ECE."""
        probs, actuals = self._dirichlet_population(10_000)
        result = classwise_ece(probs, actuals)

        shifted = [
            [min(p[0] + 0.35, 1.0), p[1], p[2]]
            for p in probs
        ]
        shifted_result = classwise_ece(shifted, actuals)

        assert shifted_result["home"] is not None
        assert shifted_result["home"] > 0.15
        # draw and away untouched -> identical to the calibrated run
        assert shifted_result["draw"] == result["draw"]
        assert shifted_result["away"] == result["away"]
        assert shifted_result["macro"] is not None

    def test_small_n_withholds_all_classes(self):
        """n < 20 per class cannot satisfy observations/bin >= 20 -> withheld."""
        probs, actuals = self._dirichlet_population(15)
        result = classwise_ece(probs, actuals)
        assert result["home"] is None
        assert result["draw"] is None
        assert result["away"] is None
        assert result["macro"] is None
        assert result["withheld"] == ["home", "draw", "away"]

    def test_concentrated_single_bin_retained(self):
        """All predictions in one bin with n >= 20 -> retained, ECE computable."""
        n = 200
        probs = [[0.5, 0.3, 0.2]] * n
        actuals = [0] * 100 + [1] * 60 + [2] * 40
        result = classwise_ece(probs, actuals)
        assert result["withheld"] == []
        # home: p=0.5, actual rate = 100/200 = 0.5 -> ECE 0.0
        assert result["home"] == pytest.approx(0.0, abs=1e-6)
        # draw: p=0.3, actual rate = 60/200 = 0.3 -> ECE 0.0
        assert result["draw"] == pytest.approx(0.0, abs=1e-6)
        # away: p=0.2, actual rate = 40/200 = 0.2 -> ECE 0.0
        assert result["away"] == pytest.approx(0.0, abs=1e-6)

    def test_empty_raises(self):
        """Empty input raises ValueError."""
        with pytest.raises(ValueError):
            classwise_ece([], [])

    def test_length_mismatch_raises(self):
        """Mismatched actuals length raises ValueError."""
        with pytest.raises(ValueError):
            classwise_ece([[0.5, 0.3, 0.2]], [])


class TestCalibrationSlopeIntercept:
    """Tests for the read-only calibration slope/intercept fit (D-12)."""

    @staticmethod
    def _synthetic(n: int, slope: float, intercept: float, seed: int = 99) -> tuple[list[float], list[int]]:
        """Binary outcomes drawn from sigmoid(intercept + slope * logit(p))."""
        rng = np.random.default_rng(seed)
        p = rng.uniform(0.05, 0.95, size=n)
        z = intercept + slope * np.log(p / (1.0 - p))
        q = 1.0 / (1.0 + np.exp(-z))
        y = (rng.uniform(size=n) < q).astype(int)
        return p.tolist(), y.tolist()

    def test_recovers_known_linear_logit(self):
        """A known synthetic logit is recovered within tolerance."""
        predicted, actual = self._synthetic(10_000, slope=1.4, intercept=0.3)
        result = calibration_slope_intercept(predicted, actual)
        assert result["n"] == 10_000
        assert result["slope"] == pytest.approx(1.4, abs=0.05)
        assert result["intercept"] == pytest.approx(0.3, abs=0.05)

    def test_recovers_identity_calibration(self):
        """Slope 1 / intercept 0 (perfect calibration) is recovered."""
        predicted, actual = self._synthetic(10_000, slope=1.0, intercept=0.0, seed=7)
        result = calibration_slope_intercept(predicted, actual)
        assert result["slope"] == pytest.approx(1.0, abs=0.05)
        assert result["intercept"] == pytest.approx(0.0, abs=0.05)

    def test_empty_raises(self):
        """Empty input raises ValueError."""
        with pytest.raises(ValueError):
            calibration_slope_intercept([], [])

    def test_length_mismatch_raises(self):
        """Mismatched actual length raises ValueError."""
        with pytest.raises(ValueError):
            calibration_slope_intercept([0.5], [])

    def test_inputs_not_mutated(self):
        """Read-only contract: the passed lists are unchanged after the call."""
        predicted = [0.1, 0.4, 0.7, 0.9, 0.33, 0.66]
        actual = [0, 1, 1, 1, 0, 1]
        calibration_slope_intercept(predicted, actual)
        assert predicted == [0.1, 0.4, 0.7, 0.9, 0.33, 0.66]
        assert actual == [0, 1, 1, 1, 0, 1]
