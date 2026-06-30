"""Generic knockout tournament primitives: round map building, match simulation, blended probabilities, two-legged ties, penalty shootouts."""

import random

from football_core.elo import expected_score
from football_core.constants import (
    EXPECTED_GOALS_BASE_RATE,
    HOME_ADVANTAGE_MULTIPLIER,
    POISSON_TABLE_BITS,
)
from football_core.groups import _build_poisson_table, expected_goals


KNOOKOUT_ROUNDS = {"R16", "QF", "SF", "FINAL", "TPP"}


def _get_blended_prob(
    match_id: str,
    team_a: str,
    team_b: str,
    blend_params: dict | None,
    elo_ratings: dict[str, float],
) -> float:
    if blend_params:
        match_probs = blend_params.get("match_probs", {})
        if match_id in match_probs:
            return match_probs[match_id]
    return expected_score(elo_ratings[team_a], elo_ratings[team_b])


def _is_knockout_round(r: str) -> bool:
    return r in {"R16", "QF", "SF", "FINAL", "TPP"}


def _build_round_map(bracket: list[dict]) -> dict[str, list[dict]]:
    round_map: dict[str, list[dict]] = {}
    for match in bracket:
        r = match["round"]
        if not _is_knockout_round(r):
            continue
        if r not in round_map:
            round_map[r] = []
        round_map[r].append(match)
    for r in round_map:
        round_map[r].sort(key=lambda m: m["match_id"])
    return round_map


def _simulate_knockout_round(
    round_map: dict[str, list[dict]],
    round_name: str,
    played: dict[str, dict],
    winner_progression: dict[str, str],
    sf_losers: dict[str, str | None] | None,
    rng: random.Random,
    elo_ratings: dict[str, float],
    blend_params: dict | None = None,
) -> None:
    for match in round_map.get(round_name, []):
        mid = match["match_id"]
        if mid in played:
            winner_progression[mid] = played[mid]["winner"]
            if sf_losers is not None and round_name == "SF":
                sf_losers[mid] = None
            continue
        sources = match["source_matches"]
        teams_in_match = [winner_progression[s] for s in sources]
        if len(teams_in_match) == 1:
            winner_progression[mid] = teams_in_match[0]
        else:
            team_a, team_b = teams_in_match[0], teams_in_match[1]
            p_a = _get_blended_prob(mid, team_a, team_b, blend_params, elo_ratings)
            if rng.random() < p_a:
                winner_progression[mid] = team_a
                if sf_losers is not None and round_name == "SF":
                    sf_losers[mid] = team_b
            else:
                winner_progression[mid] = team_b
                if sf_losers is not None and round_name == "SF":
                    sf_losers[mid] = team_a


def _simulate_penalty_shootout(
    rng: random.Random,
    conversion_rate: float = 0.76,
    shots: int = 5,
) -> tuple[int, int]:
    """Simulate a penalty shootout with sudden death if level after ``shots`` each.

    Each shot is a configurable Bernoulli trial (default ~76%
    reflects historical UCL conversion rate).

    Parameters
    ----------
    rng:
        Seeded random.Random for deterministic results.
    conversion_rate:
        Probability each penalty is converted.
    shots:
        Number of penalty shots per side before sudden death.

    Returns
    -------
    tuple[int, int]
        (goals_a, goals_b) — the final penalty scores.
    """
    a_scored = b_scored = 0
    for i in range(shots):
        if rng.random() < conversion_rate:
            a_scored += 1
        if rng.random() < conversion_rate:
            b_scored += 1
        remaining = shots - (i + 1)
        if a_scored > b_scored + remaining or b_scored > a_scored + remaining:
            break

    while a_scored == b_scored:
        if rng.random() < conversion_rate:
            a_scored += 1
        if rng.random() < conversion_rate:
            b_scored += 1

    return a_scored, b_scored


