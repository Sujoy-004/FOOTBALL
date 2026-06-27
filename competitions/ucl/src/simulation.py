"""Monte Carlo simulation engine for UCL league phase.

Provides the top-level orchestration layer:

- :func:`simulate_league_phase` — one complete league phase iteration
- :func:`run_monte_carlo` — N-iteration Monte Carlo loop with aggregation
- :func:`aggregate_mc_results` — isolated aggregation function for testability

Consumes the match simulation and standings functions from
:mod:`competitions.ucl.src.groups` (Plan 02).
"""

from __future__ import annotations

import random

from competitions.ucl.src.groups import (
    compute_swiss_standings,
    precompute_swiss_matchup_lambdas,
    simulate_swiss_matches,
)
from football_core.constants import EXPECTED_GOALS_BASE_RATE


# ═══════════════════════════════════════════════════════════════════════════════
# ── Single-iteration orchestration
# ═══════════════════════════════════════════════════════════════════════════════


def simulate_league_phase(
    fixtures: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    uefa_coefficients: dict[str, float] | None = None,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
) -> list[dict]:
    """Simulate one complete UCL league phase iteration.

    Parameters
    ----------
    fixtures:
        UCL fixture schedule dict from ``fixtures.json``.
    elo_ratings:
        ``{team_name: Elo}`` for all 36 teams.
    rng:
        Seeded ``random.Random`` instance for reproducibility.
    uefa_coefficients:
        ``{team_name: coefficient}`` for tiebreaker step 10.
    matchup_lambdas:
        Precomputed Poisson lambdas.  Computed once if ``None``.

    Returns
    -------
    list[dict]
        List of 36 standings dicts sorted by position (1-36), each with
        full tiebreaker stats and zone classification.
    """
    if matchup_lambdas is None:
        matchup_lambdas = precompute_swiss_matchup_lambdas(
            fixtures, elo_ratings, EXPECTED_GOALS_BASE_RATE,
        )

    matches = simulate_swiss_matches(
        fixtures,
        elo_ratings,
        rng,
        base_rate=EXPECTED_GOALS_BASE_RATE,
        matchup_lambdas=matchup_lambdas,
    )

    standings = compute_swiss_standings(
        matches,
        elo_ratings=elo_ratings,
        uefa_coefficients=uefa_coefficients,
    )

    return standings


# ═══════════════════════════════════════════════════════════════════════════════
# ── Aggregation (testable in isolation)
# ═══════════════════════════════════════════════════════════════════════════════


def aggregate_mc_results(
    positions: dict[str, list[int]],
    champions: dict[str, int],
    stat_collectors: dict[str, dict[str, list[int | float]]],
    n_iterations: int,
) -> dict[str, dict]:
    """Aggregate per-iteration results into per-team D-06/D-07 output.

    Computes zone probabilities, champion probability, and averages
    for all 6 tiebreaker stats plus position.

    Parameters
    ----------
    positions:
        ``{team_name: [per-iteration position]}`` for all N iterations.
    champions:
        ``{team_name: count_of_iterations_where_position==1}``.
    stat_collectors:
        ``{team_name: {stat: [per-iteration values]}}``.
    n_iterations:
        Total number of Monte Carlo iterations.

    Returns
    -------
    dict[str, dict]
        Per-team dict matching the D-06/D-07 output schema:
        ``{team_name: {top_8_prob, playoff_prob, eliminated_prob,
                       champion_prob, avg_position, avg_pts, avg_gd,
                       avg_gs, avg_away_gs, avg_wins, avg_away_wins}}``
    """
    teams: dict[str, dict] = {}
    for team in positions:
        teams[team] = {
            "top_8_prob": sum(1 for p in positions[team] if p <= 8) / n_iterations,
            "playoff_prob": sum(1 for p in positions[team] if 9 <= p <= 24) / n_iterations,
            "eliminated_prob": sum(1 for p in positions[team] if p >= 25) / n_iterations,
            "champion_prob": champions[team] / n_iterations,
            "avg_position": sum(positions[team]) / n_iterations,
            "avg_pts": sum(stat_collectors[team]["pts"]) / n_iterations,
            "avg_gd": sum(stat_collectors[team]["gd"]) / n_iterations,
            "avg_gs": sum(stat_collectors[team]["gs"]) / n_iterations,
            "avg_away_gs": sum(stat_collectors[team]["away_gs"]) / n_iterations,
            "avg_wins": sum(stat_collectors[team]["wins"]) / n_iterations,
            "avg_away_wins": sum(stat_collectors[team]["away_wins"]) / n_iterations,
        }
    return teams


