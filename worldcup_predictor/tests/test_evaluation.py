"""Tests for evaluation.py metrics and baseline reporting."""

import json
import math
import os
import pytest
from src.evaluation import (
    brier_score, log_loss, compute_metrics,
    calibration_curve, expected_calibration_error,
    evaluate_all_matches, compare_baselines,
)


class TestBrierScore:
    def test_perfect(self):
        assert brier_score(1.0, 1.0) == 0.0

    def test_worst(self):
        assert brier_score(0.0, 1.0) == 1.0

    def test_half(self):
        assert brier_score(0.5, 1.0) == 0.25

    def test_draw(self):
        assert brier_score(0.6, 0.5) == pytest.approx(0.01)

    def test_wrong_favorite(self):
        assert brier_score(0.8, 0.0) == pytest.approx(0.64)


class TestLogLoss:
    def test_perfect(self):
        assert log_loss(0.99, 1.0) == pytest.approx(0.01005, rel=0.01)

    def test_worst(self):
        assert log_loss(0.01, 1.0) == pytest.approx(4.605, rel=0.01)

    def test_clamping_no_inf(self):
        result = log_loss(0.0, 1.0)
        assert math.isfinite(result)
        assert result > 0

    def test_draw(self):
        result = log_loss(0.5, 0.5)
        assert result == pytest.approx(0.693, rel=0.01)

    def test_draw_extreme(self):
        result = log_loss(0.99, 0.5)
        assert result > 0
        assert math.isfinite(result)


class TestComputeMetrics:
    def test_empty(self):
        result = compute_metrics([], [])
        assert result["n"] == 0

    def test_all_perfect(self):
        result = compute_metrics([1.0, 1.0, 1.0], [1.0, 1.0, 1.0])
        assert result["brier"] == 0.0
        assert result["accuracy"] == 1.0

    def test_mixed(self):
        result = compute_metrics([0.8, 0.3], [1.0, 0.0])
        assert result["n"] == 2
        assert result["accuracy"] == 1.0

    def test_includes_draw(self):
        result = compute_metrics([0.6, 0.5], [1.0, 0.5])
        assert result["n"] == 2
        assert result["accuracy"] == 0.75


class TestCalibrationCurve:
    def test_perfect_calibration(self):
        preds = [0.0, 0.0, 1.0, 1.0]
        actuals = [0.0, 0.0, 1.0, 1.0]
        cal = calibration_curve(preds, actuals, n_bins=10)
        assert len(cal["bins"]) == 10
        assert cal["ece"] == pytest.approx(0.0, abs=0.001)

    def test_miscalibrated(self):
        preds = [0.9, 0.9, 0.1, 0.1]
        actuals = [0.0, 0.0, 1.0, 1.0]
        cal = calibration_curve(preds, actuals, n_bins=10)
        assert cal["ece"] > 0.0

    def test_single_bin(self):
        preds = [0.5, 0.5, 0.5]
        actuals = [1.0, 0.0, 0.5]
        cal = calibration_curve(preds, actuals, n_bins=1)
        assert cal["bins"][0]["count"] == 3

    def test_bin_boundary(self):
        preds = [0.0, 0.5, 1.0]
        actuals = [0.0, 0.5, 1.0]
        cal = calibration_curve(preds, actuals, n_bins=10)
        assert cal["bins"][0]["count"] == 1
        assert cal["bins"][5]["count"] == 1
        assert cal["bins"][9]["count"] == 1


class TestExpectedCalibrationError:
    def test_perfect(self):
        cal = {"bins": [
            {"count": 5, "mean_predicted": 0.2, "fraction_positives": 0.2},
            {"count": 5, "mean_predicted": 0.8, "fraction_positives": 0.8},
        ]}
        assert expected_calibration_error(cal) == 0.0

    def test_imperfect(self):
        cal = {"bins": [
            {"count": 5, "mean_predicted": 0.2, "fraction_positives": 0.3},
            {"count": 5, "mean_predicted": 0.8, "fraction_positives": 0.7},
        ]}
        assert expected_calibration_error(cal) == pytest.approx(0.1)

    def test_empty(self):
        assert expected_calibration_error({"bins": []}) == 0.0


