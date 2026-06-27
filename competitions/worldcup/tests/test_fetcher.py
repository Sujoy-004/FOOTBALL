"""Tests for the fetcher module (fetch_raw_matches, process_matches)."""

import json

import pytest
import requests

from src.fetcher import (
    _extract_ai_preview,
    build_historic_url,
    fetch_raw_matches,
    process_matches,
)


class MockResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(
                f"HTTP {self.status_code}", response=self
            )


SAMPLE_MATCHES = [
    {
        "id": 12345,
        "status": "finished",
        "home_team": "Iran",
        "away_team": "Argentina",
        "home_score": 0,
        "away_score": 2,
        "event_date": "2026-06-15T22:00:00Z",
        "league": {"id": 27},
    }
]

SAMPLE_ALIASES = {"Iran": ["IR Iran"]}


def test_build_historic_url_format(monkeypatch):
    """build_historic_url returns a valid URL with WC_START_DATE and today's date."""
    from datetime import datetime
    import src.constants as c
    url = build_historic_url()
    assert url.startswith("https://sports.bzzoiro.com/api/events/")
    assert f"date_from={c.WC_START_DATE}" in url
    assert f"date_to={datetime.now().strftime('%Y-%m-%d')}" in url
    assert "league_id=27" in url
    assert "limit=200" in url


def test_build_historic_url_custom_league(monkeypatch):
    """build_historic_url(league_id=65) returns URL with league_id=65 instead of default 27."""
    from datetime import datetime
    import src.constants as c
    url = build_historic_url(league_id=65)
    assert url.startswith("https://sports.bzzoiro.com/api/events/")
    assert f"date_from={c.WC_START_DATE}" in url
    assert f"date_to={datetime.now().strftime('%Y-%m-%d')}" in url
    assert "league_id=65" in url
    assert "league_id=27" not in url
    assert "limit=200" in url


def test_fetch_success(monkeypatch):
    def mock_get(url, **kwargs):
        return MockResponse(200, {"results": SAMPLE_MATCHES})
    monkeypatch.setattr(requests, "get", mock_get)

    result = fetch_raw_matches("fake_key", "https://sports.bzzoiro.com/api/events/", 27)
    assert len(result) == 1
    assert result[0]["id"] == 12345


def test_fetch_empty_response(monkeypatch):
    def mock_get(url, **kwargs):
        return MockResponse(200, {"results": []})
    monkeypatch.setattr(requests, "get", mock_get)

    result = fetch_raw_matches("fake_key", "https://sports.bzzoiro.com/api/events/", 27)
    assert result == []


def test_fetch_all_retries_exhausted(monkeypatch):
    calls = []

    def mock_get(url, **kwargs):
        calls.append(kwargs)
        return MockResponse(500, {})
    monkeypatch.setattr(requests, "get", mock_get)

    result = fetch_raw_matches("fake_key", "https://sports.bzzoiro.com/api/events/", 27)
    assert result == []
    assert len(calls) == 3


def test_fetch_401_returns_empty(monkeypatch):
    def mock_get(url, **kwargs):
        return MockResponse(401, {})
    monkeypatch.setattr(requests, "get", mock_get)

    result = fetch_raw_matches("fake_key", "https://sports.bzzoiro.com/api/events/", 27)
    assert result == []


def test_fetch_timeout_retry(monkeypatch):
    calls = []

    def mock_get(url, **kwargs):
        calls.append(kwargs)
        raise requests.exceptions.Timeout()
    monkeypatch.setattr(requests, "get", mock_get)

    result = fetch_raw_matches("fake_key", "https://sports.bzzoiro.com/api/events/", 27)
    assert result == []
    assert len(calls) == 3


def test_fetch_malformed_json(monkeypatch):
    class BadJSONResponse(MockResponse):
        def json(self):
            raise json.JSONDecodeError("bad json", "", 0)
    monkeypatch.setattr(
        requests, "get",
        lambda url, **kwargs: BadJSONResponse(200, {}),
    )

    result = fetch_raw_matches("fake_key", "https://sports.bzzoiro.com/api/events/", 27)
    assert result == []


def test_process_matches_normalizes():
    bracket = [
        {"match_id": "R16_X", "team_a": "Argentina", "team_b": "Iran", "source_matches": None, "winner": None},
    ]
    result = process_matches(
        SAMPLE_MATCHES, {}, bracket, SAMPLE_ALIASES, set(),
    )
    assert len(result) == 1
    assert result[0]["winner"] == "Argentina"
    assert result[0]["team_a"] == "Iran"
    assert result[0]["team_b"] == "Argentina"
    assert result[0]["match_id"] == "R16_X"


def test_process_matches_unmatchable():
    bracket = [
        {"match_id": "R16_X", "team_a": "Argentina", "team_b": "Iran", "source_matches": None, "winner": None},
    ]
    bad_matches = [
        {
            "id": 999,
            "status": "finished",
            "home_team": "UnknownTeam",
            "away_team": "Argentina",
            "home_score": 1,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
        }
    ]
    result = process_matches(bad_matches, {}, bracket, SAMPLE_ALIASES, set())
    assert result == []


