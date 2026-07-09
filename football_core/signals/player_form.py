"""Player form / star-power signal — squad rating breadth and depth.

Uses player-level rating data from BSD API (context.player_data) to
estimate team strength based on the combined rating of top players.

The key insight: a team with many highly-rated players (stars) is more
likely to win than a team carried by one or two stars.

Formula:
  For each team, sum the top N ratings (default top 11 = best XI).
  strength_ratio = sum_a / (sum_a + sum_b)
  p = sigmoid(k * (strength_ratio - 0.5) * 4)

  → A team with 60% of the star-power gets p ≈ 0.77 (with k=1.5).
"""

import logging

from football_core.math_utils import sigmoid
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)

DEFAULT_K: float = 1.5
TOP_N: int = 11


class PlayerFormSignal(Signal):
    """Star-power signal — combined rating of each team's top N players.

    Requires context.player_data to be populated with team->list of player dicts
    (as produced by football_core.providers.player.parse_players).
    """

    name: str = "player_form"

    def __init__(self, k: float = DEFAULT_K, top_n: int = TOP_N) -> None:
        self._k = k
        self._top_n = top_n

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        player_data = context.player_data or {}

        players_a = player_data.get(team_a, [])
        players_b = player_data.get(team_b, [])

        if not players_a or not players_b:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        sum_a = _top_n_rating_sum(players_a, self._top_n)
        sum_b = _top_n_rating_sum(players_b, self._top_n)

        if sum_a + sum_b <= 0:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        strength_ratio = sum_a / (sum_a + sum_b)
        home_prob = sigmoid(self._k * (strength_ratio - 0.5) * 4)

        draw_prob = 0.25
        away_prob = max(0.0, 1.0 - home_prob - draw_prob)
        home_prob = 1.0 - draw_prob - away_prob

        return SignalOutput(home_prob, draw_prob, away_prob)


def _top_n_rating_sum(players: list[dict], n: int) -> float:
    """Sum the top N ratings from a list of player dicts."""
    ratings = sorted(
        (p.get("rating", 0.0) or 0.0 for p in players),
        reverse=True,
    )
    return sum(ratings[:n])