def simulate_single_match(
    team_a: str,
    team_b: str,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """Simulate a single match at neutral venue (e.g. final).

    Neutral venue means no home advantage for either team.
    If scores are level after normal time, extra time is played
    with configurable reduced Poisson lambda.  If still level,
    a penalty shootout decides.

    Returns a dict with winner, loser, scores, and ET/penalty flags.
    """
    ea = elo_ratings[team_a]
    eb = elo_ratings[team_b]

    lam_a = expected_goals(ea, eb, base_rate)
    lam_b = expected_goals(eb, ea, base_rate)
    score_a = _build_poisson_table(lam_a)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a > 0 else 0
    score_b = _build_poisson_table(lam_b)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b > 0 else 0

    if score_a != score_b:
        winner = team_a if score_a > score_b else team_b
        loser = team_b if score_a > score_b else team_a
        et_played = penalties_played = False
        et_a = et_b = pen_a = pen_b = 0
    else:
        et_played = True
        et_lam_a = lam_a * et_lambda_factor
        et_lam_b = lam_b * et_lambda_factor
        et_a = _build_poisson_table(et_lam_a)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_a > 0 else 0
        et_b = _build_poisson_table(et_lam_b)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_b > 0 else 0

        if (score_a + et_a) != (score_b + et_b):
            winner = team_a if (score_a + et_a) > (score_b + et_b) else team_b
            loser = team_b if (score_a + et_a) > (score_b + et_b) else team_a
            penalties_played = False
            pen_a = pen_b = 0
        else:
            penalties_played = True
            pen_a, pen_b = _simulate_penalty_shootout(rng, penalty_conversion_rate)
            winner = team_a if pen_a > pen_b else team_b
            loser = team_b if pen_a > pen_b else team_a

    return {
        "winner": winner,
        "loser": loser,
        "score_a": score_a + et_a,
        "score_b": score_b + et_b,
        "et_played": et_played,
        "penalties_played": penalties_played,
        "et_a": et_a,
        "et_b": et_b,
        "penalty_a": pen_a,
        "penalty_b": pen_b,
        "is_final": True,
    }


def simulate_two_legged_tie(
    team_a: str,
    team_b: str,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = EXPECTED_GOALS_BASE_RATE,
    et_lambda_factor: float = 0.25,
    penalty_conversion_rate: float = 0.76,
) -> dict:
    """Simulate a two-legged knockout tie with aggregate scoring.

    Simulates both legs using Poisson match simulation from
    football_core, then resolves by aggregate score.  If aggregate
    is level, extra time is played with configurable reduced Poisson
    lambda.  If still level, a penalty shootout decides.

    Extra time home advantage goes to the second-leg home
    team (team_b in leg 2, since team_a hosts leg 1).

    Per the 2025+ format: no away goals rule — aggregate score is
    the only tiebreaker.

    Parameters
    ----------
    team_a:
        Home team for leg 1 (away team for leg 2).
    team_b:
        Away team for leg 1 (home team for leg 2).
    elo_ratings:
        ``{team_name: Elo}`` dict.
    rng:
        Seeded random.Random for deterministic results.
    base_rate:
        Normal time expected goals base rate.
    et_lambda_factor:
        Configurable factor: ET lambda = normal_lambda * factor.
        Reflects shorter ET duration and fatigue.
    penalty_conversion_rate:
        Configurable probability each penalty shot is converted.

    Returns
    -------
    dict
        ``{winner, loser, aggregate_a, aggregate_b,
          agg_a_full, agg_b_full,
          leg1: {team_a, team_b, score_a, score_b},
          leg2: {team_a, team_b, score_a, score_b},
          et_played: bool, et_a, et_b,
          penalties_played: bool, penalty_a, penalty_b}``
    """
    ea = elo_ratings[team_a]
    eb = elo_ratings[team_b]

    lam_a1 = expected_goals(ea, eb, base_rate)
    lam_b1 = expected_goals(eb, ea, base_rate)
    score_a1 = _build_poisson_table(lam_a1)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a1 > 0 else 0
    score_b1 = _build_poisson_table(lam_b1)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b1 > 0 else 0

    lam_b2 = expected_goals(eb, ea, base_rate)
    lam_a2 = expected_goals(ea, eb, base_rate)
    score_b2 = _build_poisson_table(lam_b2)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_b2 > 0 else 0
    score_a2 = _build_poisson_table(lam_a2)[rng.getrandbits(POISSON_TABLE_BITS)] if lam_a2 > 0 else 0

    agg_a = score_a1 + score_a2
    agg_b = score_b1 + score_b2

    et_played = False
    et_a = et_b = 0
    if agg_a == agg_b:
        et_played = True
        et_lam_a = expected_goals(ea, eb, base_rate) * et_lambda_factor
        et_lam_b = expected_goals(eb, ea, base_rate) * et_lambda_factor * HOME_ADVANTAGE_MULTIPLIER
        et_a = _build_poisson_table(et_lam_a)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_a > 0 else 0
        et_b = _build_poisson_table(et_lam_b)[rng.getrandbits(POISSON_TABLE_BITS)] if et_lam_b > 0 else 0
        agg_a += et_a
        agg_b += et_b

    penalties_played = False
    pen_a = pen_b = 0
    if agg_a == agg_b:
        penalties_played = True
        pen_a, pen_b = _simulate_penalty_shootout(rng, penalty_conversion_rate)

    if agg_a > agg_b:
        winner, loser = team_a, team_b
    elif agg_b > agg_a:
        winner, loser = team_b, team_a
    elif penalties_played:
        if pen_a > pen_b:
            winner, loser = team_a, team_b
        else:
            winner, loser = team_b, team_a
    else:
        winner, loser = None, None

    return {
        "winner": winner,
        "loser": loser,
        "aggregate_a": score_a1 + score_a2,
        "aggregate_b": score_b1 + score_b2,
        "agg_a_full": agg_a,
        "agg_b_full": agg_b,
        "leg1": {"team_a": team_a, "team_b": team_b, "score_a": score_a1, "score_b": score_b1},
        "leg2": {"team_a": team_a, "team_b": team_b, "score_a": score_a2, "score_b": score_b2},
        "et_played": et_played,
        "et_a": et_a,
        "et_b": et_b,
        "penalties_played": penalties_played,
        "penalty_a": pen_a,
        "penalty_b": pen_b,
    }
