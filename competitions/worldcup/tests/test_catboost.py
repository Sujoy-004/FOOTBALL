"""Tests for catboost.py — prediction parsing, missing predictions, cache TTL.

All file I/O tests use tmp_path to avoid modifying real data files.
"""
from datetime import datetime, timezone

import pytest

from src.predictors.catboost import (
    fetch_and_cache_catboost,
    parse_catboost_response,
)
from src.state import load_signal_cache, save_signal_cache


# ─── Prediction Parsing Tests ───────────────────────────────────────


class TestParsePredictions:
    """parse_catboost_response: parse BSD predictions into canonical format."""

    def _make_alias_lookup(self):
        return {
            "argentina": "Argentina",
            "algeria": "Algeria",
            "brazil": "Brazil",
            "japan": "Japan",
        }

    def _make_groups(self):
        return {
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

    def _make_valid_prediction(self, overrides: dict | None = None) -> dict:
        pred = {
            "event_id": 12345,
            "home_team": "Argentina",
            "away_team": "Algeria",
            "event_date": "2026-06-17T05:00:00+00:00",
            "home_probability": 64.0,
            "draw_probability": 20.0,
            "away_probability": 17.0,
            "confidence": 0.88,
            "model_version": "catboost-v5.0",
            "updated_at": "2026-06-16T12:00:00+00:00",
        }
        if overrides:
            pred.update(overrides)
        return pred

    def test_parse_valid_prediction(self):
        """BSD prediction dict → entry with probability=0.64 (64% → /100)."""
        result = parse_catboost_response(
            [self._make_valid_prediction()],
            self._make_alias_lookup(),
            self._make_groups(),
            [],
        )
        assert "GS_B_01" in result
        entry = result["GS_B_01"]
        assert entry["probability"] == 0.64
        assert entry["available"] is True

    def test_parse_all_fields(self):
        """confidence, model_version, timestamp stored in cache entry."""
        result = parse_catboost_response(
            [self._make_valid_prediction()],
            self._make_alias_lookup(),
            self._make_groups(),
            [],
        )
        entry = result["GS_B_01"]
        assert entry["confidence"] == 0.88
        assert entry["model_version"] == "catboost-v5.0"
        assert "timestamp" in entry
        assert entry["timestamp"] == "2026-06-16T12:00:00+00:00"

    def test_parse_null_predictions(self):
        """All probability fields are None → available=False, reason='predictions_not_available'."""
        pred = self._make_valid_prediction({
            "home_probability": None, "draw_probability": None, "away_probability": None,
        })
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        assert "GS_B_01" in result
        entry = result["GS_B_01"]
        assert entry["available"] is False
        assert entry["reason"] == "predictions_not_available"

    def test_parse_missing_event_id(self):
        """No event_id → skip gracefully (not in matches)."""
        pred = self._make_valid_prediction({"event_id": None})
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        assert len(result) == 0

    def test_parse_negative_probability(self):
        """Negative probability → available=False, reason='invalid_probability'."""
        pred = self._make_valid_prediction({
            "home_probability": -50.0,
        })
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        assert "GS_B_01" in result
        entry = result["GS_B_01"]
        assert entry["available"] is False
        assert entry["reason"] == "invalid_probability"

    def test_parse_probabilities_not_sum_one(self):
        """Non-normalized probs stored as-is (normalization happens in Phase 14)."""
        pred = self._make_valid_prediction({
            "home_probability": 80.0,
            "draw_probability": 30.0,
            "away_probability": 20.0,
        })
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        entry = result["GS_B_01"]
        assert entry["probability"] == 0.8
        assert entry["available"] is True

    def test_parse_flat_percentage_format(self):
        """Percentage values (64.0) are converted to 0-1 floats (0.64)."""
        pred = self._make_valid_prediction()
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        entry = result["GS_B_01"]
        assert entry["probability"] == 0.64
        assert abs(entry["probability"] * 100.0 - 64.0) < 0.001
        assert entry["available"] is True

    def test_parse_different_field_names(self):
        """Alternative field names via fallback chain (home_win → probability_home)."""
        alias = {"brazil": "Brazil", "japan": "Japan"}
        groups = {
            "groups": {
                "C": {
                    "teams": ["Brazil", "Japan"],
                    "matches": [{"match_id": "GS_C_01", "team_a": "Brazil", "team_b": "Japan"}],
                },
            },
        }
        # Fallback 1: home_win, draw, away_win (flat top-level fields)
        pred1 = {
            "event_id": 200,
            "home_team": "Brazil",
            "away_team": "Japan",
            "event_date": "2026-06-18T05:00:00+00:00",
            "home_win": 55.0,
            "draw": 25.0,
            "away_win": 20.0,
            "confidence": 0.75,
            "model_version": "catboost-v5.0",
            "updated_at": "2026-06-17T12:00:00+00:00",
        }
        result = parse_catboost_response([pred1], alias, groups, [])
        entry = result["GS_C_01"]
        assert entry["probability"] == 0.55
        assert entry["confidence"] == 0.75

        # Fallback 2: probability_home, probability_draw, probability_away (flat)
        pred2 = {
            "event_id": 201,
            "home_team": "Brazil",
            "away_team": "Japan",
            "event_date": "2026-06-18T05:00:00+00:00",
            "probability_home": 60.0,
            "probability_draw": 22.0,
            "probability_away": 18.0,
            "confidence": 0.80,
            "model_version": "catboost-v5.0",
            "updated_at": "2026-06-17T12:00:00+00:00",
        }
        result = parse_catboost_response([pred2], alias, groups, [])
        entry = result["GS_C_01"]
        assert entry["probability"] == 0.60
        assert entry["confidence"] == 0.80


# ─── Missing Predictions Tests ──────────────────────────────────────


class TestMissingPredictions:
    """parse_catboost_response: handle mixed availability."""

    def test_all_missing(self):
        """All predictions null → all entries available=False."""
        alias_lookup = {
            "argentina": "Argentina", "algeria": "Algeria",
            "brazil": "Brazil", "japan": "Japan",
        }
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [{"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"}],
                },
                "C": {
                    "teams": ["Brazil", "Japan"],
                    "matches": [{"match_id": "GS_C_01", "team_a": "Brazil", "team_b": "Japan"}],
                },
            },
        }
        predictions = [
            {"event_id": 100, "home_team": "Argentina", "away_team": "Algeria",
             "home_probability": None, "draw_probability": None, "away_probability": None,
             "updated_at": "2026-06-16T12:00:00+00:00"},
            {"event_id": 200, "home_team": "Brazil", "away_team": "Japan",
             "home_probability": None, "draw_probability": None, "away_probability": None,
             "updated_at": "2026-06-16T12:00:00+00:00"},
        ]
        result = parse_catboost_response(predictions, alias_lookup, groups, [])
        assert result["GS_B_01"]["available"] is False
        assert result["GS_C_01"]["available"] is False
        assert len(result) == 2

    def test_partial_missing(self):
        """Some have predictions, some don't → mixed available flags."""
        alias_lookup = {
            "argentina": "Argentina", "algeria": "Algeria",
            "brazil": "Brazil", "japan": "Japan",
        }
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [{"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"}],
                },
                "C": {
                    "teams": ["Brazil", "Japan"],
                    "matches": [{"match_id": "GS_C_01", "team_a": "Brazil", "team_b": "Japan"}],
                },
            },
        }
        predictions = [
            {
                "event_id": 100, "home_team": "Argentina", "away_team": "Algeria",
                "event_date": "2026-06-17T05:00:00+00:00",
                "home_probability": 64.0, "draw_probability": 20.0,
                "away_probability": 17.0, "confidence": 0.88,
                "model_version": "catboost-v5.0",
                "updated_at": "2026-06-16T12:00:00+00:00",
            },
            {
                "event_id": 200, "home_team": "Brazil", "away_team": "Japan",
                "home_probability": None, "draw_probability": None, "away_probability": None,
                "updated_at": "2026-06-16T12:00:00+00:00",
            },
        ]
        result = parse_catboost_response(predictions, alias_lookup, groups, [])
        assert result["GS_B_01"]["available"] is True
        assert result["GS_B_01"]["probability"] == 0.64
        assert result["GS_C_01"]["available"] is False
        assert result["GS_C_01"]["reason"] == "predictions_not_available"
        assert len(result) == 2


