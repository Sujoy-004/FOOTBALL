"""Tests for calibration orchestration (run_calibration)."""

import json
import os
import tempfile

import pytest

from competitions.ucl.src.calibrate import (
    run_calibration,
    DEFAULT_THRESHOLD,
    _build_signal_registry,
    _get_default_output_path,
)
from football_core.blender import compute_log_loss_weights


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_replay_data(matches: list[dict]) -> str:
    """Create a temp replay JSON file and return its path."""
    data = {"matches": matches}
    fd, path = tempfile.mkstemp(suffix=".json", prefix="replay_", text=True)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


def _cleanup_temp(path: str) -> None:
    """Remove temp file if it exists."""
    try:
        os.remove(path)
    except OSError:
        pass


_SAMPLE_MATCHES = [
    {"team_a": "Man City", "team_b": "Bayern", "home_score": 2, "away_score": 1},
    {"team_a": "Real Madrid", "team_b": "PSG", "home_score": 3, "away_score": 0},
    {"team_a": "Liverpool", "team_b": "Inter", "home_score": 1, "away_score": 1},
    {"team_a": "Barcelona", "team_b": "Dortmund", "home_score": 2, "away_score": 2},
    {"team_a": "Arsenal", "team_b": "AC Milan", "home_score": 1, "away_score": 0},
    {"team_a": "Juventus", "team_b": "PSV", "home_score": 2, "away_score": 0},
    {"team_a": "Man City", "team_b": "Real Madrid", "home_score": 2, "away_score": 2},
    {"team_a": "Bayern", "team_b": "Barcelona", "home_score": 3, "away_score": 1},
    {"team_a": "PSG", "team_b": "Liverpool", "home_score": 2, "away_score": 2},
    {"team_a": "Inter", "team_b": "Arsenal", "home_score": 1, "away_score": 0},
    {"team_a": "Dortmund", "team_b": "Juventus", "home_score": 2, "away_score": 1},
    {"team_a": "PSV", "team_b": "AC Milan", "home_score": 0, "away_score": 0},
    {"team_a": "Real Madrid", "team_b": "Bayern", "home_score": 1, "away_score": 0},
    {"team_a": "Man City", "team_b": "PSG", "home_score": 3, "away_score": 1},
    {"team_a": "Liverpool", "team_b": "Barcelona", "home_score": 2, "away_score": 0},
    {"team_a": "Inter", "team_b": "Dortmund", "home_score": 0, "away_score": 0},
    {"team_a": "Arsenal", "team_b": "PSV", "home_score": 3, "away_score": 0},
    {"team_a": "AC Milan", "team_b": "Juventus", "home_score": 1, "away_score": 0},
    {"team_a": "Man City", "team_b": "Liverpool", "home_score": 1, "away_score": 0},
    {"team_a": "Bayern", "team_b": "Inter", "home_score": 2, "away_score": 0},
    {"team_a": "Real Madrid", "team_b": "Arsenal", "home_score": 2, "away_score": 1},
    {"team_a": "PSG", "team_b": "Dortmund", "home_score": 1, "away_score": 1},
    {"team_a": "Barcelona", "team_b": "AC Milan", "home_score": 2, "away_score": 0},
    {"team_a": "Juventus", "team_b": "PSV", "home_score": 1, "away_score": 0},
]


# ── TestBuildSignalRegistry ─────────────────────────────────────────────────


class TestBuildSignalRegistry:
    """Verify _build_signal_registry produces expected signals."""

    def test_registry_contains_expected_signals(self):
        registry = _build_signal_registry()
        signal_names = registry.list()
        assert "refined_elo" in signal_names
        assert "market_odds" in signal_names
        assert "rolling_form" in signal_names
        assert "squad_value" in signal_names
        assert "rest_days" in signal_names

    def test_registry_signals_conform_to_protocol(self):
        registry = _build_signal_registry()
        for signal in registry.all():
            assert hasattr(signal, "name")
            assert callable(getattr(signal, "predict", None))


# ── TestRunCalibration ─────────────────────────────────────────────────────


