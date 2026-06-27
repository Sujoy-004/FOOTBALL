"""Lineup strength (market value log-ratio) signal computation.

Computes a strength signal for each match based on the log-ratio of squad
market values between the two teams.

Formula:
  strength_delta = ln(home_value / away_value)
  p = sigmoid(k * strength_delta)

Where k = DEFAULT_LINEUP_K (0.35). Market values come from a static file
(team_values.json) with aggregate squad values in EUR.

Data sources:
  team_values.json — static squad market value file (pre-loaded or auto-load).

Threat model:
- T-15-06: Missing team (not in team_values) → available: false with reason
- T-15-07: Non-positive market value → available: false with reason
- T-15-08: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-09: Graceful ledger upsert failure (try/except with logger.warning)
- T-15-10: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
import math
from datetime import datetime, timedelta, timezone

from src import constants
from src.math_utils import sigmoid as _sigmoid

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _compute_match_lineup_signal(
    team_a: str,
    team_b: str,
    team_values: dict[str, int],
    k: float,
) -> dict:
    """Compute lineup strength signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        team_values: Dict mapping team name → squad market value in EUR.
        k: Sigmoid steepness (DEFAULT_LINEUP_K or overridden).

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

    strength_delta = math.log(value_a / value_b)
    p = _sigmoid(k * strength_delta)

    # Clamp to [1e-15, 1-1e-15] — T-15-10
    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "timestamp": now.isoformat(),
        "available": True,
    }


# ─── Public API ─────────────────────────────────────────────────────────────


def compute_lineup_signal(
    groups: dict,
    team_values: dict | None = None,
    bracket: list[dict] | None = None,
    k_factor: float | None = None,
) -> dict:
    """Compute lineup strength signal based on squad market value log-ratio.

    For each match with a known team_a/team_b pairing, computes::

        strength_delta = ln(value_a / value_b)
        p = sigmoid(k * strength_delta)

    Args:
        groups: Groups dict (with optional 'groups' wrapper key).
        team_values: Pre-loaded dict of team → market value (EUR).
                     Auto-loads from state if None.
        bracket: Optional bracket list. Auto-loads if None.
        k_factor: Sigmoid steepness. Defaults to ``constants.DEFAULT_LINEUP_K``.

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry (1h TTL).
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
            logger.warning("Could not load bracket data for lineup signal", exc_info=True)
            bracket = []

    k = k_factor if k_factor is not None else constants.DEFAULT_LINEUP_K

    groups_data = groups.get("groups", groups)
    result: dict[str, dict] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            entry = _compute_match_lineup_signal(
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
        entry = _compute_match_lineup_signal(
            match["team_a"], match["team_b"],
            team_values, k,
        )
        result[mid] = entry

    # Upsert into permanent prediction ledger — T-15-09
    if result:
        try:
            from src.state import ledger_upsert
            for mid, entry in result.items():
                ledger_upsert(mid, "lineup_strength", entry)
        except Exception:
            logger.warning(
                "Failed to upsert lineup strength into prediction ledger",
                exc_info=True,
            )

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }
