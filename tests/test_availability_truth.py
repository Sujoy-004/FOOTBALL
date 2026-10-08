"""Plan 02-07 — truthful four-state availability with reasons, payload-wide.

Criterion 1 end-to-end: with ``worldcup/data/played.json`` deleted the WC
``/api/data`` and ``/api/overview`` report ``played: missing`` with a
human-readable reason — never a rendered zero or an empty table. ``missing``
and ``empty`` are distinct states, and ``n_played``/``n_unplayed`` are
omitted (never ``0``) while the underlying store cannot be read.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

FOUR_STATES = {"available", "empty", "missing", "unavailable"}


def _pin_snapshot() -> None:
    import web.startup as startup

    startup.set_session_decision(startup.StartupDecision("snapshot", ""))


@pytest.fixture
def wc_dir(tmp_path, monkeypatch):
    """Seeded WC tmp data dir; cache rebuilt from that seeded dir."""
    import arch_util as au
    import web.wc_app as wc_app
    from competitions.worldcup.src import overview as wc_overview

    dst = au.seed_wc_dir(tmp_path / "wc")
    monkeypatch.setattr(wc_app, "DATA_DIR", dst)
    monkeypatch.setattr(wc_overview, "DATA_DIR", dst)
    saved = au.snapshot_cache_state(wc_app)
    wc_app.cache.clear()
    from web.wc_app import compute_overview
    wc_app.cache.update(compute_overview())
    _pin_snapshot()
    try:
        yield dst
    finally:
        au.restore_cache_state(wc_app, saved)
        import web.startup as startup

        startup.set_session_decision(None)


@pytest.fixture
def ucl_dir(tmp_path, monkeypatch):
    """Full copy of the real UCL data dir; cache rebuilt."""
    import web.ucl_app as ucl_app

    dst = tmp_path / "ucl_data"
    shutil.copytree(ROOT / "competitions" / "ucl" / "data", dst)
    # The real 2026/27 season dir ships no knockout_results.json; creating
    # an empty one gives a fully readable store set (EMPTY is honest) so the
    # healthy case asserts the no-reason contract.
    (dst / "seasons" / "2026_27" / "knockout_results.json").write_text(
        "{}", encoding="utf-8")
    monkeypatch.setattr(ucl_app, "DATA_DIR", dst)
    ucl_app.cache = ucl_app.compute_all()
    _pin_snapshot()
    try:
        yield dst
    finally:
        import web.startup as startup

        startup.set_session_decision(None)


@pytest.fixture
def laliga_dir(tmp_path, monkeypatch):
    """Full copy of the real LaLiga data dir; cache rebuilt."""
    import web.laliga_app as laliga_app

    dst = tmp_path / "laliga_data"
    shutil.copytree(ROOT / "competitions" / "laliga" / "data", dst)
    monkeypatch.setattr(laliga_app, "DATA_DIR", dst)
    laliga_app.cache = laliga_app.compute_all()
    _pin_snapshot()
    try:
        yield dst
    finally:
        import web.startup as startup

        startup.set_session_decision(None)


class TestWCAvailability:
    def test_all_available_omits_reason(self, wc_dir):
        from web.wc_app import wc_app

        with TestClient(wc_app) as client:
            data = client.get("/api/data").json()
            assert data["availability"] == {
                "played_groups": "available",
                "played": "available",
            }
            assert "availability_reason" not in data
            assert isinstance(data["n_played"], int)
            assert isinstance(data["n_unplayed"], int)

    def test_missing_store_reports_missing_omits_counts(self, wc_dir):
        from web.wc_app import wc_app

        (wc_dir / "played.json").unlink()
        with TestClient(wc_app) as client:
            data = client.get("/api/data").json()
            assert data["availability"]["played"] == "missing"
            assert "played.json" in data["availability_reason"]["played"]
            assert "n_played" not in data
            assert "n_unplayed" not in data
            assert "refresh" in data

    def test_empty_is_not_missing(self, wc_dir):
        from web.wc_app import wc_app

        (wc_dir / "played.json").write_text("{}", encoding="utf-8")
        with TestClient(wc_app) as client:
            data = client.get("/api/data").json()
            assert data["availability"]["played"] == "empty"
            assert "played" not in data.get("availability_reason", {})
            # EMPTY is an honest, readable state: counts are present, not omitted.
            assert isinstance(data["n_unplayed"], int)

    def test_unparseable_is_unavailable(self, wc_dir):
        from web.wc_app import wc_app

        (wc_dir / "played.json").write_text("{not json", encoding="utf-8")
        with TestClient(wc_app) as client:
            data = client.get("/api/data").json()
            assert data["availability"]["played"] == "unavailable"
            assert "played" in data["availability_reason"]
            assert "n_played" not in data
            assert "n_unplayed" not in data

    def test_overview_parity(self, wc_dir):
        from web.wc_app import wc_app

        with TestClient(wc_app) as client:
            data = client.get("/api/data").json()
            overview = client.get("/api/overview").json()
            assert overview["availability"] == data["availability"]
            assert overview.get("availability_reason") == data.get(
                "availability_reason")

    def test_simulate_refused_on_missing_store(self, wc_dir):
        from web.wc_app import wc_app

        (wc_dir / "played.json").unlink()
        with TestClient(wc_app) as client:
            r = client.post("/api/simulate", json={"iterations": 5})
            assert r.status_code == 409
            assert "played" in r.json()["error"]

    def test_simulate_proceeds_when_store_empty(self, wc_dir):
        from web.wc_app import wc_app

        (wc_dir / "played.json").write_text("{}", encoding="utf-8")
        with TestClient(wc_app) as client:
            r = client.post("/api/simulate", json={"iterations": 5})
            assert r.status_code != 409

    def test_what_if_refused_on_missing_store(self, wc_dir):
        from web.wc_app import wc_app

        (wc_dir / "played.json").unlink()
        with TestClient(wc_app) as client:
            r = client.post(
                "/api/what-if", json={"match_id": "X", "elo_delta": 50})
            assert r.status_code == 409
            assert "played" in r.json()["error"]


class TestUCLLaLigaAvailability:
    def test_ucl_reason_parity_and_healthy_omits_reason(self, ucl_dir):
        import web.ucl_app as ucl_app
        from web.ucl_app import ucl_app as app

        with TestClient(app) as client:
            data = client.get("/api/data").json()
            assert "availability_reason" not in data
        (ucl_dir / "seasons" / "2026_27" / "results.json").unlink()
        ucl_app.cache = ucl_app.compute_all()
        with TestClient(app) as client:
            data = client.get("/api/data").json()
            assert data["availability"]["league_results"] == "missing"
            assert "results.json" in (
                data["availability_reason"]["league_results"])

    def test_laliga_reason_parity_and_healthy_omits_reason(self, laliga_dir):
        import web.laliga_app as laliga_app

        with TestClient(laliga_app.laliga_app) as client:
            data = client.get("/api/data").json()
            assert "availability_reason" not in data
        from competitions.laliga.src import seasons as season_store

        active = season_store.active_season(laliga_dir)
        target = season_store.season_dir(laliga_dir, active) / "results.json"
        target.unlink()
        laliga_app.cache = laliga_app.compute_all()
        with TestClient(laliga_app.laliga_app) as client:
            data = client.get("/api/data").json()
            assert data["availability"]["results"] == "missing"
            assert "results.json" in data["availability_reason"]["results"]

    def test_ucl_payload_key_set_unchanged(self, ucl_dir):
        import web.ucl_app as ucl_app
        from web.ucl_app import ucl_app as app

        ucl_app.cache = ucl_app.compute_all()
        with TestClient(app) as client:
            data = client.get("/api/data").json()
            expected = {
                "refresh", "teams", "all_teams", "n_teams", "n_iterations",
                "snapshot_date", "champion", "mode", "availability", "phase",
                "lifecycle", "season", "n_total_fixtures", "simulation",
                "n_unplayed", "n_played",
            }
            assert set(data) == expected

    def test_laliga_payload_key_set_unchanged(self, laliga_dir):
        import web.laliga_app as laliga_app

        laliga_app.cache = laliga_app.compute_all()
        with TestClient(laliga_app.laliga_app) as client:
            data = client.get("/api/data").json()
            expected = {
                "refresh", "teams", "all_teams", "standings", "n_teams",
                "n_iterations", "snapshot_date", "champion", "mode",
                "availability", "phase", "season", "n_total_fixtures",
                "odds_status", "simulation", "n_unplayed", "n_played",
            }
            assert set(data) == expected


class TestWCTruthPayloadParity:
    def test_wc_phase_and_no_simulation_carries_availability(self, monkeypatch):
        import web.startup as startup

        monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
        startup.set_session_decision(startup.StartupDecision("snapshot", ""))
        try:
            from web.wc_app import cache, compute_overview, wc_app

            cache.update(compute_overview())
            with TestClient(wc_app) as client:
                overview = client.get("/api/overview").json()
                assert overview["has_simulation"] is False
                assert set(overview["availability"].values()) <= FOUR_STATES
                assert set(overview["availability"]) == {"played", "played_groups"}
                assert "availability_reason" not in overview
        finally:
            startup.set_session_decision(None)
