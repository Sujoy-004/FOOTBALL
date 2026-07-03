"""Shared accuracy metric primitives — extracted from WC evaluation.py."""

import math

import numpy as np


def brier_score(prediction: float, actual: float) -> float:
    return (prediction - actual) ** 2


def log_loss(prediction: float, actual: float, eps: float = 1e-15) -> float:
    p = max(eps, min(1 - eps, prediction))
    if actual == 0.5:
        return -0.5 * (math.log(p) + math.log(1 - p))
    return -(actual * math.log(p) + (1 - actual) * math.log(1 - p))


def compute_metrics(predictions: list[float], actuals: list[float]) -> dict:
    if not predictions or len(predictions) != len(actuals):
        return {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0}
    n = len(predictions)
    brier_sum = ll_sum = 0.0
    correct = 0.0
    for p, a in zip(predictions, actuals):
        brier_sum += brier_score(p, a)
        ll_sum += log_loss(p, a)
        if a == 0.5:
            correct += 0.5
        elif (p >= 0.5 and a == 1.0) or (p < 0.5 and a == 0.0):
            correct += 1
    return {"brier": brier_sum / n, "log_loss": ll_sum / n, "accuracy": correct / n, "n": n}


def calibration_curve(predictions: list[float], actuals: list[float], n_bins: int = 10) -> dict:
    bins = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        bin_preds, bin_actuals = [], []
        for p, a in zip(predictions, actuals):
            if lo <= p < hi or (i == n_bins - 1 and p == 1.0):
                bin_preds.append(p)
                bin_actuals.append(a)
        if bin_preds:
            mean_pred = sum(bin_preds) / len(bin_preds)
            frac_pos = sum(a for a in bin_actuals) / len(bin_actuals)
            bins.append({"bin_start": round(lo, 2), "bin_end": round(hi, 2), "count": len(bin_preds), "mean_predicted": round(mean_pred, 4), "fraction_positives": round(frac_pos, 4)})
        else:
            bins.append({"bin_start": round(lo, 2), "bin_end": round(hi, 2), "count": 0, "mean_predicted": 0.0, "fraction_positives": 0.0})
    ece = expected_calibration_error({"bins": bins})
    return {"bins": bins, "ece": round(ece, 6)}


def expected_calibration_error(calibration: dict) -> float:
    bins = calibration.get("bins", [])
    total = sum(b.get("count", 0) for b in bins)
    if total == 0:
        return 0.0
    ece = 0.0
    for b in bins:
        n = b.get("count", 0)
        if n > 0:
            ece += (n / total) * abs(b["mean_predicted"] - b["fraction_positives"])
    return ece


# ═══════════════════════════════════════════════════════════════════════════════
# ── Tournament Rank Probability Score (TRPS) ────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


def trps(prediction_matrix: np.ndarray, actual_ranks: np.ndarray,
         rank_weights: np.ndarray | None = None) -> float:
    """Tournament Rank Probability Score (Ekstrøm et al. 2021).

    Parameters
    ----------
    prediction_matrix : np.ndarray
        (R x T) matrix where R = number of ranks, T = number of teams.
        Each column must sum to 1.0 (predicted probability distribution
        over ranks for each team).
    actual_ranks : np.ndarray
        (T,) array of integers in 1..R giving each team's actual final rank.
    rank_weights : np.ndarray | None, optional
        (R-1,) array of non-negative weights for each rank (except the last).
        If None, uniform weights are used.

    Returns
    -------
    float
        TRPS score. 0.0 = perfect prediction. Higher = worse.

    Notes
    -----
    Formula: TRPS = 1/T * 1/(R-1) * sum_{t=1}^{T} sum_{r=1}^{R-1} (O_rt - X_rt)^2
    Where O is the one-hot encoded actual ranks and X is the cumulative prediction matrix.
    """
    R, T = prediction_matrix.shape

    # Convert actual ranks (1-indexed) to one-hot matrix O of shape (R, T)
    O = np.zeros((R, T))
    O[actual_ranks - 1, np.arange(T)] = 1.0

    # Cumulative distributions along rank axis
    O_cum = np.cumsum(O, axis=0)
    X_cum = np.cumsum(prediction_matrix, axis=0)

    # Squared differences at each rank (excluding last)
    squared_diff = (O_cum[:-1, :] - X_cum[:-1, :]) ** 2  # ((R-1) x T)

    if rank_weights is not None:
        weighted = rank_weights[:, np.newaxis] * squared_diff
        return float(np.sum(weighted) / (T * (R - 1)))

    return float(np.sum(squared_diff) / (T * (R - 1)))