# ─── Cache Schema Tests ─────────────────────────────────────────────


class TestCatboostCache:
    """fetch_and_cache_catboost: cache dict schema validation."""

    def _mock_empty_response(self, monkeypatch):
        """Monkeypatch requests.get to return empty results list."""
        def mock_get(*args, **kwargs):
            class MockResponse:
                status_code = 200
                def json(self):
                    return {"count": 0, "results": []}
                def raise_for_status(self):
                    pass
            return MockResponse()
        monkeypatch.setattr("requests.get", mock_get)

    def test_cache_schema_valid(self, monkeypatch):
        """fetch_and_cache_catboost returns dict with fetched_at, expires_at, matches."""
        self._mock_empty_response(monkeypatch)
        cache = fetch_and_cache_catboost(
            "test_key", {}, {"groups": {}}, [], cache_ttl_hours=24,
        )
        assert "fetched_at" in cache
        assert "expires_at" in cache
        assert "matches" in cache

    def test_cache_produces_24h_ttl(self, monkeypatch):
        """expires_at is ~24h from fetched_at."""
        self._mock_empty_response(monkeypatch)
        cache = fetch_and_cache_catboost(
            "test_key", {}, {"groups": {}}, [], cache_ttl_hours=24,
        )
        fetched = datetime.fromisoformat(cache["fetched_at"])
        expires = datetime.fromisoformat(cache["expires_at"])
        diff = (expires - fetched).total_seconds()
        assert 23 * 3600 < diff < 25 * 3600


