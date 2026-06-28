"""UCL Predictor — Swiss league phase simulation, standings, Monte Carlo, and knockout."""

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
from competitions.ucl.src.knockout import (
    simulate_playoff_round,
    simulate_two_legged_tie,
)
from competitions.ucl.src.simulation import (
    aggregate_mc_results,
    run_monte_carlo,
    simulate_league_phase,
)

__all__ = [
    "fetch_team_elos",
    "resolve_clubelo_name",
    "get_clubelo_snapshot_date",
    "precompute_swiss_matchup_lambdas",
    "simulate_swiss_matches",
    "compute_swiss_standings",
    "simulate_playoff_round",
    "simulate_two_legged_tie",
    "simulate_league_phase",
    "run_monte_carlo",
    "aggregate_mc_results",
]
