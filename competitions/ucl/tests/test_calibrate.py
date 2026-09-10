"""Tests for calibration orchestration (run_calibration)."""

import json
import math
import os
import tempfile

import pytest

from competitions.ucl.src.calibrate import (
    run_calibration,
    DEFAULT_THRESHOLD,
    _build_signal_registry,
    _get_default_output_path,
    _outcome_index,
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


def _make_squad_values(teams: dict[str, float], tmp_path) -> str:
    """Write a squad_values JSON and return its path."""
    path = os.path.join(str(tmp_path), "squad_values.json")
    with open(path, "w") as f:
        json.dump(teams, f)
    return path


def _build_md_matches(md_num: int, n: int, teams: list[str]) -> list[dict]:
    """Build n matches for matchday md_num with random-ish outcomes."""
    import random
    rng = random.Random(md_num * 100 + n)
    matches = []
    shuffled = list(teams)
    rng.shuffle(shuffled)
    for i in range(0, min(len(shuffled) - 1, n * 2 - 1), 2):
        ta, tb = shuffled[i], shuffled[i + 1]
        mid = f"MD{md_num:02d}_{(i // 2) + 1:02d}"
        hs = rng.randint(0, 4)
        aws = rng.randint(0, 4)
        matches.append({
            "match_id": mid,
            "team_a": ta,
            "team_b": tb,
            "home_score": hs,
            "away_score": aws,
        })
        if len(matches) >= n:
            break
    return matches


def _build_synthetic_season(
    tmp_path,
    n_md: int = 8,
    matches_per_md: int = 9,
    include_dates: bool = True,
    include_squad_values: bool = True,
) -> tuple[str, list[dict], str | None]:
    """Build a synthetic season with n_md matchdays.

    Returns (replay_path, all_matches, squad_values_path_or_None).
    """
    import random
    rng = random.Random(42)
    teams = [f"Team_{i}" for i in range(1, matches_per_md * 2 + 1)]
    all_matches = []
    for md in range(1, n_md + 1):
        shuffled = list(teams)
        rng.shuffle(shuffled)
        for i in range(0, len(shuffled) - 1, 2):
            ta, tb = shuffled[i], shuffled[i + 1]
            mid = f"MD{md:02d}_{(i // 2) + 1:02d}"
            match = {
                "match_id": mid,
                "team_a": ta,
                "team_b": tb,
                "home_score": rng.randint(0, 4),
                "away_score": rng.randint(0, 4),
            }
            if include_dates:
                import datetime
                base = datetime.date(2026, 9, 15)
                matchday_date = base + datetime.timedelta(weeks=md - 1)
                match["event_date"] = matchday_date.isoformat()
            all_matches.append(match)

    replay_path = _make_replay_data(all_matches)

    sv_path = None
    if include_squad_values:
        sv = {t: float(rng.randint(50, 1200)) for t in teams}
        sv_path = _make_squad_values(sv, tmp_path)

    return replay_path, all_matches, sv_path


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
                # New keys
                assert "metric" in config
                assert config["metric"] == "multi_class_log_loss"
                assert "split" in config
                assert "n_fit" in config["split"]
                assert "n_oos" in config["split"]
                assert "chronology" in config["split"]
                assert "signals_available" in config
                assert "in_sample" in config
                assert "out_of_sample" in config
                assert "verdict" in config
                assert "written" in config
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
                if config["weights"]:
                    assert abs(total_weight - 1.0) < 0.01
                else:
                    # No available signals -> empty weights is correct
                    assert total_weight == 0
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
            assert os.path.exists(output_path)
            tmp_files = [
                f for f in os.listdir(str(tmp_path))
                if f.endswith(".tmp")
            ]
            assert len(tmp_files) == 0
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
            with pytest.raises((ValueError, KeyError)):
                run_calibration(replay_data_path=replay_path)
        finally:
            _cleanup_temp(replay_path)


# ── TestPerSignalLogLoss ──────────────────────────────────────────────────


class TestPerSignalLogLoss:
    """Verify per-signal multi-class log-loss computation."""

    @staticmethod
    def _manual_multiclass_log_loss(predictions: list[dict], actuals: list[tuple]) -> float:
        """Compute multi-class log loss (football_core.evaluation.multi_class_log_loss style)
        from predictions and actuals."""
        from football_core.evaluation import multi_class_log_loss as mcll
        probs = [[p["home"], p["draw"], p["away"]] for p in predictions]
        actual_indices = [int(a[0]) for a in actuals]  # 1.0 -> home win -> 0
        # Re-derive index from actual tuple
        idx_actuals = []
        for a in actuals:
            if a[0] == 1.0:
                idx_actuals.append(0)
            elif a[2] == 1.0:
                idx_actuals.append(2)
            else:
                idx_actuals.append(1)
        return mcll(probs, idx_actuals)

    def test_multiclass_log_loss_formula(self):
        """Test that multi_class_log_loss matches expected formula."""
        from football_core.evaluation import multi_class_log_loss as mcll
        # Perfect prediction: p=[1.0, 0.0, 0.0] for home win (actual=0)
        ll = mcll([[1.0, 0.0, 0.0]], [0])
        assert ll < 0.001

    def test_equal_log_losses_produce_uniform_weights(self):
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
        assert abs(sum(weights.values()) - 1.0) < 1e-5

    def test_known_probability_pattern(self):
        """Verify with known probabilities and actual outcomes."""
        from football_core.evaluation import multi_class_log_loss as mcll

        probs = [[0.6, 0.3, 0.1], [0.2, 0.6, 0.2]]
        actuals = [0, 1]  # home win, draw
        ll = mcll(probs, actuals)

        # Compute expected: -log(0.6) for match 1, -log(0.6) for match 2
        expected = (-math.log(0.6) + -math.log(0.6)) / 2
        assert abs(ll - expected) < 1e-10

    def test_better_signal_gets_higher_weight(self):
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
        assert "config" in path


# ── NEW-1: Synthetic data with split and verdict ──────────────────────────


class TestSyntheticSplitAndVerdict:
    """Synthetic data: verify split, weights, OOS, verdict, and write gate."""

    def test_split_and_weights_with_squad_values(self, tmp_path):
        """8 MDs, last 3 OOS. Only squad_value available -> UNVERIFIED (1 signal)."""
        n_md = 8
        matches_per_md = 9
        teams = [f"Team_{i}" for i in range(1, matches_per_md * 2 + 1)]
        sv = {t: float(100 + i * 50) for i, t in enumerate(teams)}

        replay_path, all_matches, sv_path = _build_synthetic_season(
            tmp_path, n_md=n_md, matches_per_md=matches_per_md,
            include_dates=False, include_squad_values=True,
        )
        # Overwrite sv_path with our own
        sv_path = _make_squad_values(sv, tmp_path)

        output_fd, output_path = tempfile.mkstemp(
            suffix=".json", prefix="weights_", text=True
        )
        os.close(output_fd)
        try:
            config = run_calibration(
                replay_data_path=replay_path,
                output_path=output_path,
                squad_values_path=sv_path,
                threshold=5,
            )

            # Split
            assert config["split"]["n_fit"] > 0
            assert config["split"]["n_oos"] > 0
            assert config["split"]["n_fit"] + config["split"]["n_oos"] == len(all_matches)
            assert config["split"]["chronology"] in ("matchday", "date")

            # Weights only for available signals
            for sig_name in config["weights"]:
                assert config["signals_available"][sig_name] == "available"

            # squad_value is the only available signal (no dates, no elo, no odds)
            assert config["signals_available"]["squad_value"] == "available"
            assert config["signals_available"]["refined_elo"].startswith("insufficient_data")
            assert config["signals_available"]["market_odds"].startswith("insufficient_data")

            # OOS dict has required keys
            oos = config["out_of_sample"]
            assert "ensemble_log_loss" in oos
            assert "uniform_log_loss" in oos
            assert "frequency_log_loss" in oos
            assert oos["n"] > 0

            # Verdict: UNVERIFIED because only 1 real signal
            assert config["verdict"]["status"] == "UNVERIFIED"
            assert any("1 real signal" in r for r in config["verdict"]["reasons"])

        finally:
            _cleanup_temp(output_path)
            _cleanup_temp(replay_path)

    def test_require_verified_blocks_write(self, tmp_path):
        """require_verified=True blocks writing when verdict != PASS."""
        replay_path, _, sv_path = _build_synthetic_season(
            tmp_path, n_md=8, matches_per_md=9,
            include_dates=False, include_squad_values=True,
        )
        output_path = os.path.join(str(tmp_path), "weights_blocked.json")

        config = run_calibration(
            replay_data_path=replay_path,
            output_path=output_path,
            squad_values_path=sv_path,
            threshold=5,
            require_verified=True,
        )

        assert config["verdict"]["status"] != "PASS"
        assert config["written"] is False
        assert not os.path.exists(output_path)
        _cleanup_temp(replay_path)

    def test_unverified_never_overwrites_production_path(self, tmp_path, monkeypatch):
        """An UNVERIFIED calibration must never clobber production weights,
        even when require_verified is not set."""
        replay_path, _, sv_path = _build_synthetic_season(
            tmp_path, n_md=8, matches_per_md=9,
            include_dates=False, include_squad_values=True,
        )
        prod = os.path.join(str(tmp_path), "prod_weights.json")

        monkeypatch.setattr(
            "competitions.ucl.src.calibrate._get_default_output_path",
            lambda: prod,
        )
        try:
            config = run_calibration(
                replay_data_path=replay_path,
                squad_values_path=sv_path,
                threshold=5,
            )
            assert config["verdict"]["status"] == "UNVERIFIED"
            assert config["written"] is False
            assert not os.path.exists(prod)
            assert any("production" in r for r in config["verdict"]["reasons"])
        finally:
            _cleanup_temp(replay_path)

    def test_require_verified_allows_write_on_pass(self, tmp_path):
        """require_verified=True allows writing when verdict == PASS.

        To get PASS we need >= 2 real signals with >= 30 OOS.
        We provide both elo_ratings and squad_values so refined_elo + squad_value
        are available.  No event_dates so matchday-based split is used.
        11 matches/MD x 12 MDs = 132 total, last 3 MDs = 33 OOS >= 30.
        """
        import random
        rng = random.Random(99)
        n_md = 12
        matches_per_md = 11
        teams = [f"T{i}" for i in range(1, matches_per_md * 2 + 1)]
        sv = {t: float(rng.randint(100, 1200)) for t in teams}
        elo = {t: float(rng.randint(1500, 2100)) for t in teams}

        all_matches = []
        for md in range(1, n_md + 1):
            shuffled = list(teams)
            rng.shuffle(shuffled)
            for i in range(0, len(shuffled) - 1, 2):
                ta, tb = shuffled[i], shuffled[i + 1]
                mid = f"MD{md:02d}_{(i // 2) + 1:02d}"
                all_matches.append({
                    "match_id": mid,
                    "team_a": ta,
                    "team_b": tb,
                    "home_score": rng.randint(0, 4),
                    "away_score": rng.randint(0, 4),
                })

        replay_path = _make_replay_data(all_matches)
        sv_path = _make_squad_values(sv, tmp_path)
        output_path = os.path.join(str(tmp_path), "weights_pass.json")

        try:
            config = run_calibration(
                replay_data_path=replay_path,
                output_path=output_path,
                squad_values_path=sv_path,
                elo_ratings=elo,
                threshold=5,
                require_verified=True,
            )

            avail_available = [k for k, v in config["signals_available"].items() if v == "available"]
            assert "squad_value" in avail_available
            assert "refined_elo" in avail_available

            # Last 3 of 12 MDs = 33 OOS, 99 fit
            assert config["split"]["n_oos"] == 33
            assert config["split"]["n_fit"] == 99

            if config["verdict"]["status"] == "PASS":
                assert config["written"] is True
                assert os.path.exists(output_path)
            else:
                assert config["written"] is False
                assert not os.path.exists(output_path)
        finally:
            _cleanup_temp(replay_path)

    def test_no_data_empty_weights(self, tmp_path):
        """Replay data with no elo/odds/dates/squad_values -> weights empty."""
        import random
        rng = random.Random(77)
        teams = [f"Alpha_{i}" for i in range(1, 11)]
        matches = []
        for md in range(1, 6):
            shuffled = list(teams)
            rng.shuffle(shuffled)
            for i in range(0, len(shuffled) - 1, 2):
                ta, tb = shuffled[i], shuffled[i + 1]
                matches.append({
                    "match_id": f"MD{md:02d}_{(i // 2) + 1:02d}",
                    "team_a": ta,
                    "team_b": tb,
                    "home_score": rng.randint(0, 3),
                    "away_score": rng.randint(0, 3),
                    # No event_date, no odds, no elo
                })

        replay_path = _make_replay_data(matches)
        # Use empty squad_values to prevent default file from providing data
        empty_sv = _make_squad_values({}, tmp_path)
        output_fd, output_path = tempfile.mkstemp(
            suffix=".json", prefix="weights_", text=True
        )
        os.close(output_fd)
        try:
            config = run_calibration(
                replay_data_path=replay_path,
                output_path=output_path,
                threshold=3,
                squad_values_path=empty_sv,
            )
            # No signals available -> weights empty
            assert config["weights"] == {}
            assert config["verdict"]["status"] == "UNVERIFIED"
            # signals_available should list reasons for each
            for sig_name, reason in config["signals_available"].items():
                assert reason.startswith("insufficient_data") or reason == "available"
        finally:
            _cleanup_temp(output_path)
            _cleanup_temp(replay_path)


# ── NEW-2: No available signals ───────────────────────────────────────────


class TestNoAvailableSignals:
    """Replay data with no elo/odds/dates/squad_values -> no available signals."""

    def test_no_signals_available(self, tmp_path):
        import random
        rng = random.Random(55)
        teams = [f"X_{i}" for i in range(1, 11)]
        matches = []
        for md in range(1, 6):
            shuffled = list(teams)
            rng.shuffle(shuffled)
            for i in range(0, len(shuffled) - 1, 2):
                ta, tb = shuffled[i], shuffled[i + 1]
                matches.append({
                    "match_id": f"MD{md:02d}_{(i // 2) + 1:02d}",
                    "team_a": ta,
                    "team_b": tb,
                    "home_score": rng.randint(0, 3),
                    "away_score": rng.randint(0, 3),
                })

        replay_path = _make_replay_data(matches)
        # Use empty squad_values to prevent default file from providing data
        empty_sv = _make_squad_values({}, tmp_path)
        output_fd, output_path = tempfile.mkstemp(
            suffix=".json", prefix="weights_", text=True
        )
        os.close(output_fd)
        try:
            config = run_calibration(
                replay_data_path=replay_path,
                output_path=output_path,
                threshold=3,
                squad_values_path=empty_sv,
            )
            assert config["weights"] == {}
            assert config["verdict"]["status"] == "UNVERIFIED"
            # All signals should be insufficient
            for sig_name, status in config["signals_available"].items():
                if sig_name != "squad_value":
                    assert status.startswith("insufficient_data")
        finally:
            _cleanup_temp(output_path)
            _cleanup_temp(replay_path)


# ── NEW-3: Chronological integrity ────────────────────────────────────────


class TestChronologicalIntegrity:
    """OOS contexts never see their own result; fit contexts are prior-only."""

    def test_oos_context_excludes_own_result(self, tmp_path):
        from competitions.ucl.src.historical import (
            build_context_for_match,
            load_replay_matches,
        )

        n_md = 8
        matches_per_md = 9
        teams = [f"Team_{i}" for i in range(1, matches_per_md * 2 + 1)]
        sv = {t: float(100 + i * 50) for i, t in enumerate(teams)}

        replay_path, all_matches, sv_path = _build_synthetic_season(
            tmp_path, n_md=n_md, matches_per_md=matches_per_md,
            include_dates=False, include_squad_values=True,
        )

        try:
            loaded = load_replay_matches(replay_path)
            # Check OOS matches (last 3 MDs)
            for m in loaded:
                md_match = None
                import re
                md_num = re.match(r"^MD(\d{2})", m.get("match_id", ""))
                if md_num and int(md_num.group(1)) >= 6:
                    ctx = build_context_for_match(m, loaded, squad_values=sv)
                    # Context should not contain the match itself
                    ctx_ids = {pm.get("match_id") for pm in ctx.fixtures}
                    assert m.get("match_id") not in ctx_ids, (
                        f"OOS context for {m['match_id']} contains itself"
                    )
                    # played_results should not contain the match's own outcome
                    for pr in ctx.played_results:
                        assert pr.get("match_id") != m.get("match_id"), (
                            f"OOS played_results for {m['match_id']} contains itself"
                        )
        finally:
            _cleanup_temp(replay_path)

    def test_fit_context_prior_only(self, tmp_path):
        from competitions.ucl.src.historical import (
            build_context_for_match,
            load_replay_matches,
            order_matches,
            chronological_key,
        )

        n_md = 8
        matches_per_md = 9
        teams = [f"Team_{i}" for i in range(1, matches_per_md * 2 + 1)]
        sv = {t: float(100 + i * 50) for i, t in enumerate(teams)}

        replay_path, all_matches, sv_path = _build_synthetic_season(
            tmp_path, n_md=n_md, matches_per_md=matches_per_md,
            include_dates=False, include_squad_values=True,
        )

        try:
            loaded = load_replay_matches(replay_path)
            ordered = order_matches(loaded)
            # For each fit match (first 5 MDs)
            for m in ordered:
                md_match = None
                import re
                md_num = re.match(r"^MD(\d{2})", m.get("match_id", ""))
                if md_num and int(md_num.group(1)) <= 5:
                    ctx = build_context_for_match(m, loaded, squad_values=sv)
                    target_key = chronological_key(m)
                    # All fixtures in context must be strictly before this match
                    for pm in ctx.fixtures:
                        pm_key = chronological_key(pm)
                        assert pm_key < target_key, (
                            f"Fit context for {m['match_id']} contains "
                            f"future match {pm.get('match_id')} (key {pm_key} >= {target_key})"
                        )
        finally:
            _cleanup_temp(replay_path)


# ── NEW-4: Output file writing ────────────────────────────────────────────


class TestOutputFileWriting:
    """Verify output_path writing works and file has required keys."""

    def test_output_file_reload(self, tmp_path):
        replay_path, _, sv_path = _build_synthetic_season(
            tmp_path, n_md=8, matches_per_md=9,
            include_dates=False, include_squad_values=True,
        )
        output_path = os.path.join(str(tmp_path), "weights_reload.json")

        try:
            config = run_calibration(
                replay_data_path=replay_path,
                output_path=output_path,
                squad_values_path=sv_path,
                threshold=5,
            )

            assert os.path.exists(output_path)
            with open(output_path) as f:
                reloaded = json.load(f)

            # All required top-level keys
            for key in [
                "version", "calibrated_at", "method", "source",
                "n_matches", "threshold", "weights", "metric",
                "per_signal", "split", "signals_available",
                "in_sample", "out_of_sample", "verdict", "written",
            ]:
                assert key in reloaded, f"Missing key: {key}"

            assert reloaded == config
        finally:
            _cleanup_temp(replay_path)


# ── TestOutcomeIndex ──────────────────────────────────────────────────────


class TestOutcomeIndex:
    """Verify _outcome_index helper."""

    def test_home_win(self):
        assert _outcome_index({"home_score": 2, "away_score": 1}) == 0

    def test_draw(self):
        assert _outcome_index({"home_score": 1, "away_score": 1}) == 1

    def test_away_win(self):
        assert _outcome_index({"home_score": 0, "away_score": 3}) == 2

    def test_missing_scores(self):
        assert _outcome_index({}) is None
        assert _outcome_index({"home_score": None, "away_score": 1}) is None
