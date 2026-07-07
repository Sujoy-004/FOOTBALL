"""Smoke tests for UCL Live Monitor end-to-end flow."""

import os
import subprocess
import sys

import pytest

HAS_API_KEY = bool(os.environ.get("BSD_API_KEY"))


@pytest.mark.skipif(not HAS_API_KEY, reason="BSD_API_KEY not set")
class TestLiveSmoke:

    def test_live_once_runs(self):
        """--mode live --once --seed 42 exits cleanly with non-empty output."""
        result = subprocess.run(
            [sys.executable, "-m", "competitions.ucl.main",
             "--mode", "live", "--once", "-n", "100", "--seed", "42"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"
        assert len(result.stdout) > 0, "Expected non-empty output"

    def test_live_once_seed_reproducible(self):
        """Same seed produces identical output twice."""
        result1 = subprocess.run(
            [sys.executable, "-m", "competitions.ucl.main",
             "--mode", "live", "--once", "-n", "100", "--seed", "42"],
            capture_output=True, text=True, timeout=60,
        )
        result2 = subprocess.run(
            [sys.executable, "-m", "competitions.ucl.main",
             "--mode", "live", "--once", "-n", "100", "--seed", "42"],
            capture_output=True, text=True, timeout=60,
        )
        assert result1.stdout == result2.stdout, "Same seed should produce identical output"

    def test_simulate_mode_unchanged(self):
        """Existing --mode simulate still works after live mode changes."""
        result = subprocess.run(
            [sys.executable, "-m", "competitions.ucl.main",
             "--mode", "simulate", "-n", "100", "--seed", "42"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0
        assert "Champion" in result.stdout or "champion" in result.stdout.lower()
