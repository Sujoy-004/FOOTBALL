"""Availability / Injury Impact signal — squad fitness from player data — DEPRECATED.

Use football_core.signals.availability.AvailabilitySignal instead.
Kept for backward compatibility with legacy refresh_from_api()."""

import logging
from datetime import datetime, timedelta, timezone

from football_core.providers.player import fetch_and_cache_players
from football_core.signals.availability import compute_availability_signal_for_match

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


def fetch_and_cache_availability_signal(
    api_key: str,
    groups: dict,
    bracket: list[dict] | None = None,
    league_id: int = 27,
    cache_ttl_hours: int = 6,
) -> dict:
    """Fetch player data and compute availability signal.

    When player data is empty (BSD blocked / unavailable), returns a cache
    with ``available: False`` for every match — the blender ignores it.

    Args:
        api_key: BSD API token.
        groups: Groups dict.
        bracket: Optional bracket match list.
        league_id: BSD league ID.
        cache_ttl_hours: Cache TTL for player data (default 6h — changes rapidly).

    Returns:
        Cache dict with keys: fetched_at, expires_at, matches.
    """
    player_cache = fetch_and_cache_players(
        api_key, league_id=league_id, cache_ttl_hours=cache_ttl_hours,
    )
    player_data = player_cache.get("players", {})

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=cache_ttl_hours)).isoformat()

    # Graceful degradation: no player data → mark all matches unavailable
    if not player_data:
        logger.warning("No player data — returning unavailable availability signal")
        mid_set = _all_match_ids(groups, bracket)
        return {"fetched_at": now.isoformat(), "expires_at": expires_at, "matches": _unavailable_matches(mid_set)}

    matches = {}

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            matches[mid] = compute_availability_signal_for_match(
                match["team_a"], match["team_b"], player_data,
            )

    if bracket:
        for match in bracket:
            if match.get("team_a") is None or match.get("team_b") is None:
                continue
            mid = match.get("match_id")
            if not mid:
                continue
            matches[mid] = compute_availability_signal_for_match(
                match["team_a"], match["team_b"], player_data,
            )

    cache = {
        "fetched_at": now.isoformat(),
        "expires_at": expires_at,
        "matches": matches,
    }

    return cache
