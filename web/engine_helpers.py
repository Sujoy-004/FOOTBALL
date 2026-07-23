"""EnsembleEngine helpers for the web app — bridge between on-disk caches and BlendedPredictions."""

import json
from pathlib import Path

from competitions.worldcup.src import constants
from competitions.worldcup.src.state import load_signal_cache
from football_core.blender import EnsembleEngine
from football_core.signal import BlendedPrediction, PredictionContext, Signal, SignalOutput

DATA_DIR = constants.DATA_DIR


def _build_engine_from_caches(weights: dict[str, float] | None = None) -> EnsembleEngine | None:
    """Load all signal caches from disk and build an EnsembleEngine.

    Args:
        weights: Optional dict of signal weights (e.g. {"elo": 0.4, "market_odds": 0.3}).
            Passed to EnsembleEngine for weighted blend. None = uniform fallback.

    Returns None if no caches are available (cold start).
    """
    odds_cache = load_signal_cache("odds_cache.json", DATA_DIR)
    cb_cache = load_signal_cache("catboost_cache.json", DATA_DIR)
    form_cache = load_signal_cache("form_cache.json", DATA_DIR)
    lineup_cache = load_signal_cache("lineup_cache.json", DATA_DIR)
    defensive_cache = load_signal_cache("defensive_cache.json", DATA_DIR)
    manager_cache = load_signal_cache("manager_effect_cache.json", DATA_DIR)
    availability_cache = load_signal_cache("availability_cache.json", DATA_DIR)

    _caches = {
        "market_odds": (odds_cache or {}).get("matches", {}),
        "catboost": (cb_cache or {}).get("matches", {}),
        "form": (form_cache or {}).get("matches", {}),
        "lineup_strength": (lineup_cache or {}).get("matches", {}),
        "defensive_quality": (defensive_cache or {}).get("matches", {}),
        "manager_effect": (manager_cache or {}).get("matches", {}),
        "availability": (availability_cache or {}).get("matches", {}),
    }

    class _CacheSignal(Signal):
        name: str = ""
        def __init__(self, name: str, cache: dict) -> None:
            self.name = name
            self._cache = cache
        def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
            mid = match.get("match_id", "")
            entry = self._cache.get(mid) if self._cache else None
            if entry:
                prob = entry.get("probability", 1 / 3)
                return SignalOutput(prob, 0.25, 1.0 - prob - 0.25)
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

    class _EloSignal(Signal):
        name: str = "elo"
        def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
            from football_core.elo import expected_score
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")
            elo_r = context.elo_ratings or {}
            home = elo_r.get(team_a, 1500)
            away = elo_r.get(team_b, 1500)
            hp = expected_score(home, away, home_advantage=100)
            dp = max(0.0, 1.0 - abs(hp - 0.5) * 2.0) * 0.35
            return SignalOutput(hp, dp, 1.0 - hp - dp)

    signals = [_EloSignal()]
    for name, cache in _caches.items():
        sig = _CacheSignal(name, cache)
        signals.append(sig)

    return EnsembleEngine(signals, weights=weights)



def compute_team_strengths_from_predictions(
    predictions: list[BlendedPrediction],
    all_matches: list[dict],
) -> dict[str, dict[str, float]]:
    """Build per-team per-signal strength from BlendedPrediction signal_breakdown.

    Returns: {signal_name: {team_name: avg_strength}}
    """
    accum: dict[str, dict[str, list[float]]] = {}
    for bp, match in zip(predictions, all_matches):
        ta = match.get("team_a", "")
        tb = match.get("team_b", "")
        if not ta or not tb:
            continue
        for sig_name, breakdown in bp.signal_breakdown.items():
            if sig_name not in accum:
                accum[sig_name] = {}
            accum[sig_name].setdefault(ta, []).append(breakdown.get("home", 0.5))
            accum[sig_name].setdefault(tb, []).append(breakdown.get("away", 0.5))

    result: dict[str, dict[str, float]] = {}
    for sig_name, team_vals in accum.items():
        result[sig_name] = {
            team: sum(vals) / len(vals) for team, vals in team_vals.items()
        }
    return result
