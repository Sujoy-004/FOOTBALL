"""Shared schema and constants for the historical UCL backfill.

Canonical naming follows the existing production conventions:
- team keys are exact strings from ``data/team_aliases.json`` and the
  non-league container used by ``competitions/ucl/data/seasons/*`` fixtures.
- match ids use the harness ``MD(\d{2})_<idx>`` matchday-prefixed scheme;
  ``event_date`` remains the primary chronology per ``src/historical.py``.

Storage deviation (documented in PROVENANCE.json): the approved plan's
``data/seasons/<season>/`` path is the gitignored runtime season store, so
the git-trackable backfill lives under ``data/historical/<season>/``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

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


def year_key(season: str) -> int:
    return int(season.split("_")[0])


def md_match_id(matchday: int, index: int) -> str:
    """Matchday-prefixed id, e.g. MD06_03 -> 'MD06_03'."""
    return f"MD{matchday:02d}_{index:02d}"


def season_dir(season: str) -> str:
    return os.path.join(HISTORICAL_DIR, season)


def write_json(path: str, data: Any) -> str:
    """Atomically write JSON and return a content hash of the file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def duplicate_keys(matches: list[dict]) -> list[str]:
    """match_ids appearing more than once, preserving first-seen order."""
    seen: dict[str, int] = {}
    for m in matches:
        mid = m.get("match_id")
        if mid is not None:
            seen[mid] = seen.get(mid, 0) + 1
    return [mid for mid, count in seen.items() if count > 1]