"""Rolling form (exponentially weighted recent results) signal computation.

DEPRECATED — Use football_core.signals.rolling_form.RollingFormSignal instead.
Kept for backward compatibility with legacy cache-dict format.

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

from football_core.provider import ResultHistoryProvider
from football_core.signal import PredictionContext
from football_core.signals.rolling_form import RollingFormSignal

logger = logging.getLogger(__name__)


class _PlayedResultsProvider:
    """Adapter wrapping WC played/played_groups dicts as a MatchResultProvider.

    Provides team results from in-memory played match dicts for the
    RollingFormSignal to consume.
    """

    def __init__(self, played: dict[str, dict], played_groups: dict[str, dict]) -> None:
        self._all_played: dict[str, dict] = {}
        self._all_played.update(played)
        self._all_played.update(played_groups)

        self._team_results: dict[str, list[dict]] = {}
        for match in self._all_played.values():
            if not isinstance(match, dict):
                continue
            team_a = match.get("team_a")
            team_b = match.get("team_b")
            completed_at = match.get("completed_at", "")
            for team in (team_a, team_b):
                if team:
                    self._team_results.setdefault(team, []).append({
                        "winner": match.get("winner"),
                        "is_draw": match.get("is_draw", False),
                        "completed_at": completed_at,
                    })
        for team in self._team_results:
            self._team_results[team].sort(
                key=lambda r: r.get("completed_at", ""),
                reverse=True,
            )

    def get_team_results(
        self, team: str, before_date: str, limit: int = 10
    ) -> list[dict]:
        results = self._team_results.get(team, [])
        filtered = [r for r in results if r.get("completed_at", "") < before_date]
        return filtered[:limit]


def compute_rolling_form_signal(
    teams: dict,
    groups: dict,
    played: dict | None = None,
    played_groups: dict | None = None,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute rolling form signal — delegates to RollingFormSignal.

    For each match with a known team_a/team_b pairing, computes via
    RollingFormSignal::

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

    provider = _PlayedResultsProvider(played or {}, played_groups or {})
    signal = RollingFormSignal(result_provider=provider, windows=[5], decay_factor=0.9)

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups

    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        if m.get("team_a") is not None and m.get("team_b") is not None:
            all_matches.append(m)

    context = PredictionContext(fixtures=list(all_matches), elo_ratings={})

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

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }


def _process_match(
    mid: str,
    match: dict,
    signal: RollingFormSignal,
    context: PredictionContext,
    now: datetime,
    result: dict[str, dict],
) -> None:
    """Process a single match through the signal and populate result dict."""
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
        logger.exception("RollingFormSignal failed for match %s", mid)
        result[mid] = {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": "error",
        }