def validate_tournament_matrix(
    prediction_matrix: np.ndarray,
    actual_ranks: np.ndarray,
) -> None:
    """Validate TRPS input matrix dimensions and constraints.

    Parameters
    ----------
    prediction_matrix : np.ndarray
        (R x T) predicted probability matrix.
    actual_ranks : np.ndarray
        (T,) array of actual ranks (1-indexed).

    Raises
    ------
    ValueError
        If any constraint is violated, with descriptive message.
    """
    if prediction_matrix.ndim != 2:
        raise ValueError(
            f"prediction_matrix must be 2D, got {prediction_matrix.ndim}D"
        )
    R, T = prediction_matrix.shape
    if R < 2:
        raise ValueError(
            f"prediction_matrix must have at least 2 ranks, got {R}"
        )
    if actual_ranks.ndim != 1:
        raise ValueError(
            f"actual_ranks must be 1D, got {actual_ranks.ndim}D"
        )
    if len(actual_ranks) != T:
        raise ValueError(
            f"actual_ranks length ({len(actual_ranks)}) must match "
            f"prediction_matrix columns ({T})"
        )
    if not np.allclose(np.sum(prediction_matrix, axis=0), 1.0, rtol=1e-5):
        raise ValueError(
            "Each column of prediction_matrix must sum to 1.0"
        )
    if np.any(actual_ranks < 1) or np.any(actual_ranks > R):
        raise ValueError(
            f"actual_ranks must be in range [1, {R}], "
            f"got [{actual_ranks.min()}, {actual_ranks.max()}]"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ── Multi-outcome evaluation helpers ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


def multi_class_log_loss(
    probabilities: list[list[float]],
    actuals: list[int],
    eps: float = 1e-15,
) -> float:
    """Multi-class log loss for 3-outcome (home/draw/away) predictions.

    Parameters
    ----------
    probabilities : list[list[float]]
        Nested list where each element is [p_home, p_draw, p_away].
    actuals : list[int]
        List of integers: 0 = home, 1 = draw, 2 = away.
    eps : float, optional
        Epsilon for numerical clamping, by default 1e-15.

    Returns
    -------
    float
        Multi-class log loss (lower = better).
    """
    n = len(probabilities)
    if n == 0:
        return 0.0

    total_loss = 0.0
    for probs, actual in zip(probabilities, actuals):
        p = max(eps, min(1 - eps, probs[actual]))
        total_loss += -math.log(p)

    return total_loss / n


def multi_class_brier(
    probabilities: list[list[float]],
    actuals: list[int],
) -> float:
    """Multi-class Brier score for 3-outcome (home/draw/away) predictions.

    Sum of squared differences across all 3 classes, divided by (3 * N).

    Parameters
    ----------
    probabilities : list[list[float]]
        Nested list where each element is [p_home, p_draw, p_away].
    actuals : list[int]
        List of integers: 0 = home, 1 = draw, 2 = away.

    Returns
    -------
    float
        Multi-class Brier score (0 = perfect, higher = worse).
    """
    n = len(probabilities)
    if n == 0:
        return 0.0

    total = 0.0
    for probs, actual in zip(probabilities, actuals):
        for k in range(3):
            y_k = 1.0 if k == actual else 0.0
            total += (probs[k] - y_k) ** 2

    return total / (3.0 * n)


def multi_class_ece(
    probabilities: list[list[float]],
    actuals: list[int],
    n_bins: int = 10,
) -> float:
    """Confidence-based Expected Calibration Error for 3-outcome predictions.

    Uses the max predicted probability as the confidence score, then bins
    predictions by confidence and compares mean confidence to accuracy.
    Adaptive binning reduces bin count when sample size < 100.

    Parameters
    ----------
    probabilities : list[list[float]]
        Nested list where each element is [p_home, p_draw, p_away].
    actuals : list[int]
        List of integers: 0 = home, 1 = draw, 2 = away.
    n_bins : int, optional
        Number of confidence bins, by default 10.

    Returns
    -------
    float
        Expected Calibration Error (0 = perfectly calibrated, higher = worse).
    """
    n = len(probabilities)
    if n == 0:
        return 0.0

    # Adaptive binning for small samples
    if n < 100:
        n_bins = max(3, n // 10)

    # For each prediction, record confidence (max prob) and whether it was correct
    confidences: list[float] = []
    correct: list[bool] = []
    for probs, actual in zip(probabilities, actuals):
        pred_class = int(np.argmax(probs))
        confidences.append(max(probs))
        correct.append(pred_class == actual)

    bins: list[dict] = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        bin_confs: list[float] = []
        bin_correct: list[bool] = []
        for c, ok in zip(confidences, correct):
            if lo <= c < hi or (i == n_bins - 1 and c == 1.0):
                bin_confs.append(c)
                bin_correct.append(ok)
        if bin_confs:
            mean_conf = sum(bin_confs) / len(bin_confs)
            acc = sum(1 for ok in bin_correct) / len(bin_correct)
            bins.append({
                "bin_start": round(lo, 2),
                "bin_end": round(hi, 2),
                "count": len(bin_confs),
                "mean_confidence": round(mean_conf, 4),
                "accuracy": round(acc, 4),
            })

    # Compute ECE as weighted mean of |confidence - accuracy|
    total_count = sum(b["count"] for b in bins)
    if total_count == 0:
        return 0.0

    ece = 0.0
    for b in bins:
        ece += (b["count"] / total_count) * abs(b["mean_confidence"] - b["accuracy"])

    return round(ece, 6)
