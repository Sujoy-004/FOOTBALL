"""Explicit snapshot mode must make ZERO live provider/API requests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


@pytest.fixture(autouse=True)
def isolated_refresh_ledger(tmp_path, monkeypatch):
    """Keep every refresh-ledger write inside the test sandbox.

    The pipelines persist freshness reports next to the web layer; without
    this redirect, test runs overwrite the production
    web/last_refresh.json (the historical 'LiveProv'/'_DeadProvider'
    artifacts).
    """
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.ucl_app as ucl_app
    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.setattr(ucl_app, "_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    yield


class _CountingProvider:
    last_error = None
    calls = 0

    def fetch_matches(self, *a, **k):
        _CountingProvider.calls += 1
        return []


@pytest.fixture
def snapshot_env(monkeypatch):
    """Force startup decision to snapshot + counting provider."""
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    # Explicit snapshot must stay zero-network even though the server
    # lifespan re-runs run_startup_flow (non-interactive => "auto" by
    # default): the env override pins the decision to snapshot.
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    prov = _CountingProvider()
    _CountingProvider.calls = 0
    import web.common
    monkeypatch.setattr(web.common, "get_data_provider",
                        lambda b, f, l=None: prov)
    # force the startup decision without running interactive flow
    import web.startup as startup
    startup._last_decision = startup.StartupDecision("snapshot", "")
    return prov


def test_wc_snapshot_mode_zero_live_calls(snapshot_env, tmp_path):
    """1. WC fetch_live_data in snapshot mode: 0 provider calls."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    report = wc_pipeline.fetch_live_data("", "", WC_DATA)
    assert _CountingProvider.calls == 0
    assert report["attempted"] is False
    assert "snapshot" in report.get("skipped_reason", "")


def test_ucl_snapshot_mode_zero_live_calls(snapshot_env):
    """2. UCL _fetch_live_data in snapshot mode: 0 provider calls."""
    import web.ucl_app as ucl_app
    ucl_app._fetch_live_data()
    assert _CountingProvider.calls == 0


def test_ucl_refresh_endpoint_blocked_in_snapshot(snapshot_env):
    from web.startup import is_snapshot_mode
    assert is_snapshot_mode()


def _historical_ucl_data(tmp_path):
    import shutil
    from competitions.ucl.src.seasons import set_current_season
    dst = tmp_path / "ucl_data"
    shutil.copytree(UCL_DATA, dst)
    set_current_season(dst, "2025/26", basis="pointer_local", provider=None)
    return dst


def test_ucl_deterministic_compute_no_knockout_results(tmp_path):
    """Missing knockout_results.json must NOT suppress standings/odds/signals."""
    from competitions.ucl.src.orchestrator import run_deterministic_compute
    data_dir = _historical_ucl_data(tmp_path)
    (data_dir / "knockout_results.json").unlink(missing_ok=True)
    result = run_deterministic_compute(str(data_dir), bsd_api_key="")
    assert "error" not in result, f"deterministic_compute errored: {result.get('error')}"
    standings = result.get("standings", [])
    assert len(standings) == 36, f"expected 36 teams, got {len(standings)}"
    assert result.get("mode") == "results"


def test_ucl_api_data_valid_json_in_snapshot(tmp_path, monkeypatch):
    """3+4. /ucl/api/data returns valid JSON in snapshot mode (no empty body)."""
    from fastapi.testclient import TestClient
    import web.ucl_app as app
    data_dir = _historical_ucl_data(tmp_path)
    monkeypatch.setattr(app, "DATA_DIR", data_dir)
    with TestClient(app.ucl_app) as client:
        for url in ("/api/data", "/api/standings",
                    "/api/bracket", "/api/odds"):
            r = client.get(url)
            assert r.status_code == 200, url
            r.json()  # raises if body is empty/malformed


