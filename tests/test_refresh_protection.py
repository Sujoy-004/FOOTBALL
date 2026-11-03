"""Tests for manual refresh protection in production mode (SEC-05).

Verifies:
- In development/non-production, manual refresh endpoints are open (HTTP 200).
- In production (ENVIRONMENT=production or RENDER=true), unauthenticated requests return HTTP 403 Forbidden.
- In production, requests with valid ADMIN_KEY via header or query param succeed (HTTP 200).
- Direct Python function invocations of api_refresh() without arguments succeed without TypeError.
"""

from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from web import laliga_app, ucl_app, wc_app
from web.server import app

COMPETITIONS = [
    ("worldcup", wc_app, "/worldcup/api/refresh"),
    ("ucl", ucl_app, "/ucl/api/refresh"),
    ("laliga", laliga_app, "/laliga/api/refresh"),
]


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("comp_id,app_mod,endpoint", COMPETITIONS)
def test_refresh_dev_mode_allowed(client, monkeypatch, comp_id, app_mod, endpoint):
    """In non-production, unauthenticated refresh is allowed."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ADMIN_KEY", raising=False)

    fake_report = {"attempted": False, "success": True, "error": None}
    with patch("web.competitions.REGISTRY.get") as mock_get:
        mock_adapter = MagicMock()
        mock_adapter.refresh.return_value = fake_report
        mock_get.return_value = mock_adapter

        response = client.post(endpoint)

    assert response.status_code == 200


@pytest.mark.parametrize("comp_id,app_mod,endpoint", COMPETITIONS)
def test_refresh_production_mode_forbidden(client, monkeypatch, comp_id, app_mod, endpoint):
    """In production, unauthenticated refresh returns 403 Forbidden with explanation."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_KEY", "prod-secret-999")

    response = client.post(endpoint)
    assert response.status_code == 403
    detail = response.json().get("detail", "").lower()
    assert "manual refresh is disabled in production" in detail
    assert "protect api quotas" in detail


@pytest.mark.parametrize("comp_id,app_mod,endpoint", COMPETITIONS)
def test_refresh_production_mode_with_admin_header(client, monkeypatch, comp_id, app_mod, endpoint):
    """In production, providing valid X-Admin-Key permits manual refresh."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_KEY", "prod-secret-999")

    fake_report = {"attempted": False, "success": True, "error": None}
    with patch("web.competitions.REGISTRY.get") as mock_get:
        mock_adapter = MagicMock()
        mock_adapter.refresh.return_value = fake_report
        mock_get.return_value = mock_adapter

        response = client.post(endpoint, headers={"X-Admin-Key": "prod-secret-999"})

    assert response.status_code == 200


@pytest.mark.parametrize("comp_id,app_mod,endpoint", COMPETITIONS)
def test_refresh_production_mode_with_admin_query(client, monkeypatch, comp_id, app_mod, endpoint):
    """In production, providing valid ?admin_key= query parameter permits manual refresh."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("ADMIN_KEY", "prod-secret-999")

    fake_report = {"attempted": False, "success": True, "error": None}
    with patch("web.competitions.REGISTRY.get") as mock_get:
        mock_adapter = MagicMock()
        mock_adapter.refresh.return_value = fake_report
        mock_get.return_value = mock_adapter

        response = client.post(f"{endpoint}?admin_key=prod-secret-999")

    assert response.status_code == 200


@pytest.mark.parametrize("comp_id,app_mod,_", COMPETITIONS)
def test_direct_python_invocation_without_arguments(monkeypatch, comp_id, app_mod, _):
    """Calling api_refresh() directly in Python without arguments must not raise TypeError."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)

    fake_report = {"attempted": False, "success": True, "error": None}
    with patch("web.competitions.REGISTRY.get") as mock_get:
        mock_adapter = MagicMock()
        mock_adapter.refresh.return_value = fake_report
        mock_get.return_value = mock_adapter

        res = app_mod.api_refresh()

    assert res.status_code == 200
