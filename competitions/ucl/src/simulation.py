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
from collections import defaultdict

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
# ── Stubs (replaced by full implementations in Task 2)
# ═══════════════════════════════════════════════════════════════════════════════


def run_monte_carlo(*args, **kwargs):
    """Run Monte Carlo simulation of UCL league phase.

    .. warning::

        This is a placeholder stub and will be replaced in Task 2.
    """
    raise NotImplementedError("Will be implemented in Task 2")


def aggregate_mc_results(*args, **kwargs):
    """Aggregate per-iteration results into final output.

    .. warning::

        This is a placeholder stub and will be replaced in Task 2.
    """
    raise NotImplementedError("Will be implemented in Task 2")
