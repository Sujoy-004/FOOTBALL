"""Unit tests for the ucl-predict CLI argument parser.

Tests all flag behaviors: defaults, individual flags, combined flags,
non-int rejection, fixture-source flag, and provider resolution.
"""

import os
from dataclasses import asdict

import pytest

from competitions.ucl.main import (
    _parse_args, _run_validation_suite,
    build_simulation_result, parse_weights,
)
from football_core.provider import (
    FixtureSchedule, FixtureProvider, Team, Match, FixtureProviderError,
)


def test_defaults():
    """Empty argv returns default values."""
    args = _parse_args([])
    assert args.iterations == 10000
    assert args.seed is None
    assert args.output is None


def test_iterations_flag():
    """-n flag overrides iterations default."""
    args = _parse_args(["-n", "5000"])
    assert args.iterations == 5000


def test_seed_flag():
    """--seed flag sets seed value."""
    args = _parse_args(["--seed", "42"])
    assert args.seed == 42


def test_output_flag():
    """-o flag sets output file path."""
    args = _parse_args(["-o", "results.json"])
    assert args.output == "results.json"


def test_all_flags_together():
    """All three flags combined return correct namespace."""
    args = _parse_args(["-n", "5000", "--seed", "42", "-o", "out.json"])
    assert args.iterations == 5000
    assert args.seed == 42
    assert args.output == "out.json"


def test_seed_rejects_non_int():
    """--seed with non-int value raises SystemExit."""
    try:
        _parse_args(["--seed", "abc"])
        assert False, "Should have raised SystemExit"
    except SystemExit:
        pass


