"""Shared simulation task service — the run-response contract (Phase 4, 04-05).

``web.simulation_service.SimulationTaskService`` is the ONE place a run
response is shaped, so every competition app inherits the same contract:

* **SIM-02 / D-11** — an omitted seed is generated SERVER-SIDE and RETURNED
  (the client can copy it to reproduce the run), and every response carries
  ``seed``, ``n_simulations`` and ``provenance == "simulated"``.
* **D-12** — a second concurrent run for the same competition is REJECTED
  with a specific error instead of queueing a second CPU-bound run.
* **D-13** — a failing runner surfaces its exact message, never a vague
  "simulation failed".
* **D-14** — the runner receives the resolved ``(count, seed)`` binding ONCE,
  at run start, so the run is reproducible from the value that was returned.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from football_core.domain import ResultProvenance
from web.simulation_service import SimulationTaskService

#: How long a test waits for a background worker to reach a terminal state.
_WAIT_SECONDS = 10.0


def _eligible() -> tuple[bool, Optional[str], str]:
    return True, None, ""


def _not_eligible() -> tuple[bool, Optional[str], str]:
    return False, "no_unplayed_matches", "simulation not needed - no unplayed matches"


def _on_result(result: dict, count: int, seed: Optional[int]) -> dict:
    return {"echo": result.get("ok"), "count": count, "seed": seed}


class _Recorder:
    """A runner stub that records the ``(count, seed)`` binding it receives.

    Args:
        gate: When given, the runner blocks on it until the test releases it —
            the handle that keeps a run "in flight" for the D-12 gate.
        error: When given, the runner raises it (the D-13 path).
    """

    def __init__(self, gate: Optional[threading.Event] = None,
                 error: Optional[BaseException] = None) -> None:
        self.calls: list[tuple[int, Optional[int]]] = []
        self.gate = gate
        self.error = error
        self.called = threading.Event()

    def __call__(self, progress_cb: Any, count: int, seed: Optional[int]) -> dict:
        self.calls.append((count, seed))
        self.called.set()
        if self.gate is not None:
            self.gate.wait(timeout=_WAIT_SECONDS)
        if self.error is not None:
            raise self.error
        return {"ok": True}


def _start(service: SimulationTaskService, runner: _Recorder, *,
           competition_id: str = "ucl", raw_count: Any = 7, seed: Any = None,
           eligibility_fn: Any = _eligible) -> tuple[int, dict]:
    """Start one run through the shared service and return ``(status, ack)``."""
    return service.start(
        competition_id=competition_id,
        raw_count=raw_count,
        default_count=5,
        seed=seed,
        runner=runner,
        eligibility_fn=eligibility_fn,
        on_result=_on_result,
    )


def _poll_until_terminal(service: SimulationTaskService, task_id: str) -> dict:
    """Poll *task_id* until it reaches a terminal state and return that poll."""
    deadline = time.time() + _WAIT_SECONDS
    while time.time() < deadline:
        payload = service.poll(task_id)
        if payload.get("status") in ("completed", "failed"):
            return payload
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} never reached a terminal state")


class TestRunResponseContract:
    """SIM-02 / D-11: the run response declares seed, count and provenance."""

    def test_omitted_seed_is_generated_and_returned(self):
        """An omitted seed is generated server-side and handed back."""
        recorder = _Recorder()
        service = SimulationTaskService()
        status, ack = _start(service, recorder, seed=None)

        assert status == 200
        assert isinstance(ack["seed"], int), ack
        assert ack["seed"] > 0, ack
        assert ack["n_simulations"] == 7, ack
        assert ack["provenance"] == ResultProvenance.SIMULATED.value, ack
        assert ack["provenance"] == "simulated"

    def test_explicit_seed_is_echoed(self):
        """An explicit seed is echoed verbatim (the reproducibility handle)."""
        recorder = _Recorder()
        service = SimulationTaskService()
        status, ack = _start(service, recorder, seed=4242)

        assert status == 200
        assert ack["seed"] == 4242, ack
        assert ack["n_simulations"] == 7, ack
        assert ack["provenance"] == "simulated", ack

    def test_completed_result_carries_the_same_contract(self):
        """The terminal result repeats the ack's contract fields."""
        recorder = _Recorder()
        service = SimulationTaskService()
        _status, ack = _start(service, recorder, seed=99)
        assert recorder.called.wait(timeout=_WAIT_SECONDS)

        payload = _poll_until_terminal(service, ack["task_id"])
        assert payload["status"] == "completed", payload
        result = payload["result"]
        assert result["status"] == "completed", result
        assert result["n_simulations"] == 7, result
        assert result["seed"] == 99, result
        assert result["provenance"] == "simulated", result


