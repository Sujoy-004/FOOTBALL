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
# D-01 window: every LaLiga season from 2000/01 through 2025/26 (26 entries,
# chronological iteration order). This is the single source of truth for the
# committed corpus window; consumers (build, evaluate, the leakage audit) derive
# their season list from here rather than duplicating it.
SEASONS: dict[str, str] = {
    "2000_01": "2000/01",
    "2001_02": "2001/02",
    "2002_03": "2002/03",
    "2003_04": "2003/04",
    "2004_05": "2004/05",
    "2005_06": "2005/06",
    "2006_07": "2006/07",
    "2007_08": "2007/08",
    "2008_09": "2008/09",
    "2009_10": "2009/10",
    "2010_11": "2010/11",
    "2011_12": "2011/12",
    "2012_13": "2012/13",
    "2013_14": "2013/14",
    "2014_15": "2014/15",
    "2015_16": "2015/16",
    "2016_17": "2016/17",
    "2017_18": "2017/18",
    "2018_19": "2018/19",
    "2019_20": "2019/20",
    "2020_21": "2020/21",
    "2021_22": "2021/22",
    "2022_23": "2022/23",
    "2023_24": "2023/24",
    "2024_25": "2024/25",
    "2025_26": "2025/26",
}

# football-data.co.uk SP1 archive codes (single result + closing-odds source).
# Archive code is the two-digit start year followed by the two-digit end year
# (e.g. 2000/01 -> "0001", 2024/25 -> "2425").
FD_SEASON_URLS: dict[str, str] = {
    "2000_01": "https://www.football-data.co.uk/mmz4281/0001/SP1.csv",
    "2001_02": "https://www.football-data.co.uk/mmz4281/0102/SP1.csv",
    "2002_03": "https://www.football-data.co.uk/mmz4281/0203/SP1.csv",
    "2003_04": "https://www.football-data.co.uk/mmz4281/0304/SP1.csv",
    "2004_05": "https://www.football-data.co.uk/mmz4281/0405/SP1.csv",
    "2005_06": "https://www.football-data.co.uk/mmz4281/0506/SP1.csv",
    "2006_07": "https://www.football-data.co.uk/mmz4281/0607/SP1.csv",
    "2007_08": "https://www.football-data.co.uk/mmz4281/0708/SP1.csv",
    "2008_09": "https://www.football-data.co.uk/mmz4281/0809/SP1.csv",
    "2009_10": "https://www.football-data.co.uk/mmz4281/0910/SP1.csv",
    "2010_11": "https://www.football-data.co.uk/mmz4281/1011/SP1.csv",
    "2011_12": "https://www.football-data.co.uk/mmz4281/1112/SP1.csv",
    "2012_13": "https://www.football-data.co.uk/mmz4281/1213/SP1.csv",
    "2013_14": "https://www.football-data.co.uk/mmz4281/1314/SP1.csv",
    "2014_15": "https://www.football-data.co.uk/mmz4281/1415/SP1.csv",
    "2015_16": "https://www.football-data.co.uk/mmz4281/1516/SP1.csv",
    "2016_17": "https://www.football-data.co.uk/mmz4281/1617/SP1.csv",
    "2017_18": "https://www.football-data.co.uk/mmz4281/1718/SP1.csv",
    "2018_19": "https://www.football-data.co.uk/mmz4281/1819/SP1.csv",
    "2019_20": "https://www.football-data.co.uk/mmz4281/1920/SP1.csv",
    "2020_21": "https://www.football-data.co.uk/mmz4281/2021/SP1.csv",
    "2021_22": "https://www.football-data.co.uk/mmz4281/2122/SP1.csv",
    "2022_23": "https://www.football-data.co.uk/mmz4281/2223/SP1.csv",
    "2023_24": "https://www.football-data.co.uk/mmz4281/2324/SP1.csv",
    "2024_25": "https://www.football-data.co.uk/mmz4281/2425/SP1.csv",
    "2025_26": "https://www.football-data.co.uk/mmz4281/2526/SP1.csv",
}

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")

# The merged replay file is named for the window it actually contains. Every
# consumer resolves the name through these constants rather than a literal, so a
# widened corpus cannot silently leave a reader pointing at a stale dataset.
REPLAY_NAME = "replay_2000_01_2025_26.json"
REPLAY_PATH = os.path.join(HISTORICAL_DIR, REPLAY_NAME)


def match_id(season: str, index: int) -> str:
    """Stable unique match id, e.g. '2019_20_m001' (1-based by event_date)."""
    return f"{season}_m{index:03d}"


season_dir = partial(_season_dir, HISTORICAL_DIR)

__all__ = [
    "DATA_DIR",
    "FD_SEASON_URLS",
    "HISTORICAL_DIR",
    "REPLAY_NAME",
    "REPLAY_PATH",
    "SCHEMA",
    "SEASONS",
    "duplicate_keys",
    "match_id",
    "read_json",
    "season_dir",
    "write_json",
    "year_key",
]
