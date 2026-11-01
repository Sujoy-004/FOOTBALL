"""Security and credential hygiene tests for football_core/odds.py.

Verifies D-04:
- sanitize_odds_url removes apiKey query parameters from URLs and exception strings.
- TheOddsApiOddsProvider redacts API credentials in transport exceptions and provenance fields.
"""

from __future__ import annotations

import pytest
import requests

from football_core.odds import (
    TheOddsApiOddsProvider,
    ProviderUnavailableError,
    sanitize_odds_url,
)


class TestSanitizeOddsUrl:
    def test_empty_and_none(self):
        assert sanitize_odds_url("") == ""
        assert sanitize_odds_url(None) is None

    def test_url_without_api_key(self):
        url = "https://api.the-odds-api.com/v4/sports/soccer/odds/?regions=eu&markets=h2h"
        assert sanitize_odds_url(url) == url

    def test_url_with_first_param_api_key(self):
        url = "https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey=secret_key_123&regions=eu"
        sanitized = sanitize_odds_url(url)
        assert "secret_key_123" not in sanitized
        assert "apiKey=[REDACTED]" in sanitized
        assert sanitized == "https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey=[REDACTED]&regions=eu"

    def test_url_with_subsequent_param_api_key(self):
        url = "https://api.the-odds-api.com/v4/sports/soccer/odds/?regions=eu&apiKey=secret_key_456"
        sanitized = sanitize_odds_url(url)
        assert "secret_key_456" not in sanitized
        assert "&apiKey=[REDACTED]" in sanitized
        assert sanitized == "https://api.the-odds-api.com/v4/sports/soccer/odds/?regions=eu&apiKey=[REDACTED]"

    def test_case_insensitive_api_key(self):
        url = "https://example.com/api?APIKEY=secret_abc&other=1"
        sanitized = sanitize_odds_url(url)
        assert "secret_abc" not in sanitized
        assert "[REDACTED]" in sanitized

        url2 = "https://example.com/api?foo=1&ApiKey=secret_def"
        sanitized2 = sanitize_odds_url(url2)
        assert "secret_def" not in sanitized2
        assert "[REDACTED]" in sanitized2


class TestOddsProviderCredentialRedaction:
    def test_odds_provider_redacts_api_key_in_exceptions(self):
        secret_key = "secret_12345_very_confidential"
        provider = TheOddsApiOddsProvider(api_key=secret_key)

        def mock_failing_http(url, params):
            raise requests.RequestException(
                f"Connection failed for url: https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={secret_key}&regions=eu"
            )

        with pytest.raises(ProviderUnavailableError) as exc_info:
            provider.fetch_events("laliga", http_fn=mock_failing_http)

        msg = str(exc_info.value)
        assert secret_key not in msg
        assert "apiKey=[REDACTED]" in msg
        assert "the-odds-api transport error: RequestException" in msg

    def test_odds_provider_redacts_plain_key_leakage(self):
        secret_key = "secret_plain_key_xyz987"
        provider = TheOddsApiOddsProvider(api_key=secret_key)

        def mock_failing_http(url, params):
            raise ConnectionError(f"Fatal socket error with credentials {secret_key}")

        with pytest.raises(ProviderUnavailableError) as exc_info:
            provider.fetch_events("laliga", http_fn=mock_failing_http)

        msg = str(exc_info.value)
        assert secret_key not in msg
        assert "[REDACTED]" in msg

    def test_normalize_event_redacts_provenance_url(self):
        secret_key = "secret_norm_key"
        provider = TheOddsApiOddsProvider(api_key=secret_key)
        raw_event = {
            "id": "evt-123",
            "home_team": "Real Madrid",
            "away_team": "Barcelona",
            "commence_time": "2026-11-10T20:00:00Z",
            "bookmakers": [],
        }
        url_with_key = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={secret_key}&regions=eu"
        normalized = provider._normalize_event(raw_event, url_with_key)

        assert secret_key not in normalized["provenance"]
        assert "apiKey=[REDACTED]" in normalized["provenance"]
