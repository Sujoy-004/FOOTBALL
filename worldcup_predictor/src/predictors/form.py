"""Form (Elo-based residual) signal computation.

Computes a form signal for each match based on the difference in average
Elo residuals between the two teams over their most recent matches.

Formula:
  residual = actual - expected_score (per match, per team)
  form_delta = avg(home_residuals) - avg(away_residuals)
  p = sigmoid(k * form_delta)

Where k = DEFAULT_FORM_K (1.0) and the rolling window is FORM_WINDOW_SIZE (5).
If either team has 0 played matches, the signal is marked unavailable.

Data sources:
  played + played_groups — ALL available match results.

Threat model:
- T-15-01: Missing team (not in teams data) → available: false with reason
- T-15-02: Team with 0 played matches → available: false with reason
- T-15-03: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-04: Graceful ledger upsert failure (try/except with logger.warning)
- T-15-05: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
import math
from datetime import datetime, timedelta, timezone

from src import constants
from src.elo import expected_score

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _sigmoid(x: float) -> float:
    """Compute sigmoid function using math.exp (pure stdlib).

    Args:
        x: Input value (real number).

    Returns:
        Sigmoid output in (0, 1).
    """
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _compute_residual(match: dict, teams: dict) -> tuple[float, float, str | None]:
    """Compute Elo residuals for both teams from a played match result.

    Actual score from team_a's perspective:
      - team_a wins → actual_a = 1.0
      - draw (winner is None or is_draw=True) → actual_a = 0.5
      - team_b wins → actual_a = 0.0

    residual_a = actual_a - expected_score(elo_a, elo_b, home_advantage=0)
    residual_b = -residual_a (zero-sum property of Elo).

    Args:
        match: Played match dict with keys: team_a, team_b, winner,
               home_score, away_score, is_draw (optional).
        teams: Dict mapping team name → dict with 'elo' key.

    Returns:
        Tuple of (residual_a, residual_b, error_reason).
        If either team is missing from teams data, returns (0.0, 0.0, reason).
    """
    team_a_name = match.get("team_a")
    team_b_name = match.get("team_b")

    if not team_a_name or not team_b_name:
        return 0.0, 0.0, "missing_team_name"

    if team_a_name not in teams:
        return 0.0, 0.0, f"team_not_in_teams_data: {team_a_name}"
    if team_b_name not in teams:
        return 0.0, 0.0, f"team_not_in_teams_data: {team_b_name}"

    elo_a = teams[team_a_name]["elo"]
    elo_b = teams[team_b_name]["elo"]
    expected_a = expected_score(elo_a, elo_b, home_advantage=0)

    winner = match.get("winner")
    is_draw = match.get("is_draw", False)

    if is_draw or winner is None:
        actual_a = 0.5
    elif winner == team_a_name:
        actual_a = 1.0
    elif winner == team_b_name:
        actual_a = 0.0
    else:
        # Winner doesn't match either team — treat as draw (safety)
        logger.warning(
            "Unexpected winner %r for match %s vs %s",
            winner, team_a_name, team_b_name,
        )
        actual_a = 0.5

    residual_a = actual_a - expected_a
    residual_b = -residual_a

    return residual_a, residual_b, None


def _build_team_residuals(
    played: dict,
    played_groups: dict,
    teams: dict,
) -> dict[str, list[dict]]:
    """Build mapping of team_name → chronologically-sorted residual entries.

    Merges both played (bracket) and played_groups (group stage) results into
    a single per-team list sorted by recency descending (most recent first).

    Each entry::

        {"residual": float, "completed_at": str}

    Args:
        played: Dict of played bracket match results (match_id → match dict).
        played_groups: Dict of played group match results (match_id → match dict).
        teams: Teams dict with Elo ratings.

    Returns:
        Dict mapping team_name → list of residual entries sorted by
        completed_at descending (most recent first).
    """
    team_residuals: dict[str, list[dict]] = {}

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

        residual_a, residual_b, error = _compute_residual(match, teams)
        if error is not None:
            logger.debug("Skipping residual for match %s: %s",
                         match.get("match_id", "?"), error)
            continue

        completed_at = match.get("completed_at", "")

        team_residuals.setdefault(team_a_name, []).append({
            "residual": residual_a,
            "completed_at": completed_at,
        })
        team_residuals.setdefault(team_b_name, []).append({
            "residual": residual_b,
            "completed_at": completed_at,
        })

    # Sort each team's residuals by recency descending
    for team in team_residuals:
        team_residuals[team].sort(
            key=lambda e: e["completed_at"],
            reverse=True,
        )

    return team_residuals


def _compute_match_form_signal(
    team_a: str,
    team_b: str,
    team_residuals: dict[str, list[dict]],
    teams: dict,
    k: float,
    window: int,
) -> dict:
    """Compute form signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        team_residuals: Pre-built mapping from _build_team_residuals.
        teams: Teams dict with Elo ratings.
        k: Sigmoid steepness (DEFAULT_FORM_K or overridden).
        window: Rolling window size (FORM_WINDOW_SIZE or overridden).

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

    residuals_a = team_residuals.get(team_a, [])
    residuals_b = team_residuals.get(team_b, [])

    if not residuals_a:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"no_match_history: {team_a}",
        }
    if not residuals_b:
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"no_match_history: {team_b}",
        }

    # Average residuals over the rolling window (use all available if < window)
    recent_a = residuals_a[:window]
    recent_b = residuals_b[:window]
    avg_home = sum(e["residual"] for e in recent_a) / len(recent_a)
    avg_away = sum(e["residual"] for e in recent_b) / len(recent_b)

    form_delta = avg_home - avg_away
    p = _sigmoid(k * form_delta)

    # Clamp to [1e-15, 1-1e-15] — T-15-05
    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "timestamp": now.isoformat(),
        "available": True,
    }


