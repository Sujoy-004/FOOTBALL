"""Availability / Injury Impact signal — squad fitness from player data.

WC-specific orchestration layer. Fetches player data via
football_core.providers.player, computes availability signal,
persists to prediction ledger, and returns cache dict.
"""

import logging
from datetime import datetime, timedelta, timezone

from football_core.providers.player import fetch_and_cache_players
from football_core.signals.availability import compute_availability_signal_for_match

logger = logging.getLogger(__name__)


def fetch_and_cache_availability_signal(
    api_key: str,
    groups: dict,
    bracket: list[dict] | None = None,
    league_id: int = 27,
    cache_ttl_hours: int = 6,
) -> dict:
    """Fetch player data and compute availability signal.

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

    if matches:
        try:
            from src.state import load_prediction_ledger, save_prediction_ledger
            ledger = load_prediction_ledger()
            for mid, entry in matches.items():
                if mid not in ledger:
                    ledger[mid] = {}
                ledger[mid]["availability"] = entry
            save_prediction_ledger(ledger)
        except Exception:
            logger.warning("Failed to persist availability signal to prediction ledger", exc_info=True)

    return cache
