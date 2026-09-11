"""Ensemble strategy selector + Market+Elo composite signal for UCL.

MarketEloSignal composites the market-odds signal with the refined-Elo
signal. When usable market odds are present they are blended with the Elo
probabilities using the configured weights and renormalized to sum to 1.
When they are absent the Elo probabilities pass through unchanged — no
fabricated odds are produced. Provenance of every predict() call is
recorded per instance and surfaced through last_provenance()/reset_provenance().

build_strategy_engine() is self-contained (no results_file/squad values) so
the market_elo candidate architectures can be A/B tested in isolation.
'production' stays in orchestrator.build_signal_engine().
"""

import copy
import json
import logging
import os

from football_core.blender import EnsembleEngine
from football_core.signal import PredictionContext, Signal, SignalOutput
from football_core.signals.market_odds import MarketOddsSignal
from football_core.signals.refined_elo import RefinedEloSignal

logger = logging.getLogger(__name__)

MARKET_ELO_EQUAL_WEIGHTS = {"market_odds": 0.5, "refined_elo": 0.5}

STRATEGIES = ("production", "market_elo_equal", "market_elo_prior")


def _get_config_dir() -> str:
    """Return absolute path to competitions/ucl/config/ directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
    )


PRIOR_WEIGHTS_PATH = os.path.join(_get_config_dir(), "market_elo_prior_weights.json")


class MarketEloSignal(Signal):
    """Composite of MarketOddsSignal and RefinedEloSignal with blend weights.

    With usable odds the weighted blend is renormalized to sum to 1; without
    them the Elo output is returned unchanged and the market is absent from
    the blend.
    """

    name = "market_elo"

    def __init__(self, weights: dict | None = None) -> None:
        default = MARKET_ELO_EQUAL_WEIGHTS if weights is None else weights
        self.weights = {k: v for k, v in default.items()}
        self._last_evidence: dict = {}

    @staticmethod
    def _usable_odds(match: dict) -> bool:
        odds_home = match.get("odds_home")
        odds_draw = match.get("odds_draw")
        odds_away = match.get("odds_away")
        return all(
            o is not None and isinstance(o, (int, float)) and o > 0
            for o in (odds_home, odds_draw, odds_away)
        )

    def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
        elo_out = RefinedEloSignal().predict(match, context)
        elo_probs = {
            "home": elo_out.home_prob,
            "draw": elo_out.draw_prob,
            "away": elo_out.away_prob,
        }

        if self._usable_odds(match):
            market_out = MarketOddsSignal().predict(match, context)
            market_probs = {
                "home": market_out.home_prob,
                "draw": market_out.draw_prob,
                "away": market_out.away_prob,
            }
            w_market = max(0.0, self.weights.get("market_odds", 0.0))
            w_elo = max(0.0, self.weights.get("refined_elo", 0.0))
            total_w = w_market + w_elo
            if total_w <= 0:
                w_market, w_elo = 0.5, 0.5
                total_w = 1.0
            applied = {"market_odds": w_market / total_w, "refined_elo": w_elo / total_w}
            blended = {
                "home": applied["market_odds"] * market_probs["home"]
                + applied["refined_elo"] * elo_probs["home"],
                "draw": applied["market_odds"] * market_probs["draw"]
                + applied["refined_elo"] * elo_probs["draw"],
                "away": applied["market_odds"] * market_probs["away"]
                + applied["refined_elo"] * elo_probs["away"],
            }
            total = blended["home"] + blended["draw"] + blended["away"]
            if total > 0:
                result = SignalOutput(
                    blended["home"] / total,
                    blended["draw"] / total,
                    blended["away"] / total,
                )
            else:
                result = elo_out
            usable = True
            used_signals = ["market_odds", "refined_elo"]
        else:
            market_probs = None
            result = elo_out
            usable = False
            used_signals = ["refined_elo"]
            applied = {"refined_elo": 1.0}

        self._last_evidence = {
            "usable_odds": usable,
            "market_odds": market_probs,
            "refined_elo": elo_probs,
            "used_signals": used_signals,
            "weights": applied,
        }
        return result

    def last_provenance(self) -> dict:
        """Return a deep copy of the most recent predict() evidence."""
        return copy.deepcopy(self._last_evidence)

    def reset_provenance(self) -> None:
        self._last_evidence = {}


def load_prior_weights() -> tuple[dict | None, str]:
    """Load strict-prior weights from PRIOR_WEIGHTS_PATH.

    Returns (weights, "market_elo_prior_weights.json") on success and
    (None, "equal_fallback") on any error. Never raises.
    """
    try:
        with open(PRIOR_WEIGHTS_PATH) as f:
            data = json.load(f)
        raw = data.get("weights") if isinstance(data, dict) else None
        if not isinstance(raw, dict) or not raw:
            return None, "equal_fallback"
        return (
            {k: float(v) for k, v in raw.items()},
            "market_elo_prior_weights.json",
        )
    except Exception:
        return None, "equal_fallback"


def build_strategy_engine(
    strategy: str,
    *,
    elo_ratings: dict[str, float],
    signal_weights_path: str | None = None,
) -> EnsembleEngine:
    """Build the Market+Elo EnsembleEngine for a candidate strategy.

    Self-contained for A/B tests: no results_file or squad values required.
    elo_ratings is accepted for call-shape compatibility with the production
    engine; the Market+Elo signal reads Elo from the PredictionContext at
    predict() time.
    """
    if strategy == "market_elo_equal":
        weights = dict(MARKET_ELO_EQUAL_WEIGHTS)
    elif strategy == "market_elo_prior":
        weights, source = load_prior_weights()
        if weights is None:
            logger.warning(
                "Prior weights unavailable from %s (%s) — using equal 0.5/0.5",
                PRIOR_WEIGHTS_PATH, source,
            )
            weights = dict(MARKET_ELO_EQUAL_WEIGHTS)
    else:
        raise ValueError(
            f"Unknown ensemble strategy {strategy!r} — build_strategy_engine "
            "supports only the market_elo candidates; use "
            "orchestrator.build_signal_engine for 'production'"
        )
    return EnsembleEngine([MarketEloSignal(weights)], weights={"market_elo": 1.0})