class TestRunCalibration:
    """Verify run_calibration orchestration."""

    def test_calibrate_writes_config(self):
        replay_path = _make_replay_data(_SAMPLE_MATCHES)
        try:
            output_fd, output_path = tempfile.mkstemp(
                suffix=".json", prefix="weights_", text=True
            )
            os.close(output_fd)
            try:
                config = run_calibration(
                    replay_data_path=replay_path,
                    output_path=output_path,
                )
                assert os.path.exists(output_path)
                with open(output_path) as f:
                    saved = json.load(f)
                assert saved == config
            finally:
                _cleanup_temp(output_path)
        finally:
            _cleanup_temp(replay_path)

    def test_calibrate_output_schema(self):
        replay_path = _make_replay_data(_SAMPLE_MATCHES[:10])
        try:
            output_fd, output_path = tempfile.mkstemp(
                suffix=".json", prefix="weights_", text=True
            )
            os.close(output_fd)
            try:
                config = run_calibration(
                    replay_data_path=replay_path,
                    output_path=output_path,
                )
                assert "version" in config
                assert config["version"] == 1
                assert "calibrated_at" in config
                assert "n_matches" in config
                assert "threshold" in config
                assert "weights" in config
                assert "per_signal" in config
            finally:
                _cleanup_temp(output_path)
        finally:
            _cleanup_temp(replay_path)

    def test_calibrate_weights_sum_to_one(self):
        replay_path = _make_replay_data(_SAMPLE_MATCHES)
        try:
            output_fd, output_path = tempfile.mkstemp(
                suffix=".json", prefix="weights_", text=True
            )
            os.close(output_fd)
            try:
                config = run_calibration(
                    replay_data_path=replay_path,
                    output_path=output_path,
                )
                total_weight = sum(config["weights"].values())
                assert abs(total_weight - 1.0) < 0.01
            finally:
                _cleanup_temp(output_path)
        finally:
            _cleanup_temp(replay_path)

    def test_calibrate_excludes_under_sampled(self):
        # 5 matches with threshold=20 — no signal should reach threshold
        few_matches = _SAMPLE_MATCHES[:5]
        replay_path = _make_replay_data(few_matches)
        try:
            output_fd, output_path = tempfile.mkstemp(
                suffix=".json", prefix="weights_", text=True
            )
            os.close(output_fd)
            try:
                config = run_calibration(
                    replay_data_path=replay_path,
                    threshold=20,
                    output_path=output_path,
                )
                # Since no signal reaches 20 matches, weights should be empty
                assert config["weights"] == {}
                # All signals should be marked as excluded
                for sig_name, sig_data in config["per_signal"].items():
                    if sig_data["n_matches"] < 20:
                        assert sig_data["excluded"] is True
            finally:
                _cleanup_temp(output_path)
        finally:
            _cleanup_temp(replay_path)

    def test_calibrate_atomic_write(self, tmp_path):
        replay_path = _make_replay_data(_SAMPLE_MATCHES[:10])
        try:
            output_path = os.path.join(str(tmp_path), "weights_out.json")
            config = run_calibration(
                replay_data_path=replay_path,
                output_path=output_path,
            )
            # Verify file is written correctly — no .tmp files left in tmp_path
            assert os.path.exists(output_path)
            tmp_files = [
                f for f in os.listdir(str(tmp_path))
                if f.endswith(".tmp")
            ]
            assert len(tmp_files) == 0
            # Verify content
            with open(output_path) as f:
                saved = json.load(f)
            assert saved == config
        finally:
            _cleanup_temp(replay_path)

    def test_calibrate_invalid_path_raises(self):
        with pytest.raises(FileNotFoundError):
            run_calibration(replay_data_path="/nonexistent/path/data.json")

    def test_calibrate_empty_data_raises(self):
        replay_path = _make_replay_data([])
        try:
            with pytest.raises(ValueError, match="No matches"):
                run_calibration(replay_data_path=replay_path)
        finally:
            _cleanup_temp(replay_path)


# ── TestPerSignalLogLoss ──────────────────────────────────────────────────


