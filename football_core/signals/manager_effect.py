"""Manager Effect signal — win rate and tactical style from manager profiles.

Computes a manager quality signal from:
  win_pct — historical win percentage
  preferred_formation / formations_used — tactical flexibility bonus
  team_style — attacking/defensive/balanced modifier

Formula:
  base_rating = win_pct
  tactical_bonus = len(formations_used) * FORMATION_BONUS_PER
  effective_rating = base_rating + tactical_bonus + style_modifier
  p = sigmoid(k * (rating_a - rating_b))

Both a standalone compute function and a Signal protocol class are provided.
"""

import logging
import math

from football_core.math_utils import sigmoid
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)

DEFAULT_K: float = 2.0
"""Sigmoid steepness for manager effect signal.
win_pct ∈ [0, 1] so rating difference ∈ [-1, +1].
k=2.0 maps diff=0.5 to sigmoid(1.0)=0.73."""

FORMATION_BONUS_PER: float = 0.02
"""Small rating bonus per distinct formation used (tactical flexibility)."""

STYLE_MODIFIERS: dict[str, float] = {
    "attacking": 0.02,
    "defensive": -0.02,
    "balanced": 0.0,
}
"""Rating modifier for manager's team_style profile."""


def compute_manager_rating(profile: dict) -> float:
    """Compute composite manager quality rating from a manager profile dict.

    Args:
        profile: Manager profile dict with 'win_pct', 'formations_used', 'team_style'.

    Returns:
        Manager quality rating (0 to ~1.1 max with bonuses).
    """
    win_pct = profile.get("win_pct", 0.0)
    if not isinstance(win_pct, (int, float)):
        win_pct = 0.0

    formations = profile.get("formations_used", [])
    if not isinstance(formations, list):
        formations = []
    tactical_bonus = len(formations) * FORMATION_BONUS_PER

    team_style = profile.get("team_style", "balanced")
    if not isinstance(team_style, str):
        team_style = "balanced"
    style_mod = STYLE_MODIFIERS.get(team_style, 0.0)

    return win_pct + tactical_bonus + style_mod


def compute_manager_probability(
    rating_a: float,
    rating_b: float,
    k: float = DEFAULT_K,
) -> float:
    """Compute match probability from manager rating difference.

    Args:
        rating_a: Manager rating for team A (home).
        rating_b: Manager rating for team B (away).
        k: Sigmoid steepness.

    Returns:
        Probability that team A wins based on manager quality difference.
    """
    diff = rating_a - rating_b
    return sigmoid(k * diff)


def compute_manager_signal_for_match(
    team_a: str,
    team_b: str,
    manager_data: dict[str, dict],
) -> dict:
    """Compute manager effect signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        manager_data: Dict mapping team name → manager profile dict.

    Returns:
        Signal entry dict with keys: probability, available, reason (if unavailable).
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    prof_a = manager_data.get(team_a)
    prof_b = manager_data.get(team_b)

    if not prof_a or not prof_b:
        missing = []
        if not prof_a:
            missing.append(team_a)
        if not prof_b:
            missing.append(team_b)
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"manager_data_not_found: {', '.join(missing)}",
        }

    rating_a = compute_manager_rating(prof_a)
    rating_b = compute_manager_rating(prof_b)

    p = compute_manager_probability(rating_a, rating_b)

    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "timestamp": now.isoformat(),
        "available": True,
        "manager_rating_a": round(rating_a, 4),
        "manager_rating_b": round(rating_b, 4),
    }


def compute_manager_signal(
    manager_data: dict[str, dict],
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute manager effect signal for all group and bracket matches.

    Args:
        manager_data: Dict mapping team name → manager profile dict.
        groups: Groups dict (with optional 'groups' wrapper key).
        bracket: Optional bracket match list.

    Returns:
        Cache dict with keys: fetched_at, expires_at, matches.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups
    result: dict[str, dict] = {}

    for group_letter in groups_data:
        for match in groups_data[group_letter].get("matches", []):
            mid = match.get("match_id")
            if not mid:
                continue
            entry = compute_manager_signal_for_match(
                match["team_a"], match["team_b"], manager_data,
            )
            result[mid] = entry

    if bracket:
        for match in bracket:
            if match.get("team_a") is None or match.get("team_b") is None:
                continue
            mid = match.get("match_id")
            if not mid:
                continue
            entry = compute_manager_signal_for_match(
                match["team_a"], match["team_b"], manager_data,
            )
            result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }


class ManagerEffectSignal(Signal):
    """Manager effect signal — win rate + tactical flexibility composite.

    Requires context.manager_data to be populated with team→profile dicts.
    """

    name: str = "manager_effect"

    def __init__(self, k: float = DEFAULT_K) -> None:
        self._k = k

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        manager_data = context.manager_data or {}

        prof_a = manager_data.get(team_a)
        prof_b = manager_data.get(team_b)

        if not prof_a or not prof_b:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        rating_a = compute_manager_rating(prof_a)
        rating_b = compute_manager_rating(prof_b)
        home_prob = compute_manager_probability(rating_a, rating_b, self._k)

        draw_prob = 0.25
        away_prob = 1.0 - home_prob - draw_prob

        return SignalOutput(home_prob, draw_prob, away_prob)
