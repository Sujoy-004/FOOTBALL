"""CatBoost prediction ingestion — re-exports from football_core with WC ledger upsert."""

import logging

from football_core.predictors.catboost import (
    _normalize_prediction,
    _extract_probability,
    _extract_xg,
    _find_match_id,
    parse_catboost_response,
    predictions_url_for_league,
    fetch_and_cache_catboost as _core_fetch_and_cache_catboost,
)

logger = logging.getLogger(__name__)


def fetch_and_cache_catboost(
    api_key: str,
    alias_lookup: dict[str, str],
    groups: dict,
    bracket: list[dict],
    cache_ttl_hours: int = 24,
    league_id: int = 27,
) -> dict:
    result = _core_fetch_and_cache_catboost(
        api_key, alias_lookup, groups, bracket,
        cache_ttl_hours=cache_ttl_hours, league_id=league_id,
    )
    parsed = result.get("matches", {})
    if parsed:
        try:
            from src.state import ledger_upsert
            for mid, entry in parsed.items():
                ledger_upsert(mid, "catboost", entry)
        except Exception:
            logger.warning("Failed to upsert catboost into prediction ledger", exc_info=True)
    return result
