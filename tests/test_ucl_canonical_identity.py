"""Canonical fixture identity for the active UCL season (2026/27).

Black-box acceptance tests for the fixture-identity fix:

1. team names from one spelling family collapse onto ONE folded key
   (``Atletico Madrid`` == ``Atlético Madrid``, ``Bodo/Glimt`` ==
   ``Bodø/Glimt``, ...);
2. the ACTIVE-SEASON lookup resolves a provider's short/legacy spelling to
   the DRAW canonical (``PSV -> PSV Eindhoven``) regardless of root
   ``fixtures.json`` seeding (alias precedence — the root clobber cannot
   leak into the season identity);
3. a live PSV-vs-Shakhtar event draws with its short spelling and attaches
   to the single canonical fixture (no duplicate matchup);
4. duplicate fixture identity detection: an incoming provider event merges
   into the existing ``gen-*`` canonical row instead of creating a second
   row, even when its provider match_id matches a legacy twin row;
5. the store canonicalization is provenance-preserving: duplicate rows are
   merged, official results are re-keyed onto the canonical identity with
   their scores/provenance verbatim, NO result is ever created/promoted,
   and a re-run of the migration is a no-op (idempotent).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import arch_util as au

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


def _seed_season(tmp_path: Path, fixtures_rows: list[dict]) -> Path:
    """Minimal UCL data dir: real aliases + current.json + a 2026/27 store."""
    ucl_dir = tmp_path / "ucl"
    seat = ucl_dir / "seasons" / "2026_27"
    seat.mkdir(parents=True, exist_ok=True)
    shutil.copy2(UCL_DATA / "team_aliases.json", ucl_dir / "team_aliases.json")
    fx_doc = {
        "schema": 1,
        "season": "2026/27",
        "fixtures": fixtures_rows,
        "availability": {"fixtures_count": len(fixtures_rows), "results_count": 0, "partial": True},
        "meta": {"provider": None},
    }
    (seat / "fixtures.json").write_text(json.dumps(fx_doc, ensure_ascii=False), encoding="utf-8")
    (ucl_dir / "current.json").write_text(json.dumps({"season": "2026/27"}), encoding="utf-8")
    return ucl_dir


# ── 1. folded identity ───────────────────────────────────────────────────────

def test_fold_keys_collapse_accent_and_ascii_families():
    from football_core.fetcher import fold_pair_key, fold_team_key

    assert fold_team_key("Atlético Madrid") == fold_team_key("Atletico Madrid")
    assert fold_team_key("Bodø/Glimt") == fold_team_key("Bodo/Glimt")
    assert fold_team_key("Fenerbahçe") == fold_team_key("Fenerbahce")
    # One spelling family maps to ONE key; distinct families stay distinct.
    assert fold_team_key("Inter") != fold_team_key("Inter Milan")
    # Home/away order is preserved (A@B != B@A).
    assert fold_pair_key("A", "B") != fold_pair_key("B", "A")


# ── 2. alias precedence, scoped away from the root clobber ───────────────────

def test_active_season_lookup_resolves_short_spelling_to_draw_canonical(tmp_path):
    """PSV must resolve to ``PSV Eindhoven`` in the season lookup even when
    the legacy root fixtures.json seeds ``PSV``."""
    from competitions.ucl.src.pipeline import build_active_season_lookup
    from football_core.fetcher import _build_alias_lookup, normalize_team

    ucl_dir = _seed_season(tmp_path, [
        {"match_id": "gen-psv1", "team_a": "PSV Eindhoven",
         "team_b": "Shakhtar Donetsk", "event_date": None,
         "stage": "LEAGUE_STAGE", "status": "scheduled"},
        {"match_id": "gen-atm1", "team_a": "Atlético Madrid",
         "team_b": "Bodø/Glimt", "event_date": None,
         "stage": "LEAGUE_STAGE", "status": "scheduled"},
    ])
    aliases = json.loads((ucl_dir / "team_aliases.json").read_text(encoding="utf-8"))

    # Legacy root seeding clobbers 'psv' -> 'PSV' (the old defect).
    root_fx = {"schedule": {"teams": [{"name": "PSV"}]}}
    (ucl_dir / "fixtures.json").write_text(json.dumps(root_fx), encoding="utf-8")
    legacy = _build_alias_lookup(aliases, [])
    for team in root_fx["schedule"]["teams"]:
        legacy[team["name"].strip().lower()] = team["name"]
    assert normalize_team("PSV", legacy) == "PSV"

    # Season lookup is scoped: root clobber excluded, alias last-writer wins.
    season_lookup = build_active_season_lookup(ucl_dir, aliases)
    assert normalize_team("PSV", season_lookup) == "PSV Eindhoven"
    assert normalize_team("Inter", season_lookup) == "Inter Milan"
    assert normalize_team("Bayern", season_lookup) == "Bayern Munich"
    assert normalize_team("Atletico Madrid", season_lookup) == "Atlético Madrid"
    assert normalize_team("Bodo/Glimt", season_lookup) == "Bodø/Glimt"
    assert normalize_team("Shakhtar Donetsk", season_lookup) == "Shakhtar Donetsk"


# ── 3. live event attaches to the single canonical fixture (the PSV case) ─────

def test_psv_live_event_merges_into_drawn_fixture_and_attaches_result(tmp_path):
    from competitions.ucl.src.pipeline import fetch_live_data

    ucl_dir = _seed_season(tmp_path, [{
        "match_id": "gen-psv2",
        "team_a": "PSV Eindhoven",
        "team_b": "Shakhtar Donetsk",
        "event_date": None,
        "stage": "LEAGUE_STAGE",
        "status": "scheduled",
    }])

    scheduled = [{
        "status": "scheduled",
        "home_team": "PSV",
        "away_team": "Shakhtar Donetsk",
        "season": "2026/27",
        "match_id": "575390",
        "event_date": "2026-09-16T19:00:00Z",
        "stage": "LEAGUE_STAGE",
    }]
    fetch_live_data(ucl_dir, "", "", provider=au.StubProvider(scheduled, competition="CL"))
    fx = json.loads(
        (ucl_dir / "seasons" / "2026_27" / "fixtures.json").read_text(encoding="utf-8"))
    assert len(fx["fixtures"]) == 1, "short-spelling scheduled event must not add a duplicate row"
    assert fx["fixtures"][0]["match_id"] == "gen-psv2"
    assert fx["fixtures"][0]["team_a"] == "PSV Eindhoven"
    assert fx["fixtures"][0]["event_date"] == "2026-09-16T19:00:00Z"

    finished = [{
        "status": "finished",
        "home_team": "PSV",
        "away_team": "Shakhtar Donetsk",
        "home_score": 2,
        "away_score": 1,
        "season": "2026/27",
        "match_id": "575390",
        "event_date": "2026-09-16T19:00:00Z",
        "stage": "LEAGUE_STAGE",
    }]
    summary = fetch_live_data(ucl_dir, "", "", provider=au.StubProvider(finished, competition="CL"))
    report = summary["report"]
    assert report.get("finished", {}).get("ingested", 0) == 1
    res = json.loads(
        (ucl_dir / "seasons" / "2026_27" / "results.json").read_text(encoding="utf-8"))
    m = res["matches"][0]
    assert m["match_id"] == "gen-psv2"
    assert m["team_a"] == "PSV Eindhoven"
    assert m["team_b"] == "Shakhtar Donetsk"
    assert (m["home_score"], m["away_score"]) == (2, 1)


# ── 4. duplicate fixture identity detection (folded canonical pairing) ────────

def test_duplicate_fixture_identity_merges_into_canonical_gen_row(tmp_path):
    from competitions.ucl.src.ingest import _upsert_season_fixtures
    from competitions.ucl.src.seasons import read_season_fixtures

    # A: legacy provider id on the CANONICAL pair — no new row, gen id kept.
    ucl_dir = _seed_season(tmp_path, [
        {"match_id": "gen-rm", "team_a": "Real Madrid", "team_b": "Inter Milan",
         "event_date": None, "stage": "LEAGUE_STAGE", "status": "scheduled"},
    ])
    added, updated, total = _upsert_season_fixtures(ucl_dir, "2026/27", [{
        "home_team": "Real Madrid",
        "away_team": "Inter Milan",
        "match_id": "575325",
        "event_date": "2026-09-16T19:00:00Z",
        "stage": "LEAGUE_STAGE",
        "status": "timed",
    }], "test")

    assert (added, total) == (0, 1), \
        "an event for an already-stored matchup must merge, never add a row"
    doc = read_season_fixtures(ucl_dir, "2026/27")
    rows = doc["fixtures"]
    assert len(rows) == 1 and rows[0]["match_id"] == "gen-rm"
    assert rows[0]["team_a"] == "Real Madrid" and rows[0]["team_b"] == "Inter Milan"
    assert rows[0]["event_date"] == "2026-09-16T19:00:00Z"
    assert rows[0]["status"] == "timed"
    assert updated == 1

    # B: accent folding — ASCII provider spelling folds onto the drawn row.
    ucl_dir2 = _seed_season(tmp_path, [
        {"match_id": "gen-atm", "team_a": "Atlético Madrid", "team_b": "Bodø/Glimt",
         "event_date": None, "stage": "LEAGUE_STAGE", "status": "scheduled"},
    ])
    added2, updated2, total2 = _upsert_season_fixtures(ucl_dir2, "2026/27", [
        {"home_team": "Atletico Madrid", "away_team": "Bodo/Glimt",
         "event_date": "2026-10-03T19:00:00Z", "stage": "LEAGUE_STAGE",
         "status": "scheduled"},
        {"home_team": "Atletico Madrid", "away_team": "Bodo/Glimt",
         "event_date": "2026-10-03T19:00:00Z", "stage": "LEAGUE_STAGE",
         "status": "scheduled"},
    ], "test")
    assert added2 == 0, "ASCII spelling must merge onto the accented canonical row"
    assert total2 == 1
    doc2 = read_season_fixtures(ucl_dir2, "2026/27")
    assert doc2["fixtures"][0]["match_id"] == "gen-atm"
    assert doc2["fixtures"][0]["team_a"] == "Atlético Madrid"
    assert doc2["fixtures"][0]["event_date"] == "2026-10-03T19:00:00Z"

    # C: a legacy short-spelling twin row already in the store — the incoming
    # canonical event must still attach to the gen-* row, never to the twin.
    ucl_dir3 = _seed_season(tmp_path, [
        {"match_id": "gen-rm", "team_a": "Real Madrid", "team_b": "Inter Milan",
         "event_date": None, "stage": "LEAGUE_STAGE", "status": "scheduled"},
        {"match_id": "575325", "team_a": "Real Madrid", "team_b": "Inter",
         "event_date": None, "stage": "LEAGUE_STAGE", "status": "scheduled"},
    ])
    added3, _u, total3 = _upsert_season_fixtures(ucl_dir3, "2026/27", [{
        "home_team": "Real Madrid",
        "away_team": "Inter Milan",
        "match_id": "575325",
        "event_date": "2026-09-16T19:00:00Z",
        "stage": "LEAGUE_STAGE",
        "status": "timed",
    }], "test")
    assert added3 == 0
    doc3 = read_season_fixtures(ucl_dir3, "2026/27")
    by_id3 = {r["match_id"]: r for r in doc3["fixtures"]}
    assert by_id3["gen-rm"]["event_date"] == "2026-09-16T19:00:00Z", \
        "canonical gen-* identity wins over a bare provider match_id hit"
    assert by_id3["575325"]["event_date"] is None, "legacy twin row is left untouched"


# ── 5. store canonicalization: provenance preserved, official results re-keyed ─

def test_store_canonicalization_preserves_and_rekeys_results(tmp_path):
    from competitions.ucl.src.seasons import (
        empty_results_document,
        read_season_fixtures,
        read_season_results,
    )
    from competitions.ucl.src.store_canonical import canonicalize_season_store
    from football_core.fetcher import fold_pair_key

    ucl_dir = _seed_season(tmp_path, [
        {"match_id": "gen-aaa", "team_a": "Real Madrid", "team_b": "Inter Milan",
         "event_date": None, "stage": "LEAGUE_STAGE", "status": "scheduled"},
        {"match_id": "575325", "team_a": "Real Madrid", "team_b": "Inter",
         "event_date": "2026-09-16T19:00:00Z", "stage": "LEAGUE_STAGE", "status": "finished"},
        {"match_id": "gen-bbb", "team_a": "Borussia Dortmund", "team_b": "Villarreal",
         "event_date": None, "stage": "LEAGUE_STAGE", "status": "scheduled"},
    ])
    res_doc = empty_results_document("2026/27")
    res_doc["matches"] = [
        {"match_id": "575325", "team_a": "Real Madrid", "team_b": "Inter",
         "home_score": 2, "away_score": 1, "winner": "Real Madrid"},
        {"match_id": "gen-bbb", "team_a": "Borussia Dortmund", "team_b": "Villarreal",
         "home_score": 3, "away_score": 2, "winner": "Borussia Dortmund"},
    ]
    (ucl_dir / "seasons" / "2026_27" / "results.json").write_text(
        json.dumps(res_doc, ensure_ascii=False), encoding="utf-8")

    dry = canonicalize_season_store(ucl_dir, "2026/27", dry_run=True)
    assert dry["duplicate_pairs"] == 1
    assert dry["rows_removed"] == 1
    assert dry["results_rekeyed"] == 1
    assert dry["total_results_before"] == dry["total_results_after"] == 2, \
        "canonicalization must never create or drop official results"

    report = canonicalize_season_store(ucl_dir, "2026/27", dry_run=False)
    assert report["results_rekeyed"] == 1

    fx = read_season_fixtures(ucl_dir, "2026/27")
    rows = fx["fixtures"]
    assert len(rows) == 2
    folded = {fold_pair_key(r["team_a"], r["team_b"]) for r in rows}
    assert len(folded) == len(rows), "no two rows may share one canonical identity"

    rm = next(r for r in rows if r["match_id"] == "gen-aaa")
    assert rm["event_date"] == "2026-09-16T19:00:00Z"
    assert rm["status"] == "finished"

    res = read_season_results(ucl_dir, "2026/27")
    matches = {m["match_id"]: m for m in res["matches"]}
    rekeyed = matches["gen-aaa"]
    assert rekeyed["team_a"] == "Real Madrid" and rekeyed["team_b"] == "Inter Milan"
    assert (rekeyed["home_score"], rekeyed["away_score"]) == (2, 1)
    assert rekeyed["winner"] == "Real Madrid", "official-result provenance is preserved"
    kept = matches["gen-bbb"]
    assert (kept["home_score"], kept["away_score"]) == (3, 2) and kept["winner"] == "Borussia Dortmund"

    rerun = canonicalize_season_store(ucl_dir, "2026/27", dry_run=False)
    assert rerun["duplicate_pairs"] == 0
    assert rerun["rows_removed"] == 0
    assert rerun["results_rekeyed"] == 0
    assert rerun["changed_any"] is False, "migration is idempotent"