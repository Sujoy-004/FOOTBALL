"""Exchange 3: ACTIVE-season simulation truth (served-path E2E).

Scenario: a mid-season UCL snapshot — 60 of 144 league matches played,
knockout store absent — must report an honest lifecycle ("active"), offer
season-wide simulation ("available"), and any run must leave the factual
stores byte-identical while producing clearly SIMULATED projections that
are reproducible per seed.
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
PLAYED_ROWS = 60


@pytest.fixture
def snapshot_mode(monkeypatch):
    import web.startup as startup
    # Pin snapshot through the server lifespan too: zero network.
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield
    startup._last_decision = None


@pytest.fixture
def active_season_dir(tmp_path):
    """Tmp DATA_DIR: real fixtures/rules, league ledger truncated to 60
    played rows, knockout_results.json deliberately ABSENT."""
    shutil.copytree(UCL_DATA, tmp_path, dirs_exist_ok=True)
    # Only the canonical stores are removed; rule/pairing files stay so the
    # canonical bracket layer can still render simulated trees.
    (tmp_path / "knockout_results.json").unlink()
    snapshot = tmp_path / "snapshot.json"
    if snapshot.exists():
        snapshot.unlink()
    payload = json.loads(
        (UCL_DATA / "results.json").read_text(encoding="utf-8"))
    rows = payload["matches"] if isinstance(payload, dict) else payload
    assert len(rows) >= PLAYED_ROWS
    truncated = rows[:PLAYED_ROWS]
    if isinstance(payload, dict):
        payload["matches"] = truncated
        out = payload
    else:
        out = truncated
    (tmp_path / "results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _coeff_elo() -> dict[str, float]:
    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
    coeffs = {t["name"]: t["coefficient"] for t in fixtures["schedule"]["teams"]}
    mx = max(coeffs.values())
    return {n: 1400.0 + (c / mx) * 400.0 for n, c in coeffs.items()}


def _run_to_completion(client: TestClient, body: dict) -> dict:
    resp = client.post("/api/simulate", json=body)
    assert resp.status_code == 200, resp.text
    ack = resp.json()
    assert ack.get("requested") is True, ack
    task_id = ack["task_id"]
    payload = {}
    for _ in range(240):
        time.sleep(0.25)
        payload = client.get(f"/api/simulation/progress/{task_id}").json()
        if payload.get("status") in ("completed", "failed"):
            break
    assert payload.get("status") == "completed", payload
    return payload


class TestActiveSeasonLifecycle:
    def test_active_stage_reported_with_league_progress(self, snapshot_mode, active_season_dir, monkeypatch):
        import web.ucl_app as app
        from web.ucl_app import ucl_app

        monkeypatch.setattr(app, "DATA_DIR", active_season_dir)
        # Minimal cache seed (parity with existing suites); the lifespan
        # recompute reproduces the same values offline from the tmp stores.
        app.cache.update({
            "elo_ratings": _coeff_elo(),
            "availability": {"league_results": "available",
                             "knockout_results": "missing"},
            "champion": None,
        })
        with TestClient(ucl_app) as client:
            data = client.get("/api/data").json()

            lifecycle = data["lifecycle"]
            assert lifecycle["stage"] == "active"
            assert lifecycle["progress"] == {"played": PLAYED_ROWS, "total": 144}
            assert lifecycle["provider_current_season"] is None
            assert lifecycle["season_mismatch"] is False

            sim_block = data["simulation"]
            assert sim_block["availability"] == "available"
            assert sim_block["what_if"] is False

            # Factual counts stay 60-based (never inflated by fixtures).
            assert data["n_played"] == PLAYED_ROWS
            assert data["n_unplayed"] == 144 - PLAYED_ROWS


class TestActiveSeasonSimulationTruth:
    def test_simulation_preserves_facts_and_is_seed_reproducible(
            self, snapshot_mode, active_season_dir, monkeypatch):
        import web.ucl_app as app
        from web.ucl_app import ucl_app

        monkeypatch.setattr(app, "DATA_DIR", active_season_dir)
        app.cache.update({
            "elo_ratings": _coeff_elo(),
            "availability": {"league_results": "available",
                             "knockout_results": "missing"},
            "champion": None,
        })
        app.sim_cache = {}

        results_path = active_season_dir / "results.json"
        fixtures_path = active_season_dir / "fixtures.json"
        results_before = results_path.read_bytes()
        fixtures_before = fixtures_path.read_bytes()

        def _odds_signature(sim_payload: dict) -> list[tuple[str, float]]:
            return [
                (o["team"], float(o["champion_prob"]))
                for o in sim_payload["odds"]
            ]

        with TestClient(ucl_app) as client:
            # ── Run A: seed 777 ──────────────────────────────────────────
            _run_to_completion(client, {"iterations": 3, "seed": 777})

            # Played matches are immutable facts: byte-identical ledger.
            assert results_path.read_bytes() == results_before
            assert fixtures_path.read_bytes() == fixtures_before

            data = client.get("/api/data").json()
            assert data["n_played"] == PLAYED_ROWS
            assert data["phase"]["phase"] == "league_stage"

            sim_a = client.get("/api/simulation").json()
            champ_total = sum(o["champion_prob"] for o in sim_a["odds"])
            assert abs(champ_total - 1.0) < 1e-6
            assert sim_a["simulation_meta"]["seed"] == 777

            bracket = sim_a["bracket"]
            assert bracket and bracket.get("stages")
            for stage_key in ("playoff", "R16", "QF", "SF", "FINAL"):
                for node in bracket["stages"][stage_key]["matches"]:
                    assert node["provenance"] == "simulated", (
                        stage_key, node.get("id"))

            sig_a = _odds_signature(sim_a)
            champion_a = sim_a.get("champion")

            # ── Run B: different seed ────────────────────────────────────
            _run_to_completion(client, {"iterations": 3, "seed": 778})
            sim_b = client.get("/api/simulation").json()
            assert abs(sum(o["champion_prob"] for o in sim_b["odds"]) - 1.0) < 1e-6
            # Each run records ITS OWN seed (provenance, never reused).
            assert sim_b["simulation_meta"]["seed"] == 778
            assert sim_b["simulation_meta"]["seed"] != sim_a["simulation_meta"]["seed"]
            # Nondeterministic across environments: record, never assert.
            champion_differs = sim_b.get("champion") != champion_a

            # ── Run C: same seed as A -> identical projection arrays ────
            _run_to_completion(client, {"iterations": 3, "seed": 777})
            sim_c = client.get("/api/simulation").json()
            assert _odds_signature(sim_c) == sig_a

            # Stores STILL untouched after three runs.
            assert results_path.read_bytes() == results_before
            assert fixtures_path.read_bytes() == fixtures_before