class TestPerSignalLogLoss:
    """Verify per-signal multi-class log-loss computation."""

    @staticmethod
    def _manual_multiclass_log_loss(predictions: list[dict], actuals: list[tuple]) -> float:
        """Compute 3-binary log-loss manually from predictions and actuals."""
        from football_core.evaluation import log_loss

        n = len(predictions)
        ll_total = 0.0
        for pred, actual in zip(predictions, actuals):
            ll_home = log_loss(pred["home"], actual[0])
            ll_draw = log_loss(pred["draw"], actual[1])
            ll_away = log_loss(pred["away"], actual[2])
            ll_total += (ll_home + ll_draw + ll_away) / 3
        return ll_total / n

    def test_multiclass_log_loss_formula(self):
        # Test that the multi-class log-loss formula is correct
        from football_core.evaluation import log_loss

        # For a perfect prediction:
        # pred=(1.0, 0.0, 0.0), actual=(1.0, 0.0, 0.0) — home win
        # Everything perfectly predicted → log-loss should be near 0
        ll_home = log_loss(1.0, 1.0)
        ll_draw = log_loss(0.0, 0.0)
        ll_away = log_loss(0.0, 0.0)
        multiclass = (ll_home + ll_draw + ll_away) / 3
        assert multiclass < 0.001

    def test_equal_log_losses_produce_uniform_weights(self):
        # Two signals with equal log-loss → equal weights
        log_losses = {"sig_a": 0.6, "sig_b": 0.6}
        weights = compute_log_loss_weights(log_losses)
        assert abs(weights["sig_a"] - weights["sig_b"]) < 1e-10
        assert abs(weights["sig_a"] - 0.5) < 1e-10
        assert abs(weights["sig_b"] - 0.5) < 1e-10

    def test_three_equal_weights(self):
        log_losses = {"a": 0.5, "b": 0.5, "c": 0.5}
        weights = compute_log_loss_weights(log_losses)
        uniform = round(1 / 3, 6)
        assert abs(weights["a"] - uniform) < 1e-10
        assert abs(weights["b"] - uniform) < 1e-10
        assert abs(weights["c"] - uniform) < 1e-10
        # Rounding to 6 decimal places may cause sum != 1.0 by ~1e-6
        assert abs(sum(weights.values()) - 1.0) < 1e-5

    def test_known_probability_pattern(self):
        """Verify with known probabilities and actual outcomes."""
        from football_core.evaluation import log_loss

        # Two matches with known predictions
        # Match 1: pred=(0.6, 0.3, 0.1), actual=(1.0, 0.0, 0.0) [home win]
        ll_home_1 = log_loss(0.6, 1.0)
        ll_draw_1 = log_loss(0.3, 0.0)
        ll_away_1 = log_loss(0.1, 0.0)
        mc_ll_1 = (ll_home_1 + ll_draw_1 + ll_away_1) / 3

        # Match 2: pred=(0.2, 0.6, 0.2), actual=(0.0, 1.0, 0.0) [draw]
        ll_home_2 = log_loss(0.2, 0.0)
        ll_draw_2 = log_loss(0.6, 1.0)
        ll_away_2 = log_loss(0.2, 0.0)
        mc_ll_2 = (ll_home_2 + ll_draw_2 + ll_away_2) / 3

        avg_mc_ll = (mc_ll_1 + mc_ll_2) / 2

        # Now compute via the manual helper
        manual = self._manual_multiclass_log_loss(
            [
                {"home": 0.6, "draw": 0.3, "away": 0.1},
                {"home": 0.2, "draw": 0.6, "away": 0.2},
            ],
            [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        )
        assert abs(manual - avg_mc_ll) < 1e-10

    def test_better_signal_gets_higher_weight(self):
        # Lower log-loss = better signal = higher weight
        weights = compute_log_loss_weights({"good": 0.3, "bad": 0.9})
        assert weights["good"] > weights["bad"]


# ── TestDefaultThreshold ──────────────────────────────────────────────────


class TestDefaultThreshold:
    """Verify DEFAULT_THRESHOLD constant."""

    def test_default_threshold_value(self):
        assert DEFAULT_THRESHOLD == 20

    def test_threshold_parameter_passthrough(self):
        replay_path = _make_replay_data(_SAMPLE_MATCHES)
        try:
            output_fd, output_path = tempfile.mkstemp(
                suffix=".json", prefix="weights_", text=True
            )
            os.close(output_fd)
            try:
                config = run_calibration(
                    replay_data_path=replay_path,
                    threshold=5,
                    output_path=output_path,
                )
                assert config["threshold"] == 5
            finally:
                _cleanup_temp(output_path)
        finally:
            _cleanup_temp(replay_path)


# ── TestGetDefaultOutputPath ──────────────────────────────────────────────


class TestGetDefaultOutputPath:
    """Verify _get_default_output_path returns correct path."""

    def test_output_path_ends_with_signal_weights_json(self):
        path = _get_default_output_path()
        assert path.endswith("signal_weights.json")

    def test_output_path_contains_config_dir(self):
        path = _get_default_output_path()
        # Verify it points to competitions/ucl/config/signal_weights.json
        assert "config" in path
