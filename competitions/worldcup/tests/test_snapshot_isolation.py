"""Snapshot isolation + refresh-report regressions (World Cup scope).

Ported from the repo-root ``tests/test_snapshot_isolation.py`` World Cup
cases. Every test here redirects the shared ``<repo>/web/last_refresh.json``
freshness ledger into ``tmp_path`` so running the World Cup suite can never
overwrite the production ledger (the historical source of the "LiveProv"
pollution artifacts).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"

# Import bootstrap (mirrors tests/conftest.py): worldcup must precede ucl on
# sys.path so the bare ``src`` name resolves to the World Cup package.
_UCL = str(ROOT / "competitions" / "ucl")
_WC = str(ROOT / "competitions" / "worldcup")
for _entry in (_UCL, _WC, str(ROOT)):
    while _entry in sys.path:
        sys.path.remove(_entry)
sys.path.insert(0, _UCL)
sys.path.insert(0, _WC)
sys.path.insert(0, str(ROOT))


class _CountingProvider:
    last_error = None
    calls = 0

    def fetch_matches(self, *a, **k):
        _CountingProvider.calls += 1
        return []


@pytest.fixture(autouse=True)
def isolated_last_refresh(monkeypatch, tmp_path):
    """Redirect the production last_refresh.json ledger into tmp_path."""
    import competitions.worldcup.src.pipeline as wc_pipeline

    target = tmp_path / "last_refresh.json"
    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path", lambda: target)
    return target


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
    monkeypatch.setattr(startup, "_last_decision",
                        startup.StartupDecision("snapshot", ""))
    return prov


def test_wc_snapshot_mode_zero_live_calls(snapshot_env):
    """1. WC fetch_live_data in snapshot mode: 0 provider calls."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    report = wc_pipeline.fetch_live_data("", "", WC_DATA)
    assert _CountingProvider.calls == 0
    assert report["attempted"] is False
    assert "snapshot" in report.get("skipped_reason", "")


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
    monkeypatch.setattr(startup, "_last_decision",
                        startup.StartupDecision("live-configured", ""))
    wc_pipeline.fetch_live_data("", "", WC_DATA)
    assert calls["n"] >= 1


def test_failed_refresh_persists_only_into_redirected_ledger(
    monkeypatch, isolated_last_refresh
):
    """Regression: a failed refresh must never touch web/last_refresh.json.

    The failure report is written exclusively into the redirected ledger;
    the production file stays byte-identical.
    """
    prod = ROOT / "web" / "last_refresh.json"
    before = prod.read_bytes() if prod.exists() else None

    class EmptyProv:
        last_error = None

        def fetch_matches(self, **k):
            return []

    monkeypatch.setattr("web.common.get_data_provider",
                        lambda b, f, l=None: EmptyProv())
    import web.startup as startup
    monkeypatch.setattr(startup, "_last_decision",
                        startup.StartupDecision("live-configured", ""))

    import competitions.worldcup.src.pipeline as wc_pipeline
    report = wc_pipeline.fetch_live_data("", "", WC_DATA)
    assert report["success"] is False
    assert "no matches" in (report["error"] or "")

    payload = json.loads(isolated_last_refresh.read_text(encoding="utf-8"))
    assert payload["worldcup"]["error"] == report["error"]

    after = prod.read_bytes() if prod.exists() else None
    assert after == before, "production web/last_refresh.json was modified"


def test_unreadable_data_files_return_structured_report(
    monkeypatch, tmp_path
):
    """Data-file load failure returns a shaped report, never None."""
    import competitions.worldcup.src.pipeline as wc_pipeline

    class StubProv:
        last_error = None

        def fetch_matches(self, **k):
            return [{"match_id": "stub"}]

    monkeypatch.setattr("web.common.get_data_provider",
                        lambda b, f, l=None: StubProv())
    import web.startup as startup
    monkeypatch.setattr(startup, "_last_decision",
                        startup.StartupDecision("live-configured", ""))

    report = wc_pipeline.fetch_live_data("", "", tmp_path)
    assert isinstance(report, dict)
    assert report["provider"] is None
    assert report["attempted"] is False
    assert report["success"] is False
    assert report["stale"] is True
    assert "failed to load data files" in (report["error"] or "")
    assert report["skipped_reason"]
    assert "finished" in report
