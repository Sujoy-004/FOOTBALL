"""Tests for authenticated POST /api/admin/sync endpoint and token verification.

Covers SEC-04 & SEC-05:
- Production gating (ENVIRONMENT=production, RENDER=true)
- Constant-time token verification (hmac.compare_digest)
- X-Admin-Key header and ?admin_key= query parameter support
- Non-production convenience mode with unset ADMIN_KEY
- Mutex lock contention returning HTTP 409 Conflict
"""

import hmac
import os
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from web.server import app


@pytest.fixture
def client():
    # Use TestClient with lifespan disabled for focused routing tests, or standard client
    return TestClient(app, raise_server_exceptions=False)


def test_admin_sync_production_missing_key(client, monkeypatch):
    """In production, missing admin key returns 403 Forbidden."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_KEY", "super-secret-12345")

    response = client.post("/api/admin/sync")
    assert response.status_code == 403
    assert "admin key" in response.json().get("detail", "").lower()


def test_admin_sync_production_invalid_key(client, monkeypatch):
    """In production, invalid admin key returns 403 Forbidden."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_KEY", "super-secret-12345")

    response = client.post("/api/admin/sync", headers={"X-Admin-Key": "wrong-key"})
    assert response.status_code == 403

    response_query = client.post("/api/admin/sync?admin_key=wrong-key")
    assert response_query.status_code == 403


def test_admin_sync_production_valid_key_header(client, monkeypatch):
    """In production, matching X-Admin-Key header executes sync and returns 200."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_KEY", "super-secret-12345")

    fake_report = {
        "status": "completed",
        "elapsed_seconds": 0.5,
        "timestamp": 123456789.0,
        "results": {"worldcup": {"attempted": True, "success": True, "error": None}},
    }

    with patch("web.sync_worker.sync_worker.run_sync_all", new_callable=AsyncMock) as mock_sync:
        mock_sync.return_value = fake_report
        response = client.post("/api/admin/sync", headers={"X-Admin-Key": "super-secret-12345"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    mock_sync.assert_awaited_once_with(force=True)


def test_admin_sync_production_valid_key_query(client, monkeypatch):
    """In production, matching ?admin_key= query parameter executes sync and returns 200."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("ADMIN_KEY", "super-secret-12345")

    fake_report = {
        "status": "completed",
        "elapsed_seconds": 0.2,
        "timestamp": 123456789.0,
        "results": {},
    }

    with patch("web.sync_worker.sync_worker.run_sync_all", new_callable=AsyncMock) as mock_sync:
        mock_sync.return_value = fake_report
        response = client.post("/api/admin/sync?admin_key=super-secret-12345")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_admin_sync_constant_time_comparison(client, monkeypatch):
    """Admin key verification must call hmac.compare_digest to prevent timing attacks."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_KEY", "test-key-abc")

    with patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_compare, \
         patch("web.sync_worker.sync_worker.run_sync_all", new_callable=AsyncMock):
        client.post("/api/admin/sync", headers={"X-Admin-Key": "test-key-abc"})
        mock_compare.assert_called_with("test-key-abc", "test-key-abc")


def test_admin_sync_non_production_unset_key(client, monkeypatch, caplog):
    """In non-production with unset ADMIN_KEY, sync is permitted with warning."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ADMIN_KEY", raising=False)

    fake_report = {"status": "completed", "results": {}}

    with patch("web.sync_worker.sync_worker.run_sync_all", new_callable=AsyncMock) as mock_sync:
        mock_sync.return_value = fake_report
        response = client.post("/api/admin/sync")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert "Admin sync called without configured ADMIN_KEY in non-production mode" in caplog.text


def test_admin_sync_conflict_when_locked(client, monkeypatch):
    """Calling /api/admin/sync while sync is running returns HTTP 409 Conflict."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ADMIN_KEY", raising=False)

    with patch("web.sync_worker.sync_worker._lock.locked", return_value=True):
        response = client.post("/api/admin/sync")

    assert response.status_code == 409
    assert "already in progress" in response.json().get("detail", "").lower()
