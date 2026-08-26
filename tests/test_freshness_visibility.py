"""Freshness/staleness visibility regressions (truth-first Exchange 2).

Guarantees:
- A failed or empty provider refresh produces a structured report marked
  stale=True with the error reason preserved.
- The report is stored for the API surface (WC: cache["refresh"]; UCL:
  _refresh_report) so stale fallback data cannot masquerade as current.
- Completed results stay excluded from simulation (UCL league evidence).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


@pytest.fixture(autouse=True)
def isolated_refresh_ledger(tmp_path, monkeypatch):
    """Redirect freshness-ledger writes away from the production file."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.ucl_app as ucl_app
    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.setattr(ucl_app, "_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    yield


class _DeadProvider:
    """Provider stub that authenticates/fetches like a broken endpoint."""
    last_error = "HTTP 400: Your API token is invalid."

    def __init__(self):
        self.calls = 0

    def fetch_matches(self, *a, **k):
        self.calls += 1
        return []


@pytest.fixture
def dead_provider(monkeypatch):
    prov = _DeadProvider()

    def _factory(bsd_key, fdo_key, league_id=None):
        return prov

    monkeypatch.setattr("web.common.get_data_provider", _factory)
    return prov


def test_wc_failed_refresh_is_visible_and_marked_stale(monkeypatch, caplog):
    """WC: failed refresh -> structured report, stale flag, persisted reason."""
    import logging

    import competitions.worldcup.src.pipeline as wc_pipeline

    import web.common
    monkeypatch.setattr(
        web.common, "get_data_provider",
        lambda b, f, l: type("P", (), {"last_error": "HTTP 400: invalid",
                                       "fetch_matches": lambda s, **k: []})())
    report = wc_pipeline.fetch_live_data("", "", WC_DATA)
    assert report["attempted"] is True
    assert report["success"] is False
    assert report["stale"] is True
    assert "invalid" in (report["error"] or "")
    # previous successful timestamp must be preserved for comparison
    assert "last_success_at" in report


def test_wc_failure_surfaces_in_api_cache(monkeypatch):
    """WC app wrapper stores the report where /api/data|overview serve it."""
    import web.wc_app as wc_app

    report = {"provider": "X", "attempted": True, "success": False,
              "error": "boom", "stale": True}
    monkeypatch.setattr(
        "competitions.worldcup.src.pipeline.fetch_live_data",
        lambda *a, **k: report)
    out = wc_app._fetch_live_data()
    assert out == report
    assert wc_app.cache["refresh"]["stale"] is True


def test_ucl_empty_fetch_marks_stale(monkeypatch, caplog):
    """UCL: empty provider response -> stale report persisted + warned."""
    import logging

    dead = _DeadProvider()
    monkeypatch.setattr("web.common.get_data_provider", lambda b, f, l=None: dead)

    import web.ucl_app as ucl_app
    with caplog.at_level(logging.WARNING):
        ucl_app._fetch_live_data()
    rep = ucl_app._refresh_report
    assert rep["attempted"] is True
    assert rep["success"] is False
    assert rep["stale"] is True
    assert any("STALE" in r.message for r in caplog.records)


def test_ucl_league_results_fully_ingested():
    """Available evidence: every completed league fixture is excluded from sampling."""
    # Use the tracked bootstrap file instead of private runtime results.json
    results = json.loads((UCL_DATA / "bootstrap" / "league_results_2025_26.json").read_text(encoding="utf-8"))
    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text(encoding="utf-8"))
    fx_ids = {m["match_id"] for md in fixtures["schedule"]["matchdays"] for m in md}
    got_ids = {m["match_id"] for m in results.get("matches", [])}
    assert got_ids == fx_ids, "league results incomplete vs fixtures"
