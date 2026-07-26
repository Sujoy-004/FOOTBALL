"""Team synergy (scoring efficiency) signal computation.

DEPRECATED — Delegates to football_core.signals.team_synergy.TeamSynergySignal.
Kept for backward compatibility with legacy cache-dict format.

Formula (consolidated):
  For each team, from context.played_results:
    avg_scored   = sum(home/away goals scored) / n_matches
    avg_conceded = sum(home/away goals conceded) / n_matches
    synergy      = avg_scored / max(avg_scored + avg_conceded, 0.01)
  home_prob = sigmoid(k * (synergy_a - synergy_b) * 3)

Data sources:
  played + played_groups — ALL available match results (passed via context.played_results).

Threat model:
- T-15-XX: Team with 0 played matches → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timedelta, timezone

from football_core.signal import PredictionContext
from football_core.signals.team_synergy import TeamSynergySignal

logger = logging.getLogger(__name__)


TEAM_SYNERGY_K: float = 2.0
"""Kept for backward compatibility (core signal uses its own k default)."""

DRAW_PROB: float = 0.25
"""Kept for backward compatibility."""


def compute_team_synergy_signal(
    teams: dict,
    groups: dict,
    played: dict | None = None,
    played_groups: dict | None = None,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute team synergy signal — delegates to TeamSynergySignal.

    For each match with a known team_a/team_b pairing, computes via
    TeamSynergySignal::

        synergy_a = avg_scored / max(avg_scored + avg_conceded, 0.01)
        home_prob = sigmoid(k * (synergy_a - synergy_b) * 3)
        draw_prob = 0.25

    Args:
        teams: Dict mapping team name → dict (passed through for API consistency).
        groups: Groups dict (with optional 'groups' wrapper key).
        played: Dict of played bracket matches. Auto-loads if None.
        played_groups: Dict of played group matches. Auto-loads if None.
        bracket: Optional bracket list. Auto-loads if None.

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry (1h TTL).
            matches (dict): Match-ID → signal entry mapping.
    """
    now = datetime.now(timezone.utc)

    # Auto-load data if not provided
    if played is None:
        from src.state import load_played
        played = load_played()

    if played_groups is None:
        from src.state import load_played_groups
        played_groups = load_played_groups()

    if bracket is None:
        try:
            from src.state import load_bracket
            bracket = load_bracket()
        except Exception:
            logger.warning("Could not load bracket data for team synergy signal", exc_info=True)
            bracket = []

    # Build played_results from all available data
    played_results: list[dict] = list(played.values())
    if played_groups:
        played_results.extend(played_groups.values())

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    # Build all_matches list
    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        if m.get("team_a") is not None and m.get("team_b") is not None:
            all_matches.append(m)

    signal = TeamSynergySignal()
    context = PredictionContext(
        fixtures=list(all_matches),
        elo_ratings={},
        played_results=played_results,
    )

    result: dict[str, dict] = {}

    # Process group matches
    for g in groups_data.values():
        for match in g.get("matches", []):
            mid = match.get("match_id")
            if not mid:
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
                logger.exception("TeamSynergySignal failed for match %s", mid)
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
            logger.exception("TeamSynergySignal failed for match %s", mid)
            result[mid] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": "error",
            }

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }
