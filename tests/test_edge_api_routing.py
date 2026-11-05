"""Tests for dynamic client API routing adapter and CORS compatibility.

Covers Task 1 / EDGE-02:
- getApiBaseUrl() behavior with and without window.__APP_CONFIG__.API_URL
- resolveApiUrl() path normalization without double slashes or double /api
- safeJson() error formatting and URL prepending
- FastAPI server CORS middleware authorizing Cloudflare Pages (*.pages.dev)
- Rejection of unauthorized origins
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from web.server import app

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web" / "static"
API_JS = STATIC_DIR / "api.js"
CONFIG_JS = STATIC_DIR / "config.js"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_config_and_api_js_exist():
    """Verify config.js and api.js are present in web/static."""
    assert CONFIG_JS.exists(), "web/static/config.js must exist"
    assert API_JS.exists(), "web/static/api.js must exist"
    
    config_text = CONFIG_JS.read_text(encoding="utf-8")
    assert "window.__APP_CONFIG__" in config_text
    assert "API_URL" in config_text


def test_js_api_adapter_node_execution():
    """Directly test web/static/api.js using Node.js to verify browser runtime semantics."""
    node_test_script = """
    import { getApiBaseUrl, resolveApiUrl, safeJson } from './web/static/api.js';
    import assert from 'node:assert';

    // 1. Local dev fallback: window.__APP_CONFIG__ not defined or API_URL empty
    globalThis.window = { __APP_CONFIG__: { API_URL: '' } };
    assert.strictEqual(getApiBaseUrl(), '');
    assert.strictEqual(resolveApiUrl('/worldcup/api/data'), '/worldcup/api/data');
    assert.strictEqual(resolveApiUrl('worldcup/api/data'), 'worldcup/api/data');
    assert.strictEqual(resolveApiUrl('https://other.com/api'), 'https://other.com/api');

    // 2. Production config: API_URL set with trailing slash
    globalThis.window.__APP_CONFIG__.API_URL = 'https://football-api.onrender.com/';
    assert.strictEqual(getApiBaseUrl(), 'https://football-api.onrender.com');

    // 3. Normalization without duplicate slashes or double /api
    assert.strictEqual(
      resolveApiUrl('/worldcup/api/data'),
      'https://football-api.onrender.com/worldcup/api/data'
    );
    assert.strictEqual(
      resolveApiUrl('ucl/api/simulation'),
      'https://football-api.onrender.com/ucl/api/simulation'
    );
    assert.strictEqual(
      resolveApiUrl('https://already-absolute.com/api'),
      'https://already-absolute.com/api'
    );

    // 4. safeJson error formatting
    globalThis.fetch = async (url) => ({
      ok: false,
      status: 502,
      text: async () => 'Bad Gateway upstream timeout'
    });

    try {
      await safeJson('/laliga/api/data');
      assert.fail('safeJson should have thrown');
    } catch (err) {
      assert.ok(err.message.includes('[502]'));
      assert.ok(err.message.includes('https://football-api.onrender.com/laliga/api/data'));
      assert.ok(err.message.includes('Bad Gateway'));
    }

    // 5. safeJson non-JSON handling
    globalThis.fetch = async (url) => ({
      ok: true,
      status: 200,
      text: async () => '<html><body>Not JSON</body></html>'
    });

    try {
      await safeJson('/laliga/api/data');
      assert.fail('safeJson should have thrown on non-JSON');
    } catch (err) {
      assert.ok(err.message.includes('non-JSON response'));
    }

    // 6. safeJson success
    globalThis.fetch = async (url) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ status: 'ok', count: 42 })
    });

    const data = await safeJson('/laliga/api/data');
    assert.strictEqual(data.count, 42);

    console.log('NODE_OK');
    """

    res = subprocess.run(
        ["node", "--input-type=module", "-e", node_test_script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node tests failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    assert "NODE_OK" in res.stdout


def test_cors_cloudflare_pages_apex(client):
    """FastAPI CORS headers permit direct cross-origin requests from Cloudflare Pages apex."""
    headers = {"Origin": "https://football-edge.pages.dev"}
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://football-edge.pages.dev"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_cloudflare_pages_preview_subdomain(client):
    """FastAPI CORS headers permit direct requests from preview branch subdomains on Pages."""
    headers = {"Origin": "https://feat-new-theme.football-edge.pages.dev"}
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://feat-new-theme.football-edge.pages.dev"


def test_cors_unauthorized_third_party_rejected(client):
    """Unauthorized third-party origins are rejected by CORS headers."""
    headers = {"Origin": "https://unauthorized-attacker.com"}
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_direct_tournament_api_endpoints(client):
    """Tournament API endpoints allow direct CORS from Cloudflare Pages."""
    headers = {"Origin": "https://football-app.pages.dev"}
    endpoints = [
        "/worldcup/api/data",
        "/ucl/api/data",
        "/laliga/api/data",
    ]
    for ep in endpoints:
        resp = client.get(ep, headers=headers)
        assert resp.status_code in (200, 503)
        assert resp.headers.get("access-control-allow-origin") == "https://football-app.pages.dev"


def test_zero_bare_unrouted_api_calls_in_js_modules():
    """Verify that every fetch call in tournament JS modules resolves through resolveApiUrl."""
    js_files = [
        STATIC_DIR / "wc.js",
        STATIC_DIR / "ucl.js",
        STATIC_DIR / "laliga.js",
        STATIC_DIR / "shared.js",
    ]
    import re

    # Pattern finding fetch calls that don't pass resolveApiUrl
    fetch_pattern = re.compile(r"fetch\(([^,\)]+)", re.MULTILINE)

    for js_path in js_files:
        assert js_path.exists(), f"{js_path.name} must exist"
        text = js_path.read_text(encoding="utf-8")
        matches = fetch_pattern.findall(text)
        for target in matches:
            target_clean = target.strip()
            # In api.js, target is targetUrl. In tournament files, it must use resolveApiUrl
            assert "resolveApiUrl" in target_clean, (
                f"Unrouted fetch call found in {js_path.name}: fetch({target_clean})"
            )


def test_zero_bare_unrouted_api_calls_in_index_html():
    """Verify that all fetch calls in index.html resolve through _resolveApiUrl."""
    import re
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    fetch_pattern = re.compile(r"fetch\(([^,\)]+)", re.MULTILINE)
    matches = fetch_pattern.findall(index_html)
    assert len(matches) >= 10, f"Expected at least 10 fetch calls in index.html, found {len(matches)}"

    for target in matches:
        target_clean = target.strip()
        assert "_resolveApiUrl" in target_clean or "resolveApiUrl" in target_clean, (
            f"Unrouted fetch call found in index.html: fetch({target_clean})"
        )


def test_module_import_and_export_wiring():
    """Verify that shared.js exports resolveApiUrl and tournament modules import it."""
    shared_text = (STATIC_DIR / "shared.js").read_text(encoding="utf-8")
    assert "resolveApiUrl" in shared_text
    assert "getApiBaseUrl" in shared_text

    for mod_name in ("wc.js", "ucl.js", "laliga.js"):
        mod_text = (STATIC_DIR / mod_name).read_text(encoding="utf-8")
        assert "resolveApiUrl" in mod_text, f"{mod_name} must reference resolveApiUrl"
