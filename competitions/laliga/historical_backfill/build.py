"""Build orchestrator for the historical LaLiga backfill.

Runs the two source adapters (football-data.co.uk SP1 results+odds, ClubElo
snapshots), assembles the leak-free per-season dataset under
``competitions/laliga/data/historical/``, writes provenance, and validates
counts / duplicates / team-key coverage / odds and Elo coverage before
merging into a single evaluation-ready replay file.

The per-season dataset layout (``matches.json`` + a FROZEN per-season
``elo_ratings.json`` taken strictly before that season's first match) is
what keeps the evaluation leak-free: nothing recomputes a rating with an
in-season outcome, so no future data can reach a prediction. The generic
part of that contract (validation, provenance writing, replay summary) lives
once in ``football_core.historical_backfill``; this module is the LaLiga
configuration of it.

Adapter entrypoints (implemented by the source submodules):

    from competitions.laliga.historical_backfill.sources.results_fd import (
        fetch_football_data_matches,
    )
    from competitions.laliga.historical_backfill.sources.elo_clubelo import (
        fetch_elo_snapshots,
    )

    results: dict[str, list[dict]] = fetch_football_data_matches()
        # season keyed "2019_20".."2023_24"; each match dict has
        #   team_a, team_b (canonical keys),
        #   home_score, away_score, event_date (ISO-8601 UTC),
        #   odds_home/odds_draw/odds_away, odds_bookmaker, odds_known_at

    elo: dict[str, dict[str, float]] = fetch_elo_snapshots()
        # canonical team key -> ClubElo archive snapshot strictly before the
        # season's first match; every canonical team of that season present.
"""

from __future__ import annotations

import json
import os
import sys

from football_core.historical_backfill import (
    assert_season_clean,
    summarize_replay,
    used_elo_map,
    validate_season as _validate_season,
    write_json,
    write_season_dataset,
)

from competitions.laliga.historical_backfill.contract import (
    HISTORICAL_DIR,
    SCHEMA,
    SEASONS,
    match_id,
    season_dir,
)


def _retrieve() -> tuple[dict, dict]:
    from competitions.laliga.historical_backfill.sources.elo_clubelo import (
        fetch_elo_snapshots,
    )
    from competitions.laliga.historical_backfill.sources.results_fd import (
        fetch_football_data_matches,
    )

    results = fetch_football_data_matches()
    elo = fetch_elo_snapshots()
    return results, elo


def build(verify_only: bool = False) -> dict:
    results, elo = _retrieve()

    summary: dict = {"seasons": {}, "replay": {}, "provenance_hashes": {}}
    replay_matches: list[dict] = []

    for season, label in SEASONS.items():
        matches = results[season]
        ordered = sorted(matches, key=lambda m: m["event_date"])
        for i, m in enumerate(ordered, start=1):
            m["match_id"] = match_id(season, i)
        elo_map = elo[season]
        check = _validate_season(season, ordered, elo_map)
        summary["seasons"][season] = check
        assert_season_clean(season, check)

        elo_map_used = used_elo_map(elo_map, ordered)

        if not verify_only:
            summary["provenance_hashes"][season] = write_season_dataset(
                HISTORICAL_DIR, season, label, ordered, elo_map_used, check,
                _provenance_sources(season),
            )
        replay_matches.extend(ordered)

    merged = {
        "schema": SCHEMA,
        "seasons": list(SEASONS.values()),
        "matches": replay_matches,
    }
    summary["replay"] = summarize_replay(replay_matches)
    if not verify_only:
        write_json(
            os.path.join(HISTORICAL_DIR, "replay_2019_20_2023_24.json"), merged
        )
    return summary


def os_season(season: str, name: str) -> str:
    return os.path.join(season_dir(season), name)


def _provenance_sources(season: str) -> dict:
    return {
        "results_odds": {
            "name": "football-data.co.uk SP1 archive",
            "url": (
                "https://www.football-data.co.uk/mmz4281/{code}/SP1.csv "
                "(season 2019/20-2023/24)"
            ),
            "license": "free for research use (see football-data.co.uk/terms.php)",
            "note": (
                "single authoritative file per season: 380 completed matches "
                "of a 20-team double round-robin with final scores and closing "
                "1X2 odds; bookmaker preference Pinnacle -> Bet365 -> Max "
                "-> Avg; odds_known_at recorded as the kickoff event_date "
                "(closing line knowable at kickoff)"
            ),
        },
        "elo": {
            "name": "xgabora/Club-Football-Match-Data EloRatings.csv",
            "url": (
                "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data/"
                "master/data/EloRatings.csv"
            ),
            "license": "MIT (ClubElo archive snapshots)",
            "deviation": (
                "live api.clubelo.com unreachable from this environment; "
                "using MIT-licensed ClubElo snapshot mirror strictly before "
                "each season's first match (pre-match, no leakage)"
            ),
        },
        "team_keys": {
            "canonical": "data/team_aliases.json keys; long-form aliases used "
            "by the 2026/27 production fixtures preferred where present",
            "extras": "teams absent from 2026/27 (e.g. Almeria, Cadiz, Eibar, "
            "Girona, Granada, Huesca, Las Palmas, Leganes, Mallorca, "
            "Valladolid) get stable new keys via backfill/team_map.py",
        },
    }


if __name__ == "__main__":
    flag = "--verify-only" in sys.argv
    print(json.dumps(build(verify_only=flag), indent=2))