# ─── Public API ─────────────────────────────────────────────────────────────


def compute_form_signal(
    teams: dict,
    groups: dict,
    played: dict | None = None,
    played_groups: dict | None = None,
    bracket: list[dict] | None = None,
    k_factor: float | None = None,
    form_window: int | None = None,
) -> dict:
    """Compute form-based Elo residual signal for all group and bracket matches.

    For each match with a known team_a/team_b pairing, computes the form
    signal as::

        form_delta = avg(team_a_residuals) - avg(team_b_residuals)
        p = sigmoid(k * form_delta)

    where residuals are ``actual - expected_score`` from played matches.

    Args:
        teams: Dict mapping team name → dict with 'elo' key.
        groups: Groups dict (with optional 'groups' wrapper key).
        played: Dict of played bracket matches. Auto-loads if None.
        played_groups: Dict of played group matches. Auto-loads if None.
        bracket: Optional bracket list. Auto-loads if None.
        k_factor: Sigmoid steepness. Defaults to ``constants.DEFAULT_FORM_K``.
        form_window: Rolling window. Defaults to ``constants.FORM_WINDOW_SIZE``.

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
            logger.warning("Could not load bracket data for form signal", exc_info=True)
            bracket = []

    k = k_factor if k_factor is not None else constants.DEFAULT_FORM_K
    window = form_window if form_window is not None else constants.FORM_WINDOW_SIZE

    # Build per-team residual history from all played matches
    team_residuals = _build_team_residuals(played, played_groups, teams)

    groups_data = groups.get("groups", groups)
    result: dict[str, dict] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            entry = _compute_match_form_signal(
                match["team_a"], match["team_b"],
                team_residuals, teams, k, window,
            )
            result[mid] = entry

    # Process bracket matches — skip unresolved slots (team_a or team_b is None)
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue
        entry = _compute_match_form_signal(
            match["team_a"], match["team_b"],
            team_residuals, teams, k, window,
        )
        result[mid] = entry

    # Upsert into permanent prediction ledger — T-15-04
    if result:
        try:
            from src.state import ledger_upsert
            for mid, entry in result.items():
                ledger_upsert(mid, "form", entry)
        except Exception:
            logger.warning("Failed to upsert form signal into prediction ledger", exc_info=True)

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }
