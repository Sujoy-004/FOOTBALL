"""Calibration, blending, and evaluation primitives — competition-agnostic.

Pure-computation functions for Platt scaling, Brier-weighted blending,
rolling Brier computation, and Poisson base rate computation.

Uses ONLY Python stdlib (math module). No numpy, no sklearn.
"""

import json
import math

from football_core.elo import expected_score
from football_core.signal import BlendedPrediction, PredictionContext, Signal, SignalRegistry, SignalOutput

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


class EnsembleEngine:
    """Orchestrates signal evaluation and blends results into a single prediction.

    Wraps SignalRegistry for signal evaluation, applies weighted averaging
    per outcome (home/draw/away independently), re-normalizes to 1.0.
    """

    def __init__(
        self,
        signals: list[Signal],
        weights: dict[str, float] | None = None,
        weights_path: str | None = None,
    ):
        """Construct engine with signals and weights.

        Args:
            signals: List of Signal instances to register and evaluate.
            weights: Optional direct weights dict (takes precedence over file).
            weights_path: Optional path to JSON weight config file.
                If both weights and weights_path are None, uniform weights are used.
        """
        self._registry = SignalRegistry()
        for sig in signals:
            self._registry.register(sig)

        # Resolve weights: direct dict > JSON file > uniform fallback
        if weights is not None:
            self._weights = {k: v for k, v in weights.items() if v > 0}
        elif weights_path is not None:
            with open(weights_path) as f:
                data = json.load(f)
            raw = data.get("weights", {})
            self._weights = {k: v for k, v in raw.items() if v > 0}
        else:
            # Uniform fallback to all registered signals
            names = self._registry.list()
            uniform = 1.0 / len(names) if names else 0.0
            self._weights = {n: uniform for n in names}

    def evaluate(self, match: dict, context: PredictionContext) -> BlendedPrediction:
        """Evaluate all registered signals and blend into a single prediction.

        Args:
            match: Match dict with team_a, team_b, match_id, etc.
            context: PredictionContext with elo_ratings, fixtures, etc.

        Returns:
            BlendedPrediction with blended probabilities, signal breakdown, and weights.
        """
        signal_results = self._registry.evaluate(match, context)
        return self._blend(signal_results)

    def _blend(self, results: dict[str, SignalOutput]) -> BlendedPrediction:
        """Blend per-signal SignalOutputs into a single BlendedPrediction.

        Blends home_prob, draw_prob, away_prob independently, then
        re-normalizes to handle floating-point drift.
        """
        # Filter to signals that have positive weights and produced output
        active = {name: out for name, out in results.items()
                  if self._weights.get(name, 0) > 0}

        if not active:
            return BlendedPrediction(1 / 3, 1 / 3, 1 / 3, {}, {})

        # Re-normalize weights for available signals
        avail_weights = {n: self._weights[n] for n in active}
        total_w = sum(avail_weights.values())  # guaranteed > 0 since active is non-empty
        norm_weights = {n: w / total_w for n, w in avail_weights.items()}

        # Blend each outcome independently per Pitfall 1
        blended_h = sum(norm_weights[n] * r.home_prob for n, r in active.items())
        blended_d = sum(norm_weights[n] * r.draw_prob for n, r in active.items())
        blended_a = sum(norm_weights[n] * r.away_prob for n, r in active.items())

        # Re-normalize to handle floating-point drift per D-01
        total = blended_h + blended_d + blended_a
        if total > 0:
            blended_h /= total
            blended_d /= total
            blended_a /= total

        # Build breakdown dict: {signal_name: {home, draw, away, weight}}
        breakdown = {}
        for name, result in active.items():
            breakdown[name] = {
                "home": round(result.home_prob, 4),
                "draw": round(result.draw_prob, 4),
                "away": round(result.away_prob, 4),
                "weight": round(norm_weights[name], 4),
            }

        return BlendedPrediction(
            home_prob=round(blended_h, 6),
            draw_prob=round(blended_d, 6),
            away_prob=round(blended_a, 6),
            signal_breakdown=breakdown,
            weights_applied=dict(norm_weights),
        )

    @property
    def weights(self) -> dict[str, float]:
        """Return current weights dict (read-only)."""
        return dict(self._weights)


def compute_log_loss_weights(log_losses: dict[str, float]) -> dict[str, float]:
    """Compute inverse-log-loss normalized weights for ensemble blending.

    w_i = (1/ll_i) / sum(1/ll_j for j in signals)

    Delegates to compute_blend_weights() which implements the same
    1/x normalization. This wrapper exists for API clarity — callers
    pass log-loss values, not Brier scores.

    Args:
        log_losses: {signal_name: log_loss_value}

    Returns:
        {signal_name: normalized_weight} summing to 1.0
    """
    return compute_blend_weights(log_losses)
