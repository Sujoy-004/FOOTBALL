"""Resilience, repository adapter, and fallback tests for persistence layer."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import pytest
from sqlalchemy import select, text
from starlette.testclient import TestClient

from football_core.persistence.engine import check_db_health, ensure_schema, get_engine, reset_engine
from football_core.persistence.repository import (
    append_retirement_records,
    load_competition_state,
    load_played_matches,
    save_competition_state,
    save_played_matches,
)
from football_core.persistence.schema import competition_states, match_records, metadata, retirement_records
from football_core.persistence.seeder import auto_seed_if_empty, is_match_records_empty, seed_competition_matches
from web.health import register_db_checker
from web.server import app


@pytest.fixture(autouse=True)
def cleanup():
    reset_engine()
    register_db_checker(None)
    yield
    reset_engine()
    register_db_checker(None)


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


# ============================================================================
# Auto-Seeder Tests (PERS-01, D-07)
# ============================================================================


def test_auto_seed_populates_empty_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When match_records is empty, auto_seed_if_empty populates records from disk snapshots."""
    db_file = tmp_path / "test_auto_seed.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    fake_root = tmp_path / "repo"
    wc_data = fake_root / "competitions" / "worldcup" / "data"
    wc_data.mkdir(parents=True, exist_ok=True)
    wc_matches = {
        "m_wc_01": {"match_id": "m_wc_01", "home": "Spain", "away": "Brazil", "score": [2, 1], "status": "played"},
        "m_wc_02": {"match_id": "m_wc_02", "home": "Germany", "away": "Italy", "score": [1, 0], "status": "played"},
    }
    (wc_data / "played.json").write_text(json.dumps(wc_matches), encoding="utf-8")

    ucl_data = fake_root / "competitions" / "ucl" / "data"
    ucl_data.mkdir(parents=True, exist_ok=True)
    ucl_matches = {
        "m_ucl_01": {"match_id": "m_ucl_01", "home": "Real Madrid", "away": "Milan", "score": [3, 1], "status": "played"}
    }
    (ucl_data / "played.json").write_text(json.dumps(ucl_matches), encoding="utf-8")

    assert ensure_schema() is True
    assert is_match_records_empty() is True

    seeded = auto_seed_if_empty(base_dir=fake_root)
    assert seeded is True
    assert is_match_records_empty() is False

    engine = get_engine()
    assert engine is not None
    with engine.connect() as conn:
        rows = conn.execute(select(match_records.c.competition, match_records.c.match_id)).fetchall()
        assert len(rows) == 3
        match_ids = {r[1] for r in rows}
        assert match_ids == {"m_wc_01", "m_wc_02", "m_ucl_01"}


def test_auto_seed_skips_non_empty_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When match_records already contains rows, auto_seed_if_empty skips seeding immediately."""
    db_file = tmp_path / "test_auto_seed_skip.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    fake_root = tmp_path / "repo"
    wc_data = fake_root / "competitions" / "worldcup" / "data"
    wc_data.mkdir(parents=True, exist_ok=True)
    (wc_data / "played.json").write_text(
        json.dumps({"m_new": {"match_id": "m_new", "status": "played"}}),
        encoding="utf-8",
    )

    # Insert 1 pre-existing row into match_records
    save_played_matches(
        "worldcup",
        "2026",
        {"m_existing": {"match_id": "m_existing", "status": "played"}},
    )
    assert is_match_records_empty() is False

    # Auto seed should detect non-empty table and return False without modifying rows
    seeded = auto_seed_if_empty(base_dir=fake_root)
    assert seeded is False

    engine = get_engine()
    assert engine is not None
    with engine.connect() as conn:
        rows = conn.execute(select(match_records.c.match_id)).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "m_existing"


def test_auto_seed_idempotent_on_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Calling seed_competition_matches multiple times uses ON CONFLICT DO NOTHING without error."""
    db_file = tmp_path / "test_seed_idempotent.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    json_path = tmp_path / "played.json"
    matches = {
        "m01": {"match_id": "m01", "home": "Spain", "away": "Brazil", "score": [2, 1], "status": "played"}
    }
    json_path.write_text(json.dumps(matches), encoding="utf-8")

    assert ensure_schema() is True

    # First seed inserts 1 row
    first_count = seed_competition_matches("worldcup", "2026", json_path)
    assert first_count == 1

    # Second seed on same data inserts 0 rows (ON CONFLICT DO NOTHING)
    second_count = seed_competition_matches("worldcup", "2026", json_path)
    assert second_count == 0

    engine = get_engine()
    assert engine is not None
    with engine.connect() as conn:
        rows = conn.execute(select(match_records)).fetchall()
        assert len(rows) == 1


def test_auto_seed_skips_when_database_unconfigured(monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is unset, auto_seed_if_empty returns False immediately."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert auto_seed_if_empty() is False


# ============================================================================
# Health Check & Resilience Tests (PERS-03, D-08, T-09-06)
# ============================================================================


def test_health_reports_fallback_json_when_url_unset(monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is unset, /health reports database: fallback_json and HTTP 200."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    register_db_checker(check_db_health)

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["database"] == "fallback_json"
        assert payload["status"] == "ok"


def test_health_reports_sqlite_when_sqlite_url_set(monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is configured with SQLite, /health reports database: sqlite and HTTP 200."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    register_db_checker(check_db_health)

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["database"] == "sqlite"
        assert payload["status"] == "ok"


def test_health_reports_503_when_configured_database_unreachable(monkeypatch: pytest.MonkeyPatch):
    """When DATABASE_URL is set but unreachable, /health degrades to HTTP 503 and status unhealthy."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://baduser:badpass@127.0.0.1:59999/baddb")
    register_db_checker(check_db_health)

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 503
        payload = resp.json()
        assert payload["database"] == "postgres"
        assert payload["status"] == "unhealthy"


def test_secrets_redacted_in_database_error_logs(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    """Trigger connection failure with password in DATABASE_URL and assert password is not leaked in log records."""
    secret_pass = "super_secret_neon_password_xyz987"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://neonuser:{secret_pass}@127.0.0.1:59999/neondb")
    reset_engine()

    with caplog.at_level("ERROR"):
        status_label, is_healthy = check_db_health()

    assert is_healthy is False
    assert status_label == "postgres"
    captured_logs = caplog.text
    assert secret_pass not in captured_logs
    assert "[REDACTED]" in captured_logs or "59999" in captured_logs


def test_zero_network_at_import_time(monkeypatch: pytest.MonkeyPatch):
    """Verify that importing any persistence module never initiates network socket connections."""
    import socket

    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Network socket initiated during persistence import!")

    monkeypatch.setattr(socket, "socket", forbidden_socket)

    modules_to_test = [
        "football_core.persistence",
        "football_core.persistence.normalizer",
        "football_core.persistence.engine",
        "football_core.persistence.schema",
        "football_core.persistence.repository",
        "football_core.persistence.seeder",
    ]
    for mod_name in modules_to_test:
        importlib.import_module(mod_name)


