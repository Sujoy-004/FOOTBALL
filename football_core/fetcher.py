"""Fetch and process live match results from BSD API — generic pipeline."""

import logging

from football_core.data_providers.bsd_provider import BSDDataProvider

logger = logging.getLogger(__name__)


def fetch_raw_matches(api_key: str, api_url: str, league_id: int, timeout: int = 10) -> list[dict]:
    """Thin wrapper — delegates to :class:`BSDDataProvider.fetch_matches`."""
    provider = BSDDataProvider(api_key, league_id=league_id)
    return provider.fetch_matches(url=api_url, league_id=league_id, timeout=timeout)



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

