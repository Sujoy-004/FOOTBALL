"""Tests for secret redaction hardening and logging filter.

Covers SEC-01 and SEC-02:
- DATABASE_URL password extraction and redaction
- ADMIN_KEY and environment credential scrubbing
- Query string parameters (?admin_key=, ?apiKey=) and Bearer tokens
- SecretRedactingFilter on log messages, dict args, and tuple args
- Traceback formatting and pre-sanitization into exc_text with null exc_info
"""

import logging
import sys
import pytest

from football_core.domain import redact_secrets
from web.security import SecretRedactingFilter, install_logging_filters


def test_redact_secrets_database_url(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://app_user:super_secret_db_pass_777@ep-cool-db.eu-central-1.neon.tech/neondb?sslmode=require",
    )
    # Test redaction of full connection URL in text
    conn_text = "Database connection string: postgresql://app_user:super_secret_db_pass_777@ep-cool-db.eu-central-1.neon.tech/neondb"
    sanitized_conn = redact_secrets(conn_text)
    assert "super_secret_db_pass_777" not in sanitized_conn
    assert "[REDACTED]" in sanitized_conn

    # Test redaction of isolated password leaking in error message
    err_text = 'connection failed: password authentication failed for user "app_user": password "super_secret_db_pass_777"'
    sanitized_err = redact_secrets(err_text)
    assert "super_secret_db_pass_777" not in sanitized_err
    assert "[REDACTED]" in sanitized_err


def test_redact_secrets_admin_key_and_env_vars(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "operator_secret_admin_key_456")
    monkeypatch.setenv("SECRET_TOKEN", "bearer_token_xyz_888")

    text1 = "Authorized request with ADMIN_KEY: operator_secret_admin_key_456"
    sanitized1 = redact_secrets(text1)
    assert "operator_secret_admin_key_456" not in sanitized1
    assert "[REDACTED]" in sanitized1

    text2 = "Auth failure for token: bearer_token_xyz_888"
    sanitized2 = redact_secrets(text2)
    assert "bearer_token_xyz_888" not in sanitized2
    assert "[REDACTED]" in sanitized2


def test_redact_secrets_query_params_and_bearer():
    query_url1 = "https://football.example.com/api/admin/sync?admin_key=supersecret999&dry_run=true"
    sanitized_query1 = redact_secrets(query_url1)
    assert "supersecret999" not in sanitized_query1
    assert "admin_key=[REDACTED]" in sanitized_query1
    assert "dry_run=true" in sanitized_query1

    query_url2 = "https://api.the-odds-api.com/v4/odds/?apiKey=odds_api_key_12345&region=eu"
    sanitized_query2 = redact_secrets(query_url2)
    assert "odds_api_key_12345" not in sanitized_query2
    assert "apiKey=[REDACTED]" in sanitized_query2
    assert "region=eu" in sanitized_query2

    auth_bearer = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token"
    sanitized_bearer = redact_secrets(auth_bearer)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token" not in sanitized_bearer
    assert "Bearer [REDACTED]" in sanitized_bearer

    assignment = '{"admin_key": "raw_admin_key_val_321"}'
    sanitized_assign = redact_secrets(assignment)
    assert "raw_admin_key_val_321" not in sanitized_assign
    assert "[REDACTED]" in sanitized_assign


def test_secret_redacting_filter_msg_and_args(monkeypatch):
    monkeypatch.setenv("API_KEY", "sensitive_api_token_555")
    filter_obj = SecretRedactingFilter()

    # Test msg scrubbing
    record_msg = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Leaking key: sensitive_api_token_555 in message",
        args=(),
        exc_info=None,
    )
    assert filter_obj.filter(record_msg) is True
    assert "sensitive_api_token_555" not in record_msg.msg
    assert "[REDACTED]" in record_msg.msg

    # Test tuple args scrubbing
    record_tuple = logging.LogRecord(
        name="test_logger",
        level=logging.WARNING,
        pathname="test.py",
        lineno=20,
        msg="Token is %s for user %s",
        args=("sensitive_api_token_555", "alice"),
        exc_info=None,
    )
    assert filter_obj.filter(record_tuple) is True
    assert record_tuple.args[0] == "[REDACTED]"
    assert record_tuple.args[1] == "alice"

    # Test dict args scrubbing
    record_dict = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=30,
        msg="Details: %(secret)s",
        args={"secret": "sensitive_api_token_555", "code": 100},
        exc_info=None,
    )
    assert filter_obj.filter(record_dict) is True
    assert record_dict.args["secret"] == "[REDACTED]"
    assert record_dict.args["code"] == 100


def test_secret_redacting_filter_traceback_scrubbing(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:db_password_in_traceback_999@host:5432/db")
    filter_obj = SecretRedactingFilter()

    try:
        raise ValueError("Database connection failed with password: db_password_in_traceback_999")
    except Exception:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=50,
        msg="Database error occurred",
        args=(),
        exc_info=exc_info,
    )

    assert filter_obj.filter(record) is True
    # exc_info must be nulled to prevent unredacted formatException call downstream
    assert record.exc_info is None
    # exc_text must be populated and sanitized
    assert record.exc_text is not None
    assert "db_password_in_traceback_999" not in record.exc_text
    assert "[REDACTED]" in record.exc_text
    assert "Traceback (most recent call last):" in record.exc_text


def test_install_logging_filters_attaches_to_all_targets():
    install_logging_filters()
    root = logging.getLogger()
    assert any(isinstance(f, SecretRedactingFilter) for f in root.filters)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "football_core", "web"):
        l = logging.getLogger(name)
        assert any(isinstance(f, SecretRedactingFilter) for f in l.filters)
