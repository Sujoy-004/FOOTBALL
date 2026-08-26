"""Tests for competitions.ucl.src.state.build_competition_state."""

import copy
import json
from pathlib import Path

import pytest

from competitions.ucl.src.state import SEASON, build_competition_state

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DATA_DIR = REPO_ROOT / "competitions" / "ucl" / "data"

TIE_KEYS = {
    "id", "round", "team_a", "team_b", "legs",
    "aggregate_a", "aggregate_b", "agg_a_full", "agg_b_full",
    "et_played", "et_a", "et_b", "penalties_played",
    "penalty_a", "penalty_b", "penalty_winner", "winner",
    "status", "provenance", "slot_sources", "source_matches",
}
FINAL_KEYS = {
    "id", "team_a", "team_b", "score", "et_played", "et_a", "et_b",
    "penalties_played", "penalty_winner", "penalty_score",
    "winner", "status", "provenance", "source_matches",
}


def _copy_base_data(tmp_path: Path, with_results: bool = True) -> Path:
    dst = tmp_path / "data"
    dst.mkdir()
    for name in ("bracket_rules.json", "playoff_pairings.json", "fixtures.json"):
        (dst / name).write_text(
            (REAL_DATA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    if with_results:
        (dst / "results.json").write_text(
            (REAL_DATA_DIR / "results.json").read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def _rules_ids(dst: Path, round_name: str) -> list:
    rules = json.loads((dst / "bracket_rules.json").read_text(encoding="utf-8"))
    return [m["match_id"] for m in rules["matches"] if m["round"] == round_name]


def _v2_store() -> dict:
    return {
        "schema": 2,
        "matches": {
            "playoff": [
                {
                    "match_id": "playoff_t1", "tie_num": 1, "round": "playoff",
                    "team_a": "Monaco", "team_b": "PSG",
                    "slot_sources": {"position_a": 9, "position_b": 24},
                    "source_matches": None,
                    "legs": [
                        {"leg": 1, "home": "Monaco", "away": "PSG",
                         "home_score": 2, "away_score": 2},
                        {"leg": 2, "home": "PSG", "away": "Monaco",
                         "home_score": 3, "away_score": 2},
                    ],
                    "aggregate_a": 4, "aggregate_b": 5,
                    "et_played": False, "et_a": 0, "et_b": 0,
                    "penalties_played": False, "penalty_a": 0, "penalty_b": 0,
                    "penalty_winner": None,
                    "winner": "PSG", "status": "played", "provenance": "manual",
                },
                {
                    "match_id": "playoff_t2", "tie_num": 2, "round": "playoff",
                    "team_a": "Galatasaray", "team_b": "Juventus",
                    "slot_sources": {"position_a": 10, "position_b": 23},
                    "source_matches": None,
                    "legs": [
                        {"leg": 1, "home": "Galatasaray", "away": "Juventus",
                         "home_score": 2, "away_score": 0},
                        {"leg": 2, "home": "Juventus", "away": "Galatasaray",
                         "home_score": 3, "away_score": 1},
                    ],
                    "aggregate_a": 3, "aggregate_b": 3,
                    "et_played": True, "et_a": 1, "et_b": 1,
                    "penalties_played": True, "penalty_a": 3, "penalty_b": 4,
                    "penalty_winner": "Juventus",
                    "winner": "Juventus", "status": "played_pens", "provenance": "manual",
                },
            ],
            "rounds": {
                "R16": [
                    {
                        "match_id": "r16_03", "round": "R16", "quarter": 2,
                        "team_a": "Real Madrid", "team_b": "Man City",
                        "legs": None,
                        "aggregate_a": 5, "aggregate_b": 1,
                        "agg_a_full": 5, "agg_b_full": 1,
                        "et_played": False, "et_a": 0, "et_b": 0,
                        "penalties_played": False, "penalty_a": 0, "penalty_b": 0,
                        "penalty_winner": None,
                        "winner": "Real Madrid", "status": "played",
                        "provenance": "official",
                    },
                    {
                        "match_id": "r16_01", "round": "R16", "quarter": 1,
                        "team_a": "PSG", "team_b": "Chelsea",
                        "legs": None,
                        "aggregate_a": 8, "aggregate_b": 2,
                        "agg_a_full": 8, "agg_b_full": 2,
                        "et_played": False, "et_a": 0, "et_b": 0,
                        "penalties_played": False, "penalty_a": 0, "penalty_b": 0,
                        "penalty_winner": None,
                        "winner": "PSG", "status": "played", "provenance": "official",
                    },
                ],
                "QF": [], "SF": [],
            },
            "final": [],
            "champion": None,
        },
        "meta": {"provider": "test", "backfilled_from": None, "updated_at": "2026-01-01T00:00:00Z"},
    }


def _sim_payload() -> dict:
    return {
        "playoff_winners": {1: "PSG", 2: "Galatasaray"},
        "playoff": [
            {"tie_num": 1, "team_a": "PSG", "team_b": "Monaco", "winner": "PSG",
             "aggregate_a": 5, "aggregate_b": 4,
             "et_played": False, "penalties_played": False},
            {"tie_num": 2, "team_a": "Galatasaray", "team_b": "Juventus",
             "winner": "Galatasaray",
             "aggregate_a": 7, "aggregate_b": 5,
             "et_played": True, "et_a": 2, "et_b": 1,
             "penalties_played": False},
        ],
        "bracket_rounds": {
            "R16": [
                {
                    "match_id": "r16_01", "team_a": "PSG", "team_b": "Chelsea",
                    "result": {
                        "leg1": {"team_a": "PSG", "team_b": "Chelsea",
                                 "score_a": 3, "score_b": 1},
                        "leg2": {"team_a": "Chelsea", "team_b": "PSG",
                                 "score_a": 1, "score_b": 2},
                        "aggregate_a": 5, "aggregate_b": 2,
                        "agg_a_full": 5, "agg_b_full": 2,
                        "et_played": False, "et_a": 0, "et_b": 0,
                        "penalties_played": False, "penalty_a": 0, "penalty_b": 0,
                        "winner": "PSG", "loser": "Chelsea",
                    },
                    "source_matches": None,
                },
            ],
            "FINAL": [
                {
                    "match_id": "final_01", "team_a": "PSG", "team_b": "Arsenal",
                    "result": {"score": {"home": 2, "away": 1}, "winner": "PSG"},
                },
            ],
        },
    }


def _all_ko_nodes(state: dict) -> list:
    nodes = []
    for stage_id in ("playoff", "R16", "QF", "SF"):
        nodes.extend(state["stages"][stage_id]["matches"])
    nodes.append(state["stages"]["FINAL"]["matches"][0])
    return nodes


def test_missing_knockout_store_produces_skeletons(tmp_path):
    dst = _copy_base_data(tmp_path)
    state = build_competition_state(dst)
    assert state["availability"]["knockout_results"] == "missing"
    assert state["availability"]["fixtures"] == "available"
    assert state["availability"]["league_results"] == "available"
    assert state["champion"] is None
    assert state["season"] == SEASON
    assert len(state["stages"]["playoff"]["matches"]) == 8
    assert len(state["stages"]["R16"]["matches"]) == 8
    assert len(state["stages"]["QF"]["matches"]) == 4
    assert len(state["stages"]["SF"]["matches"]) == 2
    assert len(state["stages"]["FINAL"]["matches"]) == 1
    r16 = state["stages"]["R16"]["matches"]
    assert [m["id"] for m in r16] == _rules_ids(dst, "R16")
    for match in r16:
        assert match["team_a"] is None and match["team_b"] is None
        assert match["status"] == "scheduled"
        assert match["winner"] is None
        assert match["provenance"] is None
        assert match["slot_sources"] == {"home_seed": match["quarter"], "away_playoff_tie": None} or \
               set(match["slot_sources"].keys()) == {"home_seed", "away_playoff_tie"}
    qf = state["stages"]["QF"]["matches"]
    assert qf[0]["source_matches"] == ["r16_01", "r16_02"]
    assert qf[1]["source_matches"] == ["r16_03", "r16_04"]
    final_node = state["stages"]["FINAL"]["matches"][0]
    assert final_node == {
        "id": "final_01", "team_a": None, "team_b": None,
        "score": {"home": None, "away": None},
        "et_played": False, "et_a": 0, "et_b": 0,
        "penalties_played": False, "penalty_winner": None,
        "penalty_score": None, "winner": None,
        "status": "scheduled", "provenance": None,
        "source_matches": ["sf_01", "sf_02"],
    }
    po = state["stages"]["playoff"]["matches"]
    assert [m["id"] for m in po] == [f"playoff_t{i}" for i in range(1, 9)]
    assert po[0]["slot_sources"] == {"position_a": 9, "position_b": 24}
    assert po[7]["slot_sources"] == {"position_a": 16, "position_b": 17}


def test_empty_v1_store_is_honest_empty(tmp_path):
    dst = _copy_base_data(tmp_path)
    (dst / "knockout_results.json").write_text(
        json.dumps({"matches": {}}), encoding="utf-8")
    state = build_competition_state(dst)
    assert state["availability"]["knockout_results"] == "empty"
    assert state["champion"] is None
    for match in state["stages"]["R16"]["matches"]:
        assert match["team_a"] is None and match["team_b"] is None
        assert match["status"] == "scheduled"


def test_v2_store_merges_by_stable_ids(tmp_path):
    dst = _copy_base_data(tmp_path)
    (dst / "knockout_results.json").write_text(
        json.dumps(_v2_store()), encoding="utf-8")
    state = build_competition_state(dst)
    assert state["availability"]["knockout_results"] == "available"
    assert state["phase"]["phase"] == "knockout"
    po = state["stages"]["playoff"]["matches"]
    t1 = po[0]
    assert t1["id"] == "playoff_t1"
    assert t1["winner"] == "PSG"
    assert t1["aggregate_a"] == 4 and t1["aggregate_b"] == 5
    assert t1["agg_a_full"] == 4 and t1["agg_b_full"] == 5
    assert len(t1["legs"]) == 2
    assert t1["status"] == "played"
    t2 = po[1]
    assert t2["id"] == "playoff_t2"
    assert t2["status"] == "played_pens"
    assert t2["agg_a_full"] == 4 and t2["agg_b_full"] == 4
    assert t2["penalty_winner"] == "Juventus"
    assert t2["winner"] == "Juventus"
    r16 = state["stages"]["R16"]["matches"]
    by_id = {m["id"]: m for m in r16}
    assert set(by_id) == set(_rules_ids(dst, "R16"))
    assert by_id["r16_01"]["team_a"] == "PSG"
    assert by_id["r16_01"]["winner"] == "PSG"
    assert by_id["r16_03"]["team_a"] == "Real Madrid"
    assert by_id["r16_03"]["provenance"] == "official"
    assert by_id["r16_02"]["team_a"] is None
    assert by_id["r16_02"]["status"] == "scheduled"
    assert by_id["r16_02"]["provenance"] is None
    for match in state["stages"]["QF"]["matches"]:
        assert match["team_a"] is None and match["status"] == "scheduled"


def test_v1_bootstrap_normalises_to_canonical_ids(tmp_path):
    dst = _copy_base_data(tmp_path)
    bootstrap = json.loads(
        (REAL_DATA_DIR / "bootstrap" / "2025_26_knockout_results.json")
        .read_text(encoding="utf-8"))
    (dst / "knockout_results.json").write_text(
        json.dumps(bootstrap), encoding="utf-8")
    state = build_competition_state(dst)
    assert state["availability"]["knockout_results"] == "available"
    assert state["phase"]["phase"] == "completed"
    assert state["champion"] == "PSG"
    po = state["stages"]["playoff"]["matches"]
    assert [m["id"] for m in po] == [f"playoff_t{i}" for i in range(1, 9)]
    assert po[0]["team_a"] == "Monaco" and po[0]["team_b"] == "PSG"
    assert po[0]["aggregate_a"] == 4 and po[0]["aggregate_b"] == 5
    assert po[0]["winner"] == "PSG"
    assert all(m["legs"] is None for m in po)
    assert all(m["provenance"] == "manual" for m in po)
    r16 = state["stages"]["R16"]["matches"]
    assert [m["id"] for m in r16] == _rules_ids(dst, "R16")
    assert r16[0]["team_a"] == "PSG" and r16[0]["team_b"] == "Chelsea"
    assert r16[0]["aggregate_a"] == 8 and r16[0]["agg_a_full"] == 8
    assert r16[0]["status"] == "played"
    qf = state["stages"]["QF"]["matches"]
    assert [m["id"] for m in qf] == _rules_ids(dst, "QF")
    sf = state["stages"]["SF"]["matches"]
    assert [m["id"] for m in sf] == _rules_ids(dst, "SF")
    final_node = state["stages"]["FINAL"]["matches"][0]
    assert final_node["id"] == "final_01"
    assert final_node["score"] == {"home": 1, "away": 1}
    assert final_node["penalties_played"] is True
    assert final_node["penalty_winner"] == "PSG"
    assert final_node["penalty_score"] == "4-3"
    assert final_node["winner"] == "PSG"
    assert final_node["status"] == "played_pens"
    assert final_node["provenance"] == "manual"


def test_repeated_builds_are_byte_stable(tmp_path):
    dst = _copy_base_data(tmp_path)
    bootstrap = json.loads(
        (REAL_DATA_DIR / "bootstrap" / "2025_26_knockout_results.json")
        .read_text(encoding="utf-8"))
    (dst / "knockout_results.json").write_text(
        json.dumps(bootstrap), encoding="utf-8")
    first = build_competition_state(dst)
    second = build_competition_state(dst)
    assert json.dumps(first) == json.dumps(second)


def test_source_matches_resolve_within_state(tmp_path):
    dst = _copy_base_data(tmp_path)
    bootstrap = json.loads(
        (REAL_DATA_DIR / "bootstrap" / "2025_26_knockout_results.json")
        .read_text(encoding="utf-8"))
    (dst / "knockout_results.json").write_text(
        json.dumps(bootstrap), encoding="utf-8")
    state = build_competition_state(dst)
    known = set(_rules_ids(dst, "R16")) | set(_rules_ids(dst, "QF")) \
        | set(_rules_ids(dst, "SF")) | set(_rules_ids(dst, "FINAL")) \
        | {f"playoff_t{i}" for i in range(1, 9)}
    for node in _all_ko_nodes(state):
        for src in node.get("source_matches") or []:
            assert src in known


def test_exact_contract_shapes(tmp_path):
    dst = _copy_base_data(tmp_path)
    bootstrap = json.loads(
        (REAL_DATA_DIR / "bootstrap" / "2025_26_knockout_results.json")
        .read_text(encoding="utf-8"))
    (dst / "knockout_results.json").write_text(
        json.dumps(bootstrap), encoding="utf-8")
    state = build_competition_state(dst)
    assert state["competition"] == "ucl"
    assert state["stage_order"] == ["league", "playoff", "R16", "QF", "SF", "FINAL"]
    assert state["stages"]["league"]["layout"] == "list"
    assert state["stages"]["league"]["matchdays"]
    for stage_id in ("R16", "QF", "SF", "FINAL"):
        assert state["stages"][stage_id]["layout"] == "tree"
    for node in state["stages"]["R16"]["matches"]:
        assert set(node.keys()) == TIE_KEYS | {"quarter"}
    for node in state["stages"]["QF"]["matches"]:
        assert set(node.keys()) == TIE_KEYS | {"quarter"}
    for node in state["stages"]["SF"]["matches"]:
        assert set(node.keys()) == TIE_KEYS
    for node in state["stages"]["playoff"]["matches"]:
        assert set(node.keys()) == TIE_KEYS | {"tie_num"}
    final_node = state["stages"]["FINAL"]["matches"][0]
    assert set(final_node.keys()) == FINAL_KEYS


def test_simulation_branch_flattens_result_blob(tmp_path):
    dst = _copy_base_data(tmp_path)
    state = build_competition_state(dst, mode="simulation",
                                    sim_payload=_sim_payload())
    assert state["mode"] == "simulation"
    assert state["champion"] is None
    assert "champion_probs" not in state
    po = state["stages"]["playoff"]["matches"]
    t1 = next(m for m in po if m["id"] == "playoff_t1")
    assert t1["team_a"] == "PSG" and t1["winner"] == "PSG"
    assert t1["aggregate_a"] == 5 and t1["aggregate_b"] == 4
    assert t1["provenance"] == "simulated"
    assert t1["status"] == "played"
    t2 = next(m for m in po if m["id"] == "playoff_t2")
    assert t2["team_a"] == "Galatasaray" and t2["winner"] == "Galatasaray"
    assert t2["agg_a_full"] == 9 and t2["agg_b_full"] == 6
    t3 = next(m for m in po if m["id"] == "playoff_t3")
    assert t3["team_a"] is None and t3["status"] == "scheduled"
    assert t3["provenance"] == "simulated"
    r16 = state["stages"]["R16"]["matches"]
    r16_01 = next(m for m in r16 if m["id"] == "r16_01")
    assert r16_01["team_a"] == "PSG" and r16_01["team_b"] == "Chelsea"
    assert r16_01["winner"] == "PSG"
    assert r16_01["aggregate_a"] == 5 and r16_01["aggregate_b"] == 2
    assert r16_01["agg_a_full"] == 5 and r16_01["agg_b_full"] == 2
    assert len(r16_01["legs"]) == 2
    assert r16_01["legs"][0] == {"leg": 1, "home": "PSG", "away": "Chelsea",
                                 "home_score": 3, "away_score": 1}
    assert r16_01["provenance"] == "simulated"
    assert r16_01["source_matches"] == ["r16_01", "r16_02"] or \
        r16_01["source_matches"] is None
    r16_02 = next(m for m in r16 if m["id"] == "r16_02")
    assert r16_02["team_a"] is None and r16_02["status"] == "scheduled"
    final_node = state["stages"]["FINAL"]["matches"][0]
    assert final_node["team_a"] == "PSG" and final_node["team_b"] == "Arsenal"
    assert final_node["score"] == {"home": 2, "away": 1}
    assert final_node["winner"] == "PSG"
    assert final_node["provenance"] == "simulated"
    for node in _all_ko_nodes(state):
        assert node["provenance"] == "simulated"


def test_simulation_champion_probs_passthrough(tmp_path):
    dst = _copy_base_data(tmp_path)
    payload = _sim_payload()
    payload["champion_probs"] = {"PSG": 0.4, "Arsenal": 0.1}
    state = build_competition_state(dst, mode="simulation", sim_payload=payload)
    assert state["champion_probs"] == {"PSG": 0.4, "Arsenal": 0.1}


def test_simulation_requires_payload(tmp_path):
    dst = _copy_base_data(tmp_path)
    with pytest.raises(ValueError):
        build_competition_state(dst, mode="simulation")
    with pytest.raises(ValueError):
        build_competition_state(dst, mode="simulation", sim_payload=["nope"])


def test_invalid_mode_raises(tmp_path):
    dst = _copy_base_data(tmp_path)
    with pytest.raises(ValueError):
        build_competition_state(dst, mode="bogus")


def test_dag_unresolved_reference_raises(tmp_path):
    dst = _copy_base_data(tmp_path)
    rules = json.loads((dst / "bracket_rules.json").read_text(encoding="utf-8"))
    for match in rules["matches"]:
        if match["match_id"] == "qf_01":
            match["source_matches"] = ["r16_01", "r16_xx"]
    (dst / "bracket_rules.json").write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(ValueError):
        build_competition_state(dst)


def test_dag_cycle_raises(tmp_path):
    dst = _copy_base_data(tmp_path)
    rules = json.loads((dst / "bracket_rules.json").read_text(encoding="utf-8"))
    for match in rules["matches"]:
        if match["match_id"] == "r16_01":
            match["source_matches"] = ["qf_01"]
    (dst / "bracket_rules.json").read_text(encoding="utf-8")
    (dst / "bracket_rules.json").write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(ValueError):
        build_competition_state(dst)


def test_unreadable_knockout_store_behaves_as_unavailable(tmp_path):
    dst = _copy_base_data(tmp_path)
    (dst / "knockout_results.json").write_text("{not json", encoding="utf-8")
    state = build_competition_state(dst)
    assert state["availability"]["knockout_results"] == "unavailable"
    assert state["champion"] is None
    for match in state["stages"]["R16"]["matches"]:
        assert match["team_a"] is None
