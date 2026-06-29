"""Tests for UCL fixture providers — Protocol conformance and FixtureSchedule validation."""

import json

import pytest

from football_core.provider import (
    FixtureProvider,
    FixtureSchedule,
    FixtureProviderError,
    Team,
    Match,
)


def _build_schedule_from_json(fixtures_path: str) -> FixtureSchedule:
    """Load a fixtures.json file and convert to FixtureSchedule dataclass."""
    with open(fixtures_path) as f:
        data = json.load(f)
    schedule_dict = data["schedule"]
    teams = [Team(**t) for t in schedule_dict["teams"]]
    matchdays = []
    for md in schedule_dict["matchdays"]:
        matches = [Match(**m) for m in md]
        matchdays.append(matches)
    return FixtureSchedule(teams=teams, matchdays=matchdays)


class TestFixtureProviderProtocol:
    """Tests that FixtureProvider is a Protocol and that provider stubs conform."""

    def test_fixture_provider_is_protocol(self):
        """FixtureProvider should be a runtime_checkable Protocol."""
        assert hasattr(FixtureProvider, "_is_protocol")
        assert FixtureProvider._is_protocol is True
        assert hasattr(FixtureProvider, "_is_runtime_protocol")
        assert FixtureProvider._is_runtime_protocol is True

    def test_protocol_has_load_method(self):
        """FixtureProvider Protocol should define a load() method."""
        assert hasattr(FixtureProvider, "load")
        assert callable(FixtureProvider.load)

    def test_bsd_provider_conforms(self):
        """A BSDFixtureProvider stub should pass isinstance(FixtureProvider) check."""
        class BSDFixtureProviderStub:
            def load(self) -> FixtureSchedule:
                return FixtureSchedule(teams=[], matchdays=[])

        provider = BSDFixtureProviderStub()
        assert isinstance(provider, FixtureProvider)

    def test_repo_provider_conforms(self):
        """A RepoFixtureProvider stub should pass isinstance(FixtureProvider) check."""
        class RepoFixtureProviderStub:
            def load(self) -> FixtureSchedule:
                return FixtureSchedule(teams=[], matchdays=[])

        provider = RepoFixtureProviderStub()
        assert isinstance(provider, FixtureProvider)


class TestFixtureScheduleValidation:
    """Tests for FixtureSchedule.validate() — delegates to existing validate_ucl_fixtures()."""

    def test_valid_schedule_passes(self, sample_fixture_path):
        """A valid 36-team, 8-matchday schedule should pass validate() without raising."""
        schedule = _build_schedule_from_json(sample_fixture_path)
        assert len(schedule.teams) == 36
        assert len(schedule.matchdays) == 8
        # validate() should not raise for a valid schedule
        schedule.validate()

    def test_invalid_team_count_raises(self):
        """A FixtureSchedule with 0 teams should raise ValueError on validate()."""
        schedule = FixtureSchedule(teams=[], matchdays=[])
        with pytest.raises(ValueError, match="Expected 36 teams"):
            schedule.validate()

    def test_invalid_matchday_count_raises(self, sample_36_teams_data):
        """A FixtureSchedule with 0 matchdays should raise ValueError on validate()."""
        teams = [Team(**t) for t in sample_36_teams_data]
        schedule = FixtureSchedule(teams=teams, matchdays=[])
        with pytest.raises(ValueError, match="Expected 8 matchdays"):
            schedule.validate()

    def test_validation_delegates_to_existing(self, monkeypatch, sample_fixture_path):
        """validate() should call validate_ucl_fixtures() from the existing validation module."""
        call_count = 0
        captured_arg = None

        def mock_validate(fixtures):
            nonlocal call_count, captured_arg
            call_count += 1
            captured_arg = fixtures
            return fixtures

        monkeypatch.setattr(
            "competitions.ucl.src.validation.validate_ucl_fixtures",
            mock_validate,
        )

        schedule = _build_schedule_from_json(sample_fixture_path)
        schedule.validate()

        assert call_count >= 1, "validate_ucl_fixtures was never called"
        assert captured_arg is not None
        assert "schedule" in captured_arg
