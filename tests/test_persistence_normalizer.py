"""Tests for database URL normalization and serverless engine factory."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.engine import Engine

from football_core.persistence.engine import (
    check_db_health,
    get_database_url,
    get_engine,
    is_database_configured,
    reset_engine,
)
from football_core.persistence.normalizer import normalize_database_url


@pytest.fixture(autouse=True)
def clean_engine():
    """Ensure engine state is clean before and after each test."""
    reset_engine()
    yield
    reset_engine()


@pytest.mark.parametrize(
    ("input_url", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("sqlite:///:memory:", "sqlite:///:memory:"),
        ("sqlite:///./data/test.db", "sqlite:///./data/test.db"),
        ("postgres://user:pass@localhost:5432/mydb", "postgresql://user:pass@localhost:5432/mydb"),
        ("postgresql://user:pass@localhost:5432/mydb", "postgresql://user:pass@localhost:5432/mydb"),
        (
            "postgresql://u:p@ep-cool-fog-123456.eu-central-1.aws.neon.tech/neondb",
            "postgresql://u:p@ep-cool-fog-123456-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        ),
        (
            "postgres://u:p@ep-cool-fog-123456.eu-central-1.aws.neon.tech/neondb",
            "postgresql://u:p@ep-cool-fog-123456-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        ),
        (
            "postgresql://u:p@ep-cool-fog-123456-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require",
            "postgresql://u:p@ep-cool-fog-123456-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        ),
        (
            "postgresql://u:p@ep-cool-fog-123456-pooler.eu-central-1.aws.neon.tech/neondb",
            "postgresql://u:p@ep-cool-fog-123456-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        ),
        (
            "postgres://user%40example.com:p%25ss%3Aword@ep-xyz-987.us-east-2.aws.neon.tech:5432/football?channel_binding=require",
            "postgresql://user%40example.com:p%25ss%3Aword@ep-xyz-987-pooler.us-east-2.aws.neon.tech:5432/football?channel_binding=require&sslmode=require",
        ),
    ],
)
def test_normalize_database_url_cases(input_url: str | None, expected: str):
    """Verify URL normalization handles schemes, hosts, pooler injection, and credentials."""
    result = normalize_database_url(input_url)
    assert result == expected


def test_idempotent_neon_pooler_handling():
    """Verify that multiple normalization passes do not duplicate -pooler suffix."""
    url = "postgres://user:pass@ep-sample-123.eu-west-1.aws.neon.tech/neondb"
    norm1 = normalize_database_url(url)
    norm2 = normalize_database_url(norm1)
    norm3 = normalize_database_url(norm2)

    assert norm1 == norm2 == norm3
    assert norm1.count("-pooler") == 1
    assert "sslmode=require" in norm1


def test_password_preservation_with_special_characters():
    """Verify usernames and passwords with percent-encoding and special chars are preserved."""
    url = "postgresql://my_user%40org:secret%23p%24ss%25word@ep-xyz.eu-central-1.aws.neon.tech:5432/db"
    normalized = normalize_database_url(url)
    assert "my_user%40org:secret%23p%24ss%25word@" in normalized
    assert "ep-xyz-pooler.eu-central-1.aws.neon.tech:5432" in normalized
    assert normalized.endswith("?sslmode=require")


def test_engine_pool_options_and_resilience_sqlite(monkeypatch: pytest.MonkeyPatch):
    """Verify engine creates with pool_pre_ping, pool_recycle, and check_same_thread for SQLite."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    reset_engine()

    assert is_database_configured() is True
    engine = get_engine()
    assert isinstance(engine, Engine)
    assert engine.dialect.name == "sqlite"
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 300

    # Engine is cached lazily
    assert get_engine() is engine


def test_engine_pool_options_postgres(monkeypatch: pytest.MonkeyPatch):
    """Verify postgres engine configures connect_timeout=10, pool_pre_ping=True, pool_recycle=300."""
    neon_url = "postgres://u:p@ep-test-123.eu-central-1.aws.neon.tech/neondb"
    monkeypatch.setenv("DATABASE_URL", neon_url)
    reset_engine()

    with patch("football_core.persistence.engine.create_engine") as mock_create_engine:
        mock_engine = MagicMock(spec=Engine)
        mock_create_engine.return_value = mock_engine

        engine = get_engine()
        assert engine is mock_engine
        mock_create_engine.assert_called_once()
        args, kwargs = mock_create_engine.call_args

        assert args[0] == "postgresql://u:p@ep-test-123-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require"
        assert kwargs.get("pool_pre_ping") is True
        assert kwargs.get("pool_recycle") == 300
        assert kwargs.get("connect_args") == {"connect_timeout": 10}


def test_check_db_health_fallback_json_when_unset(monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is unset, check_db_health returns ('fallback_json', True)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine()

    assert is_database_configured() is False
    assert get_database_url() == ""
    assert get_engine() is None
    driver, healthy = check_db_health()
    assert driver == "fallback_json"
    assert healthy is True


def test_check_db_health_sqlite(monkeypatch: pytest.MonkeyPatch):
    """When configured with SQLite, check_db_health probes SELECT 1 and returns ('sqlite', True)."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    reset_engine()

    driver, healthy = check_db_health()
    assert driver == "sqlite"
    assert healthy is True


def test_check_db_health_failure_redacts_credentials(monkeypatch: pytest.MonkeyPatch):
    """When probing fails, errors are redacted and returns (driver, False)."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    reset_engine()

    engine = get_engine()
    assert engine is not None

    with patch.object(engine, "connect", side_effect=Exception("Database password=super_secret_123 failed")):
        driver, healthy = check_db_health()
        assert driver == "sqlite"
        assert healthy is False
