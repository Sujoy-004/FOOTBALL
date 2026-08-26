"""Simulated-path state payload contract (Exchange 2 unification).

Locks the clean ``sim_state_payload`` emitted by the Monte Carlo pipeline
onto the exact shape ``competitions.ucl.src.state.build_competition_state``
consumes with ``mode="simulation"``, and proves the end-to-end chain:

    seeded MC run -> sim_state_payload -> canonical competition state

with no null-team/TBD incoherence anywhere a winner was resolved.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from football_core.provider import FixtureSchedule

from competitions.ucl.result import SimulationResult
from competitions.ucl.src.orchestrator import build_simulation_result
from competitions.ucl.src.state import STAGE_ORDER, build_competition_state

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DATA_DIR = REPO_ROOT / "competitions" / "ucl" / "data"

KO_ROUNDS = ("R16", "QF", "SF", "FINAL")
ID_PREFIXES = {"R16": "r16_", "QF": "qf_", "SF": "sf_", "FINAL": "final_"}
ROUND_COUNTS = {"R16": 8, "QF": 4, "SF": 2, "FINAL": 1}

FINAL_NODE_KEYS = {
    "id", "team_a", "team_b", "score", "et_played", "et_a", "et_b",
    "penalties_played", "penalty_winner", "penalty_score",
    "winner", "status", "provenance", "source_matches",
}


def _synthetic_elo() -> dict[str, float]:
    """Coefficient-derived Elo for all 36 teams (zero live requests)."""
    fixtures = json.loads(
        (REAL_DATA_DIR / "fixtures.json").read_text(encoding="utf-8"))
    coeffs = {t["name"]: t["coefficient"] for t in fixtures["schedule"]["teams"]}
    max_coeff = max(coeffs.values())
    return {name: 1400.0 + (c / max_coeff) * 400.0 for name, c in coeffs.items()}


def _run_sim(seed: int = 42, n_iterations: int = 4):
    """Small seeded end-to-end simulation through the public entry point."""
    fixtures = json.loads(
        (REAL_DATA_DIR / "fixtures.json").read_text(encoding="utf-8"))
    schedule = FixtureSchedule.from_dict(fixtures["schedule"])
    return build_simulation_result(
        schedule, _synthetic_elo(), seed=seed, n_iterations=n_iterations)


def _state_data_dir(tmp_path: Path) -> Path:
    """Minimal on-disk store for the canonical state builder."""
    dst = tmp_path / "data"
    dst.mkdir(parents=True)
    for name in ("bracket_rules.json", "playoff_pairings.json", "fixtures.json"):
        shutil.copy(REAL_DATA_DIR / name, dst / name)
    (dst / "results.json").write_text('{"matches": []}', encoding="utf-8")
    return dst


def _all_ko_nodes(state: dict) -> list:
    nodes = []
    for stage_id in ("playoff", "R16", "QF", "SF"):
        nodes.extend(state["stages"][stage_id]["matches"])
    nodes.append(state["stages"]["FINAL"]["matches"][0])
    return nodes


@pytest.fixture(scope="module")
def sim_result():
    return _run_sim(seed=42, n_iterations=4)


@pytest.fixture(scope="module")
def payload(sim_result):
    return sim_result.sim_state_payload


class TestPayloadShape:
    """sim_state_payload carries the exact state.py contract."""

    def test_result_keeps_legacy_contract(self, sim_result, payload):
        """build_simulation_result still returns a full SimulationResult."""
        assert isinstance(sim_result, SimulationResult)
        assert len(sim_result.standings) == 36
        assert len(sim_result.teams) == 36
        assert sim_result.bracket_champion
        assert {rnd: len(sim_result.bracket_rounds[rnd]) for rnd in KO_ROUNDS} \
            == ROUND_COUNTS
        assert set(payload.keys()) == {
            "playoff_winners", "playoff", "bracket_rounds", "champion_probs"}

    def test_bracket_ids_follow_stable_conventions(self, payload):
        """Every match_id matches its round's stable id convention."""
        seen = set()
        for rnd in KO_ROUNDS:
            entries = payload["bracket_rounds"][rnd]
            assert len(entries) == ROUND_COUNTS[rnd]
            for entry in entries:
                mid = entry["match_id"]
                assert mid.startswith(ID_PREFIXES[rnd]), (
                    f"{mid} does not use the {ID_PREFIXES[rnd]} convention")
                assert mid[len(ID_PREFIXES[rnd]):].isdigit()
                assert mid not in seen, f"duplicate match_id {mid}"
                seen.add(mid)
        assert len(seen) == 15

    def test_later_rounds_carry_resolved_team_names(self, payload):
        """QF/SF/FINAL entries never show null teams or TBD slots."""
        for rnd in ("QF", "SF", "FINAL"):
            for entry in payload["bracket_rounds"][rnd]:
                assert isinstance(entry["team_a"], str) and entry["team_a"]
                assert isinstance(entry["team_b"], str) and entry["team_b"]
                assert entry["winner"] in (entry["team_a"], entry["team_b"])
                for value in (entry["team_a"], entry["team_b"], entry["winner"]):
                    assert value not in ("TBD", "?"), f"TBD placeholder in {rnd}"

    def test_result_blobs_contain_leg_scores(self, payload):
        """Two-legged rounds carry leg-level scores and aggregates."""
        for rnd in ("R16", "QF", "SF"):
            for entry in payload["bracket_rounds"][rnd]:
                blob = entry["result"]
                for leg_key in ("leg1", "leg2"):
                    leg = blob[leg_key]
                    assert isinstance(leg["score_a"], int) and leg["score_a"] >= 0
                    assert isinstance(leg["score_b"], int) and leg["score_b"] >= 0
                assert isinstance(blob["aggregate_a"], int)
                assert isinstance(blob["aggregate_b"], int)
                # Canonical legs reproduce the raw aggregate totals, with
                # each leg reporting its true host first.
                team_goals: dict[str, int] = {}
                for leg in entry["legs"]:
                    assert [l["leg"] for l in entry["legs"]] == [1, 2]
                    assert leg["home"] and leg["away"]
                    team_goals[leg["home"]] = (
                        team_goals.get(leg["home"], 0) + leg["home_score"])
                    team_goals[leg["away"]] = (
                        team_goals.get(leg["away"], 0) + leg["away_score"])
                assert team_goals[entry["team_a"]] == blob["aggregate_a"]
                assert team_goals[entry["team_b"]] == blob["aggregate_b"]

    def test_final_is_single_match_with_score(self, payload):
        final_entry = payload["bracket_rounds"]["FINAL"][0]
        assert final_entry["match_id"] == "final_01"
        assert final_entry["score"]["home"] is not None
        assert final_entry["score"]["away"] is not None
        assert final_entry["winner"] in (final_entry["team_a"], final_entry["team_b"])
        assert "legs" not in final_entry

    def test_source_matches_present_from_qf_onwards(self, payload):
        known = {e["match_id"]
                 for rnd in KO_ROUNDS
                 for e in payload["bracket_rounds"][rnd]}
        for idx, rnd in enumerate(KO_ROUNDS):
            for entry in payload["bracket_rounds"][rnd]:
                sources = entry.get("source_matches")
                if rnd == "R16":
                    assert sources is None
                    continue
                assert isinstance(sources, list) and len(sources) == 2
                for src in sources:
                    assert src in known

    def test_playoff_ties_carry_legs_aggregate_winner(
        self, sim_result, payload,
    ):
        ties = payload["playoff"]
        assert [t["tie_num"] for t in ties] == list(range(1, 9))
        for tie in ties:
            assert tie["winner"] and tie["winner"] == tie["team_a"]
            assert tie["loser"] and tie["loser"] == tie["team_b"]
            assert isinstance(tie["aggregate_a"], int)
            assert isinstance(tie["aggregate_b"], int)
            assert tie["agg_a_full"] >= tie["aggregate_a"]
            assert tie["agg_b_full"] >= tie["aggregate_b"]
            assert len(tie["legs"]) == 2
            for leg in tie["legs"]:
                assert isinstance(leg["home_score"], int)
                assert isinstance(leg["away_score"], int)
                assert leg["home"] and leg["away"]
        winners = payload["playoff_winners"]
        assert set(winners.keys()) == set(range(1, 9))
        assert winners == {
            t["tie_num"]: t["winner"] for t in ties}

    def test_champion_probs_passthrough(self, payload):
        probs = payload["champion_probs"]
        assert isinstance(probs, dict) and probs
        for name, prob in probs.items():
            assert isinstance(name, str) and name
            assert 0.0 < prob <= 1.0
        assert sum(probs.values()) <= 1.0 + 1e-9


