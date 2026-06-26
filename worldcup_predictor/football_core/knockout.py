"""Generic knockout tournament primitives: round map building, match simulation, blended probabilities."""

import random

from football_core.elo import expected_score


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
