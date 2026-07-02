"""Team data provider — fetches team listings from BSD `/api/teams/`.

Provides team ID → name mapping consumed by player and other providers
that need to resolve ``current_team_id`` to a display name. Follows the
same cache-dict pattern as manager.py and player.py.
"""

import logging
from datetime import datetime, timedelta, timezone

import requests

from football_core import constants

logger = logging.getLogger(__name__)

TEAMS_API_URL: str = "https://sports.bzzoiro.com/api/teams/"


def fetch_teams(
    api_key: str,
    league_id: int = 27,
    timeout: int | None = None,
) -> dict[int, str]:
    """Fetch team listings from BSD and build ID→name mapping.

    Args:
        api_key: BSD API token.
        league_id: BSD league ID (default 27 = World Cup 2026).
        timeout: Request timeout in seconds.

    Returns:
        Dict mapping team ID → team name.
        Empty dict on failure.

    Raises:
        requests.RequestException: On HTTP or connection failure.
    """
    if timeout is None:
        timeout = constants.API_TIMEOUT

    url = f"{TEAMS_API_URL}?league={league_id}&limit=100"
    headers = {"Authorization": f"Token {api_key}"}

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 401:
            logger.warning("HTTP 401 fetching teams, returning empty map")
            return {}
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not isinstance(results, list):
            logger.warning("Unexpected teams response format: %s", type(results))
            return {}
        team_map: dict[int, str] = {}
        for t in results:
            tid = t.get("id")
            name = t.get("name")
            if tid is not None and name:
                team_map[int(tid)] = str(name)
        return team_map
    except requests.exceptions.Timeout:
        logger.warning("Teams request timed out")
        return {}
    except requests.exceptions.ConnectionError:
        logger.warning("Teams connection error")
        return {}
    except Exception:
        logger.warning("Failed to fetch team data, returning empty map", exc_info=True)
        return {}


def fetch_and_cache_teams(
    api_key: str,
    league_id: int = 27,
    cache_ttl_hours: int = 48,
) -> dict:
    """Fetch and cache team ID→name mapping in the standard cache-dict format.

    Team listings change rarely (between tournaments), so TTL is generous.

    Returns:
        Cache dict with keys: fetched_at, expires_at, team_map.
    """
    now = datetime.now(timezone.utc)
    try:
        team_map = fetch_teams(api_key, league_id=league_id)
        logger.info("Fetched %d teams for league %d", len(team_map), league_id)
        return {
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
            "team_map": {str(k): v for k, v in team_map.items()},
        }
    except Exception:
        logger.warning("Failed to fetch team data, returning empty cache", exc_info=True)
        return {
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
            "team_map": {},
        }
