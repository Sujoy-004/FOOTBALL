"""Idempotent auto-seeding of database tables from verified on-disk snapshots."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from football_core.domain import redact_secrets
from football_core.persistence.engine import ensure_schema, get_engine, is_database_configured
from football_core.persistence.schema import match_records

logger = logging.getLogger(__name__)


def is_match_records_empty() -> bool:
    """Check if match_records table contains zero rows."""
    engine = get_engine()
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(match_records)).scalar()
            return count == 0
    except Exception as exc:
        logger.warning("Failed to count match_records: %s", redact_secrets(str(exc)))
        return False


def seed_competition_matches(
    competition: str,
    season: str,
    json_path: Path,
) -> int:
    """Seed match records from an on-disk JSON store using ON CONFLICT DO NOTHING."""
    if not json_path.exists():
        return 0

    engine = get_engine()
    if engine is None:
        return 0

    try:
        raw_data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read seed file %s: %s", json_path, exc)
        return 0

    matches_dict = raw_data if isinstance(raw_data, dict) else {}
    if not matches_dict:
        return 0

    insert_fn = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    inserted = 0

    with engine.begin() as conn:
        for match_id, payload in matches_dict.items():
            if not isinstance(payload, dict):
                continue
            row = {
                "competition": competition,
                "season": season,
                "match_id": str(match_id),
                "status": payload.get("status", "played"),
                "event_date": None,
                "payload": payload,
            }
            stmt = insert_fn(match_records).values(row).on_conflict_do_nothing()
            result = conn.execute(stmt)
            if result.rowcount > 0:
                inserted += 1

    return inserted


def auto_seed_if_empty(base_dir: Path | None = None) -> bool:
    """Auto-seed verified on-disk facts into an empty database."""
    if not is_database_configured():
        return False

    if not ensure_schema():
        logger.warning("Cannot auto-seed: schema initialization failed")
        return False

    if not is_match_records_empty():
        logger.info("Database match_records already populated; skipping auto-seed")
        return False

    logger.info("Empty database detected; starting non-destructive auto-seed from on-disk facts...")
    root = base_dir or Path(__file__).resolve().parents[2]

    seeds = [
        ("worldcup", "2026", root / "competitions" / "worldcup" / "data" / "played.json"),
        ("ucl", "2024-2025", root / "competitions" / "ucl" / "data" / "played.json"),
        ("laliga", "2024-2025", root / "competitions" / "laliga" / "data" / "played.json"),
    ]

    total_seeded = 0
    for comp, season, path in seeds:
        count = seed_competition_matches(comp, season, path)
        total_seeded += count
        logger.info("Seeded %d matches for %s (%s)", count, comp, season)

    logger.info("Auto-seed complete: %d total matches ingested into Postgres", total_seeded)
    return True
