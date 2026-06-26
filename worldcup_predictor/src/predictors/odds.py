"""Market odds ingestion — re-exports from football_core with WC ledger upsert."""

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
    parsed = result.get("matches", {})
    if parsed:
        try:
            from src.state import ledger_upsert
            for mid, entry in parsed.items():
                ledger_upsert(mid, "market_odds", entry)
        except Exception:
            logger.warning("Failed to upsert market_odds into prediction ledger", exc_info=True)
    return result
