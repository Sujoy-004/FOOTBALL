"""Signal interface and registry — competition-agnostic signal architecture."""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class SignalOutput:
    """Probability distribution for one match from a single signal.
    Should sum to ~1.0 (caller may normalize if needed)."""

    home_prob: float
    draw_prob: float
    away_prob: float


@dataclass
class PredictionContext:
    """Rich context passed to each signal's predict() call.
    Contains all data a signal might need without forcing signals
    to import their own data sources."""

    fixtures: list
    elo_ratings: dict[str, float]
    played_results: list | None = None
    team_aliases: dict | None = None
    squad_values: dict[str, float] | None = None
    manager_data: dict[str, dict] | None = None
    player_data: dict[str, list[dict]] | None = None


@runtime_checkable
class Signal(Protocol):
    """Predict match outcome probabilities.
    Subclasses implement signal-specific logic.
    Must not modify match or context."""

    name: str

    def predict(self, match: dict, context: PredictionContext) -> SignalOutput: ...


class SignalRegistryError(Exception):
    """Raised on invalid SignalRegistry operations."""


class SignalRegistry:
    """Plugin-style registry for prediction signals.
    New signals added as new classes registered here —
    no modification to existing code.
    Use evaluate() as single entry point (D-08)."""

    def __init__(self) -> None:
        self._signals: dict[str, Signal] = {}

    def register(self, signal: Signal) -> None:
        if signal.name in self._signals:
            raise SignalRegistryError(
                f"Signal '{signal.name}' is already registered"
            )
        self._signals[signal.name] = signal

    def get(self, name: str) -> Signal:
        if name not in self._signals:
            raise SignalRegistryError(
                f"Signal '{name}' is not registered"
            )
        return self._signals[name]

    def list(self) -> list[str]:
        return sorted(self._signals.keys())

    def all(self) -> List[Signal]:
        return list(self._signals.values())

    def clear(self) -> None:
        self._signals.clear()

    def evaluate(
        self, match: dict, context: PredictionContext
    ) -> dict[str, SignalOutput]:
        """Evaluate all registered signals for a single match.
        Handles individual signal failures gracefully — a broken signal
        never crashes the pipeline."""
        results: dict[str, SignalOutput] = {}
        for name in sorted(self._signals):
            signal = self._signals[name]
            try:
                results[name] = signal.predict(match, context)
            except Exception:
                logger.error(
                    "Signal '%s' failed for match %s — returning uniform fallback",
                    name, match.get("match_id", "unknown"),
                )
                results[name] = SignalOutput(1 / 3, 1 / 3, 1 / 3)
        return results


@dataclass
class BlendedPrediction:
    """Final blended probability for one match from the ensemble.

    Produced by EnsembleEngine.evaluate(). Consumed by Phase 9 calibration
    and downstream consumers (simulation, display).

    signal_breakdown: {signal_name: {home, draw, away, weight}}
    weights_applied:  {signal_name: normalized_weight}
    """

    home_prob: float
    draw_prob: float
    away_prob: float
    signal_breakdown: dict[str, dict[str, float]]
    weights_applied: dict[str, float]
