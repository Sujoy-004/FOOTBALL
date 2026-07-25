"""Rolling form (exponentially weighted recent results) signal computation.

DEPRECATED — Use football_core.signals.rolling_form.RollingFormSignal instead.
Kept for backward compatibility with legacy refresh_from_api().

NOTE: This is a DIFFERENT signal from form.py (which is Elo-residual based).
This signal computes form as a weighted average of recent match outcomes
with exponential decay, mapped through Elo expected_score.

Formula:
  weight = 0.9^k where k = recency rank (0 = most recent)
  weighted_outcome = win=1.0, draw=0.5, loss=0.0 (per match)
  form = weighted average of outcomes for each team
  p = expected_score(form_a * 100 + 1500, form_b * 100 + 1500, home_advantage=0)

Data sources:
  played + played_groups — ALL available match results.

Threat model:
- T-15-XX: Team with 0 played matches → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timedelta, timezone

from src.elo import expected_score
from src.math_utils import sigmoid as _sigmoid

logger = logging.getLogger(__name__)


# ─── Constants ──────────────────────────────────────────────────────────────

FORM_DECAY: float = 0.9
"""Exponential decay factor per recency rank (0.9^k)."""


# ─── Helpers ────────────────────────────────────────────────────────────────


def _compute_outcome_for_team(match: dict, team_name: str) -> float:
    """Compute match outcome from the perspective of the given team.

    Args:
        match: Played match dict with keys: team_a, team_b, winner, is_draw.
        team_name: Name of the team whose perspective to use.

    Returns:
        1.0 for win, 0.5 for draw, 0.0 for loss.
    """
    winner = match.get("winner")
    is_draw = match.get("is_draw", False)

    if is_draw or winner is None:
        return 0.5
    if winner == team_name:
        return 1.0
    return 0.0


def _build_team_form_history(
    played: dict,
    played_groups: dict,
) -> dict[str, list[dict]]:
    """Build mapping of team_name → recency-sorted form entries.

    Merges both played (bracket) and played_groups (group stage) results into
    a single per-team list sorted by recency descending (most recent first).

    Each entry::

        {"outcome": float, "completed_at": str}

    Args:
        played: Dict of played bracket match results (match_id → match dict).
        played_groups: Dict of played group match results (match_id → match dict).

    Returns:
        Dict mapping team_name → list of form entries sorted by
        completed_at descending (most recent first).
    """
    team_entries: dict[str, list[dict]] = {}

    # Merge both data sources
    all_played: dict[str, dict] = {}
    all_played.update(played)
    all_played.update(played_groups)

    for match in all_played.values():
        if not isinstance(match, dict):
            continue

        team_a_name = match.get("team_a")
        team_b_name = match.get("team_b")

        if not team_a_name or not team_b_name:
            continue

        outcome_a = _compute_outcome_for_team(match, team_a_name)
        outcome_b = _compute_outcome_for_team(match, team_b_name)

        completed_at = match.get("completed_at", "")

        team_entries.setdefault(team_a_name, []).append({
            "outcome": outcome_a,
            "completed_at": completed_at,
        })
        team_entries.setdefault(team_b_name, []).append({
            "outcome": outcome_b,
            "completed_at": completed_at,
        })

    # Sort each team's entries by recency descending
    for team in team_entries:
        team_entries[team].sort(
            key=lambda e: e["completed_at"],
            reverse=True,
        )

    return team_entries


def _compute_team_form(entries: list[dict]) -> float:
    """Compute exponentially-weighted form average from a team's entries.

    Args:
        entries: List of form entries sorted by recency descending.

    Returns:
        Weighted average form value (0.0 to 1.0).
    """
    if not entries:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0

    for k, entry in enumerate(entries):
        weight = FORM_DECAY ** k
        weighted_sum += entry["outcome"] * weight
        total_weight += weight

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def _compute_match_rolling_form_signal(
    team_a: str,
    team_b: str,
    team_form_history: dict[str, list[dict]],
) -> dict:
    """Compute rolling form signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        team_form_history: Pre-built mapping from _build_team_form_history.

    Returns:
        Signal entry dict with keys: probability, available, reason (if unavailable).
    """
    now = datetime.now(timezone.utc)

    entries_a = team_form_history.get(team_a, [])
    entries_b = team_form_history.get(team_b, [])

    if not entries_a:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"no_match_history: {team_a}",
        }
    if not entries_b:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"no_match_history: {team_b}",
        }

    form_a = _compute_team_form(entries_a)
    form_b = _compute_team_form(entries_b)

    # Map form to Elo-like ratings and compute expected score
    p = expected_score(form_a * 100 + 1500, form_b * 100 + 1500, home_advantage=0)

    # Clamp to [1e-15, 1-1e-15]
    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "timestamp": now.isoformat(),
        "available": True,
    }


# ─── Public API ─────────────────────────────────────────────────────────────


def compute_rolling_form_signal(
    teams: dict,
    groups: dict,
    played: dict | None = None,
    played_groups: dict | None = None,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute rolling form signal for all group and bracket matches.

    For each match with a known team_a/team_b pairing, computes::

        weight = 0.9^k (k = recency rank, 0 = most recent)
        weighted_outcome = win=1.0, draw=0.5, loss=0.0
        form = weighted average of outcomes
        p = expected_score(form_a * 100 + 1500, form_b * 100 + 1500)

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
            logger.warning("Could not load bracket data for rolling form signal", exc_info=True)
            bracket = []

    # Build per-team form history from all played matches
    team_form_history = _build_team_form_history(played, played_groups)

    groups_data = groups.get("groups", groups)
    result: dict[str, dict] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            entry = _compute_match_rolling_form_signal(
                match["team_a"], match["team_b"],
                team_form_history,
            )
            result[mid] = entry

    # Process bracket matches — skip unresolved slots (team_a or team_b is None)
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue
        entry = _compute_match_rolling_form_signal(
            match["team_a"], match["team_b"],
            team_form_history,
        )
        result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }
