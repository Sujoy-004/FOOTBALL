"""Exchange 3: match-insight tie enrichment against the frozen contract.

On the completed real season:
- final_01 is a single MATCH with score-derived aggregate and penalty
  shootout passthrough;
- qf_01 is a two-legged TIE whose historical record is aggregate-only,
  so it carries the exact availability note;
- a league row keeps the plain "match" shape with no tie fields;
- ?context=simulated flips ONLY provenance;
- an unresolved knockout slot in a KO-less tmp dataset errors honestly
  instead of returning 500.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"

AGGREGATE_ONLY_NOTE = (
    "Aggregate-only historical record; per-leg scores not available.")


@pytest.fixture
def snapshot_mode(monkeypatch):
    import web.startup as startup
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield
    startup._last_decision = None


class TestInsightTiesRealData:
    def test_final_is_a_match_with_pens_passthrough(self, snapshot_mode):
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            ins = client.get(
                "/api/match/insight?match_id=final_01").json()
            assert "error" not in ins
            assert ins["kind"] == "match"
            assert ins["legs"] is None
            assert ins["aggregate"] == {"a": 1, "b": 1}
            assert ins["pens"]["played"] is True
            assert ins["pens"]["winner"] == "PSG"
            assert ins["pens"]["score"] == "4-3"
            assert ins["availability_note"] is None
            assert ins["what_if"]["eligible"] is True
            assert ins["what_if"]["reason"] is None
            assert ins["provenance"] == "manual"

    def test_qf_is_aggregate_only_tie_with_exact_note(self, snapshot_mode):
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            ins = client.get("/api/match/insight?match_id=qf_01").json()
            assert "error" not in ins
            assert ins["kind"] == "tie"
            assert ins["legs"] is None
            assert ins["aggregate"] == {"a": 0, "b": 1}
            assert ins["availability_note"] == AGGREGATE_ONLY_NOTE
            assert ins["what_if"]["eligible"] is True
            assert ins["provenance"] == "manual"

    def test_league_row_keeps_plain_match_shape(self, snapshot_mode):
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            lmd = client.get("/api/bracket").json()["league_matchdays"]
            first_md = next(iter(lmd))
            mid = lmd[first_md][0]["match_id"]
            ins = client.get(f"/api/match/insight?match_id={mid}").json()
            assert "error" not in ins
            assert ins["kind"] == "match"
            assert ins["legs"] is None
            assert ins["aggregate"] is None
            assert ins["pens"] is None
            assert ins["et"] is None
            assert ins["availability_note"] is None
            assert ins["what_if"]["eligible"] is True
            # Results-ledger rows are official by domain rule.
            assert ins["provenance"] == "official"
            assert ins["played"] is True

    def test_simulated_context_flips_only_provenance(self, snapshot_mode):
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            real = client.get("/api/match/insight?match_id=qf_01").json()
            sim = client.get(
                "/api/match/insight?match_id=qf_01&context=simulated").json()
            assert sim["provenance"] == "simulated"
            assert real["provenance"] != "simulated"
            stripped_real = {k: v for k, v in real.items() if k != "provenance"}
            stripped_sim = {k: v for k, v in sim.items() if k != "provenance"}
            assert stripped_sim == stripped_real


class TestInsightUnresolvedSlot:
    def test_missing_ko_store_slot_errors_without_500(
            self, snapshot_mode, tmp_path, monkeypatch):
        import web.ucl_app as app
        from web.ucl_app import ucl_app

        # Canonical skeleton: rules/pairings present so the bracket state can
        # build, but knockout_results.json absent -> every slot unresolved.
        for f in ("fixtures.json", "team_aliases.json", "bootstrap/league_results_2025_26.json",
                  "bracket_rules.json", "playoff_pairings.json"):
            src = UCL_DATA / f
            dst = tmp_path / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        # Also copy as results.json for the app
        shutil.copy(UCL_DATA / "bootstrap" / "league_results_2025_26.json", tmp_path / "results.json")
        monkeypatch.setattr(app, "DATA_DIR", tmp_path)

        with TestClient(ucl_app) as client:
            resp = client.get("/api/match/insight?match_id=r16_01")
            assert resp.status_code == 200
            body = resp.json()
            # Honest unresolved handling: structured error, no fabrication.
            assert body.get("error") == "match teams not set"
