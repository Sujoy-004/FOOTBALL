"""Tests for governance.py version tracking and state.py governance persistence.

All file I/O tests use tmp_path to avoid modifying real data files.
"""

import json
import os
from pathlib import Path

import pytest

from src import state
from src import constants


# ─── Version persistence tests (Task 1) ─────────────────────────────────────


class TestLoadVersions:
    """Tests for state.load_versions() — graceful bootstrap and round-trip."""

    def test_load_versions_not_exists(self, tmp_path):
        """File missing → returns default dict with D0, M0, R0, None timestamps."""
        versions = state.load_versions(data_dir=tmp_path)
        assert versions["data_version"] == "D0"
        assert versions["model_version"] == "M0"
        assert versions["run_version"] == "R0"
        assert versions["last_data_change"] is None
        assert versions["last_model_change"] is None
        assert versions["last_run_timestamp"] is None

    def test_save_and_load_versions(self, tmp_path):
        """Save version dict, load it back, verify all keys match."""
        original = {
            "data_version": "D5",
            "model_version": "M3",
            "run_version": "R42",
            "last_data_change": "2026-06-17T12:00:00",
            "last_model_change": "2026-06-17T12:00:00",
            "last_run_timestamp": "2026-06-18T12:00:00",
        }
        state.save_versions(original, data_dir=tmp_path)
        loaded = state.load_versions(data_dir=tmp_path)
        assert loaded == original


class TestRunSnapshot:
    """Tests for state.save_run_snapshot() and state.load_run_snapshot()."""

    def test_save_run_snapshot(self, tmp_path):
        """Save snapshot dict to data/runs/{run_id}.json, load via load_run_snapshot."""
        snapshot = {
            "run_version": "2026-06-18T12:00:00.000000",
            "data_version": "D5",
            "model_version": "M3",
            "timestamp": "2026-06-18T12:00:00",
            "signal_counts": {"elo": 30, "form": 25},
            "blend_weights": {"elo": 0.5, "form": 0.5},
            "per_signal_brier": {"elo": 0.108, "form": 0.112},
            "blended_brier": 0.093,
            "drift_status": "HEALTHY",
        }
        state.save_run_snapshot(snapshot, data_dir=tmp_path)
        loaded = state.load_run_snapshot("2026-06-18T12:00:00.000000", data_dir=tmp_path)
        assert loaded == snapshot

    def test_save_run_snapshot_creates_runs_dir(self, tmp_path):
        """runs/ subdirectory is created automatically."""
        runs_dir = tmp_path / constants.GOV_RUNS_DIR
        assert not runs_dir.exists()
        snapshot = {
            "run_version": "test-run-id",
            "data_version": "D0",
            "model_version": "M0",
            "timestamp": "2026-06-18T12:00:00",
            "signal_counts": {},
            "blend_weights": {},
            "per_signal_brier": {},
            "blended_brier": 0.0,
            "drift_status": "COLD_START",
        }
        state.save_run_snapshot(snapshot, data_dir=tmp_path)
        assert runs_dir.exists()
        assert runs_dir.is_dir()


class TestBacktestReport:
    """Tests for state.load_backtest_report() and state.save_backtest_report()."""

    def test_load_backtest_report_not_exists(self, tmp_path):
        """File missing → returns None."""
        report = state.load_backtest_report(data_dir=tmp_path)
        assert report is None

    def test_save_and_load_backtest_report(self, tmp_path):
        """Save and load backtest report dict, verify keys."""
        report = {
            "tournaments": ["2018", "2022"],
            "n_total_matches": 128,
            "per_signal": {},
            "signal_ranking": [],
        }
        state.save_backtest_report(report, data_dir=tmp_path)
        loaded = state.load_backtest_report(data_dir=tmp_path)
        assert loaded == report


# ─── Version increment tests (Task 2) ─────────────────────────────────────


def make_versions(data=None):
    """Helper: create a fresh versions dict, optionally overriding defaults."""
    v = {
        "data_version": "D0",
        "model_version": "M0",
        "run_version": "R0",
        "last_data_change": None,
        "last_model_change": None,
        "last_run_timestamp": None,
    }
    if data:
        v.update(data)
    return v


