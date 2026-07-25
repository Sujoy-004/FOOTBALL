"""Rest days (recovery advantage) signal computation.

DEPRECATED — Use football_core.signals.rest_days.RestDaysSignal instead.
Kept for backward compatibility with legacy refresh_from_api().

Computes a rest advantage signal for each match based on the number of
days since each team's most recent fixture.

Formula:
  rest_a = days since team_a's previous match
  rest_b = days since team_b's previous match
  rest_ratio = rest_a / max(rest_a + rest_b, 0.01)
  home_prob = sigmoid(k * (rest_ratio - 0.5) * 2)
  draw_prob = 0.25

Where k = 1.0. Dates come from the match dict's event_date/date/completed_at
fields. If no date info is available for a match, the signal is marked
unavailable.

Data sources:
  group fixture schedule (from groups dict) + bracket — all match dates.

Threat model:
- T-15-XX: Match with no date info → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timedelta, timezone

from src.math_utils import sigmoid as _sigmoid

logger = logging.getLogger(__name__)


# ─── Constants ──────────────────────────────────────────────────────────────

REST_DAYS_K: float = 1.0
"""Sigmoid steepness for rest days signal."""

DRAW_PROB: float = 0.25
"""Fixed draw probability for rest days signal."""

DEFAULT_REST_DAYS: int = 7
"""Default rest days to use when no date info is available."""
# ─── Helpers ────────────────────────────────────────────────────────────────


def _extract_date(match: dict) -> str | None:
    """Extract date string from a match dict.

    Checks event_date, date, and completed_at fields in order.

    Args:
        match: Match dict.

    Returns:
        Date string if found, None otherwise.
    """
    return (match.get("event_date") or
            match.get("date") or
            match.get("completed_at"))


def _compute_rest_days_for_team(
    team_name: str,
    match_date: str,
    team_fixtures: dict[str, list[tuple[str, str]]],
) -> int:
    """Compute rest days for a team leading into a given match date.

    Args:
        team_name: Name of the team.
        match_date: ISO date string of the current match.
        team_fixtures: Dict mapping team_name → list of (match_id, date) tuples
                       sorted by date descending.

    Returns:
        Number of rest days (integer). Defaults to DEFAULT_REST_DAYS if no
        previous match found.
    """
    fixtures = team_fixtures.get(team_name, [])
    if not fixtures:
        return DEFAULT_REST_DAYS

    for mid, date_str in fixtures:
        if date_str < match_date:
            # Found the most recent previous match
            try:
                prev = datetime.fromisoformat(date_str)
                current = datetime.fromisoformat(match_date)
                diff = (current - prev).days
                return max(1, diff)
            except (ValueError, TypeError):
                continue

    return DEFAULT_REST_DAYS


def _build_fixture_map(
    groups_data: dict,
    bracket: list[dict],
) -> dict[str, list[tuple[str, str]]]:
    """Build a mapping of team_name → list of (match_id, date) sorted descending.

    Merges group stage and bracket fixtures.

    Args:
        groups_data: Groups dict (with optional 'groups' wrapper key resolved).
        bracket: List of bracket match dicts.

    Returns:
        Dict mapping team_name → list of (match_id, date) tuples sorted by
        date descending.
    """
    team_fixtures: dict[str, list[tuple[str, str]]] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            team_a = match.get("team_a")
            team_b = match.get("team_b")
            date_str = _extract_date(match)
            mid = match.get("match_id", "?")

            if team_a and date_str:
                team_fixtures.setdefault(team_a, []).append((mid, date_str))
            if team_b and date_str:
                team_fixtures.setdefault(team_b, []).append((mid, date_str))

    # Process bracket matches
    for match in bracket:
        team_a = match.get("team_a")
        team_b = match.get("team_b")
        date_str = _extract_date(match)
        mid = match.get("match_id", "?")

        if not team_a or not team_b:
            continue

        if date_str:
            team_fixtures.setdefault(team_a, []).append((mid, date_str))
            team_fixtures.setdefault(team_b, []).append((mid, date_str))

    # Sort each team's fixtures by date descending
    def _sort_key(item: tuple[str, str]) -> str:
        return item[1]

    for team in team_fixtures:
        team_fixtures[team].sort(key=_sort_key, reverse=True)

    return team_fixtures


def _has_date(match: dict) -> bool:
    """Check if a match dict has any date information."""
    return bool(_extract_date(match))


def _compute_match_rest_days_signal(
    team_a: str,
    team_b: str,
    match_date: str,
    team_fixtures: dict[str, list[tuple[str, str]]],
) -> dict:
    """Compute rest days signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        match_date: ISO date string of the current match.
        team_fixtures: Pre-built mapping from _build_fixture_map.

    Returns:
        Signal entry dict with keys: probability, available, reason (if unavailable).
    """
    now = datetime.now(timezone.utc)

    rest_a = _compute_rest_days_for_team(team_a, match_date, team_fixtures)
    rest_b = _compute_rest_days_for_team(team_b, match_date, team_fixtures)

    rest_ratio = rest_a / max(rest_a + rest_b, 0.01)
    p = _sigmoid(REST_DAYS_K * (rest_ratio - 0.5) * 2)

    # Clamp to [1e-15, 1-1e-15]
    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "draw_probability": DRAW_PROB,
        "timestamp": now.isoformat(),
        "available": True,
    }


# ─── Public API ─────────────────────────────────────────────────────────────


def compute_rest_days_signal(
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute rest days signal for all group and bracket matches.

    For each match with a known team_a/team_b pairing and date info, computes::

        rest_a = days since team_a's previous match
        rest_b = days since team_b's previous match
        rest_ratio = rest_a / max(rest_a + rest_b, 0.01)
        p = sigmoid(k * (rest_ratio - 0.5) * 2)
        draw_prob = 0.25

    Args:
        groups: Groups dict (with optional 'groups' wrapper key).
        bracket: Optional bracket list. Auto-loads if None.

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry (1h TTL).
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

    groups_data = groups.get("groups", groups)

    # Build fixture map from all available match dates
    team_fixtures = _build_fixture_map(groups_data, bracket)

    result: dict[str, dict] = {}

    # Process group matches
    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue

            team_a = match.get("team_a")
            team_b = match.get("team_b")
            date_str = _extract_date(match)

            if not date_str:
                result[mid] = {
                    "probability": None,
                    "timestamp": now.isoformat(),
                    "available": False,
                    "reason": "no_date_info",
                }
                continue

            entry = _compute_match_rest_days_signal(
                team_a, team_b, date_str, team_fixtures,
            )
            result[mid] = entry

    # Process bracket matches — skip unresolved slots (team_a or team_b is None)
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue

        team_a = match.get("team_a")
        team_b = match.get("team_b")
        date_str = _extract_date(match)

        if not date_str:
            result[mid] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": "no_date_info",
            }
            continue

        entry = _compute_match_rest_days_signal(
            team_a, team_b, date_str, team_fixtures,
        )
        result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }
