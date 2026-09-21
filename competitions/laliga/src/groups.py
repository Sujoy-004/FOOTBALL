"""LaLiga standings computation — official tiebreaker chain.

Official LaLiga order: points -> head-to-head points -> head-to-head goal
difference -> overall goal difference -> overall goals scored -> fair play
-> playoff. The shared kernel in ``football_core.groups`` resolves a tied
cluster with exactly that precedence (h2h points, h2h GD, h2h goals,
overall GD, overall goals, conduct, Elo), so the standings delegate to it
instead of re-implementing tiebreak logic.
"""

from __future__ import annotations

from football_core.constants import DEFAULT_ELO
from football_core.groups import _tiebreak_group


def played_map_from_rows(results: list[dict]) -> dict[str, dict]:
    """Normalize stored result rows to the flat {match_id: match} seed."""
    flat: dict[str, dict] = {}
    for m in results:
        if not isinstance(m, dict) or not m.get("match_id"):
            continue
        flat[m["match_id"]] = {
            "team_a": m.get("team_a") or m["home_team"],
            "team_b": m.get("team_b") or m["away_team"],
            "home_team": m.get("home_team") or m.get("team_a"),
            "away_team": m.get("away_team") or m.get("team_b"),
            "score_a": m.get("home_score") or 0,
            "score_b": m.get("away_score") or 0,
            "winner": m.get("winner"),
        }
    return flat


def compute_laliga_standings(
    flat_results: dict[str, dict],
    elo_ratings: dict[str, float] | None = None,
) -> list[dict]:
    """Full league table over a flat {match_id: match} result map.

    Deterministic: real results are the only input; ties resolve through
    the shared h2h-first tiebreak kernel. Each returned row carries the
    canonical position-first display shape.
    """
    elo_ratings = elo_ratings or {}
    table: dict[str, dict] = {}
    for match in flat_results.values():
        ta, tb = match["team_a"], match["team_b"]
        sa = match.get("score_a") or 0
        sb = match.get("score_b") or 0
        for team, gf, ga in ((ta, sa, sb), (tb, sb, sa)):
            row = table.setdefault(
                team,
                {"team": team, "played": 0, "wins": 0, "draws": 0,
                 "losses": 0, "goals_for": 0, "goals_against": 0,
                 "gd": 0, "pts": 0},
            )
            row["played"] += 1
            row["goals_for"] += gf
            row["goals_against"] += ga
            row["gd"] += gf - ga
        if sa > sb:
            table[ta]["wins"] += 1
            table[ta]["pts"] += 3
            table[tb]["losses"] += 1
        elif sb > sa:
            table[tb]["wins"] += 1
            table[tb]["pts"] += 3
            table[ta]["losses"] += 1
        else:
            table[ta]["draws"] += 1
            table[ta]["pts"] += 1
            table[tb]["draws"] += 1
            table[tb]["pts"] += 1

    # Tiebreak cluster input: every field the shared kernel may consult
    # (pts/gd/gs/conduct_score/elo) must be present.
    team_data = [
        {**row, "gs": row["goals_for"],
         "conduct_score": 0,  # no booked-cards ledger in shipped data
         "elo": elo_ratings.get(team, float(DEFAULT_ELO))}
        for team, row in sorted(table.items())
    ]

    ordered = _tiebreak_group(team_data, flat_results)
    out = []
    for i, row in enumerate(ordered):
        row = dict(row)
        row["goal_diff"] = row.pop("gd")
        row["points"] = row.pop("pts")
        out.append({"position": i + 1, **row})
    return out