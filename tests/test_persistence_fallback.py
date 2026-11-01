"""Resilience, repository adapter, and fallback tests for persistence layer."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from sqlalchemy import select, text

from football_core.persistence.engine import get_engine, reset_engine
from football_core.persistence.repository import (
    append_retirement_records,
    load_competition_state,
    load_played_matches,
    save_competition_state,
    save_played_matches,
)
from football_core.persistence.schema import competition_states, match_records, metadata, retirement_records


@pytest.fixture(autouse=True)
def cleanup():
    reset_engine()
    yield
    reset_engine()


# ============================================================================
# Repository Tests: Offline JSON Fallback (DATABASE_URL unset)
# ============================================================================


def test_repository_save_played_matches_fallback_to_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is unset, save_played_matches writes to local played.json."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    matches = {
        "m01": {"match_id": "m01", "home": "Spain", "away": "Brazil", "score": [2, 1], "status": "played"}
    }
    save_played_matches("worldcup", "2026", matches, data_dir=tmp_path)

    json_file = tmp_path / "played.json"
    assert json_file.exists()
    loaded = json.loads(json_file.read_text(encoding="utf-8"))
    assert loaded == matches
    assert get_engine() is None


def test_repository_load_played_matches_fallback_to_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is unset, load_played_matches reads from local played.json."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    matches = {
        "m02": {"match_id": "m02", "home": "France", "away": "Germany", "score": [1, 1], "status": "played"}
    }
    json_file = tmp_path / "played.json"
    json_file.write_text(json.dumps(matches), encoding="utf-8")

    result = load_played_matches("worldcup", "2026", data_dir=tmp_path)
    assert result == matches
    assert get_engine() is None


def test_repository_state_and_retirement_no_ops_when_unset(monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is unset, state and retirement operations are safe no-ops."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Save state -> no error, no engine initialized
    save_competition_state("worldcup", "2026", "results", {"standings": []})
    assert load_competition_state("worldcup", "2026") is None

    # Append retirement -> no error
    append_retirement_records("worldcup", [{"match_id": "m01", "reason": "real_match_arrived"}])
    assert get_engine() is None


# ============================================================================
# Repository Tests: SQLite-backed SQL Upserts and Roundtrip
# ============================================================================


def test_repository_save_and_load_played_matches_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is configured, matches are upserted to database and loaded correctly."""
    db_file = tmp_path / "test_repo.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    matches_v1 = {
        "m01": {
            "match_id": "m01",
            "home": "Spain",
            "away": "Brazil",
            "score": [1, 0],
            "status": "played",
            "event_date": "2026-06-15T18:00:00Z",
        }
    }
    save_played_matches("worldcup", "2026", matches_v1, data_dir=tmp_path)

    # Assert matches loaded from DB
    loaded = load_played_matches("worldcup", "2026", data_dir=tmp_path)
    assert loaded == matches_v1

    # Verify on_conflict_do_update works on upsert
    matches_v2 = {
        "m01": {
            "match_id": "m01",
            "home": "Spain",
            "away": "Brazil",
            "score": [2, 1],  # score correction
            "status": "played",
            "event_date": "2026-06-15T18:00:00Z",
        },
        "m02": {
            "match_id": "m02",
            "home": "France",
            "away": "Germany",
            "score": [0, 0],
            "status": "played",
        },
    }
    save_played_matches("worldcup", "2026", matches_v2, data_dir=tmp_path)

    loaded_v2 = load_played_matches("worldcup", "2026", data_dir=tmp_path)
    assert len(loaded_v2) == 2
    assert loaded_v2["m01"]["score"] == [2, 1]
    assert loaded_v2["m02"]["home"] == "France"


def test_repository_save_and_load_competition_state_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify saving and loading competition state snapshots in database."""
    db_file = tmp_path / "test_repo_state.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    state_v1 = {"champion": "Spain", "stages": {"final": {"winner": "Spain"}}}
    save_competition_state("worldcup", "2026", "results", state_v1)

    loaded = load_competition_state("worldcup", "2026")
    assert loaded == state_v1

    # Test updating existing state
    state_v2 = {"champion": "Brazil", "stages": {"final": {"winner": "Brazil"}}}
    save_competition_state("worldcup", "2026", "results", state_v2)

    loaded_v2 = load_competition_state("worldcup", "2026")
    assert loaded_v2 == state_v2

    # Querying non-existent season returns None
    assert load_competition_state("worldcup", "2030") is None


def test_repository_append_retirement_records_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify appending retirement records in database with on_conflict_do_nothing."""
    db_file = tmp_path / "test_repo_retirements.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    records = [
        {"record_id": "ret_01", "match_id": "m01", "reason": "real_match_arrived", "retired_at": "2026-06-15T20:00:00Z"},
        {"record_id": "ret_02", "match_id": "m02", "reason": "store_replaced"},
    ]
    append_retirement_records("ucl", records)

    engine = get_engine()
    assert engine is not None
    with engine.connect() as conn:
        rows = conn.execute(
            select(retirement_records.c.record_id, retirement_records.c.retired_match).where(
                retirement_records.c.competition == "ucl"
            )
        ).fetchall()
        assert len(rows) == 2
        record_ids = {r[0] for r in rows}
        assert record_ids == {"ret_01", "ret_02"}

    # Idempotent: re-appending the same records does not raise primary key error
    append_retirement_records("ucl", records)
    with engine.connect() as conn:
        count = conn.execute(select(retirement_records)).fetchall()
        assert len(count) == 2


def test_repository_load_played_matches_graceful_fallback_on_db_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When database query fails unexpectedly, load_played_matches gracefully falls back to local disk."""
    db_file = tmp_path / "test_repo_err.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    # Prepare local disk fallback
    fallback_matches = {"m_fallback": {"match_id": "m_fallback", "status": "played"}}
    json_file = tmp_path / "played.json"
    json_file.write_text(json.dumps(fallback_matches), encoding="utf-8")

    engine = get_engine()
    assert engine is not None

    # Corrupt or drop the table to simulate DB error
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS match_records"))

    # Loading should catch the exception, log it, and return on-disk matches
    loaded = load_played_matches("worldcup", "2026", data_dir=tmp_path)
    assert loaded == fallback_matches
