"""Tests for ValidationSuite — walk-forward and replay validation."""
from __future__ import annotations

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


class TestStubTier1:
    """Tests that the Tier 1 stub raises NotImplementedError until Plan 09-03."""

    def test_run_tier_1_raises(self):
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        with pytest.raises(NotImplementedError, match="Plan 09-03"):
            suite.run_tier_1_cross_tournament()

    def test_run_all_raises(self):
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        with pytest.raises(NotImplementedError, match="Plan 09-03"):
            suite.run_all()

    def test_save_baseline_raises(self):
        engine = _MockEngine()
        suite = ValidationSuite(engine, {})
        with pytest.raises(NotImplementedError, match="Plan 09-03"):
            suite.save_baseline()
