"""CatBoost prediction ingestion — re-exports from football_core.

DEPRECATED — use football_core.signals.catboost.CatBoostSignal instead.
Kept for backward compatibility with legacy refresh_from_api() in wc_app.py."""

import logging

from football_core.predictors.catboost import (
    _normalize_prediction,
    _extract_probability,
    _extract_xg,
    _find_match_id,
    parse_catboost_response,
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
    return result
