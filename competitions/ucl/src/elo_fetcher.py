"""ClubElo API fetcher for UCL team Elo ratings.

Provides cached fetching of Elo ratings from api.clubelo.com for all 36 UCL
teams.  Team name → ClubElo slug resolution uses the team_aliases.json file.

Per D-01 through D-05:
- D-01: ClubElo (api.clubelo.com) as Elo rating source
- D-02: Fetch all 36 teams' ratings once before simulation starts
- D-03: Cache fetched ratings for the entire simulation run
- D-04: Record the ClubElo snapshot date in simulation output
- D-05: Refresh policy is configurable per-run (not within a run)

Fetch strategy
--------------
Rather than making 36 individual HTTP requests (one per team), this module
issues a *single* request to the ClubElo date-based ranking endpoint:

    http://api.clubelo.com/YYYY-MM-DD

which returns a CSV of all clubs ranked on that date.  The Elo for each team
is extracted by looking up its ClubElo name (from the alias file) in the
ranking dict.  This is faster, more reliable, and aligns with D-02.
"""

from __future__ import annotations

import csv
import functools
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import date

from football_core.constants import DEFAULT_ELO

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

_API_BASE = "http://api.clubelo.com"


# ── Alias resolution ────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _load_aliases(alias_path: str | None = None) -> dict[str, list[str]]:
    """Load the team alias mapping from a JSON file.

    The file is expected to map internal team names to a list of aliases
    where the first entry is the ClubElo display name used in the ranking CSV.

    Results are cached so the file is read at most once per run.
    """
    if alias_path is None:
        alias_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "team_aliases.json",
        )
    with open(alias_path) as f:
        return json.load(f)


def resolve_clubelo_name(team_name: str, alias_path: str | None = None) -> str:
    """Resolve an internal team name to a ClubElo display name.

    Looks up *team_name* in the alias dictionary.  The first alias
    for a team is the ClubElo display name used in the ranking CSV.
    Falls back to *team_name* itself if not found in the alias file.
    """
    aliases = _load_aliases(alias_path)
    team_aliases = aliases.get(team_name)
    if team_aliases and len(team_aliases) > 0:
        return team_aliases[0]
    return team_name


# ── Ranking fetching ─────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _fetch_ranking_csv(snapshot_date: str) -> str:
    """Fetch the ClubElo ranking CSV for *snapshot_date*.

    Results are cached so the ranking is fetched at most once per run
    (D-03).
    """
    url = f"{_API_BASE}/{snapshot_date}"
    logger.debug("Fetching ClubElo ranking from %s", url)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read().decode("utf-8")


def _parse_ranking_csv(csv_text: str) -> dict[str, float]:
    """Parse a ClubElo ranking CSV into ``{Club name: Elo}`` lookup."""
    ranking: dict[str, float] = {}
    reader = csv.DictReader(line for line in csv_text.splitlines() if line.strip())
    for row in reader:
        club = row.get("Club", "")
        try:
            ranking[club] = float(row["Elo"])
        except (ValueError, KeyError):
            continue
    return ranking


def fetch_team_elos(
    team_names: list[str],
    alias_path: str | None = None,
    delay: float = 0.0,
) -> dict[str, float]:
    """Fetch Elo ratings for all *team_names* from ClubElo.

    Issues a single HTTP request to the ClubElo date-based ranking endpoint
    (``api.clubelo.com/YYYY-MM-DD``), then looks up each team by its ClubElo
    display name (resolved via :func:`resolve_clubelo_name`).

    The ranking is cached so subsequent calls return immediately without
    making additional HTTP requests (D-03).

    Parameters
    ----------
    team_names:
        List of internal team names to resolve and look up.
    alias_path:
        Path to the ``team_aliases.json`` file.  Defaults to
        ``competitions/ucl/data/team_aliases.json``.
    delay:
        Ignored (kept for backward compatibility with the per-team design).

    Returns
    -------
    dict[str, float]
        Mapping of *team_name* → Elo rating.  Teams not found in the
        ranking (unranked or unresolved) get ``DEFAULT_ELO`` (1500).
    """
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
            logger.warning(
                "ClubElo name '%s' (for team '%s') not found in ranking — "
                "falling back to DEFAULT_ELO=%d",
                clubelo_name, team_name, DEFAULT_ELO,
            )
            elos[team_name] = float(DEFAULT_ELO)

    return elos


# ── Snapshot date ───────────────────────────────────────────────────────────


def get_clubelo_snapshot_date() -> str:
    """Return today's date as ``YYYY-MM-DD`` (D-04)."""
    return date.today().isoformat()
