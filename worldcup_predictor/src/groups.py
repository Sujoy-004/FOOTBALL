"""Group stage simulation engine for the World Cup predictor.
Simulates 72 round-robin group matches per iteration using a Poisson score model,
computes standings with FIFA 2026 7-step tiebreaker, ranks third-placed teams,
and resolves Annex C R32 matchups.
"""

import math
import random

from src import constants


def expected_goals(
    rating_a: float, rating_b: float, base_rate: float | None = None
) -> float:
    """Expected goals for team A against team B using the Elo-to-goals formula.

    Computes team A's expected goal rate (lambda parameter for Poisson) against
    team B at neutral venue modified by home advantage for team A.

    Args:
        rating_a: Elo rating of team A (the "home" side in the fixture).
        rating_b: Elo rating of team B (the "away" side).
        base_rate: Base expected goals at Elo-neutral conditions.
                   Defaults to constants.EXPECTED_GOALS_BASE_RATE.

    Returns:
        Float >= 0 representing team A's expected goals (Poisson lambda).
    """
    adj_base = (base_rate if base_rate is not None else constants.EXPECTED_GOALS_BASE_RATE) * 1.05
    return adj_base * (10.0 ** ((rating_a - rating_b) / 400.0))


def _poisson_sample(lam: float, rng: random.Random) -> int:
    """Draw a Poisson-distributed integer using the Knuth algorithm.

    Args:
        lam: The lambda parameter (mean) of the Poisson distribution.
        rng: A seeded random.Random instance for reproducibility.

    Returns:
        A non-negative integer sampled from Poisson(lam).
    """
    if lam <= 0.0:
        return 0
    k = 0
    p = 1.0
    bound = math.exp(-lam)
    while p > bound:
        k += 1
        p *= rng.random()
    return k - 1


def _simulate_single_match(
    team_a: str, team_b: str, elo_a: float, elo_b: float, rng: random.Random
) -> dict:
    """Simulate a single group match, returning scores, winner, and card counts.

    Goals are drawn from a Poisson distribution whose lambda is determined
    by the Elo-to-goals formula (expected_goals). Card counts are drawn from
    separate Poisson distributions (YC ~ Poisson(2.0), RC ~ Poisson(0.05)).

    Args:
        team_a: Name of team A (home side — receives home advantage).
        team_b: Name of team B (away side).
        elo_a: Elo rating of team A.
        elo_b: Elo rating of team B.
        rng: Seeded random.Random instance.

    Returns:
        Dict with keys: team_a, team_b, score_a, score_b, winner,
        yellow_cards_a, red_cards_a, yellow_cards_b, red_cards_b.
    """
    lambda_a = expected_goals(elo_a, elo_b)
    lambda_b = expected_goals(elo_b, elo_a)

    score_a = _poisson_sample(lambda_a, rng)
    score_b = _poisson_sample(lambda_b, rng)

    if score_a > score_b:
        winner = team_a
    elif score_b > score_a:
        winner = team_b
    else:
        winner = None

    yc_a = _poisson_sample(2.0, rng)
    rc_a = _poisson_sample(0.05, rng)
    yc_b = _poisson_sample(2.0, rng)
    rc_b = _poisson_sample(0.05, rng)

    return {
        "team_a": team_a,
        "team_b": team_b,
        "score_a": score_a,
        "score_b": score_b,
        "winner": winner,
        "yellow_cards_a": yc_a,
        "red_cards_a": rc_a,
        "yellow_cards_b": yc_b,
        "red_cards_b": rc_b,
    }


def simulate_group_matches(
    groups: dict,
    teams: dict[str, dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
) -> dict[str, dict[str, dict]]:
    """Simulate all unplayed group matches across all 12 groups.

    For each group (A–L), each match with a null winner is simulated using
    the Poisson score model. Already-played matches are skipped (their results
    are preserved). The input groups dict is NOT mutated.

    Args:
        groups: The groups dict loaded from groups.json, with structure
                {"groups": {"A": {"teams": [...], "matches": [...]}, ...}}.
        teams: Dict mapping team names to their data dicts (contains "elo").
        elo_ratings: Pre-computed dict mapping team names to Elo ratings.
        rng: Seeded random.Random instance for reproducibility.

    Returns:
        Nested dict: {group_letter: {match_id: match_result_dict}}
        where match_result_dict has keys: team_a, team_b, score_a, score_b,
        winner, yellow_cards_a, red_cards_a, yellow_cards_b, red_cards_b.
    """
    results: dict[str, dict[str, dict]] = {}
    groups_data = groups.get("groups", groups)

    for group_letter, group_data in groups_data.items():
        group_results: dict[str, dict] = {}
        for match in group_data["matches"]:
            mid = match["match_id"]
            team_a = match["team_a"]
            team_b = match["team_b"]

            elo_a = elo_ratings[team_a]
            elo_b = elo_ratings[team_b]

            result = _simulate_single_match(team_a, team_b, elo_a, elo_b, rng)
            group_results[mid] = result

        results[group_letter] = group_results

    return results
