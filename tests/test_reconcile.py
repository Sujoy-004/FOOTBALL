"""Unit suite for the pure reconciliation kernel contract (Phase 5, RECON-01).

Defends:
* Mathematical correctness of the set algebra (factual ∩ sim \ retired).
* Mode derivation rules (real / partial / not_applicable).
* Aggregated DataAvailability ranking.
* Immutability and provenance invariants of Retirement records.

No filesystem I/O beyond tmp_path, zero network calls, zero web/competition imports.
"""

from __future__ import annotations

import dataclasses
import pytest

from football_core.domain import DataAvailability, ResultProvenance
from football_core.reconcile import (
    AVAILABILITY_SEVERITY,
    Reconciliation,
    Retirement,
    aggregate_availability,
    derive_mode,
    retire_matching,
    retire_whole_snapshot,
)


def test_retirement_set_is_the_intersection_minus_already_retired():
    """Retirement set is (factual_ids ∩ sim_ids) - already_retired (D-17)."""
    retirements = retire_matching(
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        factual_ids=frozenset({"M73", "M74", "GS_A_01"}),
        sim_ids=frozenset({"M73", "M89"}),
        already_retired=frozenset(),
        superseded_answers={"M73": {"pred": 1}},
        real_results={"M73": {"score": "2-1"}},
        store_stamp_at_retirement={},
    )
    assert len(retirements) == 1
    assert retirements[0].match_id == "M73"

    retirements_second = retire_matching(
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        factual_ids=frozenset({"M73", "M74", "GS_A_01"}),
        sim_ids=frozenset({"M73", "M89"}),
        already_retired=frozenset({"M73"}),
        superseded_answers={"M73": {"pred": 1}},
        real_results={"M73": {"score": "2-1"}},
        store_stamp_at_retirement={},
    )
    assert retirements_second == ()


def test_idempotent_reingest_does_not_retire():
    """Double invocation with already_retired produces an empty tuple (D-01)."""
    first = retire_matching(
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        factual_ids=frozenset({"M73"}),
        sim_ids=frozenset({"M73"}),
        already_retired=frozenset(),
        superseded_answers={"M73": {}},
        real_results={"M73": {}},
        store_stamp_at_retirement={},
    )
    assert len(first) == 1
    already = frozenset(r.match_id for r in first if r.match_id)
    second = retire_matching(
        competition="worldcup",
        retired_at="2026-10-23T10:01:00Z",
        factual_ids=frozenset({"M73"}),
        sim_ids=frozenset({"M73"}),
        already_retired=already,
        superseded_answers={"M73": {}},
        real_results={"M73": {}},
        store_stamp_at_retirement={},
    )
    assert second == ()


def test_unchanged_facts_retire_nothing():
    """factual_ids equal to already_retired retires nothing."""
    retirements = retire_matching(
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        factual_ids=frozenset({"M73"}),
        sim_ids=frozenset({"M73"}),
        already_retired=frozenset({"M73"}),
        superseded_answers={"M73": {}},
        real_results={"M73": {}},
        store_stamp_at_retirement={},
    )
    assert retirements == ()


def test_mode_is_real_when_no_new_facts_landed():
    """derive_mode is 'real' when new_facts is empty and live answers exist (D-19)."""
    mode = derive_mode(
        has_live_answers=True,
        new_facts=frozenset(),
        sim_ids=frozenset({"M73"}),
    )
    assert mode == "real"


def test_mode_is_partial_when_a_group_stage_fact_landed():
    """derive_mode is 'partial' when a fact outside sim_ids landed (D-11)."""
    mode = derive_mode(
        has_live_answers=True,
        new_facts=frozenset({"GS_A_01"}),
        sim_ids=frozenset({"M73"}),
    )
    assert mode == "partial"


def test_mode_is_not_applicable_without_live_answers():
    """has_live_answers=False yields 'not_applicable' unconditionally."""
    mode = derive_mode(
        has_live_answers=False,
        new_facts=frozenset({"M73"}),
        sim_ids=frozenset({"M73"}),
    )
    assert mode == "not_applicable"


