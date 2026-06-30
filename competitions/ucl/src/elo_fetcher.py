"""UCL ClubElo fetcher — thin wrapper around football_core.elo_fetcher.

All generic ClubElo logic lives in football_core. This module wires
the UCL-specific alias path and re-exports for backward compatibility.
"""

import os

from football_core.elo_fetcher import (
    get_clubelo_snapshot_date,
    fetch_team_elos as _core_fetch_team_elos,
    resolve_clubelo_name as _core_resolve_clubelo_name,
)

_UCL_ALIAS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "team_aliases.json",
)


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


def resolve_clubelo_name(team_name: str, alias_path: str | None = None) -> str:
    return _core_resolve_clubelo_name(team_name, alias_path or _UCL_ALIAS_PATH)
