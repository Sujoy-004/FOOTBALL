"""Full tournament simulation: group stage -> Annex C -> R32 -> knockout."""

import random
from collections import defaultdict

from src.elo import expected_score
from src.groups import (
    compute_standings,
    precompute_matchup_lambdas,
    rank_third_placed,
    select_advancers,
    resolve_r32_matchups,
    simulate_group_matches,
)

ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]
ROUND_KEYS = {"QF": "qf", "SF": "sf", "FINAL": "final"}


def _build_round_map(bracket: list[dict]) -> dict[str, list[dict]]:
    round_map: dict[str, list[dict]] = {}
    for match in bracket:
        r = match["round"]
        if r == "R32":
            continue
        if r not in round_map:
            round_map[r] = []
        round_map[r].append(match)
    for r in round_map:
        round_map[r].sort(key=lambda m: m["match_id"])
    return round_map


def _simulate_r32_resolved(
    r32_matchups: dict[str, dict],
    played: dict[str, dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
) -> dict[str, str]:
    winner_progression: dict[str, str] = {}
    for mid, match in r32_matchups.items():
        if mid in played:
            winner_progression[mid] = played[mid]["winner"]
            continue
        team_a = match["team_a"]
        team_b = match["team_b"]
        p_a = expected_score(elo_ratings[team_a], elo_ratings[team_b])
        winner_progression[mid] = team_a if rng.random() < p_a else team_b
    return winner_progression


def _simulate_r16(
    round_map: dict[str, list[dict]],
    played: dict[str, dict],
    winner_progression: dict[str, str],
    rng: random.Random,
    elo_ratings: dict[str, float],
) -> None:
    for match in round_map.get("R16", []):
        mid = match["match_id"]
        if mid in played:
            winner_progression[mid] = played[mid]["winner"]
            continue
        sources = match["source_matches"]
        teams_in_match = [winner_progression[s] for s in sources]
        if len(teams_in_match) == 1:
            winner_progression[mid] = teams_in_match[0]
        else:
            team_a, team_b = teams_in_match[0], teams_in_match[1]
            p_a = expected_score(elo_ratings[team_a], elo_ratings[team_b])
            winner_progression[mid] = team_a if rng.random() < p_a else team_b


def _simulate_knockout_round(
    round_map: dict[str, list[dict]],
    round_name: str,
    played: dict[str, dict],
    winner_progression: dict[str, str],
    sf_losers: dict[str, str | None] | None,
    rng: random.Random,
    elo_ratings: dict[str, float],
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
            p_a = expected_score(elo_ratings[team_a], elo_ratings[team_b])
            if rng.random() < p_a:
                winner_progression[mid] = team_a
                if sf_losers is not None and round_name == "SF":
                    sf_losers[mid] = team_b
            else:
                winner_progression[mid] = team_b
                if sf_losers is not None and round_name == "SF":
                    sf_losers[mid] = team_a


def _simulate_tpp(
    round_map: dict[str, list[dict]],
    played: dict[str, dict],
    winner_progression: dict[str, str],
    sf_losers: dict[str, str | None],
    rng: random.Random,
    elo_ratings: dict[str, float],
) -> None:
    for match in round_map.get("TPP", []):
        mid = match["match_id"]
        if mid in played:
            winner_progression[mid] = played[mid]["winner"]
            continue
        sources = match["source_matches"]
        teams_in_match = [sf_losers.get(s) for s in sources]
        if None in teams_in_match or len(teams_in_match) < 2:
            continue
        team_a, team_b = teams_in_match[0], teams_in_match[1]
        p_a = expected_score(elo_ratings[team_a], elo_ratings[team_b])
        winner_progression[mid] = team_a if rng.random() < p_a else team_b


def run_full_simulation(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    played: dict[str, dict],
    iterations: int = 50000,
    seed: int | None = None,
    played_groups: dict[str, dict] | None = None,
) -> dict[str, dict[str, float]]:
    """Run full tournament simulation: group stage -> Annex C -> knockout.

    Args:
        teams: Dict of team name -> team data.
        groups: Group definitions dict.
        bracket: Knockout bracket match list.
        annex_c: Annex C third-place lookup table.
        played: Dict of played knockout matches.
        iterations: Number of Monte Carlo iterations (default 50000).
        seed: Random seed for reproducibility.
        played_groups: Dict of played group match results. Forwarded to
                       simulate_group_matches() so real results are used
                       instead of simulating.

    Returns:
        Dict mapping team name to dict of probabilities for each round.
    """
    rng = random.Random(seed)
    round_map = _build_round_map(bracket)
    elo_ratings = {name: data["elo"] for name, data in teams.items()}

    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Precompute λ values once (Elo ratings don't change across iterations)
    matchup_lambdas = precompute_matchup_lambdas(groups, elo_ratings)

    for _ in range(iterations):
        winner_progression: dict[str, str] = {}
        sf_losers: dict[str, str | None] = {}

        results = simulate_group_matches(groups, teams, elo_ratings, rng, fair_play=False, matchup_lambdas=matchup_lambdas, played_groups=played_groups)
        standings = compute_standings(results, elo_ratings)
        third_ranked = rank_third_placed(standings)
        advancers = select_advancers(standings, third_ranked)
        r32_matchups = resolve_r32_matchups(advancers, standings, third_ranked, annex_c)

        wp = _simulate_r32_resolved(r32_matchups, played, elo_ratings, rng)
        winner_progression.update(wp)

        _simulate_r16(round_map, played, winner_progression, rng, elo_ratings)

        for rn in ["QF", "SF"]:
            _simulate_knockout_round(
                round_map, rn, played, winner_progression, sf_losers, rng, elo_ratings
            )

        _simulate_tpp(round_map, played, winner_progression, sf_losers, rng, elo_ratings)

        _simulate_knockout_round(
            round_map, "FINAL", played, winner_progression, None, rng, elo_ratings
        )

        for round_name in ROUND_ORDER:
            if round_name not in round_map:
                continue
            for match in round_map[round_name]:
                sources = match.get("source_matches")
                if sources is None:
                    continue
                for src in sources:
                    if src in winner_progression:
                        team = winner_progression[src]
                        rk = ROUND_KEYS.get(round_name)
                        if rk:
                            counts[team][rk] += 1

        if "FINAL" in winner_progression:
            counts[winner_progression["FINAL"]]["champion"] += 1

    result: dict[str, dict[str, float]] = {}
    for team in teams:
        result[team] = {
            "qf": counts[team].get("qf", 0) / iterations,
            "sf": counts[team].get("sf", 0) / iterations,
            "final": counts[team].get("final", 0) / iterations,
            "champion": counts[team].get("champion", 0) / iterations,
        }

    return result
