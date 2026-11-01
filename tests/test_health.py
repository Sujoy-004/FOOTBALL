"""Tests for /health readiness and keep-awake probe."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from web.server import app


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
