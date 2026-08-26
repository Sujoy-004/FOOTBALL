"""Exchange 4: competition registry + shared simulation product contract.

Covers the user-facing truth model: canonical status vocabulary, validation
before eligibility, availability/request-state exposure, registry discovery,
and reproducibility through the actual API path.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


@pytest.fixture
def snapshot_mode(monkeypatch):
    import web.startup as startup
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield
    startup._last_decision = None


# ── Registry ────────────────────────────────────────────────────────────────

class TestCompetitionRegistry:
    def test_default_registry_resolves_both_competitions(self):
        from web.competitions import build_default_registry
        reg = build_default_registry()
        assert reg.ids() == ["worldcup", "ucl"]
        wc = reg.get("worldcup")
        ucl = reg.get("ucl")
        assert wc.mount_prefix == "/worldcup"
        assert ucl.mount_prefix == "/ucl"
        assert wc.display_name and ucl.display_name

    def test_unknown_competition_lists_known_ids(self):
        from web.competitions import build_default_registry
        reg = build_default_registry()
        with pytest.raises(KeyError) as exc:
            reg.get("laliga")
        assert "worldcup" in str(exc.value)
        assert "ucl" in str(exc.value)

    def test_duplicate_registration_rejected(self):
        from web.competitions import (
            CompetitionAdapter, CompetitionRegistry, build_default_registry)
        reg = CompetitionRegistry()
        template = build_default_registry().get("worldcup")
        reg.register(template)
        with pytest.raises(ValueError):
            reg.register(template)

    def test_status_shape_contract_on_snapshot_data(self, snapshot_mode):
        """Both adapters expose the identical status shape from real data."""
        from web.competitions import REGISTRY
        from web.server import app as server_app
        # Boot once so both apps' caches are populated (as in production).
        with TestClient(server_app):
            for adapter in REGISTRY.list():
                status = adapter.status()
                for key in ("phase", "n_played", "n_unplayed",
                            "availability", "champion"):
                    assert key in status, (adapter.id, key)
                phase = status["phase"]
                assert "label" in phase and "progress" in phase and "stores" in phase

    def test_simulation_support_shape_and_wc_not_needed(self, snapshot_mode):
        from web.competitions import REGISTRY
        wc = REGISTRY.get("worldcup").simulation()
        assert wc["availability"] == "not_needed"
        assert wc["reason"] == "no_unplayed_matches"
        assert wc["request_state"] == "not_requested"
        ucl = REGISTRY.get("ucl").simulation()
        # Current dataset: league complete but KO undecided -> projectable.
        assert ucl["availability"] == "available"

    def test_server_mounts_come_from_registry(self, snapshot_mode):
        from web.server import app as server_app
        from web.competitions import REGISTRY
        mounted = {route.path for route in server_app.routes}
        for adapter in REGISTRY.list():
            with TestClient(adapter.subapp) as client:
                r = client.get("/api/data")
                assert r.status_code == 200, adapter.id


# ── Shared simulation product contract ─────────────────────────────────────

class TestSharedContractStates:
    def test_validation_error_precedes_eligibility_wc(self, snapshot_mode):
        """Invalid count is rejected even when nothing needs simulating."""
        from web.wc_app import wc_app
        with TestClient(wc_app) as client:
            r = client.post("/api/simulate",
                            json={"iterations": 2_000_000})
            assert r.status_code == 400
            assert r.json()["status"] == "validation_error"

    def test_validation_error_precedes_eligibility_ucl(self, snapshot_mode):
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            r = client.post("/api/simulate", json={"iterations": -5})
            assert r.status_code == 400
            assert r.json()["status"] == "validation_error"

    def test_not_requested_state_before_any_run(self, snapshot_mode):
        from web.wc_app import wc_app
        import web.wc_app as wc_mod
        wc_mod.sim_cache = {}
        with TestClient(wc_app) as client:
            body = client.get("/api/simulation").json()
            assert body["status"] == "not_requested"
            overview = client.get("/api/overview").json()
            assert overview["has_simulation"] is False
            data = client.get("/api/data").json()
            assert data["simulation"]["request_state"] == "not_requested"
            assert data["simulation"]["availability"] == "not_needed"

    def test_ucl_availability_available_when_ko_undecided(
            self, snapshot_mode, tmp_path, monkeypatch):
        """League complete + knockout store absent -> outcomes undecided,
        simulation stays available. Isolated data dir so this holds whether
        or not the real dataset carries backfilled knockout history."""
        import web.ucl_app as app
        from web.ucl_app import ucl_app
        for f in ("fixtures.json", "team_aliases.json", "results.json"):
            shutil.copy(UCL_DATA / f, tmp_path / f)
        monkeypatch.setattr(app, "DATA_DIR", tmp_path)
        with TestClient(ucl_app) as client:
            data = client.get("/api/data").json()
            assert data["simulation"]["availability"] == "available"
            assert data["phase"]["phase"] == "league_stage_complete"
            assert data["simulation"].get("what_if") is False

    def test_ucl_completed_run_exposes_shared_meta(
            self, snapshot_mode, tmp_path, monkeypatch):
        import web.ucl_app as app
        from web.ucl_app import ucl_app
        for f in ("fixtures.json", "team_aliases.json"):
            shutil.copy(UCL_DATA / f, tmp_path / f)
        monkeypatch.setattr(app, "DATA_DIR", tmp_path)
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
            r = client.post("/api/simulate",
                            json={"iterations": 3, "seed": 4242})
            assert r.status_code == 200
            task_id = r.json()["task_id"]
            for _ in range(120):
                time.sleep(0.25)
                pr = client.get(f"/api/simulation/progress/{task_id}").json()
                if pr["status"] in ("completed", "failed"):
                    break
            assert pr["status"] == "completed", pr

            sim = client.get("/api/simulation").json()
            meta = sim["simulation_meta"]
            assert meta["requested"] is True
            assert meta["status"] == "completed"
            assert meta["seed"] == 4242
            assert meta["provenance"]["real_results_preserved"] is True
            # Terminal tasks are cleaned up unconditionally.
            again = client.get(f"/api/simulation/progress/{task_id}").json()
            assert again["status"] == "not_found"

            # Reproducibility through the API path: same seed, same state.
            app.cache.update({"elo_ratings": dict(app.cache["elo_ratings"])})
            r2 = client.post("/api/simulate",
                             json={"iterations": 3, "seed": 4242})
            task_id2 = r2.json()["task_id"]
            for _ in range(120):
                time.sleep(0.25)
                pr2 = client.get(f"/api/simulation/progress/{task_id2}").json()
                if pr2["status"] in ("completed", "failed"):
                    break
            assert pr2["status"] == "completed"
            sim2 = client.get("/api/simulation").json()
            top1 = max(sim["odds"], key=lambda o: o.get("champion_prob", 0))
            top2 = max(sim2["odds"], key=lambda o: o.get("champion_prob", 0))
            assert top1["team"] == top2["team"]
            assert abs(top1["champion_prob"] - top2["champion_prob"]) < 1e-9

            # Canonical real-data file was never created by the simulation.
            assert not (tmp_path / "knockout_results.json").exists()


# ── Frontend truth wiring ──────────────────────────────────────────────────

class TestFrontendTruthWiring:
    def _served(self, client, name):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200
        return r.text

    def test_wc_frontend_labels_and_states(self, snapshot_mode):
        from web.server import app as server_app
        with TestClient(server_app) as client:
            js = self._served(client, "wc.js")
            assert "SIM " in js                      # projected overlay label
            assert '"not_needed"' in js              # canonical status match
            assert '"completed"' in js and '"failed"' in js
            assert "Simulation is not needed" in js  # completed-season copy
            assert "__refreshWC" not in js           # dead handler removed

    def test_ucl_frontend_controls_and_no_fabrication(self, snapshot_mode):
        from web.server import app as server_app
        with TestClient(server_app) as client:
            js = self._served(client, "ucl.js")
            assert "/simulate" in js                 # controls now exist
            assert "Run Simulation" in js
            assert "SIMULATION" in js                # provenance banner
            assert "not needed" in js.lower() or "not_needed" in js
            assert "|| 0.33" not in js and "|| 0.5" not in js
            shared = self._served(client, "shared.js")
            assert '"not_needed"' in shared and '"completed"' in shared