# ─── Fetch Integration Tests ─────────────────────────────────────────


class TestCatboostFetch:
    """fetch_and_cache_catboost: HTTP fetch and error handling."""

    def _make_mock_response(self, status_code: int = 200, json_data: dict | None = None):
        """Create a mock requests.Response-like object."""
        if json_data is None:
            json_data = {"count": 0, "results": []}

        class MockResponse:
            def __init__(self):
                self.status_code = status_code
                self._json = json_data

            def json(self):
                return self._json

            def raise_for_status(self):
                if self.status_code >= 400:
                    import requests as req
                    raise req.exceptions.HTTPError(
                        f"HTTP {self.status_code}", response=self
                    )

        return MockResponse()

    def test_fetch_returns_cache_dict(self, monkeypatch):
        """fetch_and_cache_catboost returns dict with fetched_at, expires_at, matches."""
        mock_resp = self._make_mock_response()
        monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)

        cache = fetch_and_cache_catboost(
            "test_key", {}, {"groups": {}}, [], cache_ttl_hours=24,
        )
        assert "fetched_at" in cache
        assert "expires_at" in cache
        assert "matches" in cache
        assert isinstance(cache["matches"], dict)

    def test_fetch_handles_api_error(self, monkeypatch):
        """When requests.get raises exception, returns empty matches dict gracefully."""
        def mock_get_error(*args, **kwargs):
            import requests as req
            raise req.exceptions.ConnectionError("Connection refused")
        monkeypatch.setattr("requests.get", mock_get_error)

        cache = fetch_and_cache_catboost(
            "test_key", {}, {"groups": {}}, [], cache_ttl_hours=24,
        )
        assert "fetched_at" in cache
        assert "expires_at" in cache
        assert cache["matches"] == {}

    def test_fetch_uses_token_header(self, monkeypatch):
        """Requests use Authorization: Token header."""
        captured_kwargs = {}

        def mock_get(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return self._make_mock_response()

        monkeypatch.setattr("requests.get", mock_get)
        fetch_and_cache_catboost(
            "my_secret_key", {}, {"groups": {}}, [], cache_ttl_hours=24,
        )
        headers = captured_kwargs.get("headers", {})
        assert headers.get("Authorization") == "Token my_secret_key"

    def test_fetch_with_predictions(self, monkeypatch):
        """When API returns predictions, they are parsed into matches."""
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [{"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"}],
                },
            },
        }
        json_data = {
            "count": 1,
            "results": [
                {
                    "event_id": 12345,
                    "home_team": "Argentina",
                    "away_team": "Algeria",
                    "event_date": "2026-06-17T05:00:00+00:00",
                    "home_probability": 64.0,
                    "draw_probability": 20.0,
                    "away_probability": 17.0,
                    "confidence": 0.88,
                    "model_version": "catboost-v5.0",
                    "updated_at": "2026-06-16T12:00:00+00:00",
                },
            ],
        }
        mock_resp = self._make_mock_response(json_data=json_data)
        monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)

        cache = fetch_and_cache_catboost(
            "test_key", alias_lookup, groups, [], cache_ttl_hours=24,
        )
        assert "GS_B_01" in cache["matches"]
        assert cache["matches"]["GS_B_01"]["probability"] == 0.64
        assert cache["matches"]["GS_B_01"]["available"] is True

    def test_fetch_upserts_ledger(self, monkeypatch):
        """fetch_and_cache_catboost calls ledger_upsert for each parsed match."""
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [{"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"}],
                },
            },
        }
        json_data = {
            "count": 1,
            "results": [
                {
                    "event_id": 12345,
                    "home_team": "Argentina",
                    "away_team": "Algeria",
                    "event_date": "2026-06-17T05:00:00+00:00",
                    "home_probability": 64.0,
                    "draw_probability": 20.0,
                    "away_probability": 17.0,
                    "confidence": 0.88,
                    "model_version": "catboost-v5.0",
                    "updated_at": "2026-06-16T12:00:00+00:00",
                },
            ],
        }
        mock_resp = self._make_mock_response(json_data=json_data)
        monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)

        calls = []
        def fake_ledger_upsert(mid, signal, entry):
            calls.append((mid, signal, entry.get("probability")))
        monkeypatch.setattr("src.state.ledger_upsert", fake_ledger_upsert)

        fetch_and_cache_catboost(
            "test_key", alias_lookup, groups, [], cache_ttl_hours=24,
        )

        assert len(calls) == 1
        mid, signal, prob = calls[0]
        assert mid == "GS_B_01"
        assert signal == "catboost"
        assert abs(prob - 0.64) < 0.001


