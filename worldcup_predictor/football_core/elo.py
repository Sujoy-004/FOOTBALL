"""Elo rating engine for tournament prediction."""

import math

from football_core import constants


def expected_score(rating_a: float, rating_b: float, home_advantage: int = 0) -> float:
    effective_a = rating_a + home_advantage
    return 1.0 / (1.0 + math.pow(10, (rating_b - effective_a) / 400.0))


def compute_k_factor(goal_diff: int, base_K: int = 60) -> float:
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
    current_elos = {name: data["elo"] for name, data in teams.items()}

    goal_diff = abs(match.get("home_score", 0) - match.get("away_score", 0))
    adjusted_K = compute_k_factor(goal_diff, constants.K_FACTOR)

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
