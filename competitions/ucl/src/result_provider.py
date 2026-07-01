"""Match result providers for UCL — replay JSON file and BSD live fetch.

Both implement the MatchResultProvider Protocol from football_core.
ReplayMatchResultProvider loads from a local JSON file (replay mode).
BSDMatchResultProvider fetches from the BSD API (live mode).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from football_core.provider import MatchResultProvider

logger = logging.getLogger(__name__)


class ReplayMatchResultProvider:
    """Load played match results from a local JSON replay file.

    Expected JSON format (D-04):
        {"matches": [
            {"team_a": str, "team_b": str,
             "home_score": int, "away_score": int},
            ...
        ]}
    """

    def __init__(self, path: str) -> None:
        self._path = path

    def load(self) -> dict[tuple[str, str], tuple[int, int]]:
        """Load replay matches from JSON file (D-04 format).

        Returns dict keyed by (team_a, team_b) with (home_score, away_score).
        Both orientations stored for bidirectional lookup (D-02).

        Raises FileNotFoundError, json.JSONDecodeError on I/O errors.
        """
        with open(self._path) as f:
            data = json.load(f)

        played: dict[tuple[str, str], tuple[int, int]] = {}
        for match in data["matches"]:
            ta, tb = match["team_a"], match["team_b"]
            score = (match["home_score"], match["away_score"])
            played[(ta, tb)] = score
            played[(tb, ta)] = score

        logger.info("Loaded %d played matches from %s", len(played) // 2, self._path)
        return played


class BSDMatchResultProvider:
    """Fetch completed UCL match results from BSD API for live conditioning mode.

    Wraps the existing fetch_ucl_matches() from fetcher.py in the
    MatchResultProvider Protocol interface.
    """

    def __init__(
        self,
        api_key: str,
        team_aliases: dict[str, list[str]],
        fixtures_schedule: dict,
    ) -> None:
        self._api_key = api_key
        self._team_aliases = team_aliases
        self._fixtures_schedule = fixtures_schedule

    def load(self) -> dict[tuple[str, str], tuple[int, int]]:
        """Fetch completed BSD matches and convert to played_matches format.

        Uses fetch_ucl_matches() from fetcher.py (reuses Phase 4 code).
        Filters to completed matches only (winner is not None or is_draw).
        """
        from competitions.ucl.src.fetcher import fetch_ucl_matches

        bsd_results = fetch_ucl_matches(
            self._api_key, self._team_aliases, self._fixtures_schedule,
        )

        played: dict[tuple[str, str], tuple[int, int]] = {}
        for match in bsd_results:
            ta, tb = match["team_a"], match["team_b"]
            score = (match["home_score"], match["away_score"])
            played[(ta, tb)] = score
            played[(tb, ta)] = score

        logger.info("Converted %d BSD matches to played_matches", len(played) // 2)
        return played


def convert_bsd_matches(
    bsd_results: list[dict[str, Any]],
) -> dict[tuple[str, str], tuple[int, int]]:
    """Convert BSD fetch_ucl_matches() output to played_matches format.

    Standalone utility (not Protocol-implementing) — same conversion
    logic as BSDMatchResultProvider.load() but operates on pre-fetched data.

    BSD format (from fetcher.py):
        {"team_a": str, "team_b": str,
         "home_score": int, "away_score": int,
         "winner": str|None, "is_draw": bool, ...}
    """
    played: dict[tuple[str, str], tuple[int, int]] = {}
    for match in bsd_results:
        ta, tb = match["team_a"], match["team_b"]
        score = (match["home_score"], match["away_score"])
        played[(ta, tb)] = score
        played[(tb, ta)] = score

    logger.info("Converted %d BSD matches to played_matches", len(played) // 2)
    return played
