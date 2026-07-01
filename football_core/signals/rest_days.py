"""Rest days signal — fixture congestion effects computed from schedule."""

import logging
import math
from datetime import datetime

from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)


class RestDaysSignal(Signal):
    """Rest advantage signal computed entirely from fixture schedule.
    No external API needed."""

    name: str = "rest_days"

    def __init__(self, max_advantage: float = 0.1) -> None:
        self._max_advantage = max_advantage

    def _compute_rest_days(
        self, team: str, match_date: str, fixtures: list
    ) -> int:
        team_matches = [
            m
            for m in fixtures
            if (m.get("team_a") == team or m.get("team_b") == team)
            and m.get("event_date", "") < match_date
        ]
        if not team_matches:
            return 7
        team_matches.sort(key=lambda m: m.get("event_date", ""), reverse=True)
        latest = team_matches[0].get("event_date", "")
        try:
            current = datetime.fromisoformat(match_date)
            previous = datetime.fromisoformat(latest)
            diff = (current - previous).days
            return max(diff, 1)
        except (ValueError, TypeError):
            return 7

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        event_date = match.get("event_date", "")
        fixtures = context.fixtures or []

        rest_a = self._compute_rest_days(team_a, event_date, fixtures)
        rest_b = self._compute_rest_days(team_b, event_date, fixtures)

        diff = rest_a - rest_b
        adjustment = self._max_advantage * math.tanh(diff / 7.0)

        home_prob = (1 / 3) + adjustment
        draw_prob = 1 / 3
        away_prob = (1 / 3) - adjustment

        return SignalOutput(home_prob, draw_prob, away_prob)
