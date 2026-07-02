"""Player data provider — fetches player profiles from BSD `/api/v2/players/`.

Returns structured PlayerProfile per player, consumed by the availability /
injury impact signal. Fetched once per TTL, cached by the orchestrator.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

from football_core import constants
from football_core.providers.team import fetch_teams

logger = logging.getLogger(__name__)

PLAYERS_API_URL: str = "https://sports.bzzoiro.com/api/v2/players/"


@dataclass
class PlayerProfile:
    name: str
    team: str
    position: str = ""
    rating: float = 0.0
    availability: str = "available"
    injury_risk: str = "Low"
    market_value_eur: float = 0.0


def fetch_players(
    api_key: str,
    league_id: int = 27,
    timeout: int | None = None,
) -> list[dict]:
    """Fetch raw player data from BSD `/api/v2/players/`.

    Args:
        api_key: BSD API token.
        league_id: BSD league ID (default 27 = World Cup 2026).
        timeout: Request timeout in seconds.

    Returns:
        Raw list of player dicts from the API (paginated).

    Raises:
        requests.RequestException: On HTTP or connection failure after retries.
    """
    if timeout is None:
        timeout = constants.API_TIMEOUT

    url = f"{PLAYERS_API_URL}?league_id={league_id}&limit=200"
    headers = {"Authorization": f"Token {api_key}"}
    backoff_seconds = [1, 2, 4]

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 401:
                logger.warning("HTTP 401 fetching players, returning []")
                return []
            resp.raise_for_status()
            data = resp.json()
            all_players: list[dict] = list(data.get("results", []))

            next_url = data.get("next")
            while next_url:
                resp = requests.get(next_url, headers=headers, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                all_players.extend(data.get("results", []))
                next_url = data.get("next")

            return all_players
        except requests.exceptions.Timeout:
            logger.warning("Players request timed out (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            raise
        except requests.exceptions.ConnectionError:
            logger.warning("Players connection error (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            raise
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            logger.warning("Players malformed JSON, returning []")
            return []

    return []


def parse_players(
    raw_players: list[dict],
    team_map: dict[int, str] | None = None,
) -> dict[str, list[PlayerProfile]]:
    """Parse raw BSD player data into team-keyed list of PlayerProfile.

    Args:
        raw_players: Raw list from fetch_players().
        team_map: Optional dict mapping current_team_id → team name.
                  When provided, extracted from ``current_team_id``.
                  When absent, falls back to the legacy ``team`` field.

    Returns:
        Dict mapping team name → list of PlayerProfile for that team.
    """
    teams: dict[str, list[PlayerProfile]] = {}

    for p in raw_players:
        if not isinstance(p, dict):
            continue

        if team_map:
            tid = p.get("national_team_id")
            team_name = team_map.get(tid) if isinstance(tid, int) else None
        else:
            team_data = p.get("team")
            if isinstance(team_data, dict):
                team_name = team_data.get("name", "")
            elif isinstance(team_data, str):
                team_name = team_data
            else:
                continue

        if not team_name:
            continue

        profile = PlayerProfile(
            name=p.get("name", ""),
            team=team_name,
            position=p.get("position", ""),
            rating=_safe_float(p, "rating"),
            availability=p.get("availability", "available"),
            injury_risk=p.get("injury_risk", "Low"),
            market_value_eur=_safe_float(p, "market_value_eur"),
        )
        teams.setdefault(team_name, []).append(profile)

    return teams


def fetch_and_cache_players(
    api_key: str,
    league_id: int = 27,
    cache_ttl_hours: int = 6,
    team_map: dict[int, str] | None = None,
) -> dict:
    """Fetch and cache player data in the standard cache-dict format.

    Uses a shorter TTL (6h) because player availability changes rapidly
    (match-day squad announcements, late fitness tests).

    Args:
        api_key: BSD API token.
        league_id: BSD league ID.
        cache_ttl_hours: Cache validity in hours.
        team_map: Optional dict mapping current_team_id → team name.
                  Fetched from BSD if not provided and needed.

    Returns:
        Cache dict with keys: fetched_at, expires_at, players (team-keyed profiles).
    """
    now = datetime.now(timezone.utc)
    try:
        raw = fetch_players(api_key, league_id=league_id)
        if not raw:
            return {
                "fetched_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
                "players": {},
            }
        if team_map is None:
            team_map = fetch_teams(api_key, league_id=league_id)
        parsed = parse_players(raw, team_map=team_map)
        total = sum(len(v) for v in parsed.values())
        logger.info("Fetched %d players across %d teams for league %d", total, len(parsed), league_id)
        return {
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
            "players": {
                team: [_profile_to_dict(p) for p in profiles]
                for team, profiles in parsed.items()
            },
        }
    except Exception:
        logger.warning("Failed to fetch player data, returning empty cache", exc_info=True)
        return {
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
            "players": {},
        }


def _safe_float(d: dict, key: str) -> float:
    val = d.get(key)
    if val is not None and isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _profile_to_dict(p: PlayerProfile) -> dict:
    return {
        "name": p.name,
        "team": p.team,
        "position": p.position,
        "rating": p.rating,
        "availability": p.availability,
        "injury_risk": p.injury_risk,
        "market_value_eur": p.market_value_eur,
    }
