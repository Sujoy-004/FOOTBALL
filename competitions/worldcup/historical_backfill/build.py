"""Build orchestrator for the historical World Cup backfill.

Runs the two source adapters (openfootball world-cup results, national-team
Elo snapshots), assembles the leak-free per-season dataset under
``competitions/worldcup/data/historical/``, writes provenance, and validates
counts / duplicates / team-key coverage before merging into a single
evaluation-ready replay file.

The per-season dataset layout (``matches.json`` + a FROZEN per-season
``elo_ratings.json``) is what keeps the evaluation leak-free: nothing
recomputes a rating with an in-season outcome, so no future data can reach a
prediction. The generic part of that contract (validation, provenance
writing, replay summary) lives once in ``football_core.historical_backfill``;
this module is the World Cup configuration of it.

Adapter entrypoints (implemented by the source submodules):

    from competitions.worldcup.historical_backfill.sources.results_intl import fetch
    from competitions.worldcup.historical_backfill.sources.elo_snapshots import (
        fetch_elo_snapshots,
    )

    matches: list[dict] | None = fetch(season)
        # season keyed "2002".."2026"; each match dict has
        #   team_a, team_b (canonical keys),
        #   home_score, away_score, event_date (ISO-8601 UTC),
        #   round ("group" | "round of 32" | "round of 16" | "quarter-final" |
        #          "semi-final" | "final" | "third place"),
        #   winner (advancing side, knockout only), pk_winner (shootout winner),
        #   stage ("group" | "knockout")
        # Returns None when the tournament is absent from the source.

    elo: dict[str, dict[str, float]] = fetch_elo_snapshots()
        # season key -> national-team Elo snapshot. Empty per season: no
        # date-indexed historical feed exists (A4); the gap is recorded in
        # PROVENANCE.json, never fabricated.
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

from competitions.worldcup.historical_backfill.contract import (
    HISTORICAL_DIR,
    REPLAY_NAME,
    SCHEMA,
    SEASONS,
    TOURNEY_DIRS,
    match_id,
    season_dir,
)


def _retrieve() -> tuple[dict, dict, dict]:
    """Run both adapters for the contracted window.

    Returns ``(results, elo, exclusions)``. ``results`` holds only the
    tournaments whose openfootball source exists and parses; ``exclusions``
    names every other contracted tournament with the reason. The Elo
    snapshot is computed for the whole window (empty per season on the
    verified no-historical-feed path).
    """
    from competitions.worldcup.historical_backfill.sources.elo_snapshots import (
        fetch_elo_snapshots,
    )
    from competitions.worldcup.historical_backfill.sources.results_intl import (
        TournamentFormatError,
        fetch,
    )

    results: dict[str, list[dict]] = {}
    exclusions: dict[str, str] = {}
    for season in SEASONS:
        try:
            matches = fetch(season)
        except TournamentFormatError as exc:
            exclusions[season] = str(exc)
            continue
        if matches is None:
            exclusions[season] = (
                "source-absent: openfootball/world-cup publishes no cup.txt "
                f"for {season}; no keyless results source covers this tournament"
            )
            continue
        results[season] = matches
    elo = fetch_elo_snapshots()
    return results, elo, exclusions


def build(verify_only: bool = False) -> dict:
    results, elo, exclusions = _retrieve()

    accepted = [s for s in SEASONS if s in results]
    if not accepted:
        raise ValueError(
            "World Cup historical corpus could not be assembled: every "
            f"contracted tournament is absent ({sorted(exclusions)}). The "
            "World Cup block is honestly deferred/provider-empty — the "
            "corpus is never padded (D-04)."
        )

    summary: dict = {
        "seasons": {},
        "replay": {},
        "provenance_hashes": {},
        "accepted_seasons": accepted,
        "excluded_seasons": dict(exclusions),
    }
    replay_matches: list[dict] = []

    for season, label in SEASONS.items():
        if season not in results:
            # Excluded-and-reported: the source is absent or unparsable.
            # Never fabricated to reach a round window.
            continue
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
        "seasons": [SEASONS[s] for s in accepted],
        "matches": replay_matches,
    }
    summary["replay"] = summarize_replay(replay_matches)
    if not verify_only:
        write_json(os.path.join(HISTORICAL_DIR, REPLAY_NAME), merged)
    return summary


def os_season(season: str, name: str) -> str:
    return os.path.join(season_dir(season), name)


def _provenance_sources(season: str) -> dict:
    slug = TOURNEY_DIRS[season]
    return {
        "results": {
            "name": "openfootball/world-cup cup.txt + cup_finals.txt",
            "url": (
                f"https://raw.githubusercontent.com/openfootball/world-cup/"
                f"master/{slug}/cup.txt (+ cup_finals.txt)"
            ),
            "license": "CC0-1.0 (public domain)",
            "note": (
                "per-tournament group-stage and knockout files; real national "
                "teams, real scores, real dates; knockout winners resolved "
                "from extra-time/penalty annotations (never a fabricated "
                "draw); kickoff times converted to UTC where the source "
                "publishes a UTC offset (2014+), otherwise a documented "
                "21:00:00Z default is used (day-level chronology unaffected)"
            ),
        },
        "elo": {
            "name": "eloratings.net (national-team Elo)",
            "url": "https://www.eloratings.net/World.tsv",
            "license": "eloratings.net",
            "deviation": (
                "no date-indexed historical feed exists (verified "
                "2026-10-15: date-indexed URLs return HTTP 404); every "
                "tournament snapshot is empty and the gap is recorded — "
                "refined_elo is reported as insufficient_data:no_elo_ratings "
                "and never rendered as a synthetic rating (A4/D-03)"
            ),
        },
        "team_keys": {
            "canonical": "data/team_aliases.json keys (long-form 2026 "
            "production keys) + stable extras for historical national "
            "teams absent from the 2026 aliases (Angola, Cameroon, China, "
            "Costa Rica, Denmark, Ireland, Italy, Nigeria, Poland, Russia, "
            "Serbia and Montenegro, Slovenia, Togo, Trinidad and Tobago, "
            "Ukraine); openfootball-only spellings curated "
            "(Bosnia-Herzegovina -> Bosnia and Herzegovina)",
        },
    }


if __name__ == "__main__":
    flag = "--verify-only" in sys.argv
    print(json.dumps(build(verify_only=flag), indent=2))
