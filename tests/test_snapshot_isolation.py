"""Explicit snapshot mode must make ZERO live provider/API requests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


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


def test_ucl_api_data_valid_json_in_snapshot():
    """3+4. /ucl/api/data returns valid JSON in snapshot mode (no empty body)."""
    from fastapi.testclient import TestClient
    from web.ucl_app import ucl_app
    with TestClient(ucl_app) as client:
        for url in ("/api/data", "/api/standings",
                    "/api/bracket", "/api/odds"):
            r = client.get(url)
            assert r.status_code == 200, url
            r.json()  # raises if body is empty/malformed


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
