"""Tests for odds.py — vig removal, response parsing, cache pipeline.

All file I/O tests use tmp_path to avoid modifying real data files.
"""
from datetime import datetime, timezone

import pytest

from src.predictors.odds import (
    fetch_and_cache_odds,
    parse_odds_response,
    remove_vig,
)
from src.state import load_signal_cache, save_signal_cache


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


# ─── Cache Schema Tests ───────────────────────────────────────────────


class TestOddsCache:
    """fetch_and_cache_odds: cache dict schema validation."""

    def test_cache_produces_valid_schema(self):
        """fetch_and_cache_odds returns dict with fetched_at, expires_at, matches keys."""
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
        cache = fetch_and_cache_odds("test_key", events, alias_lookup, groups)
        assert "fetched_at" in cache
        assert "expires_at" in cache
        assert "matches" in cache

    def test_cache_expires_at_is_future(self):
        """expires_at is a valid ISO datetime in the future (12h from fetched_at)."""
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
        cache = fetch_and_cache_odds("test_key", events, alias_lookup, groups)
        fetched = datetime.fromisoformat(cache["fetched_at"])
        expires = datetime.fromisoformat(cache["expires_at"])
        assert expires > fetched
        # Should be ~12 hours in the future
        diff = (expires - fetched).total_seconds()
        assert 11 * 3600 < diff < 13 * 3600

    def test_cache_matches_contains_entries(self):
        """matches is a dict with entries for each processed event."""
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
        cache = fetch_and_cache_odds("test_key", events, alias_lookup, groups)
        assert isinstance(cache["matches"], dict)
        assert "GS_B_01" in cache["matches"]


# ─── Cache Persistence Tests ──────────────────────────────────────────


class TestOddsPersistence:
    """Cache save/load roundtrip using tmp_path for isolated file I/O."""

    def test_save_and_load_cache(self, tmp_path):
        """save via save_signal_cache, load via load_signal_cache → identical content."""
        cache = {
            "fetched_at": "2026-06-16T12:00:00+00:00",
            "expires_at": "2026-06-17T00:00:00+00:00",
            "matches": {"GS_B_01": {"probability": 0.54, "available": True}},
        }
        save_signal_cache(cache, "odds_cache.json", data_dir=tmp_path)
        loaded = load_signal_cache("odds_cache.json", data_dir=tmp_path)
        assert loaded == cache

    def test_cache_file_created(self, tmp_path):
        """After save, cache file exists on disk."""
        cache = {
            "fetched_at": "2026-06-16T12:00:00+00:00",
            "expires_at": "2026-06-17T00:00:00+00:00",
            "matches": {},
        }
        save_signal_cache(cache, "odds_cache.json", data_dir=tmp_path)
        assert (tmp_path / "odds_cache.json").exists()

    def test_cache_round_trip(self, tmp_path):
        """Full save→load→verify values preserved."""
        original = {
            "fetched_at": "2026-06-16T12:00:00+00:00",
            "expires_at": "2026-06-17T00:00:00+00:00",
            "matches": {
                "GS_B_01": {
                    "probability": 0.54,
                    "timestamp": "2026-06-16T12:00:00+00:00",
                    "available": True,
                },
            },
        }
        save_signal_cache(original, "odds_cache.json", data_dir=tmp_path)
        loaded = load_signal_cache("odds_cache.json", data_dir=tmp_path)
        assert loaded["matches"]["GS_B_01"]["probability"] == 0.54
        assert loaded["matches"]["GS_B_01"]["available"] is True


# ─── Fetch and Cache Integration Tests ───────────────────────────────


class TestFetchAndCacheOdds:
    """Full fetch_and_cache_odds pipeline with various event scenarios."""

    def _make_event_fixtures(self):
        """Create reusable test fixtures."""
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
        return alias_lookup, groups

    def test_fetch_and_cache_with_valid_events(self):
        """Minimal BSD event dicts → matches contain probability values."""
        alias_lookup, groups = self._make_event_fixtures()
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
        cache = fetch_and_cache_odds("test_key", events, alias_lookup, groups)
        match = cache["matches"]["GS_B_01"]
        assert "probability" in match
        assert isinstance(match["probability"], float)
        assert 0 < match["probability"] < 1
        assert match["available"] is True

    def test_fetch_and_cache_all_missing_odds(self):
        """Events without odds → all matches have available=False."""
        alias_lookup, groups = self._make_event_fixtures()
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
        cache = fetch_and_cache_odds("test_key", events, alias_lookup, groups)
        match = cache["matches"]["GS_B_01"]
        assert match["available"] is False
        assert match["reason"] == "odds_not_available"
        assert match["probability"] is None

    def test_fetch_and_cache_mixed(self):
        """Some with odds, some without → correct available flags."""
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria",
                        "brazil": "Brazil", "japan": "Japan"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [
                        {"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"},
                    ],
                },
                "C": {
                    "teams": ["Brazil", "Japan"],
                    "matches": [
                        {"match_id": "GS_C_01", "team_a": "Brazil", "team_b": "Japan"},
                    ],
                },
            }
        }
        events = [
            {
                "id": 100,
                "home_team": "Argentina",
                "away_team": "Algeria",
                "odds_home": 1.45,
                "odds_draw": 4.20,
                "odds_away": 7.50,
                "status": "upcoming",
                "event_date": "2026-06-17T05:00:00+00:00",
                "round_number": 1,
                "group_name": "Group B",
            },
            {
                "id": 200,
                "home_team": "Brazil",
                "away_team": "Japan",
                "odds_home": None,
                "odds_draw": None,
                "odds_away": None,
                "status": "upcoming",
                "event_date": "2026-06-18T05:00:00+00:00",
                "round_number": 1,
                "group_name": "Group C",
            },
        ]
        cache = fetch_and_cache_odds("test_key", events, alias_lookup, groups)
        # GS_B_01 has valid odds
        assert cache["matches"]["GS_B_01"]["available"] is True
        assert cache["matches"]["GS_B_01"]["probability"] > 0
        # GS_C_01 has missing odds
        assert cache["matches"]["GS_C_01"]["available"] is False
        assert cache["matches"]["GS_C_01"]["reason"] == "odds_not_available"

    def test_fetch_upserts_market_odds_ledger(self):
        """fetch_and_cache_odds calls ledger_upsert for each parsed event."""
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
        import src.state
        original = src.state.ledger_upsert
        calls = []
        def fake_ledger_upsert(mid, signal, entry):
            calls.append((mid, signal, entry.get("probability")))
        src.state.ledger_upsert = fake_ledger_upsert
        try:
            cache = fetch_and_cache_odds("test_key", events, alias_lookup, groups)
        finally:
            src.state.ledger_upsert = original

        assert len(calls) == 1
        mid, signal, prob = calls[0]
        assert mid == "GS_B_01"
        assert signal == "market_odds"
        assert 0 < prob < 1