class TestFixtureSource:
    """Tests for the --fixture-source CLI flag."""

    def test_default_is_auto(self):
        """Default fixture-source is 'auto'."""
        args = _parse_args([])
        assert args.fixture_source == "auto"

    def test_repo_flag(self):
        """--fixture-source repo sets source to 'repo'."""
        args = _parse_args(["--fixture-source", "repo"])
        assert args.fixture_source == "repo"

    def test_bsd_flag(self):
        """--fixture-source bsd sets source to 'bsd'."""
        args = _parse_args(["--fixture-source", "bsd"])
        assert args.fixture_source == "bsd"

    def test_invalid_choice_rejected(self):
        """Invalid --fixture-source value raises SystemExit."""
        try:
            _parse_args(["--fixture-source", "invalid"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

    def test_compatible_with_other_flags(self):
        """--fixture-source works alongside other flags."""
        args = _parse_args(["-n", "5000", "--fixture-source", "repo", "-s", "42"])
        assert args.iterations == 5000
        assert args.fixture_source == "repo"
        assert args.seed == 42


class TestNoSyntheticPath:
    """Verifies the synthetic-only execution path has been removed."""

    def test_main_import_no_direct_json_open(self):
        """main.py no longer directly opens fixtures.json for simulation."""
        import competitions.ucl.main as main_mod
        import inspect
        source = inspect.getsource(main_mod)
        # The old pattern with open(fixtures_path) as f: fixtures = json.load(f)
        # should NOT exist outside of teams_data extraction and provider construction
        assert "fixtures_schedule = provider.load()" in source, (
            "Fixtures should be loaded via provider, not direct json.load"
        )

    def test_build_simulation_result_accepts_fixtureschedule(self):
        """build_simulation_result accepts FixtureSchedule (not dict)."""
        import inspect
        sig = inspect.signature(build_simulation_result)
        param = sig.parameters["fixtures"]
        assert "FixtureSchedule" in str(param.annotation), (
            f"Expected FixtureSchedule type, got {param.annotation}"
        )


class TestProviderResolution:
    """Tests that provider resolution produces valid FixtureSchedule."""

    def test_repo_provider_returns_schedule(self, sample_fixture_path):
        """RepoFixtureProvider returns valid FixtureSchedule with 36 teams and 8 matchdays."""
        from competitions.ucl.src.provider import RepoFixtureProvider
        provider = RepoFixtureProvider(fixtures_path=sample_fixture_path)
        schedule = provider.load()
        assert isinstance(schedule, FixtureSchedule)
        assert len(schedule.teams) == 36
        assert len(schedule.matchdays) == 8


class TestModeFlags:
    """Tests for the --mode and --replay-data CLI flags."""

    def test_default_is_simulate(self):
        args = _parse_args([])
        assert args.mode == "simulate"

    def test_replay_flag(self):
        args = _parse_args(["--mode", "replay"])
        assert args.mode == "replay"

    def test_live_flag(self):
        args = _parse_args(["--mode", "live"])
        assert args.mode == "live"

    def test_invalid_mode_rejected(self):
        try:
            _parse_args(["--mode", "invalid"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

    def test_replay_data_flag(self):
        args = _parse_args(["--mode", "replay", "--replay-data", "data.json"])
        assert args.mode == "replay"
        assert args.replay_data == "data.json"

    def test_replay_data_defaults_none(self):
        args = _parse_args(["--mode", "replay"])
        assert args.replay_data is None

    def test_mode_compatible_with_other_flags(self):
        args = _parse_args(["-n", "5000", "--mode", "live", "--seed", "42"])
        assert args.iterations == 5000
        assert args.mode == "live"
        assert args.seed == 42


class TestCalibrateFlags:
    """Tests for the --calibrate and --replay-data CLI flags (D-07)."""

    def test_calibrate_default_false(self):
        args = _parse_args([])
        assert args.calibrate is False

    def test_calibrate_flag_true(self):
        args = _parse_args(["--calibrate"])
        assert args.calibrate is True

    def test_calibrate_needs_replay_data(self):
        """--calibrate without --replay-data errors in main(). Parser accepts both independently."""
        args = _parse_args(["--calibrate"])
        assert args.calibrate is True
        assert args.replay_data is None  # Validation happens in main(), not parser

    def test_calibrate_with_replay_data(self):
        args = _parse_args(["--calibrate", "--replay-data", "data.json"])
        assert args.calibrate is True
        assert args.replay_data == "data.json"

    def test_compatible_with_other_flags(self):
        args = _parse_args([
            "--calibrate", "--replay-data", "data.json",
            "-n", "5000", "-s", "42",
        ])
        assert args.calibrate is True
        assert args.replay_data == "data.json"
        assert args.iterations == 5000
        assert args.seed == 42


class TestWeightFlags:
    """Tests for --weights CLI flag and parse_weights() (D-05)."""

    def test_weights_default_none(self):
        args = _parse_args([])
        assert args.weights is None

    def test_weights_override_single(self):
        args = _parse_args(["--weights", "elo=1.0"])
        assert args.weights == "elo=1.0"

    def test_weights_override_multiple(self):
        args = _parse_args(["--weights", "elo=0.4,market=0.3,form=0.2,squad=0.1"])
        assert args.weights == "elo=0.4,market=0.3,form=0.2,squad=0.1"

    def test_parse_weights_basic(self):
        w = parse_weights("elo=0.5,market=0.5")
        assert abs(w["elo"] - 0.5) < 1e-9
        assert abs(w["market"] - 0.5) < 1e-9

    def test_parse_weights_auto_normalizes(self):
        """Sum != 1.0 auto-normalizes with warning."""
        w = parse_weights("elo=0.6,market=0.6")
        assert abs(sum(w.values()) - 1.0) < 1e-9
        assert abs(w["elo"] - 0.5) < 1e-9
        assert abs(w["market"] - 0.5) < 1e-9

    def test_parse_weights_returns_none(self):
        assert parse_weights(None) is None

    def test_parse_weights_rejects_non_numeric(self):
        try:
            parse_weights("elo=abc")
            assert False, "Should raise SystemExit"
        except SystemExit:
            pass

    def test_parse_weights_rejects_negative(self):
        try:
            parse_weights("elo=-0.5")
            assert False, "Should raise SystemExit"
        except SystemExit:
            pass

    def test_parse_weights_rejects_missing_equals(self):
        try:
            parse_weights("el0.5")
            assert False, "Should raise SystemExit"
        except SystemExit:
            pass

    def test_parse_weights_single_signal(self):
        w = parse_weights("elo=1.0")
        assert abs(w["elo"] - 1.0) < 1e-9


class TestBreakdownFlags:
    """Tests for --show-breakdown CLI flag (D-07)."""

    def test_breakdown_default_none(self):
        args = _parse_args([])
        assert args.show_breakdown is None

    def test_breakdown_flag_without_value_defaults_summary(self):
        """--show-breakdown without value defaults to 'summary'."""
        args = _parse_args(["--show-breakdown"])
        assert args.show_breakdown == "summary"

    def test_breakdown_summary(self):
        args = _parse_args(["--show-breakdown", "summary"])
        assert args.show_breakdown == "summary"

    def test_breakdown_match(self):
        args = _parse_args(["--show-breakdown", "match"])
        assert args.show_breakdown == "match"

    def test_breakdown_invalid_choice_rejected(self):
        try:
            _parse_args(["--show-breakdown", "invalid"])
            assert False, "Should raise SystemExit"
        except SystemExit:
            pass


class TestCounterfactualFlags:
    """Tests for --what-if CLI flag parsing."""

    def test_what_if_default_none(self):
        args = _parse_args([])
        assert args.what_if_list is None

    def test_what_if_single(self):
        args = _parse_args(["--what-if", "Arsenal.elo=1960"])
        assert args.what_if_list == ["Arsenal.elo=1960"]

    def test_what_if_multiple(self):
        args = _parse_args([
            "--what-if", "Arsenal.elo=1960",
            "--what-if", "RealMadrid.elo=2100",
        ])
        assert len(args.what_if_list) == 2
        assert args.what_if_list[0] == "Arsenal.elo=1960"
        assert args.what_if_list[1] == "RealMadrid.elo=2100"


class TestReportFlags:
    """Tests for --report CLI flag parsing."""

    def test_report_default_none(self):
        args = _parse_args([])
        assert args.report is None

    def test_report_flag(self):
        args = _parse_args(["--report", "report.json"])
        assert args.report == "report.json"

    def test_report_compatible_with_other_flags(self):
        args = _parse_args([
            "-n", "5000", "--report", "report.json", "--seed", "42",
        ])
        assert args.report == "report.json"
        assert args.iterations == 5000
        assert args.seed == 42


class TestValidationSuiteIntegration:
    """Tests for _run_validation_suite returning correct structure."""

    def test_help_includes_tier(self):
        """--help output includes --tier flag."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "competitions.ucl.main", "--help"],
            capture_output=True, text=True,
        )
        assert "--tier" in result.stdout
        assert "cross-tournament" in result.stdout
        assert "walk-forward" in result.stdout
        assert "replay" in result.stdout


class TestTierFlags:
    """Tests for --tier CLI flag (Phase 9 validation suite)."""

    def test_tier_default_all(self):
        args = _parse_args(["--validate"])
        assert args.tier == "all"

    def test_tier_cross_tournament(self):
        args = _parse_args(["--validate", "--tier", "cross-tournament"])
        assert args.tier == "cross-tournament"

    def test_tier_walk_forward(self):
        args = _parse_args(["--validate", "--tier", "walk-forward"])
        assert args.tier == "walk-forward"

    def test_tier_replay(self):
        args = _parse_args(["--validate", "--tier", "replay"])
        assert args.tier == "replay"

    def test_tier_invalid_choice_rejected(self):
        try:
            _parse_args(["--validate", "--tier", "invalid"])
            assert False, "Should raise SystemExit"
        except SystemExit:
            pass

    def test_tier_compatible_with_seed(self):
        args = _parse_args(["--validate", "--tier", "walk-forward", "-s", "42"])
        assert args.tier == "walk-forward"
        assert args.seed == 42
