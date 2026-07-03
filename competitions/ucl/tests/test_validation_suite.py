"""Tests for ValidationSuite — walk-forward and replay validation."""
from __future__ import annotations

import os

import pytest

from competitions.ucl.src.validation_suite import ValidationSuite, ValidationResult
from football_core.signal import BlendedPrediction, PredictionContext


class _MockEngine:
    """Minimal EnsembleEngine stub returning controlled predictions.

    For test purposes, returns a configurable BlendedPrediction for
    any match evaluated. Used to isolate ValidationSuite logic from
    signal ensemble complexity.
    """

    def __init__(self, default_probs: tuple[float, float, float] | None = None):
        self._default = default_probs or (0.5, 0.25, 0.25)

    def evaluate(self, match: dict, context: PredictionContext) -> BlendedPrediction:
        """Return fixed probabilities for any match."""
        # If the match has a winner, return slightly informed probabilities
        if match.get("home_score") is not None and match.get("away_score") is not None:
            hs, aws = match["home_score"], match["away_score"]
            if hs > aws:
                return BlendedPrediction(0.8, 0.15, 0.05, {}, {})
            elif aws > hs:
                return BlendedPrediction(0.05, 0.15, 0.8, {}, {})
            else:
                return BlendedPrediction(0.1, 0.8, 0.1, {}, {})
        return BlendedPrediction(*self._default, {}, {})


class TestWalkForwardSplits:
    """Tests for the walk-forward split logic."""

    def test_basic_split(self):
        """3 seasons with window=2 yields 1 split: seasons[0:2] -> seasons[2]."""
        seasons = {
            "Y2023": {"matches": [], "teams": [], "standings": []},
            "Y2024": {"matches": [], "teams": [], "standings": []},
            "Y2025": {"matches": [], "teams": [], "standings": []},
        }
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons)
        splits = suite.walk_forward_splits(window=2)
        assert len(splits) == 1
        source, eval_id = splits[0]
        assert source == ["Y2023", "Y2024"]
        assert eval_id == "Y2025"

    def test_five_seasons_window_2(self):
        """5 seasons with window=2 yields 3 splits."""
        seasons = {f"Y{n}": {"matches": [], "teams": [], "standings": []}
                   for n in range(2022, 2027)}
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons)
        splits = suite.walk_forward_splits(window=2)
        assert len(splits) == 3
        assert splits[0] == (["Y2022", "Y2023"], "Y2024")
        assert splits[1] == (["Y2023", "Y2024"], "Y2025")
        assert splits[2] == (["Y2024", "Y2025"], "Y2026")

    def test_window_equals_season_count(self):
        """When window == number of seasons, no splits (no eval season)."""
        seasons = {
            "Y2023": {"matches": [], "teams": [], "standings": []},
            "Y2024": {"matches": [], "teams": [], "standings": []},
            "Y2025": {"matches": [], "teams": [], "standings": []},
        }
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons)
        splits = suite.walk_forward_splits(window=3)
        assert len(splits) == 0

    def test_window_larger_than_seasons(self):
        """When window > seasons, no splits."""
        seasons = {
            "Y2023": {"matches": [], "teams": [], "standings": []},
            "Y2024": {"matches": [], "teams": [], "standings": []},
        }
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons)
        splits = suite.walk_forward_splits(window=5)
        assert len(splits) == 0

    def test_empty_seasons(self):
        """No seasons yields no splits."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        splits = suite.walk_forward_splits(window=2)
        assert len(splits) == 0

    def test_correct_season_ids_from_fixture(self, seasons_data):
        """With fixture seasons_data, splits use correct season IDs."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        splits = suite.walk_forward_splits(window=2)
        # 4 seasons, window=2 => 2 splits
        assert len(splits) == 2
        ids = list(seasons_data.keys())
        assert splits[0] == (ids[:2], ids[2])
        assert splits[1] == (ids[1:3], ids[3])


class TestValidationResult:
    """Tests for the ValidationResult dataclass."""

    def test_basic_creation(self):
        result = ValidationResult(
            tier="walk_forward",
            date="2026-07-03",
            n_matches=100,
            n_seasons=4,
            metrics={"log_loss": 0.5, "brier": 0.2, "ece": 0.05},
        )
        assert result.tier == "walk_forward"
        assert result.metrics["log_loss"] == 0.5
        assert result.baseline is False

    def test_with_details(self):
        result = ValidationResult(
            tier="replay",
            date="2026-07-03",
            n_matches=50,
            n_seasons=1,
            metrics={"ece": 0.03, "n_decision_points": 50},
            details={"per_matchday": [{"matchday_index": 0, "n_simulated": 25, "ece": 0.02}]},
        )
        assert result.details is not None
        assert len(result.details["per_matchday"]) == 1

    def test_baseline_flag(self):
        result = ValidationResult(
            tier="cross_tournament", date="2026-07-03",
            n_matches=0, n_seasons=0, metrics={}, baseline=True,
        )
        assert result.baseline is True

    def test_default_baseline_false(self):
        result = ValidationResult(
            tier="walk_forward", date="2026-07-03",
            n_matches=0, n_seasons=0, metrics={},
        )
        assert result.baseline is False


