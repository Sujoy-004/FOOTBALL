"""Manager-based signals — defensive quality + manager effect.

WC-specific orchestration layer. Fetches manager data once via
football_core.providers.manager, then computes both signals,
persists to prediction ledger, and returns cache dicts.
"""

import logging
from datetime import datetime, timedelta, timezone

from football_core.providers.manager import fetch_and_cache_managers
from football_core.signals.defensive_quality import compute_defensive_signal, compute_defensive_signal_for_match
from football_core.signals.manager_effect import compute_manager_signal, compute_manager_signal_for_match

logger = logging.getLogger(__name__)


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

    # Persist to prediction ledger (batched — single load/save)
    if defensive_matches or manager_matches:
        try:
            from src.state import load_prediction_ledger, save_prediction_ledger
            ledger = load_prediction_ledger()
            for mid, entry in defensive_matches.items():
                if mid not in ledger:
                    ledger[mid] = {}
                ledger[mid]["defensive_quality"] = entry
            for mid, entry in manager_matches.items():
                if mid not in ledger:
                    ledger[mid] = {}
                ledger[mid]["manager_effect"] = entry
            save_prediction_ledger(ledger)
        except Exception:
            logger.warning("Failed to persist manager signals to prediction ledger", exc_info=True)

    return defensive_cache, manager_cache_out
