"""Rolling form signal — multi-window form features with exponential decay weighting (D-09: uses MatchResultProvider)."""

import logging
from datetime import datetime

from football_core.elo import expected_score
from football_core.result_provider import MatchResultProvider
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)


class RollingFormSignal(Signal):
    """Recent form signal using configurable windows and exponential decay.
    Uses MatchResultProvider for data (D-09 — agnostic to BSD vs replay)."""

    name: str = "rolling_form"

    def __init__(
        self,
        result_provider: MatchResultProvider,
        windows: list[int] | None = None,
        decay_factor: float = 0.9,
    ) -> None:
        self._result_provider = result_provider
        self._windows = windows or [3, 5, 10]
        self._decay_factor = decay_factor

    def _compute_form_for_team(
        self, team: str, match_date: str
    ) -> float:
        results = self._result_provider.get_team_results(
            team, match_date, limit=max(self._windows)
        )
        if not results:
            return 0.5
        results.sort(key=lambda r: r.get("event_date", ""), reverse=True)
        total_weight = 0.0
        weighted_sum = 0.0
        for k, r in enumerate(results):
            weight = self._decay_factor ** k
            if r.get("is_draw"):
                outcome = 0.5
            elif r.get("winner") == team:
                outcome = 1.0
            else:
                outcome = 0.0
            weighted_sum += outcome * weight
            total_weight += weight
        return weighted_sum / total_weight if total_weight > 0 else 0.5

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        event_date = match.get("event_date", "")

        form_a = self._compute_form_for_team(team_a, event_date)
        form_b = self._compute_form_for_team(team_b, event_date)

        raw_home = expected_score(
            form_a * 100 + 1500, form_b * 100 + 1500, home_advantage=0
        )
        draw_prob = max(0.0, 1.0 - abs(raw_home - 0.5) * 2.0) * 0.35
        away_prob = 1.0 - raw_home - draw_prob

        return SignalOutput(raw_home, draw_prob, away_prob)