class TestInFlightGate:
    """D-12: a second concurrent run for one competition is rejected."""

    def test_second_run_rejected_when_in_flight(self):
        gate = threading.Event()
        recorder = _Recorder(gate=gate)
        service = SimulationTaskService()
        try:
            status, ack = _start(service, recorder, seed=1)
            assert status == 200, ack
            assert recorder.called.wait(timeout=_WAIT_SECONDS)

            status2, payload = _start(service, recorder, seed=2)
            assert status2 == 409, payload
            error = payload["error"]
            assert "already" in error.lower(), error
            assert "in flight" in error.lower(), error
            # The rejected run never reached the runner.
            assert len(recorder.calls) == 1, recorder.calls
        finally:
            gate.set()

    def test_in_flight_gate_is_scoped_to_one_competition(self):
        """A run for another competition is not blocked by an in-flight run."""
        gate = threading.Event()
        recorder = _Recorder(gate=gate)
        service = SimulationTaskService()
        try:
            status, _ack = _start(service, recorder, competition_id="ucl", seed=1)
            assert status == 200
            assert recorder.called.wait(timeout=_WAIT_SECONDS)

            status2, payload = _start(service, recorder, competition_id="laliga", seed=2)
            assert status2 == 200, payload
        finally:
            gate.set()

    def test_a_finished_run_does_not_block_the_next_one(self):
        """The gate is about IN-FLIGHT runs, not about history."""
        recorder = _Recorder()
        service = SimulationTaskService()
        _status, ack = _start(service, recorder, seed=1)
        assert recorder.called.wait(timeout=_WAIT_SECONDS)
        _poll_until_terminal(service, ack["task_id"])

        status2, _payload = _start(service, recorder, seed=2)
        assert status2 == 200


class TestSpecificErrors:
    """D-13: errors name the specific problem."""

    def test_runner_error_surfaces_exact_message(self):
        message = "Cannot simulate - group stage results are MISSING"
        recorder = _Recorder(error=RuntimeError(message))
        service = SimulationTaskService()
        _status, ack = _start(service, recorder, seed=1)
        assert recorder.called.wait(timeout=_WAIT_SECONDS)

        payload = _poll_until_terminal(service, ack["task_id"])
        assert payload["status"] == "failed", payload
        assert payload["error"] == message, payload

    def test_ineligible_run_reports_not_needed_with_specific_message(self):
        recorder = _Recorder()
        service = SimulationTaskService()
        status, payload = _start(service, recorder, seed=1,
                                 eligibility_fn=_not_eligible)

        assert status == 200, payload
        assert payload["status"] == "not_needed", payload
        assert payload["reason"] == "no_unplayed_matches", payload
        assert "no unplayed matches" in payload["message"].lower(), payload
        # An ineligible competition never spawns a runner.
        assert recorder.calls == []

    def test_invalid_seed_is_rejected_before_any_run(self):
        recorder = _Recorder()
        service = SimulationTaskService()
        status, payload = _start(service, recorder, seed="not-a-number")

        assert status == 400, payload
        assert payload["status"] == "validation_error", payload
        assert "seed" in payload["error"].lower(), payload
        assert recorder.calls == []


class TestRunnerBinding:
    """D-14: the runner receives the resolved (count, seed) once, at start."""

    def test_runner_receives_resolved_count_and_seed_once(self):
        recorder = _Recorder()
        service = SimulationTaskService()
        _status, ack = _start(service, recorder, raw_count=7, seed=777)
        assert recorder.called.wait(timeout=_WAIT_SECONDS)
        _poll_until_terminal(service, ack["task_id"])

        assert recorder.calls == [(7, 777)], recorder.calls

    def test_omitted_seed_is_bound_to_the_runner_as_an_int(self):
        """The generated seed is the SAME value the runner is handed."""
        recorder = _Recorder()
        service = SimulationTaskService()
        _status, ack = _start(service, recorder, seed=None)
        assert recorder.called.wait(timeout=_WAIT_SECONDS)
        _poll_until_terminal(service, ack["task_id"])

        assert len(recorder.calls) == 1, recorder.calls
        count, seed = recorder.calls[0]
        assert count == 7
        assert isinstance(seed, int) and seed > 0
        assert seed == ack["seed"]
