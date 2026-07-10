"""CatBoost prediction signal — wraps CatBoost model cache for WC integration."""

import logging

from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)


class CatBoostSignal(Signal):
    """CatBoost model prediction signal.

    Reads from a pre-loaded catboost cache dict passed via constructor.
    If no cache is provided, returns uniform fallback.
    """

    name: str = "catboost"

    def __init__(self, cache: dict | None = None) -> None:
        self._cache = cache or {}

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        mid = match.get("match_id", "")
        entry = self._cache.get("matches", {}).get(mid) if self._cache else None
        if entry:
            prob = entry.get("probability", 1 / 3)
            draw_prob = 0.25
            return SignalOutput(prob, draw_prob, 1.0 - prob - draw_prob)
        logger.debug(
            "CatBoost cache miss for match %s — returning uniform",
            mid,
        )
        return SignalOutput(1 / 3, 1 / 3, 1 / 3)
