"""Build orchestrator for the historical UCL backfill.

Runs the three source adapters, assembles the leak-free per-season
dataset under ``competitions/ucl/data/historical/``, writes provenance,
and validates counts / duplicates / team-key coverage before merging into
a single evaluation-ready replay file.

Adapter entrypoints (implemented by the source subagents):

    from competitions.ucl.historical_backfill.sources.results_openfootball import (
        fetch_openfootball_matches,
    )
    from competitions.ucl.historical_backfill.sources.odds_hf import attach_odds
    from competitions.ucl.historical_backfill.sources.elo_clubelo import (
        fetch_elo_snapshots,
    )

    results: dict[season, list[dict]] = fetch_openfootball_matches()
        # season keyed "2019_20".."2023_24"; each match dict has
        #   match_id (MDxx_yy), team_a, team_b (canonical keys),
        #   home_score, away_score, event_date (ISO-8601 UTC),
        #   round_label, home_ground (str|None, "neutral" for COVID final-8)

    odds: dict[season, dict[(date, home, away), odds]] = attach_odds()
        # odds: {"odds_home": float, "odds_draw": float, "odds_away": float,
        #        "bookmaker": str, "known_at": str}
        # keyed by ISO date (same calendar date convention as results) +
        # canonical home/away team keys.

    elo: dict[season, dict[str, float]] = fetch_elo_snapshots()
        # canonical team key -> ClubElo archive snapshot strictly before the
        # season's first match; every canonical team of that season present.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from competitions.ucl.historical_backfill.contract import (
    HISTORICAL_DIR,
    SEASONS,
    duplicate_keys,
    season_dir,
    write_json,
)

SCHEMA = 1


def _retrieve() -> tuple[dict, dict, dict]:
    from competitions.ucl.historical_backfill.sources.elo_clubelo import (
        fetch_elo_snapshots,
    )
    from competitions.ucl.historical_backfill.sources.odds_hf import attach_odds
    from competitions.ucl.historical_backfill.sources.results_openfootball import (
        fetch_openfootball_matches,
    )

    results = fetch_openfootball_matches()
    odds = attach_odds()
    elo = fetch_elo_snapshots()
    return results, odds, elo


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
    results, odds, elo = _retrieve()

    summary: dict = {"seasons": {}, "replay": {}, "provenance_hashes": {}}
    replay_matches: list[dict] = []

    for season, label in SEASONS.items():
        matches = results[season]
        ordered = sorted(matches, key=lambda m: m["event_date"])
        for m in ordered:
            odd = odds.get(season, {}).get(
                (m["event_date"][:10], m["team_a"], m["team_b"])
            )
            if odd:
                m["odds_home"] = odd["odds_home"]
                m["odds_draw"] = odd["odds_draw"]
                m["odds_away"] = odd["odds_away"]
                m["odds_bookmaker"] = odd["bookmaker"]
                m["odds_known_at"] = odd.get("known_at")
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
        "results": {
            "name": "openfootball/champions-league",
            "url": (
                "https://raw.githubusercontent.com/openfootball/champions-league/"
                f"master/{season.replace('_', '-')}/cl.txt"
            ),
            "license": "CC0-1.0 (public domain)",
        },
        "odds": {
            "name": "v-eatpizzanot/soccer-dataset odds.parquet",
            "url": (
                "https://huggingface.co/datasets/eatpizzanot/soccer-dataset/"
                "resolve/main/odds.parquet"
            ),
            "license": "CC-BY-4.0 (compiled from API-Football closing odds)",
            "note": "1X2 closing market; bookmaker preference Pinnacle first",
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
            "extras": "teams absent from 2026/27 (e.g. Red Star Belgrade, "
            "Dinamo Zagreb) get stable new keys via backfill/team_map.py",
        },
    }


if __name__ == "__main__":
    flag = "--verify-only" in sys.argv
    print(json.dumps(build(verify_only=flag), indent=2))