class TestEvaluateAllMatches:
    def test_basic_replay(self, tmp_path):
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B", "winner": "A", "home_score": 2, "away_score": 0, "completed_at": "2026-06-15T20:00:00Z"}}
        played_groups = {}
        result = evaluate_all_matches(teams, played, played_groups, signal_name="elo")
        assert result["n_matches"] == 1
        assert 0 < result["metrics"]["brier"] < 1
        assert result["metrics"]["n"] == 1

    def test_empty_played(self, tmp_path):
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        result = evaluate_all_matches(teams, {}, {}, signal_name="elo")
        assert result["n_matches"] == 0

    def test_report_shape(self, tmp_path):
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B", "winner": "A", "home_score": 2, "away_score": 0, "completed_at": "2026-06-15T20:00:00Z"}}
        result = evaluate_all_matches(teams, played, {}, signal_name="elo")
        assert "model" in result
        assert "metrics" in result
        assert "calibration" in result
        assert "brier" in result["metrics"]
        assert "log_loss" in result["metrics"]
        assert "accuracy" in result["metrics"]
        assert "ece" in result["calibration"]

    def test_skips_unknown_teams(self, tmp_path):
        teams = {"A": {"elo": 2000}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "UNKNOWN", "winner": "A", "home_score": 2, "away_score": 0, "completed_at": "2026-06-15T20:00:00Z"}}
        result = evaluate_all_matches(teams, played, {}, signal_name="elo")
        assert result["n_matches"] == 0


class TestEvaluateAllMatchesSignalName:
    """Tests for signal_name parameter on evaluate_all_matches (D-11)."""

    @pytest.fixture
    def teams(self):
        return {"A": {"elo": 2000}, "B": {"elo": 1900}}

    @pytest.fixture
    def played_basic(self):
        return {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                        "winner": "A", "home_score": 2, "away_score": 0,
                        "completed_at": "2026-06-15T20:00:00Z"}}

    def test_evaluate_signal_elo(self, teams, played_basic):
        """signal_name='elo' replays through Elo pipeline and produces compound entries."""
        result = evaluate_all_matches(teams, played_basic, {}, signal_name="elo")
        assert result["n_matches"] == 1
        assert 0 < result["metrics"]["brier"] < 1
        # Load history to check compound entry format
        from src.state import load_prediction_history
        h = load_prediction_history()
        compound_entries = [e for e in h if e.get("signals", {}).get("elo")]
        assert len(compound_entries) >= 1
        entry = compound_entries[-1]
        assert "signals" in entry, "Must produce compound entry"
        assert "prediction" not in entry, "No top-level prediction"
        assert "signal" not in entry, "No top-level signal"
        assert entry["signals"]["elo"]["available"] is True

    def test_evaluate_signal_none(self, teams, played_basic):
        """signal_name=None returns multi-signal report with 'signals' key (D-11)."""
        result = evaluate_all_matches(teams, played_basic, {}, signal_name=None)
        assert "signals" in result, "Multi-signal report must have 'signals' key"
        assert isinstance(result["signals"], dict)
        assert len(result["signals"]) > 0, "Should have at least one signal"
        # At minimum should have 'elo' from the replay
        assert "elo" in result["signals"]
        assert result["signals"]["elo"]["n_matches"] > 0

    def test_evaluate_signal_none_with_compound_history(self, tmp_path):
        """signal_name=None with pre-existing compound entries reads all signal keys."""
        from src.state import save_prediction_history, load_prediction_history
        from src import constants
        import copy

        # Save compound entries with multiple signals
        entries = [
            {
                "match_id": "M01",
                "timestamp": "2026-06-15T12:00:00+00:00",
                "team_a": "A", "team_b": "B",
                "actual": 1.0,
                "signals": {
                    "elo": {"probability": 0.64, "version": "v1", "timestamp": "...", "available": True},
                    "market_odds": {"probability": 0.71, "version": "v1", "timestamp": "...", "available": True},
                },
            },
            {
                "match_id": "M02",
                "timestamp": "2026-06-15T14:00:00+00:00",
                "team_a": "C", "team_b": "D",
                "actual": 0.0,
                "signals": {
                    "elo": {"probability": 0.55, "version": "v1", "timestamp": "...", "available": True},
                    "market_odds": {"probability": 0.42, "version": "v1", "timestamp": "...", "available": False},
                },
            },
        ]
        orig_dir = constants.DATA_DIR
        try:
            constants.DATA_DIR = tmp_path
            save_prediction_history(entries)
            # signal_name=None with empty played/played_groups -> reads from history
            result = evaluate_all_matches({"A": {"elo": 2000}}, {}, {}, signal_name=None)
            assert "signals" in result
            assert "elo" in result["signals"]
            assert "market_odds" in result["signals"]
            assert result["signals"]["elo"]["n_matches"] >= 1
            assert result["signals"]["market_odds"]["n_matches"] >= 1
        finally:
            constants.DATA_DIR = orig_dir

    def test_evaluate_signal_market_odds(self, tmp_path):
        """signal_name='market_odds' reads from prediction_history compound entries."""
        from src.state import save_prediction_history
        from src import constants

        entries = [
            {
                "match_id": "M01",
                "timestamp": "2026-06-15T12:00:00+00:00",
                "team_a": "A", "team_b": "B",
                "actual": 1.0,
                "signals": {
                    "market_odds": {"probability": 0.71, "version": "v1", "timestamp": "...", "available": True},
                },
            },
        ]
        orig_dir = constants.DATA_DIR
        try:
            constants.DATA_DIR = tmp_path
            save_prediction_history(entries)
            result = evaluate_all_matches({"A": {"elo": 2000}}, {}, {}, signal_name="market_odds")
            assert result["n_matches"] == 1
            assert "metrics" in result
            assert result["metrics"]["n"] == 1
        finally:
            constants.DATA_DIR = orig_dir

    def test_evaluate_signal_nonexistent(self, tmp_path):
        """Unknown signal name returns n_matches=0 report (graceful, no crash)."""
        from src import constants
        orig_dir = constants.DATA_DIR
        try:
            constants.DATA_DIR = tmp_path
            result = evaluate_all_matches({"A": {"elo": 2000}}, {}, {}, signal_name="nonexistent")
            assert result["n_matches"] == 0
        finally:
            constants.DATA_DIR = orig_dir

    def test_evaluate_signal_empty_history(self, tmp_path):
        """No entries have the requested signal -> report with n_matches=0."""
        from src.state import save_prediction_history
        from src import constants

        entries = [
            {
                "match_id": "M01",
                "timestamp": "2026-06-15T12:00:00+00:00",
                "team_a": "A", "team_b": "B",
                "actual": 1.0,
                "signals": {
                    "elo": {"probability": 0.64, "version": "v1", "timestamp": "...", "available": True},
                },
            },
        ]
        orig_dir = constants.DATA_DIR
        try:
            constants.DATA_DIR = tmp_path
            save_prediction_history(entries)
            result = evaluate_all_matches({"A": {"elo": 2000}}, {}, {}, signal_name="market_odds")
            assert result["n_matches"] == 0
        finally:
            constants.DATA_DIR = orig_dir

    def test_evaluate_signal_catboost(self, tmp_path):
        """signal_name='catboost' reads from prediction_history compound entries."""
        from src.state import save_prediction_history
        from src import constants

        entries = [
            {
                "match_id": "M01",
                "timestamp": "2026-06-15T12:00:00+00:00",
                "team_a": "A", "team_b": "B",
                "actual": 1.0,
                "signals": {
                    "catboost": {"probability": 0.63, "version": "v1", "timestamp": "...", "available": True},
                },
            },
        ]
        orig_dir = constants.DATA_DIR
        try:
            constants.DATA_DIR = tmp_path
            save_prediction_history(entries)
            result = evaluate_all_matches({"A": {"elo": 2000}}, {}, {}, signal_name="catboost")
            assert result["n_matches"] == 1
        finally:
            constants.DATA_DIR = orig_dir


