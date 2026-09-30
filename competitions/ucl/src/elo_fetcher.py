"""UCL ClubElo fetcher — thin wrapper around football_core.elo_fetcher.

All generic ClubElo logic lives in football_core. This module wires
the UCL-specific alias path and re-exports for backward compatibility.
"""

import logging
import os
from pathlib import Path

from football_core.elo_fetcher import (
    elo_store_fetched_at as _core_elo_store_fetched_at,
    get_clubelo_snapshot_date,
    fetch_team_elos as _core_fetch_team_elos,
    refresh_elos_if_stale as _core_refresh_elos_if_stale,
    resolve_clubelo_name as _core_resolve_clubelo_name,
)

logger = logging.getLogger(__name__)

_UCL_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)
_UCL_ALIAS_PATH = os.path.join(_UCL_DATA_DIR, "team_aliases.json")


def fetch_team_elos(
    team_names: list[str],
    alias_path: str | None = None,
    delay: float = 0.0,
) -> dict[str, float]:
    return _core_fetch_team_elos(
        team_names,
        alias_path or _UCL_ALIAS_PATH,
        delay=delay,
    )


def refresh_elos_if_stale(
    team_names: list[str],
    alias_path: str | None = None,
    data_dir: str | Path | None = None,
    max_age_hours: float = 24.0,
) -> dict[str, float]:
    """Stored ClubElo ratings, re-fetched only when stale or incomplete.

    The store lives in the UCL data dir rather than the active season dir:
    ClubElo rates a club globally, so one snapshot serves every season and
    splitting it per season would mean one fetch per season.
    """
    return _core_refresh_elos_if_stale(
        team_names,
        alias_path or _UCL_ALIAS_PATH,
        data_dir if data_dir is not None else _UCL_DATA_DIR,
        max_age_hours=max_age_hours,
    )


def resolve_clubelo_name(team_name: str, alias_path: str | None = None) -> str:
    return _core_resolve_clubelo_name(team_name, alias_path or _UCL_ALIAS_PATH)


def elo_store_fetched_at() -> str:
    """When the stored UCL ratings were read, or ``""`` if there are none."""
    return _core_elo_store_fetched_at(_UCL_DATA_DIR)
