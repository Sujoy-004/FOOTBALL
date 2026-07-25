"""Squad market value strength signal computation.

DEPRECATED — Use football_core.signals.squad_value.SquadValueSignal instead.
Kept for backward compatibility with legacy refresh_from_api().

Computes a strength signal for each match based on the ratio of squad
market values between the two teams.

Formula:
  strength = value_a / max(value_a + value_b, 0.01)
  home_prob = sigmoid(k * (strength - 0.5) * 4)
  draw_prob = 0.25

Where k = 1.5. Market values come from a static file (team_values.json).
If either team has no value data or non-positive value, the signal is
marked unavailable.

Data sources:
  team_values.json — static squad market value file (pre-loaded or auto-load).

Threat model:
- T-15-XX: Missing team (not in team_values) → available: false with reason
- T-15-XX: Non-positive market value → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timedelta, timezone

from src import constants
from src.math_utils import sigmoid as _sigmoid

logger = logging.getLogger(__name__)


# ─── Constants ──────────────────────────────────────────────────────────────

SQUAD_VALUE_K: float = 1.5
"""Sigmoid steepness for squad value signal."""

DRAW_PROB: float = 0.25
"""Fixed draw probability for squad value signal."""


# ─── Helpers ────────────────────────────────────────────────────────────────


def _compute_match_squad_value_signal(
    team_a: str,
    team_b: str,
    team_values: dict[str, int],
    k: float,
) -> dict:
    """Compute squad value signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        team_values: Dict mapping team name → squad market value in EUR.
        k: Sigmoid steepness.

    Returns:
        Signal entry dict with keys: probability, available, reason (if unavailable).
    """
    now = datetime.now(timezone.utc)

    if team_a not in team_values:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_value_not_found: {team_a}",
        }
    if team_b not in team_values:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_value_not_found: {team_b}",
        }

    value_a = team_values[team_a]
    value_b = team_values[team_b]

    if not isinstance(value_a, (int, float)) or value_a <= 0:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"non_positive_value: {team_a}={value_a!r}",
        }
    if not isinstance(value_b, (int, float)) or value_b <= 0:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"non_positive_value: {team_b}={value_b!r}",
        }

    strength = value_a / max(value_a + value_b, 0.01)
    p = _sigmoid(k * (strength - 0.5) * 4)

    # Clamp to [1e-15, 1-1e-15]
    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "draw_probability": DRAW_PROB,
        "timestamp": now.isoformat(),
        "available": True,
    }


# ─── Public API ─────────────────────────────────────────────────────────────


def compute_squad_value_signal(
    groups: dict,
    team_values: dict | None = None,
    bracket: list[dict] | None = None,
    k_factor: float | None = None,
) -> dict:
    """Compute squad value strength signal for all group and bracket matches.

    For each match with a known team_a/team_b pairing, computes::

        strength = value_a / max(value_a + value_b, 0.01)
        p = sigmoid(k * (strength - 0.5) * 4)
        draw_prob = 0.25

    Args:
        groups: Groups dict (with optional 'groups' wrapper key).
        team_values: Pre-loaded dict of team → market value (EUR).
                     Auto-loads from state if None.
        bracket: Optional bracket list. Auto-loads if None.
        k_factor: Sigmoid steepness. Defaults to ``SQUAD_VALUE_K`` (1.5).

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry (24h TTL).
            matches (dict): Match-ID → signal entry mapping.
    """
    now = datetime.now(timezone.utc)

    # Auto-load data if not provided
    if team_values is None:
        from src.state import load_team_values
        team_values = load_team_values()

    if bracket is None:
        try:
            from src.state import load_bracket
            bracket = load_bracket()
        except Exception:
            logger.warning("Could not load bracket data for squad value signal", exc_info=True)
            bracket = []

    k = k_factor if k_factor is not None else SQUAD_VALUE_K

    groups_data = groups.get("groups", groups)
    result: dict[str, dict] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            entry = _compute_match_squad_value_signal(
                match["team_a"], match["team_b"],
                team_values, k,
            )
            result[mid] = entry

    # Process bracket matches — skip unresolved slots (team_a or team_b is None)
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue
        entry = _compute_match_squad_value_signal(
            match["team_a"], match["team_b"],
            team_values, k,
        )
        result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=constants.CATBOOST_CACHE_TTL_HOURS)).isoformat(),
        "matches": result,
    }
