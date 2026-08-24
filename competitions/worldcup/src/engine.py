"""World Cup ensemble engine builder.

Builds the canonical EnsembleEngine over the surviving signal roster
(base Elo + market_odds / rolling_form / squad_value / rest_days caches)
with the standard weight-resolution precedence.
"""

import logging
from pathlib import Path
from typing import Any

from src.constants import (
    ODDS_CACHE_FILE,
    ROLLING_FORM_CACHE_FILE,
    SQUAD_VALUE_CACHE_FILE,
    REST_DAYS_CACHE_FILE,
)
from football_core.signal import PredictionContext

logger = logging.getLogger(__name__)


def build_signal_engine(
    odds_cache: dict | None = None,
    rolling_form_cache: dict | None = None,
    squad_value_cache: dict | None = None,
    rest_days_cache: dict | None = None,
    weights: dict[str, float] | None = None,
    weights_path: str | None = None,
) -> Any:
    """Build an EnsembleEngine: base Elo + the 4 cache-backed refinement signals."""
    from football_core.blender import EnsembleEngine
    from football_core.signal import Signal, SignalOutput, PredictionContext

    _caches = {
        "market_odds": (odds_cache or {}).get("matches", {}),
        "rolling_form": (rolling_form_cache or {}).get("matches", {}),
        "squad_value": (squad_value_cache or {}).get("matches", {}),
        "rest_days": (rest_days_cache or {}).get("matches", {}),
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
                draw_prob = 0.25
                return SignalOutput(prob, draw_prob, 1.0 - prob - draw_prob)
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

    class _EloSignal(Signal):
        name: str = "elo"

        def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
            from football_core.elo import expected_score
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")
            elo_ratings = context.elo_ratings or {}
            home = elo_ratings.get(team_a, 1500)
            away = elo_ratings.get(team_b, 1500)
            home_prob = expected_score(home, away, home_advantage=100)
            draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35
            away_prob = 1.0 - home_prob - draw_prob
            return SignalOutput(home_prob, draw_prob, away_prob)

    signals: list[Signal] = [_EloSignal()]
    for name, cache in _caches.items():
        signals.append(_CacheSignal(name, cache))

    if weights is not None:
        return EnsembleEngine(signals, weights=weights)
    if weights_path is not None:
        return EnsembleEngine(signals, weights_path=weights_path)
    return EnsembleEngine(signals)


def build_engine_from_caches(
    weights: dict[str, float] | None = None,
    data_dir: Path | str | None = None,
) -> Any:
    """Load all signal caches from disk and build an EnsembleEngine.

    Weight resolution: explicit ``weights`` dict > committed
    ``config/signal_weights.json`` (when present) > uniform fallback.
    """
    if data_dir is None:
        from src import constants as _c
        data_dir = _c.DATA_DIR
    from src.state import load_signal_cache

    odds_cache = load_signal_cache("odds_cache.json", data_dir)
    rolling_form_cache = load_signal_cache("rolling_form_cache.json", data_dir)
    squad_value_cache = load_signal_cache("squad_value_cache.json", data_dir)
    rest_days_cache = load_signal_cache("rest_days_cache.json", data_dir)

    weights_path = Path(__file__).resolve().parent.parent / "config" / "signal_weights.json"

    return build_signal_engine(
        odds_cache=odds_cache,
        rolling_form_cache=rolling_form_cache,
        squad_value_cache=squad_value_cache,
        rest_days_cache=rest_days_cache,
        weights=weights,
        weights_path=None if weights is not None else str(weights_path) if weights_path.exists() else None,
    )
