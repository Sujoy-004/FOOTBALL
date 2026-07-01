"""Monte Carlo simulation engine for UCL league phase.

Provides the top-level orchestration layer:

- :func:`simulate_league_phase` — one complete league phase iteration
- :func:`run_monte_carlo` — N-iteration Monte Carlo loop with aggregation
- :func:`aggregate_mc_results` — isolated aggregation function for testability

Consumes the match simulation and standings functions from
:mod:`competitions.ucl.src.groups` (Plan 02).
"""

from __future__ import annotations

import json
import os
import random

from competitions.ucl.src.groups import (
    compute_swiss_standings,
    precompute_swiss_matchup_lambdas,
    simulate_swiss_matches,
)
from competitions.ucl.src.knockout import (
    build_r16_bracket,
    simulate_knockout_tree,
    simulate_playoff_round,
    track_knockout_stages,
)
from football_core.constants import EXPECTED_GOALS_BASE_RATE


# ── D-09 stage constants ──────────────────────────────────────────────────────

STAGE_ORDER = [
    "eliminated",
    "playoff",
    "r16",
    "qf",
    "sf",
    "final",
    "champion",
]
"""Ordered list of D-09 stages; index equals numeric value for post-aggregation."""

STAGE_TO_VALUE: dict[str, int] = {s: i for i, s in enumerate(STAGE_ORDER)}
"""Map stage name to its numeric value (0–6) for per-iteration stage tracking."""


# ═══════════════════════════════════════════════════════════════════════════════
# ── Single-iteration orchestration
# ═══════════════════════════════════════════════════════════════════════════════


def simulate_league_phase(
    fixtures: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    uefa_coefficients: dict[str, float] | None = None,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
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
        played_matches=played_matches,
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
    stage_collectors: dict[str, list[int]] | None = None,
) -> dict[str, dict]:
    """Aggregate per-iteration results into per-team D-06/D-07/D-09 output.

    Computes zone probabilities, champion probability, and averages
    for all 6 tiebreaker stats plus position.

    If *stage_collectors* is provided, also computes D-09 stage
    probabilities (stage_eliminated_prob, stage_playoff_prob, …).

    Parameters
    ----------
    positions:
        ``{team_name: [per-iteration position]}`` for all N iterations.
    champions:
        ``{team_name: count_of_iterations_where_team_was_champion}``.
    stat_collectors:
        ``{team_name: {stat: [per-iteration values]}}``.
    n_iterations:
        Total number of Monte Carlo iterations.
    stage_collectors:
        ``{team_name: [per-iteration stage values]}``, where values
        are ints from 0 (eliminated) to 6 (champion) per STAGE_ORDER.
        If None, stage probabilities are skipped (backward compat).

    Returns
    -------
    dict[str, dict]
        Per-team dict with D-06/D-07 fields plus D-09 stage probability
        fields if *stage_collectors* was provided.
    """
    teams: dict[str, dict] = {}
    for team in positions:
        entry = {
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

        if stage_collectors and team in stage_collectors:
            stages = stage_collectors[team]
            # T-02-11: Verify stage values in range [0, 6], clamp invalid to 0
            clamped = [s if 0 <= s <= 6 else 0 for s in stages]
            entry["stage_eliminated_prob"] = sum(1 for s in clamped if s == 0) / n_iterations
            entry["stage_playoff_prob"] = sum(1 for s in clamped if s == 1) / n_iterations
            entry["stage_r16_prob"] = sum(1 for s in clamped if s == 2) / n_iterations
            entry["stage_qf_prob"] = sum(1 for s in clamped if s == 3) / n_iterations
            entry["stage_sf_prob"] = sum(1 for s in clamped if s == 4) / n_iterations
            entry["stage_final_prob"] = sum(1 for s in clamped if s == 5) / n_iterations
            # champion_prob already set above from champions dict

        teams[team] = entry

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
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
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
    # D-09: stage tracking collector (value 0-6 per iteration)
    stage_collectors: dict[str, list[int]] = {
        t: [] for t in team_names
    }

    # Pre-build Elo dict lookup for knockout pipeline (T-02-13)
    elo_dict: dict[str, float] = dict(elo_ratings)

    # ── 4b. Load competition data files ONCE (perf: avoid O(n) disk I/O) ─
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
    )
    pairings_path = os.path.join(data_dir, "playoff_pairings.json")
    with open(pairings_path) as f:
        _pairings_data = json.load(f)
    bracket_path = os.path.join(data_dir, "bracket_rules.json")
    with open(bracket_path) as f:
        _bracket_data = json.load(f)

    # ── 5. Main iteration loop ──────────────────────────────────────────
    for _ in range(n_iterations):
        standings = simulate_league_phase(
            fixtures,
            elo_ratings,
            rng,
            uefa_coefficients=uefa_coefficients,
            matchup_lambdas=matchup_lambdas,
            played_matches=played_matches,
        )

        # ── Knockout pipeline (Phase 2) ─────────────────────────────────
        playoff_result = simulate_playoff_round(
            standings, elo_dict, rng,
            pairings_data=_pairings_data,
        )
        bracket = build_r16_bracket(
            standings, playoff_result,
            bracket_data=_bracket_data,
        )
        tree_result = simulate_knockout_tree(
            bracket, elo_dict, rng,
        )
        stages = track_knockout_stages(standings, tree_result)
        # ── end knockout pipeline ──────────────────────────────────────

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
            # D-09: champion determined by knockout tree, not league position 1
            if stages[team] == "champion":
                champions[team] += 1
            # D-09: track stage value for post-aggregation
            stage_collectors[team].append(STAGE_TO_VALUE[stages[team]])

    # ── 6. Aggregate and return ─────────────────────────────────────────
    from competitions.ucl.src.elo_fetcher import get_clubelo_snapshot_date

    return {
        "snapshot_date": get_clubelo_snapshot_date(),
        "n_iterations": n_iterations,
        "seed": seed,
        "teams": aggregate_mc_results(
            positions, champions, stat_collectors, n_iterations,
            stage_collectors=stage_collectors,
        ),
        "stage_order": STAGE_ORDER,  # D-09 metadata for consumers
    }