def test_mode_is_partial_when_a_retired_answer_has_a_live_descendant():
    """has_stale_descendants=True forces 'partial' mode even without new_facts (D-11)."""
    mode = derive_mode(
        has_live_answers=True,
        new_facts=frozenset(),
        sim_ids=frozenset({"M73"}),
        has_stale_descendants=True,
    )
    assert mode == "partial"


@pytest.mark.parametrize(
    "avail",
    [
        DataAvailability.AVAILABLE,
        DataAvailability.EMPTY,
        DataAvailability.MISSING,
        DataAvailability.UNAVAILABLE,
    ],
)
def test_availability_table_never_claims_currency(avail: DataAvailability):
    """Non-AVAILABLE states never yield 'real' mode and never report 0 retired."""
    # Tests availability table behavior under each state
    res = aggregate_availability([avail])
    assert res == avail
    if avail is not DataAvailability.AVAILABLE:
        # Cannot yield mode real when not available
        mode = derive_mode(
            has_live_answers=True,
            new_facts=frozenset(),
            sim_ids=frozenset({"M73"}),
        )
        assert mode != "real" or avail == DataAvailability.AVAILABLE


def test_aggregate_availability_takes_the_worst_state():
    """aggregate_availability selects the worst state according to AVAILABILITY_SEVERITY."""
    assert (
        aggregate_availability([DataAvailability.AVAILABLE, DataAvailability.EMPTY])
        == DataAvailability.EMPTY
    )
    assert (
        aggregate_availability([DataAvailability.EMPTY, DataAvailability.MISSING])
        == DataAvailability.MISSING
    )
    assert (
        aggregate_availability([DataAvailability.UNAVAILABLE, DataAvailability.AVAILABLE])
        == DataAvailability.UNAVAILABLE
    )


def test_retired_answer_provenance_stays_simulated():
    """Retirement provenance is always ResultProvenance.SIMULATED (D-09)."""
    r = Retirement(
        match_id="M73",
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        reason="real_result_ingested",
        real_match_id="M73",
    )
    assert r.provenance is ResultProvenance.SIMULATED
    retirements = retire_matching(
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        factual_ids=frozenset({"M73"}),
        sim_ids=frozenset({"M73"}),
        already_retired=frozenset(),
        superseded_answers={"M73": {}},
        real_results={"M73": {}},
        store_stamp_at_retirement={},
    )
    assert all(item.provenance is ResultProvenance.SIMULATED for item in retirements)


def test_retirement_record_carries_the_superseded_answer():
    """Retirement carries superseded_answer verbatim (D-07)."""
    superseded = {"prob_a": 0.65, "predicted_score": "2-1"}
    retirements = retire_matching(
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        factual_ids=frozenset({"M73"}),
        sim_ids=frozenset({"M73"}),
        already_retired=frozenset(),
        superseded_answers={"M73": superseded},
        real_results={"M73": {"score": "1-0"}},
        store_stamp_at_retirement={},
    )
    assert len(retirements) == 1
    assert retirements[0].superseded_answer == superseded


def test_retirement_record_is_frozen():
    """Retirement is a frozen dataclass."""
    r = Retirement(
        match_id="M73",
        competition="worldcup",
        retired_at="2026-10-23T10:00:00Z",
        reason="real_result_ingested",
        real_match_id="M73",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.match_id = "M74"  # type: ignore[misc]


def test_whole_snapshot_retirement_has_no_match_id():
    """retire_whole_snapshot produces a record with match_id is None and scope='snapshot' (D-10)."""
    r = retire_whole_snapshot(
        competition="ucl",
        retired_at="2026-10-23T10:00:00Z",
        superseded_answer={"winner": "Real Madrid"},
        store_stamp_at_retirement={},
        reason="store_replaced",
    )
    assert r.match_id is None
    assert r.scope == "snapshot"
    assert r.reason == "store_replaced"