class TestTier2WalkForward:
    """Tests for the walk-forward validation (Tier 2)."""

    def test_returns_validation_result(self, seasons_data):
        """run_tier_2_walk_forward returns a ValidationResult."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_2_walk_forward(window=2)
        assert isinstance(result, ValidationResult)
        assert result.tier == "walk_forward"

    def test_metrics_are_numeric(self, seasons_data):
        """All metrics are floats or ints."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_2_walk_forward(window=2)
        for key in ("log_loss", "brier", "ece"):
            val = result.metrics.get(key)
            assert val is not None, f"Missing metric: {key}"
            assert isinstance(val, (int, float)), f"{key} is not numeric: {type(val)}"

    def test_season_ids_in_details(self, seasons_data):
        """Per-season details contain correct season IDs."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_2_walk_forward(window=2)
        assert result.details is not None
        per_season = result.details.get("per_season", [])
        ids = list(seasons_data.keys())
        # With 4 seasons and window=2, eval seasons are ids[2] and ids[3]
        eval_ids = {entry["season_id"] for entry in per_season}
        assert ids[2] in eval_ids
        assert ids[3] in eval_ids

    def test_n_matches_positive(self, seasons_data):
        """At least some matches are evaluated."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_2_walk_forward(window=2)
        assert result.n_matches > 0
        assert result.n_seasons > 0

    def test_known_metrics_values(self, seasons_data):
        """With mock engine that's highly confident, metrics should be decent."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_2_walk_forward(window=2)
        # The mock engine returns 0.8 for the correct outcome most of the time
        assert result.metrics["log_loss"] > 0.0
        assert result.metrics["brier"] > 0.0


class TestTier3Replay:
    """Tests for replay validation (Tier 3)."""

    def test_returns_validation_result(self, replay_matchdays):
        """run_tier_3_replay returns a ValidationResult."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_3_replay(replay_matchdays)
        assert isinstance(result, ValidationResult)
        assert result.tier == "replay"

    def test_has_ece_metric(self, replay_matchdays):
        """Replay result contains ECE metric."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_3_replay(replay_matchdays)
        assert "ece" in result.metrics
        assert isinstance(result.metrics["ece"], float)

    def test_has_decision_points(self, replay_matchdays):
        """Replay result tracks number of decision points."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_3_replay(replay_matchdays)
        assert result.metrics["n_decision_points"] > 0

    def test_details_contain_per_matchday(self, replay_matchdays):
        """Details include per_matchday breakdown."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_3_replay(replay_matchdays)
        assert result.details is not None
        assert "per_matchday" in result.details
        assert len(result.details["per_matchday"]) > 0

    def test_details_contain_calibration_bins(self, replay_matchdays):
        """Details include calibration bins."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_3_replay(replay_matchdays)
        assert result.details is not None
        assert "calibration_bins" in result.details

    def test_empty_matchdays(self):
        """Empty replay list returns zeroed result."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_3_replay([])
        assert result.metrics["ece"] == 0.0
        assert result.metrics["n_decision_points"] == 0

    def test_single_matchday(self):
        """Single matchday (no remaining fixtures) returns zeroed result."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_3_replay([
            [{"team_a": "TeamA", "team_b": "TeamB", "winner": "TeamA", "is_draw": False}],
        ])
        assert result.metrics["n_decision_points"] == 0


