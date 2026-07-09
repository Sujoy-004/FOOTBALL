"""ClubElo API fetcher — competition-agnostic.

Provides cached fetching of Elo ratings from api.clubelo.com for any
list of team names.  Team name to ClubElo slug resolution uses a
team_aliases.json file supplied by the caller.

Fetch strategy
--------------
Primary: issues a *single* request to the ClubElo date-based ranking endpoint:

    http://api.clubelo.com/YYYY-MM-DD

which returns a CSV of all clubs ranked on that date.  The Elo for each team
is extracted by looking up its ClubElo name (from the alias file) in the
ranking dict.

Fallback: if a team is not found in the daily snapshot (e.g. its ranking
period has expired), the per-team history endpoint is queried:

    http://api.clubelo.com/{team_name}

which returns the team's full historical CSV.  The most recent Elo rating
is used.  This ensures teams with expired rankings still get a real value
rather than the DEFAULT_ELO fallback.
"""

from __future__ import annotations

import csv
import functools
import json
import logging
import time
import urllib.request
from datetime import date

from football_core.constants import DEFAULT_ELO

logger = logging.getLogger(__name__)

_API_BASE = "http://api.clubelo.com"


@functools.lru_cache(maxsize=1)
def _load_aliases(alias_path: str) -> dict[str, list[str]]:
    with open(alias_path) as f:
        return json.load(f)


def resolve_clubelo_name(team_name: str, alias_path: str) -> str:
    aliases = _load_aliases(alias_path)
    team_aliases = aliases.get(team_name)
    if team_aliases and len(team_aliases) > 0:
        return team_aliases[0]
    return team_name


@functools.lru_cache(maxsize=1)
def _fetch_ranking_csv(snapshot_date: str) -> str:
    url = f"{_API_BASE}/{snapshot_date}"
    logger.debug("Fetching ClubElo ranking from %s", url)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read().decode("utf-8")


def _parse_ranking_csv(csv_text: str) -> dict[str, float]:
    ranking: dict[str, float] = {}
    reader = csv.DictReader(line for line in csv_text.splitlines() if line.strip())
    for row in reader:
        club = row.get("Club", "")
        try:
            ranking[club] = float(row["Elo"])
        except (ValueError, KeyError):
            continue
    return ranking


@functools.lru_cache(maxsize=128)
def _fetch_team_history(clubelo_name: str) -> float | None:
    """Hit the per-team ClubElo endpoint and return the most recent Elo."""
    url = f"{_API_BASE}/{clubelo_name}"
    logger.debug("Fetching ClubElo team history from %s", url)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            csv_text = resp.read().decode("utf-8")
    except Exception:
        logger.warning("Failed to fetch ClubElo history for '%s'", clubelo_name)
        return None

    reader = csv.DictReader(line for line in csv_text.splitlines() if line.strip())
    latest_elo = None
    for row in reader:
        try:
            latest_elo = float(row["Elo"])
        except (ValueError, KeyError):
            continue
    return latest_elo


def fetch_team_elos(
    team_names: list[str],
    alias_path: str,
    delay: float = 0.0,
) -> dict[str, float]:
    snapshot_date = get_clubelo_snapshot_date()
    csv_text = _fetch_ranking_csv(snapshot_date)
    ranking = _parse_ranking_csv(csv_text)

    elos: dict[str, float] = {}
    for team_name in team_names:
        clubelo_name = resolve_clubelo_name(team_name, alias_path)
        elo = ranking.get(clubelo_name)
        if elo is not None:
            elos[team_name] = elo
        else:
            logger.info(
                "ClubElo name '%s' (for team '%s') not found in daily snapshot — "
                "trying per-team history endpoint",
                clubelo_name, team_name,
            )
            hist_elo = _fetch_team_history(clubelo_name)
            if hist_elo is not None:
                logger.info(
                    "Found historical Elo %.1f for '%s' (team '%s')",
                    hist_elo, clubelo_name, team_name,
                )
                elos[team_name] = hist_elo
            else:
                logger.warning(
                    "ClubElo name '%s' (for team '%s') not found in history either — "
                    "falling back to DEFAULT_ELO=%d",
                    clubelo_name, team_name, DEFAULT_ELO,
                )
                elos[team_name] = float(DEFAULT_ELO)

    return elos


def get_clubelo_snapshot_date() -> str:
    return date.today().isoformat()
