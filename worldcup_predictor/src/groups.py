"""Group stage simulation engine for the World Cup predictor.
Simulates 72 round-robin group matches per iteration using a Poisson score model,
computes standings with FIFA 2026 7-step tiebreaker, ranks third-placed teams,
and resolves Annex C R32 matchups.
"""

import functools
import math
import random
from collections import defaultdict

from src import constants


MAX_EXPECTED_GOALS = constants.MAX_EXPECTED_GOALS


def expected_goals(
    rating_a: float, rating_b: float, base_rate: float
) -> float:
    """Expected goals for team A against team B using the Elo-to-goals formula.

    Computes team A's expected goal rate (lambda parameter for Poisson) against
    team B at neutral venue modified by home advantage for team A.
    Capped at MAX_EXPECTED_GOALS (8.0) to prevent unrealistically high
    expectations for extreme Elo gaps, which would also make the Knuth
    Poisson sampler prohibitively expensive.

    Args:
        rating_a: Elo rating of team A (the "home" side in the fixture).
        rating_b: Elo rating of team B (the "away" side).
        base_rate: Base expected goals at Elo-neutral conditions.

    Returns:
        Float >= 0 representing team A's expected goals (Poisson lambda),
        capped at MAX_EXPECTED_GOALS.
    """
    adj_base = base_rate * constants.HOME_ADVANTAGE_MULTIPLIER
    return min(adj_base * (10.0 ** ((rating_a - rating_b) / 400.0)), MAX_EXPECTED_GOALS)


_TABLE_BITS = constants.POISSON_TABLE_BITS
_TABLE_SIZE = constants.POISSON_TABLE_SIZE


@functools.lru_cache(maxsize=None)
def _build_poisson_table(lam: float) -> list[int]:
    """Build a precomputed inverse-CDF lookup table for Poisson(lam).

    Maps uniform [0, 1) quantized to _TABLE_SIZE buckets directly to
    Poisson samples. Replaces the Knuth while-loop with O(1) table lookup:
    one getrandbits call + one list index per sample.
    """
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
    """Draw a Poisson-distributed integer using inverse-CDF table lookup.

    Precomputes a lookup table on first use for each lambda, then samples
    via a single getrandbits call and list index. Much faster than the
    Knuth algorithm for the common case of small-to-moderate lambda.

    Args:
        lam: The lambda parameter (mean) of the Poisson distribution.
        rng: A seeded random.Random instance for reproducibility.

    Returns:
        A non-negative integer sampled from Poisson(lam).
    """
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
    """Simulate a single group match, returning scores, winner, and card counts.

    Goals are drawn from a Poisson distribution whose lambda is determined
    by the Elo-to-goals formula (expected_goals). Precomputed lambda values
    can be passed directly to avoid recomputation in tight loops.

    Args:
        team_a: Name of team A (home side — receives home advantage).
        team_b: Name of team B (away side).
        elo_a: Elo rating of team A.
        elo_b: Elo rating of team B.
        rng: Seeded random.Random instance.
        lambda_a: Precomputed expected goals for team A. If None, computed.
        lambda_b: Precomputed expected goals for team B. If None, computed.
        fair_play: If True, simulate yellow/red cards.
        base_rate: Base expected goals at Elo-neutral conditions.

    Returns:
        Dict with keys: team_a, team_b, score_a, score_b, winner,
        yellow_cards_a, red_cards_a, yellow_cards_b, red_cards_b.
    """
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
    """Precompute expected goals (λ) for every group match.

    λ values depend only on Elo ratings, which are fixed for a simulation run.
    Computing them once and reusing across iterations saves ~5.8s per 50K sims.

    Phase 18 (D-04): When xg_overrides is provided and a match_id is present,
    the xG tuple overrides the Elo-derived expected_goals() values.

    Args:
        groups: Groups dict (with or without "groups" wrapper key).
        elo_ratings: Dict mapping team name → Elo rating.
        base_rate: Base expected goals at Elo-neutral conditions.
        xg_overrides: Optional dict mapping match_id → (lambda_a, lambda_b)
                      from BSD xG predictions. When provided and mid present,
                      overrides Elo-derived expected_goals.

    Returns:
        Dict mapping match_id → (lambda_a, lambda_b).
        xg_overrides values are used verbatim when applicable.
    """
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
    """Simulate all unplayed group matches across all 12 groups.

    For each group (A–L), each match with a null winner is simulated using
    the Poisson score model. Matches present in played_groups use their real
    results instead of simulating (D-07). The input groups dict is NOT mutated.

    Args:
        groups: The groups dict loaded from groups.json, with structure
                {"groups": {"A": {"teams": [...], "matches": [...]}, ...}}.
        teams: Dict mapping team names to their data dicts (contains "elo").
        elo_ratings: Pre-computed dict mapping team names to Elo ratings.
        rng: Seeded random.Random instance for reproducibility.
        fair_play: If True, simulate yellow/red cards. If False, all cards
                   set to 0 (avoids 66% of Poisson draws for performance).
        matchup_lambdas: Precomputed λ values for each match. If None,
                         computed on first call (and returned via closure).
        played_groups: Dict of real group match results keyed by match_id.
                       Matches in this dict use real results instead of
                       simulation. Defaults to empty dict.
        base_rate: Base expected goals at Elo-neutral conditions.

    Returns:
        Nested dict: {group_letter: {match_id: match_result_dict}}
        where match_result_dict has keys: team_a, team_b, score_a, score_b,
        winner, yellow_cards_a, red_cards_a, yellow_cards_b, red_cards_b.
    """
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

            # Inject real result if this match was played (D-07)
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

            # Inlined _poisson_sample for score_a
            if la <= 0.0:
                score_a = 0
            else:
                table = build_table(la)
                score_a = table[getrandbits(table_bits)]

            # Inlined _poisson_sample for score_b
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


