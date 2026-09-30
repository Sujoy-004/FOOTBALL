"""Shared schema and constants for the historical LaLiga backfill.

Canonical naming follows the existing production conventions:
- team keys are exact strings from ``data/team_aliases.json`` (the 2026/27
  long-form production keys preferred), plus a small stable set of keys for
  clubs absent from the production fixtures (see backfill/team_map.py).
- match ids use a season-scoped ``<season>_m<nnn>`` scheme; every match has a
  real ``event_date`` so ``event_date`` is the sole trustworthy chronology per
  src/historical.py (which is reused read-only from competitions.ucl).

Data sources: results + closing odds from the football-data.co.uk SP1 archive
(one file per season, exactly 380 matches for a 20-team double round-robin);
pre-season Elo snapshots from the MIT-licensed ClubElo archive mirror.

Storage deviation (documented in PROVENANCE.json): the approved plan's
``data/seasons/<season>/`` path is the gitignored runtime season store, so
the git-trackable backfill lives under ``data/historical/<season>/`` — the same
convention UCL established.

The competition-agnostic helpers (atomic JSON writes, id/duplicate checks,
season paths) live once in ``football_core.historical_backfill``; this module
is the LaLiga-flavoured view of them.
"""

from __future__ import annotations

import os
from functools import partial

from football_core.historical_backfill import (
    PROVENANCE_SCHEMA as SCHEMA,
    duplicate_keys,
    read_json,
    season_dir as _season_dir,
    write_json,
    year_key,
)

# Seasons to backfill: start year key -> label.
SEASONS: dict[str, str] = {
    "2019_20": "2019/20",
    "2020_21": "2020/21",
    "2021_22": "2021/22",
    "2022_23": "2022/23",
    "2023_24": "2023/24",
}

# football-data.co.uk SP1 archive codes (single result + closing-odds source).
FD_SEASON_URLS: dict[str, str] = {
    "2019_20": "https://www.football-data.co.uk/mmz4281/1920/SP1.csv",
    "2020_21": "https://www.football-data.co.uk/mmz4281/2021/SP1.csv",
    "2021_22": "https://www.football-data.co.uk/mmz4281/2122/SP1.csv",
    "2022_23": "https://www.football-data.co.uk/mmz4281/2223/SP1.csv",
    "2023_24": "https://www.football-data.co.uk/mmz4281/2324/SP1.csv",
}

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")


def match_id(season: str, index: int) -> str:
    """Stable unique match id, e.g. '2019_20_m001' (1-based by event_date)."""
    return f"{season}_m{index:03d}"


season_dir = partial(_season_dir, HISTORICAL_DIR)

__all__ = [
    "DATA_DIR",
    "FD_SEASON_URLS",
    "HISTORICAL_DIR",
    "SCHEMA",
    "SEASONS",
    "duplicate_keys",
    "match_id",
    "read_json",
    "season_dir",
    "write_json",
    "year_key",
]
