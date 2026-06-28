"""Two-legged knockout tie simulation for UCL.

Provides the core two-legged aggregate scoring primitive with
extra time (reduced Poisson lambda) and penalty shootouts.

Per D-01: ET simulated locally — BSD API does not expose ET scores.
Per D-02: Penalties simulated locally — calibration in config constant.
Per D-03: ET home advantage belongs to second-leg home team.
"""

from __future__ import annotations

import random

from football_core.constants import (
    EXPECTED_GOALS_BASE_RATE,
    HOME_ADVANTAGE_MULTIPLIER,
    POISSON_TABLE_BITS,
)
from football_core.groups import _build_poisson_table, expected_goals

# ── Configurable constants ─────────────────────────────────────
# These are module-level defaults. Move to a shared
# config/constants layer (e.g. competitions/ucl/src/config.py)
# if they stabilise across multiple modules.  Exact values are
# implementation decisions, not architectural contracts.
# For now, inline defaults keep the API self-contained.

PENALTY_SHOTS_PER_SIDE: int = 5


def _simulate_penalty_shootout(
    rng: random.Random,
    conversion_rate: float = 0.76,
) -> tuple[int, int]:
    """Simulate a penalty shootout with sudden death if level after 5 shots each.

    Each shot is a configurable Bernoulli trial (default ~76%
    reflects historical UCL conversion rate).

    Parameters
    ----------
    rng:
        Seeded random.Random for deterministic results.
    conversion_rate:
        Probability each penalty is converted.

    Returns
    -------
    tuple[int, int]
        (goals_a, goals_b) — the final penalty scores.
    """
    shots = PENALTY_SHOTS_PER_SIDE
    a_scored = b_scored = 0
    for i in range(shots):
        if rng.random() < conversion_rate:
            a_scored += 1
        if rng.random() < conversion_rate:
            b_scored += 1
        # Early termination: one team cannot be caught
        remaining = shots - (i + 1)
        if a_scored > b_scored + remaining or b_scored > a_scored + remaining:
            break

    # Sudden death if still level
    while a_scored == b_scored:
        if rng.random() < conversion_rate:
            a_scored += 1
        if rng.random() < conversion_rate:
            b_scored += 1

    return a_scored, b_scored


def simulate_two_legged_tie(
    team_a: str,
    team_b: str,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """Simulate a two-legged knockout tie with aggregate scoring.

    Simulates both legs using Poisson match simulation from
    football_core, then resolves by aggregate score.  If aggregate
    is level, extra time is played with configurable reduced Poisson
    lambda (per D-01).  If still level, a penalty shootout decides
    with a configurable calibrated conversion model (per D-02).

    Per D-03: extra time home advantage goes to the second-leg home
    team (team_b in leg 2, since team_a hosts leg 1).

    Per the 2025+ format: no away goals rule — aggregate score is
    the only tiebreaker.

    Parameters
    ----------
    team_a:
        Home team for leg 1 (away team for leg 2).
    team_b:
        Away team for leg 1 (home team for leg 2).
    elo_ratings:
        ``{team_name: Elo}`` dict.
    rng:
        Seeded random.Random for deterministic results.
    base_rate:
        Normal time expected goals base rate.
    et_lambda_factor:
        Configurable factor: ET lambda = normal_lambda * factor.
        Reflects shorter ET duration and fatigue.  Move to config
        layer if value stabilises.
    penalty_conversion_rate:
        Configurable probability each penalty shot is converted.
        Historical UCL baseline ~76%.  Move to config layer if
        value stabilises.

    Returns
    -------
    dict
        ``{winner, loser, aggregate_a, aggregate_b,
          agg_a_full, agg_b_full,
          leg1: {team_a, team_b, score_a, score_b},
          leg2: {team_a, team_b, score_a, score_b},
          et_played: bool, et_a, et_b,
          penalties_played: bool, penalty_a, penalty_b}``
    """
    # ── 1. Fetch Elo ratings ──────────────────────────────────────────────
    ea = elo_ratings[team_a]
    eb = elo_ratings[team_b]

    # ── 2. Leg 1 (team_a home, team_b away) ──────────────────────────────
    lam_a1 = expected_goals(ea, eb, base_rate)
    lam_b1 = expected_goals(eb, ea, base_rate)
    score_a1 = _build_poisson_table(lam_a1)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a1 > 0 else 0
    score_b1 = _build_poisson_table(lam_b1)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b1 > 0 else 0

    # ── 3. Leg 2 (team_b home, team_a away) ──────────────────────────────
    lam_b2 = expected_goals(eb, ea, base_rate)    # home advantage for team_b
    lam_a2 = expected_goals(ea, eb, base_rate)    # away for team_a
    score_b2 = _build_poisson_table(lam_b2)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b2 > 0 else 0
    score_a2 = _build_poisson_table(lam_a2)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a2 > 0 else 0

    # ── 4. Compute aggregate ─────────────────────────────────────────────
    agg_a = score_a1 + score_a2
    agg_b = score_b1 + score_b2

    # ── 5. Extra time (if aggregate level, per D-01) ─────────────────────
    et_played = False
    et_a = et_b = 0
    if agg_a == agg_b:
        et_played = True
        # ET: reduced lambda — home advantage to leg 2 host (team_b per D-03)
        # Team_b (second-leg host) gets an extra HOME_ADVANTAGE_MULTIPLIER boost
        # on top of the base factor already applied by expected_goals().
        et_lam_a = expected_goals(ea, eb, base_rate) * et_lambda_factor   # team_a away
        et_lam_b = expected_goals(eb, ea, base_rate) * et_lambda_factor * HOME_ADVANTAGE_MULTIPLIER  # team_b home (D-03)
        et_a = _build_poisson_table(et_lam_a)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_a > 0 else 0
        et_b = _build_poisson_table(et_lam_b)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_b > 0 else 0
        agg_a += et_a
        agg_b += et_b

    # ── 6. Penalties (if still level, per D-02) ──────────────────────────
    penalties_played = False
    pen_a = pen_b = 0
    if agg_a == agg_b:
        penalties_played = True
        pen_a, pen_b = _simulate_penalty_shootout(rng, penalty_conversion_rate)

    # ── 7. Determine winner ──────────────────────────────────────────────
    if agg_a > agg_b:
        winner, loser = team_a, team_b
    elif agg_b > agg_a:
        winner, loser = team_b, team_a
    elif penalties_played:
        # Penalty shootout resolves the tie
        if pen_a > pen_b:
            winner, loser = team_a, team_b
        else:
            winner, loser = team_b, team_a
    else:
        winner, loser = None, None

    # ── 8. Return result dict ────────────────────────────────────────────
    # aggregate_a/b = normal time only (subtract ET contributions)
    return {
        "winner": winner,
        "loser": loser,
        "aggregate_a": score_a1 + score_a2,
        "aggregate_b": score_b1 + score_b2,
        "agg_a_full": agg_a,
        "agg_b_full": agg_b,
        "leg1": {"team_a": team_a, "team_b": team_b, "score_a": score_a1, "score_b": score_b1},
        "leg2": {"team_a": team_a, "team_b": team_b, "score_a": score_a2, "score_b": score_b2},
        "et_played": et_played,
        "et_a": et_a,
        "et_b": et_b,
        "penalties_played": penalties_played,
        "penalty_a": pen_a,
        "penalty_b": pen_b,
    }
