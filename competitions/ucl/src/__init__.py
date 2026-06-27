"""UCL Predictor — Swiss league phase simulation and standings computation."""

from competitions.ucl.src.elo_fetcher import (
    fetch_team_elos,
    get_clubelo_snapshot_date,
    resolve_clubelo_name,
)
from competitions.ucl.src.groups import (
    compute_swiss_standings,
    precompute_swiss_matchup_lambdas,
    simulate_swiss_matches,
)

__all__ = [
    "fetch_team_elos",
    "resolve_clubelo_name",
    "get_clubelo_snapshot_date",
    "precompute_swiss_matchup_lambdas",
    "simulate_swiss_matches",
    "compute_swiss_standings",
]
