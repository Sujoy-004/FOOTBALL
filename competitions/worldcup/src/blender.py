"""Blender module for Phase 14 Signal Blending.

Primitives imported from football_core.blender. Orchestration (calibrate_and_blend)
lives here because it wires WC-specific signal names and cache structures.
"""

from football_core.blender import (
    _sigmoid,
    _log_odds,
    _platt_targets,
    calibrate_signal,
    apply_calibration,
    compute_rolling_brier,
    compute_blend_weights,
    blend_predictions,
    compute_poisson_base_rate,
    EPS,
    RIDGE,
    MAX_ITER,
    CONV_TOL,
)
from src import constants
from src.elo import expected_score


def calibrate_and_blend(
    history: list[dict], signal_keys: list[str], elo_ratings: dict[str, float],
    groups_data: dict, bracket_data: list[dict],
    odds_cache: dict, cb_cache: dict,
    brier_window: int = constants.BRIER_WINDOW_SIZE,
    cold_start_threshold: int = constants.COLD_START_THRESHOLD,
    form_cache: dict | None = None,
    lineup_cache: dict | None = None,
) -> dict | None:
    if not history or not signal_keys:
        return None

    calibration_params = {}

    for signal_key in signal_keys:
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

    signal_briers = {}
    for signal_key in signal_keys:
        signal_briers[signal_key] = calibration_params[signal_key]["brier"]

    blend_weights = compute_blend_weights(signal_briers)

    match_probs = {}

    try:
        form_cache = form_cache or {}
        lineup_cache = lineup_cache or {}

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

            calibrated_probs: dict[str, float] = {}
            for sig_key, raw_p in raw_probs.items():
                cal = calibration_params.get(sig_key, {})
                A = cal.get("A", 1.0) if isinstance(cal, dict) else 1.0
                B = cal.get("B", 0.0) if isinstance(cal, dict) else 0.0
                calibrated_probs[sig_key] = apply_calibration(raw_p, A, B)

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
