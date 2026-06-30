"""Generic group simulation: Poisson score model, tiebreaker chain, round-robin match simulation."""

import functools
import math
import random
from collections import defaultdict

from football_core import constants


MAX_EXPECTED_GOALS = constants.MAX_EXPECTED_GOALS


def expected_goals(
    rating_a: float, rating_b: float, base_rate: float
) -> float:
    adj_base = base_rate * constants.HOME_ADVANTAGE_MULTIPLIER
    return min(adj_base * (10.0 ** ((rating_a - rating_b) / 400.0)), MAX_EXPECTED_GOALS)


_TABLE_BITS = constants.POISSON_TABLE_BITS
_TABLE_SIZE = constants.POISSON_TABLE_SIZE


@functools.lru_cache(maxsize=None)
def _build_poisson_table(lam: float) -> list[int]:
    if lam <= 0.0:
        return [0] * _TABLE_SIZE
    term = math.exp(-lam)
    total = 0.0
    k = 0
    cdf = []
    while total < 0.999999:
        total += term
        cdf.append(total)
        k += 1
        term *= lam / k
    table = []
    idx = 0
    for k, cum_prob in enumerate(cdf):
        boundary = int(cum_prob * _TABLE_SIZE)
        while idx < boundary:
            table.append(k)
            idx += 1
    while len(table) < _TABLE_SIZE:
        table.append(len(cdf) - 1)
    return table


def _poisson_sample(lam: float, rng: random.Random) -> int:
    if lam <= 0.0:
        return 0
    table = _build_poisson_table(lam)
    return table[rng.getrandbits(_TABLE_BITS)]


def _simulate_single_match(
    team_a: str, team_b: str, elo_a: float, elo_b: float, rng: random.Random,
    lambda_a: float | None = None, lambda_b: float | None = None,
    fair_play: bool = True,
    base_rate: float = constants.EXPECTED_GOALS_BASE_RATE,
) -> dict:
    if lambda_a is None:
        lambda_a = expected_goals(elo_a, elo_b, base_rate)
    if lambda_b is None:
        lambda_b = expected_goals(elo_b, elo_a, base_rate)

    score_a = _poisson_sample(lambda_a, rng)
    score_b = _poisson_sample(lambda_b, rng)

    if score_a > score_b:
        winner = team_a
    elif score_b > score_a:
        winner = team_b
    else:
        winner = None

    if fair_play:
        yc_a = _poisson_sample(2.0, rng)
        rc_a = _poisson_sample(0.05, rng)
        yc_b = _poisson_sample(2.0, rng)
        rc_b = _poisson_sample(0.05, rng)
    else:
        yc_a = rc_a = yc_b = rc_b = 0

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


def precompute_matchup_lambdas(
    groups: dict,
    elo_ratings: dict[str, float],
    base_rate: float,
    xg_overrides: dict[str, tuple[float, float]] | None = None,
) -> dict[str, tuple[float, float]]:
    groups_data = groups.get("groups", groups)
    lambdas: dict[str, tuple[float, float]] = {}
    for group_data in groups_data.values():
        for match in group_data["matches"]:
            mid = match["match_id"]
            if xg_overrides and mid in xg_overrides:
                lambdas[mid] = xg_overrides[mid]
            else:
                ta, tb = match["team_a"], match["team_b"]
                ea, eb = elo_ratings[ta], elo_ratings[tb]
                lambdas[mid] = (expected_goals(ea, eb, base_rate), expected_goals(eb, ea, base_rate))
    return lambdas


def simulate_group_matches(
    groups: dict,
    teams: dict[str, dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float,
    fair_play: bool = True,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    played_groups: dict[str, dict] | None = None,
) -> dict[str, dict[str, dict]]:
    groups_data = groups.get("groups", groups)
    played_groups = played_groups or {}

    if matchup_lambdas is None:
        matchup_lambdas = precompute_matchup_lambdas(groups, elo_ratings, base_rate=base_rate)

    getrandbits = rng.getrandbits
    build_table = _build_poisson_table
    table_bits = _TABLE_BITS

    results: dict[str, dict[str, dict]] = {}
    for group_letter, group_data in groups_data.items():
        group_results: dict[str, dict] = {}
        for match in group_data["matches"]:
            mid = match["match_id"]

            if mid in played_groups:
                pg = played_groups[mid]
                group_results[mid] = {
                    "team_a": pg["team_a"],
                    "team_b": pg["team_b"],
                    "score_a": pg["home_score"],
                    "score_b": pg["away_score"],
                    "winner": pg["winner"],
                    "yellow_cards_a": 0,
                    "red_cards_a": 0,
                    "yellow_cards_b": 0,
                    "red_cards_b": 0,
                }
                continue

            ta: str = match["team_a"]
            tb: str = match["team_b"]
            la, lb = matchup_lambdas[mid]

            if la <= 0.0:
                score_a = 0
            else:
                table = build_table(la)
                score_a = table[getrandbits(table_bits)]

            if lb <= 0.0:
                score_b = 0
            else:
                table = build_table(lb)
                score_b = table[getrandbits(table_bits)]

            if score_a > score_b:
                winner = ta
            elif score_b > score_a:
                winner = tb
            else:
                winner = None

            if fair_play:
                yc_table = build_table(2.0)
                rc_table = build_table(0.05)
                yc_a = yc_table[getrandbits(table_bits)]
                rc_a = rc_table[getrandbits(table_bits)]
                yc_b = yc_table[getrandbits(table_bits)]
                rc_b = rc_table[getrandbits(table_bits)]
            else:
                yc_a = rc_a = yc_b = rc_b = 0

            group_results[mid] = {
                "team_a": ta, "team_b": tb,
                "score_a": score_a, "score_b": score_b,
                "winner": winner,
                "yellow_cards_a": yc_a, "red_cards_a": rc_a,
                "yellow_cards_b": yc_b, "red_cards_b": rc_b,
            }
        results[group_letter] = group_results
    return results


def _compute_conduct_score(yellow_cards: int, red_cards: int) -> int:
    return (yellow_cards * 1) + (red_cards * 4)


def _compute_h2h(
    cluster: list[dict],
    results: dict[str, dict],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    tied_teams: set[str] = {t["team"] for t in cluster}

    h2h_pts: dict[str, int] = {}
    h2h_gd: dict[str, int] = {}
    h2h_gs: dict[str, int] = {}

    for t in cluster:
        team = t["team"]
        h2h_pts[team] = 0
        h2h_gd[team] = 0
        h2h_gs[team] = 0

    for match in results.values():
        ta: str = match["team_a"]
        tb: str = match["team_b"]

        if ta not in tied_teams or tb not in tied_teams:
            continue

        sa: int = match["score_a"]
        sb: int = match["score_b"]

        if sa > sb:
            h2h_pts[ta] += 3
        elif sb > sa:
            h2h_pts[tb] += 3
        else:
            h2h_pts[ta] += 1
            h2h_pts[tb] += 1

        gd = sa - sb
        h2h_gd[ta] += gd
        h2h_gd[tb] -= gd

        h2h_gs[ta] += sa
        h2h_gs[tb] += sb

    return h2h_pts, h2h_gd, h2h_gs


def _resolve_by_values(
    cluster: list[dict],
    values: dict[str, int | float],
    results: dict[str, dict],
    depth: int,
    *,
    reverse: bool = True,
) -> list[dict] | None:
    groups: dict[int | float, list[dict]] = defaultdict(list)
    for t in cluster:
        groups[values[t["team"]]].append(t)

    if len(groups) == 1:
        return None

    sorted_vals = sorted(groups.keys(), reverse=reverse)
    result: list[dict] = []
    for v in sorted_vals:
        resolved = _tiebreak_group(groups[v], results, depth + 1)
        result.extend(resolved)
    return result


def _resolve_tied_cluster(
    cluster: list[dict],
    results: dict[str, dict],
    depth: int,
) -> list[dict]:
    if len(cluster) <= 1:
        return cluster

    h2h_pts, h2h_gd, h2h_gs = _compute_h2h(cluster, results)

    result = _resolve_by_values(cluster, h2h_pts, results, depth, reverse=True)
    if result is not None:
        return result

    result = _resolve_by_values(cluster, h2h_gd, results, depth, reverse=True)
    if result is not None:
        return result

    result = _resolve_by_values(cluster, h2h_gs, results, depth, reverse=True)
    if result is not None:
        return result

    values_gd = {t["team"]: t["gd"] for t in cluster}
    result = _resolve_by_values(cluster, values_gd, results, depth, reverse=True)
    if result is not None:
        return result

    values_gs = {t["team"]: t["gs"] for t in cluster}
    result = _resolve_by_values(cluster, values_gs, results, depth, reverse=True)
    if result is not None:
        return result

    values_co = {t["team"]: t["conduct_score"] for t in cluster}
    result = _resolve_by_values(cluster, values_co, results, depth, reverse=False)
    if result is not None:
        return result

    values_elo = {t["team"]: t["elo"] for t in cluster}
    result = _resolve_by_values(cluster, values_elo, results, depth, reverse=True)
    if result is not None:
        return result

    return sorted(cluster, key=lambda t: t["team"])


def _tiebreak_group(
    team_data_list: list[dict],
    results: dict[str, dict],
    depth: int = 0,
) -> list[dict]:
    if depth > 10:
        raise ValueError("Tiebreaker recursion exceeded max depth")

    n = len(team_data_list)
    if n <= 1:
        return team_data_list

    sorted_teams = sorted(team_data_list, key=lambda t: t["pts"], reverse=True)

    result: list[dict] = []
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_teams[j]["pts"] == sorted_teams[i]["pts"]:
            j += 1

        cluster = sorted_teams[i:j]
        if len(cluster) == 1:
            result.append(cluster[0])
        else:
            result.extend(_resolve_tied_cluster(cluster, results, depth))
        i = j

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ── League-format (Swiss / round-robin league) functions
# ═══════════════════════════════════════════════════════════════════════════════


def precompute_matchup_lambdas_league(
    fixtures: dict,
    elo_ratings: dict[str, float],
    base_rate: float = constants.EXPECTED_GOALS_BASE_RATE,
) -> dict[str, tuple[float, float]]:
    """Pre-compute Poisson lambdas for every match in a league-format fixture schedule.

    Expects *fixtures* to have a ``schedule`` key containing
    ``{teams: [...], matchdays: [[{match_id, team_a, team_b}, ...], ...]}``.
    """
    lambdas: dict[str, tuple[float, float]] = {}
    schedule = fixtures.get("schedule", fixtures)
    for matchday in schedule["matchdays"]:
        for match in matchday:
            mid = match["match_id"]
            ta, tb = match["team_a"], match["team_b"]
            ea, eb = elo_ratings[ta], elo_ratings[tb]
            lambdas[mid] = (
                expected_goals(ea, eb, base_rate),
                expected_goals(eb, ea, base_rate),
            )
    return lambdas


def simulate_league_matches(
    fixtures: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = constants.EXPECTED_GOALS_BASE_RATE,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    fair_play: bool = True,
) -> dict[str, dict]:
    """Simulate all matches in a league-format fixture schedule.

    Follows the same Poisson sampling pattern as
    :func:`simulate_group_matches` but iterates matchday-based fixtures
    rather than group-based matches.

    Returns a flat dict keyed by ``match_id`` (NOT grouped by matchday).
    Does NOT mutate the input *fixtures*.
    """
    fixtures = {"schedule": {
        "teams": list(fixtures.get("schedule", fixtures).get("teams", [])),
        "matchdays": [
            list(md) for md in fixtures.get("schedule", fixtures).get("matchdays", [])
        ],
    }}

    schedule = fixtures["schedule"]

    if matchup_lambdas is None:
        matchup_lambdas = precompute_matchup_lambdas_league(
            fixtures, elo_ratings, base_rate=base_rate,
        )

    getrandbits = rng.getrandbits
    table_bits = _TABLE_BITS
    build_table = _build_poisson_table

    results: dict[str, dict] = {}
    for matchday in schedule["matchdays"]:
        for match in matchday:
            mid = match["match_id"]
            ta: str = match["team_a"]
            tb: str = match["team_b"]
            la, lb = matchup_lambdas[mid]

            score_a = (
                0 if la <= 0.0 else build_table(la)[getrandbits(table_bits)]
            )
            score_b = (
                0 if lb <= 0.0 else build_table(lb)[getrandbits(table_bits)]
            )

            if score_a > score_b:
                winner = ta
            elif score_b > score_a:
                winner = tb
            else:
                winner = None

            if fair_play:
                yc_table = build_table(2.0)
                rc_table = build_table(0.05)
                yc_a = yc_table[getrandbits(table_bits)]
                rc_a = rc_table[getrandbits(table_bits)]
                yc_b = yc_table[getrandbits(table_bits)]
                rc_b = rc_table[getrandbits(table_bits)]
            else:
                yc_a = rc_a = yc_b = rc_b = 0

            results[mid] = {
                "team_a": ta,
                "team_b": tb,
                "score_a": score_a,
                "score_b": score_b,
                "winner": winner,
                "yellow_cards_a": yc_a,
                "red_cards_a": rc_a,
                "yellow_cards_b": yc_b,
                "red_cards_b": rc_b,
            }

    return results
