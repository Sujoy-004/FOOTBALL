"""Elo odds signal computation — delegates to RefinedEloSignal from football_core.

DEPRECATED — Use football_core.signals.refined_elo.RefinedEloSignal instead.
Kept for backward compatibility with legacy cache-dict format.

Computes an odds signal for each match based on the Elo rating difference
between the two teams, including home advantage.

Delegates to RefinedEloSignal:
  home_prob = expected_score(home_elo, away_elo, home_advantage=100)
  draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35

Data sources:
  teams dict — Elo ratings per team (passed via context.elo_ratings).

Threat model:
- T-15-XX: Missing team (not in teams data) → available: false with reason
- T-15-XX: Bracket match with unresolved team_a/team_b → silently skipped
- T-15-XX: Probability clamped to [1e-15, 1-1e-15] to avoid log(0) downstream
"""

import logging
from datetime import datetime, timedelta, timezone

from football_core.signal import PredictionContext
from football_core.signals.refined_elo import RefinedEloSignal

logger = logging.getLogger(__name__)


def compute_elo_odds_signal(
    teams: dict,
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute Elo odds signal — delegates to RefinedEloSignal.

    For each match with a known team_a/team_b pairing, computes via
    RefinedEloSignal::

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

    if bracket is None:
        try:
            from src.state import load_bracket
            bracket = load_bracket()
        except Exception:
            logger.warning("Could not load bracket data for elo odds signal", exc_info=True)
            bracket = []

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        if m.get("team_a") is not None and m.get("team_b") is not None:
            all_matches.append(m)

    elo_ratings = {name: data["elo"] for name, data in teams.items()}
    context = PredictionContext(
        fixtures=list(all_matches),
        elo_ratings=elo_ratings,
    )

    signal = RefinedEloSignal(home_advantage=100)

    result: dict[str, dict] = {}

    for g in groups_data.values():
        for match in g.get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            _process_match(mid, match, signal, context, now, result)

    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue
        _process_match(mid, match, signal, context, now, result)

    expires_at = (now + timedelta(hours=24)).isoformat()
    return {
        "fetched_at": now.isoformat(),
        "expires_at": expires_at,
        "matches": result,
    }


def _process_match(
    mid: str,
    match: dict,
    signal: RefinedEloSignal,
    context: PredictionContext,
    now: datetime,
    result: dict[str, dict],
) -> None:
    """Process a single match through the signal and populate result dict."""
    team_a = match.get("team_a", "")
    team_b = match.get("team_b", "")

    if team_a not in (context.elo_ratings or {}):
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_not_found: {team_a}",
        }
        return
    if team_b not in (context.elo_ratings or {}):
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_not_found: {team_b}",
        }
        return

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
        logger.exception("RefinedEloSignal failed for match %s", mid)
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": "error",
        }