# ─── Tiebreaker functions ──────────────────────────────────────────────


def _compute_conduct_score(yellow_cards: int, red_cards: int) -> int:
    """Compute fair play conduct score as positive penalty points.

    Per D-04 through D-06 and PITFALLS.md Pitfall 8:
    - Each yellow card = +1 penalty point
    - Each red card (straight) = +4 penalty points

    Lower score = better conduct. This follows RESPONSE.md Clarification 1:
    conduct score is stored as positive penalty points, sorted ASCENDING.

    Args:
        yellow_cards: Total yellow cards for the team across all group matches.
        red_cards: Total red cards (straight) for the team.

    Returns:
        Integer penalty points (lower = better conduct).
    """
    return (yellow_cards * 1) + (red_cards * 4)


def _compute_h2h(
    cluster: list[dict],
    results: dict[str, dict],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Compute H2H points, GD, and GS among a set of tied teams.

    Scans all matches in the group results. Only matches where BOTH teams
    are in the tied set are considered (the 'mini-tournament' among tied teams).

    Args:
        cluster: List of team data dicts (must have 'team' key).
        results: Per-group match results dict (keyed by match_id).

    Returns:
        Tuple of (h2h_pts, h2h_gd, h2h_gs) dicts mapping team -> stat value.
    """
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

        # Points: standard 3/1/0
        if sa > sb:
            h2h_pts[ta] += 3
        elif sb > sa:
            h2h_pts[tb] += 3
        else:
            h2h_pts[ta] += 1
            h2h_pts[tb] += 1

        # Goal difference
        gd = sa - sb
        h2h_gd[ta] += gd
        h2h_gd[tb] -= gd

        # Goals scored
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
    """Try to resolve a tied cluster by grouping teams by a sort value.

    Groups teams by their value for a given tiebreaker criterion. If the
    group creates multiple distinct value tiers, recursively resolve each
    tier using _tiebreak_group (restarting the chain from step 1).

    Args:
        cluster: List of tied team data dicts.
        values: Dict mapping team name -> sort value for this criterion.
        results: Per-group match results dict for H2H recomputation.
        depth: Current recursion depth (to guard against infinite loops).
        reverse: If True, sort descending (higher value = better).

    Returns:
        Sorted list if resolved, or None if all teams have same value
        (no separation at this step).
    """
    groups: dict[int | float, list[dict]] = defaultdict(list)
    for t in cluster:
        groups[values[t["team"]]].append(t)

    if len(groups) == 1:
        return None  # Not resolved at this step

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
    """Apply the full 7-step tiebreaker chain to resolve a tied cluster.

    Each step attempts to separate teams. If a step creates value tiers,
    the separated teams are resolved recursively from step 1 until all
    positions are determined. If all 7 steps fail, team name is used as
    arbitrary deterministic tiebreaker.

    Args:
        cluster: List of team data dicts tied on points.
        results: Per-group match results dict for H2H recomputation.
        depth: Current recursion depth.

    Returns:
        Sorted list of team data dicts.
    """
    if len(cluster) <= 1:
        return cluster

    # Compute H2H stats once (used by steps 1-3)
    h2h_pts, h2h_gd, h2h_gs = _compute_h2h(cluster, results)

    # Steps 1-7: Apply each criterion
    # Step 1: H2H points (higher = better)
    result = _resolve_by_values(cluster, h2h_pts, results, depth, reverse=True)
    if result is not None:
        return result

    # Step 2: H2H goal difference (higher = better)
    result = _resolve_by_values(cluster, h2h_gd, results, depth, reverse=True)
    if result is not None:
        return result

    # Step 3: H2H goals scored (higher = better)
    result = _resolve_by_values(cluster, h2h_gs, results, depth, reverse=True)
    if result is not None:
        return result

    # Step 4: Overall goal difference (higher = better)
    values_gd = {t["team"]: t["gd"] for t in cluster}
    result = _resolve_by_values(cluster, values_gd, results, depth, reverse=True)
    if result is not None:
        return result

    # Step 5: Overall goals scored (higher = better)
    values_gs = {t["team"]: t["gs"] for t in cluster}
    result = _resolve_by_values(cluster, values_gs, results, depth, reverse=True)
    if result is not None:
        return result

    # Step 6: Fair play conduct score (lower = better, ascending)
    values_co = {t["team"]: t["conduct_score"] for t in cluster}
    result = _resolve_by_values(cluster, values_co, results, depth, reverse=False)
    if result is not None:
        return result

    # Step 7: Elo rating as FIFA ranking proxy (higher = better, descending)
    values_elo = {t["team"]: t["elo"] for t in cluster}
    result = _resolve_by_values(cluster, values_elo, results, depth, reverse=True)
    if result is not None:
        return result

    # All 7 steps failed — break ties by team name (deterministic)
    return sorted(cluster, key=lambda t: t["team"])


def _tiebreak_group(
    team_data_list: list[dict],
    results: dict[str, dict],
    depth: int = 0,
) -> list[dict]:
    """Recursively sort a group's teams using the FIFA 2026 7-step tiebreaker.

    Implements recursive narrowing per D-14: teams are first sorted by points.
    Any cluster of teams with equal points enters the 7-step tiebreaker chain.
    When a partial resolution occurs, the resolved team(s) are assigned their
    positions and the remaining tied teams are recursed on from step 1.

    Args:
        team_data_list: List of team data dicts with keys: team, pts, gd, gs,
                        conduct_score, elo.
        results: Per-group match results dict (keyed by match_id).
        depth: Recursion depth guard (raises ValueError if > 10).

    Returns:
        List of team data dicts sorted by final ranking (best first).

    Raises:
        ValueError: If recursion depth exceeds 10 (infinite loop guard).
    """
    if depth > 10:
        raise ValueError("Tiebreaker recursion exceeded max depth")

    n = len(team_data_list)
    if n <= 1:
        return team_data_list

    # Sort by points descending (always the primary criterion)
    sorted_teams = sorted(team_data_list, key=lambda t: t["pts"], reverse=True)

    # Walk the sorted list and resolve tied clusters
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


def compute_standings(
    results: dict[str, dict[str, dict]],
    elo_ratings: dict[str, float],
) -> dict[str, list[dict]]:
    """Compute sorted group standings from match results for all 12 groups.

    For each group (A-L), accumulates points, GD, GS, fair play cards from
    match results, then applies the FIFA 2026 7-step tiebreaker chain via
    _tiebreak_group. Positions 1-4 are assigned after sorting.

    Per RESPONSE.md Clarification 2: `elo_ratings` provides Elo proxy for
    FIFA ranking (step 7 of the tiebreaker). Higher Elo = better = wins
    tiebreak. Phase 10 expected to replace with real FIFA ranking data.

    Args:
        results: Match results dict from simulate_group_matches():
                 {group_letter: {match_id: {team_a, team_b, score_a, score_b,
                 winner, yellow_cards_a, red_cards_a, ...}}}
        elo_ratings: Dict mapping team name -> Elo rating (used as FIFA
                     ranking proxy for step 7 of the tiebreaker).

    Returns:
        Dict mapping group letter to list of team standings dicts sorted
        by final ranking (position 1 = group winner). Each entry has keys:
        team, pts, gd, gs, yellow_cards, red_cards, conduct_score, elo,
        position.
    """
    standings: dict[str, list[dict]] = {}

    for group_letter in "ABCDEFGHIJKL":
        if group_letter not in results:
            continue

        group_results = results[group_letter]

        # Collect unique teams and initialize stats
        team_stats: dict[str, dict] = {}
        for match in group_results.values():
            for side in ("team_a", "team_b"):
                team = match[side]
                if team not in team_stats:
                    team_stats[team] = {
                        "team": team,
                        "pts": 0,
                        "gd": 0,
                        "gs": 0,
                        "yellow_cards": 0,
                        "red_cards": 0,
                        "conduct_score": 0,
                        "elo": elo_ratings.get(team, 1500.0),
                    }

        # Accumulate stats from each match
        for match in group_results.values():
            ta: str = match["team_a"]
            tb: str = match["team_b"]
            sa: int = match["score_a"]
            sb: int = match["score_b"]

            ts_a = team_stats[ta]
            ts_b = team_stats[tb]

            # Points: win=3, draw=1, loss=0
            if sa > sb:
                ts_a["pts"] += 3
            elif sb > sa:
                ts_b["pts"] += 3
            else:
                ts_a["pts"] += 1
                ts_b["pts"] += 1

            # Goal difference
            gd = sa - sb
            ts_a["gd"] += gd
            ts_b["gd"] -= gd

            # Goals scored
            ts_a["gs"] += sa
            ts_b["gs"] += sb

            # Cards (fields always present)
            ts_a["yellow_cards"] += match["yellow_cards_a"]
            ts_a["red_cards"] += match["red_cards_a"]
            ts_b["yellow_cards"] += match["yellow_cards_b"]
            ts_b["red_cards"] += match["red_cards_b"]

        # Compute conduct scores (positive penalty points, lower = better)
        for stats in team_stats.values():
            stats["conduct_score"] = _compute_conduct_score(
                stats["yellow_cards"], stats["red_cards"]
            )

        # Sort using recursive tiebreaker
        team_list = list(team_stats.values())
        team_list = _tiebreak_group(team_list, group_results)

        # Assign final positions 1-4
        for i, t_stats in enumerate(team_list):
            t_stats["position"] = i + 1

        standings[group_letter] = team_list

    return standings


# ─── Third-place ranking and advancement ────────────────────────────────


def rank_third_placed(standings: dict[str, list[dict]]) -> list[dict]:
    """Rank third-placed teams across all 12 groups using 5-step tiebreaker.

    5-step cross-group tiebreaker per D-15 (NO H2H — Pitfall 4 guard):
    1. Overall points (descending)
    2. Overall goal difference (descending)
    3. Overall goals scored (descending)
    4. Fair play conduct_score (ascending — lower positive penalty points = better)
    5. FIFA ranking (ascending — lower rank number = better)

    Uses Elo as FIFA ranking proxy (higher Elo = better = lower rank number).
    Phase 10 expected to replace with real FIFA ranking data.

    Args:
        standings: Output of compute_standings() — dict mapping group letter
                   to list of team standings dicts sorted by position (1-4).

    Returns:
        List of dicts sorted by rank (1st = best, 12th = worst), each with:
        {group, team, pts, gd, gs, conduct_score}.
    """
    third_placed: list[dict] = []

    for group_letter in "ABCDEFGHIJKL":
        if group_letter not in standings:
            continue
        group_standings = standings[group_letter]
        if len(group_standings) < 3:
            continue
        # Position 3 = index 2 (standings are sorted by position 1-4)
        third = group_standings[2]
        entry = {
            "group": group_letter,
            "team": third["team"],
            "pts": third["pts"],
            "gd": third["gd"],
            "gs": third["gs"],
            "conduct_score": third["conduct_score"],
            "_elo": third.get("elo", 1500.0),  # internal — for sorting only
        }
        third_placed.append(entry)

    # Sort by 5-step tiebreaker
    # Use -elo as fifa_rank proxy (higher Elo → lower fifa_rank → sorts earlier)
    third_placed.sort(
        key=lambda t: (-t["pts"], -t["gd"], -t["gs"], t["conduct_score"], -t["_elo"])
    )

    # Strip internal _elo field from output
    result: list[dict] = []
    for t in third_placed:
        result.append({
            "group": t["group"],
            "team": t["team"],
            "pts": t["pts"],
            "gd": t["gd"],
            "gs": t["gs"],
            "conduct_score": t["conduct_score"],
        })

    return result


def select_advancers(
    standings: dict[str, list[dict]],
    third_ranked: list[dict],
) -> dict[str, dict[int, str | None]]:
    """Select top 2 per group + top 8 best third-placed teams.

    Per D-12 and ADVANCEMENT rules:
    - Top 2 from each group (positions 1 and 2) auto-advance → 24 teams
    - Top 8 of the 12 third-placed teams also advance → 8 teams
    - Total advancing: 32 teams (Round of 32)

    Args:
        standings: Output of compute_standings().
        third_ranked: Output of rank_third_placed(), sorted best-to-worst.

    Returns:
        Dict mapping group letter to {1: winner, 2: runner_up, 3: third_team_or_none}.
        Always contains keys 1, 2, 3 for all 12 groups (A-L). Position 4 is
        excluded per D-12. Key 3 is None for groups whose third-placed team
        does not advance.
    """
    # Groups whose third-placed team is in the top 8
    top8_groups: set[str] = {t["group"] for t in third_ranked[:8]}

    advancers: dict[str, dict[int, str | None]] = {}

    for group_letter in "ABCDEFGHIJKL":
        if group_letter not in standings:
            continue
        group = standings[group_letter]
        third_team: str | None = group[2]["team"] if group_letter in top8_groups else None
        advancers[group_letter] = {
            1: group[0]["team"],
            2: group[1]["team"],
            3: third_team,
        }

    return advancers


# ─── Annex C R32 match resolution ──────────────────────────────────────


def resolve_r32_matchups(
    advancers: dict[str, dict[int, str | None]],
    standings: dict[str, list[dict]],
    third_ranked: list[dict],
    annex_c: dict,
) -> dict[str, dict]:
    """Resolve all 16 Round of 32 matches via group_position and Annex C lookup.

    Per ARCHITECTURE §3.1 algorithm:
    1. Select top 8 third-placed teams from third_ranked
    2. Build Annex C key from sorted advancing group letters
    3. Strip _meta key from annex_c and look up assignment
    4. Resolve 8 winner-vs-third matches via Annex C assignment
    5. Resolve 8 fixed matches via group_position slots

    Anti-Pattern 4 guard: winner groups that face third-place teams are
    derived from the R32 match structure (not hardcoded as a separate list).

    Args:
        advancers: Output of select_advancers() — {group: {1: winner, 2: ru, 3: 3rd}}.
        standings: Output of compute_standings() — for full team data per group.
        third_ranked: Output of rank_third_placed() — sorted best-to-worst.
        annex_c: Raw Annex C dict from anneex_c.json (may contain _meta key).

    Returns:
        Dict of 16 match entries: {match_id: {match_id, team_a, team_b}}.
        Keys are M73 through M88 (inclusive).

    Raises:
        ValueError: If the Annex C combination key is not found in the table.
    """
    # Step 1: Determine advancing third-place groups
    top8 = third_ranked[:8]
    advancing_groups = sorted(t["group"] for t in top8)

    # Step 2: Build Annex C key (sorted, comma-separated)
    key = ",".join(advancing_groups)

    # Step 3: Clean _meta and look up
    clean_annex: dict = {k: v for k, v in annex_c.items() if k != "_meta"}
    if key not in clean_annex:
        raise ValueError(
            f"Annex C key not found: {key}. "
            f"This is a data integrity error — all 495 combinations "
            f"should be present."
        )
    assignment: dict[str, str] = clean_annex[key]

    # Build winner_group -> third_group mapping from assignment
    # e.g. "1A" -> "3H" means Winner A faces third-place from Group H
    winner_to_third: dict[str, str] = {}
    for slot_key, third_ref in assignment.items():
        winner_group = slot_key[1:]  # "1A" -> "A"
        third_group = third_ref[1:]  # "3H" -> "H"
        winner_to_third[winner_group] = third_group

    # R32 structure: (match_id, team_a (group, pos), team_b_spec)
    # team_b_spec is either (group, pos) for fixed matches, or None for Annex C
    R32_DEFS: list[tuple[str, tuple[str, int], tuple[str, int] | None]] = [
        ("M73", ("A", 2), ("B", 2)),          # A2 vs B2
        ("M74", ("E", 1), None),               # E1 vs 3rd(E)
        ("M75", ("F", 1), ("C", 2)),           # F1 vs C2
        ("M76", ("C", 1), ("F", 2)),           # C1 vs F2
        ("M77", ("I", 1), None),               # I1 vs 3rd(I)
        ("M78", ("E", 2), ("I", 2)),           # E2 vs I2
        ("M79", ("A", 1), None),               # A1 vs 3rd(A)
        ("M80", ("L", 1), None),               # L1 vs 3rd(L)
        ("M81", ("D", 1), None),               # D1 vs 3rd(D)
        ("M82", ("G", 1), None),               # G1 vs 3rd(G)
        ("M83", ("K", 2), ("L", 2)),           # K2 vs L2
        ("M84", ("H", 1), ("J", 2)),           # H1 vs J2
        ("M85", ("B", 1), None),               # B1 vs 3rd(B)
        ("M86", ("J", 1), ("H", 2)),           # J1 vs H2
        ("M87", ("K", 1), None),               # K1 vs 3rd(K)
        ("M88", ("D", 2), ("G", 2)),           # D2 vs G2
    ]

    matchups: dict[str, dict] = {}

    for mid, team_a_spec, team_b_spec in R32_DEFS:
        team_a_group, team_a_pos = team_a_spec
        team_a = advancers[team_a_group][team_a_pos]

        if team_b_spec is not None:
            # Fixed match: resolve via advancers[group][position]
            team_b_group, team_b_pos = team_b_spec
            team_b = advancers[team_b_group][team_b_pos]
        else:
            # Annex C match: resolve third-place team via assignment
            winner_group = team_a_spec[0]
            third_group = winner_to_third[winner_group]
            team_b = advancers[third_group][3]
            # Safety check: third_group should have an advancing third-placed team
            if team_b is None:
                raise ValueError(
                    f"Group {third_group}'s third-placed team is None in advancers "
                    f"but Annex C assignment expects it for match {mid}."
                )

        matchups[mid] = {
            "match_id": mid,
            "team_a": team_a,
            "team_b": team_b,
        }

    return matchups
