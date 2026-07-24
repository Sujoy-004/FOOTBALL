"""Player data provider — fetches player profiles from BSD `/api/v2/players/`.

Returns structured PlayerProfile per player, consumed by the availability /
injury impact signal. Fetched once per TTL, cached by the orchestrator.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from football_core import constants
from football_core.data_providers.bsd_provider import BSDDataProvider
from football_core.providers.team import fetch_teams

logger = logging.getLogger(__name__)


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
    """Thin wrapper — delegates to :class:`BSDDataProvider.fetch_players`."""
    provider = BSDDataProvider(api_key, league_id=league_id)
    return provider.fetch_players(league_id=league_id, timeout=timeout or constants.API_TIMEOUT)


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