def test_process_matches_filters_played():
    bracket = [
        {"match_id": "R16_X", "team_a": "Argentina", "team_b": "Iran", "source_matches": None, "winner": None},
    ]
    result = process_matches(
        SAMPLE_MATCHES, {}, bracket, SAMPLE_ALIASES, {"12345"},
    )
    assert result == []


def test_process_matches_draw():
    """Draw match (equal scores, no BSD winner) produces entry with winner=None, is_draw=True."""
    bracket = [
        {"match_id": "R16_X", "team_a": "Argentina", "team_b": "Iran", "source_matches": None, "winner": None},
    ]
    draw_match = [{
        "id": 99991, "status": "finished",
        "home_team": "Iran", "away_team": "Argentina",
        "home_score": 1, "away_score": 1,
        "event_date": "2026-06-15T22:00:00Z", "league": {"id": 27},
    }]
    result = process_matches(draw_match, {}, bracket, SAMPLE_ALIASES, set())
    assert len(result) == 1
    assert result[0]["winner"] is None
    assert result[0]["is_draw"] is True
    assert result[0]["home_score"] == 1
    assert result[0]["away_score"] == 1
    assert result[0]["match_id"] == "R16_X"


def test_process_matches_pk():
    """PK shootout (equal scores + BSD winner) produces entry with winner set, is_draw=False."""
    bracket = [
        {"match_id": "R16_X", "team_a": "Argentina", "team_b": "Iran", "source_matches": None, "winner": None},
    ]
    pk_match = [{
        "id": 99992, "status": "finished",
        "home_team": "Iran", "away_team": "Argentina",
        "home_score": 1, "away_score": 1, "winner": "Argentina",
        "event_date": "2026-06-15T22:00:00Z", "league": {"id": 27},
    }]
    result = process_matches(pk_match, {}, bracket, SAMPLE_ALIASES, set())
    assert len(result) == 1
    assert result[0]["winner"] == "Argentina"
    assert result[0]["is_draw"] is False
    assert result[0]["match_id"] == "R16_X"


ENRICHED_MATCH = {
    "id": 99993, "status": "finished",
    "home_team": "Iran", "away_team": "Argentina",
    "home_score": 0, "away_score": 2,
    "event_date": "2026-06-15T22:00:00Z", "league": {"id": 27},
    "live_stats": {
        "home": {"yellow_cards": 3, "red_cards": 0, "shots_on_target": 2, "ball_possession": 42},
        "away": {"yellow_cards": 1, "red_cards": 0, "shots_on_target": 5, "ball_possession": 58},
    },
    "venue": {"name": "Azadi Stadium"},
    "referee": {"name": "Felix Zwayer"},
}


def test_process_matches_with_enrichment():
    """process_matches() attaches stats and context keys when BSD provides them."""
    bracket = [
        {"match_id": "R16_X", "team_a": "Argentina", "team_b": "Iran", "source_matches": None, "winner": None},
    ]
    result = process_matches([ENRICHED_MATCH], {}, bracket, SAMPLE_ALIASES, set())
    assert len(result) == 1
    entry = result[0]
    assert "stats" in entry
    assert entry["stats"]["yellow_cards_home"] == 3
    assert entry["stats"]["yellow_cards_away"] == 1
    assert entry["stats"]["possession_home"] == 42
    assert entry["stats"]["possession_away"] == 58
    assert "context" in entry
    assert entry["context"]["venue"] == "Azadi Stadium"
    assert entry["context"]["referee"] == "Felix Zwayer"


# ─── AI preview extraction tests (Phase 18) ────────────────────────────


def test_extract_ai_preview_present():
    """Valid ai_preview.text returns the text string."""
    result = _extract_ai_preview({
        "ai_preview": {"text": "Mexico expected to dominate possession."}
    })
    assert result == "Mexico expected to dominate possession."


def test_extract_ai_preview_missing():
    """Absent ai_preview key returns None."""
    result = _extract_ai_preview({})
    assert result is None


def test_extract_ai_preview_empty_text():
    """Empty ai_preview.text returns None."""
    result = _extract_ai_preview({"ai_preview": {"text": ""}})
    assert result is None


def test_extract_ai_preview_not_dict():
    """Non-dict ai_preview returns None."""
    result = _extract_ai_preview({"ai_preview": "just a string"})
    assert result is None


def test_process_matches_no_stats():
    """process_matches() omits stats key when BSD live_stats is None."""
    bracket = [
        {"match_id": "R16_X", "team_a": "Argentina", "team_b": "Iran", "source_matches": None, "winner": None},
    ]
    no_stats = dict(ENRICHED_MATCH, live_stats=None)
    result = process_matches([no_stats], {}, bracket, SAMPLE_ALIASES, set())
    assert len(result) == 1
    assert "stats" not in result[0]
    assert "context" in result[0]
