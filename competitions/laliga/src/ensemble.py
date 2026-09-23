"""LaLiga ensemble strategy selector.

build_strategy_engine() selects a headline EnsembleEngine for a candidate
strategy. The signal interfaces are the shared ``football_core`` contracts
(``football_core.blender.EnsembleEngine`` and
``football_core.signals.market_odds.MarketOddsSignal``); only the strategy
selection is league-owned. 'production' stays in
pipeline.build_signal_engine().
"""

from __future__ import annotations

from football_core.blender import EnsembleEngine

STRATEGIES = ("production", "market_only")


def build_strategy_engine(
    strategy: str,
    *,
    elo_ratings: dict[str, float] | None = None,
) -> EnsembleEngine:
    """Build the EnsembleEngine for a selectable LaLiga strategy.

    For 'market_only' the aggregate market odds are the sole predictive
    signal, so the engine is weighted ``{"market_odds": 1.0}``.
    ``elo_ratings`` is accepted for call-shape parity with the production
    engine but unused: MarketOddsSignal reads odds from the match dict.
    """
    if strategy == "market_only":
        from football_core.signals.market_odds import MarketOddsSignal

        return EnsembleEngine([MarketOddsSignal()], weights={"market_odds": 1.0})
    raise ValueError(
        f"Unknown ensemble strategy {strategy!r} — build_strategy_engine "
        "supports only 'market_only'; use pipeline.build_signal_engine "
        "for 'production'"
    )