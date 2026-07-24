"""Manager-based signals — defensive quality + manager effect — DEPRECATED.

Use football_core.signals.defensive_quality.DefensiveQualitySignal and
football_core.signals.manager_effect.ManagerEffectSignal instead.
Kept for backward compatibility with legacy refresh_from_api()."""

import logging
from datetime import datetime, timedelta, timezone

from football_core.providers.manager import fetch_and_cache_managers
from football_core.signals.defensive_quality import compute_defensive_signal, compute_defensive_signal_for_match
from football_core.signals.manager_effect import compute_manager_signal, compute_manager_signal_for_match

logger = logging.getLogger(__name__)


def _all_match_ids(
    groups: dict,
    bracket: list[dict] | None,
) -> set[str]:
    """Collect all match IDs from groups and optional bracket."""
    mids: set[str] = set()
    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups
    for gd in groups_data.values():
        for match in gd.get("matches") or []:
            mid = match.get("match_id")
            if mid:
                mids.add(mid)
    if bracket:
        for match in bracket:
            mid = match.get("match_id")
            if mid:
                mids.add(mid)
    return mids


def _unavailable_matches(match_ids: set[str]) -> dict[str, dict]:
    """Build a match dict with all entries marked unavailable."""
    return {mid: {"probability": None, "available": False} for mid in match_ids}


def fetch_and_cache_manager_signals(
    api_key: str,
    groups: dict,
    bracket: list[dict] | None = None,
    league_id: int = 27,
    cache_ttl_hours: int = 24,
) -> tuple[dict, dict]:
    """Fetch manager data and compute both defensive quality + manager effect.

    One API call serves both signals. Each signal gets its own cache dict
    matching the standard ``{fetched_at, expires_at, matches}`` schema.

    When manager data is empty (BSD blocked / unavailable), both caches
    return ``available: False`` for every match — the blender ignores them.

    Args:
        api_key: BSD API token.
        groups: Groups dict.
        bracket: Optional bracket match list.
        league_id: BSD league ID.
        cache_ttl_hours: Cache TTL for manager data.

    Returns:
        Tuple of (defensive_cache, manager_cache).
        Each cache has keys: fetched_at, expires_at, matches.
    """
    # Single API call — one fetch, two signals
    manager_cache = fetch_and_cache_managers(
        api_key, league_id=league_id, cache_ttl_hours=cache_ttl_hours,
    )
    manager_data = manager_cache.get("managers", {})

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=cache_ttl_hours)).isoformat()

    # Graceful degradation: no manager data → mark all matches unavailable
    if not manager_data:
        logger.warning("No manager data — returning unavailable defensive/manager signals")
        mid_set = _all_match_ids(groups, bracket)
        empty = {"fetched_at": now.isoformat(), "expires_at": expires_at, "matches": _unavailable_matches(mid_set)}
        return empty, empty

    defensive_matches = {}
    manager_matches = {}

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            defensive_matches[mid] = compute_defensive_signal_for_match(
                match["team_a"], match["team_b"], manager_data,
            )
            manager_matches[mid] = compute_manager_signal_for_match(
                match["team_a"], match["team_b"], manager_data,
            )

    if bracket:
        for match in bracket:
            if match.get("team_a") is None or match.get("team_b") is None:
                continue
            mid = match.get("match_id")
            if not mid:
                continue
            defensive_matches[mid] = compute_defensive_signal_for_match(
                match["team_a"], match["team_b"], manager_data,
            )
            manager_matches[mid] = compute_manager_signal_for_match(
                match["team_a"], match["team_b"], manager_data,
            )

    defensive_cache = {
        "fetched_at": now.isoformat(),
        "expires_at": expires_at,
        "matches": defensive_matches,
    }
    manager_cache_out = {
        "fetched_at": now.isoformat(),
        "expires_at": expires_at,
        "matches": manager_matches,
    }

    return defensive_cache, manager_cache_out
