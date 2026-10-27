"""Pure reconciliation kernel contract (Phase 5, RECON-01/RECON-02/C-02).

Design rules:
* Set algebra for retirement: intersection of factual match ids and simulated match ids minus already retired ids.
* Single source of truth for retirement mode derivation.
* Frozen dataclasses: Retirement and Reconciliation.
* DataAvailability aggregation taking the most severe state.

Ground rules: stdlib only — no ``web`` imports and no ``competitions``
imports, and no repo-path knowledge. Callers pass all paths and dictionaries,
which keeps the kernel competition-agnostic. The layering guard
(``tests/test_layering_architecture.py``) enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from football_core.domain import DataAvailability, ResultProvenance

#: Severity order used to aggregate per-store availability into one verdict.
AVAILABILITY_SEVERITY: tuple[DataAvailability, ...] = (
    DataAvailability.AVAILABLE,
    DataAvailability.EMPTY,
    DataAvailability.UNAVAILABLE,
    DataAvailability.MISSING,
)


@dataclass(frozen=True)
class Retirement:
    """A simulated answer superseded by a real result. Never deleted (D-07).

    Attributes:
        match_id: Identifier of the superseded simulated match (None for snapshot).
        competition: Competition identifier.
        retired_at: ISO-8601 UTC timestamp of retirement.
        reason: Machine-readable reason for retirement.
        real_match_id: Real fixture/match id that superseded this answer.
        store_stamp_at_retirement: Store stamp captured when retirement occurred.
        provenance: Always SIMULATED.
        superseded_answer: Verbatim superseded simulated answer payload.
        scope: "match" or "snapshot".
        real_result: Optional stored real result row.
    """

    match_id: Optional[str]
    competition: str
    retired_at: str
    reason: str
    real_match_id: Optional[str]
    store_stamp_at_retirement: Mapping[str, Any] = field(default_factory=dict)
    provenance: ResultProvenance = ResultProvenance.SIMULATED
    superseded_answer: Mapping[str, Any] = field(default_factory=dict)
    scope: str = "match"
    real_result: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class Reconciliation:
    """The honest verdict for one competition (D-19).

    Attributes:
        retired: Tuple of Retirement records.
        still_valid: Tuple of simulated match ids that remain valid.
        mode: "real" | "partial" | "not_applicable".
        availability: Aggregated DataAvailability.
        whole_snapshot_retired: Whether the whole simulation snapshot was retired.
        not_established: Carrier for unestablished reconciliation state (D-13).
    """

    retired: tuple[Retirement, ...]
    still_valid: tuple[str, ...]
    mode: str
    availability: DataAvailability
    whole_snapshot_retired: bool = False
    not_established: bool = False


def derive_mode(
    *,
    has_live_answers: bool,
    new_facts: frozenset[str],
    sim_ids: frozenset[str],
    has_stale_descendants: bool = False,
    availability: DataAvailability = DataAvailability.AVAILABLE,
) -> str:
    """Derive the reconciliation mode string."""
    if not has_live_answers:
        return "not_applicable"
    if availability is not DataAvailability.AVAILABLE:
        return "partial"
    uncovered = new_facts - sim_ids
    if uncovered:
        # A real fact landed that the simulation does not cover (the World
        # Cup group-stage case) - the verdict must NOT imply currency.
        return "partial"
    if has_stale_descendants:
        # A retired answer's descendant is still simulated (a corrected
        # upstream result left a downstream answer stale).
        return "partial"
    return "real"


def retire_matching(
    *,
    competition: str,
    retired_at: str,
    factual_ids: frozenset[str],
    sim_ids: frozenset[str],
    already_retired: frozenset[str],
    superseded_answers: Mapping[str, Any],
    real_results: Mapping[str, Any],
    store_stamp_at_retirement: Mapping[str, Any],
    reason: str = "real_result_ingested",
) -> tuple[Retirement, ...]:
    """Retire simulation answers matching new factual ids."""
    covered = (factual_ids & sim_ids) - already_retired
    return tuple(
        Retirement(
            match_id=mid,
            competition=competition,
            retired_at=retired_at,
            reason=reason,
            real_match_id=mid,
            store_stamp_at_retirement=store_stamp_at_retirement,
            provenance=ResultProvenance.SIMULATED,
            superseded_answer=superseded_answers.get(mid, {}),
            real_result=real_results.get(mid),
            scope="match",
        )
        for mid in sorted(covered)
    )


def retire_whole_snapshot(
    *,
    competition: str,
    retired_at: str,
    superseded_answer: Mapping[str, Any],
    store_stamp_at_retirement: Mapping[str, Any],
    reason: str = "store_replaced",
) -> Retirement:
    """Retire an entire simulation snapshot."""
    return Retirement(
        match_id=None,
        competition=competition,
        retired_at=retired_at,
        reason=reason,
        real_match_id=None,
        store_stamp_at_retirement=store_stamp_at_retirement,
        provenance=ResultProvenance.SIMULATED,
        superseded_answer=superseded_answer,
        scope="snapshot",
        real_result=None,
    )


def aggregate_availability(
    availabilities: Iterable[DataAvailability],
) -> DataAvailability:
    """Aggregate multiple DataAvailability values taking the worst state."""
    worst = DataAvailability.AVAILABLE
    for state in availabilities:
        candidate = DataAvailability(state)
        if AVAILABILITY_SEVERITY.index(candidate) > AVAILABILITY_SEVERITY.index(worst):
            worst = candidate
    return worst


def assemble_reconciliation(
    *,
    retired: Iterable[Retirement],
    still_valid: Iterable[str],
    availability: DataAvailability,
    has_live_answers: bool,
    new_facts: frozenset[str],
    sim_ids: frozenset[str],
    has_stale_descendants: bool = False,
    whole_snapshot_retired: bool = False,
    not_established: bool = False,
) -> Reconciliation:
    """Assemble a Reconciliation verdict."""
    mode = derive_mode(
        has_live_answers=has_live_answers,
        new_facts=new_facts,
        sim_ids=sim_ids,
        has_stale_descendants=has_stale_descendants,
        availability=availability,
    )
    return Reconciliation(
        retired=tuple(retired),
        still_valid=tuple(still_valid),
        mode=mode,
        availability=availability,
        whole_snapshot_retired=whole_snapshot_retired,
        not_established=not_established,
    )
