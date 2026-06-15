"""Elo rating engine for the World Cup predictor.

Provides standard World Football Elo rating calculations:
- expected_score: Calculate expected win probability for a match.
- update_ratings: Update Elo ratings after a match result.

Uses the standard Elo formula from eloratings.net:
  E_a = 1 / (1 + 10^((rating_b - effective_a) / 400))
  Rn = Ro + K * (W - We)

Where K=60 is the default for World Cup finals matches.
"""

import math

from src import constants


def expected_score(rating_a: float, rating_b: float, home_advantage: int = 0) -> float:
    """Calculate expected score (win probability) for team A against team B.

    Uses the standard Elo formula:
        E_a = 1 / (1 + 10^((rating_b - effective_a) / 400))

    For knockout matches, home_advantage = 0 (neutral venue).

    Args:
        rating_a: Elo rating of team A.
        rating_b: Elo rating of team B.
        home_advantage: Points added to rating_a for home-field effect (default 0).

    Returns:
        Float between 0.0 and 1.0 representing team A's expected score.
    """
    effective_a = rating_a + home_advantage
    return 1.0 / (1.0 + math.pow(10, (rating_b - effective_a) / 400.0))


def compute_k_factor(goal_diff: int, base_K: int = 60) -> float:
    """Compute adjusted K-factor using eloratings.net goal-difference multiplier.

    Step-function per eloratings.net/about and D-10:
        GD = 0 or 1 → G = 1.0 (draws and one-goal wins)
        GD = 2     → G = 1.5 (two-goal wins)
        GD >= 3    → G = (11 + GD) / 8 (three+ goal wins)

    Args:
        goal_diff: Absolute goal difference (abs(home - away)), always >= 0.
        base_K: Base K-factor (60 for World Cup finals, from constants.py).

    Returns:
        Adjusted K-factor as float.

    Examples:
        >>> compute_k_factor(0, 60)
        60.0
        >>> compute_k_factor(2, 60)
        90.0
        >>> compute_k_factor(7, 60)
        135.0
    """
    if goal_diff <= 1:
        G = 1.0
    elif goal_diff == 2:
        G = 1.5
    else:
        G = (11 + goal_diff) / 8.0
    return base_K * G


def update_ratings(
    team_a: str,
    team_b: str,
    winner: str | None,
    current_elos: dict[str, float],
    K: int = 60,
    pk_winner: str | None = None,
) -> dict[str, float]:
    """Update Elo ratings after a match result.

    Computes new ratings for both teams based on the match outcome.
    Supports penalty shootout (PK) mode via pk_winner parameter — when
    set, uses a 0.75/0.25 result split per eloratings.net PK rule.

    Does NOT modify the input `current_elos` dict.

    Args:
        team_a: Name of the first team.
        team_b: Name of the second team.
        winner: Name of the winning team (must be team_a or team_b),
                or None for a draw. For PK-decided matches, winner
                holds the team that won on penalties.
        current_elos: Dict mapping team names to their current Elo ratings.
        K: K-factor controlling rating change magnitude (default 60).
        pk_winner: If set, overrides result_a with 0.75/0.25 PK split
                   (must be team_a or team_b). Default None.

    Returns:
        Dict with only the two changed teams and their new ratings.

    Raises:
        ValueError: If winner is not None, team_a, or team_b.
        ValueError: If pk_winner is not None, team_a, or team_b.
    """
    elo_a = current_elos[team_a]
    elo_b = current_elos[team_b]

    expected_a = expected_score(elo_a, elo_b)
    expected_b = 1.0 - expected_a

    if pk_winner is not None:
        if pk_winner == team_a:
            result_a = 0.75
        elif pk_winner == team_b:
            result_a = 0.25
        else:
            raise ValueError(
                f"pk_winner '{pk_winner}' must be '{team_a}' or '{team_b}'"
            )
    elif winner is None:
        result_a = 0.5
    elif winner == team_a:
        result_a = 1.0
    elif winner == team_b:
        result_a = 0.0
    else:
        raise ValueError(
            f"Winner '{winner}' must be None, '{team_a}', or '{team_b}'"
        )

    new_elo_a = elo_a + K * (result_a - expected_a)
    new_elo_b = elo_b + K * ((1.0 - result_a) - expected_b)

    return {
        team_a: round(new_elo_a, 1),
        team_b: round(new_elo_b, 1),
    }


def apply_elo_update(match: dict, teams: dict[str, dict]) -> dict[str, dict[str, float]]:
    """Apply Elo rating update for a single match result with K-multiplier.

    Computes goal-difference K-multiplier via compute_k_factor() per
    eloratings.net step-function spec (D-10). Detects PK-decided matches
    (is_draw=False + winner set + GD=0) and passes pk_winner for the
    0.75/0.25 result split (D-06, D-07). Mutates teams dict in-place.

    Args:
        match: Match dict with keys: team_a, team_b, winner (may be None),
               home_score, away_score. For PK shootouts: winner holds the
               PK winner and is_draw=False. For true draws: winner=None.
        teams: Dict mapping team name to team data (mutated in-place).

    Returns:
        Dict of {team_name: {"old": old_rating, "new": new_rating}}
        for the two teams involved.
    """
    current_elos = {name: data["elo"] for name, data in teams.items()}

    # Compute goal-difference K-multiplier (D-10, D-13)
    goal_diff = abs(match.get("home_score", 0) - match.get("away_score", 0))
    adjusted_K = compute_k_factor(goal_diff, constants.K_FACTOR)

    # Detect PK mode (D-06, D-07)
    pk_winner = None
    if not match.get("is_draw", True) and match.get("winner") is not None:
        pk_winner = match["winner"]

    ratings_update = update_ratings(
        match["team_a"],
        match["team_b"],
        match.get("winner"),
        current_elos,
        K=int(round(adjusted_K)),
        pk_winner=pk_winner,
    )
    elo_updates: dict[str, dict[str, float]] = {}
    for team_name, new_rating in ratings_update.items():
        old_rating = current_elos[team_name]
        elo_updates[team_name] = {"old": old_rating, "new": new_rating}
        teams[team_name]["elo"] = new_rating
    return elo_updates
