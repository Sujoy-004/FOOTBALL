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
SEASONS: dict[str, str] = {
    "2019_20": "2019/20",
    "2020_21": "2020/21",
    "2021_22": "2021/22",
    "2022_23": "2022/23",
    "2023_24": "2023/24",
}

# Old-format knockout mapping (pre-2024/25: R16/QF/SF/F single-knockout).
ROUND_MATCHDAY: dict[str, int] = {
    "group": 1,          # group-stage matchdays derive as 1..6
    "round of 16": 7,
    "quarter-final": 8,
    "quarter-finals": 8,
    "semi-final": 9,
    "semi-finals": 9,
    "final": 10,
}

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")


def md_match_id(matchday: int, index: int) -> str:
    """Matchday-prefixed id, e.g. MD06_03 -> 'MD06_03'."""
    return f"MD{matchday:02d}_{index:02d}"


season_dir = partial(_season_dir, HISTORICAL_DIR)

__all__ = [
    "DATA_DIR",
    "HISTORICAL_DIR",
    "ROUND_MATCHDAY",
    "SCHEMA",
    "SEASONS",
    "duplicate_keys",
    "md_match_id",
    "read_json",
    "season_dir",
    "write_json",
    "year_key",
]
