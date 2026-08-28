"""Offline tests for competitions.ucl.src.ingest + competitions.ucl.backfill.

Covers the Exchange 2 Phase 9 checklist: skeleton creation from an empty
store, idempotency, no duplicate legs, leg preservation, ET and penalty
capture, winner resolution (including shootouts), backfill reproduction of
the bootstrap bracket (8/8/4/2/1 + champion PSG), IngestReport counter
invariants, v1->v2 upgrade-on-read, and atomic writes without temp-file
leftovers.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from competitions.ucl.backfill import main as backfill_main
from competitions.ucl.src.ingest import (
    BACKFILL_SOURCE_TAG,
    ingest_ucl_events,
    load_knockout_store,
)

REPO_DATA = Path(__file__).resolve().parents[1] / "data"

# Club01 is the strongest team; standings position p == Club{p:02d}.
TEAM_NAMES = [f"Club{i:02d}" for i in range(1, 25)]


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_data_dir(tmp_path: Path) -> Path:
    dp = tmp_path / "data"
    dp.mkdir(parents=True, exist_ok=True)
    # Single round-robin schedule (one fixture per unordered pair, mirroring
    # the real fixtures.json shape) so every synthetic league event has a
    # fixture target while fixtures.json stays the schedule authority.
    matchdays, md_num = [], 0
    for i in range(len(TEAM_NAMES)):
        for j in range(i + 1, len(TEAM_NAMES)):
            md_num += 1
            # Weaker team (higher index) hosts; stronger side wins on the road.
            matchdays.append([{
                "match_id": f"MD{md_num:04d}",
                "team_a": TEAM_NAMES[j], "team_b": TEAM_NAMES[i],
            }])
    fixtures = {
        "schedule": {
            "teams": [{"name": t} for t in TEAM_NAMES],
            "matchdays": matchdays,
        }
    }
    (dp / "fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")
    (dp / "results.json").write_text('{"matches": []}', encoding="utf-8")
    (dp / "knockout_results.json").write_text('{"matches": {}}', encoding="utf-8")
    shutil.copy(REPO_DATA / "playoff_pairings.json", dp / "playoff_pairings.json")
    shutil.copy(REPO_DATA / "bracket_rules.json", dp / "bracket_rules.json")
    return dp


def _league_events() -> list[dict]:
    """Single round-robin where the stronger (lower index) team always wins."""
    events = []
    for i in range(len(TEAM_NAMES)):
        for j in range(i + 1, len(TEAM_NAMES)):
            # Weaker team hosts; stronger side wins 0-2.
            events.append({
                "home_team": TEAM_NAMES[j], "away_team": TEAM_NAMES[i],
                "home_score": 0, "away_score": 2,
                "status": "finished", "stage": "LEAGUE_STAGE",
            })
    return events


def _ko_event(stage_token, home, away, hs, aws, **extra) -> dict:
    ev = {
        "home_team": home, "away_team": away,
        "home_score": hs, "away_score": aws,
        "status": "finished", "stage": stage_token,
    }
    ev.update(extra)
    return ev


# ── ingest: creation, idempotency, legs ─────────────────────────────────────


def test_empty_store_with_real_input_creates_entries(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events() + [
        _ko_event("PLAYOFFS", "Club24", "Club09", 1, 2, event_date="2026-02-17"),
        _ko_event("PLAYOFFS", "Club09", "Club24", 3, 0, event_date="2026-02-24"),
    ]
    report = ingest_ucl_events(events, dp, "TestProvider")

    doc = load_knockout_store(dp)
    assert doc["schema"] == 2
    assert len(doc["matches"]["playoff"]) == 8

    tie1 = next(t for t in doc["matches"]["playoff"] if t["match_id"] == "playoff_t1")
    # Seeded Club09 (position 9) hosts leg 2 -> stored as team_b.
    assert tie1["team_a"] == "Club24" and tie1["team_b"] == "Club09"
    assert tie1["slot_sources"] == {"position_a": 9, "position_b": 24}
    assert len(tie1["legs"]) == 2
    assert tie1["legs"][0] == {"leg": 1, "home": "Club24", "away": "Club09",
                               "home_score": 1, "away_score": 2}
    assert tie1["legs"][1]["home"] == "Club09" and tie1["legs"][1]["home_score"] == 3
    assert tie1["aggregate_a"] == 1 and tie1["aggregate_b"] == 5
    assert tie1["winner"] == "Club09"
    assert tie1["status"] == "played" and tie1["provenance"] == "official"

    # R16 skeleton: seeds from top-8 zone, playoff winner propagated to slot.
    r16 = {m["match_id"]: m for m in doc["matches"]["rounds"]["R16"]}
    assert len(r16) == 8
    assert r16["r16_07"]["team_a"] == "Club07"      # home_seed=7 -> position 7
    assert r16["r16_07"]["team_b"] == "Club09"      # winner of playoff tie 1
    assert r16["r16_07"]["slot_sources"] == {"home_seed": 7, "away_playoff_tie": 1}
    assert r16["r16_01"]["team_a"] == "Club01"
    assert r16["r16_01"]["team_b"] is None          # playoff tie 7 undecided

    qf = {m["match_id"]: m for m in doc["matches"]["rounds"]["QF"]}
    assert len(qf) == 4 and all(m["team_a"] is None and m["team_b"] is None for m in qf.values())
    assert len(doc["matches"]["rounds"]["SF"]) == 2
    fin = doc["matches"]["final"]
    assert len(fin) == 1 and fin[0]["match_id"] == "final_01" and fin[0]["winner"] is None
    assert doc["matches"]["champion"] is None

    res = json.loads((dp / "results.json").read_text(encoding="utf-8"))
    assert len(res["matches"]) == 276
    assert report.finished["ingested"] == 278       # 276 league + 2 legs
    assert any(s["key"] == "playoff" and s["count"] >= 1 for s in report.stages)
    assert report.written_files


def test_repeat_ingest_is_idempotent(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events() + [
        _ko_event("PLAYOFFS", "Club18", "Club15", 2, 1),
        _ko_event("PLAYOFFS", "Club15", "Club18", 1, 1),
    ]
    ingest_ucl_events(events, dp, "TestProvider")
    results_before = (dp / "results.json").read_bytes()
    ko_before = (dp / "knockout_results.json").read_bytes()

    time.sleep(0.02)  # ensure a rewrite would stamp a different updated_at
    second = ingest_ucl_events(events, dp, "TestProvider")

    assert (dp / "results.json").read_bytes() == results_before
    assert (dp / "knockout_results.json").read_bytes() == ko_before
    assert second.written_files == []


def test_no_duplicate_legs_and_legs_preserved(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events() + [
        _ko_event("PLAYOFFS", "Club24", "Club09", 1, 2, event_date="2026-02-17"),
        _ko_event("PLAYOFFS", "Club09", "Club24", 3, 0, event_date="2026-02-24"),
    ]
    ingest_ucl_events(events, dp, "TestProvider")
    # Re-ingest only the knockout part — must not duplicate or sum legs.
    ingest_ucl_events([
        _ko_event("PLAYOFFS", "Club24", "Club09", 1, 2, event_date="2026-02-17"),
        _ko_event("PLAYOFFS", "Club09", "Club24", 3, 0, event_date="2026-02-24"),
    ], dp, "TestProvider")

    doc = load_knockout_store(dp)
    tie1 = next(t for t in doc["matches"]["playoff"] if t["tie_num"] == 1)
    assert len(tie1["legs"]) == 2
    assert [l["leg"] for l in tie1["legs"]] == [1, 2]
    scores = {(l["home"], l["away"]): (l["home_score"], l["away_score"]) for l in tie1["legs"]}
    assert scores[("Club24", "Club09")] == (1, 2)
    assert scores[("Club09", "Club24")] == (3, 0)


def test_extra_time_decides_level_aggregate(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events() + [
        # Playoff tie 7: unseeded Club18 upsets seeded Club15 -> fills r16_01 team_b.
        _ko_event("PLAYOFFS", "Club18", "Club15", 2, 1),
        _ko_event("PLAYOFFS", "Club15", "Club18", 1, 1),
        # R16 r16_01: Club01 vs Club18 — level aggregate, ET goal decides.
        _ko_event("LAST_16", "Club01", "Club18", 2, 0),
        _ko_event("LAST_16", "Club18", "Club01", 2, 0,
                  duration="EXTRA_TIME", et_home=1, et_away=0),
    ]
    report = ingest_ucl_events(events, dp, "TestProvider")

    doc = load_knockout_store(dp)
    r16 = {m["match_id"]: m for m in doc["matches"]["rounds"]["R16"]}
    entry = r16["r16_01"]
    assert entry["aggregate_a"] == 2 and entry["aggregate_b"] == 2
    assert entry["et_played"] is True
    assert entry["et_a"] == 0 and entry["et_b"] == 1   # ET goals kept separate
    assert entry["penalties_played"] is False          # never invented
    assert entry["winner"] == "Club18"
    assert entry["status"] == "played"

    # Cascade: QF slot filled from decided R16 winner, sibling stays null.
    qf = {m["match_id"]: m for m in doc["matches"]["rounds"]["QF"]}
    assert qf["qf_01"]["team_a"] == "Club18"
    assert qf["qf_01"]["team_b"] is None
    assert any(s["key"] == "knockout" and s["count"] >= 1 for s in report.stages)


def test_penalty_shootout_captured_and_decides_winner(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events() + [
        _ko_event("PLAYOFFS", "Club24", "Club09", 1, 0),
        _ko_event("PLAYOFFS", "Club09", "Club24", 1, 0,
                  duration="PENALTY_SHOOTOUT", shootout={"home": 4, "away": 3}),
    ]
    ingest_ucl_events(events, dp, "TestProvider")

    doc = load_knockout_store(dp)
    tie1 = next(t for t in doc["matches"]["playoff"] if t["tie_num"] == 1)
    assert tie1["aggregate_a"] == 1 and tie1["aggregate_b"] == 1  # level
    assert tie1["et_played"] is True                              # shootout implies ET
    assert tie1["et_a"] == 0 and tie1["et_b"] == 0
    assert tie1["penalties_played"] is True
    assert tie1["penalty_a"] == 3 and tie1["penalty_b"] == 4      # team_a/team_b view
    assert tie1["penalty_winner"] == "Club09"
    assert tie1["winner"] == "Club09"
    assert tie1["status"] == "played_pens"
    # Winner propagated downstream.
    r16 = {m["match_id"]: m for m in doc["matches"]["rounds"]["R16"]}
    assert r16["r16_07"]["team_b"] == "Club09"


def test_final_single_match_and_champion(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events()
    # Drive the whole bracket with synthetic two-legged results so SF winners exist.
    playoff_pairs = {
        1: ("Club24", "Club09"), 2: ("Club23", "Club10"), 3: ("Club22", "Club11"),
        4: ("Club21", "Club12"), 5: ("Club20", "Club13"), 6: ("Club19", "Club14"),
        7: ("Club18", "Club15"), 8: ("Club17", "Club16"),
    }
    for tn, (unseeded, seeded) in playoff_pairs.items():
        events.append(_ko_event("PLAYOFFS", unseeded, seeded, 2, 0))
        events.append(_ko_event("PLAYOFFS", seeded, unseeded, 2, 1))  # unseeded wins
    r16_pairs = {
        "r16_01": ("Club01", "Club18"), "r16_02": ("Club02", "Club17"),
        "r16_03": ("Club03", "Club20"), "r16_04": ("Club04", "Club19"),
        "r16_05": ("Club05", "Club22"), "r16_06": ("Club06", "Club21"),
        "r16_07": ("Club07", "Club24"), "r16_08": ("Club08", "Club23"),
    }
    for mid, (seed, challenger) in r16_pairs.items():
        events.append(_ko_event("LAST_16", seed, challenger, 3, 0))
        events.append(_ko_event("LAST_16", challenger, seed, 1, 2))   # seed wins
    qf_pairs = {
        "qf_01": ("Club01", "Club02"), "qf_02": ("Club03", "Club04"),
        "qf_03": ("Club05", "Club06"), "qf_04": ("Club07", "Club08"),
    }
    for mid, (ta, tb) in qf_pairs.items():
        events.append(_ko_event("QUARTER_FINALS", ta, tb, 2, 0))
        events.append(_ko_event("QUARTER_FINALS", tb, ta, 1, 3))
    sf_pairs = {"sf_01": ("Club01", "Club03"), "sf_02": ("Club05", "Club07")}
    for mid, (ta, tb) in sf_pairs.items():
        events.append(_ko_event("SEMI_FINALS", ta, tb, 2, 1))
        events.append(_ko_event("SEMI_FINALS", tb, ta, 0, 2))
    events.append(_ko_event("FINAL", "Club01", "Club05", 1, 1,
                            duration="PENALTY_SHOOTOUT", shootout={"home": 5, "away": 4}))

    ingest_ucl_events(events, dp, "TestProvider")

    doc = load_knockout_store(dp)
    fin = doc["matches"]["final"][0]
    assert fin["score"] == {"home": 1, "away": 1}
    assert fin["penalties_played"] is True and fin["winner"] == "Club01"
    assert fin["status"] == "played_pens"
    assert doc["matches"]["champion"] == "Club01"


# ── IngestReport counters ────────────────────────────────────────────────────


def test_report_counters_invariant(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events() + [
        _ko_event("PLAYOFFS", "Club24", "Club09", 1, 2),
        _ko_event("PLAYOFFS", "Club09", "Club24", 3, 0),
        {"home_team": "", "away_team": "Ghost FC", "home_score": 0, "away_score": 0,
         "status": "finished", "stage": "PLAYOFFS"},           # unmatchable
        _ko_event("MYSTERY_ROUND", "Club01", "Club02", 1, 0),  # unknown stage
    ]
    report = ingest_ucl_events(events, dp, "TestProvider")

    fin = report.finished
    assert set(fin) == {"received", "normalized", "ingested",
                        "skipped_unmatchable", "skipped_no_target"}
    assert fin["received"] == fin["normalized"] == fin["ingested"] + \
        fin["skipped_unmatchable"] + fin["skipped_no_target"]
    assert fin["received"] == 280
    assert fin["skipped_unmatchable"] == 1 and fin["skipped_no_target"] == 1

    payload = report.to_dict()
    assert payload["provider"] == "TestProvider"
    assert payload["attempted"] is True and payload["success"] is True
    assert payload["stale"] is False and payload["error"] is None
    keys = [s["key"] for s in payload["stages"]]
    assert keys == ["teams", "league", "playoff", "knockout", "champion"]
    assert all(set(s) == {"key", "label", "state", "count", "detail"} for s in payload["stages"])
    assert all(s["state"] in ("ok", "pending", "error", "unavailable") for s in payload["stages"])


# ── v1 -> v2 upgrade-on-read ─────────────────────────────────────────────────


def test_v1_store_upgraded_on_read_and_preserved(tmp_path):
    dp = _make_data_dir(tmp_path)
    v1 = {
        "matches": {
            "playoff": [
                {"tie_num": 1, "team_a": "Alpha", "team_b": "Beta",
                 "aggregate_a": 2, "aggregate_b": 1, "winner": "Alpha"},
            ],
            "rounds": {
                "R16": [
                    {"team_a": "Top Seed", "team_b": "Alpha",
                     "score_a": 4, "score_b": 1, "winner": "Top Seed"},
                ],
                "QF": [],
                "SF": [],
                "FINAL": [
                    {"team_a": "PSG", "team_b": "Arsenal",
                     "score_a": 1, "score_b": 1, "winner": "PSG",
                     "penalties": {"winner": "PSG", "score": "4-3"}},
                ],
            },
            "champion": "PSG",
        }
    }
    (dp / "knockout_results.json").write_text(json.dumps(v1), encoding="utf-8")

    doc = load_knockout_store(dp)
    assert doc["schema"] == 2
    assert "FINAL" not in doc["matches"]["rounds"]
    final_entry = doc["matches"]["final"][0]
    assert final_entry["score"] == {"home": 1, "away": 1}
    assert final_entry["penalties_played"] is True
    assert final_entry["penalty_winner"] == "PSG" and final_entry["penalty_score"] == "4-3"
    assert final_entry["status"] == "played_pens" and final_entry["provenance"] == "manual"
    r16 = doc["matches"]["rounds"]["R16"][0]
    assert r16["aggregate_a"] == 4 and r16["aggregate_b"] == 1  # score_* renamed
    assert doc["matches"]["champion"] == "PSG"

    # A subsequent ingest must NOT clobber pre-existing history nor re-derive
    # a skeleton over it.
    before = (dp / "knockout_results.json").read_bytes()
    ingest_ucl_events(_league_events(), dp, "TestProvider")
    after_doc = load_knockout_store(dp)
    assert after_doc["matches"]["champion"] == "PSG"
    assert after_doc["matches"]["playoff"][0]["team_a"] == "Alpha"
    if (dp / "knockout_results.json").read_bytes() != before:
        # Only acceptable change would be from real matched KO events — none here.
        pytest.fail("store rewritten without matching knockout events")


def test_atomic_write_leaves_no_temp_files(tmp_path):
    dp = _make_data_dir(tmp_path)
    events = _league_events() + [
        _ko_event("PLAYOFFS", "Club24", "Club09", 1, 2),
        _ko_event("PLAYOFFS", "Club09", "Club24", 3, 0),
    ]
    ingest_ucl_events(events, dp, "TestProvider")
    leftovers = [p.name for p in dp.iterdir() if ".tmp" in p.name]
    assert leftovers == []


# ── backfill ─────────────────────────────────────────────────────────────────


def test_backfill_reproduces_full_bracket_from_bootstrap(tmp_path):
    dp = _make_data_dir(tmp_path)
    empty_before = (dp / "knockout_results.json").read_bytes()
    shutil.copytree(REPO_DATA / "bootstrap", dp / "bootstrap")

    rc = backfill_main(["--data-dir", str(dp)])
    assert rc == 0

    doc = json.loads((dp / "knockout_results.json").read_text(encoding="utf-8"))
    m = doc["matches"]
    assert doc["schema"] == 2
    assert len(m["playoff"]) == 8
    assert len(m["rounds"]["R16"]) == 8
    assert len(m["rounds"]["QF"]) == 4
    assert len(m["rounds"]["SF"]) == 2
    assert len(m["final"]) == 1
    assert m["champion"] == "PSG"

    assert [t["match_id"] for t in m["playoff"]] == [f"playoff_t{i}" for i in range(1, 9)]
    assert all(t["provenance"] == "manual" for t in m["playoff"])
    assert all(t["legs"] is None for t in m["playoff"])
    assert m["playoff"][0]["team_a"] == "Monaco" and m["playoff"][0]["team_b"] == "PSG"
    assert m["playoff"][0]["winner"] == "PSG"
    assert m["playoff"][0]["slot_sources"] == {"position_a": 9, "position_b": 24}

    r16 = {x["match_id"]: x for x in m["rounds"]["R16"]}
    assert set(r16) == {f"r16_{i:02d}" for i in range(1, 9)}
    # Canonical chain: r16_07 receives the winner of playoff tie 1 (PSG).
    assert r16["r16_07"]["team_b"] == "PSG"
    assert r16["r16_07"]["slot_sources"] == {"home_seed": 7, "away_playoff_tie": 1}
    assert r16["r16_01"]["team_b"] == "Bodo/Glimt"   # winner of playoff tie 7
    assert all(x["provenance"] == "manual" and x["legs"] is None for x in r16.values())

    qf = {x["match_id"]: x for x in m["rounds"]["QF"]}
    assert set(qf) == {f"qf_{i:02d}" for i in range(1, 5)}
    assert qf["qf_04"]["source_matches"] == ["r16_07", "r16_08"]
    assert {qf["qf_04"]["team_a"], qf["qf_04"]["team_b"]} == {"PSG", "Liverpool"}
    sf = {x["match_id"]: x for x in m["rounds"]["SF"]}
    assert set(sf) == {"sf_01", "sf_02"}

    fin = m["final"][0]
    assert fin["match_id"] == "final_01"
    assert fin["score"] == {"home": 1, "away": 1}
    assert fin["penalties_played"] is True
    assert fin["penalty_winner"] == "PSG" and fin["penalty_score"] == "4-3"
    assert fin["winner"] == "PSG" and fin["status"] == "played_pens"
    assert fin["provenance"] == "manual"
    assert fin["source_matches"] == ["sf_01", "sf_02"]

    assert doc["meta"]["backfilled_from"] == BACKFILL_SOURCE_TAG
    assert doc["meta"]["provider"] is None
    assert doc["meta"]["updated_at"]


def test_backfill_fails_cleanly_without_bootstrap(tmp_path):
    dp = _make_data_dir(tmp_path)
    before = (dp / "knockout_results.json").read_bytes()

    rc = backfill_main(["--data-dir", str(dp)])

    assert rc == 1
    assert (dp / "knockout_results.json").read_bytes() == before  # untouched


# ── pipeline delegation ──────────────────────────────────────────────────────


class _StubProvider:
    last_error = None

    def __init__(self, raw):
        self._raw = raw

    def fetch_matches(self, competition_id="CL"):
        return list(self._raw)


def test_pipeline_fetch_live_data_delegates_to_ingest(monkeypatch, tmp_path):
    from competitions.ucl.src import pipeline

    dp = _make_data_dir(tmp_path)
    # Pre-seed league history + skeleton so the stub's playoff event has a
    # resolved slot to land in. The generated schedule contains the pair
    # (Club01, Club02), so the stub's league event resolves to that fixture.
    ingest_ucl_events(_league_events(), dp, "SeedProvider")

    stub = _StubProvider([
        {"home_team": "Club01", "away_team": "Club02", "home_score": 3, "away_score": 1,
         "status": "finished", "stage": "LEAGUE_STAGE"},
        {"home_team": "Club24", "away_team": "Club09", "home_score": 1, "away_score": 2,
         "status": "finished", "stage": "PLAYOFFS", "event_date": "2026-02-17"},
    ])
    monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: stub)

    out = pipeline.fetch_live_data(dp, "key", "", 7)

    # Legacy contract keys preserved...
    assert out["status"] == "ok"
    assert out["n_raw"] == 2
    assert out["n_updated"] == 2
    assert out["provider_name"] == "_StubProvider"
    # ...plus the structured report superset.
    rep = out["report"]
    assert rep["attempted"] is True and rep["success"] is True and rep["stale"] is False
    fin = rep["finished"]
    assert fin["received"] == fin["normalized"] == \
        fin["ingested"] + fin["skipped_unmatchable"] + fin["skipped_no_target"]
    assert set(rep["written_files"]) == {str(dp / "results.json"),
                                         str(dp / "knockout_results.json")}

    res = json.loads((dp / "results.json").read_text(encoding="utf-8"))
    # Fixture-keyed upsert (legacy semantics): scores overwritten on the
    # pre-seeded MD0001 row.
    assert {"match_id": "MD0001", "team_a": "Club02", "team_b": "Club01",
            "home_score": 3, "away_score": 1} in res["matches"]
    doc = load_knockout_store(dp)
    assert doc["schema"] == 2
    assert doc["meta"]["provider"] == "_StubProvider"
    tie1 = next(t for t in doc["matches"]["playoff"] if t["tie_num"] == 1)
    assert tie1["winner"] == "Club09"


def test_pipeline_fetch_live_data_skip_paths(monkeypatch, tmp_path):
    from competitions.ucl.src import pipeline

    monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: None)
    out = pipeline.fetch_live_data(tmp_path, "", "")
    assert out["status"] == "skip"
    assert out["report"]["attempted"] is False

    dead = _StubProvider([])
    dead.last_error = "HTTP 400: invalid token"
    monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: dead)
    out = pipeline.fetch_live_data(tmp_path, "k", "")
    assert out["status"] == "skip"
    rep = out["report"]
    assert rep["attempted"] is True and rep["success"] is False
    assert rep["stale"] is True and "invalid" in rep["error"]


# ── Exchange 5: provider-data downgrade guards ────────────────────────────────


def _make_decided_final_dir(tmp_path: Path) -> Path:
    """Create a data dir with a fully-decided final (PSG won 4-3 on pens)."""
    dp = _make_data_dir(tmp_path)
    # Drive the full bracket to get SF winners into the final slot.
    events = _league_events()
    playoff_pairs = {
        1: ("Club24", "Club09"), 2: ("Club23", "Club10"), 3: ("Club22", "Club11"),
        4: ("Club21", "Club12"), 5: ("Club20", "Club13"), 6: ("Club19", "Club14"),
        7: ("Club18", "Club15"), 8: ("Club17", "Club16"),
    }
    for tn, (unseeded, seeded) in playoff_pairs.items():
        events.append(_ko_event("PLAYOFFS", unseeded, seeded, 2, 0))
        events.append(_ko_event("PLAYOFFS", seeded, unseeded, 2, 1))
    r16_pairs = {
        "r16_01": ("Club01", "Club18"), "r16_02": ("Club02", "Club17"),
        "r16_03": ("Club03", "Club20"), "r16_04": ("Club04", "Club19"),
        "r16_05": ("Club05", "Club22"), "r16_06": ("Club06", "Club21"),
        "r16_07": ("Club07", "Club24"), "r16_08": ("Club08", "Club23"),
    }
    for mid, (seed, challenger) in r16_pairs.items():
        events.append(_ko_event("LAST_16", seed, challenger, 3, 0))
        events.append(_ko_event("LAST_16", challenger, seed, 1, 2))
    qf_pairs = {
        "qf_01": ("Club01", "Club02"), "qf_02": ("Club03", "Club04"),
        "qf_03": ("Club05", "Club06"), "qf_04": ("Club07", "Club08"),
    }
    for mid, (ta, tb) in qf_pairs.items():
        events.append(_ko_event("QUARTER_FINALS", ta, tb, 2, 0))
        events.append(_ko_event("QUARTER_FINALS", tb, ta, 1, 3))
    sf_pairs = {"sf_01": ("Club01", "Club03"), "sf_02": ("Club05", "Club07")}
    for mid, (ta, tb) in sf_pairs.items():
        events.append(_ko_event("SEMI_FINALS", ta, tb, 2, 1))
        events.append(_ko_event("SEMI_FINALS", tb, ta, 0, 2))
    events.append(_ko_event("FINAL", "Club01", "Club05", 1, 1,
                            duration="PENALTY_SHOOTOUT", shootout={"home": 4, "away": 3}))
    ingest_ucl_events(events, dp, "SeedProvider")
    return dp


def test_incomplete_provider_does_not_clear_existing_winner(tmp_path):
    """FDO returns final as 1-1 with no pen evidence — must not nullify PSG."""
    dp = _make_decided_final_dir(tmp_path)

    doc_before = load_knockout_store(dp)
    fin_before = doc_before["matches"]["final"][0]
    assert fin_before["winner"] == "Club01"
    assert fin_before["penalties_played"] is True
    assert fin_before["status"] == "played_pens"

    # Incomplete provider data: same score but no penalty evidence.
    incomplete_events = [
        _ko_event("FINAL", "Club01", "Club05", 1, 1),
    ]
    report = ingest_ucl_events(incomplete_events, dp, "IncompleteProvider")

    doc_after = load_knockout_store(dp)
    fin_after = doc_after["matches"]["final"][0]
    assert fin_after["winner"] == "Club01", "winner must not be nullified"
    assert fin_after["penalties_played"] is True, "penalty evidence must be preserved"
    assert fin_after["status"] == "played_pens", "status must not downgrade"
    assert fin_after["penalty_score"] == "4-3", "penalty score must be preserved"


def test_scheduled_provider_result_does_not_overwrite_completed(tmp_path):
    """Provider returns status=scheduled for a completed final — no change."""
    dp = _make_decided_final_dir(tmp_path)

    before_bytes = (dp / "knockout_results.json").read_bytes()

    scheduled_events = [
        {"home_team": "Club01", "away_team": "Club05", "home_score": 0,
         "away_score": 0, "status": "scheduled", "stage": "FINAL"},
    ]
    ingest_ucl_events(scheduled_events, dp, "ScheduledProvider")

    after_bytes = (dp / "knockout_results.json").read_bytes()
    assert after_bytes == before_bytes, "store must not be rewritten for scheduled data"


def test_penalty_decided_result_remains_decided(tmp_path):
    """Penalty shootout fields are preserved even when provider omits them."""
    dp = _make_decided_final_dir(tmp_path)

    # Provider sends the final with a score that matches but no pen evidence.
    incomplete_events = [
        _ko_event("FINAL", "Club01", "Club05", 2, 1),
    ]
    ingest_ucl_events(incomplete_events, dp, "PartialProvider")

    doc = load_knockout_store(dp)
    fin = doc["matches"]["final"][0]
    assert fin["winner"] == "Club01"
    assert fin["penalties_played"] is True, "penalty flag must not be cleared"
    assert fin["penalty_score"] == "4-3", "penalty score must not be cleared"
    assert fin["penalty_winner"] is not None, "penalty winner must not be cleared"


def test_provider_cannot_add_legs_to_decided_aggregate_only_tie(tmp_path):
    """QF tie decided without legs — provider legs must not be added."""
    dp = _make_decided_final_dir(tmp_path)

    # Now manually strip legs from a decided QF tie to simulate aggregate-only.
    ko_path = dp / "knockout_results.json"
    doc = json.loads(ko_path.read_text(encoding="utf-8"))
    qf = doc["matches"]["rounds"]["QF"]
    # qf_01: Club01 won 5-0 aggregate (legs=[2-0, 1-3 reversed order check...).
    # Find the tie and strip legs.
    for tie in qf:
        if tie["match_id"] == "qf_01":
            assert tie["winner"] == "Club01"
            tie["legs"] = None
            break
    ko_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    # Verify precondition.
    doc_before = load_knockout_store(dp)
    qf_map = {m["match_id"]: m for m in doc_before["matches"]["rounds"]["QF"]}
    assert qf_map["qf_01"]["legs"] is None, "precondition: tie is aggregate-only"
    assert qf_map["qf_01"]["winner"] == "Club01"

    # Provider sends per-leg events for the same tie.
    leg_events = [
        _ko_event("QUARTER_FINALS", "Club01", "Club02", 2, 0),
        _ko_event("QUARTER_FINALS", "Club02", "Club01", 1, 3),
    ]
    ingest_ucl_events(leg_events, dp, "LegsProvider")

    doc_after = load_knockout_store(dp)
    qf_after = {m["match_id"]: m for m in doc_after["matches"]["rounds"]["QF"]}
    tie_after = qf_after["qf_01"]
    assert tie_after["legs"] is None, "legs must not be added to decided aggregate-only tie"
    assert tie_after["winner"] == "Club01"
    # Aggregates unchanged from original seeding (Club01 5-1 on aggregate).
    assert tie_after["aggregate_a"] == 5
    assert tie_after["aggregate_b"] == 1


def test_genuinely_newer_result_can_update_undecided_entry(tmp_path):
    """Undecided tie gets legs and winner from provider — should update."""
    dp = _make_data_dir(tmp_path)
    # Only one leg of playoff tie 7, drawn — tie remains undecided.
    events = _league_events() + [
        _ko_event("PLAYOFFS", "Club18", "Club15", 1, 1, event_date="2026-02-17"),
    ]
    ingest_ucl_events(events, dp, "SeedProvider")

    # Tie 7 is undecided (one drawn leg, level aggregate).
    doc_before = load_knockout_store(dp)
    tie7 = next(t for t in doc_before["matches"]["playoff"] if t["tie_num"] == 7)
    assert tie7["winner"] is None

    # Now send both legs (second one decides it).
    leg_events = [
        _ko_event("PLAYOFFS", "Club18", "Club15", 1, 1, event_date="2026-02-17"),
        _ko_event("PLAYOFFS", "Club15", "Club18", 0, 2, event_date="2026-02-24"),
    ]
    ingest_ucl_events(leg_events, dp, "OfficialProvider")

    doc_after = load_knockout_store(dp)
    tie7_after = next(t for t in doc_after["matches"]["playoff"] if t["tie_num"] == 7)
    assert tie7_after["winner"] == "Club18"
    assert tie7_after["legs"] is not None
    assert len(tie7_after["legs"]) == 2
    assert tie7_after["status"] == "played"
    assert tie7_after["provenance"] == "official"


def test_should_apply_update_guard_unit():
    """Direct unit test of _should_apply_update logic."""
    from competitions.ucl.src.ingest import _should_apply_update

    # 1. Winner nullification blocked.
    assert _should_apply_update(
        {"winner": "PSG", "status": "played_pens"},
        {"winner": None, "status": "scheduled"},
    ) is False

    # 2. Penalty evidence loss blocked.
    assert _should_apply_update(
        {"winner": "PSG", "penalties_played": True},
        {"winner": "PSG", "penalties_played": False},
    ) is False

    # 3. Legs added to decided aggregate-only tie blocked.
    assert _should_apply_update(
        {"winner": "Arsenal", "legs": None},
        {"winner": "Arsenal", "legs": [{"leg": 1}]},
    ) is False

    # 4. Enrichment of undecided entry allowed.
    assert _should_apply_update(
        {"winner": None, "legs": None},
        {"winner": "Team", "legs": [{"leg": 1}]},
    ) is True

    # 5. Same winner, same penalty evidence — allowed.
    assert _should_apply_update(
        {"winner": "PSG", "penalties_played": True},
        {"winner": "PSG", "penalties_played": True},
    ) is True

    # 6. Both undecided — allowed.
    assert _should_apply_update(
        {"winner": None},
        {"winner": None},
    ) is True

    # 7. Legs already present, update with new legs — allowed.
    assert _should_apply_update(
        {"winner": "Team", "legs": [{"leg": 1}]},
        {"winner": "Team", "legs": [{"leg": 1}, {"leg": 2}]},
    ) is True
