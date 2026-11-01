"""Hybrid storage repository providing PostgreSQL persistence with local JSON fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import football_core.state as core_state
from football_core.domain import redact_secrets
from football_core.persistence.engine import ensure_schema, get_engine, is_database_configured
from football_core.persistence.schema import competition_states, match_records, retirement_records

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def save_played_matches(
    competition: str,
    season: str,
    matches: Mapping[str, Any],
    data_dir: Path | str | None = None,
) -> None:
    """Save played match facts to PostgreSQL or fall back to local played.json.

    Args:
        competition: Competition identifier (e.g. 'worldcup', 'ucl', 'laliga').
        season: Season identifier (e.g. '2026', '2025-2026').
        matches: Dictionary mapping match_id to match payload.
        data_dir: Optional path for offline fallback store.
    """
    if not is_database_configured():
        core_state.save_played(dict(matches), data_dir=data_dir)
        return

    engine = get_engine()
    if engine is None or not ensure_schema():
        logger.warning("Database unavailable; falling back to disk for save_played_matches")
        core_state.save_played(dict(matches), data_dir=data_dir)
        return

    insert_fn = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert

    now = _now_utc()
    rows = []
    for match_id, payload in matches.items():
        status = payload.get("status", "played") if isinstance(payload, Mapping) else "played"
        raw_date = payload.get("event_date") or payload.get("date") if isinstance(payload, Mapping) else None
        event_date = None
        if raw_date:
            try:
                event_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                if event_date.tzinfo is None:
                    event_date = event_date.replace(tzinfo=timezone.utc)
            except Exception:
                event_date = None

        rows.append({
            "competition": competition,
            "season": str(season),
            "match_id": str(match_id),
            "status": str(status),
            "event_date": event_date,
            "payload": payload,
            "updated_at": now,
        })

    if not rows:
        return

    try:
        with engine.begin() as conn:
            for row in rows:
                stmt = insert_fn(match_records).values(row)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["competition", "season", "match_id"],
                    set_={
                        "status": stmt.excluded.status,
                        "event_date": stmt.excluded.event_date,
                        "payload": stmt.excluded.payload,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                conn.execute(stmt)
    except Exception as exc:
        safe_msg = redact_secrets(str(exc))
        logger.error("Failed to save matches to database: %s; falling back to disk", safe_msg)
        core_state.save_played(dict(matches), data_dir=data_dir)


def load_played_matches(
    competition: str,
    season: str,
    data_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Load played match facts from PostgreSQL or fall back to local played.json."""
    if not is_database_configured():
        return core_state.load_played(data_dir=data_dir)

    engine = get_engine()
    if engine is None:
        return core_state.load_played(data_dir=data_dir)

    try:
        with engine.connect() as conn:
            stmt = select(match_records.c.match_id, match_records.c.payload).where(
                match_records.c.competition == competition,
                match_records.c.season == str(season),
            )
            rows = conn.execute(stmt).fetchall()
            return {r[0]: r[1] for r in rows}
    except Exception as exc:
        safe_msg = redact_secrets(str(exc))
        logger.error("Failed to load matches from database: %s; falling back to disk", safe_msg)
        return core_state.load_played(data_dir=data_dir)


def save_competition_state(
    competition: str,
    season: str,
    mode: str,
    state: Mapping[str, Any],
) -> None:
    """Save derived competition state snapshot to database."""
    if not is_database_configured():
        return

    engine = get_engine()
    if engine is None or not ensure_schema():
        return

    insert_fn = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    now = _now_utc()
    row = {
        "competition": competition,
        "season": str(season),
        "mode": str(mode),
        "state": dict(state),
        "updated_at": now,
    }

    try:
        with engine.begin() as conn:
            stmt = insert_fn(competition_states).values(row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["competition", "season"],
                set_={
                    "mode": stmt.excluded.mode,
                    "state": stmt.excluded.state,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            conn.execute(stmt)
    except Exception as exc:
        safe_msg = redact_secrets(str(exc))
        logger.error("Failed to save competition state: %s", safe_msg)


def load_competition_state(
    competition: str,
    season: str,
) -> Optional[dict[str, Any]]:
    """Load latest derived state snapshot from database if present."""
    if not is_database_configured():
        return None

    engine = get_engine()
    if engine is None:
        return None

    try:
        with engine.connect() as conn:
            stmt = select(competition_states.c.state).where(
                competition_states.c.competition == competition,
                competition_states.c.season == str(season),
            )
            row = conn.execute(stmt).fetchone()
            return row[0] if row else None
    except Exception as exc:
        safe_msg = redact_secrets(str(exc))
        logger.error("Failed to load competition state: %s", safe_msg)
        return None


def append_retirement_records(
    competition: str,
    records: list[dict[str, Any]],
) -> None:
    """Append retirement records to database."""
    if not is_database_configured() or not records:
        return

    engine = get_engine()
    if engine is None or not ensure_schema():
        return

    insert_fn = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    now = _now_utc()

    try:
        with engine.begin() as conn:
            for idx, rec in enumerate(records):
                record_id = str(rec.get("record_id") or rec.get("match_id") or f"ret_{idx}")
                raw_retired_at = rec.get("retired_at")
                retired_at = now
                if raw_retired_at:
                    try:
                        retired_at = datetime.fromisoformat(str(raw_retired_at).replace("Z", "+00:00"))
                        if retired_at.tzinfo is None:
                            retired_at = retired_at.replace(tzinfo=timezone.utc)
                    except Exception:
                        retired_at = now

                row = {
                    "competition": competition,
                    "record_id": record_id,
                    "retired_match": rec,
                    "retired_at": retired_at,
                }
                stmt = insert_fn(retirement_records).values(row).on_conflict_do_nothing()
                conn.execute(stmt)
    except Exception as exc:
        safe_msg = redact_secrets(str(exc))
        logger.error("Failed to append retirement records: %s", safe_msg)
