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
``data/seasons/<season>/`` path is the gitignored runtime season store, so the
git-trackable backfill lives under ``data/historical/<season>/`` — the same
convention UCL established.
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


def year_key(season: str) -> int:
    return int(season.split("_")[0])


def match_id(season: str, index: int) -> str:
    """Stable unique match id, e.g. '2019_20_m001' (1-based by event_date)."""
    return f"{season}_m{index:03d}"


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