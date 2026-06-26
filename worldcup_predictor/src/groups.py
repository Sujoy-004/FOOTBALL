"""Group stage simulation — extends football_core with WC-specific standings/advancement."""

from football_core.groups import (
    expected_goals,
    _build_poisson_table,
    _poisson_sample,
    _simulate_single_match,
    precompute_matchup_lambdas,
    simulate_group_matches,
    _compute_conduct_score,
    _compute_h2h,
    _resolve_by_values,
    _resolve_tied_cluster,
    _tiebreak_group,
)

from src import constants
from src.constants import MAX_EXPECTED_GOALS, HOME_ADVANTAGE_MULTIPLIER


def compute_standings(
    results: dict[str, dict[str, dict]],
    elo_ratings: dict[str, float],
) -> dict[str, list[dict]]:
    standings: dict[str, list[dict]] = {}

    for group_letter in "ABCDEFGHIJKL":
        if group_letter not in results:
            continue

        group_results = results[group_letter]

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

        for match in group_results.values():
            ta: str = match["team_a"]
            tb: str = match["team_b"]
            sa: int = match["score_a"]
            sb: int = match["score_b"]

            ts_a = team_stats[ta]
            ts_b = team_stats[tb]

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

            ts_a["yellow_cards"] += match["yellow_cards_a"]
            ts_a["red_cards"] += match["red_cards_a"]
            ts_b["yellow_cards"] += match["yellow_cards_b"]
            ts_b["red_cards"] += match["red_cards_b"]

        for stats in team_stats.values():
            stats["conduct_score"] = _compute_conduct_score(
                stats["yellow_cards"], stats["red_cards"]
            )

        team_list = list(team_stats.values())
        team_list = _tiebreak_group(team_list, group_results)

        for i, t_stats in enumerate(team_list):
            t_stats["position"] = i + 1

        standings[group_letter] = team_list

    return standings


def rank_third_placed(standings: dict[str, list[dict]]) -> list[dict]:
    third_placed: list[dict] = []

    for group_letter in "ABCDEFGHIJKL":
        if group_letter not in standings:
            continue
        group_standings = standings[group_letter]
        if len(group_standings) < 3:
            continue
        third = group_standings[2]
        entry = {
            "group": group_letter,
            "team": third["team"],
            "pts": third["pts"],
            "gd": third["gd"],
            "gs": third["gs"],
            "conduct_score": third["conduct_score"],
            "_elo": third.get("elo", 1500.0),
        }
        third_placed.append(entry)

    third_placed.sort(
        key=lambda t: (-t["pts"], -t["gd"], -t["gs"], t["conduct_score"], -t["_elo"])
    )

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


def resolve_r32_matchups(
    advancers: dict[str, dict[int, str | None]],
    standings: dict[str, list[dict]],
    third_ranked: list[dict],
    annex_c: dict,
) -> dict[str, dict]:
    top8 = third_ranked[:8]
    advancing_groups = sorted(t["group"] for t in top8)
    key = ",".join(advancing_groups)

    clean_annex: dict = {k: v for k, v in annex_c.items() if k != "_meta"}
    if key not in clean_annex:
        raise ValueError(
            f"Annex C key not found: {key}. "
            f"This is a data integrity error — all 495 combinations "
            f"should be present."
        )
    assignment: dict[str, str] = clean_annex[key]

    winner_to_third: dict[str, str] = {}
    for slot_key, third_ref in assignment.items():
        winner_group = slot_key[1:]
        third_group = third_ref[1:]
        winner_to_third[winner_group] = third_group

    R32_DEFS: list[tuple[str, tuple[str, int], tuple[str, int] | None]] = [
        ("M73", ("A", 2), ("B", 2)),
        ("M74", ("E", 1), None),
        ("M75", ("F", 1), ("C", 2)),
        ("M76", ("C", 1), ("F", 2)),
        ("M77", ("I", 1), None),
        ("M78", ("E", 2), ("I", 2)),
        ("M79", ("A", 1), None),
        ("M80", ("L", 1), None),
        ("M81", ("D", 1), None),
        ("M82", ("G", 1), None),
        ("M83", ("K", 2), ("L", 2)),
        ("M84", ("H", 1), ("J", 2)),
        ("M85", ("B", 1), None),
        ("M86", ("J", 1), ("H", 2)),
        ("M87", ("K", 1), None),
        ("M88", ("D", 2), ("G", 2)),
    ]

    matchups: dict[str, dict] = {}

    for mid, team_a_spec, team_b_spec in R32_DEFS:
        team_a_group, team_a_pos = team_a_spec
        team_a = advancers[team_a_group][team_a_pos]

        if team_b_spec is not None:
            team_b_group, team_b_pos = team_b_spec
            team_b = advancers[team_b_group][team_b_pos]
        else:
            winner_group = team_a_spec[0]
            third_group = winner_to_third[winner_group]
            team_b = advancers[third_group][3]
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
