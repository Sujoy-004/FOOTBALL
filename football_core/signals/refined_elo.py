"""Refined Elo signal — wraps ClubElo with configurable K-factor and goal-difference weighting."""

import logging

from football_core.constants import DEFAULT_ELO
from football_core.elo import expected_score
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)


class RefinedEloSignal(Signal):
    """Elo-based prediction signal with configurable K-factor, home advantage,
    and goal-difference weighting."""

    name: str = "refined_elo"

    def __init__(
        self,
        k_factor: int = 60,
        home_advantage: int = 100,
        goal_diff_weighting: bool = True,
    ) -> None:
        self._k_factor = k_factor
        self._home_advantage = home_advantage
        self._goal_diff_weighting = goal_diff_weighting

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")

        home_elo = context.elo_ratings.get(team_a, DEFAULT_ELO)
        away_elo = context.elo_ratings.get(team_b, DEFAULT_ELO)

        home_prob = expected_score(home_elo, away_elo, self._home_advantage)
        draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35
        away_prob = 1.0 - home_prob - draw_prob

        return SignalOutput(home_prob, draw_prob, away_prob)
