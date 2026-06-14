"""Fetch and process live match results from Football-Data.org API."""

import json
import logging
import time

import requests

from src import constants

logger = logging.getLogger(__name__)


def fetch_raw_matches(api_key: str, api_url: str = "", timeout: int = 10) -> list[dict]:
    if not api_url:
        api_url = constants.API_URL
    if timeout == 10:
        timeout = constants.API_TIMEOUT

    headers = {"Authorization": f"Token {api_key}"}
    backoff_seconds = [1, 2, 4]

    for attempt in range(3):
        try:
            resp = requests.get(api_url, headers=headers, timeout=timeout)

            if resp.status_code == 401:
                logger.warning("HTTP 401 (invalid API key), returning []")
                return []

            resp.raise_for_status()
            data = resp.json()
            all_events = list(data.get("results", []))

            next_url = data.get("next")
            while next_url:
                resp = requests.get(next_url, headers=headers, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                all_events.extend(data.get("results", []))
                next_url = data.get("next")

            return all_events

        except requests.exceptions.Timeout:
            logger.warning("Request timed out (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            return []

        except requests.exceptions.ConnectionError:
            logger.warning("Connection error (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            return []

        except requests.exceptions.HTTPError:
            logger.warning("HTTP error (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            return []

        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            logger.warning("Malformed JSON response, returning []")
            return []

    return []


def process_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    bracket: list[dict],
    aliases: dict[str, list[str]],
    played_ids: set[str],
) -> list[dict]:
    alias_lookup = _build_alias_lookup(aliases, bracket)
    results: list[dict] = []

    for match in raw_matches:
        if match.get("status") != "finished":
            continue

        match_id = str(match.get("id", ""))
        if match_id in played_ids:
            continue

        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")

        home_norm = _normalize_team(home_name, alias_lookup)
        away_norm = _normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.warning("Unmatchable team names: home=%r, away=%r", home_name, away_name)
            continue

        bracket_id = _find_bracket_match(home_norm, away_norm, bracket)
        if bracket_id is None:
            logger.warning("No bracket match found for %s vs %s", home_norm, away_norm)
            continue

        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)

        if home_score > away_score:
            winner = home_norm
        elif away_score > home_score:
            winner = away_norm
        else:
            continue

        results.append({
            "match_id": bracket_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "home_score": home_score,
            "away_score": away_score,
            "completed_at": match.get("event_date", ""),
        })

    return results


def _build_alias_lookup(aliases: dict[str, list[str]], bracket: list[dict]) -> dict[str, str]:
    lookup: dict[str, str] = {}

    for match in bracket:
        if match.get("team_a"):
            lookup[match["team_a"].strip().lower()] = match["team_a"]
        if match.get("team_b"):
            lookup[match["team_b"].strip().lower()] = match["team_b"]

    for canonical, variants in aliases.items():
        lookup[canonical.strip().lower()] = canonical
        for variant in variants:
            lookup[variant.strip().lower()] = canonical

    return lookup


def _normalize_team(api_name: str, alias_lookup: dict[str, str]) -> str | None:
    return alias_lookup.get(api_name.strip().lower())


def _find_bracket_match(home_norm: str, away_norm: str, bracket: list[dict]) -> str | None:
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        if {match["team_a"], match["team_b"]} == {home_norm, away_norm}:
            return match["match_id"]
    return None


def _extract_group_letter(group_name: str) -> str | None:
    """Extract group letter from 'Group A' -> 'A'. Returns None if invalid."""
    if not group_name or not group_name.startswith("Group "):
        return None
    if len(group_name) != 7:
        return None
    letter = group_name[6:7]  # "Group A" -> "A"
    if not letter or letter not in "ABCDEFGHIJKL":
        return None
    return letter


def _find_group_match(
    home_norm: str,
    away_norm: str,
    group_letter: str,
    round_number: int,
    groups: dict,
) -> str | None:
    """Find group match_id by team pair within a group.

    Mirrors _find_bracket_match() at line 150. Uses team pair set equality
    to resolve the match slot. The round_number parameter is available for
    additional filtering if needed in future data versions.

    Args:
        home_norm: Normalized home team name.
        away_norm: Normalized away team name.
        group_letter: Single letter group identifier (A-L).
        round_number: BSD API round_number field (1-6), reserved for future use.
        groups: Groups dict from groups.json.

    Returns:
        Match ID string (e.g. "GS_A_01") or None if not found.
    """
    groups_data = groups.get("groups", groups)
    if group_letter not in groups_data:
        return None
    for match in groups_data[group_letter]["matches"]:
        if {match["team_a"], match["team_b"]} == {home_norm, away_norm}:
            return match["match_id"]
    return None


def process_group_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    groups: dict,
    aliases: dict[str, list[str]],
    played_group_ids: set[str],
    played_bsd_event_ids: set[str],
) -> list[dict]:
    """Process BSD API events with non-null group_name into group match results.

    Filters finished events from the BSD API that have a group_name field,
    normalizes team names (using alias_lookup + group team names), resolves
    group match slots, deduplicates by BSD event id and match_id, and
    returns a list of new match result entries.

    Per D-01 through D-06, D-19 from the Phase 10 context:
    - Skip knockout events (group_name is None)
    - Skip draws (no winner)
    - Log warnings for unmatchable teams, invalid group letters, unfindable slots
    - Dedup via BSD event id (session-level) and match_id (cross-restart)

    Args:
        raw_matches: List of raw BSD API event dicts.
        teams: Dict mapping team name to team data (unused here, kept for
               signature consistency with process_matches).
        groups: Groups dict from groups.json (with or without "groups" wrapper).
        aliases: Team alias mapping from team_aliases.json.
        played_group_ids: Set of match_ids already in played_groups (cross-restart dedup).
        played_bsd_event_ids: Set of BSD event ids seen this session (in-memory dedup).

    Returns:
        List of new match entry dicts with keys: match_id, team_a, team_b,
        winner, home_score, away_score, completed_at.
    """
    # Build alias lookup that also includes all group team names (Pitfall 2 guard)
    alias_lookup = _build_alias_lookup(aliases, [])  # empty bracket for knockout
    groups_data = groups.get("groups", groups)
    for group_data in groups_data.values():
        for team in group_data.get("teams", []):
            alias_lookup[team.strip().lower()] = team

    results: list[dict] = []

    for match in raw_matches:
        if match.get("status") != "finished":
            continue

        group_name = match.get("group_name")
        if group_name is None:
            continue  # knockout match, handled by process_matches()

        # Dedup by BSD event id (session-level, per A5)
        bsd_id = str(match.get("id", ""))
        if bsd_id in played_bsd_event_ids:
            continue
        played_bsd_event_ids.add(bsd_id)

        # Extract group letter from "Group A" -> "A" (D-02)
        group_letter = _extract_group_letter(group_name)
        if group_letter is None:
            logger.warning("Invalid group_name: %r", group_name)
            continue

        # Normalize team names
        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")
        home_norm = _normalize_team(home_name, alias_lookup)
        away_norm = _normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.warning(
                "Unmatchable team names: home=%r, away=%r", home_name, away_name
            )
            continue

        # Find group match slot (D-03)
        round_number = match.get("round_number", 0)
        match_id = _find_group_match(
            home_norm, away_norm, group_letter, round_number, groups
        )
        if match_id is None:
            logger.warning(
                "No group match found for %s vs %s in group %s (round %d)",
                home_norm, away_norm, group_letter, round_number,
            )
            continue

        # Dedup by match_id (cross-restart)
        if match_id in played_group_ids:
            continue

        # Check for winner (D-06: skip draws)
        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)
        if home_score > away_score:
            winner = home_norm
        elif away_score > home_score:
            winner = away_norm
        else:
            continue  # Draw — skip

        # Append entry per D-04 structure
        results.append({
            "match_id": match_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "home_score": home_score,
            "away_score": away_score,
            "completed_at": match.get("event_date", ""),
        })

    return results
