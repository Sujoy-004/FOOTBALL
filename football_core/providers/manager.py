"""Manager data provider — fetches manager profiles from BSD `/api/managers/`.

Returns structured ManagerProfile per team, consumed by defensive quality
and manager effect signals. Fetched once per TTL, cached by the orchestrator.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

from football_core import constants

logger = logging.getLogger(__name__)

MANAGERS_API_URL: str = "https://sports.bzzoiro.com/api/managers/"


@dataclass
class ManagerProfile:
    name: str
    team: str
    win_pct: float = 0.0
    avg_goals_scored: float = 0.0
    avg_goals_conceded: float = 0.0
    avg_xg_for: float = 0.0
    avg_xg_against: float = 0.0
    clean_sheet_pct: float = 0.0
    btts_pct: float = 0.0
    over_25_pct: float = 0.0
    avg_possession: float = 0.0
    preferred_formation: str = ""
    formations_used: list[str] = field(default_factory=list)
    team_style: str = ""
    pressing_intensity: str = ""
    defensive_line: str = ""
    profile: str = ""


def fetch_managers(
    api_key: str,
    league_id: int = 27,
    timeout: int | None = None,
) -> list[dict]:
    """Fetch raw manager data from BSD `/api/managers/`.

    Args:
        api_key: BSD API token.
        league_id: BSD league ID (default 27 = World Cup 2026).
        timeout: Request timeout in seconds.

    Returns:
        Raw list of manager dicts from the API.

    Raises:
        requests.RequestException: On HTTP or connection failure after retries.
    """
    if timeout is None:
        timeout = constants.API_TIMEOUT

    url = f"{MANAGERS_API_URL}?league={league_id}"
    headers = {"Authorization": f"Token {api_key}"}
    backoff_seconds = [1, 2, 4]

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 401:
                logger.warning("HTTP 401 fetching managers, returning []")
                return []
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not isinstance(results, list):
                logger.warning("Unexpected managers response format: %s", type(results))
                return []
            return results
        except requests.exceptions.Timeout:
            logger.warning("Managers request timed out (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            raise
        except requests.exceptions.ConnectionError:
            logger.warning("Managers connection error (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            raise
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            logger.warning("Managers malformed JSON, returning []")
            return []

    return []


def parse_managers(raw_managers: list[dict]) -> dict[str, ManagerProfile]:
    """Parse raw BSD manager data into team-keyed ManagerProfile dict.

    Args:
        raw_managers: Raw list from fetch_managers().

    Returns:
        Dict mapping team name → ManagerProfile.
    """
    result: dict[str, ManagerProfile] = {}

    for m in raw_managers:
        if not isinstance(m, dict):
            continue

        team_data = m.get("current_team")
        if isinstance(team_data, dict):
            team_name = team_data.get("name", "")
        elif isinstance(team_data, str):
            team_name = team_data
        else:
            continue

        if not team_name:
            continue

        profile = ManagerProfile(
            name=m.get("name", ""),
            team=team_name,
            win_pct=_safe_float(m, "win_pct"),
            avg_goals_scored=_safe_float(m, "avg_goals_scored"),
            avg_goals_conceded=_safe_float(m, "avg_goals_conceded"),
            avg_xg_for=_safe_float(m, "avg_xg_for"),
            avg_xg_against=_safe_float(m, "avg_xg_against"),
            clean_sheet_pct=_safe_float(m, "clean_sheet_pct"),
            btts_pct=_safe_float(m, "btts_pct"),
            over_25_pct=_safe_float(m, "over_25_pct"),
            avg_possession=_safe_float(m, "avg_possession"),
            preferred_formation=m.get("preferred_formation", ""),
            formations_used=m.get("formations_used", []),
            team_style=m.get("team_style", ""),
            pressing_intensity=m.get("pressing_intensity", ""),
            defensive_line=m.get("defensive_line", ""),
            profile=m.get("profile", ""),
        )
        result[team_name] = profile

    return result


def fetch_and_cache_managers(
    api_key: str,
    league_id: int = 27,
    cache_ttl_hours: int = 24,
) -> dict:
    """Fetch and cache manager data in the standard cache-dict format.

    Returns:
        Cache dict with keys: fetched_at, expires_at, managers (parsed profiles).
    """
    now = datetime.now(timezone.utc)
    try:
        raw = fetch_managers(api_key, league_id=league_id)
        parsed = parse_managers(raw)
        logger.info("Fetched %d manager profiles for league %d", len(parsed), league_id)
        return {
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
            "managers": {k: _profile_to_dict(v) for k, v in parsed.items()},
        }
    except Exception:
        logger.warning("Failed to fetch manager data, returning empty cache", exc_info=True)
        return {
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
            "managers": {},
        }


def _safe_float(d: dict, key: str) -> float:
    val = d.get(key)
    if val is not None and isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _profile_to_dict(p: ManagerProfile) -> dict:
    return {
        "name": p.name,
        "team": p.team,
        "win_pct": p.win_pct,
        "avg_goals_scored": p.avg_goals_scored,
        "avg_goals_conceded": p.avg_goals_conceded,
        "avg_xg_for": p.avg_xg_for,
        "avg_xg_against": p.avg_xg_against,
        "clean_sheet_pct": p.clean_sheet_pct,
        "btts_pct": p.btts_pct,
        "over_25_pct": p.over_25_pct,
        "avg_possession": p.avg_possession,
        "preferred_formation": p.preferred_formation,
        "formations_used": p.formations_used,
        "team_style": p.team_style,
        "pressing_intensity": p.pressing_intensity,
        "defensive_line": p.defensive_line,
        "profile": p.profile,
    }
