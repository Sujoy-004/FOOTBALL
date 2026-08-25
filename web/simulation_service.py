"""Shared simulation request orchestration (Exchange 4).

One task registry, one thread lifecycle, one progress protocol, and one
canonical status vocabulary for every competition's /api/simulate endpoint.

Layering: this is an APP-support module (threads, locks, HTTP-shaped
payloads). football_core stays engine-pure; competition brains keep their
own runners, eligibility logic, cache stores, and snapshot writers.

Canonical wire vocabulary (single field, shipped with matching frontend):

    not_requested  no simulation has been requested this session
    running        accepted and executing in a background thread
    completed      simulation finished successfully
    not_needed     competition fully determined by real results
    unavailable    required fixtures/data genuinely missing
    failed         runner raised; diagnostics in ``error``
    validation_error  invalid count/seed (HTTP 400)

Legacy strings (none/starting/started/complete/error/no_unplayed_matches/
no_outstanding_outcomes/invalid_request) were retired together with the
frontend consumers in the same commit.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Optional

from football_core.simulation import (
    SimulationContractError,
    validate_n_simulations,
)

# progress callback handed to runners: (iteration, total_iterations, stage)
ProgressCB = Callable[[int, int, str], None]
Runner = Callable[[ProgressCB, int, Optional[int]], dict]
EligibilityFn = Callable[[], tuple[bool, Optional[str], str]]
OnResult = Callable[[dict, int, Optional[int]], dict]


class SimulationTaskService:
    """Owns task ids, the in-flight registry, worker threads, and the
    normalized progress shape. Competition apps supply runner/eligibility/
    on_result closures bound to their own module state."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(
        self,
        *,
        competition_id: str,
        raw_count: Any,
        default_count: int,
        seed: Any,
        runner: Runner,
        eligibility_fn: EligibilityFn,
        on_result: OnResult,
        options: Optional[dict] = None,
        extra_ack: Optional[dict] = None,
    ) -> tuple[int, dict]:
        """Validate, gate on eligibility, spawn the worker.

        Returns ``(http_status, payload)`` ready for JSONResponse. Count
        parsing mirrors the historical endpoints: explicit None falls back
        to *default_count*, but a literal falsy value like 0 reaches
        validation and is rejected (never silently defaulted).
        """
        count_value = raw_count
        if count_value is None:
            count_value = default_count
        try:
            count = validate_n_simulations(int(count_value))
        except SimulationContractError as exc:
            return 400, {
                "status": "validation_error",
                "state": "validation_error",
                "error": f"invalid simulation count {count_value!r}: {exc}",
            }
        except (TypeError, ValueError) as exc:
            return 400, {
                "status": "validation_error",
                "state": "validation_error",
                "error": f"invalid simulation count {count_value!r}: {exc}",
            }

        resolved_seed: Optional[int]
        if seed is None:
            resolved_seed = None  # engine generates one; returned on completion
        else:
            try:
                resolved_seed = int(seed)
            except (TypeError, ValueError) as exc:
                return 400, {
                    "status": "validation_error",
                    "state": "validation_error",
                    "error": f"invalid seed {seed!r}: {exc}",
                }

        eligible, reason_code, message = eligibility_fn()
        if not eligible:
            payload = {
                "status": "not_needed",
                "state": "not_needed",
                "reason": reason_code,
                "message": message,
                "requested": False,
            }
            payload.update(extra_ack or {})
            return 200, payload

        task_id = str(uuid.uuid4())
        with self._lock:
            self._tasks[task_id] = {
                "competition": competition_id,
                "status": "running",
                "progress": 0.0,
                "iteration": 0,
                "total_iterations": count,
                "stage": "Starting...",
                "t0": time.time(),
                "elapsed": 0.0,
                "error": None,
                "result": None,
            }

        options = dict(options or {})

        def _worker() -> None:
            def progress_cb(done: int, total: int, stage: str = "") -> None:
                with self._lock:
                    entry = self._tasks.get(task_id)
                    if entry is None:
                        return
                    if isinstance(total, int) and total > 0:
                        entry["total_iterations"] = total
                        entry["iteration"] = max(0, min(int(done), total))
                        entry["progress"] = round(min(100.0, done / total * 100.0), 2)
                    if stage:
                        entry["stage"] = stage
                    entry["elapsed"] = round(time.time() - entry["t0"], 2)

            try:
                result = runner(progress_cb, count, resolved_seed)
                summary = on_result(result, count, resolved_seed) or {}
                with self._lock:
                    entry = self._tasks[task_id]
                    entry["status"] = "completed"
                    entry["progress"] = 100.0
                    entry["elapsed"] = round(time.time() - entry["t0"], 2)
                    entry["result"] = {"status": "completed", **summary}
            except Exception as exc:  # fail fast; no partial results emitted
                with self._lock:
                    entry = self._tasks[task_id]
                    entry["status"] = "failed"
                    entry["error"] = str(exc)
                    entry["elapsed"] = round(time.time() - entry["t0"], 2)

        threading.Thread(target=_worker, daemon=True).start()

        payload = {
            "task_id": task_id,
            "status": "running",
            "state": "running",
            "requested": True,
            "requested_count": count,
            "count": count,
            "seed": resolved_seed,
            **options,
            **(extra_ack or {}),
        }
        return 200, payload

    def poll(self, task_id: str) -> dict:
        """Unified progress shape; terminal states are cleaned up
        unconditionally (fixes the historical leak-on-missing-result)."""
        with self._lock:
            entry = self._tasks.get(task_id)
            if entry is None:
                return {"status": "not_found", "state": "not_found",
                        "error": "task not found"}
            snapshot = {
                "task_id": task_id,
                "status": entry["status"],
                "state": entry["status"],
                "progress": entry["progress"],
                "iteration": entry["iteration"],
                "total_iterations": entry["total_iterations"],
                "stage": entry.get("stage", ""),
                "elapsed": entry.get("elapsed", 0.0),
                "error": entry.get("error"),
                "result": entry.get("result"),
            }
            if entry["status"] in ("completed", "failed"):
                del self._tasks[task_id]
            return snapshot


def build_simulation_meta(
    *,
    requested_count: int,
    actual_count: int | None,
    seed: int | None,
    provenance_extra: Optional[dict] = None,
    engine_version: str | None = None,
    extra: Optional[dict] = None,
) -> dict:
    """The shared COMPLETED metadata block every competition surfaces."""
    meta = {
        "requested": True,
        "status": "completed",
        "requested_count": requested_count,
        "count": actual_count if actual_count is not None else requested_count,
        "seed": seed,
        "provenance": {
            "real_results_preserved": True,
            "simulated_matches_only": True,
            **(provenance_extra or {}),
        },
    }
    if engine_version:
        meta["engine_version"] = engine_version
    if extra:
        meta.update(extra)
    return meta
