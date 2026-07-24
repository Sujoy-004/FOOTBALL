"""Fetch and process live match results from BSD API — generic pipeline."""

import logging

from football_core.data_providers.bsd_provider import BSDDataProvider

logger = logging.getLogger(__name__)


def fetch_raw_matches(api_key: str, api_url: str, league_id: int, timeout: int = 10) -> list[dict]:
    """Thin wrapper — delegates to :class:`BSDDataProvider.fetch_matches`."""
    provider = BSDDataProvider(api_key, league_id=league_id)
    return provider.fetch_matches(url=api_url, league_id=league_id, timeout=timeout)


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

        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.debug("Unmatchable team names: home=%r, away=%r", home_name, away_name)
            continue

        bracket_id = find_bracket_match(home_norm, away_norm, bracket)
        if bracket_id is None:
            logger.debug("No bracket match found for %s vs %s", home_norm, away_norm)
            continue

        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)

        if home_score > away_score:
            winner = home_norm
            is_draw = False
        elif away_score > home_score:
            winner = away_norm
            is_draw = False
        else:
            bsd_winner = match.get("winner")
            if bsd_winner:
                bsd_winner_lower = bsd_winner.strip().lower()
                home_lower = home_name.strip().lower()
                away_lower = away_name.strip().lower()
                if bsd_winner_lower == home_lower:
                    winner = home_norm
                elif bsd_winner_lower == away_lower:
                    winner = away_norm
                else:
                    winner = None
                is_draw = False
            else:
                winner = None
                is_draw = True

        entry: dict = {
            "match_id": bracket_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "is_draw": is_draw,
            "home_score": home_score,
            "away_score": away_score,
            "completed_at": match.get("event_date", ""),
        }
        results.append(entry)

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


def normalize_team(api_name: str, alias_lookup: dict[str, str]) -> str | None:
    key = api_name.strip().lower()
    result = alias_lookup.get(key)
    if result is not None:
        return result
    if "&" in key:
        alt = key.replace("&", "and").replace("  ", " ")
        return alias_lookup.get(alt)
    return None


def find_bracket_match(home_norm: str, away_norm: str, bracket: list[dict]) -> str | None:
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        if {match["team_a"], match["team_b"]} == {home_norm, away_norm}:
            return match["match_id"]
    return None


def _extract_group_letter(group_name: str) -> str | None:
    if not group_name or not group_name.startswith("Group "):
        return None
    if len(group_name) != 7:
        return None
    letter = group_name[6:7]
    if not letter or not letter.isalpha() or not letter.isupper():
        return None
    return letter


def find_group_match(
    home_norm: str,
    away_norm: str,
    group_letter: str,
    round_number: int,
    groups: dict,
) -> str | None:
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
    alias_lookup = _build_alias_lookup(aliases, [])
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
            continue

        bsd_id = str(match.get("id", ""))
        if bsd_id in played_bsd_event_ids:
            continue
        played_bsd_event_ids.add(bsd_id)

        group_letter = _extract_group_letter(group_name)
        if group_letter is None:
            logger.debug("Invalid group_name: %r", group_name)
            continue

        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            logger.debug(
                "Unmatchable team names: home=%r, away=%r", home_name, away_name
            )
            continue

        round_number = match.get("round_number", 0)
        match_id = find_group_match(
            home_norm, away_norm, group_letter, round_number, groups
        )
        if match_id is None:
            logger.debug(
                "No group match found for %s vs %s in group %s (round %d)",
                home_norm, away_norm, group_letter, round_number,
            )
            continue

        if match_id in played_group_ids:
            continue

        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)
        if home_score > away_score:
            winner = home_norm
            is_draw = False
        elif away_score > home_score:
            winner = away_norm
            is_draw = False
        else:
            winner = None
            is_draw = True

        entry: dict = {
            "match_id": match_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "is_draw": is_draw,
            "home_score": home_score,
            "away_score": away_score,
            "completed_at": match.get("event_date", ""),
        }
        results.append(entry)

    return results
