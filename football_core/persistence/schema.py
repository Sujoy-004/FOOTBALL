"""SQLAlchemy Core Table definitions for Neon serverless cloud persistence."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    JSON,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

# Portable JSON column: JSONB on PostgreSQL, JSON on SQLite
JSONType = JSON().with_variant(JSONB, "postgresql")

# Match facts table (PERS-01, D-03)
match_records = Table(
    "match_records",
    metadata,
    Column("competition", String(32), nullable=False),
    Column("season", String(32), nullable=False),
    Column("match_id", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("event_date", DateTime(timezone=True), nullable=True),
    Column("payload", JSONType, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
    PrimaryKeyConstraint("competition", "season", "match_id", name="pk_match_records"),
    Index("ix_match_records_comp_season_date", "competition", "season", "event_date"),
    Index("ix_match_records_status", "status"),
)

# Competition state snapshots (PERS-01, D-03)
competition_states = Table(
    "competition_states",
    metadata,
    Column("competition", String(32), nullable=False),
    Column("season", String(32), nullable=False),
    Column("mode", String(32), nullable=False),
    Column("state", JSONType, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
    PrimaryKeyConstraint("competition", "season", name="pk_competition_states"),
)

# Retirement records ledger (PERS-01, D-03)
retirement_records = Table(
    "retirement_records",
    metadata,
    Column("competition", String(32), nullable=False),
    Column("record_id", String(128), nullable=False),
    Column("retired_match", JSONType, nullable=False),
    Column("retired_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("competition", "record_id", name="pk_retirement_records"),
    Index("ix_retirement_records_competition", "competition"),
)
