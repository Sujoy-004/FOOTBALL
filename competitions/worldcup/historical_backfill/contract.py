"""Shared schema and constants for the historical World Cup backfill.

Canonical naming follows the existing production conventions:
- team keys are exact strings from ``data/team_aliases.json`` (the 2026
  long-form production keys) plus a stable set of keys for historical
  national teams absent from the 2026 aliases (Angola, Serbia and
  Montenegro, ...) — resolved direction-consistently by
  ``football_core.historical_backfill.TeamKeys``.
- match ids use a season-scoped ``<season>_m<nnn>`` scheme; every match has a
  real ``event_date`` so ``event_date`` is the sole trustworthy chronology per
  ``src/historical.py`` (the WC leak-free primitives).

Data sources: results from the openfootball world-cup archive (one
``cup.txt`` group-stage file + one ``cup_finals.txt`` knockout file per
tournament; CC0 public domain). No odds source exists for this archive —
odds fields are omitted entirely (coverage reported as 0, never
fabricated). National-team Elo: ``sources/elo_snapshots.py`` (no
date-indexed historical feed exists — coverage gap recorded, never a
synthetic rating).

Storage deviation (documented in PROVENANCE.json): the approved plan's
``data/seasons/<season>/`` path is the gitignored runtime season store, so
the git-trackable backfill lives under ``data/historical/<season>/`` — the
same convention UCL and LaLiga established.

The competition-agnostic helpers (atomic JSON writes, id/duplicate checks,
season paths) live once in ``football_core.historical_backfill``; this
module is the World-Cup-flavoured view of them.
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

# Tournaments to backfill: start year key -> label.
# D-01 window: every senior men's World Cup whose dates fall inside
# 2000-01-01 .. 2026-12-31 — 2002, 2006, 2010, 2014, 2018, 2022, 2026
# (7 entries, chronological iteration order). 1998 (June 1998) predates the
# window and is NOT included: the replay name below is for the window
# actually contained. This is the single source of truth for the committed
# corpus window; consumers (build, evaluate, the leakage audit) derive their
# season list from here rather than duplicating it.
SEASONS: dict[str, str] = {
    "2002": "2002",
    "2006": "2006",
    "2010": "2010",
    "2014": "2014",
    "2018": "2018",
    "2022": "2022",
    "2026": "2026",
}

# openfootball/world-cup repository directory slug per tournament. The URL
# template matches the provenance record in ``build._provenance_sources`` so
# widening the contract widens the acquisition without a literal in the
# builder.
TOURNEY_DIRS: dict[str, str] = {
    "2002": "2002--south_korea-n-japan",
    "2006": "2006--germany",
    "2010": "2010--south_africa",
    "2014": "2014--brazil",
    "2018": "2018--russia",
    "2022": "2022--qatar",
    "2026": "2026--canada-usa-mexico",
}

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")

# The merged replay file is named for the window it actually contains. Every
# consumer resolves the name through these constants rather than a literal, so
# a widened corpus cannot silently leave a reader pointing at a stale dataset.
REPLAY_NAME = "replay_2002_2026.json"
REPLAY_PATH = os.path.join(HISTORICAL_DIR, REPLAY_NAME)


def match_id(season: str, index: int) -> str:
    """Stable unique match id, e.g. '2002_m001' (1-based by event_date)."""
    return f"{season}_m{index:03d}"


season_dir = partial(_season_dir, HISTORICAL_DIR)

__all__ = [
    "DATA_DIR",
    "HISTORICAL_DIR",
    "REPLAY_NAME",
    "REPLAY_PATH",
    "SCHEMA",
    "SEASONS",
    "TOURNEY_DIRS",
    "duplicate_keys",
    "match_id",
    "read_json",
    "season_dir",
    "write_json",
    "year_key",
]