def match_entry(match_id, signals=None):
    """Helper: create a minimal prediction_history entry."""
    sigs = signals or {}
    return {
        "match_id": match_id,
        "timestamp": "2026-06-18T12:00:00",
        "team_a": "A",
        "team_b": "B",
        "actual": 1.0,
        "signals": sigs,
    }


class TestDataVersion:
    """Tests for governance._compute_data_version() increment logic."""

    def test_data_version_new_match(self):
        """New match_id in new_history not in prev_history → data_version increments."""
        from src.governance import _compute_data_version

        prev = [match_entry("M1"), match_entry("M2")]
        new = [match_entry("M1"), match_entry("M2"), match_entry("M3")]
        result = _compute_data_version(make_versions(), prev, new)
        assert result == "D1"

    def test_data_version_new_signal(self):
        """Entry gains a new signal key → data_version increments."""
        from src.governance import _compute_data_version

        prev = [match_entry("M1", {"elo": {"probability": 0.6, "available": True}})]
        new = [match_entry("M1", {
            "elo": {"probability": 0.6, "available": True},
            "form": {"probability": 0.5, "available": True},
        })]
        result = _compute_data_version(make_versions(), prev, new)
        assert result == "D1"

    def test_data_version_no_change(self):
        """No new matches, no new signals → data_version unchanged."""
        from src.governance import _compute_data_version

        prev = [match_entry("M1", {"elo": {}})]
        new = [match_entry("M1", {"elo": {}})]
        result = _compute_data_version(make_versions(data={"data_version": "D5"}), prev, new)
        assert result == "D5"

    def test_data_version_not_on_merge(self):
        """Merge execution or governance run does not increment data_version (D-02)."""
        from src.governance import _compute_data_version

        prev = [match_entry("M1")]
        new = [match_entry("M1")]
        result = _compute_data_version(make_versions(data={"data_version": "D3"}), prev, new)
        assert result == "D3"


class TestModelVersion:
    """Tests for governance._compute_model_version() increment logic."""

    def test_model_version_signal_added(self):
        """Signal keys change from ['elo'] to ['elo', 'form'] → model_version increments."""
        from src.governance import _compute_model_version

        result = _compute_model_version(
            make_versions(),
            prev_signal_keys=["elo"],
            new_signal_keys=["elo", "form"],
            calibration_changed=False,
        )
        assert result == "M1"

    def test_model_version_calibration_refit(self):
        """Identity calibration → non-identity calibration → model_version increments."""
        from src.governance import _compute_model_version

        result = _compute_model_version(
            make_versions(),
            prev_signal_keys=["elo"],
            new_signal_keys=["elo"],
            calibration_changed=True,
        )
        assert result == "M1"

    def test_model_version_no_change(self):
        """No signal or calibration change → model_version unchanged."""
        from src.governance import _compute_model_version

        result = _compute_model_version(
            make_versions(data={"model_version": "M4"}),
            prev_signal_keys=["elo", "form"],
            new_signal_keys=["elo", "form"],
            calibration_changed=False,
        )
        assert result == "M4"

    def test_model_version_calibration_changed_between_values(self):
        """Calibration params change between non-identity values → increments."""
        from src.governance import _compute_model_version

        result = _compute_model_version(
            make_versions(data={"model_version": "M2"}),
            prev_signal_keys=["elo"],
            new_signal_keys=["elo"],
            calibration_changed=True,
        )
        assert result == "M3"

    def test_model_version_calibration_unchanged(self):
        """Calibration stays the same → no increment."""
        from src.governance import _compute_model_version

        result = _compute_model_version(
            make_versions(data={"model_version": "M5"}),
            prev_signal_keys=["elo"],
            new_signal_keys=["elo"],
            calibration_changed=False,
        )
        assert result == "M5"


class TestRunVersion:
    """Tests for governance._compute_run_version()."""

    def test_run_version_format(self):
        """_compute_run_version() returns ISO 8601 timestamp string."""
        from src.governance import _compute_run_version

        import re
        result = _compute_run_version()
        # ISO 8601 regex: 2026-06-18T12:00:00.000000 or similar
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result)
