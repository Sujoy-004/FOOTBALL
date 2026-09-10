"""Regression tests for the UCL season presentation contract."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


def _season_matchday_fixture_ids(season_dir, matchday=1):
    """Resolve the CURRENT authoritative fixture ids for a matchday.

    Delegates to pipeline.build_matchday_map so the precedence logic
    (official_matchday first, then simulation_matchday) is the production
    truth, not a test-side re-implementation. Resolved at runtime so
    regenerated `gen-*` fixture ids can never break the contract.
    """
    from competitions.ucl.src.pipeline import build_matchday_map

    return {
        match_id
        for match_id, md in build_matchday_map(season_dir).items()
        if md == matchday
    }


@pytest.fixture
def active_2026_runtime(tmp_path, monkeypatch):
    import web.competitions as competitions
    import web.startup as startup
    import web.ucl_app as app
    import competitions.ucl.src.orchestrator as orchestrator
    from competitions.ucl.src.seasons import set_current_season

    data_dir = tmp_path / "ucl_data"
    shutil.copytree(UCL_DATA, data_dir)
    set_current_season(data_dir, "2026/27", basis="draw", provider="ucl.draw.2026_27")

    monkeypatch.setattr(app, "DATA_DIR", data_dir)
    monkeypatch.setattr(orchestrator, "_resolve_elo_ratings", lambda _teams: {})
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    competitions.reset_lazy_gates()
    app._refresh_report = {}
    app._refresh_reports = {}
    app._refresh_reports_seeded = False
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield app.ucl_app, data_dir
    startup._last_decision = None
    competitions.reset_lazy_gates()


def test_2026_27_standings_and_matchdays_are_season_scoped(active_2026_runtime):
    app, data_dir = active_2026_runtime

    with TestClient(app) as client:
        overview = client.get("/api/data").json()
        standings_payload = client.get("/api/standings").json()
        bracket = client.get("/api/bracket").json()
        seasons = client.get("/api/seasons").json()
        odds = client.get("/api/odds").json()
        signals = client.get("/api/signals").json()

    assert overview["season"] == "2026/27"
    assert overview["n_teams"] == 36
    assert overview["snapshot_date"] == "2026/27 Season — Real Results"

    standings = standings_payload["standings"]
    assert standings_payload["season"] == "2026/27"
    assert len(standings) == 36
    assert len(standings[:8]) == 8

    matchdays = bracket["stages"]["league"]["matchdays"]
    md1_canonical = _season_matchday_fixture_ids(data_dir / "seasons" / "2026_27")
    assert md1_canonical
    assert set(matchdays) == {"MD01"}
    assert all(not key.startswith("gen-") for key in matchdays)
    md1 = matchdays["MD01"]
    assert md1
    assert {m["match_id"] for m in md1} <= md1_canonical
    assert all(m["match_id"].startswith("gen-") for m in md1)
    assert all(m["status"] == "played" for m in md1)
    assert bracket["lifecycle"]["season"] == "2026/27"

    assert seasons["active_season"] == "2026/27"
    assert odds["season"] == "2026/27"
    assert len(odds["odds"]) == 36
    assert signals["season"] == "2026/27"


def test_season_switch_recomputes_all_payloads_without_leakage(active_2026_runtime):
    app, data_dir = active_2026_runtime

    with TestClient(app) as client:
        switched = client.post("/api/season", json={"season": "2025/26"})
        assert switched.status_code == 200
        assert switched.json()["current"]["provider"] is None

        historical = client.get("/api/data").json()
        historical_standings = client.get("/api/standings").json()
        historical_bracket = client.get("/api/bracket").json()
        assert historical["season"] == "2025/26"
        assert historical["snapshot_date"] == "2025/26 Season — Real Results"
        assert historical_standings["season"] == "2025/26"
        assert set(historical_bracket["stages"]["league"]["matchdays"]) == {
            f"MD{i:02d}" for i in range(1, 9)
        }

        switched_back = client.post("/api/season", json={"season": "2026/27"})
        assert switched_back.status_code == 200
        current = client.get("/api/data").json()
        current_standings = client.get("/api/standings").json()
        current_bracket = client.get("/api/bracket").json()
        assert current["season"] == "2026/27"
        assert current["snapshot_date"] == "2026/27 Season — Real Results"
        assert current_standings["season"] == "2026/27"
        assert len(current_standings["standings"]) == 36
        current_matchdays = current_bracket["stages"]["league"]["matchdays"]
        assert set(current_matchdays) == {"MD01"}
        md1 = current_matchdays["MD01"]
        assert md1
        assert {m["match_id"] for m in md1} <= _season_matchday_fixture_ids(
            data_dir / "seasons" / "2026_27"
        )


def test_authoritative_matchday_metadata_and_legacy_fallback():
    from competitions.ucl.src.pipeline import build_league_matchdays, build_matchday_map

    season_dir = UCL_DATA / "seasons" / "2026_27"
    matchday_map = build_matchday_map(season_dir)
    results = json.loads((season_dir / "results.json").read_text(encoding="utf-8"))["matches"]
    grouped = build_league_matchdays(results, matchday_map)
    md1_canonical = _season_matchday_fixture_ids(season_dir)
    assert md1_canonical
    assert set(grouped) == {"MD01"}
    assert all(not key.startswith("gen-") for key in grouped)
    md1 = grouped["MD01"]
    assert md1
    assert {m["match_id"] for m in md1} <= md1_canonical
    assert all(m["match_id"].startswith("gen-") for m in md1)
    assert all(m["status"] == "played" for m in md1)

    historical_results = json.loads(
        (UCL_DATA / "results.json").read_text(encoding="utf-8")
    )["matches"]
    historical_grouped = build_league_matchdays(historical_results, {})
    assert list(historical_grouped) == [f"MD{i:02d}" for i in range(1, 9)]


def test_frontend_keeps_top8_preview_separate_from_full_standings():
    source = (ROOT / "web" / "static" / "ucl.js").read_text(encoding="utf-8")
    assert "standings.slice(0, 8)" in source
    assert "st.forEach(function(r)" in source
    assert 'md.replace(/^MD/, "Matchday ")' in source


def test_gen_fixture_rekey_keeps_matchday_contract(tmp_path):
    """Proof of immunity: rekey EVERY gen-* fixture id in a COPY of the live
    2026/27 season and verify grouping, canonical metadata resolution and the
    runtime resolver still agree, so the contract never hardcodes ephemeral
    fixture ids."""
    import hashlib

    from competitions.ucl.src.pipeline import build_league_matchdays, build_matchday_map

    season_dir = UCL_DATA / "seasons" / "2026_27"
    fx = json.loads((season_dir / "fixtures.json").read_text(encoding="utf-8"))
    res = json.loads(
        (season_dir / "results.json").read_text(encoding="utf-8")
    )["matches"]
    orig_ids = _season_matchday_fixture_ids(season_dir)
    orig_played_ids = {m["match_id"] for m in res}
    assert orig_ids
    assert orig_played_ids

    def rekey(mid):
        if not mid.startswith("gen-"):
            return mid
        return "genx-" + hashlib.sha256(f"rekeyed\n{mid}".encode()).hexdigest()[:16]

    fx["fixtures"] = [
        {**row, "match_id": rekey(row["match_id"])} for row in fx["fixtures"]
    ]
    res = [{**m, "match_id": rekey(m["match_id"])} for m in res]

    clone = tmp_path / "seasons" / "2026_27"
    clone.mkdir(parents=True)
    (clone / "fixtures.json").write_text(json.dumps(fx, indent=2), encoding="utf-8")
    (clone / "results.json").write_text(
        json.dumps({"matches": res}, indent=2), encoding="utf-8"
    )

    grouped = build_league_matchdays(res, build_matchday_map(clone))
    assert set(grouped) == {"MD01"}
    md1 = grouped["MD01"]
    assert md1
    assert {m["match_id"] for m in md1} <= _season_matchday_fixture_ids(clone)
    assert {m["match_id"] for m in md1}.isdisjoint(orig_ids)
    assert {m["match_id"] for m in md1} == {rekey(x) for x in orig_played_ids}
    assert all(m["match_id"].startswith("genx-") for m in md1)
    assert all(m["status"] == "played" for m in md1)
