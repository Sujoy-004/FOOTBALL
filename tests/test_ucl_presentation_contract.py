"""Regression tests for the UCL season presentation contract."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


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
    app, _ = active_2026_runtime

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
    assert set(matchdays) == {"MD01"}
    assert all(not key.startswith("gen-") for key in matchdays)
    assert [m["match_id"] for m in matchdays["MD01"]] == [
        "gen-718aee3152be59d5",
        "gen-398466668835ffd4",
        "gen-4ac782392d1a34de",
        "gen-cfa02111ba88e027",
        "gen-f4b6285469c3b0e0",
        "gen-2ce302d883e61826",
    ]
    assert all(m["status"] == "played" for m in matchdays["MD01"])
    assert bracket["lifecycle"]["season"] == "2026/27"

    assert seasons["active_season"] == "2026/27"
    assert odds["season"] == "2026/27"
    assert len(odds["odds"]) == 36
    assert signals["season"] == "2026/27"


def test_season_switch_recomputes_all_payloads_without_leakage(active_2026_runtime):
    app, _ = active_2026_runtime

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
        assert len(current_matchdays["MD01"]) == 6


def test_authoritative_matchday_metadata_and_legacy_fallback():
    from competitions.ucl.src.pipeline import build_league_matchdays, build_matchday_map

    season_dir = UCL_DATA / "seasons" / "2026_27"
    matchday_map = build_matchday_map(season_dir)
    results = json.loads((season_dir / "results.json").read_text(encoding="utf-8"))["matches"]
    grouped = build_league_matchdays(results, matchday_map)
    assert set(grouped) == {"MD01"}
    assert all(not key.startswith("gen-") for key in grouped)
    assert {m["match_id"] for m in grouped["MD01"]} == {
        "gen-718aee3152be59d5",
        "gen-398466668835ffd4",
        "gen-4ac782392d1a34de",
        "gen-cfa02111ba88e027",
        "gen-f4b6285469c3b0e0",
        "gen-2ce302d883e61826",
    }

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