class TestStateBuildsFromPayload:
    """The payload feeds build_competition_state(mode='simulation') directly."""

    @pytest.fixture(scope="class")
    def state(self, payload, tmp_path_factory):
        dst = _state_data_dir(tmp_path_factory.mktemp("simstate"))
        return build_competition_state(dst, mode="simulation", sim_payload=payload)

    def test_stage_ids_match_canonical_order(self, state):
        assert state["mode"] == "simulation"
        assert state["stage_order"] == list(STAGE_ORDER)
        assert list(state["stages"].keys()) == [
            "league", "playoff", "R16", "QF", "SF", "FINAL"]

    def test_all_knockout_nodes_marked_simulated(self, state):
        for node in _all_ko_nodes(state):
            assert node["provenance"] == "simulated", (
                f"{node['id']} provenance {node['provenance']!r}")

    def test_stage_sizes_follow_bracket_rules(self, state):
        sizes = {"playoff": 8, "R16": 8, "QF": 4, "SF": 2, "FINAL": 1}
        for stage_id, expected in sizes.items():
            matches = state["stages"][stage_id]["matches"]
            assert len(matches) == expected
            assert all(m["id"] for m in matches)

    def test_final_single_match_shape(self, state):
        final_node = state["stages"]["FINAL"]["matches"][0]
        assert set(final_node.keys()) == FINAL_NODE_KEYS
        assert final_node["id"] == "final_01"
        assert final_node["score"]["home"] is not None
        assert final_node["score"]["away"] is not None
        assert "legs" not in final_node
        assert final_node["status"] in ("played", "played_pens")

    def test_two_legged_nodes_expose_legs_and_aggregates(self, state):
        for stage_id in ("playoff", "R16", "QF", "SF"):
            for node in state["stages"][stage_id]["matches"]:
                assert node["legs"] and len(node["legs"]) == 2, (
                    f"{node['id']} missing legs")
                assert node["aggregate_a"] is not None
                assert node["aggregate_b"] is not None
                assert node["status"] in ("played", "played_pens")

    def test_no_tbd_placeholders_anywhere(self, state):
        """Winner known implies both team names known — zero TBD coherence."""
        for node in _all_ko_nodes(state):
            if node.get("winner"):
                assert node.get("team_a") and node.get("team_b"), (
                    f"{node['id']}: winner without resolved teams")
            serialized = json.dumps(node)
            assert "TBD" not in serialized
            assert '"?"' not in serialized

    def test_every_slot_resolved_in_fully_simulated_season(self, state):
        """All simulated ties completed: every node has winner and teams."""
        for node in _all_ko_nodes(state):
            assert node["winner"], f"{node['id']} has no winner"
            assert node["team_a"] and node["team_b"]

    def test_champion_probs_reach_the_state_document(self, state, payload):
        assert state["champion_probs"] == payload["champion_probs"]

    def test_bracket_consistency_with_engine_champion(self, state, sim_result):
        final_node = state["stages"]["FINAL"]["matches"][0]
        assert final_node["winner"] == sim_result.bracket_champion


class TestDeterminism:
    """Same seed serialises to an identical payload."""

    def test_same_seed_identical_json(self):
        first = _run_sim(seed=7, n_iterations=2).sim_state_payload
        second = _run_sim(seed=7, n_iterations=2).sim_state_payload
        assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)

    def test_same_seed_state_documents_identical(self, tmp_path):
        first = _run_sim(seed=11, n_iterations=2).sim_state_payload
        second = _run_sim(seed=11, n_iterations=2).sim_state_payload
        dst_a = _state_data_dir(tmp_path / "run_a")
        dst_b = _state_data_dir(tmp_path / "run_b")
        state_a = build_competition_state(dst_a, mode="simulation", sim_payload=first)
        state_b = build_competition_state(dst_b, mode="simulation", sim_payload=second)
        assert json.dumps(state_a) == json.dumps(state_b)