class TestCompareBaselines:
    def test_different(self):
        before = {"model": "elo-only", "metrics": {"brier": 0.18, "log_loss": 0.5, "accuracy": 0.7, "n": 10}, "calibration": {"ece": 0.05}}
        after = {"model": "elo-odds", "metrics": {"brier": 0.15, "log_loss": 0.4, "accuracy": 0.75, "n": 10}, "calibration": {"ece": 0.03}}
        comp = compare_baselines(before, after)
        assert comp["deltas"]["brier"] == pytest.approx(-0.03)
        assert comp["verdict"] == "IMPROVED"

    def test_identical(self):
        r = {"model": "elo-only", "metrics": {"brier": 0.18, "log_loss": 0.5, "accuracy": 0.7, "n": 10}, "calibration": {"ece": 0.05}}
        comp = compare_baselines(r, r)
        assert comp["deltas"]["brier"] == 0.0
        assert comp["verdict"] == "SIMILAR"

    def test_regressed(self):
        before = {"model": "a", "metrics": {"brier": 0.15, "log_loss": 0.4, "accuracy": 0.75, "n": 10}, "calibration": {"ece": 0.03}}
        after = {"model": "b", "metrics": {"brier": 0.2, "log_loss": 0.6, "accuracy": 0.65, "n": 10}, "calibration": {"ece": 0.08}}
        comp = compare_baselines(before, after)
        assert comp["deltas"]["brier"] == pytest.approx(0.05)
        assert comp["verdict"] == "REGRESSED"