class TestTier1CrossTournament:
    """Tests for cross-tournament backtest (Tier 1)."""

    def test_returns_validation_result(self, seasons_data):
        """Returns a ValidationResult with tier='cross_tournament'."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_1_cross_tournament()
        assert isinstance(result, ValidationResult)
        assert result.tier == "cross_tournament"

    def test_has_trps_metric(self, seasons_data):
        """Result contains TRPS metric as float between 0 and 1."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_1_cross_tournament()
        assert "trps" in result.metrics
        assert isinstance(result.metrics["trps"], float)
        assert 0.0 <= result.metrics["trps"] <= 1.0

    def test_has_champion_accuracy(self, seasons_data):
        """Result contains champion_accuracy as float."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_1_cross_tournament()
        assert "champion_accuracy" in result.metrics
        assert isinstance(result.metrics["champion_accuracy"], float)

    def test_has_stage_accuracy(self, seasons_data):
        """Result contains stage_accuracy as float."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_1_cross_tournament()
        assert "stage_accuracy" in result.metrics
        assert isinstance(result.metrics["stage_accuracy"], float)

    def test_per_season_details(self, seasons_data):
        """Details contain per-season breakdown."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        result = suite.run_tier_1_cross_tournament()
        assert result.details is not None
        assert "per_season" in result.details
        for entry in result.details["per_season"]:
            assert "season_id" in entry
            assert "trps" in entry
            assert "champion_correct" in entry

    def test_single_season_returns_zero(self):
        """Only one season produces zeroed result (no historical comparison)."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {
            "Y2024": {"matches": [], "teams": [], "standings": []},
        })
        result = suite.run_tier_1_cross_tournament()
        assert result.metrics["trps"] == 0.0

    def test_empty_seasons(self):
        """No seasons returns zeroed metrics."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        result = suite.run_tier_1_cross_tournament()
        assert result.metrics["trps"] == 0.0


class TestStageGroups:
    """Tests for the stage grouping helper."""

    def test_36_teams_correct_group_sizes(self):
        """36 teams produce correct stage group sizes."""
        teams = [f"Team{i+1}" for i in range(36)]
        groups = ValidationSuite._compute_stage_groups(teams)
        assert len(groups["champion"]) == 1
        assert len(groups["runner_up"]) == 1
        assert len(groups["semifinal"]) == 2
        assert len(groups["quarterfinal"]) == 4
        assert len(groups["r16"]) == 8
        assert len(groups["playoff"]) == 8
        assert len(groups["eliminated"]) == 12

    def test_fewer_teams(self):
        """Works with fewer than 36 teams."""
        teams = [f"Team{i+1}" for i in range(8)]
        groups = ValidationSuite._compute_stage_groups(teams)
        assert len(groups["champion"]) == 1
        assert len(groups["runner_up"]) == 1
        assert len(groups["semifinal"]) == 2
        assert len(groups["quarterfinal"]) == 4

    def test_empty_teams(self):
        """Empty list produces empty groups."""
        groups = ValidationSuite._compute_stage_groups([])
        assert all(len(v) == 0 for v in groups.values())

    def test_stage_accuracy_perfect(self):
        """Perfect prediction yields stage accuracy 1.0."""
        teams = [f"Team{i+1}" for i in range(8)]
        groups = ValidationSuite._compute_stage_groups(teams)
        acc = ValidationSuite._stage_accuracy(teams, teams, groups)
        assert acc == pytest.approx(1.0)

    def test_stage_accuracy_imperfect(self):
        """Different ranking yields stage accuracy < 1.0."""
        actual = ["A", "B", "C", "D", "E", "F", "G", "H"]
        predicted = ["B", "A", "D", "C", "F", "E", "H", "G"]
        groups = ValidationSuite._compute_stage_groups(actual)
        acc = ValidationSuite._stage_accuracy(predicted, actual, groups)
        assert acc < 1.0


class TestRunAll:
    """Tests for the combined run_all() method."""

    def test_returns_dict_with_all_keys(self, seasons_data):
        """run_all() returns dict with phase, date, uncalibrated, etc."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        report = suite.run_all()
        assert isinstance(report, dict)
        assert report["phase"] == 9
        assert "date" in report
        assert report["uncalibrated"] is True
        assert "match_level" in report
        assert "tournament_level" in report
        assert "calibration" in report

    def test_match_level_has_expected_metrics(self, seasons_data):
        """match_level has log_loss, brier, ece."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        report = suite.run_all()
        for key in ("log_loss", "brier", "ece"):
            assert key in report["match_level"]

    def test_tournament_level_has_expected_metrics(self, seasons_data):
        """tournament_level has trps, champion_accuracy, stage_accuracy."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        report = suite.run_all()
        for key in ("trps", "champion_accuracy", "stage_accuracy"):
            assert key in report["tournament_level"]

    def test_metrics_are_numeric(self, seasons_data):
        """All metric values are numeric."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        report = suite.run_all()
        for level in ("match_level", "tournament_level"):
            for key, val in report[level].items():
                assert isinstance(val, (int, float)), f"{level}.{key} is {type(val)}"

    def test_n_seasons(self, seasons_data):
        """Report tracks season count."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        report = suite.run_all()
        assert report["n_seasons"] == 4


class TestSaveBaseline:
    """Tests for save_baseline() method."""

    def test_creates_json_file(self, seasons_data, tmp_path):
        """save_baseline creates a valid JSON file."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        path = suite.save_baseline(output_dir=str(tmp_path))
        assert os.path.exists(path)
        assert path.endswith(".json")

    def test_json_is_valid(self, seasons_data, tmp_path):
        """Saved JSON can be loaded and has expected structure."""
        import json
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        path = suite.save_baseline(output_dir=str(tmp_path))
        with open(path) as f:
            data = json.load(f)
        assert data["phase"] == 9
        assert data["uncalibrated"] is True
        assert "match_level" in data
        assert "tournament_level" in data

    def test_output_dir_created(self, seasons_data, tmp_path):
        """Non-existent output directory is created."""
        nested = tmp_path / "nonexistent" / "subdir"
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        path = suite.save_baseline(output_dir=str(nested))
        assert os.path.exists(nested)
        assert os.path.exists(path)

    def test_default_output_path(self, seasons_data):
        """Default output directory exists (data/ next to validation_suite.py)."""
        engine = _MockEngine()
        suite = ValidationSuite(engine, seasons_data)
        path = suite.save_baseline()
        assert os.path.exists(path)
        # Clean up
        if os.path.exists(path):
            os.remove(path)
