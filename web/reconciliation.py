"""The ONE owner of the invalidation decision (Phase 5, RECON-02).

The competition brains REPORT what changed as plain data on their
``IngestReport``; this module DECIDES which simulated answers that
supersedes, PERSISTS the decision, and PUBLISHES the result. No brain
imports this module and no brain may call it — the edge is a DATA edge.

Ground rules: the DECISION is pure and lives in ``football_core.reconcile``
(stdlib only, competition-agnostic); this module is the web-layer OWNER —
it knows the ledger path, the store paths and the holder, and it is the
only place a retirement is applied.

Ordering discipline (D-03): the durable ledger write lands BEFORE the
in-memory rebind. A crash between them converges on the next boot; the
reverse resurrects a retired answer.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import football_core.state
from football_core.domain import DataAvailability, load_json_store
from football_core.reconcile import (
    Retirement,
    aggregate_availability,
    assemble_reconciliation,
    retire_matching,
    retire_whole_snapshot,
)
from football_core.store_stamp import StoreStamp, sub_stamp
import web.derived.holder as holder
from web.derived.holder import publish_sim_state

logger = logging.getLogger(__name__)

# The single lock guarding retirement ledger updates.
_LEDGER_LOCK = threading.Lock()

# Explicit marker for corrupt/unreadable ledger payload
UNREADABLE = "unreadable"


def _atomic_write(*args: Any, **kwargs: Any) -> None:
    """Write atomically to disk, looking up atomic_write_text dynamically for monkeypatching."""
    getattr(football_core.state, "atomic_write_text")(*args, **kwargs)


def _no_ids(_payload: Any) -> frozenset[str]:
    """Default extractor for when no sim match ids can be found."""
    if not isinstance(_payload, Mapping):
        return frozenset()
    # Try full_bracket
    fb = _payload.get("full_bracket")
    if isinstance(fb, Mapping):
        rounds = fb.get("rounds")
        if isinstance(rounds, Mapping):
            ids = set()
            for r_matches in rounds.values():
                if isinstance(r_matches, (list, tuple)):
                    for m in r_matches:
                        if isinstance(m, Mapping) and "match_id" in m:
                            ids.add(str(m["match_id"]))
            if ids:
                return frozenset(ids)
    matches = _payload.get("matches")
    if isinstance(matches, (list, tuple)):
        return frozenset(str(m["match_id"]) for m in matches if isinstance(m, Mapping) and "match_id" in m)
    elif isinstance(matches, Mapping):
        return frozenset(str(k) for k in matches.keys())
    return frozenset()


def _no_rows(_payload: Any) -> Mapping[str, Any]:
    """Default extractor for when no rows/answers can be found."""
    if not isinstance(_payload, Mapping):
        return {}
    if "matches" in _payload and isinstance(_payload["matches"], Mapping):
        return {str(k): dict(v) if isinstance(v, Mapping) else v for k, v in _payload["matches"].items()}
    if "matches" in _payload and isinstance(_payload["matches"], (list, tuple)):
        return {str(m["match_id"]): dict(m) for m in _payload["matches"] if isinstance(m, Mapping) and "match_id" in m}
    if isinstance(_payload, Mapping) and all(isinstance(v, Mapping) for v in _payload.values()) and "full_bracket" not in _payload:
        return {str(k): dict(v) for k, v in _payload.items()}
    fb = _payload.get("full_bracket")
    if isinstance(fb, Mapping):
        rounds = fb.get("rounds")
        if isinstance(rounds, Mapping):
            answers: dict[str, Any] = {}
            for r_matches in rounds.values():
                if isinstance(r_matches, (list, tuple)):
                    for m in r_matches:
                        if isinstance(m, Mapping) and "match_id" in m:
                            answers[str(m["match_id"])] = dict(m)
            return answers
    matches = _payload.get("matches")
    if isinstance(matches, (list, tuple)):
        return {str(m["match_id"]): dict(m) for m in matches if isinstance(m, Mapping) and "match_id" in m}
    elif isinstance(matches, Mapping):
        return {str(k): dict(v) if isinstance(v, Mapping) else v for k, v in matches.items()}
    meta = _payload.get("simulation_meta")
    if isinstance(meta, Mapping):
        return {
            "seed": meta.get("seed"),
            "n_simulations": meta.get("n_simulations"),
            "provenance": "simulated",
        }
    return {}


def _never_stale(retired_ids: frozenset[str], payload: Any) -> bool:
    """Check if any simulated match still valid depends on a retired match."""
    if not retired_ids or not isinstance(payload, Mapping):
        return False
    fb = payload.get("full_bracket")
    if isinstance(fb, Mapping):
        rounds = fb.get("rounds")
        if isinstance(rounds, Mapping):
            for r_matches in rounds.values():
                if isinstance(r_matches, (list, tuple)):
                    for m in r_matches:
                        if isinstance(m, Mapping) and m.get("match_id") not in retired_ids:
                            srcs = m.get("source_matches") or []
                            if any(src in retired_ids for src in srcs):
                                return True
    return False


@dataclass(frozen=True)
class ResultStore:
    role: str
    path: Path
    ids: Callable[[Any], frozenset[str]]
    rows: Callable[[Any], Mapping[str, Any]] = _no_rows


@dataclass(frozen=True)
class ReconciliationSpec:
    competition: str
    ledger_path: Path
    result_stores: tuple[ResultStore, ...]
    observed_stamp: Callable[[], StoreStamp]
    granularity: str = "match"                     # "match" | "snapshot"
    sim_ids: Callable[[Any], frozenset[str]] = _no_ids
    sim_answers: Callable[[Any], Mapping[str, Any]] = _no_rows
    snapshot_summary: Callable[[Any], Mapping[str, Any]] = _no_rows
    stale_descendants: Callable[[frozenset[str], Any], bool] = _never_stale


def retirement_ledger_path(data_dir: Path) -> Path:
    """``competitions/<id>/data/retirements.json`` — the D-08 path.

    Competition-scoped, NOT season-scoped: the ledger is the competition's
    retirement history and one file holds every run's tombstones. A record
    does NOT carry its own season — the frozen ``Retirement`` dataclass has
    no season field, and the competition's active-season pointer owns the
    season question (a season switch retires the run with
    ``reason="store_replaced"`` instead).
    """
    return Path(data_dir) / "retirements.json"


def _utc_now() -> str:
    """ISO-8601 UTC with a ``Z`` suffix — the project's timestamp form."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_ledger_unlocked(path: Path) -> dict:
    """Read and parse the ledger. Caller may or may not hold the lock.

    Never raises: a file that has never been written is legitimately ``{}``
    (nothing recorded), while anything unreadable is logged with
    ``logger.exception`` and returned as the explicit marker — the exception
    CLASS NAME only, never the message (no path, no token leak).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - the marker IS the contract
        logger.exception("retirement ledger unreadable at %s", path)
        return {"ledger": UNREADABLE, "detail": exc.__class__.__name__}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("ledger root must be a JSON object")
    except Exception as exc:  # noqa: BLE001 - corrupt content
        logger.exception("retirement ledger unreadable at %s", path)
        return {"ledger": UNREADABLE, "detail": exc.__class__.__name__}
    return data


def read_ledger(path: Path) -> dict:
    """Read the retirement ledger under the lock."""
    with _LEDGER_LOCK:
        return _read_ledger_unlocked(Path(path))


def _record_to_dict(record: Retirement) -> dict:
    """A ``Retirement`` as a JSON-safe dict.

    ``provenance`` is written as its ``.value`` — it is ALWAYS
    ``"simulated"`` (D-09). ``store_stamp_at_retirement`` is the role-keyed
    ``{role: [mtime_ns, size]}`` mapping — never a filesystem path.
    """
    return {
        "match_id": record.match_id,
        "competition": record.competition,
        "retired_at": record.retired_at,
        "reason": record.reason,
        "real_match_id": record.real_match_id,
        "superseded_answer": dict(record.superseded_answer) if record.superseded_answer else {},
        "real_result": dict(record.real_result) if record.real_result else {},
        "store_stamp_at_retirement": dict(record.store_stamp_at_retirement) if record.store_stamp_at_retirement else {},
        "scope": record.scope,
        "provenance": record.provenance.value,
    }


def append_retirements(path: Path, competition: str,
                       records: tuple[Retirement, ...]) -> dict:
    """Append retirement records to the ledger — APPEND-ONLY (D-08).

    The whole read-modify-write happens under :data:`_LEDGER_LOCK` and
    lands through ``atomic_write_text``, so a concurrent writer can never
    observe — or clobber — a half-updated payload. The list is NEVER
    shrunk: a retirement is a tombstone beside the answer, never a deletion.

    Raises:
        Exception: Re-raised after ``logger.exception`` — a lost write must
            never look like a successful one (D-03).
    """
    ledger = Path(path)
    with _LEDGER_LOCK:
        try:
            payload = _read_ledger_unlocked(ledger)
            if payload.get("ledger") == UNREADABLE:
                logger.warning(
                    "retirement ledger was unreadable; rewriting from scratch: %s",
                    ledger,
                )
                payload = {}
            existing = payload.get("retirements")
            if not isinstance(existing, list):
                existing = []
            payload["schema"] = 1
            payload["competition"] = competition
            payload.setdefault("created_at", _utc_now())
            for record in records:
                existing.append(_record_to_dict(record))
            payload["retirements"] = existing
            _atomic_write(
                ledger,
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            )
        except Exception:
            logger.exception(
                "retirement ledger update FAILED (%s[%s])", ledger, competition
            )
            raise
    return payload


def _store_availability(spec: ReconciliationSpec) -> dict[str, str]:
    """``store filename -> availability`` for every results store."""
    out: dict[str, str] = {}
    for store in spec.result_stores:
        _payload, availability, _detail = load_json_store(store.path)
        out[store.path.name] = availability.value
    return out


def _run_key(spec: ReconciliationSpec, payload: Mapping[str, Any]) -> str:
    """The identity of the PUBLISHED RUN: ``<competition>:<seed>``."""
    meta = payload.get("simulation_meta") or {}
    return f"{spec.competition}:{meta.get('seed')}"


def _stamp_dict(stamp: Any) -> dict:
    """Normalise a stamp to its role-keyed ``{role: [mtime_ns, size]}`` dict."""
    if stamp is None:
        return {}
    if isinstance(stamp, Mapping):
        return dict(stamp)
    as_dict = getattr(stamp, "as_dict", None)
    return dict(as_dict()) if callable(as_dict) else {}


def reconcile_now(spec: ReconciliationSpec, *, report: dict | None = None,
                  reason: str = "real_result_ingested") -> dict:
    """Decide, persist and publish a reconciliation pass (D-03)."""
    state = holder.read_sim_state(spec.competition)
    payload = dict(state.get("payload") or {})
    ledger = read_ledger(spec.ledger_path)
    ledger_records = [r for r in (ledger.get("retirements") or []) if isinstance(r, dict)]

    stores = _store_availability(spec)
    factual_ids: set[str] = set()
    rows_by_id: dict[str, Any] = {}
    store_states: dict[str, DataAvailability] = {}

    for store in spec.result_stores:
        data, availability, _detail = load_json_store(store.path)
        store_states[store.role] = availability
        if availability is DataAvailability.AVAILABLE and data is not None:
            factual_ids.update(store.ids(data))
            rows_by_id.update(store.rows(data))

    aggregate = aggregate_availability(store_states.values())
    raw_data = holder.read_data(spec.competition)
    raw_state = holder._STATES.get(spec.competition)
    healthy = (raw_state is None) or (bool(raw_data) and ("error" not in raw_data))
    not_established = not healthy
    all_available = all(st is DataAvailability.AVAILABLE for st in store_states.values())

    sim_ids = spec.sim_ids(payload)
    already_retired = {r.get("match_id") for r in ledger_records if r.get("match_id")}
    sim_facts = frozenset(payload.get("sim_facts") or ())
    new_facts = frozenset(factual_ids) - sim_facts

    roles = {store.role for store in spec.result_stores}
    sub = sub_stamp(spec.observed_stamp(), roles)
    stamp_dict = sub.as_dict() if sub is not None else {}

    records: tuple[Retirement, ...] = ()
    if not not_established and bool(payload):
        if spec.granularity == "match":
            records = retire_matching(
                competition=spec.competition,
                retired_at=_utc_now(),
                factual_ids=frozenset(factual_ids),
                sim_ids=sim_ids,
                already_retired=frozenset(already_retired),
                superseded_answers=spec.sim_answers(payload),
                real_results=rows_by_id,
                store_stamp_at_retirement=stamp_dict,
                reason=reason,
            )
        elif spec.granularity == "snapshot":
            run_key = _run_key(spec, payload)
            already_retired_runs = {
                f"{spec.competition}:{(r.get('superseded_answer') or {}).get('seed')}"
                for r in ledger_records
                if isinstance(r, dict) and r.get("scope") == "snapshot"
            }
            if run_key not in already_retired_runs:
                records = (retire_whole_snapshot(
                    competition=spec.competition,
                    retired_at=_utc_now(),
                    superseded_answer=spec.snapshot_summary(payload),
                    store_stamp_at_retirement=stamp_dict,
                    reason=reason,
                ),)
            else:
                records = ()

    # DURABLE FIRST
    if records:
        append_retirements(spec.ledger_path, spec.competition, records)

    retired_ids = {r.match_id for r in records if r.match_id}
    still_valid = sim_ids - (already_retired | retired_ids)

    verdict = assemble_reconciliation(
        retired=records,
        still_valid=still_valid,
        availability=aggregate,
        has_live_answers=bool(payload) and bool(sim_ids),
        new_facts=new_facts,
        sim_ids=sim_ids,
        has_stale_descendants=spec.stale_descendants(frozenset(already_retired | retired_ids), payload),
        whole_snapshot_retired=(spec.granularity == "snapshot" and bool(records)),
        not_established=not_established,
    )

    if not all_available and verdict.mode == "real":
        verdict = replace(verdict, mode="partial")

    verdict_dict = {
        "mode": verdict.mode,
        "availability": verdict.availability.value,
        "still_valid": list(verdict.still_valid),
        "not_established": verdict.not_established,
        "whole_snapshot_retired": verdict.whole_snapshot_retired,
        "stores": dict(stores),
        "observed_stamp": dict(stamp_dict),
    }

    # REBIND SECOND
    publish_sim_state(spec.competition, payload=payload, tombstones=tuple(records),
                      reconciliation=verdict_dict, mode=verdict.mode)

    return reconciliation_block(spec)


def reconcile_if_needed(spec: ReconciliationSpec) -> dict:
    """Reconcile on the READ path, if the facts moved since the last look."""
    state = holder.read_sim_state(spec.competition)
    if not state:
        return reconciliation_block(spec)
    roles = {store.role for store in spec.result_stores}
    observed = sub_stamp(spec.observed_stamp(), roles)
    observed_dict = _stamp_dict(observed)
    recorded = (state.get("reconciliation") or {}).get("observed_stamp")
    if recorded is None:
        recorded = _stamp_dict(state.get("payload", {}).get("sim_results_stamp"))
    if observed_dict == recorded:
        return reconciliation_block(spec)
    return reconcile_now(spec)


def reconciliation_block(spec: ReconciliationSpec) -> dict:
    """The API-facing reconciliation block (C-05)."""
    ledger = read_ledger(spec.ledger_path)
    records = [r for r in (ledger.get("retirements") or []) if isinstance(r, dict)]
    state = holder.read_sim_state(spec.competition)
    verdict = dict(state.get("reconciliation") or {}) if state else {}
    raw_data = holder.read_data(spec.competition)
    raw_state = holder._STATES.get(spec.competition)
    healthy = (raw_state is None) or (bool(raw_data) and ("error" not in raw_data))
    not_established = (not healthy) or bool(verdict.get("not_established", False))
    stores = _store_availability(spec)

    mode = verdict.get("mode") or (state.get("mode") if state else None) or "simulated"

    block: dict[str, Any] = {
        "provenance": "simulated" if records or (state and state.get("payload")) else None,
        "retired": records,
        "still_simulated": list(verdict.get("still_valid") or []),
        "stores": stores,
        "not_established": not_established,
        "mode": mode,
    }
    if not_established:
        block["reconciliation_status"] = "reconciliation not established"
        return block
    if not verdict and not records:
        block["reconciliation_status"] = "not_applicable"
        return block
    block["reconciliation_status"] = "established"
    if records:
        block["retired_count"] = len(records)
    elif verdict:
        block["retired_count"] = 0

    return block
