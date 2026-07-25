"""Elo odds signal computation.

DEPRECATED — Use football_core.signals.elo.EloSignal instead.
Kept for backward compatibility with legacy refresh_from_api().

Computes an odds signal for each match based on the Elo rating difference
between the two teams, including home advantage.

Formula:
  home_prob = expected_score(home_elo, away_elo, home_advantage=100)
  draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35
  away_prob = 1.0 - home_prob - draw_prob

Data sources:
  teams dict — Elo ratings per team (already passed in).
  bracket — resolved bracket matches (auto-loaded if None).

Threat model:
- T-15-XX: Missing team (not in teams data) → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timedelta, timezone

from src import constants
from src.elo import expected_score

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _compute_match_elo_signal(
    team_a: str,
    team_b: str,
    teams: dict,
) -> dict:
    """Compute Elo odds signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        teams: Dict mapping team name → dict with 'elo' key.

    Returns:
        Signal entry dict with keys: probability, available, reason (if unavailable).
    """
    now = datetime.now(timezone.utc)

    if team_a not in teams:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_not_found: {team_a}",
        }
    if team_b not in teams:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_not_found: {team_b}",
        }

    elo_a = teams[team_a]["elo"]
    elo_b = teams[team_b]["elo"]

    home_prob = expected_score(elo_a, elo_b, home_advantage=100)
    draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35

    # Clamp to [1e-15, 1-1e-15]
    p = max(1e-15, min(1 - 1e-15, home_prob))

    return {
        "probability": p,
        "timestamp": now.isoformat(),
        "available": True,
        "draw_probability": draw_prob,
    }


# ─── Public API ─────────────────────────────────────────────────────────────


def compute_elo_odds_signal(
    teams: dict,
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute Elo odds signal for all group and bracket matches.

    For each match with a known team_a/team_b pairing, computes::

        home_prob = expected_score(home_elo, away_elo, home_advantage=100)
        draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35

    Args:
        teams: Dict mapping team name → dict with 'elo' key.
        groups: Groups dict (with optional 'groups' wrapper key).
        bracket: Optional bracket list. Auto-loads if None.

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry (24h TTL).
            matches (dict): Match-ID → signal entry mapping.
    """
    now = datetime.now(timezone.utc)

    # Auto-load data if not provided
    if bracket is None:
        try:
            from src.state import load_bracket
            bracket = load_bracket()
        except Exception:
            logger.warning("Could not load bracket data for elo odds signal", exc_info=True)
            bracket = []

    groups_data = groups.get("groups", groups)
    result: dict[str, dict] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            entry = _compute_match_elo_signal(
                match["team_a"], match["team_b"],
                teams,
            )
            result[mid] = entry

    # Process bracket matches — skip unresolved slots (team_a or team_b is None)
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue
        entry = _compute_match_elo_signal(
            match["team_a"], match["team_b"],
            teams,
        )
        result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=constants.CATBOOST_CACHE_TTL_HOURS)).isoformat(),
        "matches": result,
    }
