"""
Blender module for Phase 14 Signal Blending.

Contains pure-computation functions for Platt scaling, Brier-weighted blending,
rolling Brier computation, LOO-CV evaluation, Poisson base rate computation,
and full calibration+blend orchestration.

Uses ONLY Python stdlib (math module). No numpy, no sklearn per D-01.
"""

import json
import math

from src import constants
from src.elo import expected_score

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
    """Implement Platt's target adjustment from research Section 1 item 4."""
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


def calibrate_signal(predictions: list[float], actuals: list[float], threshold: int = constants.COLD_START_THRESHOLD) -> tuple[float, float]:
    """
    Fits Platt scaling on log-odds of predictions vs actual outcomes (0/0.5/1).
    
    If len(predictions) < threshold, returns (1.0, 0.0) for identity calibration.
    Pure Python Newton-Raphson (NOT scipy, NOT sklearn).
    Graceful degradation: returns (1.0, 0.0) for any edge case.
    """
    if not predictions or not actuals or len(predictions) != len(actuals):
        return (1.0, 0.0)
    
    if len(predictions) < threshold:
        return (1.0, 0.0)
    
    # Convert predictions to log-odds
    try:
        x = [_log_odds(p) for p in predictions]
    except (ValueError, OverflowError):
        return (1.0, 0.0)
    
    # Compute Platt-adjusted targets
    t = _platt_targets(actuals)
    
    # Initialize A=0.0, B=0.0 (identity initialization)
    A = 0.0
    B = 0.0
    
    # Newton-Raphson iteration
    for _ in range(MAX_ITER):
        # Compute f = [A*xi + B for xi in x], p = [_sigmoid(fi) for fi in f]
        f = [A * xi + B for xi in x]
        p = [_sigmoid(fi) for fi in f]
        
        # Gradient: dA = sum(xi*(pi - ti)), dB = sum(pi - ti)
        dA = sum(xi * (pi - ti) for xi, pi, ti in zip(x, p, t))
        dB = sum(pi - ti for pi, ti in zip(p, t))
        
        # Hessian with ridge: H_AA = sum(xi*xi*pi*(1-pi)) + RIDGE, H_AB = sum(xi*pi*(1-pi)), H_BB = sum(pi*(1-pi)) + RIDGE
        H_AA = sum(xi * xi * pi * (1 - pi) for xi, pi in zip(x, p)) + RIDGE
        H_AB = sum(xi * pi * (1 - pi) for xi, pi in zip(x, p))
        H_BB = sum(pi * (1 - pi) for pi in p) + RIDGE
        
        # Determinant: det = H_AA*H_BB - H_AB*H_AB; if abs(det) < 1e-12 break
        det = H_AA * H_BB - H_AB * H_AB
        if abs(det) < 1e-12:
            break
        
        # Newton step via Cramer's rule
        dA_step = (H_BB * dA - H_AB * dB) / det
        dB_step = (H_AA * dB - H_AB * dA) / det
        
        # Update A -= dA_step, B -= dB_step
        A -= dA_step
        B -= dB_step

        if abs(dA_step) < CONV_TOL and abs(dB_step) < CONV_TOL:
            break
    
    return (A, B)


def apply_calibration(p_raw: float, A: float, B: float) -> float:
    """
    Returns sigmoid(A * log_odds(p_raw) + B).
    
    Clamp p_raw to [EPS, 1-EPS] before log-odds transform.
    Clamp result to [EPS, 1-EPS] and round to 6 decimal places.
    Identity case: (A=1.0, B=0.0) → returns p_raw (identity transform).
    """
    # Identity case
    if A == 1.0 and B == 0.0:
        p_clamped = max(EPS, min(1 - EPS, p_raw))
        # Preserve EPS boundary values (don't round them to 0.0 or 1.0)
        if p_clamped <= EPS:
            return EPS
        if p_clamped >= 1 - EPS:
            return 1 - EPS
        return round(p_clamped, 6)
    
    # Clamp p_raw to [EPS, 1-EPS]
    p_clamped = max(EPS, min(1 - EPS, p_raw))
    
    # Compute log-odds
    try:
        log_odds_val = _log_odds(p_clamped)
    except (ValueError, OverflowError):
        p_fallback = max(EPS, min(1 - EPS, p_raw))
        if p_fallback <= EPS:
            return EPS
        if p_fallback >= 1 - EPS:
            return 1 - EPS
        return round(p_fallback, 6)
    
    # Apply calibration
    x = A * log_odds_val + B
    result = _sigmoid(x)
    
    # Clamp result to [EPS, 1-EPS] and round to 6 decimal places
    # Preserve EPS boundary values
    if result <= EPS:
        return EPS
    if result >= 1 - EPS:
        return 1 - EPS
    return round(result, 6)


def compute_rolling_brier(entries: list[dict], signal_key: str, window: int = constants.BRIER_WINDOW_SIZE) -> float:
    """
    Pure function — accepts prediction_history entries as a parameter (no I/O).
    
    Collects (probability, actual) pairs for signal_key where available=True and probability is not None and actual is not None.
    Takes last `window` entries by list order (history is chronologically ordered).
    Returns mean Brier: sum((p-a)**2)/n if pairs exist; returns 1.0 if no pairs (worst case).
    """
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
    
    # Take last `window` entries
    if len(pairs) > window:
        pairs = pairs[-window:]
    
    if not pairs:
        return 1.0
    
    # Compute mean Brier
    brier_sum = sum((p - a) ** 2 for p, a in pairs)
    return brier_sum / len(pairs)


def compute_blend_weights(signal_briers: dict[str, float]) -> dict[str, float]:
    """
    Per D-07: for each key, raw_weight = 1.0 / max(brier, 0.05)
    Floor at 0.05 prevents division by zero (D-07) and extreme weights from near-perfect signals.
    Normalize: divide each raw_weight by sum of all raw_weights.
    Edge case: if sum(raw_weights) == 0, return equal weights for all signals (graceful degradation per D-22).
    Round output weights to 6 decimal places.
    """
    if not signal_briers:
        return {}
    
    # Compute raw weights with floor at 0.05
    raw_weights = {}
    for signal, brier in signal_briers.items():
        raw_weights[signal] = 1.0 / max(brier, 0.05)
    
    # Normalize
    total = sum(raw_weights.values())
    if total == 0:
        # Equal weights for all signals
        weight = 1.0 / len(signal_briers)
        return {signal: round(weight, 6) for signal in signal_briers}
    
    # Normalize and round
    normalized_weights = {}
    for signal, raw_weight in raw_weights.items():
        normalized_weights[signal] = round(raw_weight / total, 6)
    
    return normalized_weights


def blend_predictions(signal_preds: dict[str, float], weights: dict[str, float]) -> float:
    """
    Only includes signals present in BOTH signal_preds AND weights (signal is available and has a weight).
    Re-normalizes weights to sum to 1 for the available subset (pitfall 6 from research: blend weights for missing signals).
    If no signals available: return 0.5 (uniform prior — graceful degradation per D-22).
    Blended = sum(weight[s] * prob[s] for available signals) / sum(weight[s] for available signals).
    Round result to 6 decimal places.
    """
    # Find intersection of signals
    available_signals = set(signal_preds.keys()) & set(weights.keys())
    
    if not available_signals:
        return 0.5
    
    # Re-normalize weights for available signals
    available_weights = {s: weights[s] for s in available_signals}
    total_weight = sum(available_weights.values())
    
    # Compute weighted average
    weighted_sum = sum(available_weights[s] * signal_preds[s] for s in available_signals)
    blended = weighted_sum / total_weight
    
    # Round result to 6 decimal places
    return round(blended, 6)





def compute_poisson_base_rate(match_data_path: str | None = None) -> float:
    """
    Per V2-09, D-09, D-10: Compute expected goals per team per match from historical World Cup data.
    
    If match_data_path is None or file doesn't exist: return 1.25 (current default from constants.py, per research Option C).
    If file exists: load JSON data, compute total_goals / total_matches / 2 (goals per team per match).
    Return float rounded to 4 decimal places.
    """
    if match_data_path is None:
        return 1.25
    
    try:
        with open(match_data_path, 'r') as f:
            data = json.load(f)
        
        total_goals = 0
        total_matches = 0
        
        for match in data:
            # Assuming match structure has 'goals' and 'teams' fields
            if 'goals' in match:
                total_goals += match['goals']
                total_matches += 1
        
        if total_matches == 0:
            return 1.25
        
        # Goals per team per match (each match has 2 teams)
        rate = total_goals / total_matches / 2
        return round(rate, 4)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return 1.25


