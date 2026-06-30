"""Calibration, blending, and evaluation primitives — competition-agnostic.

Pure-computation functions for Platt scaling, Brier-weighted blending,
rolling Brier computation, and Poisson base rate computation.

Uses ONLY Python stdlib (math module). No numpy, no sklearn.
"""

import json
import math

from football_core.elo import expected_score

EPS = 1e-15
RIDGE = 1e-6
MAX_ITER = 50
CONV_TOL = 1e-6


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x < -100:
        return EPS
    if x > 100:
        return 1 - EPS
    return 1 / (1 + math.exp(-x))


def _log_odds(p: float) -> float:
    """Clamp p to [EPS, 1-EPS], return log(p/(1-p))."""
    p = max(EPS, min(1 - EPS, p))
    return math.log(p / (1 - p))


def _platt_targets(actuals: list[float]) -> list[float]:
    n_pos = sum(1 for a in actuals if a == 1.0)
    n_neg = sum(1 for a in actuals if a == 0.0)

    t_pos = (n_pos + 1) / (n_pos + 2) if n_pos > 0 else 0.5
    t_neg = 1 / (n_neg + 2) if n_neg > 0 else 0.5

    targets = []
    for a in actuals:
        if a == 1.0:
            targets.append(t_pos)
        elif a == 0.0:
            targets.append(t_neg)
        else:
            targets.append(0.5)

    return targets


def calibrate_signal(predictions: list[float], actuals: list[float], threshold: int = 30) -> tuple[float, float]:
    if not predictions or not actuals or len(predictions) != len(actuals):
        return (1.0, 0.0)

    if len(predictions) < threshold:
        return (1.0, 0.0)

    try:
        x = [_log_odds(p) for p in predictions]
    except (ValueError, OverflowError):
        return (1.0, 0.0)

    t = _platt_targets(actuals)

    A = 0.0
    B = 0.0

    for _ in range(MAX_ITER):
        f = [A * xi + B for xi in x]
        p = [_sigmoid(fi) for fi in f]

        dA = sum(xi * (pi - ti) for xi, pi, ti in zip(x, p, t))
        dB = sum(pi - ti for pi, ti in zip(p, t))

        H_AA = sum(xi * xi * pi * (1 - pi) for xi, pi in zip(x, p)) + RIDGE
        H_AB = sum(xi * pi * (1 - pi) for xi, pi in zip(x, p))
        H_BB = sum(pi * (1 - pi) for pi in p) + RIDGE

        det = H_AA * H_BB - H_AB * H_AB
        if abs(det) < 1e-12:
            break

        dA_step = (H_BB * dA - H_AB * dB) / det
        dB_step = (H_AA * dB - H_AB * dA) / det

        A -= dA_step
        B -= dB_step

        if abs(dA_step) < CONV_TOL and abs(dB_step) < CONV_TOL:
            break

    return (A, B)


def apply_calibration(p_raw: float, A: float, B: float) -> float:
    if A == 1.0 and B == 0.0:
        p_clamped = max(EPS, min(1 - EPS, p_raw))
        if p_clamped <= EPS:
            return EPS
        if p_clamped >= 1 - EPS:
            return 1 - EPS
        return round(p_clamped, 6)

    p_clamped = max(EPS, min(1 - EPS, p_raw))

    try:
        log_odds_val = _log_odds(p_clamped)
    except (ValueError, OverflowError):
        p_fallback = max(EPS, min(1 - EPS, p_raw))
        if p_fallback <= EPS:
            return EPS
        if p_fallback >= 1 - EPS:
            return 1 - EPS
        return round(p_fallback, 6)

    x = A * log_odds_val + B
    result = _sigmoid(x)

    if result <= EPS:
        return EPS
    if result >= 1 - EPS:
        return 1 - EPS
    return round(result, 6)


def compute_rolling_brier(entries: list[dict], signal_key: str, window: int = 50) -> float:
    pairs = []

    for entry in entries:
        if not entry.get('available', True):
            continue

        signals = entry.get('signals', {})
        if signal_key not in signals:
            continue

        signal_data = signals[signal_key]
        probability = signal_data.get('probability')
        actual = entry.get('actual')

        if probability is None or actual is None:
            continue

        pairs.append((probability, actual))

    if len(pairs) > window:
        pairs = pairs[-window:]

    if not pairs:
        return 1.0

    brier_sum = sum((p - a) ** 2 for p, a in pairs)
    return brier_sum / len(pairs)


def compute_blend_weights(signal_briers: dict[str, float]) -> dict[str, float]:
    if not signal_briers:
        return {}

    raw_weights = {}
    for signal, brier in signal_briers.items():
        raw_weights[signal] = 1.0 / max(brier, 0.05)

    total = sum(raw_weights.values())
    if total == 0:
        weight = 1.0 / len(signal_briers)
        return {signal: round(weight, 6) for signal in signal_briers}

    normalized_weights = {}
    for signal, raw_weight in raw_weights.items():
        normalized_weights[signal] = round(raw_weight / total, 6)

    return normalized_weights


def blend_predictions(signal_preds: dict[str, float], weights: dict[str, float]) -> float:
    available_signals = set(signal_preds.keys()) & set(weights.keys())

    if not available_signals:
        return 0.5

    available_weights = {s: weights[s] for s in available_signals}
    total_weight = sum(available_weights.values())

    weighted_sum = sum(available_weights[s] * signal_preds[s] for s in available_signals)
    blended = weighted_sum / total_weight

    return round(blended, 6)


def compute_poisson_base_rate(match_data_path: str | None = None, fallback: float = 1.25) -> float:
    if match_data_path is None:
        return fallback

    try:
        with open(match_data_path, 'r') as f:
            data = json.load(f)

        total_goals = 0
        total_matches = 0

        for match in data:
            if 'goals' in match:
                total_goals += match['goals']
                total_matches += 1

        if total_matches == 0:
            return fallback

        rate = total_goals / total_matches / 2
        return round(rate, 4)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return fallback