# ─── Edge Case Tests ─────────────────────────────────────────────────


class TestParsePredictionsEdgeCases:
    """parse_catboost_response: edge cases for team resolution."""

    def test_no_results(self):
        """Empty predictions list → empty matches dict."""
        result = parse_catboost_response([], {}, {"groups": {}}, [])
        assert result == {}

    def test_unmatchable_team(self):
        """Team not in alias lookup → entry skipped (not in matches)."""
        alias_lookup = {"argentina": "Argentina"}  # No "algeria"
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [{"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"}],
                },
            },
        }
        predictions = [
            {
                "event_id": 100,
                "home_team": "Argentina",
                "away_team": "Algeria",  # Not in alias_lookup
                "home_probability": 64.0, "draw_probability": 20.0,
                "away_probability": 17.0,
                "updated_at": "2026-06-16T12:00:00+00:00",
            },
        ]
        result = parse_catboost_response(predictions, alias_lookup, groups, [])
        assert len(result) == 0

    def test_bracket_match_resolution(self):
        """Prediction for knockout match uses _find_bracket_match path."""
        alias_lookup = {"brazil": "Brazil", "germany": "Germany"}
        bracket = [
            {"match_id": "R16_1", "team_a": "Brazil", "team_b": "Germany"},
        ]
        predictions = [
            {
                "event_id": 300,
                "home_team": "Brazil",
                "away_team": "Germany",
                "event_date": "2026-06-28T17:00:00+00:00",
                "home_probability": 55.0,
                "draw_probability": 25.0,
                "away_probability": 20.0,
                "confidence": 0.82,
                "model_version": "catboost-v5.0",
                "updated_at": "2026-06-27T12:00:00+00:00",
            },
        ]
        result = parse_catboost_response(
            predictions, alias_lookup, {"groups": {}}, bracket,
        )
        assert "R16_1" in result
        assert result["R16_1"]["probability"] == 0.55
        assert result["R16_1"]["available"] is True

    def test_group_match_resolution(self):
        """Prediction for group match resolves via group team pair matching."""
        alias_lookup = {"france": "France", "netherlands": "Netherlands"}
        groups = {
            "groups": {
                "A": {
                    "teams": ["France", "Netherlands"],
                    "matches": [{"match_id": "GS_A_01", "team_a": "France", "team_b": "Netherlands"}],
                },
            },
        }
        predictions = [
            {
                "event_id": 400,
                "home_team": "France",
                "away_team": "Netherlands",
                "event_date": "2026-06-13T21:00:00+00:00",
                "home_probability": 48.0,
                "draw_probability": 27.0,
                "away_probability": 25.0,
                "confidence": 0.80,
                "model_version": "catboost-v5.0",
                "updated_at": "2026-06-12T12:00:00+00:00",
            },
        ]
        result = parse_catboost_response(
            predictions, alias_lookup, groups, [],
        )
        assert "GS_A_01" in result
        assert result["GS_A_01"]["probability"] == 0.48
        assert result["GS_A_01"]["available"] is True

    def test_non_dict_in_list(self):
        """Non-dict items in predictions list are skipped gracefully."""
        predictions = [
            {"event_id": 100, "home_team": "Argentina", "away_team": "Algeria",
             "home_probability": None, "draw_probability": None, "away_probability": None,
             "updated_at": "2026-06-16T12:00:00+00:00"},
            "not a dict",
            42,
            None,
        ]
        alias_lookup = {"argentina": "Argentina", "algeria": "Algeria"}
        groups = {
            "groups": {
                "B": {
                    "teams": ["Argentina", "Algeria"],
                    "matches": [{"match_id": "GS_B_01", "team_a": "Argentina", "team_b": "Algeria"}],
                },
            },
        }
        # Should not raise; non-dict items are filtered, valid entry still parsed
        result = parse_catboost_response(predictions, alias_lookup, groups, [])
        assert "GS_B_01" in result
        assert result["GS_B_01"]["available"] is False


