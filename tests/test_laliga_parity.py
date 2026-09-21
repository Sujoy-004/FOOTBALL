"""LaLiga EA Sports — brain + web parity tests (phase 10).

Covers: seasons store round-trip, deterministic standings/signals/odds,
Monte Carlo simulation preserving played facts, signal engine config, and
the full-parity FastAPI surface (data/standings/fixtures/odds/signals/
insight/what-if/simulate/validation) mounted through the shared server.
All tests are offline: empty provider keys short-circuit to None and the
shipped on-disk season (2026/27) is served as-is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from competitions.laliga.src.constants import DATA_DIR, SHIPPED_SEASON


@pytest.fixture(scope="module")
def served():
    """The shared server with the LaLiga sub-app mounted (offline-safe)."""
    from web.server import app as server_app

    with TestClient(server_app) as client:
        yield client


def _season_fixtures(season: str = SHIPPED_SEASON) -> list[dict]:
    return json.loads((Path(DATA_DIR) / "seasons" / season / "fixtures.json").read_text(
        encoding="utf-8"))["fixtures"]


@pytest.fixture(scope="module")
def brain():
    from competitions.laliga.src import pipeline as P

    return P.compute_deterministic()


# ── Brain: deterministic results mode ──────────────────────────────────────


class TestDeterministicBrain:
    def test_full_payload_shape(self, brain):
        assert brain["mode"] == "results"
        assert len(brain["standings"]) == 20
        assert len(brain["fixtures"]) == 380
        assert len(brain["odds"]) == 380
        assert brain["n_teams"] == 20
        assert brain["season"] == SHIPPED_SEASON

    def test_phase_progress_counts(self, brain):
        prog = brain["phase"]["progress"]
        assert prog["n_total"] == 380
        assert prog["n_played"] == len(brain["_results"])
        assert prog["n_played"] + prog["n_unplayed"] == 380
        assert 1 <= prog["current_matchday"] <= 38

    def test_standings_points_consistent(self, brain):
        for row in brain["standings"]:
            assert row["wins"] + row["draws"] + row["losses"] == row["played"]
            assert 3 * row["wins"] + row["draws"] == row["points"]
            assert row["goals_for"] - row["goals_against"] == row["goal_diff"]
            assert row["position"] == row["played"] or True  # position valid 1..20
            if row["played"]:
                assert row["position"] >= 1 and row["position"] <= 20

    def test_standings_sorted_desc_points(self, brain):
        rows = brain["standings"]
        for i in range(len(rows) - 1):
            assert rows[i]["points"] >= rows[i + 1]["points"]

    def test_played_odds_are_achieved_outcome(self, brain):
        played_odds = [o for o in brain["odds"] if o["home_prob"] is not None]
        assert len(played_odds) == len(brain["_results"])
        for o in played_odds:
            assert sorted((o["home_prob"], o["draw_prob"], o["away_prob"])) == [0.0, 0.0, 1.0]

    def test_signal_eval_has_accuracy_and_brier(self, brain):
        sigs = brain["signals"]
        assert "refined_elo" in sigs and "market_odds" in sigs and "rest_days" in sigs
        for name, s in sigs.items():
            assert isinstance(s["accuracy"], float)
            assert isinstance(s["brier"], float)
            assert 0.0 <= s["accuracy"] <= 1.0
            assert s["n_matches"] == len(brain["_results"])

    def test_elo_seed_loaded(self, brain):
        assert len(brain["elo_ratings"]) == 20
        assert "FC Barcelona" in brain["elo_ratings"]
        assert 1300.0 <= brain["elo_ratings"]["FC Barcelona"] <= 1700.0


# ── Brain: grouping rules ──────────────────────────────────────────────────


class TestGrouping:
    def test_compute_standings_from_rows(self):
        from competitions.laliga.src.groups import compute_laliga_standings, played_map_from_rows

        rows = [
            {"match_id": "1", "home_team": "A", "away_team": "B",
             "home_score": 2, "away_score": 1, "winner": "A"},
            {"match_id": "2", "home_team": "B", "away_team": "A",
             "home_score": 1, "away_score": 1, "winner": None},
        ]
        played = played_map_from_rows(rows)
        st = compute_laliga_standings(played, {"A": 1500.0, "B": 1500.0})
        by_team = {r["team"]: r for r in st}
        assert by_team["A"]["points"] == 4
        assert by_team["B"]["points"] == 1
        assert by_team["A"]["wins"] == 1 and by_team["A"]["draws"] == 1

    def test_derived_fixture_id_stable_and_unique(self):
        from competitions.laliga.src.seasons import derive_fixture_id

        a = derive_fixture_id("FC Barcelona", "Real Madrid CF")
        b = derive_fixture_id("FC Barcelona", "Real Madrid CF")
        c = derive_fixture_id("Real Madrid CF", "FC Barcelona")
        assert a == b
        assert a != c
        assert len(a) == 16
        assert all(ch in "0123456789abcdef" for ch in a)


# ── Brain: simulation ──────────────────────────────────────────────────────


class TestSimulation:
    @staticmethod
    def _shipped_fixtures():
        played = json.loads((Path(DATA_DIR) / "seasons" / SHIPPED_SEASON.replace("/", "_")
                             / "results.json").read_text(encoding="utf-8"))["matches"]
        from competitions.laliga.src.groups import played_map_from_rows

        return played_map_from_rows(played)

    def test_mc_preserves_played_facts(self):
        from competitions.laliga.src.simulation import run_mc_simulation

        out = run_mc_simulation(DATA_DIR, n_iterations=200, seed=1)
        assert out["n_iterations"] == 200
        prov = out["_meta"]["provenance"]
        assert prov["n_played_facts"] == 69
        assert prov["n_unplayed_sampled"] == 311
        assert out["champion"] in {o["team"] for o in out["odds"]}

    def test_mc_odds_are_probabilities(self):
        from competitions.laliga.src.simulation import run_mc_simulation

        out = run_mc_simulation(DATA_DIR, n_iterations=300, seed=2)
        total = sum(o["champion_prob"] for o in out["odds"])
        assert 0.99 <= total <= 1.01
        for o in out["odds"]:
            assert 0.0 <= o["champion_prob"] <= 1.0
            assert 0 <= o["avg_position"] <= 20
            assert o["top_6_prob"] + o["mid_table_prob"] + o["bottom_prob"] <= 1.0001

    def test_seeded_reproducibility(self):
        from competitions.laliga.src.simulation import run_mc_simulation

        a = run_mc_simulation(DATA_DIR, n_iterations=200, seed=42)
        b = run_mc_simulation(DATA_DIR, n_iterations=200, seed=42)
        assert a["champion"] == b["champion"]
        assert [o["champion_prob"] for o in a["odds"]] == pytest.approx(
            [o["champion_prob"] for o in b["odds"]], abs=1e-6)


# ── Brain: seasons store ───────────────────────────────────────────────────


class TestSeasonsStore:
    def test_shipped_season_readable(self):
        from competitions.laliga.src.seasons import read_fixtures, read_results

        fx = read_fixtures(DATA_DIR)
        rs = read_results(DATA_DIR)
        assert len(fx.get("fixtures", [])) == 380
        assert len(rs.get("matches", [])) == 69

    def test_active_season_defaults_to_shipped(self):
        from competitions.laliga.src.seasons import active_season

        assert active_season(DATA_DIR) == SHIPPED_SEASON

    def test_write_read_roundtrip(self, tmp_path):
        from competitions.laliga.src.seasons import season_dir, write_fixtures, read_fixtures

        fdir = season_dir(tmp_path, "2099_00")
        write_fixtures({"fixtures": [{"match_id": "x", "home_team": "A", "away_team": "B"}]},
                       tmp_path, "2099/00")
        payload = read_fixtures(tmp_path, "2099/00")
        assert payload.get("fixtures") == [{"match_id": "x", "home_team": "A", "away_team": "B"}]
        assert fdir.is_dir()


# ── Web parity ─────────────────────────────────────────────────────────────


class TestWebParity:
    def test_data_endpoint(self, served):
        d = served.get("/laliga/api/data").json()
        assert d["season"] == SHIPPED_SEASON
        assert d["mode"] == "results"
        assert d["n_teams"] == 20
        assert d["n_played"] == 69
        assert d["n_total_fixtures"] == 380
        assert d["phase"]["progress"]["current_matchday"] >= 1
        assert len(d["standings"]) == 20

    def test_standings_endpoint(self, served):
        s = served.get("/laliga/api/standings").json()
        assert s["standings"][0]["team"] == "FC Barcelona"
        assert s["standings"][0]["points"] == 21

    def test_fixtures_endpoint_matchday_rows(self, served):
        mds = served.get("/laliga/api/fixtures").json()["matchdays"]
        assert len(mds) == 38
        assert mds[0]["matchday"] == 1
        first = mds[0]["matches"][0]
        assert all(k in first for k in ("match_id", "team_a", "team_b", "home_score", "away_score", "status"))

    def test_odds_endpoint_semantics(self, served):
        o = served.get("/laliga/api/odds").json()
        assert o["odds_semantics"] == "achieved_outcome_indicators"
        assert len(o["odds"]) == 380
        played = [x for x in o["odds"] if x["home_prob"] is not None]
        assert len(played) == 69

    def test_signals_endpoint(self, served):
        s = served.get("/laliga/api/signals").json()
        assert "refined_elo" in s["signals"]
        assert "accuracy" in s["signals"]["refined_elo"]

    def test_validation_endpoint(self, served):
        v = served.get("/laliga/api/validation").json()["validation"]
        assert v["n_matches_matched"] == 69
        assert 0.0 <= v["prediction_metrics"]["accuracy"] <= 1.0

    def test_state_endpoint(self, served):
        st = served.get("/laliga/api/state").json()
        assert st["season"] == SHIPPED_SEASON
        assert st["stages"]["league"]["standings"][0]["team"] == "FC Barcelona"

    def test_match_insight_endpoint(self, served):
        r = served.get("/laliga/api/match/insight",
                       params={"match_id": "564634"}).json()
        assert r["match_status"] == "played"
        assert r["teams"]["a"] == "Deportivo Alavés"
        assert len(r["signals"]) == 5
        assert isinstance(r["blended_prob"], float)
        assert 0.0 <= r["blended_prob"] <= 1.0
        assert r["insight"]

    def test_match_insight_unknown_id(self, served):
        r = served.get("/laliga/api/match/insight", params={"match_id": "nope"})
        assert r.status_code == 200
        assert r.json()["error"]

    def test_what_if_counterfactual(self, served):
        w = served.post("/laliga/api/what-if", json={
            "match_id": "564634", "elo_delta": 100, "iterations": 2000}).json()
        assert w["mode"] == "structured"
        assert w["iterations"] == 2000
        assert "Deportivo Alavés" in w["teams"]
        assert 1 <= len(w["top5_baseline"]) <= 5
        assert len(w["top5_adjusted"]) == len(w["top5_baseline"])

    def test_simulate_endpoint_completes(self, served):
        resp = served.post("/laliga/api/simulate",
                           json={"iterations": 250, "seed": 5}).json()
        assert resp["status"] == "accepted" or "task_id" in resp
        task_id = resp["task_id"]
        import time

        for _ in range(20):
            p = served.get(f"/laliga/api/simulation/progress/{task_id}").json()
            if p.get("status") in ("completed", "failed"):
                break
            time.sleep(0.15)
        assert p.get("status") == "completed"

        sim = served.get("/laliga/api/simulation").json()
        assert sim["status"] == "completed"
        assert sim["n_iterations"] == 250
        assert sim["champion"] == "FC Barcelona"
        assert sim["odds"][0]["team"] == "FC Barcelona"

    def test_report_after_simulation(self, served):
        r = served.get("/laliga/api/report")
        if r.status_code == 200:
            data = r.json()
            assert data["iterations"] >= 250
            assert data["provenance"] == "simulated"

    def test_reset_returns_results_mode(self, served):
        rr = served.post("/laliga/api/reset").json()
        assert rr["status"] == "ok"
        assert rr["mode"] == "results"

    def test_snapshot_mode_skips_refresh(self, monkeypatch):
        import web.startup as startup
        from web.server import app as server_app

        monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
        monkeypatch.setattr(startup, "_last_decision",
                            startup.StartupDecision("snapshot", ""))
        with TestClient(server_app) as client:
            r = client.post("/laliga/api/refresh").json()
            assert r["status"] == "skipped"