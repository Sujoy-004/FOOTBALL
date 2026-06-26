"""Full tournament simulation: group stage -> Annex C -> R32 -> knockout."""

import random
from collections import defaultdict

from src import constants
from src.elo import expected_score
from src.groups import (
    compute_standings,
    rank_third_placed,
    select_advancers,
    resolve_r32_matchups,
)
from football_core.groups import (
    precompute_matchup_lambdas,
    simulate_group_matches,
)
from football_core.knockout import (
    _build_round_map,
    _simulate_knockout_round,
    _get_blended_prob,
)

ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]
ROUND_KEYS = {"QF": "qf", "SF": "sf", "FINAL": "final"}


def _simulate_r32_resolved(
    r32_matchups: dict[str, dict],
    played: dict[str, dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
    blend_params: dict | None = None,
) -> dict[str, str]:
    winner_progression: dict[str, str] = {}
    for mid, match in r32_matchups.items():
        if mid in played:
            winner_progression[mid] = played[mid]["winner"]
            continue
        team_a = match["team_a"]
        team_b = match["team_b"]
        p_a = _get_blended_prob(mid, team_a, team_b, blend_params, elo_ratings)
        winner_progression[mid] = team_a if rng.random() < p_a else team_b
    return winner_progression


def _simulate_r16(
    round_map: dict[str, list[dict]],
    played: dict[str, dict],
    winner_progression: dict[str, str],
    rng: random.Random,
    elo_ratings: dict[str, float],
    blend_params: dict | None = None,
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
            p_a = _get_blended_prob(mid, team_a, team_b, blend_params, elo_ratings)
            winner_progression[mid] = team_a if rng.random() < p_a else team_b


def _simulate_tpp(
    round_map: dict[str, list[dict]],
    played: dict[str, dict],
    winner_progression: dict[str, str],
    sf_losers: dict[str, str | None],
    rng: random.Random,
    elo_ratings: dict[str, float],
    blend_params: dict | None = None,
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
        p_a = _get_blended_prob(mid, team_a, team_b, blend_params, elo_ratings)
        winner_progression[mid] = team_a if rng.random() < p_a else team_b


def resolve_knockout_slot_teams(
    groups: dict,
    teams: dict[str, dict],
    played_groups: dict[str, dict],
    bracket: list[dict],
    annex_c: dict,
    known_winners: dict[str, str],
) -> dict[str, dict]:
    import random

    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    rng = random.Random(0)

    lambdas = precompute_matchup_lambdas(groups, elo_ratings, base_rate=constants.EXPECTED_GOALS_BASE_RATE)
    results = simulate_group_matches(
        groups, teams, elo_ratings, rng,
        played_groups=played_groups, matchup_lambdas=lambdas,
        base_rate=constants.EXPECTED_GOALS_BASE_RATE,
    )
    standings = compute_standings(results, elo_ratings)
    third_ranked = rank_third_placed(standings)
    advancers = select_advancers(standings, third_ranked)
    r32_matchups = resolve_r32_matchups(advancers, standings, third_ranked, annex_c)

    slot_teams: dict[str, dict] = {}
    winner_progression: dict[str, str] = dict(known_winners)

    for mid, m in r32_matchups.items():
        slot_teams[mid] = {"team_a": m["team_a"], "team_b": m["team_b"]}

    round_map = _build_round_map(bracket)
    resolution_order = ["R16", "QF", "SF", "TPP", "FINAL"]

    changed = True
    while changed:
        changed = False
        for round_name in resolution_order:
            for match in round_map.get(round_name, []):
                mid = match["match_id"]
                if mid in slot_teams:
                    continue
                sources = match.get("source_matches", [])
                if len(sources) != 2:
                    continue

                if round_name == "TPP":
                    if "SF_1" not in slot_teams or "SF_2" not in slot_teams:
                        continue
                    if "SF_1" not in winner_progression or "SF_2" not in winner_progression:
                        continue
                    s1 = slot_teams["SF_1"]
                    sf1_loser = s1["team_b"] if winner_progression["SF_1"] == s1["team_a"] else s1["team_a"]
                    s2 = slot_teams["SF_2"]
                    sf2_loser = s2["team_b"] if winner_progression["SF_2"] == s2["team_a"] else s2["team_a"]
                    slot_teams[mid] = {"team_a": sf1_loser, "team_b": sf2_loser}
                    changed = True
                else:
                    if sources[0] in winner_progression and sources[1] in winner_progression:
                        slot_teams[mid] = {
                            "team_a": winner_progression[sources[0]],
                            "team_b": winner_progression[sources[1]],
                        }
                        changed = True

    return slot_teams


def run_full_simulation(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    played: dict[str, dict],
    iterations: int = 50000,
    seed: int | None = None,
    played_groups: dict[str, dict] | None = None,
    blend_params: dict | None = None,
    xg_overrides: dict[str, tuple[float, float]] | None = None,
) -> dict[str, dict[str, float]]:
    rng = random.Random(seed)
    round_map = _build_round_map(bracket)
    elo_ratings = {name: data["elo"] for name, data in teams.items()}

    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    matchup_lambdas = precompute_matchup_lambdas(groups, elo_ratings, base_rate=constants.EXPECTED_GOALS_BASE_RATE, xg_overrides=xg_overrides)

    for _ in range(iterations):
        winner_progression: dict[str, str] = {}
        sf_losers: dict[str, str | None] = {}

        results = simulate_group_matches(groups, teams, elo_ratings, rng, fair_play=False, matchup_lambdas=matchup_lambdas, played_groups=played_groups, base_rate=constants.EXPECTED_GOALS_BASE_RATE)
        standings = compute_standings(results, elo_ratings)
        third_ranked = rank_third_placed(standings)
        advancers = select_advancers(standings, third_ranked)
        r32_matchups = resolve_r32_matchups(advancers, standings, third_ranked, annex_c)

        wp = _simulate_r32_resolved(r32_matchups, played, elo_ratings, rng, blend_params)
        winner_progression.update(wp)

        _simulate_r16(round_map, played, winner_progression, rng, elo_ratings, blend_params)

        for rn in ["QF", "SF"]:
            _simulate_knockout_round(
                round_map, rn, played, winner_progression, sf_losers, rng, elo_ratings, blend_params
            )

        _simulate_tpp(round_map, played, winner_progression, sf_losers, rng, elo_ratings, blend_params)

        _simulate_knockout_round(
            round_map, "FINAL", played, winner_progression, None, rng, elo_ratings, blend_params
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
