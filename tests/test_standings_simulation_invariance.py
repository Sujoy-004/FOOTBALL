"""Standings simulation-invariance and zero-match baseline contract tests (FMT-04, D-04).

Asserts:
1. Pre-tournament zero-match baselines return complete rosters (48 WC, 36 UCL, 20 LaLiga)
   with played=0, pts=0, gd=0 on unplayed/empty results stores.
2. Factual standings before simulation vs after simulation are 100% byte-identical
   across /api/standings and CompetitionState (stages.league.standings).
3. Simulated results never corrupt canonical factual stores.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import time
from collections.abc import Sequence
from typing import Any

import pytest
from starlette.testclient import TestClient

import web.laliga_app as laliga_mod
import web.ucl_app as ucl_mod
import web.wc_app as wc_mod
from web.derived import holder
from web.laliga_app import laliga_app as laliga_app
from web.ucl_app import ucl_app as ucl_app
from web.wc_app import wc_app as wc_app


def _get_ucl_stages_standings(client: TestClient) -> list[dict[str, Any]]:
    data = client.get("/api/data").json()
    if "stages" in data and "league" in data["stages"]:
        return data["stages"]["league"]["standings"]
    bracket = client.get("/api/bracket").json()
    return bracket["stages"]["league"]["standings"]


def _get_laliga_stages_standings(client: TestClient) -> list[dict[str, Any]]:
    data = client.get("/api/data").json()
    if "stages" in data and "league" in data["stages"]:
        return data["stages"]["league"]["standings"]
    state = client.get("/api/state").json()
    return state["stages"]["league"]["standings"]


def _dir_hashes(directory: pathlib.Path, filenames: Sequence[str]) -> dict[str, str]:
    hashes = {}
    for name in filenames:
        p = directory / name
        if p.exists():
            hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes


def _run_simulation(
    client: TestClient,
    sim_url: str = "/api/simulate",
    progress_url: str = "/api/simulation/progress/",
    iterations: int = 2,
    seed: int = 42,
    timeout: float = 15.0,
) -> dict[str, Any]:
    res = client.post(sim_url, json={"iterations": iterations, "seed": seed})
    assert res.status_code == 200, f"POST {sim_url} failed: {res.text}"
    body = res.json()
    if body.get("status") == "not_needed":
        return body

    task_id = body.get("task_id")
    assert task_id, f"Expected task_id in simulation response, got: {body}"

    t0 = time.time()
    while time.time() - t0 < timeout:
        p_res = client.get(f"{progress_url}{task_id}")
        assert p_res.status_code == 200, f"GET {progress_url}{task_id} failed: {p_res.text}"
        p_body = p_res.json()
        status = p_body.get("status")
        if status in ("completed", "failed"):
            assert status == "completed", f"Simulation failed with error: {p_body.get('error')}"
            return p_body
        time.sleep(0.05)

    raise TimeoutError(f"Simulation {task_id} did not complete within {timeout}s")


class TestZeroMatchStandingsBaselines:
    """Pre-tournament zero-match baseline contracts across all three competitions."""

    def test_wc_zero_match_standings_baseline(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
        """World Cup: 48 teams across 12 groups (A-L), 4 per group, all with 0 played/pts/gd."""
        wc_tmp = tmp_path / "wc"
        wc_tmp.mkdir()
        for fname in ("teams.json", "groups.json", "bracket.json", "annex_c.json"):
            shutil.copy(wc_mod.DATA_DIR / fname, wc_tmp / fname)
        (wc_tmp / "played.json").write_text("{}", encoding="utf-8")
        (wc_tmp / "played_groups.json").write_text("{}", encoding="utf-8")

        monkeypatch.setattr(wc_mod, "DATA_DIR", wc_tmp)
        import competitions.worldcup.src.overview as wc_ov
        monkeypatch.setattr(wc_ov, "DATA_DIR", wc_tmp)

        holder.publish_data("worldcup", wc_ov.compute_overview(), "results", wc_mod._observed_stamp())

        with TestClient(wc_app) as client:
            res = client.get("/api/standings")
            assert res.status_code == 200
            standings = res.json()["standings"]

            assert len(standings) == 48, f"Expected 48 teams, got {len(standings)}"
            by_group: dict[str, list[dict]] = {}
            for row in standings:
                by_group.setdefault(row["group"], []).append(row)

            expected_groups = [chr(ord("A") + i) for i in range(12)]
            assert sorted(by_group.keys()) == expected_groups

            for grp, teams in by_group.items():
                assert len(teams) == 4, f"Group {grp} must contain exactly 4 teams"
                positions = [t["position"] for t in teams]
                assert sorted(positions) == [1, 2, 3, 4]
                for t in teams:
                    assert t["played"] == 0
                    assert t["pts"] == 0
                    assert t["gd"] == 0
                    assert t["gs"] == 0
                    assert t["ga"] == 0
                    assert t["position"] in (1, 2, 3, 4)

    def test_ucl_zero_match_standings_baseline(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
        """UCL: 36 clubs in Swiss table with played=0, pts=0, gd=0 in /api/standings and stages.league.standings."""
        ucl_tmp = tmp_path / "ucl"
        shutil.copytree(ucl_mod.DATA_DIR, ucl_tmp, dirs_exist_ok=True)
        res_path = ucl_tmp / "seasons" / "2026_27" / "results.json"
        res_path.write_text(json.dumps({"schema": 1, "season": "2026/27", "matches": []}), encoding="utf-8")
        (ucl_tmp / "current.json").write_text(
            json.dumps({"season": "2026/27", "basis": "draw", "provider": "ucl.draw.2026_27"}),
            encoding="utf-8",
        )

        monkeypatch.setattr(ucl_mod, "DATA_DIR", ucl_tmp)
        ucl_data = ucl_mod.compute_all()
        holder.publish_data("ucl", ucl_data, "results", ucl_mod._observed_stamp())

        with TestClient(ucl_app) as client:
            s_res = client.get("/api/standings")
            assert s_res.status_code == 200
            standings = s_res.json()["standings"]

            assert len(standings) == 36, f"Expected 36 Swiss clubs, got {len(standings)}"
            for i, row in enumerate(standings, 1):
                assert row["position"] == i
                assert row["played"] == 0
                assert row["pts"] == 0
                assert row["gd"] == 0

            # CompetitionState / stages.league.standings
            league_standings = _get_ucl_stages_standings(client)
            assert len(league_standings) == 36
            for i, row in enumerate(league_standings, 1):
                assert row["position"] == i
                assert row["played"] == 0
                assert row["pts"] == 0
                assert row["gd"] == 0

            data = client.get("/api/data").json()
            assert data["n_teams"] == 36
            assert len(data["all_teams"]) == 36

    def test_laliga_zero_match_standings_baseline(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
        """LaLiga: 20 clubs in table with played=0, points=0, goal_diff=0 and correct qualification/relegation zones."""
        laliga_tmp = tmp_path / "laliga"
        shutil.copytree(laliga_mod.DATA_DIR, laliga_tmp, dirs_exist_ok=True)
        res_path = laliga_tmp / "seasons" / "2026_27" / "results.json"
        res_path.write_text(
            json.dumps({"provider": "FootballDataOrgProvider", "error": None, "matches": []}),
            encoding="utf-8",
        )

        monkeypatch.setattr(laliga_mod, "DATA_DIR", laliga_tmp)
        import competitions.laliga.src.pipeline as laliga_pl
        monkeypatch.setattr(laliga_pl, "DATA_DIR", laliga_tmp)

        laliga_data = laliga_mod.compute_all()
        holder.publish_data("laliga", laliga_data, "results", laliga_mod._observed_stamp())

        with TestClient(laliga_app) as client:
            s_res = client.get("/api/standings")
            assert s_res.status_code == 200
            standings = s_res.json()["standings"]

            assert len(standings) == 20, f"Expected 20 clubs, got {len(standings)}"
            for i, row in enumerate(standings, 1):
                assert row["position"] == i
                assert row["played"] == 0
                assert (row.get("points") == 0) or (row.get("pts") == 0)
                assert (row.get("goal_diff") == 0) or (row.get("gd") == 0)

            # Zone checks: 1 champion, 2-4 ucl, 5 uel, 6 uecl, 7-17 safe, 18-20 relegation
            assert standings[0]["zone"] == "champion"
            for r in standings[1:4]:
                assert r["zone"] == "ucl"
            assert standings[4]["zone"] == "uel"
            assert standings[5]["zone"] == "uecl"
            for r in standings[6:17]:
                assert r["zone"] == "safe"
            for r in standings[17:20]:
                assert r["zone"] == "relegation"

            # CompetitionState / stages.league.standings
            league_standings = _get_laliga_stages_standings(client)
            assert len(league_standings) == 20
            for i, row in enumerate(league_standings, 1):
                assert row["position"] == i
                assert row["played"] == 0
                assert (row.get("points") == 0) or (row.get("pts") == 0)
                assert (row.get("goal_diff") == 0) or (row.get("gd") == 0)


class TestStandingsSimulationInvariance:
    """Simulation-toggle byte-identical standings invariance contract across all three competitions (D-04)."""

    def test_wc_simulation_standings_invariance(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
        """World Cup /api/standings JSON is 100% byte-identical before vs after POST /api/simulate."""
        wc_tmp = tmp_path / "wc"
        wc_tmp.mkdir()
        for fname in ("teams.json", "groups.json", "bracket.json", "annex_c.json", "played_groups.json"):
            shutil.copy(wc_mod.DATA_DIR / fname, wc_tmp / fname)
        # Empty played.json leaves unplayed knockout matches so simulation is eligible
        (wc_tmp / "played.json").write_text("{}", encoding="utf-8")

        monkeypatch.setattr(wc_mod, "DATA_DIR", wc_tmp)
        import competitions.worldcup.src.overview as wc_ov
        monkeypatch.setattr(wc_ov, "DATA_DIR", wc_tmp)

        holder.publish_data("worldcup", wc_ov.compute_overview(), "results", wc_mod._observed_stamp())

        factual_files = ("teams.json", "groups.json", "bracket.json", "annex_c.json", "played.json", "played_groups.json")
        hashes_before = _dir_hashes(wc_tmp, factual_files)

        with TestClient(wc_app) as client:
            before_json = json.dumps(client.get("/api/standings").json()["standings"], sort_keys=True)
            _run_simulation(client)
            after_json = json.dumps(client.get("/api/standings").json()["standings"], sort_keys=True)
            assert before_json == after_json, "World Cup /api/standings mutated after simulation"

        hashes_after = _dir_hashes(wc_tmp, factual_files)
        assert hashes_before == hashes_after, "World Cup canonical factual stores were modified by simulation"

    def test_ucl_simulation_standings_invariance(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
        """UCL /api/standings and stages.league.standings are 100% byte-identical before vs after POST /api/simulate."""
        ucl_tmp = tmp_path / "ucl"
        shutil.copytree(ucl_mod.DATA_DIR, ucl_tmp, dirs_exist_ok=True)
        (ucl_tmp / "snapshot.json").unlink(missing_ok=True)

        monkeypatch.setattr(ucl_mod, "DATA_DIR", ucl_tmp)
        ucl_data = ucl_mod.compute_all()
        holder.publish_data("ucl", ucl_data, "results", ucl_mod._observed_stamp())

        season_results = ucl_tmp / "seasons" / "2026_27" / "results.json"
        season_fixtures = ucl_tmp / "seasons" / "2026_27" / "fixtures.json"
        hashes_before = {
            "results": hashlib.sha256(season_results.read_bytes()).hexdigest() if season_results.exists() else "",
            "fixtures": hashlib.sha256(season_fixtures.read_bytes()).hexdigest() if season_fixtures.exists() else "",
        }

        with TestClient(ucl_app) as client:
            before_api = json.dumps(client.get("/api/standings").json()["standings"], sort_keys=True)
            before_state = json.dumps(_get_ucl_stages_standings(client), sort_keys=True)

            _run_simulation(client)

            after_api = json.dumps(client.get("/api/standings").json()["standings"], sort_keys=True)
            after_state = json.dumps(_get_ucl_stages_standings(client), sort_keys=True)

            assert before_api == after_api, "UCL /api/standings mutated after simulation"
            assert before_state == after_state, "UCL stages.league.standings mutated after simulation"

        hashes_after = {
            "results": hashlib.sha256(season_results.read_bytes()).hexdigest() if season_results.exists() else "",
            "fixtures": hashlib.sha256(season_fixtures.read_bytes()).hexdigest() if season_fixtures.exists() else "",
        }
        assert hashes_before == hashes_after, "UCL canonical factual stores were modified by simulation"

    def test_laliga_simulation_standings_invariance(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
        """LaLiga /api/standings and stages.league.standings are 100% byte-identical before vs after POST /api/simulate."""
        laliga_tmp = tmp_path / "laliga"
        shutil.copytree(laliga_mod.DATA_DIR, laliga_tmp, dirs_exist_ok=True)
        (laliga_tmp / "snapshot.json").unlink(missing_ok=True)

        monkeypatch.setattr(laliga_mod, "DATA_DIR", laliga_tmp)
        import competitions.laliga.src.pipeline as laliga_pl
        monkeypatch.setattr(laliga_pl, "DATA_DIR", laliga_tmp)

        laliga_data = laliga_mod.compute_all()
        holder.publish_data("laliga", laliga_data, "results", laliga_mod._observed_stamp())

        season_results = laliga_tmp / "seasons" / "2026_27" / "results.json"
        season_fixtures = laliga_tmp / "seasons" / "2026_27" / "fixtures.json"
        hashes_before = {
            "results": hashlib.sha256(season_results.read_bytes()).hexdigest() if season_results.exists() else "",
            "fixtures": hashlib.sha256(season_fixtures.read_bytes()).hexdigest() if season_fixtures.exists() else "",
        }

        with TestClient(laliga_app) as client:
            before_api = json.dumps(client.get("/api/standings").json()["standings"], sort_keys=True)
            before_state = json.dumps(_get_laliga_stages_standings(client), sort_keys=True)

            _run_simulation(client)

            after_api = json.dumps(client.get("/api/standings").json()["standings"], sort_keys=True)
            after_state = json.dumps(_get_laliga_stages_standings(client), sort_keys=True)

            assert before_api == after_api, "LaLiga /api/standings mutated after simulation"
            assert before_state == after_state, "LaLiga stages.league.standings mutated after simulation"

        hashes_after = {
            "results": hashlib.sha256(season_results.read_bytes()).hexdigest() if season_results.exists() else "",
            "fixtures": hashlib.sha256(season_fixtures.read_bytes()).hexdigest() if season_fixtures.exists() else "",
        }
        assert hashes_before == hashes_after, "LaLiga canonical factual stores were modified by simulation"
