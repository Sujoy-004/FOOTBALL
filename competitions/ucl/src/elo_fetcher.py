"""UCL ClubElo fetcher — thin wrapper around football_core.elo_fetcher.

All generic ClubElo logic lives in football_core. This module wires
the UCL-specific alias path and re-exports for backward compatibility.

Extended in Phase 10 (Plan 02) to support :class:`RatingSystem`-based
fetches for the Bayesian/Glicko-1 Elo pipeline.
"""

import json
import logging
import os

from football_core.elo_fetcher import (
    get_clubelo_snapshot_date,
    fetch_team_elos as _core_fetch_team_elos,
    resolve_clubelo_name as _core_resolve_clubelo_name,
)
from football_core.glicko import DEFAULT_MU, DEFAULT_SIGMA, RatingSystem

logger = logging.getLogger(__name__)

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


# ═══════════════════════════════════════════════════════════════════════════════
# ── Glicko / RatingSystem fetchers  (Phase 10, Plan 02)
# ═══════════════════════════════════════════════════════════════════════════════


def fetch_team_ratings(team_names: list[str]) -> RatingSystem:
    """Fetch point estimates from ClubElo and wrap in a ``RatingSystem``.

    Since ClubElo API returns only point Elo ratings (no RD), every team
    receives the default uncertainty (:data:`DEFAULT_SIGMA`).

    Parameters
    ----------
    team_names:
        List of team names to fetch ratings for.

    Returns
    -------
    RatingSystem
        Populated with fetched μ (Elo) and default σ for each team.
    """
    elo_dict = _core_fetch_team_elos(team_names, _UCL_ALIAS_PATH)
    rs = RatingSystem()
    for team, elo in elo_dict.items():
        rs.set_rating(team, mu=elo, sigma=DEFAULT_SIGMA)
    return rs


def fetch_or_init_ratings(
    team_names: list[str],
    cache_path: str | None = None,
) -> RatingSystem:
    """Fetch or initialise ratings, optionally cached to disk.

    Tries to load from *cache_path* first (fast path).  If cache is
    missing, fetches from ClubElo via :func:`fetch_team_ratings` and
    persists the result to *cache_path* if provided.  Falls back to
    default ratings (1500 ± 350) for any team the API does not return.

    Parameters
    ----------
    team_names:
        List of team names to fetch ratings for.
    cache_path:
        Optional JSON file path for on-disk cache.  If ``None``,
        always fetches fresh ratings.

    Returns
    -------
    RatingSystem
        Populated :class:`~football_core.glicko.RatingSystem`.
    """
    # Try loading from cache
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                data = json.load(f)
            logger.debug("Loaded ratings cache from %s (%d teams)", cache_path, len(data))
            return RatingSystem.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load ratings cache: %s — re-fetching", exc)

    # Fetch from ClubElo
    rs = fetch_team_ratings(team_names)

    # Save to cache if requested
    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(rs.to_dict(), f, indent=2)
            logger.debug("Saved ratings cache to %s (%d teams)", cache_path, len(team_names))
        except OSError as exc:
            logger.warning("Failed to save ratings cache: %s", exc)

    return rs
