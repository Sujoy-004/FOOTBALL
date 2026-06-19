"""Tests for the enrichment module (extract_stats, extract_context)."""

import pytest

from src.enrichment import extract_stats, extract_context


FINISHED_EVENT = {
    "id": 8287,
    "status": "finished",
    "home_team": "Mexico",
    "away_team": "South Africa",
    "home_score": 2,
    "away_score": 0,
    "event_date": "2026-06-11T23:00:00Z",
    "live_stats": {
        "home": {
            "yellow_cards": 2,
            "red_cards": 1,
            "shots_on_target": 6,
            "ball_possession": 58,
        },
        "away": {
            "yellow_cards": 1,
            "red_cards": 0,
            "shots_on_target": 3,
            "ball_possession": 42,
        },
    },
    "venue": {"name": "Estadio Azteca", "city": "Mexico City"},
    "referee": {"name": "Wilton Pereira Sampaio"},
}

NO_STATS_EVENT = {**FINISHED_EVENT, "live_stats": None}

NO_CONTEXT_EVENT = {**FINISHED_EVENT, "venue": None, "referee": None}

PARTIAL_STATS_EVENT = {
    **FINISHED_EVENT,
    "live_stats": {
        "home": {"ball_possession": 60},
        "away": {"ball_possession": 40},
    },
}

ONLY_VENUE_EVENT = {**FINISHED_EVENT, "referee": None}

ONLY_REFEREE_EVENT = {**FINISHED_EVENT, "venue": None}

UPCOMING_EVENT = {
    "id": 8316,
    "status": "notstarted",
    "home_team": "USA",
    "away_team": "Australia",
    "event_date": "2026-06-23T23:00:00Z",
    "live_stats": None,
    "venue": {"name": "Lumen Field", "city": "Seattle"},
    "referee": {"name": "Felix Zwayer"},
}


class TestExtractStats:
    def test_all_fields(self):
        stats = extract_stats(FINISHED_EVENT)
        assert stats is not None
        assert stats["yellow_cards_home"] == 2
        assert stats["yellow_cards_away"] == 1
        assert stats["red_cards_home"] == 1
        assert stats["red_cards_away"] == 0
        assert stats["shots_on_target_home"] == 6
        assert stats["shots_on_target_away"] == 3
        assert stats["possession_home"] == 58
        assert stats["possession_away"] == 42

    def test_none_live_stats(self):
        assert extract_stats(NO_STATS_EVENT) is None

    def test_partial_stats(self):
        stats = extract_stats(PARTIAL_STATS_EVENT)
        assert stats is not None
        assert "possession_home" in stats
        assert "possession_away" in stats
        assert "yellow_cards_home" not in stats
        assert "shots_on_target_away" not in stats

    def test_possession_type(self):
        stats = extract_stats(FINISHED_EVENT)
        assert isinstance(stats["possession_home"], int)
        assert isinstance(stats["possession_away"], int)

    def test_upcoming_match(self):
        assert extract_stats(UPCOMING_EVENT) is None


class TestExtractContext:
    def test_both_fields(self):
        ctx = extract_context(FINISHED_EVENT)
        assert ctx is not None
        assert ctx["venue"] == "Estadio Azteca"
        assert ctx["referee"] == "Wilton Pereira Sampaio"

    def test_no_context(self):
        assert extract_context(NO_CONTEXT_EVENT) is None

    def test_only_venue(self):
        ctx = extract_context(ONLY_VENUE_EVENT)
        assert ctx is not None
        assert "venue" in ctx
        assert "referee" not in ctx

    def test_only_referee(self):
        ctx = extract_context(ONLY_REFEREE_EVENT)
        assert ctx is not None
        assert "referee" in ctx
        assert "venue" not in ctx

    def test_upcoming_match(self):
        ctx = extract_context(UPCOMING_EVENT)
        assert ctx is not None
        assert ctx["venue"] == "Lumen Field"
        assert ctx["referee"] == "Felix Zwayer"
