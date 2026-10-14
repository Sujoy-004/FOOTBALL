"""Shared schema and constants for the historical UCL backfill.

Canonical naming follows the existing production conventions:
- team keys are exact strings from ``data/team_aliases.json`` and the
  non-league container used by ``competitions/ucl/data/seasons/*`` fixtures.
- match ids use the harness ``MD(\\d{2})_<idx>`` matchday-prefixed scheme;
  ``event_date`` remains the primary chronology per ``src/historical.py``.

Storage deviation (documented in PROVENANCE.json): the approved plan's
``data/seasons/<season>/`` path is the gitignored runtime season store, so
the git-trackable backfill lives under ``data/historical/<season>/``.

The competition-agnostic helpers (atomic JSON writes, id/duplicate checks,
season paths) live once in ``football_core.historical_backfill``; this module
is the UCL-flavoured view of them.
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
# D-01 window: every UCL season from 2000/01 through 2025/26 (26 entries,
# chronological iteration order). This is the single source of truth for the
# requested window; every consumer (results/odds adapters, build, evaluate)
# derives its season list from here rather than duplicating a literal.
#
# NOTE (honest coverage): the contract REQUESTS the full 2000/01-2025/26
# window, but no keyless results source (openfootball/champions-league) serves
# 2000/01-2010/11. Those seasons are excluded-and-reported by the build
# (see data/historical/COVERAGE.md) rather than silently dropped or fabricated.
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

# Old-format knockout mapping (pre-2024/25: R16/QF/SF/F single-knockout).
# Group-stage matchdays derive as 1..6 (the "group" entry is the legacy
# group-stage marker; the concrete matchday number comes from the fixture).
ROUND_MATCHDAY: dict[str, int] = {
    "group": 1,          # group-stage matchdays derive as 1..6
    "round of 16": 7,
    "quarter-final": 8,
    "quarter-finals": 8,
    "semi-final": 9,
    "semi-finals": 9,
    "final": 10,
}

# New-format (2024/25+) mapping: 36-team single league phase (matchdays 1..8),
# then a two-legged knockout play-off round (9/10), then R16/QF/SF/Final.
# The play-off matchday number is ``playoff + (N - 1)`` for "Playoffs, Matchday N".
ROUND_MATCHDAY_LEAGUE: dict[str, int] = {
    "league": 1,         # league-phase matchdays derive as 1..8
    "playoff": 9,
    "round of 16": 11,
    "quarter-final": 12,
    "quarter-finals": 12,
    "semi-final": 13,
    "semi-finals": 13,
    "final": 14,
}

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")

# The merged replay file is named for the window it actually CONTAINS (the
# seasons a keyless results source could be acquired for), not the window the
# contract requests. Every consumer resolves the name through this constant
# rather than a literal, so a widened corpus cannot silently leave a reader
# pointing at a stale dataset.
REPLAY_NAME = "replay_2011_12_2025_26.json"
REPLAY_PATH = os.path.join(HISTORICAL_DIR, REPLAY_NAME)


def md_match_id(matchday: int, index: int) -> str:
    """Matchday-prefixed id, e.g. MD06_03 -> 'MD06_03'."""
    return f"MD{matchday:02d}_{index:02d}"


season_dir = partial(_season_dir, HISTORICAL_DIR)

__all__ = [
    "DATA_DIR",
    "HISTORICAL_DIR",
    "REPLAY_NAME",
    "REPLAY_PATH",
    "ROUND_MATCHDAY",
    "ROUND_MATCHDAY_LEAGUE",
    "SCHEMA",
    "SEASONS",
    "duplicate_keys",
    "md_match_id",
    "read_json",
    "season_dir",
    "write_json",
    "year_key",
]
