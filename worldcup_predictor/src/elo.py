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


def update_ratings(
    team_a: str,
    team_b: str,
    winner: str,
    current_elos: dict[str, float],
    K: int = 60,
) -> dict[str, float]:
    """Update Elo ratings after a match result.

    Computes new ratings for both teams based on the match outcome.
    Does NOT modify the input `current_elos` dict.

    Args:
        team_a: Name of the first team.
        team_b: Name of the second team.
        winner: Name of the winning team (must be team_a or team_b).
        current_elos: Dict mapping team names to their current Elo ratings.
        K: K-factor controlling rating change magnitude (default 60).

    Returns:
        Dict with only the two changed teams and their new ratings.

    Raises:
        ValueError: If winner is neither team_a nor team_b.
    """
    elo_a = current_elos[team_a]
    elo_b = current_elos[team_b]

    # Expected scores (neutral venue: home_advantage = 0)
    expected_a = expected_score(elo_a, elo_b)
    expected_b = 1.0 - expected_a

    # Determine result score for team A
    if winner == team_a:
        result_a = 1.0
    elif winner == team_b:
        result_a = 0.0
    else:
        raise ValueError(
            f"Winner '{winner}' must be '{team_a}' or '{team_b}'"
        )

    # Compute new ratings
    new_elo_a = elo_a + K * (result_a - expected_a)
    new_elo_b = elo_b + K * ((1.0 - result_a) - expected_b)

    # Return ONLY the changed teams (new dict, no mutation of input)
    return {
        team_a: round(new_elo_a, 1),
        team_b: round(new_elo_b, 1),
    }

# TODO: Add goal-difference K multiplier (eloratings.net adjustment) post-MVP
