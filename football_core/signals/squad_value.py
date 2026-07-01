"""Squad value signal — Transfermarkt-based strength ratio with log-transform."""

import json
import logging
import math
import os

from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)

_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "competitions",
    "ucl",
    "data",
    "squad_values.json",
)


class SquadValueSignal(Signal):
    """Squad strength signal using Transfermarkt values with log-transform.
    Log-transform prevents billionaires from dominating linearly."""

    name: str = "squad_value"

    def __init__(self, data_path: str | None = None) -> None:
        self._data_path = data_path or _DEFAULT_DATA_PATH
        self._values: dict[str, float] | None = None

    def _load_values(self) -> dict[str, float]:
        if self._values is not None:
            return self._values
        try:
            with open(self._data_path) as f:
                self._values = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("Could not load squad values from %s: %s", self._data_path, exc)
            self._values = {}
        return self._values

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        values = context.squad_values if context.squad_values else self._load_values()
        if not values:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")

        home_value = values.get(team_a)
        away_value = values.get(team_b)

        all_values = list(values.values())
        median = sorted(all_values)[len(all_values) // 2] if all_values else 500.0

        if home_value is None:
            home_value = median
        if away_value is None:
            away_value = median

        log_home = math.log(home_value)
        log_away = math.log(away_value)
        total_log = log_home + log_away

        if total_log <= 0:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        home_prob = log_home / total_log
        diff_ratio = min(abs(log_home - log_away) / total_log, 0.5)
        draw_prob = max(0.0, (1.0 - diff_ratio * 2.0) * 0.33)
        normalized_home = home_prob * (1.0 - draw_prob)
        away_prob = 1.0 - normalized_home - draw_prob

        return SignalOutput(normalized_home, draw_prob, away_prob)
