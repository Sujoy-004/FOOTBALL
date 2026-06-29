"""Shared accuracy metric primitives — extracted from WC evaluation.py."""

import math


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
