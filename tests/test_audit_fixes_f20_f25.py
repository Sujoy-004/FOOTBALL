"""Tests for F-20, F-24 (mark UNAVAILABLE on boot failure) and F-25 (secret redaction)."""

import asyncio
import os
import pytest
from unittest.mock import patch, MagicMock

from football_core.domain import redact_secrets, DataAvailability
from football_core.odds import TheOddsApiOddsProvider, ProviderUnavailableError
from web.derived import holder


def test_redact_secrets_none_and_empty():
    assert redact_secrets(None) is None
    assert redact_secrets("") == ""


def test_redact_secrets_query_parameters():
    url = "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/?apiKey=abc12345xyz&regions=eu"
    sanitized = redact_secrets(url)
    assert "abc12345xyz" not in sanitized
    assert "apiKey=[REDACTED]" in sanitized
    assert "regions=eu" in sanitized


def test_redact_secrets_auth_headers():
    header = "Authorization: Bearer secret_bearer_token_xyz"
    sanitized = redact_secrets(header)
    assert "secret_bearer_token_xyz" not in sanitized
    assert "Bearer [REDACTED]" in sanitized

    token_header = "Authorization: Token secret_token_abc"
    sanitized_token = redact_secrets(token_header)
    assert "secret_token_abc" not in sanitized_token
    assert "Token [REDACTED]" in sanitized_token


def test_redact_secrets_env_vars(monkeypatch):
    monkeypatch.setenv("TEST_SERVICE_API_KEY", "my_super_secret_key_456")
    msg = "Connection failed to server using my_super_secret_key_456 for authentication"
    sanitized = redact_secrets(msg)
    assert "my_super_secret_key_456" not in sanitized
    assert "[REDACTED]" in sanitized


def test_the_odds_api_provider_redacts_keys_on_transport_failure():
    secret_key = "very_secret_odds_key_789"
    provider = TheOddsApiOddsProvider(api_key=secret_key)

    def failing_http(url, params):
        raise ConnectionError(f"Failed to connect to {url} with params {params}")

    with pytest.raises(ProviderUnavailableError) as exc_info:
        provider.fetch_events("laliga", http_fn=failing_http)

    error_msg = str(exc_info.value)
    assert secret_key not in error_msg
    assert "[REDACTED]" in error_msg


def test_server_boot_unavailable_handling():
    from web.server import lifespan, app

    async def _run():
        holder.reset("worldcup")
        with patch("web.wc_app.compute_overview", side_effect=RuntimeError("Disk corrupted")):
            async with lifespan(app):
                wc_data = holder.read_data("worldcup")
                assert wc_data.get("availability") == "UNAVAILABLE"
                assert wc_data.get("mode") == "unavailable"
                assert holder.read_mode("worldcup") == "unavailable"
                assert holder.read_stamp("worldcup") is None

    asyncio.run(_run())
