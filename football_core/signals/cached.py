"""Cache-backed probability signal — canonical replacement for competition-local
cache wrappers.

Reads the repository's standard signal-cache entry shape::

    {"match_id": {"probability": float | None,
                  "draw_probability": float | None,   # optional
                  "available": bool, "reason": str}}  # optional

Semantics (registry convention, football_core.signal.SignalRegistry):

- missing match / ``available: false`` / ``probability: None``
      -> uniform thirds (the documented degraded output; never raises)
- otherwise
      -> home = cached probability
         draw = cached draw_probability when present, else ``default_draw``
         away = remainder, clamped so H + D + A == 1 with all parts >= 0

The draw probability is never a hardcoded constant: caches carry their own
draw estimates and callers may pass an explicit fallback.
"""

from __future__ import annotations

from football_core.signal import Signal, SignalOutput, PredictionContext

_UNIFORM = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)


class CachedProbabilitySignal(Signal):
    """Signal backed by a precomputed per-match probability cache."""

    def __init__(
        self,
        name: str,
        cache: dict[str, dict] | None,
        default_draw: float = 1.0 / 3.0,
    ) -> None:
        self.name = name
        self._cache = cache or {}
        self._default_draw = default_draw

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        mid = match.get("match_id", "")
        entry = self._cache.get(mid) if self._cache else None
        if not isinstance(entry, dict):
            return SignalOutput(*_UNIFORM)
        prob = entry.get("probability")
        if entry.get("available") is False or prob is None:
            return SignalOutput(*_UNIFORM)
        try:
            p = float(prob)
        except (TypeError, ValueError):
            return SignalOutput(*_UNIFORM)
        if not 0.0 <= p <= 1.0:
            return SignalOutput(*_UNIFORM)

        draw = entry.get("draw_probability")
        try:
            d = float(draw) if draw is not None else float(self._default_draw)
        except (TypeError, ValueError):
            d = float(self._default_draw)
        # Clamp so the residual away probability can never go negative.
        d = min(max(d, 0.0), 1.0 - p)
        away = 1.0 - p - d
        return SignalOutput(p, d, away)
