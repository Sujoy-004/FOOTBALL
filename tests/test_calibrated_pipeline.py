"""Integration tests for the calibrated validation pipeline baseline roundtrip."""

from __future__ import annotations

import json
import os
import tempfile



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
            from competitions.ucl.src.analysis import save_validation_baseline
            path = os.path.join(tmp, "baseline.json")
            save_validation_baseline(path, baseline, calibrated)

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
            from competitions.ucl.src.analysis import save_validation_baseline
            path = os.path.join(tmp, "baseline.json")
            # Only calibrated report, no uncalibrated baseline
            save_validation_baseline(path, None, {
                "match_level": {"log_loss": 0.580},
                "tournament_level": {"trps": 0.175},
            })
            with open(path) as f:
                data = json.load(f)
            # baseline entry should exist but contain no calib data yet
            assert data["baseline"] is None
            assert len(data["calibrated"]) == 1
            assert data["calibrated"][0]["log_loss"] == 0.580



