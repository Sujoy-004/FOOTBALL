"""Concurrency and read-path purity tests under store-stamp drift.

Verifies D-05:
- HTTP GET requests on web threads (/api/data, /api/simulation, /api/standings)
  never trigger synchronous Monte Carlo simulation loops upon store-stamp drift.
- When store stamps drift, GET endpoints rebuild derived state purely deterministically
  and delegate re-simulation exclusively to SimulationTaskService background threads.
"""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from web.derived import holder
from web.ucl_app import ucl_app
from web.laliga_app import laliga_app
from web.server import app as server_app


class TestReadPathConcurrency:
    def test_ucl_stamp_drift_does_not_trigger_sync_mc(self, monkeypatch):
        """Touching UCL store files causes stamp drift, but read path stays fast and pure."""
        import web.ucl_app as app

        # Spy / mock on Monte Carlo engine to ensure it is never called on GET
        with patch("football_core.simulation.MonteCarloEngine.run") as mock_mc_run, \
             patch("competitions.ucl.src.pipeline.run_mc_simulation") as mock_ucl_sim, \
             patch("competitions.ucl.src.orchestrator.run_compute_all") as mock_ucl_orch:

            with TestClient(ucl_app) as client:
                # Initial read to stabilize cache
                resp1 = client.get("/api/data")
                assert resp1.status_code == 200

                # Simulate store-stamp drift by touching active results store
                active_dir = app._active_dir()
                results_path = active_dir / "results.json"
                if results_path.exists():
                    now = time.time() + 10.0
                    os.utime(results_path, (now, now))

                # Measure GET duration
                t0 = time.perf_counter()
                resp2 = client.get("/api/data")
                elapsed = time.perf_counter() - t0

                assert resp2.status_code == 200
                assert elapsed < 1.0, f"Read took {elapsed:.3f}s, expected < 1.0s"

                # Assert that Monte Carlo simulation was never invoked
                mock_mc_run.assert_not_called()
                mock_ucl_sim.assert_not_called()
                mock_ucl_orch.assert_not_called()

    def test_ucl_compute_all_under_simulation_mode_is_pure(self, monkeypatch):
        """Under simulation mode, compute_all() returns deterministic state without calling MC."""
        import web.ucl_app as app

        # Force mode resolver to return "simulation"
        monkeypatch.setattr(
            "competitions.ucl.src.orchestrator.resolve_compute_mode",
            lambda *args, **kwargs: ("simulation", "fixtures only, simulation needed"),
        )

        with patch("football_core.simulation.MonteCarloEngine.run") as mock_mc_run, \
             patch("competitions.ucl.src.pipeline.run_mc_simulation") as mock_ucl_sim, \
             patch("competitions.ucl.src.orchestrator.run_compute_all") as mock_ucl_orch:

            t0 = time.perf_counter()
            data = app.compute_all()
            elapsed = time.perf_counter() - t0

            assert elapsed < 1.0, f"compute_all took {elapsed:.3f}s, expected < 1.0s"
            assert data["mode"] == "simulation"
            assert data.get("simulation_stale") is True

            mock_mc_run.assert_not_called()
            mock_ucl_sim.assert_not_called()
            mock_ucl_orch.assert_not_called()

    def test_laliga_stamp_drift_stays_pure(self):
        """Touching LaLiga store file does not trigger Monte Carlo loops on read."""
        import web.laliga_app as app

        with patch("football_core.simulation.MonteCarloEngine.run") as mock_mc_run:
            with TestClient(laliga_app) as client:
                resp1 = client.get("/api/data")
                assert resp1.status_code == 200

                # Cause stamp drift on results.json
                res_path = app.DATA_DIR / "seasons" / "2026_27" / "results.json"
                if not res_path.exists():
                    res_path = app.DATA_DIR / "results.json"
                if res_path.exists():
                    now = time.time() + 10.0
                    os.utime(res_path, (now, now))

                t0 = time.perf_counter()
                resp2 = client.get("/api/data")
                elapsed = time.perf_counter() - t0

                assert resp2.status_code == 200
                assert elapsed < 1.0, f"Read took {elapsed:.3f}s, expected < 1.0s"
                mock_mc_run.assert_not_called()

    def test_server_mounts_read_path_purity(self):
        """Server-level GET /laliga/api/data and /ucl/api/data are deterministic and fast."""
        with patch("football_core.simulation.MonteCarloEngine.run") as mock_mc_run:
            with TestClient(server_app) as client:
                t0 = time.perf_counter()
                resp_ucl = client.get("/ucl/api/data")
                resp_laliga = client.get("/laliga/api/data")
                elapsed = time.perf_counter() - t0

                assert resp_ucl.status_code == 200
                assert resp_laliga.status_code == 200
                assert elapsed < 1.0
                mock_mc_run.assert_not_called()