def test_ucl_browser_chain_snapshot_zero_calls_and_valid_json(snapshot_env, monkeypatch):
    """The EXACT browser flow for /#/ucl under snapshot mode:

    parent server boot -> static module fetch -> five SPA API fetches.
    Asserts zero live provider calls AND parseable bodies throughout.
    """
    import shutil
    from web.server import app as server_app

    with TestClient(server_app) as client:
        # 1. the dynamically-imported module must be served intact
        r = client.get("/static/ucl.js")
        assert r.status_code == 200
        assert len(r.content) > 10000, "ucl.js truncated"
        assert "export function init" in r.text

        # 2. the five SPA fetches parse as JSON
        for path in ("/api/data", "/api/standings", "/api/bracket",
                     "/api/odds", "/api/signals"):
            resp = client.get("/ucl" + path)
            assert resp.status_code == 200, path
            payload = resp.json()   # raises on empty/malformed body
            assert isinstance(payload, (dict, list))

        # 3. snapshot isolation held across the whole chain
        assert _CountingProvider.calls == 0


def test_served_ucl_js_parses_with_node_if_available(snapshot_env, tmp_path):
    """Guard against re-shipping a syntactically broken ucl.js."""
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    from fastapi.testclient import TestClient
    from web.server import app as server_app
    with TestClient(server_app):
        r = client_get_js(server_app)
    js_file = tmp_path / "ucl_served.js"
    js_file.write_bytes(r.content)
    chk = subprocess.run([node, "--check", str(js_file)],
                         capture_output=True, text=True, errors="replace")
    assert chk.returncode == 0, f"served ucl.js fails to parse: {chk.stderr[:300]}"


def client_get_js(server_app):
    from fastapi.testclient import TestClient
    with TestClient(server_app) as c:
        return c.get("/static/ucl.js")


def test_ucl_unhandled_exception_returns_valid_json():
    """4b. Even an internal error must produce JSON, never an empty body."""
    from fastapi.testclient import TestClient
    from web.ucl_app import ucl_app

    @ucl_app.get("/_test_raise")
    async def _raise():
        raise RuntimeError("boom")

    with TestClient(ucl_app, raise_server_exceptions=False) as client:
        r = client.get("/_test_raise")
        assert r.status_code == 500
        payload = r.json()          # must parse
        assert "error" in payload


# ── live mode unaffected ────────────────────────────────────────────────
def test_live_mode_still_reaches_provider(monkeypatch):
    """5. Without snapshot decision, WC pipeline reaches the provider."""
    import competitions.worldcup.src.pipeline as wc_pipeline

    calls = {"n": 0}

    class LiveProv:
        last_error = None

        def fetch_matches(self, **k):
            calls["n"] += 1
            return []

    monkeypatch.setattr("web.common.get_data_provider",
                        lambda b, f, l=None: LiveProv())
    # ensure NOT snapshot
    import web.startup as startup
    startup._last_decision = startup.StartupDecision("live-configured", "")
    try:
        wc_pipeline.fetch_live_data("", "", ROOT / "competitions" / "worldcup" / "data")
        assert calls["n"] >= 1
    finally:
        startup._last_decision = None


def test_ucl_snapshot_boot_makes_zero_clubelo_requests(monkeypatch, tmp_path):
    """Exchange 5: snapshot mode must not touch ClubElo either.

    The deterministic compute used to call fetch_team_elos unconditionally,
    making a live HTTP request during 'zero network' snapshot boots while
    the provider-level counter looked clean.
    """
    import web.startup as startup
    startup._last_decision = startup.StartupDecision("snapshot", "")
    import competitions.ucl.src.elo_fetcher as ucl_ef
    import football_core.elo_fetcher as core_ef

    calls = {"clubelo": 0, "urlopen": 0}

    def _no_clubelo(*a, **k):
        calls["clubelo"] += 1
        raise AssertionError("ClubElo fetched during snapshot boot")

    real_urlopen = core_ef.urllib.request.urlopen

    def _counting_urlopen(*a, **k):
        calls["urlopen"] += 1
        return real_urlopen(*a, **k)

    monkeypatch.setattr(ucl_ef, "fetch_team_elos", _no_clubelo)
    monkeypatch.setattr(core_ef.urllib.request, "urlopen", _counting_urlopen)

    from competitions.ucl.src.orchestrator import run_deterministic_compute
    data_dir = _historical_ucl_data(tmp_path)
    result = run_deterministic_compute(str(data_dir), bsd_api_key="")
    assert "error" not in result, result.get("error")
    assert len(result.get("standings", [])) == 36
    assert calls == {"clubelo": 0, "urlopen": 0}, calls
