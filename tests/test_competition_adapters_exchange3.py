"""Exchange 3: competition adapter behavior + API simulation contract.

Covers: WC/UCL adapter determinism through the public wrappers, the
eligibility honesty logic, endpoint validation errors (no silent clamping),
and the no-simulated-data-before-a-run guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


@pytest.fixture
def snapshot_mode(monkeypatch):
    import web.startup as startup
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield
    startup._last_decision = None


class TestAdapterDeterminism:
    def test_wc_wrapper_deterministic_and_contract_shaped(self):
        from competitions.worldcup.src.knockout import run_full_simulation
        teams = json.loads((WC_DATA / "teams.json").read_text("utf-8"))
        groups = json.loads((WC_DATA / "groups.json").read_text("utf-8"))
        bracket = json.loads((WC_DATA / "bracket.json").read_text("utf-8"))
        annex = json.loads((WC_DATA / "annex_c.json").read_text("utf-8"))
        args = (teams, groups, bracket, annex, {})
        a = run_full_simulation(*args, iterations=30, seed=42)
        b = run_full_simulation(*args, iterations=30, seed=42)
        assert a == b
        for team in teams:
            assert set(a[team].keys()) == {"qf", "sf", "final", "champion"}
        champ_total = sum(a[t]["champion"] for t in teams)
        assert abs(champ_total - 1.0) < 1e-9

    def test_ucl_wrapper_deterministic(self):
        from dataclasses import asdict
        from football_core.provider import FixtureSchedule
        from competitions.ucl.src.simulation import run_monte_carlo
        fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
        sched = FixtureSchedule.from_dict(fixtures["schedule"])
        fd = {"schedule": asdict(sched)}
        coeffs = {t.name: t.coefficient for t in sched.teams}
        mx = max(coeffs.values())
        elo = {t.name: 1400.0 + (coeffs[t.name] / mx) * 400.0 for t in sched.teams}
        a = run_monte_carlo(fd, elo_ratings=elo, n_iterations=15, seed=42)
        b = run_monte_carlo(fd, elo_ratings=elo, n_iterations=15, seed=42)
        assert a == b
        champ_total = sum(v["champion_prob"] for v in a["teams"].values())
        assert abs(champ_total - 1.0) < 1e-9
        # Every legacy D-06/D-07/D-09 field is present.
        sample = next(iter(a["teams"].values()))
        for key in ("top_8_prob", "playoff_prob", "eliminated_prob",
                    "champion_prob", "avg_position", "avg_pts",
                    "stage_final_prob", "stage_champion_prob"):
            assert key in sample


class TestEligibilityHonesty:
    def test_completed_real_season_is_not_simulatable(self):
        """All league matches played AND champion on file -> nothing to project."""
        from web.ucl_app import _season_outcome_undecided, cache
        saved = dict(cache)
        try:
            cache.update({
                "availability": {"league_results": "available",
                                 "knockout_results": "available"},
                "champion": "Real Madrid",
            })
            import web.ucl_app as app
            monkey_unplayed = 0
            original = app._unplayed_match_count
            app._unplayed_match_count = lambda: monkey_unplayed
            try:
                assert _season_outcome_undecided() is False
            finally:
                app._unplayed_match_count = original
        finally:
            cache.clear()
            cache.update(saved)

    def test_empty_knockout_store_keeps_season_projectable(self):
        """Missing/empty KO data means outcomes are UNDECIDED - the season
        stays simulatable; it must NOT be read as 'phase never happened'."""
        from web.ucl_app import _season_outcome_undecided, cache
        saved = dict(cache)
        try:
            cache.update({
                "availability": {"league_results": "available",
                                 "knockout_results": "empty"},
                "champion": None,
            })
            import web.ucl_app as app
            original = app._unplayed_match_count
            app._unplayed_match_count = lambda: 0
            try:
                assert _season_outcome_undecided() is True
            finally:
                app._unplayed_match_count = original
        finally:
            cache.clear()
            cache.update(saved)


class TestApiValidationContract:
    def test_wc_rejects_over_max_without_clamping(self, snapshot_mode):
        from web.wc_app import wc_app
        with TestClient(wc_app) as client:
            r = client.post("/api/simulate", json={"iterations": 2_000_000})
            assert r.status_code == 400
            body = r.json()
            assert body["status"] == "invalid_request"
            assert "1000000" in body["error"] or "1,000,000" in body["error"]

    def test_wc_rejects_zero_even_when_season_complete(self, snapshot_mode):
        from web.wc_app import wc_app
        with TestClient(wc_app) as client:
            r = client.post("/api/simulate", json={"iterations": 0})
            assert r.status_code == 400
            assert r.json()["status"] == "invalid_request"

    def test_wc_completed_season_short_circuits_honestly(self, snapshot_mode):
        from web.wc_app import wc_app
        with TestClient(wc_app) as client:
            r = client.post("/api/simulate", json={"iterations": 1_000})
            # Completed real tournament: nothing outstanding, and the real
            # champion stands - simulation neither runs nor replaces history.
            assert r.status_code == 200
            assert r.json()["status"] == "no_unplayed_matches"

    def test_ucl_rejects_invalid_count(self, snapshot_mode):
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            for bad in (0, -3):
                r = client.post("/api/simulate", json={"iterations": bad})
                assert r.status_code == 400
                assert r.json()["status"] == "invalid_request"

    def test_ucl_accepts_min_and_runs_with_generated_seed(
            self, snapshot_mode, tmp_path, monkeypatch):
        """Served-path E2E on an isolated data dir: count=1 accepted, engine
        generates a seed and returns it in the simulation metadata."""
        import shutil
        import time
        import web.ucl_app as app
        from web.ucl_app import ucl_app
        for f in ("fixtures.json", "team_aliases.json"):
            shutil.copy(UCL_DATA / f, tmp_path / f)
        monkeypatch.setattr(app, "DATA_DIR", tmp_path)
        # Pre-seed cache so the offline Elo override is used (no ClubElo);
        # derive ratings from fixture coefficients like the boot fallback.
        fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
        teams = fixtures["schedule"]["teams"]
        coeffs = {t["name"]: t["coefficient"] for t in teams}
        mx = max(coeffs.values())
        app.cache.update({
            "elo_ratings": {n: 1400.0 + (c / mx) * 400.0
                            for n, c in coeffs.items()},
            "availability": {"league_results": "missing",
                             "knockout_results": "missing"},
            "champion": None,
        })
        with TestClient(ucl_app) as client:
            r = client.post("/api/simulate", json={"iterations": 1, "seed": None})
            assert r.status_code == 200
            assert r.json()["requested"] is True
            task_id = r.json()["task_id"]
            status = ""
            payload = {}
            import time
            for _ in range(120):
                time.sleep(0.25)
                payload = client.get(
                    f"/api/simulation/progress/{task_id}").json()
                status = payload.get("status", "")
                if status in ("complete", "error"):
                    break
            assert status == "complete", payload
            sim = client.get("/api/simulation").json()
            meta = sim["simulation_meta"]
            assert meta["requested"] is True
            assert meta["count"] >= 1
            assert isinstance(meta["seed"], int) and meta["seed"] > 0
            assert meta["provenance"]["real_results_preserved"] is True

    def test_no_simulation_means_no_simulated_payload(self, snapshot_mode):
        from web import wc_app
        # Isolate from earlier tests that legitimately set the global.
        wc_app.sim_cache = {}
        with TestClient(wc_app.wc_app) as client:
            sim = client.get("/api/simulation").json()
            assert sim["status"] == "none"
            overview = client.get("/api/overview").json()
            assert overview["has_simulation"] is False
