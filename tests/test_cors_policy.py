"""Tests for CORS policy configuration on root and mounted sub-apps.

Covers SEC-03:
- Origin whitelist permitting localhost and 127.0.0.1
- Cloudflare Pages regex matching (*.pages.dev and preview subdomains)
- Disallowed origins rejected (no access-control-allow-origin header)
- Custom ALLOWED_ORIGINS environment variable parsing
- Permitted HTTP methods and headers (including X-Admin-Key)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient
import pytest

from web.server import app, asgi_app
from web.security import get_allowed_origins


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_cors_preflight_localhost_whitelisted(client):
    headers = {
        "Origin": "http://localhost:8080",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-Admin-Key, Content-Type",
    }
    response = client.options("/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8080"
    assert "X-Admin-Key" in response.headers.get("access-control-allow-headers", "")
    assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_cors_simple_get_localhost(client):
    headers = {"Origin": "http://127.0.0.1:8080"}
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:8080"


def test_cors_cloudflare_pages_regex_matching(client):
    # Production Cloudflare Pages apex domain
    resp1 = client.get("/health", headers={"Origin": "https://football-frontend.pages.dev"})
    assert resp1.status_code == 200
    assert resp1.headers.get("access-control-allow-origin") == "https://football-frontend.pages.dev"

    # Branch preview subdomain on Cloudflare Pages
    resp2 = client.get("/health", headers={"Origin": "https://preview-12.football-frontend.pages.dev"})
    assert resp2.status_code == 200
    assert resp2.headers.get("access-control-allow-origin") == "https://preview-12.football-frontend.pages.dev"


def test_cors_unauthorized_origin_rejected(client):
    headers = {"Origin": "https://malicious-attacker.com"}
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    # Unauthorized origins must not receive access-control-allow-origin
    assert "access-control-allow-origin" not in response.headers

    # Preflight should also not allow unauthorized origin
    preflight = client.options(
        "/health",
        headers={
            "Origin": "https://malicious-attacker.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_cors_subapp_endpoints_protected(client):
    # Mounted sub-apps receive CORS protection from the root middleware stack
    headers = {"Origin": "https://football-staging.pages.dev"}
    for path in ("/worldcup/api/data", "/ucl/api/data", "/laliga/api/data"):
        resp = client.get(path, headers=headers)
        assert resp.headers.get("access-control-allow-origin") == "https://football-staging.pages.dev"


def test_get_allowed_origins_env_parsing(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://football.org, https://preview.football.org, http://localhost:8080")
    origins = get_allowed_origins()
    assert "https://football.org" in origins
    assert "https://preview.football.org" in origins
    assert "http://localhost:8080" in origins
    assert "http://localhost:3000" in origins
    # Ensure no duplicates
    assert origins.count("http://localhost:8080") == 1


def test_cors_custom_origin_middleware():
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://custom-domain.com"],
        allow_origin_regex=r"^https://.*\.pages\.dev$",
        allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
        allow_headers=["Content-Type", "Authorization", "X-Admin-Key"],
        allow_credentials=True,
    )

    @test_app.get("/test")
    def sample():
        return {"ok": True}

    client = TestClient(test_app)
    resp = client.get("/test", headers={"Origin": "https://custom-domain.com"})
    assert resp.headers.get("access-control-allow-origin") == "https://custom-domain.com"
