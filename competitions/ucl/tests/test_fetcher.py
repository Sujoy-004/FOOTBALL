"""Tests for UCL BSD fetcher."""

import pytest
from competitions.ucl.src.fetcher import fetch_ucl_matches, build_ucl_url, UCL_LEAGUE_ID


class TestBuildUclUrl:
    """Tests for build_ucl_url()."""

    def test_returns_string_with_league_id(self):
        """build_ucl_url() must contain league_id=7 for UCL."""
        url = build_ucl_url()
        assert isinstance(url, str)
        assert "league_id=7" in url
        assert url.startswith("https://sports.bzzoiro.com/api/events/")


class TestFetchUclMatches:
    """Tests for fetch_ucl_matches()."""

    # ── Minimal test data ────────────────────────────────────────────────

    _MINIMAL_TEAMS = [
        {"name": "Man City", "pot": 1},
        {"name": "Bayern", "pot": 1},
        {"name": "Slovan Bratislava", "pot": 4},
        {"name": "PSG", "pot": 1},
    ]

    _MINIMAL_FIXTURES = {
        "teams": _MINIMAL_TEAMS,
        "matchdays": [
            [
                {
                    "match_id": "MD01_01",
                    "team_a": "Man City",
                    "team_b": "Bayern",
                    "home_pot": 1,
                    "away_pot": 1,
                },
                {
                    "match_id": "MD01_02",
                    "team_a": "Slovan Bratislava",
                    "team_b": "PSG",
                    "home_pot": 4,
                    "away_pot": 1,
                },
            ]
        ],
    }

    _MINIMAL_ALIASES = {
        "Man City": ["Man City"],
        "Bayern": ["Bayern"],
        "Slovan Bratislava": ["Slovan Bratislava"],
        "PSG": ["Paris SG"],
    }

    @staticmethod
    def _make_raw_event(
        home_team: str,
        away_team: str,
        home_score: int = 1,
        away_score: int = 0,
        status: str = "finished",
        event_id: int = 10001,
        odds_home=None,
        odds_draw=None,
        odds_away=None,
    ) -> dict:
        """Build a minimal BSD event dict matching fetch_raw_matches output."""
        event: dict = {
            "id": event_id,
            "status": status,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "event_date": "2026-06-15T20:00:00Z",
            "league": {"id": 7},
        }
        if odds_home is not None:
            event["odds_home"] = odds_home
        if odds_draw is not None:
            event["odds_draw"] = odds_draw
        if odds_away is not None:
            event["odds_away"] = odds_away
        return event

    # ── Tests ────────────────────────────────────────────────────────────

    def test_empty_events_return_empty_list(self, monkeypatch):
        """No BSD events should produce an empty result list."""
        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: [],
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert result == []

    def test_skips_unfinished_events(self, monkeypatch):
        """Events with status != 'finished' must be filtered out."""
        unfinished = [
            self._make_raw_event("Man City", "Bayern", status="scheduled"),
            self._make_raw_event("Man City", "Bayern", status="live"),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: unfinished,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert result == []

    def test_normalizes_matching_teams(self, monkeypatch):
        """BSD team names should resolve through alias lookup and fixture matching."""
        events = [
            self._make_raw_event("Man City", "Bayern", home_score=2, away_score=1),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        entry = result[0]
        assert entry["team_a"] == "Man City"
        assert entry["team_b"] == "Bayern"
        assert entry["match_id"] == "MD01_01"
        assert entry["home_score"] == 2
        assert entry["away_score"] == 1

    def test_normalizes_psg_through_alias(self, monkeypatch):
        """BSD returns 'Paris SG' — alias lookup should resolve to canonical 'PSG'."""
        events = [
            self._make_raw_event("Slovan Bratislava", "Paris SG", home_score=0, away_score=3),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        entry = result[0]
        # Though BSD says "Paris SG", canonical should be "PSG"
        assert entry["team_b"] == "PSG"
        assert entry["team_a"] == "Slovan Bratislava"
        assert entry["match_id"] == "MD01_02"

    def test_extracts_home_win(self, monkeypatch):
        """Home team winning should set winner to home team and is_draw=False."""
        events = [
            self._make_raw_event("Man City", "Bayern", home_score=3, away_score=0),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        entry = result[0]
        assert entry["winner"] == "Man City"
        assert entry["is_draw"] is False

    def test_extracts_away_win(self, monkeypatch):
        """Away team winning should set winner to away team and is_draw=False."""
        events = [
            self._make_raw_event("Man City", "Bayern", home_score=0, away_score=2),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        entry = result[0]
        assert entry["winner"] == "Bayern"
        assert entry["is_draw"] is False

    def test_extracts_draw(self, monkeypatch):
        """Equal scores should set winner=None and is_draw=True."""
        events = [
            self._make_raw_event("Man City", "Bayern", home_score=1, away_score=1),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        entry = result[0]
        assert entry["winner"] is None
        assert entry["is_draw"] is True

    def test_skips_unmatchable_teams(self, monkeypatch):
        """Teams not found in aliases should be skipped with a warning, not crash."""
        events = [
            self._make_raw_event("Mystery FC", "Unknown United", home_score=1, away_score=0),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        # Should not raise — unmatchable teams are logged and skipped
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert result == []

    def test_skips_unmatched_fixtures(self, monkeypatch):
        """Valid team names with no fixture match should be skipped with a warning."""
        # Valid teams but not in our minimal fixture schedule
        events = [
            self._make_raw_event("Liverpool", "Arsenal", home_score=2, away_score=0),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        # Liverpool and Arsenal are not in the fixtures — should be skipped
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert result == []

    def test_builds_fixture_lookup_bidirectionally(self, monkeypatch):
        """Fixture lookup should work with BSD events where home/away are reversed."""
        # BSD event has Bayern as home, Man City as away (reversed from fixture)
        events = [
            self._make_raw_event("Bayern", "Man City", home_score=2, away_score=2),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        entry = result[0]
        assert entry["match_id"] == "MD01_01"
        assert entry["team_a"] == "Bayern"
        assert entry["team_b"] == "Man City"
        # Draw: winner=None, is_draw=True
        assert entry["winner"] is None
        assert entry["is_draw"] is True

    def test_extracts_odds_with_vig_removal(self, monkeypatch):
        """BSD events with odds should have vig-removed fair probabilities."""
        events = [
            self._make_raw_event(
                "Man City", "Bayern", home_score=2, away_score=0,
                odds_home=2.0, odds_draw=3.5, odds_away=4.0,
            ),
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        entry = result[0]
        assert "odds" in entry
        odds = entry["odds"]
        assert "home" in odds
        assert "draw" in odds
        assert "away" in odds
        # Fair probabilities should sum to approximately 1.0
        total = odds["home"] + odds["draw"] + odds["away"]
        assert abs(total - 1.0) < 0.001, f"Probabilities sum to {total}, expected ~1.0"
        # Home odds 2.0 -> vig-removed home prob should be ~0.54
        # (1/2.0) / (1/2.0 + 1/3.5 + 1/4.0) ≈ 0.50 / 0.9643 ≈ 0.5185
        assert odds["home"] > odds["draw"]  # Lower odds = higher prob for fav
        assert odds["home"] > odds["away"]

    def test_skips_events_without_odds(self, monkeypatch):
        """BSD events without odds fields should not have an 'odds' key."""
        events = [
            self._make_raw_event("Man City", "Bayern", home_score=1, away_score=0),
            # No odds_home/odds_draw/odds_away set
        ]

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_raw_matches",
            lambda api_key, api_url, league_id, timeout=10: events,
        )
        result = fetch_ucl_matches("test_key", self._MINIMAL_ALIASES, self._MINIMAL_FIXTURES)
        assert len(result) == 1
        assert "odds" not in result[0]
