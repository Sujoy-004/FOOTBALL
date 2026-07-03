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


def _brent_minimize(
    f,
    a: float,
    b: float,
    tol: float = 1e-6,
    max_iter: int = 50,
) -> float:
    """Brent's method for 1D minimization (parabolic interpolation + golden section).

    Finds minimum of f(x) in [a, b] (unimodal) using Brent's method with
    golden-section fallback. Pure Python stdlib — no numpy/scipy dependency.

    Args:
        f: Objective function to minimize (must be unimodal in [a, b]).
        a: Left bracket.
        b: Right bracket.
        tol: Convergence tolerance on x.
        max_iter: Maximum iterations.

    Returns:
        Approximate minimizer x*.

    Reference:
        Brent, R. P. (1973). Algorithms for Minimization without Derivatives.
        Implementation based on the algorithm in Numerical Recipes §10.2.
    """
    # Golden ratio conjugate
    φ = (3 - math.sqrt(5)) / 2  # ≈ 0.381966

    # Ensure correct ordering
    if a > b:
        a, b = b, a

    # Initial interior point
    x = w = v = a + φ * (b - a)
    fx = fw = fv = f(x)

    # Previous step distance (e) and current step (d)
    d = 0.0
    e = 0.0

    for _ in range(max_iter):
        # Midpoint and convergence tolerance
        xm = (a + b) * 0.5
        tol1 = tol * abs(x) + 1e-10
        tol2 = 2.0 * tol1

        # --- Convergence check ---
        if abs(x - xm) <= tol2 - 0.5 * (b - a):
            break

        # --- Attempt parabolic interpolation ---
        # Only try if we have distinct points for a meaningful parabola
        p, q = 0.0, 0.0
        parabolic_ok = False

        if abs(e) > tol1:
            # Three distinct points for interpolation
            # Parabolic minimizer: step = -0.5 * ( (x-w)^2*(fx-fv) - (x-v)^2*(fx-fw) )
            #                           / ( (x-w)*(fx-fv) - (x-v)*(fx-fw) )
            r = (x - w) * (fx - fv)
            s = (x - v) * (fx - fw)
            denom = 2.0 * (r - s)

            if abs(denom) > 1e-15:
                # Numerator = (x-w)^2 * (fx-fv) - (x-v)^2 * (fx-fw)
                num = (x - w) * (x - w) * (fx - fv) - (x - v) * (x - v) * (fx - fw)
                p = num / denom  # This gives the step directly
                q = 1.0

                # Accept parabolic step only if it falls within [a,b]
                # and is not too large (less than half the previous step)
                step = p  # step from x to parabolic minimum
                if (abs(step) < abs(0.5 * e)
                        and a + tol1 <= x + step <= b - tol1):
                    parabolic_ok = True

        # --- If parabolic step is invalid, do golden-section ---
        if not parabolic_ok:
            # Golden section: step toward the larger gap
            if x >= xm:
                e = a - x
            else:
                e = b - x
            d = φ * e
        else:
            d = p  # Parabolic step
            e = d

        # Step magnitude must be at least tol1 (to avoid stagnation)
        if abs(d) < tol1:
            # Use sign of (xm - x) to step toward midpoint
            d = tol1 if xm >= x else -tol1

        # Take the step
        u = x + d
        fu = f(u)

        # --- Update bracket and best point ---
        if fu <= fx:
            # New point is better — move bracket to contain it
            if u >= x:
                a = x
            else:
                b = x
            # Shift points
            v, w, x = w, x, u
            fv, fw, fx = fw, fx, fu
        else:
            # x remains best — narrow bracket
            if u >= x:
                b = u
            else:
                a = u
            # Update v, w (keep x as best)
            if fu <= fw or abs(w - x) < tol1:
                v, w = w, u
                fv, fw = fw, fu
            elif fu <= fv or abs(v - x) < tol1 or abs(v - w) < tol1:
                v = u
                fv = fu

    return x


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


def compute_signal_contributions(
    blended_predictions: list[BlendedPrediction],
    target_team: str,
    weights: dict[str, float],
    match_fixtures: list[dict] | None = None,
) -> dict[str, float]:
    """Compute per-signal contribution to champion probability for a target team.

    Uses post-hoc attribution approximation: each signal is attributed a share of
    the champion probability based on its ensemble weight and how much its
    prediction deviates from uniform (1/3) for the target team's match outcomes.

    This is NOT exact decomposition — champion probability emerges from a non-linear
    MC pipeline (simulation -> standings -> tiebreakers -> bracket) and cannot be
    exactly decomposed into additive signal contributions. The attribution provides
    directional intuition (which signals push the prediction up/down), not causal
    decomposition.

    Args:
        blended_predictions: List of BlendedPrediction for all tournament matches.
        target_team: The team name to compute contributions for.
        weights: {signal_name: normalized_weight} from EnsembleEngine.
        match_fixtures: Optional list of match dicts with team_a/team_b keys.
            Must be same length as blended_predictions. When provided, contributions
            are computed only for matches involving target_team, using the correct
            home/away direction. When omitted, contributions are computed across
            all matches using average of home/away probabilities.

    Returns:
        {signal_name: raw_contribution} dict. Values are un-normalized contribution
        scores that the display layer scales to match champion probability.
        Returns empty dict if no relevant data.
    """
    if not blended_predictions or not weights or target_team is None:
        return {}

    # Initialize contribution accumulators for all signals in weights
    contributions: dict[str, float] = {sig: 0.0 for sig in weights}
    match_count: dict[str, int] = {sig: 0 for sig in weights}
    uniform_baseline = 1 / 3

    if match_fixtures is not None and len(match_fixtures) == len(blended_predictions):
        # ── Team-filtered mode: compute contributions only for target_team's matches ──
        for bp, match in zip(blended_predictions, match_fixtures):
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")
            if target_team not in (team_a, team_b):
                continue

            outcome_key = "home" if target_team == team_a else "away"
            for signal, weight in weights.items():
                if signal in bp.signal_breakdown:
                    sig_prob = bp.signal_breakdown[signal].get(outcome_key, uniform_baseline)
                    contributions[signal] += weight * (sig_prob - uniform_baseline)
                    match_count[signal] += 1
    else:
        # ── Global mode: compute across all matches (fallback without match info) ──
        for bp in blended_predictions:
            for signal, weight in weights.items():
                if signal in bp.signal_breakdown:
                    sig_home = bp.signal_breakdown[signal].get("home", uniform_baseline)
                    sig_away = bp.signal_breakdown[signal].get("away", uniform_baseline)
                    # Use the larger of home/away deviation as a directional proxy
                    best_outcome = max(sig_home, sig_away)
                    contributions[signal] += weight * (best_outcome - uniform_baseline)
                    match_count[signal] += 1

    # Remove signals with zero contribution/no matches
    result = {sig: round(val, 4) for sig, val in contributions.items()
              if match_count.get(sig, 0) > 0}

    return result
