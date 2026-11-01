"""Public persistence package exports."""

from __future__ import annotations

from football_core.persistence.engine import (
    check_db_health,
    ensure_schema,
    get_database_url,
    get_engine,
    init_db,
    is_database_configured,
    reset_engine,
)
from football_core.persistence.normalizer import normalize_database_url
from football_core.persistence.repository import (
    append_retirement_records,
    load_competition_state,
    load_played_matches,
    save_competition_state,
    save_played_matches,
)
from football_core.persistence.schema import (
    JSONType,
    competition_states,
    match_records,
    metadata,
    retirement_records,
)
from football_core.persistence.seeder import auto_seed_if_empty

__all__ = [
    "JSONType",
    "append_retirement_records",
    "auto_seed_if_empty",
    "check_db_health",
    "competition_states",
    "ensure_schema",
    "get_database_url",
    "get_engine",
    "init_db",
    "is_database_configured",
    "load_competition_state",
    "load_played_matches",
    "match_records",
    "metadata",
    "normalize_database_url",
    "reset_engine",
    "retirement_records",
    "save_competition_state",
    "save_played_matches",
]
