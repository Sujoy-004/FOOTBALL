"""Market odds ingestion — re-exports from football_core.

DEPRECATED — use football_core.signals.market_odds.MarketOddsSignal instead.
Kept for backward compatibility with legacy refresh_from_api()."""

import logging

from football_core.predictors.odds import (
    remove_vig,
    _odds_available,
    _extract_group_letter_from_event,
    parse_odds_response,
    fetch_and_cache_odds as _core_fetch_and_cache_odds,
)

logger = logging.getLogger(__name__)


def fetch_and_cache_odds(
    api_key: str,
    bsd_events: list[dict],
    alias_lookup: dict[str, str],
    groups: dict,
    cache_ttl_hours: int = 12,
    bracket: list[dict] | None = None,
) -> dict:
    result = _core_fetch_and_cache_odds(
        api_key, bsd_events, alias_lookup, groups,
        cache_ttl_hours=cache_ttl_hours, bracket=bracket,
    )
    return result
