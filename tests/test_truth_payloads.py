"""Exchange 2: truthful API payload contract (served-path tests).

Boots both sub-apps in forced-snapshot mode and asserts the additive truth
fields: explicit match status, provenance, probability availability, and
authoritative competition phase. Also locks the standings unification.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def snapshot_mode(monkeypatch, tmp_path):
    import shutil
    import web.startup as startup
    import web.ucl_app as app
    from competitions.ucl.src.seasons import set_current_season
    src = ROOT / "competitions" / "ucl" / "data"
    dst = tmp_path / "ucl_data"
    shutil.copytree(src, dst)
    set_current_season(dst, "2025/26", basis="pointer_local", provider=None)
    monkeypatch.setattr(app, "DATA_DIR", dst)
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield
    startup._last_decision = None


class TestUCLTruthPayloads:
    def test_league_rows_carry_status_winner_provenance(self):
        from competitions.ucl.src.pipeline import (
            build_league_matchdays, load_results)
        results = load_results(ROOT / "competitions" / "ucl" / "data")
        mds = build_league_matchdays(results)
        first_md = next(iter(mds.values()))
        row = first_md[0]
        assert row["status"] == "played"
        assert row["provenance"] == "official"
        assert isinstance(row["winner"], (str, type(None)))
        hs, aw = row["home_score"], row["away_score"]
        if hs > aw:
            assert row["winner"] == row["team_a"]
        elif aw > hs:
            assert row["winner"] == row["team_b"]

    def test_ko_entries_carry_status(self):
        from competitions.ucl.src.pipeline import build_deterministic_bracket
        out = build_deterministic_bracket(
            {"rounds": {"FINAL": [{"team_a": "A", "team_b": "B",
                                   "score_a": 2, "score_b": 1,
                                   "winner": "A"}]}},
            [], str(ROOT / "competitions" / "ucl" / "data"))
        final_entry = out["bracket_rounds"]["FINAL"][0]
        assert final_entry["status"] == "played"
        assert final_entry["provenance"] == "official"

    def test_ucl_insight_played_league_match_reports_truthfully(self, snapshot_mode):
        """Regression: league matches used to report played=false because the
        ledger rows have no winner key."""
        from web.ucl_app import ucl_app
        with TestClient(ucl_app) as client:
            data = client.get("/api/data").json()
            # Authoritative phase replaces client-side stage inference; the
            # exact value follows whatever the on-disk knockout evidence is
            # (backfilled history vs empty store), so assert consistency
            # rather than pinning one dataset era.
            phase = data.get("phase", {})
            ko_store = phase.get("stores", {}).get("knockout_results")
            if ko_store == "available":
                assert phase.get("phase") in ("knockout", "completed")
            else:
                assert phase.get("phase") == "league_stage_complete"

            lmd = client.get("/api/bracket").json()["league_matchdays"]
            first_md = next(iter(lmd))
            mid = lmd[first_md][0]["match_id"]
            insight = client.get(f"/api/match/insight?match_id={mid}").json()
            assert "error" not in insight
            assert insight["match_status"] == "played"
            assert insight["played"] is True
            assert insight["score"]["home"] is not None
            assert insight["prob_available"] is True
            assert isinstance(insight["blended_prob"], float)
            a, b, c = (insight["outcome_distribution"][k] for k in
                       ("a_win", "draw", "b_win"))
            assert abs(a + b + c - 1.0) <= 0.001

    def test_wc_phase_and_no_simulation(self, snapshot_mode):
        from web.wc_app import cache, compute_overview, wc_app
        # The parent server assigns wc cache at boot; mirror that here.
        cache.update(compute_overview())
        with TestClient(wc_app) as client:
            overview = client.get("/api/overview").json()
            assert overview["has_simulation"] is False
            assert overview["phase"]["phase"] == "completed"
            assert overview["phase"]["champion"]
            assert set(overview["phase"]["stores"].values()) <= {
                "available", "empty", "missing", "unavailable"}

            full = client.get("/api/bracket/full").json()
            sample = full["rounds"]["R32"][0]
            for key in ("status", "provenance", "prob_available"):
                assert key in sample

    def test_unavailable_probability_is_not_fabricated(self):
        """compute_full_bracket marks prob availability instead of silently
        defaulting; TBD slots get status=scheduled."""
        from web.wc_app import _prob_availability
        assert _prob_availability("", "", {}) == (False, "slot_unresolved")
        assert _prob_availability("Ghost A", "Ghost B", {}) == (
            False, "no_elo_rating")


class TestStandingsUnification:
    def test_deterministic_delegates_to_swiss_chain(self):
        from competitions.ucl.src.pipeline import compute_deterministic_standings
        from competitions.ucl.src.groups import compute_swiss_standings
        from competitions.ucl.src.pipeline import load_results

        results = load_results(ROOT / "competitions" / "ucl" / "data")
        det = compute_deterministic_standings(results)

        matches = {}
        for m in results:
            matches[m["match_id"]] = {
                "team_a": m["team_a"], "team_b": m["team_b"],
                "score_a": m["home_score"], "score_b": m["away_score"],
                "yellow_cards_a": 0, "red_cards_a": 0,
                "yellow_cards_b": 0, "red_cards_b": 0,
            }
        swiss = compute_swiss_standings(matches)
        assert [e["team"] for e in det] == [e["team"] for e in swiss]

    def test_display_fields_survive_unification(self):
        from competitions.ucl.src.pipeline import (
            compute_deterministic_standings, load_results)
        results = load_results(ROOT / "competitions" / "ucl" / "data")
        top = compute_deterministic_standings(results)[0]
        for key in ("position", "team", "pts", "gd", "gs", "ga",
                    "wins", "draws", "losses", "zone"):
            assert key in top, f"frontend field {key} lost in unification"

    def test_full_chain_breaks_weak_ties(self):
        """Two teams identical on the weak six criteria separate via
        opponent points (step 6) under the unified chain."""
        from competitions.ucl.src.pipeline import compute_deterministic_standings
        results = []
        mid = 0

        def add(ta, tb, hs, aw):
            nonlocal mid
            mid += 1
            results.append({"match_id": f"T{mid:03d}", "team_a": ta,
                            "team_b": tb, "home_score": hs, "away_score": aw})

        # Group X: A and B beat C/D identically and draw each other.
        add("A", "B", 0, 0)
        add("B", "A", 0, 0)
        add("A", "C", 1, 0); add("B", "D", 1, 0)
        add("A", "D", 1, 0); add("B", "C", 1, 0)
        add("C", "A", 0, 1); add("D", "B", 0, 1)
        add("C", "A", 0, 1); add("D", "B", 0, 1)
        # A's opponents collect more points than B's opponents.
        add("C", "D", 3, 0); add("D", "E", 1, 0); add("C", "E", 2, 1)
        add("E", "C", 0, 1)

        st = compute_deterministic_standings(results)
        pos = {e["team"]: e["position"] for e in st}
        assert pos["A"] != pos["B"], "weak-tied teams must separate"


class TestWCInsightTruth:
    def test_compute_match_insight_truth_fields(self, snapshot_mode):
        from web.wc_app import cache, compute_overview
        from competitions.worldcup.src.insight import compute_match_insight
        cache.update(compute_overview())
        fb = cache["full_bracket"]
        played_mid = None
        for ms in fb["rounds"].values():
            for m in ms:
                if m["played"] and m["team_a"]:
                    played_mid = m["match_id"]
                    break
            if played_mid:
                break
        payload = compute_match_insight(played_mid, fb, {}, {})
        assert payload["match_status"] == "played"
        assert payload["provenance"] == "official"
        assert payload["blended_prob"] is not None
