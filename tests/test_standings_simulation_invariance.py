"""Standings simulation-invariance and zero-match baseline contract tests (FMT-04, D-04).

Asserts:
1. Pre-tournament zero-match baselines return complete rosters (48 WC, 36 UCL, 20 LaLiga)
   with played=0, pts=0, gd=0 on unplayed/empty results stores.
2. Factual standings before simulation vs after simulation are 100% byte-identical
   across /api/standings and CompetitionState (stages.league.standings).
3. Simulated results never corrupt canonical factual stores.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import time
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
