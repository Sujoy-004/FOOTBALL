"""Market odds ingestion from BSD events endpoint — generic."""
import logging
from datetime import datetime, timedelta, timezone

from football_core.fetcher import find_bracket_match, find_group_match, normalize_team

logger = logging.getLogger(__name__)


def remove_vig(odds_home: float, odds_draw: float, odds_away: float) -> dict[str, float]:
    p_home = 1.0 / odds_home
    p_draw = 1.0 / odds_draw
    p_away = 1.0 / odds_away
    total = p_home + p_draw + p_away
    return {
        "home": p_home / total,
        "draw": p_draw / total,
        "away": p_away / total,
    }


def _odds_available(event: dict) -> tuple[bool, str | None]:
    for key in ("odds_home", "odds_draw", "odds_away"):
        val = event.get(key)
        if val is None:
            return False, "odds_not_available"
        if not isinstance(val, (int, float)) or val <= 0:
            return False, "odds_not_available"
    return True, None


def _extract_group_letter_from_event(event: dict) -> str | None:
    group_name = event.get("group_name")
    if not group_name:
        return None
    if not group_name.startswith("Group "):
        return None
    if len(group_name) < 7:
        return None
    letter = group_name[6]
    if not letter.isalpha() or not letter.isupper():
        return None
    return letter


def parse_odds_response(
    bsd_events: list[dict],
    alias_lookup: dict[str, str],
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict[str, dict]:
    now = datetime.now(timezone.utc)
    result: dict[str, dict] = {}

    for event in bsd_events:
        if event.get("status") == "finished":
            continue

        home_name = event.get("home_team", "")
        away_name = event.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.debug("Skipping event %s: unmatchable teams %r vs %r",
                         event.get("id"), home_name, away_name)
            continue

        match_id: str | None = None
        group_letter = _extract_group_letter_from_event(event)

        if group_letter is not None:
            round_number = event.get("round_number", 0)
            match_id = find_group_match(home_norm, away_norm, group_letter,
                round_number, groups)
        else:
            match_id = find_bracket_match(home_norm, away_norm, bracket)

        if match_id is None:
            logger.debug("Skipping event %s: no match_id found for %s vs %s",
                         event.get("id"), home_norm, away_norm)
            continue

        available, reason = _odds_available(event)

        if available:
            odds_h = event["odds_home"]
            odds_d = event["odds_draw"]
            odds_a = event["odds_away"]
            probs = remove_vig(odds_h, odds_d, odds_a)
            result[match_id] = {
                "probability": probs["home"],
                "timestamp": now.isoformat(),
                "available": True,
            }
        else:
            result[match_id] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": reason,
            }

    return result


def fetch_and_cache_odds(
    api_key: str,
    bsd_events: list[dict],
    alias_lookup: dict[str, str],
    groups: dict,
    cache_ttl_hours: int = 12,
    bracket: list[dict] | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    parsed = parse_odds_response(bsd_events, alias_lookup, groups, bracket=bracket)
    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
        "matches": parsed,
    }
