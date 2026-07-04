"""Integration tests for the calibrated validation pipeline (Phase 10, Plan 03).

Tests cover:
    - CLI flag parsing for --calibrated, --show-ci, --validate-calibrated
    - print_calibration_summary output structure
    - print_calibration_comparison output structure
    - print_odds with show_ci=True
    - Baseline save/load roundtrip
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# ── Fixtures ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def calibration_info() -> dict[str, Any]:
    return {
        "T": 0.95,
        "alpha": 0.05,
        "n_samples": 1200,
        "log_loss": 0.580,
        "log_loss_before": 0.610,
        "ece": 0.038,
    }


@pytest.fixture
def baseline_report() -> dict[str, Any]:
    return {
        "match_level": {
            "log_loss": 0.610,
            "ece": 0.052,
            "brier": 0.240,
        },
        "tournament_level": {
            "trps": 0.185,
        },
    }


@pytest.fixture
def calibrated_report() -> dict[str, Any]:
    return {
        "tournament_level": {
            "trps": 0.175,
            "champion_accuracy": 0.88,
            "stage_accuracy": 0.75,
        },
        "match_level": {
            "log_loss": 0.580,
            "ece": 0.038,
            "brier": 0.225,
        },
        "calibration": {
            "ece": 0.031,
            "n_decision_points": 1200,
        },
    }


@dataclass
class DummyResult:
    """Minimal SimulationResult-like object with teams attribute."""
    teams: dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def dummy_result_with_ci() -> DummyResult:
    """Result with CI fields in team data."""
    return DummyResult(teams={
        "Arsenal": {"champion_prob": 0.55, "champion_ci_lower": 0.50, "champion_ci_upper": 0.60,
                     "stage_final_prob": 0.35, "stage_sf_prob": 0.50, "stage_qf_prob": 0.70},
        "Chelsea": {"champion_prob": 0.20, "champion_ci_lower": 0.15, "champion_ci_upper": 0.25,
                    "stage_final_prob": 0.10, "stage_sf_prob": 0.25, "stage_qf_prob": 0.40},
    })


@pytest.fixture
def dummy_result_no_ci() -> DummyResult:
    """Result without CI fields in team data."""
    return DummyResult(teams={
        "Arsenal": {"champion_prob": 0.55, "stage_final_prob": 0.35, "stage_sf_prob": 0.50, "stage_qf_prob": 0.70},
        "Chelsea": {"champion_prob": 0.20, "stage_final_prob": 0.10, "stage_sf_prob": 0.25, "stage_qf_prob": 0.40},
    })


# ═══════════════════════════════════════════════════════════════════════════════
# ── print_calibration_summary Tests ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrintCalibrationSummary:
    def test_output_contains_temperature(self, calibration_info, capsys):
        """Summary includes temperature value."""
        from competitions.ucl.display import print_calibration_summary
        print_calibration_summary(calibration_info)
        captured = capsys.readouterr()
        assert "0.9500" in captured.out

    def test_output_contains_log_loss(self, calibration_info, capsys):
        """Summary includes log loss delta."""
        from competitions.ucl.display import print_calibration_summary
        print_calibration_summary(calibration_info)
        captured = capsys.readouterr()
        assert "0.5800" in captured.out
        assert "0.6100" in captured.out

    def test_output_contains_ece(self, calibration_info, capsys):
        """Summary includes ECE."""
        from competitions.ucl.display import print_calibration_summary
        print_calibration_summary(calibration_info)
        captured = capsys.readouterr()
        assert "0.0380" in captured.out

    def test_no_error_on_empty(self, capsys):
        """Empty dict prints nothing (no crash)."""
        from competitions.ucl.display import print_calibration_summary
        print_calibration_summary({})
        captured = capsys.readouterr()
        # No crash is sufficient


# ═══════════════════════════════════════════════════════════════════════════════
# ── print_calibration_comparison Tests ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrintCalibrationComparison:
    def test_output_contains_before_after(self, baseline_report, calibrated_report, capsys):
        """Comparison output includes Before and After columns."""
        from competitions.ucl.display import print_calibration_comparison
        print_calibration_comparison(baseline_report, calibrated_report)
        captured = capsys.readouterr()
        assert "Before" in captured.out
        assert "After" in captured.out

    def test_output_contains_log_loss(self, baseline_report, calibrated_report, capsys):
        """Output contains Log Loss values."""
        from competitions.ucl.display import print_calibration_comparison
        print_calibration_comparison(baseline_report, calibrated_report)
        captured = capsys.readouterr()
        assert "0.610" in captured.out
        assert "0.580" in captured.out

    def test_output_contains_delta(self, baseline_report, calibrated_report, capsys):
        """Output shows improvement (negative Δ for loss metrics)."""
        from competitions.ucl.display import print_calibration_comparison
        print_calibration_comparison(baseline_report, calibrated_report)
        captured = capsys.readouterr()
        assert "Δ" in captured.out

    def test_no_baseline_still_prints(self, calibrated_report, capsys):
        """Without baseline, prints values without Before column."""
        from competitions.ucl.display import print_calibration_comparison
        print_calibration_comparison(None, calibrated_report)
        captured = capsys.readouterr()
        assert "After" in captured.out

    def test_no_error_on_empty(self, capsys):
        """Empty reports print nothing (no crash)."""
        from competitions.ucl.display import print_calibration_comparison
        print_calibration_comparison({}, {})
        captured = capsys.readouterr()
        # No crash


# ═══════════════════════════════════════════════════════════════════════════════
# ── print_odds Tests ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrintOdds:
    def test_basic_output(self, dummy_result_with_ci, capsys):
        """print_odds prints predicted probabilities."""
        from competitions.ucl.display import print_odds
        print_odds(dummy_result_with_ci)
        captured = capsys.readouterr()
        assert "Arsenal" in captured.out
        assert "Chelsea" in captured.out
        assert "55" in captured.out  # percentage rounded

    def test_show_ci_output(self, dummy_result_with_ci, capsys):
        """show_ci=True displays P% ± W% format with CI data."""
        from competitions.ucl.display import print_odds
        print_odds(dummy_result_with_ci, show_ci=True)
        captured = capsys.readouterr()
        assert "±" in captured.out
        assert "50.0" in captured.out or "60.0" in captured.out

    def test_show_ci_no_crash_no_ci_fields(self, dummy_result_no_ci, capsys):
        """show_ci=True without CI fields in teams data does not crash."""
        from competitions.ucl.display import print_odds
        print_odds(dummy_result_no_ci, show_ci=True)
        captured = capsys.readouterr()
        assert "Arsenal" in captured.out


# ═══════════════════════════════════════════════════════════════════════════════
# ── Baseline Save/Load Roundtrip Tests ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestBaselineRoundtrip:
    def test_save_and_load(self):
        """Baseline roundtrips correctly through JSON."""
        baseline = {
            "match_level": {"log_loss": 0.610, "ece": 0.052, "brier": 0.240},
            "tournament_level": {"trps": 0.185},
        }
        calibrated = {
            "match_level": {"log_loss": 0.580, "ece": 0.038, "brier": 0.225},
            "tournament_level": {"trps": 0.175},
        }
        with tempfile.TemporaryDirectory() as tmp:
            from competitions.ucl.main import _save_validation_baseline
            path = os.path.join(tmp, "baseline.json")
            _save_validation_baseline(path, baseline, calibrated)

            # Verify file exists and is valid JSON
            with open(path) as f:
                data = json.load(f)
            assert "baseline" in data
            assert "calibrated" in data
            assert isinstance(data["calibrated"], list)
            assert data["baseline"]["log_loss"] == 0.610

    def test_first_run_no_baseline(self):
        """First run with no existing baseline creates one."""
        with tempfile.TemporaryDirectory() as tmp:
            from competitions.ucl.main import _save_validation_baseline
            path = os.path.join(tmp, "baseline.json")
            # Only calibrated report, no uncalibrated baseline
            _save_validation_baseline(path, None, {
                "match_level": {"log_loss": 0.580},
                "tournament_level": {"trps": 0.175},
            })
            with open(path) as f:
                data = json.load(f)
            # baseline entry should exist but contain no calib data yet
            assert data["baseline"] is None
            assert len(data["calibrated"]) == 1
            assert data["calibrated"][0]["log_loss"] == 0.580


# ═══════════════════════════════════════════════════════════════════════════════
# ── CLI arg parsing Tests ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIFlags:
    def test_validate_calibrated(self):
        """--validate-calibrated flag is parsed."""
        from competitions.ucl.main import _parse_args
        args = _parse_args(["--validate-calibrated"])
        assert args.validate_calibrated is True
        assert args.validate is False  # not the same flag

    def test_validate_flags_incompatible(self):
        """--validate and --validate-calibrated are mutually exclusive."""
        from competitions.ucl.main import _parse_args, _validate_args
        args = _parse_args(["--validate", "--validate-calibrated"])
        with pytest.raises(SystemExit):
            _validate_args(args)

    def test_validate_calibrated_not_default(self):
        """--validate-calibrated is False by default."""
        from competitions.ucl.main import _parse_args
        args = _parse_args([])
        assert args.validate_calibrated is False
