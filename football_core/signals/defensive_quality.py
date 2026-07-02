"""Defensive Quality signal — clean sheet rate and xGA from manager profiles.

Computes a defensive strength signal from manager-level aggregates:
  clean_sheet_pct — fraction of matches with zero goals conceded
  avg_xg_against — average expected goals conceded per match

Formula:
  defensive_rating = w_cs * clean_sheet_pct + w_xga * (1 - xga_normalized)
  p = sigmoid(k * (rating_a - rating_b))

Both a standalone compute function and a Signal protocol class are provided.
The standalone function is used by the WC cache-dict pipeline.
"""

import logging
import math

from football_core.math_utils import sigmoid
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)

DEFAULT_K: float = 2.0
"""Sigmoid steepness for defensive quality signal.
clean_sheet_pct ∈ [0, 1] so rating difference ∈ [-1, +1].
k=2.0 maps diff=0.5 to sigmoid(1.0)=0.73 — reasonable spread."""

DEFAULT_CS_WEIGHT: float = 0.5
"""Weight for clean_sheet_pct in defensive rating composite."""

DEFAULT_XGA_WEIGHT: float = 0.5
"""Weight for (1 - xga_normalized) in defensive rating composite."""

DEFAULT_MAX_XGA: float = 3.0
"""Normalization ceiling for avg_xg_against. Values above this saturate at 1.0."""


def compute_defensive_rating(profile: dict) -> float:
    """Compute composite defensive rating from a manager profile dict.

    Args:
        profile: Manager profile dict with 'clean_sheet_pct' and 'avg_xg_against'.

    Returns:
        Defensive rating in [0, 1] where 1 = best defense.
    """
    cs = profile.get("clean_sheet_pct", 0.0)
    if not isinstance(cs, (int, float)):
        cs = 0.0

    xga = profile.get("avg_xg_against", 0.0)
    if not isinstance(xga, (int, float)):
        xga = 0.0

    xga_norm = min(xga / DEFAULT_MAX_XGA, 1.0)
    xga_score = 1.0 - xga_norm

    return DEFAULT_CS_WEIGHT * cs + DEFAULT_XGA_WEIGHT * xga_score


def compute_defensive_probability(
    rating_a: float,
    rating_b: float,
    k: float = DEFAULT_K,
) -> float:
    """Compute match probability from defensive rating difference.

    Args:
        rating_a: Defensive rating for team A (home).
        rating_b: Defensive rating for team B (away).
        k: Sigmoid steepness.

    Returns:
        Probability that team A wins based on defensive quality difference.
    """
    diff = rating_a - rating_b
    return sigmoid(k * diff)


def compute_defensive_signal_for_match(
    team_a: str,
    team_b: str,
    manager_data: dict[str, dict],
) -> dict:
    """Compute defensive quality signal for a single match pairing.

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

    rating_a = compute_defensive_rating(prof_a)
    rating_b = compute_defensive_rating(prof_b)

    p = compute_defensive_probability(rating_a, rating_b)

    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "timestamp": now.isoformat(),
        "available": True,
        "defensive_rating_a": round(rating_a, 4),
        "defensive_rating_b": round(rating_b, 4),
    }


def compute_defensive_signal(
    manager_data: dict[str, dict],
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute defensive quality signal for all group and bracket matches.

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
            entry = compute_defensive_signal_for_match(
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
            entry = compute_defensive_signal_for_match(
                match["team_a"], match["team_b"], manager_data,
            )
            result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }


class DefensiveQualitySignal(Signal):
    """Defensive quality signal — clean sheet rate + xGA composite.

    Requires context.manager_data to be populated with team→profile dicts.
    """

    name: str = "defensive_quality"

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

        rating_a = compute_defensive_rating(prof_a)
        rating_b = compute_defensive_rating(prof_b)
        home_prob = compute_defensive_probability(rating_a, rating_b, self._k)

        draw_prob = 0.25
        away_prob = 1.0 - home_prob - draw_prob

        return SignalOutput(home_prob, draw_prob, away_prob)
