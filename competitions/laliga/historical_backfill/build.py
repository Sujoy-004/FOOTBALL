"""Build orchestrator for the historical LaLiga backfill.

Runs the two source adapters (football-data.co.uk SP1 results+odds, ClubElo
snapshots), assembles the leak-free per-season dataset under
``competitions/laliga/data/historical/``, writes provenance, and validates
counts / duplicates / team-key coverage / odds and Elo coverage before
merging into a single evaluation-ready replay file.

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
from datetime import datetime, timezone

from competitions.laliga.historical_backfill.contract import (
    HISTORICAL_DIR,
    SEASONS,
    duplicate_keys,
    match_id,
    season_dir,
    write_json,
)

SCHEMA = 1


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


def _validate_season(season: str, matches: list[dict], elo_map: dict[str, float]) -> dict:
    dup = duplicate_keys(matches)
    used_keys: set[str] = set()
    for m in matches:
        used_keys.add(m["team_a"])
        used_keys.add(m["team_b"])
    missing_elo = sorted(k for k in used_keys if k not in elo_map)
    return {
        "season": season,
        "n_matches": len(matches),
        "duplicate_match_ids": dup,
        "n_teams": len(used_keys),
        "elo_missing_teams": missing_elo,
        "n_odds": sum(
            1
            for m in matches
            if None not in (m.get("odds_home"), m.get("odds_draw"), m.get("odds_away"))
        ),
        "min_date": min(m["event_date"] for m in matches),
        "max_date": max(m["event_date"] for m in matches),
    }


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
        if check["duplicate_match_ids"]:
            raise AssertionError(f"{season}: duplicate match ids {check['duplicate_match_ids']}")
        if check["elo_missing_teams"]:
            print(
                f"WARNING {season}: no ClubElo contributor for "
                f"{check['elo_missing_teams']} — recorded in PROVENANCE "
                "(RefinedEloSignal falls back to DEFAULT_ELO for these, "
                "matching production semantics); coverage maintained for the "
                "other participants"
            )

        used_keys = {m["team_a"] for m in ordered} | {m["team_b"] for m in ordered}
        elo_map_used = {k: elo_map[k] for k in sorted(used_keys) if k in elo_map}

        if not verify_only:
            prov = {
                "schema": SCHEMA,
                "season": label,
                "storage_deviation": (
                    "stored under data/historical instead of the approved "
                    "data/seasons path because that path is the gitignored "
                    "runtime season store"
                ),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "checks": check,
                "files": {
                    "matches": write_json(
                        os_season(season, "matches.json"),
                        {"schema": SCHEMA, "season": label, "matches": ordered},
                    ),
                    "elo_ratings": write_json(
                        os_season(season, "elo_ratings.json"), elo_map_used
                    ),
                },
                "sources": _provenance_sources(season),
            }
            write_json(os_season(season, "PROVENANCE.json"), prov)
            summary["provenance_hashes"][season] = prov["files"]
        replay_matches.extend(ordered)

    merged = {
        "schema": SCHEMA,
        "seasons": list(SEASONS.values()),
        "matches": replay_matches,
    }
    total = len(replay_matches)
    total_odds = sum(
        1
        for m in replay_matches
        if None not in (m.get("odds_home"), m.get("odds_draw"), m.get("odds_away"))
    )
    summary["replay"] = {
        "n_matches": total,
        "n_matches_with_odds": total_odds,
        "odds_coverage": round(total_odds / total, 4) if total else None,
    }
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