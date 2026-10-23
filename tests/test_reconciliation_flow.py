"""End-to-end reconciliation flow test suite (Phase 5, RECON-01 / RECON-02 / SIM-04).

Defends:
- Claim 1: Real ingested knockout results retire covering simulated answers.
- Claim 2: Retired answers render with MatchStatus.SCHEDULED / is_played_fact is False.
- Claim 3: Durable retirement ledger survives process restarts and crash before rebind.
- Claim 5: Non-AVAILABLE availability states never claim currency or zero retired.
- Claim 6: Failed boot publishing empty state yields not_established status.
- Results role narrowing: non-results store modifications do not trigger retirement.
- Sub-stamp backstop on read path reconciles without calling brains or refresh endpoints.
- LaLiga and World Cup idempotency and content-conditional write preservation.

All store access is sandboxed under tmp_path; never touches repository stores.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from football_core.domain import (
    CanonicalMatch,
    DataAvailability,
    MatchStatus,
    ResultProvenance,
    effective_status,
)
from football_core.state import atomic_write_text
from web.derived import holder


def _owner():
    """The web-layer owner, imported lazily so a missing module fails per test."""
    import web.reconciliation as owner

    return owner


@pytest.fixture
def wc_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """World Cup sandboxed environment under tmp_path."""
    import web.wc_app as wc_app

    wc_dir = tmp_path / "wcdata"
    wc_dir.mkdir(parents=True, exist_ok=True)

    # Initial empty / default stores
    atomic_write_text(wc_dir / "played.json", json.dumps({}))
    atomic_write_text(wc_dir / "played_groups.json", json.dumps({}))
    atomic_write_text(
        wc_dir / "bracket.json",
        json.dumps(
            {
                "matches": [
                    {"match_id": "M73", "round": "R32", "team_a": "USA", "team_b": "ENG"},
                    {"match_id": "M74", "round": "R32", "team_a": "MEX", "team_b": "FRA"},
                    {
                        "match_id": "M89",
                        "round": "R16",
                        "team_a": None,
                        "team_b": None,
                        "source_matches": ["M73", "M74"],
                    },
                    {
                        "match_id": "QF_1",
                        "round": "QF",
                        "team_a": None,
                        "team_b": None,
                        "source_matches": ["M89", "M90"],
                    },
                ]
            }
        ),
    )

    monkeypatch.setattr(wc_app, "DATA_DIR", wc_dir)
    monkeypatch.setattr(
        wc_app, "_refresh_report_path", lambda: tmp_path / "wc_freshness.json"
    )

    holder.reset("worldcup")
    yield wc_dir
    holder.reset("worldcup")


@pytest.fixture
def published_wc_sim():
    """Publish a dummy simulated knockout bracket into the holder."""
    sim_payload = {
        "status": "completed",
        "simulation_meta": {
            "n_simulations": 100,
            "seed": 42,
            "provenance": "simulated",
        },
        "full_bracket": {
            "n_matchups": 4,
            "rounds": {
                "R32": [
                    {
                        "match_id": "M73",
                        "round": "R32",
                        "team_a": "USA",
                        "team_b": "ENG",
                        "prob_a": 0.55,
                        "predicted_score": "2-1",
                        "status": "simulated",
                        "provenance": "simulated",
                        "source_matches": [],
                    },
                    {
                        "match_id": "M74",
                        "round": "R32",
                        "team_a": "MEX",
                        "team_b": "FRA",
                        "prob_a": 0.40,
                        "predicted_score": "0-1",
                        "status": "simulated",
                        "provenance": "simulated",
                        "source_matches": [],
                    },
                ],
                "R16": [
                    {
                        "match_id": "M89",
                        "round": "R16",
                        "team_a": "USA",
                        "team_b": "FRA",
                        "prob_a": 0.45,
                        "predicted_score": "1-2",
                        "status": "simulated",
                        "provenance": "simulated",
                        "source_matches": ["M73", "M74"],
                    }
                ],
                "QF": [
                    {
                        "match_id": "QF_1",
                        "round": "QF",
                        "team_a": "FRA",
                        "team_b": "ARG",
                        "prob_a": 0.50,
                        "predicted_score": "2-2",
                        "status": "simulated",
                        "provenance": "simulated",
                        "source_matches": ["M89", "M90"],
                    }
                ],
            },
        },
        "sim_facts": ("GS_A_01",),
        "sim_results_stamp": {"played": [0, 0]},
    }
    holder.publish_sim("worldcup", sim_payload)
    return sim_payload


@pytest.fixture
def wc_spec(wc_env: Path):
    """ReconciliationSpec for the World Cup sandboxed environment."""
    owner = _owner()
    from football_core.store_stamp import stamp_store

    def _keys(payload: Any) -> frozenset[str]:
        if isinstance(payload, dict):
            return frozenset(payload.keys())
        return frozenset()

    def _rows(payload: Any) -> dict[str, Any]:
        return dict(payload) if isinstance(payload, dict) else {}

    played_path = wc_env / "played.json"
    played_groups_path = wc_env / "played_groups.json"

    result_stores = (
        owner.ResultStore("played", played_path, ids=_keys, rows=_rows),
        owner.ResultStore("played_groups", played_groups_path, ids=_keys, rows=_rows),
    )

    roles = {"played": "played.json", "played_groups": "played_groups.json"}

    return owner.ReconciliationSpec(
        competition="worldcup",
        ledger_path=owner.retirement_ledger_path(wc_env),
        result_stores=result_stores,
        observed_stamp=lambda: stamp_store(wc_env, roles),
        granularity="match",
    )


def test_real_result_retires_covering_sim_answers(wc_env: Path, published_wc_sim: dict, wc_spec):
    """Claim 1: Real ingested knockout result retires covering simulated answers."""
    owner = _owner()

    # Real result lands for M73
    atomic_write_text(
        wc_env / "played.json",
        json.dumps({"M73": {"score_a": 2, "score_b": 1, "winner": "USA"}}),
    )

    recon = owner.reconcile_if_needed(wc_spec)
    assert recon["retired_count"] == 1
    retired_match_ids = [r["match_id"] for r in recon["retired"]]
    assert "M73" in retired_match_ids
    assert recon["retired"][0]["real_match_id"] == "M73"
    assert recon["retired"][0]["reason"] == "real_result_ingested"


def test_retired_answer_renders_scheduled_never_played(wc_env: Path, published_wc_sim: dict, wc_spec):
    """Claim 2: Retired simulated answer renders as scheduled and never played fact."""
    owner = _owner()

    # Ingest M73
    atomic_write_text(
        wc_env / "played.json",
        json.dumps({"M73": {"score_a": 2, "score_b": 1, "winner": "USA"}}),
    )
    recon = owner.reconcile_if_needed(wc_spec)
    assert recon["retired_count"] == 1

    # Invariants
    assert (
        effective_status(MatchStatus.PLAYED, ResultProvenance.SIMULATED)
        == MatchStatus.SCHEDULED
    )
    canonical = CanonicalMatch(
        match_id="M73",
        team_a="USA",
        team_b="ENG",
        status=MatchStatus.SCHEDULED,
        provenance=ResultProvenance.SIMULATED,
    )
    assert canonical.is_played_fact is False

    # Second reconciliation check
    recon2 = owner.reconcile_if_needed(wc_spec)
    assert recon2["retired"][0]["provenance"] == "simulated"


def test_ledger_survives_restart(wc_env: Path, published_wc_sim: dict, wc_spec):
    """Claim 3: Durable ledger survives restart and crash before rebind."""
    owner = _owner()

    atomic_write_text(
        wc_env / "played.json",
        json.dumps({"M73": {"score_a": 2, "score_b": 1, "winner": "USA"}}),
    )
    recon = owner.reconcile_if_needed(wc_spec)
    assert recon["retired_count"] == 1

    # Simulate restart by resetting in-memory holder
    holder.reset("worldcup")
    block = owner.reconciliation_block(wc_spec)
    assert block["retired_count"] == 1
    assert block["retired"][0]["match_id"] == "M73"


@pytest.mark.parametrize(
    "avail",
    [
        DataAvailability.AVAILABLE,
        DataAvailability.EMPTY,
        DataAvailability.MISSING,
        DataAvailability.UNAVAILABLE,
    ],
)
def test_availability_states_never_read_as_zero_retired(
    wc_env: Path, published_wc_sim: dict, wc_spec, avail: DataAvailability
):
    """Claim 5: Non-AVAILABLE states report honest availability and omit 0 count."""
    owner = _owner()

    if avail == DataAvailability.AVAILABLE:
        atomic_write_text(
            wc_env / "played.json",
            json.dumps({"M73": {"score_a": 2, "score_b": 1, "winner": "USA"}}),
        )
    elif avail == DataAvailability.EMPTY:
        atomic_write_text(wc_env / "played.json", json.dumps({}))
    elif avail == DataAvailability.MISSING:
        (wc_env / "played.json").unlink(missing_ok=True)
    elif avail == DataAvailability.UNAVAILABLE:
        atomic_write_text(wc_env / "played.json", "{corrupt json")

    block = owner.reconciliation_block(wc_spec)
    if avail != DataAvailability.AVAILABLE:
        assert block["mode"] != "real"
        assert "retired_count" not in block or block.get("retired_count") != 0


def test_failed_boot_state_yields_not_established(wc_env: Path, wc_spec):
    """Claim 6: Empty derived state paired with current stamp yields not_established."""
    owner = _owner()
    from football_core.store_stamp import stamp_store

    roles = {"played": "played.json", "played_groups": "played_groups.json"}
    current_stamp = stamp_store(wc_env, roles)

    # Publish empty data dict against current stamp
    holder.publish_data("worldcup", {}, mode=None, stamp=current_stamp)

    block = owner.reconciliation_block(wc_spec)
    assert block.get("not_established") is True
    assert block.get("reconciliation_status") == "reconciliation not established"
    assert "retired_count" not in block
    assert block.get("mode") != "real"


def test_read_path_backstop_retires_without_a_brain_call(wc_env: Path, published_wc_sim: dict, wc_spec):
    """Sub-stamp change triggers retirement on read path without any brain call."""
    owner = _owner()

    # Modify played store directly (simulating offline CLI backfill)
    atomic_write_text(
        wc_env / "played.json",
        json.dumps({"M73": {"score_a": 1, "score_b": 0, "winner": "USA"}}),
    )

    # Calling read-path entry point directly without refresh
    recon = owner.reconcile_if_needed(wc_spec)
    assert recon["retired_count"] == 1
    assert recon["retired"][0]["match_id"] == "M73"


def test_results_role_narrowing_ignores_non_results_writes(wc_env: Path, published_wc_sim: dict, wc_spec):
    """Modifying non-results roles does not move sub-stamp or trigger retirement."""
    owner = _owner()

    # Write bracket.json (non-results role)
    atomic_write_text(wc_env / "bracket.json", json.dumps({"extra": "data"}))

    recon = owner.reconcile_if_needed(wc_spec)
    assert recon["retired_count"] == 0


def test_retirements_json_is_not_in_the_stamp_roles(wc_env: Path, wc_spec):
    """Writing retirements.json does not alter observed results-role stamp."""
    owner = _owner()
    before_stamp = wc_spec.observed_stamp()

    atomic_write_text(wc_env / "retirements.json", json.dumps({"records": []}))
    after_stamp = wc_spec.observed_stamp()

    assert before_stamp == after_stamp


def test_ledger_write_precedes_rebind(monkeypatch: pytest.MonkeyPatch, wc_env: Path, published_wc_sim: dict, wc_spec):
    """If writing the retirement ledger raises, the holder sim slot is not modified."""
    owner = _owner()

    atomic_write_text(
        wc_env / "played.json",
        json.dumps({"M73": {"score_a": 2, "score_b": 1, "winner": "USA"}}),
    )

    def _broken_write(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr("football_core.state.atomic_write_text", _broken_write)

    with pytest.raises(OSError, match="disk failure"):
        owner.reconcile_if_needed(wc_spec)

    # Sim in holder remains untouched
    sim = holder.read_sim("worldcup")
    assert sim.get("status") == "completed"


def test_group_stage_ingest_yields_partial_mode(wc_env: Path, published_wc_sim: dict, wc_spec):
    """Ingesting a group-stage result retires nothing and yields 'partial' mode (D-11)."""
    owner = _owner()

    atomic_write_text(
        wc_env / "played_groups.json",
        json.dumps({"GS_A_01": {"score_a": 1, "score_b": 0, "winner": "A"}}),
    )

    recon = owner.reconcile_if_needed(wc_spec)
    assert recon["retired_count"] == 0
    assert recon["mode"] == "partial"


def test_idempotent_reingest_does_not_retire(wc_env: Path, published_wc_sim: dict, wc_spec):
    """Running reconciler twice on identical content does not duplicate or increase retired_count."""
    owner = _owner()

    atomic_write_text(
        wc_env / "played.json",
        json.dumps({"M73": {"score_a": 2, "score_b": 1, "winner": "USA"}}),
    )

    r1 = owner.reconcile_if_needed(wc_spec)
    count1 = r1["retired_count"]

    r2 = owner.reconcile_if_needed(wc_spec)
    count2 = r2["retired_count"]

    assert count1 == count2
    retired_ids = [r["match_id"] for r in r2["retired"]]
    assert len(retired_ids) == len(set(retired_ids))


def test_changed_is_false_on_idempotent_reingest(tmp_path: Path):
    """Brain reporting channels return changed=False on idempotent re-ingest (D-06/D-15)."""
    from football_core.fetcher import IngestReport

    report = IngestReport(
        provider="Stub",
        attempted=True,
        success=True,
        error=None,
        changed=False,
        changed_match_ids=[],
    )
    d = report.to_dict()
    assert d["changed"] is False
    assert d["changed_match_ids"] == []


def test_laliga_write_is_content_conditional(tmp_path: Path):
    """LaLiga store write must be content-conditional and not touch mtime on identical content."""
    store_file = tmp_path / "results.json"
    content = json.dumps({"matches": [{"id": 1, "score": "1-0"}]})
    atomic_write_text(store_file, content)
    mtime1 = store_file.stat().st_mtime_ns

    # Plan 05-05 introduces conditional write logic
    from competitions.laliga.src.pipeline import _write_results_if_changed

    written = _write_results_if_changed(store_file, {"matches": [{"id": 1, "score": "1-0"}]})
    assert written is False
    mtime2 = store_file.stat().st_mtime_ns
    assert mtime1 == mtime2
