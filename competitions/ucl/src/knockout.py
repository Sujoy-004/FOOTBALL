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


def simulate_two_legged_tie(
    team_a: str,
    team_b: str,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """..."""
    raise NotImplementedError("Implemented in Task 2")
