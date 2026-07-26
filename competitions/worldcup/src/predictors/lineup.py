"""Lineup strength (market value log-ratio) signal computation.

DEPRECATED — Use football_core.signals.lineup.LineupStrengthSignal instead.
Kept for backward compatibility with legacy refresh_from_api().

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
from datetime import datetime, timedelta, timezone

from football_core.signal import PredictionContext
from football_core.signals.lineup import LineupStrengthSignal

logger = logging.getLogger(__name__)


def compute_lineup_signal(
    groups: dict,
    team_values: dict | None = None,
    bracket: list[dict] | None = None,
    k_factor: float | None = None,
) -> dict:
    """Compute lineup strength signal — delegates to LineupStrengthSignal.

    For each match with a known team_a/team_b pairing, computes via
    LineupStrengthSignal::

        strength_delta = ln(value_a / value_b)
        p = sigmoid(k * strength_delta)

    Args:
        groups: Groups dict (with optional 'groups' wrapper key).
        team_values: Pre-loaded dict of team → market value (EUR).
                     Auto-loads from state if None.
        bracket: Optional bracket list. Auto-loads if None.
        k_factor: Sigmoid steepness. Defaults to DEFAULT_LINEUP_K (0.35).

    Returns:
        Cache dict with keys:
            fetched_at (str): ISO timestamp of computation.
            expires_at (str): ISO timestamp of expiry (1h TTL).
            matches (dict): Match-ID → signal entry mapping.
    """
    now = datetime.now(timezone.utc)

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

    k = k_factor if k_factor is not None else 0.35
    signal = LineupStrengthSignal(k=k)

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        if m.get("team_a") is not None and m.get("team_b") is not None:
            all_matches.append(m)

    context = PredictionContext(
        fixtures=list(all_matches),
        elo_ratings={},
        squad_values=team_values,
    )

    result: dict[str, dict] = {}

    for g in groups_data.values():
        for match in g.get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            _process_match(mid, match, signal, context, now, result, team_values)

    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        mid = match.get("match_id")
        if not mid:
            continue
        _process_match(mid, match, signal, context, now, result, team_values)

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }


def _process_match(
    mid: str,
    match: dict,
    signal: LineupStrengthSignal,
    context: PredictionContext,
    now: datetime,
    result: dict[str, dict],
    team_values: dict,
) -> None:
    """Process a single match through the signal and populate result dict."""
    team_a = match.get("team_a", "")
    team_b = match.get("team_b", "")

    if team_a not in team_values:
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_value_not_found: {team_a}",
        }
        return
    if team_b not in team_values:
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"team_value_not_found: {team_b}",
        }
        return

    val_a = team_values[team_a]
    val_b = team_values[team_b]
    if not isinstance(val_a, (int, float)) or val_a <= 0:
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"non_positive_value: {team_a}={val_a!r}",
        }
        return
    if not isinstance(val_b, (int, float)) or val_b <= 0:
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"non_positive_value: {team_b}={val_b!r}",
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
        logger.exception("LineupStrengthSignal failed for match %s", mid)
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": "error",
        }
