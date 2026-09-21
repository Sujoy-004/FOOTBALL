"""LaLiga competition state — canonical factual view of the active season.

League-only: ``stages.league`` carries the deterministic standings and the
matchday schedule. There is no bracket/knockout layer, so the view is a
flat league shape that the web layer serves directly.
"""

from __future__ import annotations

from competitions.laliga.src import seasons as _season_store
from competitions.laliga.src.constants import DATA_DIR
from competitions.laliga.src.groups import compute_laliga_standings, played_map_from_rows
from competitions.laliga.src.pipeline import load_elo_ratings, load_fixtures, load_results


def build_competition_state(
    data_dir=DATA_DIR,
    mode: str = "results",
    active_season: str | None = None,
    standings: list[dict] | None = None,
) -> dict:
    """Authoritative factual state: standings + grouped matchday fixtures.

    ``standings`` may be injected (e.g. a deterministic table computed once
    by the caller); otherwise it is recomputed from the results store.
    """
    season_token = active_season or _season_store.active_season(data_dir)
    fixtures = load_fixtures(data_dir, season_token)
    if standings is None:
        results = load_results(data_dir, season_token)
        elo_ratings = load_elo_ratings(data_dir, season_token)
        standings = compute_laliga_standings(played_map_from_rows(results), elo_ratings)
    else:
        results = load_results(data_dir, season_token)
    score_by_id: dict[str, tuple] = {}
    for m in results:
        if m.get("match_id"):
            score_by_id[m["match_id"]] = (m.get("home_score"), m.get("away_score"))

    matchdays: dict[int, list[dict]] = {}
    for f in fixtures:
        try:
            md = int(f.get("matchday") or 0)
        except (TypeError, ValueError):
            md = 0
        hs, as_ = score_by_id.get(f["match_id"], (None, None))
        matchdays.setdefault(md, []).append({
            "match_id": f["match_id"],
            "team_a": f["home_team"],
            "team_b": f["away_team"],
            "home_team": f["home_team"],
            "away_team": f["away_team"],
            "home_score": hs,
            "away_score": as_,
            "event_date": f.get("event_date"),
            "status": f.get("status"),
        })

    return {
        "season": season_token,
        "mode": mode,
        "champion": None,
        "error": None,
        "n_teams": len(standings),
        "stages": {
            "league": {
                "standings": standings,
                "matchdays": [
                    {"matchday": md, "matches": sorted(matchdays[md], key=lambda m: m.get("event_date") or "")}
                    for md in sorted(matchdays)
                ],
            }
        },
    }