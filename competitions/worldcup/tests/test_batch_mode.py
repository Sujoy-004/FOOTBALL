"""Tests for --simulate batch mode: deterministic output, --iterations, --report, error handling."""

import json
import os
import subprocess
import sys

import pytest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LEAGUE_DATA_DIR = os.path.join(DATA_DIR, "27")
HAS_DATA = os.path.exists(os.path.join(LEAGUE_DATA_DIR, "teams.json"))


@pytest.mark.skipif(not HAS_DATA, reason="WC league data (data/27/) not found")
class TestBatchModeSimulate:

    def test_simulate_deterministic_output(self):
        result1 = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--seed", "42", "-n", "100"],
            capture_output=True, text=True, timeout=60,
        )
        result2 = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--seed", "42", "-n", "100"],
            capture_output=True, text=True, timeout=60,
        )
        assert result1.returncode == 0, f"Exit {result1.returncode}: {result1.stderr}"
        assert result2.returncode == 0, f"Exit {result2.returncode}: {result2.stderr}"
        import re
        def clean(seq):
            return [l for l in seq.splitlines() if not re.match(r"^\[\d{4}-\d{2}-\d{2}", l)]
        assert clean(result1.stdout) == clean(result2.stdout), "Same seed should produce identical output (ignoring timestamps)"

    def test_simulate_different_seed_different_output(self):
        result1 = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--seed", "42", "-n", "100"],
            capture_output=True, text=True, timeout=60,
        )
        result2 = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--seed", "99", "-n", "100"],
            capture_output=True, text=True, timeout=60,
        )
        assert result1.returncode == 0
        assert result2.returncode == 0
        assert result1.stdout != result2.stdout, "Different seeds should produce different output"

    def test_simulate_iterations_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--iterations", "100", "--seed", "42"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Exit {result.returncode}: {result.stderr}"
        assert len(result.stdout) > 0

    def test_simulate_argument_validation(self):
        """Verify --validate-calibrated requires --simulate."""
        result = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--validate-calibrated"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        assert "requires --simulate" in result.stderr


@pytest.mark.skipif(not HAS_DATA, reason="WC league data (data/27/) not found")
class TestBatchModeReport:

    def test_report_flag_creates_json(self, tmp_path):
        report_path = tmp_path / "test_report.json"
        result = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--report", str(report_path), "--seed", "42", "-n", "100"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Exit {result.returncode}: {result.stderr}"
        assert report_path.exists(), "Report file not created"
        with open(report_path) as f:
            report = json.load(f)
        assert "timestamp" in report
        assert "probabilities" in report
        assert "generator" in report

    def test_report_content_structure(self, tmp_path):
        report_path = tmp_path / "test_report2.json"
        subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--report", str(report_path), "--seed", "42", "-n", "100"],
            capture_output=True, text=True, timeout=60,
        )
        with open(report_path) as f:
            report = json.load(f)
        assert "timestamp" in report
        assert isinstance(report["timestamp"], str)
        assert "mode" in report
        assert report["mode"] == "simulate"
        assert "parameters" in report
        assert "iterations" in report["parameters"]
        assert "seed" in report["parameters"]
        assert "probabilities" in report
        assert isinstance(report["probabilities"], dict)
