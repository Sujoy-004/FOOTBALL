"""ClubElo snapshot adapter for the historical LaLiga backfill.

Downloads the MIT-licensed ClubElo archive mirror
(https://github.com/xgabora/Club-Football-Match-Data) and computes for every
backfill season a ``canonical team key -> elo`` snapshot taken on the latest
date STRICTLY before that season's first match (guarantees pre-match,
leakage-free ratings for every match of the season). The first match date is
read from the football-data.co.uk SP1 source file (the LaLiga results source
of truth) so results and Elo share one kickoff chronology.

Entry point matches the build.py contract::

    elo: dict[str, dict[str, float]] = fetch_elo_snapshots()
        # season keyed "2019_20".."2023_24"; each mapping is
        # canonical team key -> ClubElo strength before the season's first
        # match.

Source notes:
- ClubElo is live at api.clubelo.com (unreachable from this environment);
  this adapter uses the xgabora mirror of the ClubElo archive (MIT license),
  which mirrors the historical daily ratings 1:1.
- Clubs that do not resolve to a canonical key are logged, not raised: the
  archive contains thousands of non-LaLiga clubs worldwide. Only teams that
  are actually used by the fixtures are trimmed/validated by build.py.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from typing import Dict

import pandas as pd
import requests

from football_core.historical_backfill import elo_snapshots, load_elo_frame

from competitions.laliga.historical_backfill.contract import FD_SEASON_URLS, SEASONS
from competitions.laliga.historical_backfill.sources.results_fd import (
    TMP_DIR,
    _download,
)
from competitions.laliga.historical_backfill.team_map import canonical

ELO_CSV = os.path.join(TMP_DIR, "EloRatings.csv")
ELO_URL = (
    "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data/"
    "master/data/EloRatings.csv"
)


# Module-level log filled by the last fetch_elo_snapshots() call.
unresolved_clubs: list[str] = []


def _first_match_date(season: str) -> date:
    """First actual match date for a season, from the SP1 source file."""
    path = _download(
        FD_SEASON_URLS[season], os.path.join(TMP_DIR, f"SP1_{season}.csv")
    )
    df = pd.read_csv(path)
    dates = pd.to_datetime(df["Date"], format="%d/%m/%Y")
    return dates.min().date()


def _load_elo_frame(path: str) -> pd.DataFrame:
    return load_elo_frame(path)


def fetch_elo_snapshots() -> Dict[str, Dict[str, float]]:
    global unresolved_clubs
    csv_path = _download(ELO_URL, ELO_CSV)
    frame = _load_elo_frame(csv_path)

    def _resolve(club: str) -> str | None:
        try:
            return canonical(club)
        except KeyError:
            return None

    snapshots, unresolved_clubs = elo_snapshots(
        frame, SEASONS, _first_match_date, _resolve
    )
    return snapshots


if __name__ == "__main__":
    data = fetch_elo_snapshots()
    print()
    print("unresolved clubs:", ", ".join(unresolved_clubs))