class TestLiveBsdFormat:
    """parse_catboost_response with live BSD /api/predictions/ response format.

    The live API wraps event data under a nested ``event`` dict and uses
    ``prob_home_win`` / ``prob_draw`` / ``prob_away_win`` field names.
    """

    def _make_alias_lookup(self):
        return {
            "argentina": "Argentina",
            "algeria": "Algeria",
            "brazil": "Brazil",
            "japan": "Japan",
            "germany": "Germany",
        }

    def _make_groups(self):
        return {
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
            },
        }

    def _make_live_prediction(self, overrides: dict | None = None) -> dict:
        pred = {
            "id": 1001,
            "event": {
                "id": 5001,
                "home_team": "Argentina",
                "away_team": "Algeria",
            },
            "prob_home_win": 64.0,
            "prob_draw": 20.0,
            "prob_away_win": 17.0,
            "expected_home_goals": 1.8,
            "expected_away_goals": 0.9,
            "confidence": 0.88,
            "model_version": "catboost-v5.0",
            "updated_at": "2026-06-21T12:00:00+00:00",
        }
        if overrides:
            pred.update(overrides)
        return pred

    def test_parse_live_string_team_names(self):
        """event.home_team/away_team as plain strings (real API format)."""
        result = parse_catboost_response(
            [self._make_live_prediction()],
            self._make_alias_lookup(),
            self._make_groups(),
            [],
        )
        assert "GS_B_01" in result, f"Expected GS_B_01, got keys: {list(result)}"
        entry = result["GS_B_01"]
        assert entry["probability"] == 0.64
        assert entry["available"] is True
        assert entry["confidence"] == 0.88
        assert entry["model_version"] == "catboost-v5.0"

    def test_parse_live_dict_team_names(self):
        """event.home_team/away_team as dicts (alternate API format)."""
        pred = {
            "id": 1002,
            "event": {
                "id": 5002,
                "home_team": {"name": "Argentina", "id": 1},
                "away_team": {"name": "Algeria", "id": 2},
            },
            "prob_home_win": 64.0,
            "prob_draw": 20.0,
            "prob_away_win": 17.0,
            "confidence": 0.88,
            "model_version": "catboost-v5.0",
            "updated_at": "2026-06-21T12:00:00+00:00",
        }
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        assert "GS_B_01" in result
        assert result["GS_B_01"]["probability"] == 0.64
        assert result["GS_B_01"]["available"] is True

    def test_parse_live_xg_fields(self):
        """expected_home_goals / expected_away_goals extracted from live format."""
        result = parse_catboost_response(
            [self._make_live_prediction()],
            self._make_alias_lookup(),
            self._make_groups(),
            [],
        )
        entry = result["GS_B_01"]
        assert entry.get("expected_home_goals") == 1.8
        assert entry.get("expected_away_goals") == 0.9

    def test_parse_live_bracket_match(self):
        """Knockout prediction with nested event resolves against bracket."""
        bracket = [
            {"match_id": "R16_1", "team_a": "Brazil", "team_b": "Germany"},
        ]
        pred = {
            "id": 2002,
            "event": {
                "id": 6002,
                "home_team": "Brazil",
                "away_team": "Germany",
            },
            "prob_home_win": 55.0,
            "prob_draw": 25.0,
            "prob_away_win": 20.0,
            "confidence": 0.82,
            "model_version": "catboost-v5.0",
            "updated_at": "2026-06-27T12:00:00+00:00",
        }
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), {"groups": {}}, bracket,
        )
        assert "R16_1" in result
        assert result["R16_1"]["probability"] == 0.55
        assert result["R16_1"]["available"] is True

    def test_parse_live_missing_all_probs(self):
        """All prob fields None in live format → available=False."""
        pred = self._make_live_prediction({
            "prob_home_win": None,
            "prob_draw": None,
            "prob_away_win": None,
        })
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        entry = result["GS_B_01"]
        assert entry["available"] is False
        assert entry["reason"] == "predictions_not_available"

    def test_parse_live_missing_event_key(self):
        """No event key → gracefully skipped (no event_id to match)."""
        pred = {"id": 3003}  # No event key at all
        result = parse_catboost_response(
            [pred], self._make_alias_lookup(), self._make_groups(), [],
        )
        assert len(result) == 0

    def test_parse_live_flat_format_still_works(self):
        """Flat (legacy) format still works alongside new nested format."""
        predictions = [
            # Live nested format (string team names — real API)
            {
                "id": 101,
                "event": {
                    "id": 5001,
                    "home_team": "Argentina",
                    "away_team": "Algeria",
                },
                "prob_home_win": 64.0,
                "prob_draw": 20.0,
                "prob_away_win": 17.0,
                "confidence": 0.88,
                "model_version": "catboost-v5.0",
                "updated_at": "2026-06-21T12:00:00+00:00",
            },
            # Legacy flat format
            {
                "event_id": 5002,
                "home_team": "Brazil",
                "away_team": "Japan",
                "event_date": "2026-06-18T05:00:00+00:00",
                "home_probability": 55.0,
                "draw_probability": 25.0,
                "away_probability": 20.0,
                "confidence": 0.75,
                "model_version": "catboost-v5.0",
                "updated_at": "2026-06-20T12:00:00+00:00",
            },
        ]
        result = parse_catboost_response(
            predictions, self._make_alias_lookup(), self._make_groups(), [],
        )
        assert "GS_B_01" in result
        assert result["GS_B_01"]["probability"] == 0.64
        assert "GS_C_01" in result
        assert result["GS_C_01"]["probability"] == 0.55
