"""Tests for dialect-portable hybrid JSONB schema, DDL, and CRUD operations."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from football_core.persistence.engine import (
    ensure_schema,
    get_engine,
    init_db,
    reset_engine,
)
from football_core.persistence.schema import (
    JSONType,
    competition_states,
    match_records,
    metadata,
    retirement_records,
)


@pytest.fixture
def sqlite_engine() -> Engine:
    """Create a fresh in-memory SQLite engine for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    init_db(engine)
    return engine


def test_schema_creates_all_tables(sqlite_engine: Engine):
    """Verify that metadata creates all three required tables with correct column names."""
    table_names = set(metadata.tables.keys())
    assert {"match_records", "competition_states", "retirement_records"}.issubset(table_names)

    # Verify match_records primary keys and indexes
    pk_cols = [c.name for c in match_records.primary_key.columns]
    assert pk_cols == ["competition", "season", "match_id"]

    index_names = {idx.name for idx in match_records.indexes}
    assert "ix_match_records_comp_season_date" in index_names
    assert "ix_match_records_status" in index_names

    # Verify competition_states primary key
    cs_pk_cols = [c.name for c in competition_states.primary_key.columns]
    assert cs_pk_cols == ["competition", "season"]

    # Verify retirement_records primary key and index
    rr_pk_cols = [c.name for c in retirement_records.primary_key.columns]
    assert rr_pk_cols == ["competition", "record_id"]
    rr_indexes = {idx.name for idx in retirement_records.indexes}
    assert "ix_retirement_records_competition" in rr_indexes


def test_json_type_variant():
    """Verify that JSONType is dialect-portable with PostgreSQL JSONB variant."""
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB, dialect as pg_dialect
    from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

    assert isinstance(JSONType.dialect_impl(pg_dialect()), JSONB)
    assert isinstance(JSONType.dialect_impl(sqlite_dialect()), JSON)


def test_match_records_crud_and_json_roundtrip(sqlite_engine: Engine):
    """Verify inserting and querying match records preserves complex nested JSON structures."""
    now = datetime.now(timezone.utc)
    match_payload = {
        "match_id": "wc_2026_m01",
        "home_team": "USA",
        "away_team": "MEX",
        "home_score": 2,
        "away_score": 1,
        "provenance": "official",
        "stats": {"shots": [12, 8], "possession": 0.55},
    }

    with sqlite_engine.begin() as conn:
        conn.execute(
            match_records.insert().values(
                competition="worldcup",
                season="2026",
                match_id="wc_2026_m01",
                status="played",
                event_date=now,
                payload=match_payload,
            )
        )

    with sqlite_engine.connect() as conn:
        row = conn.execute(
            select(match_records).where(
                match_records.c.competition == "worldcup",
                match_records.c.season == "2026",
                match_records.c.match_id == "wc_2026_m01",
            )
        ).fetchone()

        assert row is not None
        assert row.competition == "worldcup"
        assert row.season == "2026"
        assert row.match_id == "wc_2026_m01"
        assert row.status == "played"
        assert row.payload == match_payload
        assert row.payload["stats"]["shots"] == [12, 8]


def test_competition_states_crud_and_update(sqlite_engine: Engine):
    """Verify competition_states insertion and update."""
    initial_state = {"phase": "league", "standings": [{"team": "Real Madrid", "points": 15}]}
    updated_state = {"phase": "knockout", "standings": [{"team": "Real Madrid", "points": 18}]}

    with sqlite_engine.begin() as conn:
        conn.execute(
            competition_states.insert().values(
                competition="ucl",
                season="2024-2025",
                mode="official",
                state=initial_state,
            )
        )

    with sqlite_engine.connect() as conn:
        row = conn.execute(
            select(competition_states).where(
                competition_states.c.competition == "ucl",
                competition_states.c.season == "2024-2025",
            )
        ).fetchone()
        assert row is not None
        assert row.mode == "official"
        assert row.state == initial_state

    # Update state
    with sqlite_engine.begin() as conn:
        conn.execute(
            competition_states.update()
            .where(
                competition_states.c.competition == "ucl",
                competition_states.c.season == "2024-2025",
            )
            .values(mode="simulated", state=updated_state)
        )

    with sqlite_engine.connect() as conn:
        row = conn.execute(
            select(competition_states).where(
                competition_states.c.competition == "ucl",
                competition_states.c.season == "2024-2025",
            )
        ).fetchone()
        assert row is not None
        assert row.mode == "simulated"
        assert row.state == updated_state


def test_retirement_records_crud(sqlite_engine: Engine):
    """Verify retirement records can be inserted and queried by competition."""
    now = datetime.now(timezone.utc)
    retired_match = {
        "match_id": "laliga_2024_m10",
        "home": "BAR",
        "away": "RMA",
        "retired_reason": "real_match_landed",
    }

    with sqlite_engine.begin() as conn:
        conn.execute(
            retirement_records.insert().values(
                competition="laliga",
                record_id="ret_001",
                retired_match=retired_match,
                retired_at=now,
            )
        )

    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            select(retirement_records).where(
                retirement_records.c.competition == "laliga"
            )
        ).fetchall()
        assert len(rows) == 1
        assert rows[0].record_id == "ret_001"
        assert rows[0].retired_match == retired_match


def test_ensure_schema_caching_and_cooldown(monkeypatch: pytest.MonkeyPatch):
    """Verify ensure_schema caches success and enforces retry cooldown on failure."""
    reset_engine()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    # Initial ensure_schema initializes tables and returns True
    assert ensure_schema() is True
    # Subsequent call returns True immediately (cached)
    assert ensure_schema() is True

    # Test failure path and cooldown
    reset_engine()
    engine = get_engine()
    assert engine is not None

    with patch("football_core.persistence.engine.metadata.create_all", side_effect=SQLAlchemyError("Connection refused")):
        # First call fails and sets cooldown
        assert ensure_schema() is False

        # Immediate second call is suppressed by cooldown without even calling create_all again
        with patch("football_core.persistence.engine.init_db") as mock_init:
            assert ensure_schema() is False
            mock_init.assert_not_called()

        # After advancing time past cooldown (10s), init_db is attempted again
        with patch("time.monotonic", return_value=time.monotonic() + 15.0):
            # If still failing
            assert ensure_schema() is False
