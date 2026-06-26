"""Euro 2024 tournament simulation: 6 groups, top 2 + 4 best 3rd, R16->QF->SF->FINAL."""

import random
from collections import defaultdict

from football_core import constants
from football_core.elo import expected_score
from src.groups import (
    compute_standings,
    precompute_matchup_lambdas,
    rank_third_placed,
    select_advancers,
    simulate_group_matches,
)

from competitions.euro import config


def expected_goals(rating_a: float, rating_b: float, base_rate: float) -> float:
    adj_base = base_rate * config.HOME_ADVANTAGE_MULTIPLIER
    return min(
        adj_base * (10.0 ** ((rating_a - rating_b) / 400.0)),
        constants.MAX_EXPECTED_GOALS,
    )


def compute_euro_standings(
    results: dict[str, dict[str, dict]],
    elo_ratings: dict[str, float],
) -> dict[str, list[dict]]:
    standings: dict[str, list[dict]] = {}
    for group_letter in "ABCDEF":
        if group_letter not in results:
            continue
        group_results = results[group_letter]
        team_stats: dict[str, dict] = {}
        for match in group_results.values():
            for side in ("team_a", "team_b"):
                team = match[side]
                if team not in team_stats:
                    team_stats[team] = {
                        "team": team, "pts": 0, "gd": 0, "gs": 0,
                        "yellow_cards": 0, "red_cards": 0, "conduct_score": 0,
                        "elo": elo_ratings.get(team, 1500.0),
                    }
        for match in group_results.values():
            ta, tb = match["team_a"], match["team_b"]
            sa, sb = match["score_a"], match["score_b"]
            ts_a, ts_b = team_stats[ta], team_stats[tb]
            if sa > sb:
                ts_a["pts"] += 3
            elif sb > sa:
                ts_b["pts"] += 3
            else:
                ts_a["pts"] += 1
                ts_b["pts"] += 1
            gd = sa - sb
            ts_a["gd"] += gd
            ts_b["gd"] -= gd
            ts_a["gs"] += sa
            ts_b["gs"] += sb
        team_list = sorted(team_stats.values(), key=lambda t: t["pts"], reverse=True)
        for i, t in enumerate(team_list):
            t["position"] = i + 1
        standings[group_letter] = team_list
    return standings


def rank_euro_third_placed(
    standings: dict[str, list[dict]],
) -> list[dict]:
    third_placed: list[dict] = []
    for group_letter in "ABCDEF":
        if group_letter not in standings:
            continue
        group_standings = standings[group_letter]
        if len(group_standings) < 3:
            continue
        third = group_standings[2]
        third_placed.append({
            "group": group_letter,
            "team": third["team"],
            "pts": third["pts"],
            "gd": third["gd"],
            "gs": third["gs"],
            "conduct_score": third.get("conduct_score", 0),
            "_elo": third.get("elo", 1500.0),
        })
    third_placed.sort(
        key=lambda t: (-t["pts"], -t["gd"], -t["gs"], t["conduct_score"], -t["_elo"])
    )
    result: list[dict] = []
    for t in third_placed:
        result.append({
            "group": t["group"], "team": t["team"],
            "pts": t["pts"], "gd": t["gd"], "gs": t["gs"],
            "conduct_score": t["conduct_score"],
        })
    return result


def select_euro_advancers(
    standings: dict[str, list[dict]],
    third_ranked: list[dict],
) -> dict[str, dict[int, str | None]]:
    top4_groups: set[str] = {t["group"] for t in third_ranked[:4]}
    advancers: dict[str, dict[int, str | None]] = {}
    for group_letter in "ABCDEF":
        if group_letter not in standings:
            continue
        group = standings[group_letter]
        third_team: str | None = group[2]["team"] if group_letter in top4_groups else None
        advancers[group_letter] = {1: group[0]["team"], 2: group[1]["team"], 3: third_team}
    return advancers


def resolve_r16_matchups(
    advancers: dict[str, dict[int, str | None]],
    third_ranked: list[dict],
    bracket: list[dict],
) -> dict[str, dict]:
    top4_third = {t["group"]: t["team"] for t in third_ranked[:4]}
    matchups: dict[str, dict] = {}
    for match in bracket:
        mid = match["match_id"]
        if match.get("round") != "R16":
            continue
        home_spec = match.get("home", {})
        away_spec = match.get("away", {})
        if home_spec.get("kind") == "group_position":
            team_a = advancers[home_spec["group"]][home_spec["position"]]
        elif home_spec.get("kind") == "third_place":
            team_a = _resolve_third_place(home_spec["groups"], top4_third)
        else:
            team_a = None
        if away_spec.get("kind") == "group_position":
            team_b = advancers[away_spec["group"]][away_spec["position"]]
        elif away_spec.get("kind") == "third_place":
            team_b = _resolve_third_place(away_spec["groups"], top4_third)
        else:
            team_b = None
        if team_a is None or team_b is None:
            continue
        matchups[mid] = {"match_id": mid, "team_a": team_a, "team_b": team_b}
    return matchups


