"""Tests for odds.py — vig removal, response parsing, cache pipeline.

All file I/O tests use tmp_path to avoid modifying real data files.
"""
from datetime import datetime, timezone

import pytest

from src.predictors.odds import remove_vig, parse_odds_response


# ─── Vig Removal Tests ─────────────────────────────────────────────────


class TestVigRemoval:
    """remove_vig: convert decimal odds to normalized probabilities."""

    def test_remove_vig_basic(self):
        """[1.85, 3.40, 4.50] → normalized probs summing to 1.0, home ~0.511."""
        result = remove_vig(1.85, 3.40, 4.50)
        assert abs(result["home"] - 0.511) < 0.01
        assert abs(sum(result.values()) - 1.0) < 1e-10

    def test_remove_vig_all_three(self):
        """All three probabilities sum to exactly 1.0 ± 1e-10 for typical odds."""
        result = remove_vig(2.0, 3.2, 3.8)
        assert abs(sum(result.values()) - 1.0) < 1e-10

    def test_remove_vig_even_odds(self):
        """[2.0, 3.0, 2.0] → home=0.375, draw=0.25, away=0.375."""
        result = remove_vig(2.0, 3.0, 2.0)
        assert result["home"] == 0.375
        assert result["draw"] == 0.25
        assert result["away"] == 0.375
        assert abs(sum(result.values()) - 1.0) < 1e-10

    def test_remove_vig_high_vig(self):
        """High vig [1.10, 8.0, 15.0] → sum of all three == 1.0."""
        result = remove_vig(1.10, 8.0, 15.0)
        assert abs(sum(result.values()) - 1.0) < 1e-10


# ─── Missing/Null Odds Tests ───────────────────────────────────────────


class TestMissingOdds:
    """parse_odds_response: handle missing, null, and zero odds."""

    def test_parse_odds_response_valid(self):
        """Event with valid odds → match_id mapped, probability, available=True."""
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [
                        {"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"},
                    ],
                }
            }
        }
        events = [
            {
                "id": 209476,
                "home_team": "Argentina",
                "away_team": "Algeria",
                "odds_home": 1.45,
                "odds_draw": 4.20,
                "odds_away": 7.50,
                "status": "upcoming",
                "event_date": "2026-06-17T05:00:00+00:00",
                "round_number": 1,
                "group_name": "Group B",
            }
        ]
        result = parse_odds_response(events, alias_lookup, groups)
        assert "GS_B_01" in result
        entry = result["GS_B_01"]
        assert entry["available"] is True
        assert "probability" in entry
        assert entry["probability"] > 0

    def test_parse_odds_response_null_odds(self):
        """Event with None odds → available=False, reason='odds_not_available'."""
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [
                        {"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"},
                    ],
                }
            }
        }
        events = [
            {
                "id": 209476,
                "home_team": "Argentina",
                "away_team": "Algeria",
                "odds_home": None,
                "odds_draw": None,
                "odds_away": None,
                "status": "upcoming",
                "event_date": "2026-06-17T05:00:00+00:00",
                "round_number": 1,
                "group_name": "Group B",
            }
        ]
        result = parse_odds_response(events, alias_lookup, groups)
        assert "GS_B_01" in result
        entry = result["GS_B_01"]
        assert entry["available"] is False
        assert entry["reason"] == "odds_not_available"

    def test_parse_odds_response_zero_odds(self):
        """Event with 0 odds → available=False."""
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [
                        {"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"},
                    ],
                }
            }
        }
        events = [
            {
                "id": 209476,
                "home_team": "Argentina",
                "away_team": "Algeria",
                "odds_home": 1.45,
                "odds_draw": 0,
                "odds_away": 7.50,
                "status": "upcoming",
                "event_date": "2026-06-17T05:00:00+00:00",
                "round_number": 1,
                "group_name": "Group B",
            }
        ]
        result = parse_odds_response(events, alias_lookup, groups)
        assert "GS_B_01" in result
        entry = result["GS_B_01"]
        assert entry["available"] is False

    def test_parse_odds_response_missing_field(self):
        """Event missing odds keys entirely → available=False."""
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [
                        {"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"},
                    ],
                }
            }
        }
        events = [
            {
                "id": 209476,
                "home_team": "Argentina",
                "away_team": "Algeria",
                "status": "upcoming",
                "event_date": "2026-06-17T05:00:00+00:00",
                "round_number": 1,
                "group_name": "Group B",
            }
        ]
        result = parse_odds_response(events, alias_lookup, groups)
        assert "GS_B_01" in result
        entry = result["GS_B_01"]
        assert entry["available"] is False
        assert entry["reason"] == "odds_not_available"
