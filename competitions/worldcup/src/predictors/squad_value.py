"""Squad market value strength signal computation.

DEPRECATED — Delegates to football_core.signals.squad_value.SquadValueSignal.
Kept for backward compatibility with legacy cache-dict format.

Formula (consolidated):
  Uses log-transform of Transfermarkt values via SquadValueSignal:
    home_prob = log(value_a) / (log(value_a) + log(value_b))
  Missing or non-positive values fall back to median squad value.

Data sources:
  team_values.json — WC-specific squad market value file (pre-loaded or auto-load).

Threat model:
- T-15-XX: Missing team (not in team_values) → available: false with reason
- T-15-XX: Non-positive market value → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timezone

from football_core.signal import PredictionContext
from football_core.signals.squad_value import SquadValueSignal

logger = logging.getLogger(__name__)


SQUAD_VALUE_K: float = 1.5
"""Kept for backward compatibility (no longer used directly)."""

DRAW_PROB: float = 0.25
"""Kept for backward compatibility (core signal computes its own draw)."""


def compute_squad_value_signal(
    groups: dict,
    team_values: dict | None = None,
    bracket: list[dict] | None = None,
    k_factor: float | None = None,
) -> dict:
    """Compute squad value signal — delegates to SquadValueSignal.

    For each match with a known team_a/team_b pairing, computes via
    SquadValueSignal using log-transform of squad market values::

        home_prob = log(value_a) / max(log(value_a) + log(value_b), 0.01)

    Args:
        groups: Groups dict (with optional 'groups' wrapper key).
        team_values: Pre-loaded dict of team → market value (EUR).
                     Auto-loads from state if None.
        bracket: Optional bracket list. Auto-loads if None.
        k_factor: Ignored (kept for backward compatibility).

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry.
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

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    # Build all_matches list
    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        if m.get("team_a") is not None and m.get("team_b") is not None:
            all_matches.append(m)

    signal = SquadValueSignal()
    context = PredictionContext(
        fixtures=list(all_matches),
        squad_values=team_values,
    )

    result: dict[str, dict] = {}

    # Process group matches
    for g in groups_data.values():
        for match in g.get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue

            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")

            if team_a not in team_values:
                result[mid] = {
                    "probability": None,
                    "timestamp": now.isoformat(),
                    "available": False,
                    "reason": f"team_value_not_found: {team_a}",
                }
                continue
            if team_b not in team_values:
                result[mid] = {
                    "probability": None,
                    "timestamp": now.isoformat(),
                    "available": False,
                    "reason": f"team_value_not_found: {team_b}",
                }
                continue

            try:
                output = signal.predict(match, context)
                p = max(1e-15, min(1 - 1e-15, output.home_prob))
                result[mid] = {
                    "probability": p,
                    "draw_probability": output.draw_prob,
                    "timestamp": now.isoformat(),
                    "available": True,
                }
            except Exception:
                logger.exception("SquadValueSignal failed for match %s", mid)
                result[mid] = {
                    "probability": None,
                    "timestamp": now.isoformat(),
                    "available": False,
                    "reason": "error",
                }

    # Process bracket matches — skip unresolved slots
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue

        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")

        if team_a not in team_values:
            result[mid] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": f"team_value_not_found: {team_a}",
            }
            continue
        if team_b not in team_values:
            result[mid] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": f"team_value_not_found: {team_b}",
            }
            continue

        try:
            output = signal.predict(match, context)
            p = max(1e-15, min(1 - 1e-15, output.home_prob))
            result[mid] = {
                "probability": p,
                "draw_probability": output.draw_prob,
                "timestamp": now.isoformat(),
                "available": True,
            }
        except Exception:
            logger.exception("SquadValueSignal failed for match %s", mid)
            result[mid] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": "error",
            }

    return {
        "fetched_at": now.isoformat(),
        "expires_at": now.isoformat(),
        "matches": result,
    }
