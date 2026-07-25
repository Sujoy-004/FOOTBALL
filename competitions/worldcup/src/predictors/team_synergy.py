"""Team synergy (scoring efficiency) signal computation.

DEPRECATED — Use football_core.signals.synergy.TeamSynergySignal instead.
Kept for backward compatibility with legacy refresh_from_api().

Computes a synergy signal for each match based on each team's historical
scoring efficiency (goals scored vs goals conceded).

Formula:
  synergy = avg_scored / max(avg_scored + avg_conceded, 0.01)
  home_prob = sigmoid(k * (synergy_a - synergy_b) * 3)
  draw_prob = 0.25

Where k = 2.0. If either team has 0 played matches, the signal is marked
unavailable.

Data sources:
  played + played_groups — ALL available match results.

Threat model:
- T-15-XX: Team with 0 played matches → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timedelta, timezone

from src.math_utils import sigmoid as _sigmoid

logger = logging.getLogger(__name__)


# ─── Constants ──────────────────────────────────────────────────────────────

TEAM_SYNERGY_K: float = 2.0
"""Sigmoid steepness for team synergy signal."""

DRAW_PROB: float = 0.25
"""Fixed draw probability for team synergy signal."""


# ─── Helpers ────────────────────────────────────────────────────────────────


def _compute_team_synergy(
    played: dict,
    played_groups: dict,
) -> dict[str, dict]:
    """Compute synergy metrics (avg scored, avg conceded) per team.

    Merges both played (bracket) and played_groups (group stage) results into
    a single per-team aggregate.

    Args:
        played: Dict of played bracket match results (match_id → match dict).
        played_groups: Dict of played group match results (match_id → match dict).

    Returns:
        Dict mapping team_name → {"avg_scored": float, "avg_conceded": float, "matches": int}.
    """
    team_stats: dict[str, dict] = {}

    # Merge both data sources
    all_played: dict[str, dict] = {}
    all_played.update(played)
    all_played.update(played_groups)

    for match in all_played.values():
        if not isinstance(match, dict):
            continue

        team_a_name = match.get("team_a")
        team_b_name = match.get("team_b")
        score_a = match.get("home_score", 0) or 0
        score_b = match.get("away_score", 0) or 0

        if not team_a_name or not team_b_name:
            continue

        if team_a_name not in team_stats:
            team_stats[team_a_name] = {"total_scored": 0, "total_conceded": 0, "matches": 0}
        if team_b_name not in team_stats:
            team_stats[team_b_name] = {"total_scored": 0, "total_conceded": 0, "matches": 0}

        team_stats[team_a_name]["total_scored"] += score_a
        team_stats[team_a_name]["total_conceded"] += score_b
        team_stats[team_a_name]["matches"] += 1

        team_stats[team_b_name]["total_scored"] += score_b
        team_stats[team_b_name]["total_conceded"] += score_a
        team_stats[team_b_name]["matches"] += 1

    result: dict[str, dict] = {}
    for team, stats in team_stats.items():
        n = stats["matches"]
        result[team] = {
            "avg_scored": stats["total_scored"] / n if n > 0 else 0.0,
            "avg_conceded": stats["total_conceded"] / n if n > 0 else 0.0,
            "matches": n,
        }

    return result


def _compute_match_synergy_signal(
    team_a: str,
    team_b: str,
    team_synergies: dict[str, dict],
) -> dict:
    """Compute team synergy signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        team_synergies: Pre-built mapping from _compute_team_synergy.

    Returns:
        Signal entry dict with keys: probability, available, reason (if unavailable).
    """
    now = datetime.now(timezone.utc)

    stats_a = team_synergies.get(team_a)
    stats_b = team_synergies.get(team_b)

    if stats_a is None or stats_a["matches"] == 0:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"no_match_history: {team_a}",
        }
    if stats_b is None or stats_b["matches"] == 0:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"no_match_history: {team_b}",
        }

    synergy_a = stats_a["avg_scored"] / max(stats_a["avg_scored"] + stats_a["avg_conceded"], 0.01)
    synergy_b = stats_b["avg_scored"] / max(stats_b["avg_scored"] + stats_b["avg_conceded"], 0.01)

    p = _sigmoid(TEAM_SYNERGY_K * (synergy_a - synergy_b) * 3)

    # Clamp to [1e-15, 1-1e-15]
    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "draw_probability": DRAW_PROB,
        "timestamp": now.isoformat(),
        "available": True,
    }


# ─── Public API ─────────────────────────────────────────────────────────────


def compute_team_synergy_signal(
    teams: dict,
    groups: dict,
    played: dict | None = None,
    played_groups: dict | None = None,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute team synergy signal for all group and bracket matches.

    For each match with a known team_a/team_b pairing, computes::

        synergy = avg_scored / max(avg_scored + avg_conceded, 0.01)
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

    # Build per-team synergy from all played matches
    team_synergies = _compute_team_synergy(played, played_groups)

    groups_data = groups.get("groups", groups)
    result: dict[str, dict] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            entry = _compute_match_synergy_signal(
                match["team_a"], match["team_b"],
                team_synergies,
            )
            result[mid] = entry

    # Process bracket matches — skip unresolved slots (team_a or team_b is None)
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue
        entry = _compute_match_synergy_signal(
            match["team_a"], match["team_b"],
            team_synergies,
        )
        result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }
