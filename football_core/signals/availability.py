"""Availability / Injury Impact signal — squad composition and player fitness.

Computes an availability strength signal from player-level data:
  availability — "available" / "injured" / "suspended"
  injury_risk — "Low" / "Medium" / "High" / "Unlikely"
  rating — player quality rating (0-100)
  position — player position for positional weighting

Formula:
  For each team, compute a weighted unavailability score:
    unavailable_pct = sum(rating for unavailable players) / sum(rating for all players)
  
  Positional weighting: missing a GK or striker penalizes more than a fullback.
  
  p = sigmoid(k * (unavail_b - unavail_a))
  → higher unavailability for team_a reduces their win probability

Both a standalone compute function and a Signal protocol class are provided.
"""

import logging
from datetime import datetime, timezone

from football_core.math_utils import sigmoid
from football_core.signal import Signal, SignalOutput, PredictionContext

logger = logging.getLogger(__name__)

DEFAULT_K: float = 3.0
"""Sigmoid steepness for availability signal.
unavailability difference ∈ [0, 1]. k=3.0 maps diff=0.5 to sigmoid(1.5)=0.82."""

POSITION_WEIGHTS: dict[str, float] = {
    "Goalkeeper": 1.5,
    "goalkeeper": 1.5,
    "GK": 1.5,
    "Defender": 1.0,
    "defender": 1.0,
    "Center Back": 1.2,
    "Right Back": 1.0,
    "Left Back": 1.0,
    "Midfielder": 1.2,
    "midfielder": 1.2,
    "Central Midfield": 1.3,
    "Attacking Midfield": 1.2,
    "Defensive Midfield": 1.3,
    "Forward": 1.4,
    "forward": 1.4,
    "Striker": 1.5,
    "Center Forward": 1.5,
    "Winger": 1.2,
    "Left Winger": 1.2,
    "Right Winger": 1.2,
}
"""Positional multipliers for unavailability weight.
GK and ST get higher weight (harder to replace)."""

UNAVAILABLE_STATUSES: set[str] = {"injured", "suspended"}
"""Player availability values that count as unavailable."""

HIGH_INJURY_RISK: set[str] = {"High", "Unlikely"}
"""injury_risk values that imply likely unavailability even if currently available."""


def _get_position_weight(position: str) -> float:
    return POSITION_WEIGHTS.get(position, 1.0)


def compute_team_unavailability(players: list[dict]) -> float:
    """Compute weighted unavailability score for a team.

    Weights unavailable players by their rating × position multiplier,
    normalised by total weighted rating of the squad.

    Args:
        players: List of player profile dicts for one team.

    Returns:
        Weighted unavailability score in [0, 1].
        0 = fully available, 1 = entire squad unavailable.
    """
    total_weighted = 0.0
    unavailable_weighted = 0.0

    for p in players:
        rating = p.get("rating", 0.0)
        if not isinstance(rating, (int, float)):
            rating = 0.0

        pos_weight = _get_position_weight(p.get("position", ""))
        weighted_rating = rating * pos_weight

        availability = p.get("availability", "available")
        injury_risk = p.get("injury_risk", "Low")

        is_unavailable = (
            availability in UNAVAILABLE_STATUSES
            or injury_risk in HIGH_INJURY_RISK
        )

        total_weighted += weighted_rating
        if is_unavailable:
            unavailable_weighted += weighted_rating

    if total_weighted <= 0:
        return 0.0

    return unavailable_weighted / total_weighted


def compute_availability_probability(
    unavail_a: float,
    unavail_b: float,
    k: float = DEFAULT_K,
) -> float:
    """Compute match probability from team unavailability difference.

    Higher unavailability for team_a reduces their win probability.

    Args:
        unavail_a: Weighted unavailability for team A (home).
        unavail_b: Weighted unavailability for team B (away).
        k: Sigmoid steepness.

    Returns:
        Probability that team A wins based on availability difference.
    """
    diff = unavail_b - unavail_a
    return sigmoid(k * diff)


def compute_availability_signal_for_match(
    team_a: str,
    team_b: str,
    player_data: dict[str, list[dict]],
) -> dict:
    """Compute availability signal for a single match pairing.

    Args:
        team_a: Home team name.
        team_b: Away team name.
        player_data: Dict mapping team name → list of player profile dicts.

    Returns:
        Signal entry dict with keys: probability, available, reason (if unavailable).
    """
    now = datetime.now(timezone.utc)

    players_a = player_data.get(team_a, [])
    players_b = player_data.get(team_b, [])

    if not players_a or not players_b:
        missing = []
        if not players_a:
            missing.append(team_a)
        if not players_b:
            missing.append(team_b)
        return {
            "probability": None,
            "timestamp": now.isoformat(),
            "available": False,
            "reason": f"player_data_not_found: {', '.join(missing)}",
        }

    unavail_a = compute_team_unavailability(players_a)
    unavail_b = compute_team_unavailability(players_b)

    p = compute_availability_probability(unavail_a, unavail_b)

    p = max(1e-15, min(1 - 1e-15, p))

    return {
        "probability": p,
        "timestamp": now.isoformat(),
        "available": True,
        "unavailability_a": round(unavail_a, 4),
        "unavailability_b": round(unavail_b, 4),
    }


def compute_availability_signal(
    player_data: dict[str, list[dict]],
    groups: dict,
    bracket: list[dict] | None = None,
) -> dict:
    """Compute availability signal for all group and bracket matches.

    Args:
        player_data: Dict mapping team name → list of player profile dicts.
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
            entry = compute_availability_signal_for_match(
                match["team_a"], match["team_b"], player_data,
            )
            result[mid] = entry

    if bracket:
        for match in bracket:
            if match.get("team_a") is None or match.get("team_b") is None:
                continue
            mid = match.get("match_id")
            if not mid:
                continue
            entry = compute_availability_signal_for_match(
                match["team_a"], match["team_b"], player_data,
            )
            result[mid] = entry

    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "matches": result,
    }


class AvailabilitySignal(Signal):
    """Availability / injury impact signal — squad fitness composite.

    Requires context.player_data to be populated with team→list of player dicts.
    """

    name: str = "availability"

    def __init__(self, k: float = DEFAULT_K) -> None:
        self._k = k

    def predict(
        self, match: dict, context: PredictionContext
    ) -> SignalOutput:
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        player_data = context.player_data or {}

        players_a = player_data.get(team_a, [])
        players_b = player_data.get(team_b, [])

        if not players_a or not players_b:
            return SignalOutput(1 / 3, 1 / 3, 1 / 3)

        unavail_a = compute_team_unavailability(players_a)
        unavail_b = compute_team_unavailability(players_b)
        home_prob = compute_availability_probability(unavail_a, unavail_b, self._k)

        draw_prob = 0.25
        away_prob = 1.0 - home_prob - draw_prob

        return SignalOutput(home_prob, draw_prob, away_prob)
