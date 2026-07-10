"""Lineup strength signal — squad market value log-ratio."""

import logging
import math

from football_core.math_utils import sigmoid
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)

DEFAULT_LINEUP_K: float = 0.35
DEFAULT_DRAW_PROB: float = 0.25


def _compute_lineup_probability(
    team_a: str,
    team_b: str,
    squad_values: dict[str, float],
    k: float = DEFAULT_LINEUP_K,
) -> float | None:
    """Compute home win probability from squad value log-ratio.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        squad_values: Dict mapping team name → squad market value.
        k: Sigmoid steepness.

    Returns:
        Home win probability, or None if either team has no value data.
    """
    val_a = squad_values.get(team_a)
    val_b = squad_values.get(team_b)
    if val_a is None or val_b is None or val_a <= 0 or val_b <= 0:
        return None
    ratio = val_a / val_b
    return sigmoid(k * math.log(ratio))


class LineupStrengthSignal(Signal):
    """Squad market value log-ratio as a strength signal.

    Reads squad values from context.squad_values (pre-loaded by caller).
    Falls back to uniform if data is unavailable.
    """

    name: str = "lineup_strength"

    def __init__(self, k: float = DEFAULT_LINEUP_K) -> None:
        self._k = k

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        squad_values = context.squad_values or {}

        home_prob = _compute_lineup_probability(
            team_a, team_b, squad_values, self._k,
        )
        if home_prob is None:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        draw_prob = DEFAULT_DRAW_PROB
        away_prob = 1.0 - home_prob - draw_prob
        return SignalOutput(home_prob, draw_prob, away_prob)
