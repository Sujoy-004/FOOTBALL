"""Serverless engine lifecycle and connection management."""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from football_core.domain import redact_secrets
from football_core.persistence.normalizer import normalize_database_url

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_schema_ready: bool = False
_schema_retry_after: float = 0.0
_SCHEMA_RETRY_COOLDOWN: float = 10.0


def get_database_url() -> str:
    """Read DATABASE_URL from environment and normalize."""
    return normalize_database_url(os.environ.get("DATABASE_URL"))


def is_database_configured() -> bool:
    """True when a non-empty DATABASE_URL is configured."""
    return bool(get_database_url())


def get_engine() -> Optional[Engine]:
    """Get or lazily initialize the SQLAlchemy engine."""
    global _engine
    if _engine is not None:
        return _engine

    db_url = get_database_url()
    if not db_url:
        return None

    is_sqlite = db_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {"connect_timeout": 10}

    _engine = create_engine(
        db_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=300,
    )
    return _engine


def reset_engine() -> None:
    """Reset the cached engine and schema status (for testing and isolation)."""
    global _engine, _schema_ready, _schema_retry_after
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None
    _schema_ready = False
    _schema_retry_after = 0.0


def check_db_health() -> tuple[str, bool]:
    """Probe database connectivity for web/health.py.

    Returns:
        (driver_label, is_healthy)
        - "fallback_json", True (when DATABASE_URL is unset)
        - "sqlite" / "postgres", True (when connection succeeds)
        - "sqlite" / "postgres", False (when connection fails)
    """
    db_url = get_database_url()
    if not db_url:
        return "fallback_json", True

    engine = get_engine()
    if engine is None:
        return "uninitialized", False

    driver_label = "sqlite" if engine.dialect.name == "sqlite" else "postgres"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return driver_label, True
    except Exception as exc:
        safe_msg = redact_secrets(str(exc))
        logger.error("Database health check probe failed: %s", safe_msg)
        return driver_label, False
