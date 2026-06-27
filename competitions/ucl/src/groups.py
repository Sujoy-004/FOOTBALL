"""Swiss match simulation and standings computation for UCL league phase.

Provides Poisson-based match simulation using football_core primitives and
the 10-step UCL tiebreaker chain (no H2H — not applicable to Swiss system).

Per UCLT-01, UCLT-02, UCLT-06:
- UCLT-01: Simulate 36-team league phase (144 matches across 8 matchdays)
- UCLT-02: Compute 36-team standings sorted by 10-step UCL tiebreaker chain
- UCLT-06: Reuse football_core Poisson primitives without modifying core
"""

from __future__ import annotations

import random
from collections import defaultdict

from football_core.constants import (
    DEFAULT_ELO,
    EXPECTED_GOALS_BASE_RATE,
    POISSON_TABLE_BITS,
)
from football_core.groups import (
    _build_poisson_table,
    _compute_conduct_score,
    expected_goals,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ── Pre-compute matchup lambdas
# ═══════════════════════════════════════════════════════════════════════════════


def precompute_swiss_matchup_lambdas(
    fixtures: dict,
    elo_ratings: dict[str, float],
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
) -> dict[str, tuple[float, float]]:
    """Pre-compute expected goals lambdas for every match in the fixture schedule.

    Iterates all matches and calls ``expected_goals()`` once per team
    per match.  Returns ``{match_id: (lambda_a, lambda_b)}``.

    Per Pitfall 4: all lambdas are precomputed ONCE before the iteration
    loop, not recalculated inside it.
    """
    lambdas: dict[str, tuple[float, float]] = {}
    schedule = fixtures.get("schedule", fixtures)
    for matchday in schedule["matchdays"]:
        for match in matchday:
            mid = match["match_id"]
            ta, tb = match["team_a"], match["team_b"]
            ea, eb = elo_ratings[ta], elo_ratings[tb]
            lambdas[mid] = (
                expected_goals(ea, eb, base_rate),
                expected_goals(eb, ea, base_rate),
            )
    return lambdas


# ═══════════════════════════════════════════════════════════════════════════════
# ── Match simulation
# ═══════════════════════════════════════════════════════════════════════════════


def simulate_swiss_matches(
    fixtures: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    fair_play: bool = True,
) -> dict[str, dict]:
    """Simulate all Swiss league phase matches using Poisson primitives.

    Follows the same sampling pattern as
    ``football_core.groups.simulate_group_matches()``.

    Parameters
    ----------
    fixtures:
        Fixture schedule dict matching the ``fixtures.json`` schema.
    elo_ratings:
        ``{team_name: elo}`` for all 36 teams.
    rng:
        Seeded ``random.Random`` instance for deterministic results.
    base_rate:
        Base scoring rate (default ``EXPECTED_GOALS_BASE_RATE``).
    matchup_lambdas:
        Pre-computed lambdas.  Computed automatically if ``None``.
    fair_play:
        Sample yellow/red cards when ``True``.

    Returns
    -------
    dict[str, dict]
        Flat dict keyed by ``match_id`` (NOT grouped by matchday).
        Does NOT mutate the input *fixtures*.
    """
    # Defensive copy to guarantee no mutation (WC anti-pattern rule)
    fixtures = {"schedule": {
        "teams": list(fixtures.get("schedule", fixtures).get("teams", [])),
        "matchdays": [
            list(md) for md in fixtures.get("schedule", fixtures).get("matchdays", [])
        ],
    }}

    schedule = fixtures["schedule"]

    if matchup_lambdas is None:
        matchup_lambdas = precompute_swiss_matchup_lambdas(
            fixtures, elo_ratings, base_rate=base_rate,
        )

    getrandbits = rng.getrandbits
    table_bits = POISSON_TABLE_BITS
    build_table = _build_poisson_table

    results: dict[str, dict] = {}
    for matchday in schedule["matchdays"]:
        for match in matchday:
            mid = match["match_id"]
            ta: str = match["team_a"]
            tb: str = match["team_b"]
            la, lb = matchup_lambdas[mid]

            score_a = (
                0 if la <= 0.0 else build_table(la)[getrandbits(table_bits)]
            )
            score_b = (
                0 if lb <= 0.0 else build_table(lb)[getrandbits(table_bits)]
            )

            if score_a > score_b:
                winner = ta
            elif score_b > score_a:
                winner = tb
            else:
                winner = None

            if fair_play:
                yc_table = build_table(2.0)
                rc_table = build_table(0.05)
                yc_a = yc_table[getrandbits(table_bits)]
                rc_a = rc_table[getrandbits(table_bits)]
                yc_b = yc_table[getrandbits(table_bits)]
                rc_b = rc_table[getrandbits(table_bits)]
            else:
                yc_a = rc_a = yc_b = rc_b = 0

            results[mid] = {
                "team_a": ta,
                "team_b": tb,
                "score_a": score_a,
                "score_b": score_b,
                "winner": winner,
                "yellow_cards_a": yc_a,
                "red_cards_a": rc_a,
                "yellow_cards_b": yc_b,
                "red_cards_b": rc_b,
            }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# ── Swiss standings (STUB — RED phase)
# ═══════════════════════════════════════════════════════════════════════════════


def compute_swiss_standings(
    matches: dict[str, dict],
    elo_ratings: dict[str, float] | None = None,
    uefa_coefficients: dict[str, float] | None = None,
) -> list[dict]:
    """STUB — returns empty list (will fail RED tests)."""
    return []
