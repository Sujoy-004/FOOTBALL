"""2026/27 UCL league-phase draw builder (snapshot -> season store).

Turns the authoritative draw snapshot
(``data/draws/2026_27_league_draw.json``) into a full season store under
``data/seasons/2026_27/`` and can make it the active data view.

Non-authoritative grouping
--------------------------
The snapshot records the 144 league-phase pairings (who hosts whom) exactly
as drawn. Real matchday assignments and kick-off dates are announced later
(``fixture_list_status.official_matchdays_known = false``), so this builder
derives a deterministic 8x18 matchday grouping that is explicitly
NON-authoritative:

- every fixture row carries ``official_matchday: null``,
  ``simulation_matchday`` (the derived slot) and
  ``provenance = {"fixture": "authoritative", "schedule": "derived"}``;
- the schedule document carries
  ``{"source": "derived", "authoritative": false, "status": "temporary",
    "grouping_method": "deterministic_v1", "official_matchdays_known": false}``.

Requested fixtures are fields for the non-authoritative schedule; the
schedule itself is grouped deterministically (sort by ``match_id``, chunk
8x18) so a re-build is byte-identical and the fixture list stays in channel
order with the schedule.

Store shape
----------
``data/seasons/2026_27/fixtures.json`` has BOTH the flat ``fixtures`` list
(resolve_active_view, ``_make_fixture_lookup_from_doc``, lifecycle counts)
AND the ``schedule`` key (RepoFixtureProvider, validation,
``run_compute_all``). ``data/seasons/2026_27/results.json`` is created as an
empty ledger (nothing has been played).

Default activation
------------------
Shipping the store (``build``) makes 2026/27 the default active season by
initializing ``data/current.json`` when no pointer exists. The pointer is
never overwritten on re-runs; 2025/26 stays selectable as a completed
historical season (``deactivate`` / ``set_current_season``).

Official enrichment
-------------------
Fixture ids are date-independent (``derive_fixture_id`` hashes only the
home/away relationship), and the ingest router updates an existing row by
its id or exact (home, away) pairing instead of appending — so ingesting the
official dated fixture list enriches the provisional rows in place (id,
provenance and metadata preserved) with no duplicates.

CLI
---
``python -m competitions.ucl.src.season_draw build --data-dir <dir>``
``python -m competitions.ucl.src.season_draw activate [--data-dir <dir>]``
``python -m competitions.ucl.src.season_draw deactivate [--data-dir <dir>]``
``python -m competitions.ucl.src.season_draw validate [--data-dir <dir>]``

All operations are idempotent: re-running produces byte-identical stores.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from competitions.ucl.src.ingest import ingest_ucl_events_multi_season
from competitions.ucl.src.seasons import (
    LOCAL_HISTORICAL_SEASON,
    derive_fixture_id,
    get_current_season,
    normalize_season_token,
    read_season_fixtures,
    set_current_season,
    write_season_fixtures,
)
from competitions.ucl.src.validation import validate_ucl_fixtures

DRAWN_SEASON = "2026/27"
SNAPSHOT_NAME = "2026_27_league_draw.json"
PROVIDER_LABEL = "ucl.draw.2026_27"
SCHEDULE_GROUPING_METHOD = "deterministic_v1"

LEAGUE_STAGE = "LEAGUE_STAGE"
SCHEDULED = "scheduled"


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def snapshot_path(data_dir: str | Path) -> Path:
    """Path of the authoritative draw snapshot under *data_dir*."""
    return Path(data_dir) / "draws" / SNAPSHOT_NAME


def load_snapshot(data_dir: str | Path) -> dict:
    """Load and validate the authoritative draw snapshot; raises on absence."""
    path = snapshot_path(data_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"draw snapshot missing: {path} — expected at {SNAPSHOT_NAME}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("draw snapshot must be a JSON object")
    return payload


def _team_meta(snapshot: dict) -> list[dict]:
    """36 teams with the exact ``{name, pot, clubelo_name, coefficient}``
    fields the strict ``FixtureSchedule`` contract demands."""
    teams = snapshot.get("teams", [])
    out: list[dict] = []
    for t in teams:
        if not isinstance(t, dict):
            raise ValueError("snapshot teams must be objects")
        out.append({
            "name": t["name"],
            "pot": int(t["pot"]),
            "clubelo_name": t["clubelo_name"],
            "coefficient": float(t["coefficient"]),
        })
    if len(out) != 36:
        raise ValueError(f"expected 36 teams in snapshot, got {len(out)}")
    return out


def _flat_matches(snapshot: dict) -> list[dict]:
    """The 144 league-phase fixtures with their authority.

    The snapshot lists each team's 8 opponents under a top-level
    ``opponents`` key, mirrored across BOTH clubs (288 entries), so it must
    be de-duplicated per pairing. ``opponent.home=True`` means the listed
    team HOSTS that opponent.
    """
    by_team = {t["name"]: t for t in snapshot.get("teams", [])}
    pair_entries: dict[tuple[str, str], tuple[dict, dict]] = {}
    order: list[tuple[str, str]] = []
    for team_entry in snapshot.get("opponents", []):
        if not isinstance(team_entry, dict):
            raise ValueError("snapshot opponents must be objects")
        team_name = team_entry["team"]
        team = by_team.get(team_name)
        if team is None:
            raise ValueError(f"snapshot opponent entry for unknown team: {team_name}")
        for opp in team_entry.get("opponents", []):
            opp_name = opp["name"]
            home, away = (team_name, opp_name) if opp.get("home", True) \
                else (opp_name, team_name)
            pair = tuple(sorted((home, away)))
            home_team = by_team.get(home)
            away_team = by_team.get(away)
            if home_team is None or away_team is None:
                raise ValueError(
                    f"snapshot pairing references unknown team: {home} v {away}")
            if int(home_team["pot"]) != int(team["pot"]) and \
                    int(away_team["pot"]) != int(team["pot"]):
                raise ValueError(
                    f"snapshot pot field disagrees with teams list for {team_name}")
            entry = {
                "match_id": derive_fixture_id(home, away, None),
                "team_a": home,
                "team_b": away,
                "home_pot": int(home_team["pot"]),
                "away_pot": int(away_team["pot"]),
            }
            if pair not in pair_entries:
                pair_entries[pair] = (entry, home, away)
                order.append(pair)
            else:
                _, first_home, first_away = pair_entries[pair]
                if (first_home, first_away) == (home, away):
                    # Mirrored entry describing the same (home, away) pairing
                    # — keep the first, nothing to re-check.
                    continue
                raise ValueError(
                    f"snapshot contradicts home/away for {pair}: "
                    f"{first_home} v {first_away} vs {home} v {away}")
    matches = [pair_entries[p][0] for p in order]
    if len(matches) != 144:
        raise ValueError(f"expected 144 fixtures in snapshot, got {len(matches)}")
    return matches


def _matches_to_events(matches: list[dict]) -> list[dict]:
    """Router events for ``ingest_ucl_events_multi_season``."""
    return [{
        "season": DRAWN_SEASON,
        "home_team": m["team_a"],
        "away_team": m["team_b"],
        "event_date": None,
        "stage": LEAGUE_STAGE,
        "status": SCHEDULED,
        "match_id": m["match_id"],
    } for m in matches]


def build_schedule(
    matches: list[dict],
    team_meta: list[dict],
) -> dict:
    """Deterministic 8x18 schedule document (non-authoritative grouping).

    Rows inside ``matchdays`` carry EXACTLY
    ``{match_id, team_a, team_b, home_pot, away_pot, event_date}`` to satisfy
    the strict ``Match(**m)`` contract.
    """
    ordered = sorted(matches, key=lambda m: m["match_id"])
    if len(ordered) % 18 != 0:
        raise ValueError("fixture count must be divisible by 18")
    chunked = [ordered[i:i + 18] for i in range(0, len(ordered), 18)]
    matchdays = [[{
        "match_id": m["match_id"],
        "team_a": m["team_a"],
        "team_b": m["team_b"],
        "home_pot": m["home_pot"],
        "away_pot": m["away_pot"],
        "event_date": None,
    } for m in md] for md in chunked]
    if len(matchdays) != 8:
        raise ValueError(f"expected 8 matchdays, got {len(matchdays)}")
    return {
        "source": "derived",
        "authoritative": False,
        "status": "temporary",
        "grouping_method": SCHEDULE_GROUPING_METHOD,
        "official_matchdays_known": False,
        "teams": team_meta,
        "matchdays": matchdays,
    }


def _assign_matchdays(fixtures: list[dict]) -> dict[str, int]:
    ordered = sorted(fixtures, key=lambda f: f["match_id"])
    return {
        f["match_id"]: (i // 18) + 1
        for i, f in enumerate(ordered)
    }


def ensure_draw_season(
    data_dir: str | Path | None = None,
    *,
    validate: bool = True,
) -> dict:
    """Build (or refresh) the 2026/27 season store from the draw snapshot.

    Idempotent and deterministic: re-running produces byte-identical stores.

    Making the store the default active season: shipping the 2026/27 store
    (this build) initializes ``data/current.json`` to point at it when no
    pointer exists yet. The existing pointer machinery then drives selection
    — 2025/26 stays fully selectable as a completed historical season, and
    the pointer is never rewritten on re-runs (idempotent).

    Returns a summary dict with the season, paths, counts, and pointer.
    """
    data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        raise ValueError(f"data dir does not exist: {data_dir}")

    snapshot = load_snapshot(data_dir)
    team_meta = _team_meta(snapshot)
    matches = _flat_matches(snapshot)

    ingest_ucl_events_multi_season(
        _matches_to_events(matches),
        data_dir,
        provider_name=PROVIDER_LABEL,
    )

    fixtures_path = data_dir / "seasons" / "2026_27" / "fixtures.json"
    doc = read_season_fixtures(data_dir, DRAWN_SEASON)
    if doc is None or not isinstance(doc, dict):
        raise ValueError(f"ingest did not produce {fixtures_path}")

    # Canonical identity re-key: every drawn row must carry the date-
    # independent derived id, regardless of what a previous scheme stored.
    pair_to_id = {
        (m["team_a"], m["team_b"]): m["match_id"]
        for m in matches
    }
    for f in doc.get("fixtures", []):
        if not isinstance(f, dict):
            continue
        rid = pair_to_id.get((f.get("team_a", ""), f.get("team_b", "")))
        if rid and rid != f.get("match_id"):
            f["match_id"] = rid

    # Deterministic stable ordering: sort flat rows by match_id so the list
    # is in channel order with the (sorted, chunked) schedule.
    doc["fixtures"] = sorted(
        (f for f in doc.get("fixtures", []) if isinstance(f, dict)),
        key=lambda f: f.get("match_id", ""),
    )
    assignment = _assign_matchdays(doc["fixtures"])
    for f in doc["fixtures"]:
        # setdefault: a rebuild preserves any official_matchday already
        # enriched onto a row by a previous official schedule ingestion.
        f.setdefault("official_matchday", None)
        f["simulation_matchday"] = assignment[f["match_id"]]
        f["provenance"] = {"fixture": "authoritative", "schedule": "derived"}

    doc["schedule"] = build_schedule(matches, team_meta)
    doc["_derived"] = {
        "schedule": "derived",
        "authoritative_schedule": False,
        "grouping_method": SCHEDULE_GROUPING_METHOD,
    }

    if validate:
        validate_ucl_fixtures(doc)
        if len(doc["fixtures"]) != 144:
            raise ValueError(f"expected 144 flat fixtures, got {len(doc['fixtures'])}")

    write_season_fixtures(data_dir, DRAWN_SEASON, doc)

    # Exchange 5 default-activation: ship the store as the active season
    # unless a pointer already exists (never overwrites a user's selection).
    current = get_current_season(data_dir)
    if current is None:
        current = set_current_season(
            data_dir,
            DRAWN_SEASON,
            basis="draw",
            provider=PROVIDER_LABEL,
        )

    results_path = data_dir / "seasons" / "2026_27" / "results.json"
    return {
        "season": DRAWN_SEASON,
        "fixtures_path": str(fixtures_path),
        "results_path": str(results_path),
        "teams": len(team_meta),
        "fixtures": len(doc["fixtures"]),
        "matchdays": len(doc["schedule"]["matchdays"]),
        "matches_per_matchday": 18,
        "grouping_method": SCHEDULE_GROUPING_METHOD,
        "authoritative_schedule": False,
        "current": current,
    }


def activate_draw_season(
    data_dir: str | Path | None = None,
    *,
    validate: bool = True,
    return_build: bool = False,
) -> dict:
    """Build the 2026/27 store and make it the active current.json view."""
    data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
    build = ensure_draw_season(data_dir, validate=validate)
    pointer = set_current_season(
        data_dir,
        DRAWN_SEASON,
        basis="draw",
        provider=PROVIDER_LABEL,
    )
    out = {
        "current": pointer,
        "active": True,
    }
    if return_build:
        out.update(build)
    return out


def deactivate_draw_season(
    data_dir: str | Path | None = None,
) -> dict:
    """Point current.json back at the shipped historical 2025/26 season."""
    data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
    pointer = set_current_season(
        data_dir,
        LOCAL_HISTORICAL_SEASON,
        basis="pointer_local",
        provider=None,
    )
    return {"current": pointer, "active": False}


def validate_draw_season(
    data_dir: str | Path | None = None,
) -> dict:
    """Validate the built season store against the authoritative snapshot."""
    data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
    snapshot = load_snapshot(data_dir)
    doc = read_season_fixtures(data_dir, DRAWN_SEASON)
    if doc is None:
        raise FileNotFoundError("2026/27 season store not built yet")
    validate_ucl_fixtures(doc)
    matches = _flat_matches(snapshot)
    schedule_ids = {
        m["match_id"]
        for md in doc["schedule"]["matchdays"]
        for m in md
    }
    flat_ids = {f["match_id"] for f in doc["fixtures"]}
    snapshot_ids = {m["match_id"] for m in matches}
    mismatches = snapshot_ids - schedule_ids
    if mismatches:
        raise ValueError(f"schedule missing snapshot fixtures: {sorted(mismatches)[:5]}")
    if schedule_ids != flat_ids:
        raise ValueError("flat fixtures and schedule disagree")
    return {
        "ok": True,
        "season": DRAWN_SEASON,
        "teams": len(doc["schedule"]["teams"]),
        "fixtures": len(flat_ids),
        "matchdays": len(doc["schedule"]["matchdays"]),
        "official_matchdays_known": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build/activate the 2026/27 UCL league-phase draw")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "activate", "deactivate", "validate"):
        sub_parser = sub.add_parser(name, help=f"{name} the 2026/27 draw season")
        sub_parser.add_argument("--data-dir", default=None,
                                help="UCL data dir (defaults to the shipped data/)")
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            summary = ensure_draw_season(args.data_dir)
        elif args.command == "activate":
            summary = activate_draw_season(args.data_dir, return_build=True)
        elif args.command == "deactivate":
            summary = deactivate_draw_season(args.data_dir)
        else:
            summary = validate_draw_season(args.data_dir)
    except Exception as exc:  # noqa: BLE001 - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())