"""World Cup ensemble engine builder.

Builds the canonical EnsembleEngine over the surviving signal roster
(base Elo + market_odds / rolling_form / squad_value / rest_days caches)
with the standard weight-resolution precedence.

All signal implementations come from football_core: the base Elo signal is
``RefinedEloSignal`` registered under WC's historical name ``"elo"`` (weight
files, calibration filters, and UI labels depend on that identity), and the
cache-backed refinement signals are ``CachedProbabilitySignal``, which honor
each cache entry's own draw probability instead of any hardcoded constant.
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
    from football_core.signal import Signal, PredictionContext  # noqa: F401
    from football_core.signals.cached import CachedProbabilitySignal
    from football_core.signals.refined_elo import RefinedEloSignal

    _caches = {
        "market_odds": (odds_cache or {}).get("matches", {}),
        "rolling_form": (rolling_form_cache or {}).get("matches", {}),
        "squad_value": (squad_value_cache or {}).get("matches", {}),
        "rest_days": (rest_days_cache or {}).get("matches", {}),
    }

    signals: list[Signal] = [RefinedEloSignal(name="elo")]
    for cache_name, cache in _caches.items():
        signals.append(CachedProbabilitySignal(cache_name, cache))

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
