"""Market odds signal — BSD odds with vig removal as match probabilities."""

import logging

from football_core.predictors.odds import remove_vig
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)


class MarketOddsSignal(Signal):
    """Market-implied probabilities from BSD odds with vig removal.
    Provides a calibration baseline and independent signal."""

    name: str = "market_odds"

    def __init__(self, fallback_uniform: bool = True) -> None:
        self._fallback_uniform = fallback_uniform

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        odds_home = match.get("odds_home")
        odds_draw = match.get("odds_draw")
        odds_away = match.get("odds_away")

        if (
            odds_home is not None
            and odds_draw is not None
            and odds_away is not None
            and isinstance(odds_home, (int, float))
            and isinstance(odds_draw, (int, float))
            and isinstance(odds_away, (int, float))
            and odds_home > 0
            and odds_draw > 0
            and odds_away > 0
        ):
            probs = remove_vig(odds_home, odds_draw, odds_away)
            return SignalOutput(
                home_prob=probs["home"],
                draw_prob=probs["draw"],
                away_prob=probs["away"],
            )

        logger.debug(
            "Missing or invalid odds for match %s — returning uniform",
            match.get("match_id", "unknown"),
        )
        return SignalOutput(1 / 3, 1 / 3, 1 / 3)
