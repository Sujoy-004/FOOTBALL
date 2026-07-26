"""Rest days (recovery advantage) signal computation.

DEPRECATED — Delegates to football_core.signals.rest_days.RestDaysSignal.
Kept for backward compatibility with legacy cache-dict format.

Formula (consolidated):
  rest_a = days since team_a's previous match (from context.fixtures)
  rest_b = days since team_b's previous match
  adjustment = max_advantage * tanh((rest_a - rest_b) / 7.0)
  home_prob = 1/3 + adjustment
  draw_prob = 1/3

Data sources:
  group fixture schedule (from groups dict) + bracket — all match dates.

Threat model:
- T-15-XX: Match with no date info → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timezone

from football_core.signal import PredictionContext
from football_core.signals.rest_days import RestDaysSignal

logger = logging.getLogger(__name__)


REST_DAYS_K: float = 1.0
"""Kept for backward compatibility (no longer used directly)."""

DRAW_PROB: float = 0.25
"""Kept for backward compatibility (core signal computes its own draw)."""

DEFAULT_REST_DAYS: int = 7
"""Kept for backward compatibility."""


def _extract_date(match: dict) -> str | None:
    """Extract date string from a match dict.

    Checks event_date, date, and completed_at fields in order.
    """
    return (match.get("event_date") or
            match.get("date") or
            match.get("completed_at"))


def compute_rest_days_signal(
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute rest days signal — delegates to RestDaysSignal.

    For each match with date info, computes via RestDaysSignal::

        rest_a = days since team_a's previous match (from context.fixtures)
        rest_b = days since team_b's previous match
        home_prob = 1/3 + max_advantage * tanh((rest_a - rest_b) / 7.0)
        draw_prob = 1/3

    Args:
        groups: Groups dict (with optional 'groups' wrapper key).
        bracket: Optional bracket list. Auto-loads if None.

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry.
            matches (dict): Match-ID → signal entry mapping.
    """
    now = datetime.now(timezone.utc)

    # Auto-load data if not provided
    if bracket is None:
        try:
            from src.state import load_bracket
            bracket = load_bracket()
        except Exception:
            logger.warning("Could not load bracket data for rest days signal", exc_info=True)
            bracket = []

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    # Build all_matches list for context.fixtures
    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        if m.get("team_a") is not None and m.get("team_b") is not None:
            all_matches.append(m)

    signal = RestDaysSignal()
    context = PredictionContext(fixtures=list(all_matches), elo_ratings={})

    result: dict[str, dict] = {}

    # Process group matches
    for g in groups_data.values():
        for match in g.get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue

            date_str = _extract_date(match)
            if not date_str:
                result[mid] = {
                    "probability": None,
                    "timestamp": now.isoformat(),
                    "available": False,
                    "reason": "no_date_info",
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
                logger.exception("RestDaysSignal failed for match %s", mid)
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

        date_str = _extract_date(match)
        if not date_str:
            result[mid] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": "no_date_info",
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
            logger.exception("RestDaysSignal failed for match %s", mid)
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