def calibrate_and_blend(history: list[dict], signal_keys: list[str], elo_ratings: dict[str, float],
                        groups_data: dict, bracket_data: list[dict],
                        odds_cache: dict, cb_cache: dict,
                        brier_window: int = constants.BRIER_WINDOW_SIZE,
                        cold_start_threshold: int = constants.COLD_START_THRESHOLD,
                        form_cache: dict | None = None,
                        lineup_cache: dict | None = None) -> dict | None:
    """
    Orchestration function — the single entry point for the entire calibration+blending pipeline.
    Accepts all data as parameters. No file I/O. Pure computation.
    
    Returns dict with keys:
      - "calibration_params": dict per signal (for persistence)
      - "blend_weights": dict[str, float] (per-signal weights)
      - "match_probs": dict[str, float] (match_id → blended probability)
    Or None if no history or no signal caches available (graceful degradation per D-22).
    """
    if not history or not signal_keys:
        return None
    
    # Flow A — Calibration fitting
    calibration_params = {}
    
    for signal_key in signal_keys:
        # Collect (prediction, actual) pairs from history
        predictions = []
        actuals = []
        
        for entry in history:
            if not entry.get('available', True):
                continue
            
            signals = entry.get('signals', {})
            if signal_key not in signals:
                continue
            
            signal_data = signals[signal_key]
            probability = signal_data.get('probability')
            actual = entry.get('actual')
            
            if probability is not None and actual is not None:
                predictions.append(probability)
                actuals.append(actual)
        
        if len(predictions) >= cold_start_threshold:
            A, B = calibrate_signal(predictions, actuals)
            calibration_params[signal_key] = {
                "A": A,
                "B": B,
                "n_matches": len(predictions),
                "brier": compute_rolling_brier(history, signal_key, brier_window),
                "fitted_at": "now"
            }
        else:
            calibration_params[signal_key] = {
                "A": 1.0,
                "B": 0.0,
                "n_matches": len(predictions),
                "brier": compute_rolling_brier(history, signal_key, brier_window),
                "fitted_at": "cold_start"
            }
    
    # Flow B — Blend weights
    signal_briers = {}
    for signal_key in signal_keys:
        signal_briers[signal_key] = calibration_params[signal_key]["brier"]
    
    blend_weights = compute_blend_weights(signal_briers)
    
    # Flow C — Match probabilities
    match_probs = {}
    
    try:
        # Default caches to empty dicts
        form_cache = form_cache or {}
        lineup_cache = lineup_cache or {}
        
        # Collect all matches from groups and bracket
        all_matches: list[dict] = []
        groups_data_inner = groups_data.get("groups", groups_data) if isinstance(groups_data, dict) else groups_data
        if isinstance(groups_data_inner, dict):
            for group_letter in groups_data_inner:
                group = groups_data_inner[group_letter]
                if isinstance(group, dict):
                    for m in group.get("matches", []):
                        if isinstance(m, dict):
                            all_matches.append(m)
        
        if isinstance(bracket_data, list):
            for m in bracket_data:
                if isinstance(m, dict):
                    all_matches.append(m)
        
        # Build cache lookups by match_id
        odds_matches = odds_cache.get("matches", {}) if isinstance(odds_cache, dict) else {}
        cb_matches = cb_cache.get("matches", {}) if isinstance(cb_cache, dict) else {}
        form_matches = form_cache.get("matches", {}) if isinstance(form_cache, dict) else {}
        lineup_matches = lineup_cache.get("matches", {}) if isinstance(lineup_cache, dict) else {}
        
        for match in all_matches:
            mid = match.get("match_id", "")
            if not mid:
                continue
            t_a = match.get("team_a", "")
            t_b = match.get("team_b", "")
            if t_a not in elo_ratings or t_b not in elo_ratings:
                continue
            
            # Collect raw probabilities from each signal
            elo_prob = expected_score(elo_ratings[t_a], elo_ratings[t_b])
            odds_prob = odds_matches.get(mid, {}).get("probability") if isinstance(odds_matches.get(mid), dict) else None
            cb_prob = cb_matches.get(mid, {}).get("probability") if isinstance(cb_matches.get(mid), dict) else None
            form_prob = form_matches.get(mid, {}).get("probability") if isinstance(form_matches.get(mid), dict) else None
            lineup_prob = lineup_matches.get(mid, {}).get("probability") if isinstance(lineup_matches.get(mid), dict) else None
            
            raw_probs: dict[str, float] = {}
            for sig_key, raw_p in [
                ("elo", elo_prob),
                ("market_odds", odds_prob),
                ("catboost", cb_prob),
                ("form", form_prob),
                ("lineup_strength", lineup_prob),
            ]:
                if raw_p is not None and isinstance(raw_p, (int, float)):
                    raw_probs[sig_key] = raw_p
            
            if not raw_probs:
                match_probs[mid] = 0.5
                continue
            
            # Apply calibration to each raw probability
            calibrated_probs: dict[str, float] = {}
            for sig_key, raw_p in raw_probs.items():
                cal = calibration_params.get(sig_key, {})
                A = cal.get("A", 1.0) if isinstance(cal, dict) else 1.0
                B = cal.get("B", 0.0) if isinstance(cal, dict) else 0.0
                calibrated_probs[sig_key] = apply_calibration(raw_p, A, B)
            
            # Blend calibrated probabilities
            blended = blend_predictions(calibrated_probs, blend_weights)
            match_probs[mid] = blended
    except Exception:
        pass
    
    if calibration_params and blend_weights:
        return {
            "calibration_params": calibration_params,
            "blend_weights": blend_weights,
            "match_probs": match_probs
        }
    
    return None


if __name__ == "__main__":
    import json
    import math
    print("Blender module loaded successfully")
    print(f"Available functions: {[f for f in dir() if not f.startswith('_')]}")
