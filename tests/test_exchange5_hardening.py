"""Exchange 5: final hardening regressions.

Locks down the slot-keyed probability fix, calibration observability
through the shared service, registry-driven mounts, and the honest
odds-semantics marker.
"""

from __future__ import annotations

import shutil
import time
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


class TestSlotKeyFix:
    def test_build_blend_params_excludes_unresolved_slots(self):
        """Bracket slots without real pairings must not carry blended
        probabilities - they would be matchup-blind constants."""
        from competitions.worldcup.src.pipeline import build_blend_params

        class FakeEngine:
            weights = {"elo": 0.2}

            class BP:
                home_prob = 0.61

            def evaluate(self, match, context):
                return self.BP()

        matches = [
            {"match_id": "GS_A_01", "team_a": "Mexico", "team_b": "Canada"},
            # Real knockout fixture rows on disk carry no teams:
            {"match_id": "M73", "home": {"kind": "group_position"}, "away": {}},
            {"match_id": "FINAL"},
        ]
        params = build_blend_params([FakeEngine.BP()] * 3, matches, FakeEngine())
        assert set(params["match_probs"]) == {"GS_A_01"}

    def test_unresolved_slots_fall_back_to_matchup_aware_elo(self):
        from football_core.elo import expected_score
        from football_core.knockout import _get_blended_prob

        blend = {"match_probs": {}, "blend_weights": {}}
        p = _get_blended_prob("M73", "Argentina", "Spain", blend,
                              {"Argentina": 2100, "Spain": 2050})
        assert p > 0.5, "stronger team must hold the advantage via fallback"

    def test_group_only_blend_matches_elo_fallback_outcomes(self):
        """Production blend_params contain ONLY real-pairing (group) ids.
        Knockout ties must therefore resolve identically whether or not
        such a payload is supplied - proving no matchup-blind constant
        reaches the simulation."""
        import json
        from competitions.worldcup.src.knockout import run_full_simulation

        teams = json.loads((WC_DATA / "teams.json").read_text("utf-8"))
        groups = json.loads((WC_DATA / "groups.json").read_text("utf-8"))
        bracket = json.loads((WC_DATA / "bracket.json").read_text("utf-8"))
        annex = json.loads((WC_DATA / "annex_c.json").read_text("utf-8"))

        # Mimic the production payload shape after the Exchange 5 fix:
        # every entry carries a REAL pairing (the 72 group fixtures).
        group_only = {
            "match_probs": {m["match_id"]: 0.99
                            for g in groups["groups"].values()
                            for m in g["matches"]},
            "blend_weights": {"elo": 1.0},
        }
        base = run_full_simulation(teams, groups, bracket, annex, {},
                                   iterations=60, seed=42)
        with_blend = run_full_simulation(teams, groups, bracket, annex, {},
                                         iterations=60, seed=42,
                                         blend_params=group_only)
        assert base == with_blend

        top5 = sorted(
            ((t, v["champion"]) for t, v in base.items() if t != "_meta"),
            key=lambda kv: kv[1], reverse=True)[:5]
        elos = {t: d["elo"] for t, d in teams.items()}
        avg_top5_elo = sum(elos[t] for t, _ in top5) / 5
        avg_all_elo = sum(elos.values()) / len(elos)
        assert avg_top5_elo > avg_all_elo


class TestCalibrationViaSharedService:
    def test_ucl_calibration_progress_is_observable(self, snapshot_mode,
                                                    tmp_path, monkeypatch):
        """Regression: calibrate task ids used to poll to not_found because
        the legacy registry was never read. Now the shared service tracks it."""
        import web.ucl_app as app
        from web.ucl_app import ucl_app
        app.DATA_DIR = UCL_DATA
        with TestClient(ucl_app) as client:
            r = client.post("/api/calibrate")
            assert r.status_code == 200
            task_id = r.json()["task_id"]
            statuses = []
            for _ in range(120):
                time.sleep(0.25)
                pr = client.get(f"/api/simulation/progress/{task_id}").json()
                statuses.append(pr["status"])
                if pr["status"] in ("completed", "failed"):
                    break
            assert statuses[-1] in ("completed", "failed"), statuses
            assert "not_found" not in statuses[:-1], (
                "task must remain pollable until terminal")


class TestRegistryWiring:
    def test_server_mounts_derive_from_registry(self, snapshot_mode):
        from web.server import app as server_app
        from web.competitions import REGISTRY

        mounted_prefixes = set()
        for route in server_app.routes:
            path = getattr(route, "path", "")
            for adapter in REGISTRY.list():
                if path.startswith(adapter.mount_prefix):
                    mounted_prefixes.add(adapter.mount_prefix)
        assert mounted_prefixes == {"/worldcup", "/ucl"}

    def test_default_count_matches_documented_default(self, snapshot_mode):
        import inspect
        from web import ucl_app
        src = inspect.getsource(ucl_app.api_simulate)
        assert "default_count=5000" in src


class TestOddsSemanticsMarker:
    def test_results_mode_odds_are_labeled_indicators(self, snapshot_mode):
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            body = client.get("/api/odds").json()
            assert body["odds_semantics"] == "achieved_outcome_indicators"
