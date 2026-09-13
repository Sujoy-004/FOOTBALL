"""Exchange 9C — competition API cache-control regression tests.

Root cause (Phase 9B): an open UCL tab could keep serving a stale,
browser-cached JSON response forever because the competition API shipped no
cache-control opt-out. These tests pin the fix: every competition API
response carries ``Cache-Control: no-store``. They also pin the invariants
around it — static assets keep their stricter header, the landing page stays
outside the policy, and the simulation endpoint (an idempotent read that
never recomputes server state) is both covered and repeatable.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.cache_control import competition_api_prefixes


@pytest.fixture(autouse=True)
def snapshot_mode(monkeypatch):
    """Pin every app boot here to snapshot (zero network)."""
    import web.startup as startup

    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield
    startup._last_decision = None


@pytest.fixture
def client():
    # The cache policy lives on web.server.asgi_app (the composed, actually
    # served app: static no-cache + competition no-store). Hitting the raw
    # FastAPI `app` would bypass the middleware chain entirely.
    from web.server import asgi_app as server_asgi

    with TestClient(server_asgi) as c:
        yield c


# ── Policy derivation ─────────────────────────────────────────────────

def test_api_prefixes_derived_from_registry():
    prefixes = competition_api_prefixes()
    assert "/worldcup/api" in prefixes
    assert "/ucl/api" in prefixes


# ── Competition API responses are no-store ────────────────────────────

def test_no_store_on_ucl_data(client):
    r = client.get("/ucl/api/data")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


def test_no_store_on_ucl_bracket(client):
    r = client.get("/ucl/api/bracket")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


def test_no_store_on_worldcup_data(client):
    r = client.get("/worldcup/api/data")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


def test_no_store_on_worldcup_overview(client):
    r = client.get("/worldcup/api/overview")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


# ── Simulation endpoint: no-store AND idempotent ──────────────────────

def test_simulation_read_is_no_store_and_idempotent(client):
    a = client.get("/ucl/api/simulation")
    b = client.get("/ucl/api/simulation")
    assert a.status_code == 200
    assert a.headers.get("cache-control") == "no-store"
    assert a.json() == b.json(), "repeatable read must return identical data"
    assert b.headers.get("cache-control") == "no-store"


# ── Non-competition responses keep prior behavior ─────────────────────

def test_static_assets_keep_no_cache_header(client):
    r = client.get("/static/shared.js")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache, no-store, must-revalidate"


def test_landing_page_not_marked_no_store(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("cache-control") != "no-store"