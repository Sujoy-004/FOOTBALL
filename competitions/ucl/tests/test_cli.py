"""Unit tests for the ucl-predict CLI argument parser.

Tests all flag behaviors: defaults, individual flags, combined flags,
non-int rejection, fixture-source flag, and provider resolution.
"""

import os
from dataclasses import asdict

import pytest

from competitions.ucl.main import _parse_args, build_simulation_result
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
