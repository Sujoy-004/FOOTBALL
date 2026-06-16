"""Market odds ingestion from BSD events endpoint.

Extracts odds_home/odds_draw/odds_away from existing BSD events response,
removes bookmaker vigorish via 1/odds normalization, and caches the
resulting home-win probabilities with TTL expiry.

Threat model:
- T-13-01: Never log BSD_API_KEY directly. Use existing Authorization: Token header pattern.
- T-13-02: Type-check odds fields for null/missing/non-positive values before vig removal.
- T-13-03: Cache persistence delegated to state.py _atomic_write_json (tmpfile + os.replace).
"""

import logging
from datetime import datetime, timedelta, timezone

from src import constants
from src.fetcher import _find_bracket_match, _find_group_match, _normalize_team

logger = logging.getLogger(__name__)


def remove_vig(odds_home: float, odds_draw: float, odds_away: float) -> dict[str, float]:
    """Remove bookmaker vigorish from decimal odds via basic 1/odds normalization.

    Converts decimal odds (e.g., 1.85, 3.40, 4.50) to implied probabilities,
    then normalizes so they sum to exactly 1.0 ± floating point tolerance.

    Args:
        odds_home: Decimal odds for home win.
        odds_draw: Decimal odds for draw.
        odds_away: Decimal odds for away win.

    Returns:
        dict with keys 'home', 'draw', 'away' — normalized probabilities summing to 1.0.
    """
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
    """Check if all three odds fields are present, non-null, and positive.

    Args:
        event: BSD event dict with possible odds_home/draw/away keys.

    Returns:
        Tuple of (available: bool, reason: str or None).
    """
    for key in ("odds_home", "odds_draw", "odds_away"):
        val = event.get(key)
        if val is None:
            return False, "odds_not_available"
        if not isinstance(val, (int, float)) or val <= 0:
            return False, "odds_not_available"
    return True, None


def _extract_group_letter_from_event(event: dict) -> str | None:
    """Extract group letter from BSD event's group_name field.

    Args:
        event: BSD event dict with optional 'group_name' key.

    Returns:
        Single group letter (A-L) or None.
    """
    group_name = event.get("group_name")
    if not group_name:
        return None
    if not group_name.startswith("Group "):
        return None
    if len(group_name) < 7:
        return None
    letter = group_name[6]
    if letter not in "ABCDEFGHIJKL":
        return None
    return letter


def parse_odds_response(
    bsd_events: list[dict],
    alias_lookup: dict[str, str],
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict[str, dict]:
    """Parse BSD events response into match_id → odds probability mapping.

    For each non-finished event, normalizes team names, resolves the internal
    match_id (group or knockout), extracts and vig-removes odds, and returns
    a mapping from match_id to odds entry.

    Args:
        bsd_events: List of raw BSD API event dicts.
        alias_lookup: Mapping of team name variants to canonical names.
        groups: Groups dict for group match resolution.
        bracket: Optional bracket list for knockout match resolution.

    Returns:
        dict mapping match_id → {probability, timestamp, available, reason?}.
    """
    now = datetime.now(timezone.utc)
    result: dict[str, dict] = {}

    for event in bsd_events:
        if event.get("status") == "finished":
            continue

        home_name = event.get("home_team", "")
        away_name = event.get("away_team", "")
        home_norm = _normalize_team(home_name, alias_lookup)
        away_norm = _normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.debug("Skipping event %s: unmatchable teams %r vs %r",
                         event.get("id"), home_name, away_name)
            continue

        # Resolve match_id
        match_id: str | None = None
        group_letter = _extract_group_letter_from_event(event)

        if group_letter is not None:
            round_number = event.get("round_number", 0)
            match_id = _find_group_match(home_norm, away_norm, group_letter,
                                          round_number, groups)
        elif bracket is not None:
            match_id = _find_bracket_match(home_norm, away_norm, bracket)

        if match_id is None:
            logger.debug("Skipping event %s: no match_id found for %s vs %s",
                         event.get("id"), home_norm, away_norm)
            continue

        # Extract and validate odds
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
    """Full fetch → parse → cache pipeline for market odds.

    Parses BSD events via parse_odds_response and wraps in a cache dict
    with ISO timestamps for TTL-based expiry.

    Note: api_key parameter is accepted for API consistency with future
    signal modules (catboost.py) but is not used for odds — odds data
    is already embedded in the events response.

    Args:
        api_key: BSD API key (unused — odds extracted from existing events).
        bsd_events: List of BSD event dicts.
        alias_lookup: Team name alias lookup.
        groups: Groups dict for match resolution.
        cache_ttl_hours: Cache TTL in hours (default: 12).
        bracket: Optional bracket list for knockout match resolution.

    Returns:
        Cache dict with keys: fetched_at, expires_at, matches.
    """
    now = datetime.now(timezone.utc)
    parsed = parse_odds_response(bsd_events, alias_lookup, groups, bracket=bracket)

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
        "matches": parsed,
    }
