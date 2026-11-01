"""Tests for /health readiness and keep-awake probe."""

from __future__ import annotations

import time
import pytest
from starlette.testclient import TestClient
from web.derived import holder
from web.health import register_db_checker, health_check
from web.server import app


@pytest.fixture(autouse=True)
def clean_db_checker():
    """Ensure DB checker is reset between tests."""
    register_db_checker(None)
    yield
    register_db_checker(None)


def test_health_tracer_e2e():
    """Verify that GET /health responds with HTTP 200 and expected schema on root app."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert isinstance(payload["uptime_seconds"], (int, float))
        assert "timestamp" in payload
        assert payload["database"] == "fallback_json"
        assert "competitions" in payload
        assert isinstance(payload["competitions"], dict)
        for comp_id in ("worldcup", "ucl", "laliga"):
            assert comp_id in payload["competitions"]
            comp_info = payload["competitions"][comp_id]
            assert comp_info["status"] in ("available", "uninitialized")
            assert "mode" in comp_info
            assert "stamp" in comp_info


def test_health_success():
    """Verify healthy 200 response with all competition cache stamps present."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["database"] == "fallback_json"
        assert payload["uptime_seconds"] >= 0
        assert "timestamp" in payload

        competitions = payload["competitions"]
        for comp_id in ("worldcup", "ucl", "laliga"):
            assert comp_id in competitions
            comp_data = competitions[comp_id]
            assert comp_data["status"] == "available"
            assert comp_data["stamp"] is not None
            assert isinstance(comp_data["stamp"], dict)


def test_health_503_on_competition_failure():
    """Verify that a competition store failure degrades readiness to HTTP 503."""
    with TestClient(app) as client:
        orig_state = holder._STATES.get("worldcup")
        try:
            holder.publish_data(
                "worldcup",
                {
                    "competition": "worldcup",
                    "mode": "unavailable",
                    "availability": "UNAVAILABLE",
                    "error": "boot computation failed",
                },
                "unavailable",
                None,
            )
            response = client.get("/health")
            assert response.status_code == 503
            payload = response.json()
            assert payload["status"] == "unhealthy"
            assert payload["competitions"]["worldcup"]["status"] == "unavailable"
        finally:
            if orig_state is not None:
                holder._STATES["worldcup"] = orig_state

        # Verify recovery back to healthy
        recovered = client.get("/health")
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "ok"


def test_health_503_on_db_failure():
    """Verify that a failing database check degrades readiness to HTTP 503."""
    with TestClient(app) as client:
        register_db_checker(lambda: ("disconnected", False))
        response = client.get("/health")
        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "unhealthy"
        assert payload["database"] == "disconnected"

        # Verify dynamic recovery when DB reports healthy
        register_db_checker(lambda: ("connected", True))
        recovered = client.get("/health")
        assert recovered.status_code == 200
        recovered_payload = recovered.json()
        assert recovered_payload["status"] == "ok"
        assert recovered_payload["database"] == "connected"


def test_health_performance():
    """Verify in-memory probe responds in <15ms without disk I/O."""
    from fastapi import Response

    # Direct handler call performance: 10 calls well within 15ms total (<1ms)
    resp = Response()
    t0 = time.perf_counter()
    for _ in range(10):
        health_check(resp)
    direct_latency_ms = (time.perf_counter() - t0) * 1000
    assert direct_latency_ms < 15.0, f"10 direct calls took {direct_latency_ms:.2f}ms"

    # End-to-end client latency per request < 15ms
    with TestClient(app) as client:
        client.get("/health")  # warmup
        for _ in range(10):
            req_start = time.perf_counter()
            response = client.get("/health")
            req_latency_ms = (time.perf_counter() - req_start) * 1000
            assert response.status_code == 200
            assert req_latency_ms < 15.0, f"Request latency {req_latency_ms:.2f}ms exceeded 15ms threshold"


def test_health_payload_sanitization(monkeypatch):
    """Verify zero secrets, passwords, connection strings, or system paths in payload."""
    secret_url = "postgresql://dbuser:super_secret_pw@db.render.internal:5432/proddb"
    monkeypatch.setenv("DATABASE_URL", secret_url)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "fdo_secret_api_key_xyz987")
    monkeypatch.setenv("THE_ODDS_API_KEY", "odds_secret_api_key_abc123")
    monkeypatch.setenv("ADMIN_KEY", "admin_super_secret_token")

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        raw_text = response.text

        # Verify sensitive credentials not present
        assert "super_secret_pw" not in raw_text
        assert "postgresql://" not in raw_text
        assert "dbuser" not in raw_text
        assert "fdo_secret_api_key" not in raw_text
        assert "odds_secret_api_key" not in raw_text
        assert "admin_super_secret_token" not in raw_text
        assert "password" not in raw_text.lower()
        assert "token" not in raw_text.lower()
        assert "secret" not in raw_text.lower()

        # Verify no file paths or stack traces leaked
        assert "C:\\" not in raw_text
        assert "/Users/" not in raw_text
        assert "Traceback" not in raw_text