# ═══════════════════════════════════════════════════════════════════════════════
# ── Monte Carlo loop
# ═══════════════════════════════════════════════════════════════════════════════


def run_monte_carlo(
    fixtures: dict,
    elo_ratings: dict[str, float] | None = None,
    n_iterations: int = 10000,
    seed: int = 42,
    uefa_coefficients: dict[str, float] | None = None,
    team_aliases: dict[str, str] | None = None,
) -> dict:
    """Run Monte Carlo simulation of UCL league phase.

    Orchestrates the full simulation pipeline: optionally fetches Elo
    ratings from ClubElo, precomputes matchup lambdas once, runs
    *n_iterations* of the league phase (match simulation → standings),
    and aggregates per-team zone/champion probabilities and stat averages.

    Parameters
    ----------
    fixtures:
        UCL fixture schedule dict (36 teams, 144 matches).
    elo_ratings:
        ``{team_name: Elo}``.  Fetched from ClubElo if ``None``.
    n_iterations:
        Number of Monte Carlo iterations (default 10 000).
    seed:
        Random seed for reproducibility.
    uefa_coefficients:
        ``{team_name: coefficient}`` for tiebreaker step 10.
    team_aliases:
        ``{team_name: clubelo_slug}`` mapping.  Loaded from
        ``data/team_aliases.json`` if not provided.

    Returns
    -------
    dict
        Output dict matching D-06/D-07 specification:
        ``{snapshot_date, n_iterations, seed,
          teams: {team_name: {top_8_prob, playoff_prob, eliminated_prob,
                              champion_prob, avg_position, avg_pts, avg_gd,
                              avg_gs, avg_away_gs, avg_wins, avg_away_wins}}}``
    """
    # ── 1. Fetch / resolve Elo ratings ──────────────────────────────────
    if elo_ratings is None:
        from competitions.ucl.src.elo_fetcher import fetch_team_elos

        team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
        elo_ratings = fetch_team_elos(team_names)

    # ── 2. Initialise seeded RNG ────────────────────────────────────────
    rng = random.Random(seed)

    # ── 3. Precompute matchup lambdas ONCE (Pitfall 4) ──────────────────
    matchup_lambdas = precompute_swiss_matchup_lambdas(
        fixtures, elo_ratings, EXPECTED_GOALS_BASE_RATE,
    )

    # ── 4. Initialise per-team collectors (post-aggregation pattern) ────
    team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
    positions: dict[str, list[int]] = {t: [] for t in team_names}
    champions: dict[str, int] = {t: 0 for t in team_names}
    stat_collectors: dict[str, dict[str, list[int | float]]] = {
        t: {"pts": [], "gd": [], "gs": [], "away_gs": [],
            "wins": [], "away_wins": []}
        for t in team_names
    }

    # ── 5. Main iteration loop ──────────────────────────────────────────
    for _ in range(n_iterations):
        standings = simulate_league_phase(
            fixtures,
            elo_ratings,
            rng,
            uefa_coefficients=uefa_coefficients,
            matchup_lambdas=matchup_lambdas,
        )

        for entry in standings:
            team = entry["team"]
            pos = entry["position"]
            positions[team].append(pos)
            stat_collectors[team]["pts"].append(entry["pts"])
            stat_collectors[team]["gd"].append(entry["gd"])
            stat_collectors[team]["gs"].append(entry["gs"])
            stat_collectors[team]["away_gs"].append(entry["away_gs"])
            stat_collectors[team]["wins"].append(entry["wins"])
            stat_collectors[team]["away_wins"].append(entry["away_wins"])
            if pos == 1:
                champions[team] += 1

    # ── 6. Aggregate and return ─────────────────────────────────────────
    from competitions.ucl.src.elo_fetcher import get_clubelo_snapshot_date

    return {
        "snapshot_date": get_clubelo_snapshot_date(),
        "n_iterations": n_iterations,
        "seed": seed,
        "teams": aggregate_mc_results(positions, champions, stat_collectors, n_iterations),
    }