def _resolve_third_place(
    candidate_groups: list[str],
    top4_third: dict[str, str],
) -> str | None:
    for g in candidate_groups:
        if g in top4_third:
            return top4_third[g]
    return None


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


def _build_round_map(bracket: list[dict]) -> dict[str, list[dict]]:
    round_map: dict[str, list[dict]] = {}
    for match in bracket:
        r = match["round"]
        if r not in round_map:
            round_map[r] = []
        round_map[r].append(match)
    for r in round_map:
        round_map[r].sort(key=lambda m: m["match_id"])
    return round_map


def _simulate_r16_resolved(
    r16_matchups: dict[str, dict],
    played: dict[str, dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
    blend_params: dict | None = None,
) -> dict[str, str]:
    winner_progression: dict[str, str] = {}
    for mid, match in r16_matchups.items():
        if mid in played:
            winner_progression[mid] = played[mid]["winner"]
            continue
        team_a = match["team_a"]
        team_b = match["team_b"]
        p_a = _get_blended_prob(mid, team_a, team_b, blend_params, elo_ratings)
        winner_progression[mid] = team_a if rng.random() < p_a else team_b
    return winner_progression


def _simulate_knockout_round(
    round_map: dict[str, list[dict]],
    round_name: str,
    played: dict[str, dict],
    winner_progression: dict[str, str],
    rng: random.Random,
    elo_ratings: dict[str, float],
    blend_params: dict | None = None,
) -> None:
    for match in round_map.get(round_name, []):
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


def resolve_knockout_slot_teams(
    groups: dict,
    teams: dict[str, dict],
    played_groups: dict[str, dict],
    bracket: list[dict],
    known_winners: dict[str, str],
) -> dict[str, dict]:
    rng = random.Random(0)
    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    lambdas = precompute_matchup_lambdas(groups, elo_ratings, base_rate=config.EXPECTED_GOALS_BASE_RATE)
    results = simulate_group_matches(
        groups, teams, elo_ratings, rng,
        played_groups=played_groups, matchup_lambdas=lambdas,
        base_rate=config.EXPECTED_GOALS_BASE_RATE,
    )
    standings = compute_standings(results, elo_ratings)
    third_ranked = rank_third_placed(standings)
    advancers = select_advancers(standings, third_ranked)
    r16_matchups = resolve_r16_matchups(advancers, third_ranked, bracket)
    slot_teams: dict[str, dict] = {}
    winner_progression: dict[str, str] = dict(known_winners)
    for mid, m in r16_matchups.items():
        slot_teams[mid] = {"team_a": m["team_a"], "team_b": m["team_b"]}
    round_map = _build_round_map(bracket)
    resolution_order = ["R16", "QF", "SF", "FINAL"]
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
    matchup_lambdas = precompute_matchup_lambdas(groups, elo_ratings, base_rate=config.EXPECTED_GOALS_BASE_RATE, xg_overrides=xg_overrides)
    for _ in range(iterations):
        results = simulate_group_matches(
            groups, teams, elo_ratings, rng,
            fair_play=False, matchup_lambdas=matchup_lambdas,
            played_groups=played_groups, base_rate=config.EXPECTED_GOALS_BASE_RATE,
        )
        standings = compute_euro_standings(results, elo_ratings)
        third_ranked = rank_euro_third_placed(standings)
        advancers = select_euro_advancers(standings, third_ranked)
        r16_matchups = resolve_r16_matchups(advancers, third_ranked, bracket)
        winner_progression = _simulate_r16_resolved(r16_matchups, played, elo_ratings, rng, blend_params)
        for rn in ["QF", "SF"]:
            _simulate_knockout_round(round_map, rn, played, winner_progression, rng, elo_ratings, blend_params)
        _simulate_knockout_round(round_map, "FINAL", played, winner_progression, rng, elo_ratings, blend_params)
        for round_name in config.ROUND_ORDER:
            if round_name not in round_map:
                continue
            for match in round_map[round_name]:
                sources = match.get("source_matches")
                if sources is None:
                    continue
                for src in sources:
                    if src in winner_progression:
                        team = winner_progression[src]
                        rk = config.ROUND_KEYS.get(round_name)
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
