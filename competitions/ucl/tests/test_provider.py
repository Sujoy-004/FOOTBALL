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


class TestRepoFixtureProvider:
    """Tests for RepoFixtureProvider — JSON file loading and validation."""

    def test_loads_valid_schedule(self, sample_fixture_path):
        """RepoFixtureProvider.load() returns valid FixtureSchedule with 36 teams, 8 matchdays."""
        from competitions.ucl.src.provider import RepoFixtureProvider

        provider = RepoFixtureProvider(fixtures_path=sample_fixture_path)
        schedule = provider.load()
        assert isinstance(schedule, FixtureSchedule)
        assert len(schedule.teams) == 36
        assert len(schedule.matchdays) == 8

    def test_missing_file_raises(self):
        """Missing file path should raise FileNotFoundError."""
        from competitions.ucl.src.provider import RepoFixtureProvider

        provider = RepoFixtureProvider(fixtures_path="/nonexistent/path.json")
        with pytest.raises(FileNotFoundError):
            provider.load()

    def test_invalid_schedule_raises(self, tmp_path):
        """RepoFixtureProvider.load() should raise ValueError on invalid schedule data."""
        from competitions.ucl.src.provider import RepoFixtureProvider

        invalid_path = tmp_path / "invalid.json"
        with open(invalid_path, "w") as f:
            json.dump({"schedule": {"teams": [], "matchdays": []}}, f)

        provider = RepoFixtureProvider(fixtures_path=str(invalid_path))
        with pytest.raises(ValueError, match="Expected 36 teams"):
            provider.load()


class TestBSDFixtureProvider:
    """Tests for BSDFixtureProvider — BSD fetch, future-date filtering, caching."""

    def test_fetches_and_parses_upcoming_events(
        self, monkeypatch, bsd_response_data, sample_36_teams_data, tmp_path,
    ):
        """BSD response with upcoming events returns valid FixtureSchedule."""
        from competitions.ucl.src.provider import BSDFixtureProvider

        def mock_fetch(api_key, api_url, league_id, timeout=10):
            return bsd_response_data

        monkeypatch.setattr(
            "competitions.ucl.src.provider.fetch_raw_matches",
            mock_fetch,
        )

        # Monkeypatch validate() to no-op: BSD snapshot only has 4 events (1 matchday),
        # which won't pass the full 36-team/8-matchday UCL validation. The parse pipeline
        # is tested here; validation is tested separately in TestFixtureScheduleValidation.
        monkeypatch.setattr(
            "competitions.ucl.src.provider.FixtureSchedule.validate",
            lambda self: None,
        )

        # Provide aliases mapping BSD API team names to canonical names
        bsd_aliases = {
            "Man City": ["Manchester City"],
            "Bayern": ["Bayern Munich"],
            "PSG": ["Paris Saint-Germain"],
            "Dortmund": ["Borussia Dortmund"],
            "Inter": ["Inter Milan"],
        }

        provider = BSDFixtureProvider(
            api_key="test_key",
            aliases=bsd_aliases,
            cache_dir=str(tmp_path),
            teams_data=sample_36_teams_data,
        )
        schedule = provider.load()
        assert isinstance(schedule, FixtureSchedule)
        assert len(schedule.teams) == 36
        assert len(schedule.matchdays) > 0

    def test_empty_response_raises(self, monkeypatch, sample_36_teams_data, tmp_path):
        """BSD returning empty list should raise FixtureProviderError."""
        from competitions.ucl.src.provider import BSDFixtureProvider, FixtureProviderError

        monkeypatch.setattr(
            "competitions.ucl.src.provider.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: [],
        )

        provider = BSDFixtureProvider(
            api_key="test_key",
            aliases={},
            cache_dir=str(tmp_path),
            teams_data=sample_36_teams_data,
        )
        with pytest.raises(FixtureProviderError, match="0 events"):
            provider.load()

    def test_only_finished_events_raises(
        self, monkeypatch, sample_36_teams_data, tmp_path,
    ):
        """BSD returning only finished events should raise FixtureProviderError (no future dates)."""
        from competitions.ucl.src.provider import BSDFixtureProvider, FixtureProviderError

        # Filter bsd_response_data to only finished events
        finished_only = [
            e for e in [
                {"id": 20001, "status": "finished", "home_team": "Man City",
                 "away_team": "Bayern", "event_date": "2025-06-01T19:00:00+00:00",
                 "league": {"id": 7}},
                {"id": 20002, "status": "finished", "home_team": "Real Madrid",
                 "away_team": "PSG", "event_date": "2025-06-02T19:00:00+00:00",
                 "league": {"id": 7}},
            ]
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.provider.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: finished_only,
        )

        provider = BSDFixtureProvider(
            api_key="test_key",
            aliases={},
            cache_dir=str(tmp_path),
            teams_data=sample_36_teams_data,
        )
        with pytest.raises(FixtureProviderError, match="0 with future dates"):
            provider.load()

    def test_cache_hit_skips_fetch(
        self, monkeypatch, sample_36_teams_data, sample_cached_fixtures,
    ):
        """Valid cache should return schedule without calling fetch_raw_matches."""
        from competitions.ucl.src.provider import BSDFixtureProvider

        # Monkeypatch validate: cached data comes from asdict(full_schedule)
        # and will re-validate after load. This is the correct validation gate
        # behaviour — but we test the cache-hit path independently here.
        monkeypatch.setattr(
            "competitions.ucl.src.provider.FixtureSchedule.validate",
            lambda self: None,
        )

        call_count = 0

        def mock_fetch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return []

        monkeypatch.setattr(
            "competitions.ucl.src.provider.fetch_raw_matches",
            mock_fetch,
        )

        provider = BSDFixtureProvider(
            api_key="test_key",
            aliases={},
            cache_dir=str(sample_cached_fixtures),
            teams_data=sample_36_teams_data,
        )
        schedule = provider.load()
        assert isinstance(schedule, FixtureSchedule)
        assert call_count == 0, "fetch_raw_matches was called despite valid cache"
