"""Always-on acquisition policy: fresh FIRST, validated snapshot FALLBACK.

Locks down the startup decision contract:

- default startup decides "auto" (attempt each provider lazily per
  competition; failures fall back to the last validated on-disk stores);
- there is NO interactive prompt and NO choice that disables scraping in
  normal mode (the old menu [1]/[2] was removed in Exchange 4 v2);
- explicit snapshot stays ZERO-network (FOOTBALL_SNAPSHOT=1 or a forced
  StartupDecision("snapshot"));
- a failed provider attempt produces a truthful attempted/success/stale
  report and NEVER deletes or overwrites existing factual stores;
- a succeeding provider refreshes the tmp data dir and reports the stage
  checklist through the freshness ledger seams.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


def _hash_json_dir(data_dir: Path) -> dict[str, str]:
    """SHA-256 of every top-level *.json store in *data_dir*."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(data_dir).glob("*.json"))
    }


class _CountingProvider:
    """Provider fake: counts fetch_matches calls, returns canned payload."""

    last_error = None
    calls = 0
    payload: list = []

    def __init__(self, payload: list | None = None, last_error: str | None = None):
        if payload is not None:
            self.payload = payload
        if last_error is not None:
            self.last_error = last_error

    def fetch_matches(self, *a, **k):
        _CountingProvider.calls += 1
        return list(self.payload)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Redirect both ledger seams into the sandbox + neutral env/decision.

    Mirrors tests/test_snapshot_isolation.py so no test here can touch the
    production web/last_refresh.json, and no decision leaks between tests.
    """
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.startup as startup
    import web.ucl_app as ucl_app

    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.setattr(ucl_app, "_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    yield
    startup._last_decision = None


# ── 1. default non-interactive path ──────────────────────────────────────

def test_default_non_interactive_decides_auto(monkeypatch):
    """No TTY + no key => "auto": attempt providers, fall back on failure."""
    import web.startup as startup

    # A falsy override must NOT force snapshot mode.
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "0")

    d = startup.run_startup_flow(echo=lambda s: None)
    assert isinstance(d, startup.StartupDecision)
    assert d.mode == "auto"
    assert d.fdo_key == ""
    assert startup.is_snapshot_mode() is False


def test_usable_key_still_decides_live_configured(monkeypatch):
    """Regression guard: Case A semantics are unchanged by the auto kind."""
    import web.startup as startup

    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "realkey123456")
    d = startup.run_startup_flow(echo=lambda s: None)
    assert d.mode == "live-configured"
    assert startup.is_snapshot_mode() is False


# ── 2. explicit snapshot stays zero-network ──────────────────────────────

@pytest.mark.parametrize("raw", ["1", "true", "YES", "on"])
def test_football_snapshot_env_forces_zero_network(monkeypatch, raw):
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.common
    import web.startup as startup
    import web.ucl_app as ucl_app

    prov = _CountingProvider()
    _CountingProvider.calls = 0
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", raw)
    monkeypatch.setattr(web.common, "get_data_provider",
                        lambda b, f, l=None: prov)

    # The override wins over every normal-mode path (there is no menu).
    d = startup.run_startup_flow(echo=lambda s: None)
    assert d.mode == "snapshot"
    assert startup.is_snapshot_mode() is True

    report_wc = wc_pipeline.fetch_live_data("", "", WC_DATA)
    ucl_app._fetch_live_data()

    assert _CountingProvider.calls == 0
    assert report_wc["attempted"] is False
    assert "snapshot" in report_wc.get("skipped_reason", "")
    assert ucl_app._refresh_report["attempted"] is False
    assert ucl_app._refresh_report["stale"] is True


def test_forced_snapshot_decision_is_zero_network(monkeypatch):
    """A forced StartupDecision("snapshot") is an explicit OFFLINE session:
    wrappers self-gate and make zero provider calls."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.common
    import web.startup as startup
    import web.ucl_app as ucl_app

    prov = _CountingProvider()
    _CountingProvider.calls = 0
    monkeypatch.setattr(web.common, "get_data_provider",
                        lambda b, f, l=None: prov)

    startup._last_decision = startup.StartupDecision("snapshot", "")
    assert startup.is_snapshot_mode() is True

    wc_pipeline.fetch_live_data("", "", WC_DATA)
    ucl_app._fetch_live_data()
    assert _CountingProvider.calls == 0


def test_no_credentials_prints_banner_and_decides_auto(monkeypatch):
    """Normal mode with no usable credential: short informational banner,
    decision stays fresh-first ("auto"); no prompt can disable scraping."""
    import web.startup as startup

    transcript: list[str] = []
    d = startup.run_startup_flow(echo=transcript.append)

    joined = "\n".join(transcript)
    assert d.mode == "auto"
    assert startup.is_snapshot_mode() is False
    assert ("acquisition will be attempted but no provider is configured"
            in joined)
    assert "stored data will be used until credentials are provided" in joined
    assert "[1]" not in joined and "[2]" not in joined


# ── 3. failing provider: truthful stale report, stores preserved ─────────

def test_auto_empty_provider_reports_stale_and_preserves_stores(monkeypatch):
    """auto + provider returning [] => attempted/success=false/stale=true
    for BOTH apps, and every factual store byte-identical before/after."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.common
    import web.startup as startup
    import web.ucl_app as ucl_app

    startup._last_decision = startup.StartupDecision("auto", "")

    prov = _CountingProvider(payload=[], last_error="provider down")
    _CountingProvider.calls = 0
    monkeypatch.setattr(web.common, "get_data_provider",
                        lambda b, f, l=None: prov)

    before = {**_hash_json_dir(WC_DATA), **_hash_json_dir(UCL_DATA)}

    rep_wc = wc_pipeline.fetch_live_data("", "", WC_DATA)
    ucl_app._fetch_live_data()

    after = {**_hash_json_dir(WC_DATA), **_hash_json_dir(UCL_DATA)}
    assert after == before, "a failed provider attempt must never rewrite stores"

    assert _CountingProvider.calls >= 2          # both wrappers attempted
    assert rep_wc["attempted"] is True
    assert rep_wc["success"] is False
    assert rep_wc["stale"] is True
    assert rep_wc["error"]

    rep_ucl = ucl_app._refresh_report
    assert rep_ucl["attempted"] is True
    assert rep_ucl["success"] is False
    assert rep_ucl["stale"] is True
    assert rep_ucl["error"]


def test_auto_raising_provider_never_touches_stores(monkeypatch):
    """auto + provider raising => no factual-store mutation from either app."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.common
    import web.startup as startup
    import web.ucl_app as ucl_app

    startup._last_decision = startup.StartupDecision("auto", "")

    class _Raising:
        last_error = None

        def fetch_matches(self, *a, **k):
            raise RuntimeError("network unreachable")

    monkeypatch.setattr(web.common, "get_data_provider",
                        lambda b, f, l=None: _Raising())

    before = {**_hash_json_dir(WC_DATA), **_hash_json_dir(UCL_DATA)}

    wc_pipeline.fetch_live_data("", "", WC_DATA)   # pipeline guards internally
    with pytest.raises(RuntimeError):
        ucl_app._fetch_live_data()                 # guarded at server lifespan

    after = {**_hash_json_dir(WC_DATA), **_hash_json_dir(UCL_DATA)}
    assert after == before


# ── 4. succeeding provider refreshes state (UCL, sandboxed DATA_DIR) ────

def test_auto_succeeding_provider_ingests_into_tmp_store(tmp_path, monkeypatch):
    """auto + stub provider => ingest runs against the SANDBOX data dir:
    success report with stage checklist, results.json updated there, and
    the repository stores untouched."""
    import web.common
    import web.startup as startup
    import web.ucl_app as ucl_app

    startup._last_decision = startup.StartupDecision("auto", "")

    tmp_data = tmp_path / "ucldata"
    shutil.copytree(UCL_DATA, tmp_data)

    fixture = json.loads(
        (tmp_data / "fixtures.json").read_text(encoding="utf-8")
    )["schedule"]["matchdays"][0][0]
    mid, home, away = fixture["match_id"], fixture["team_a"], fixture["team_b"]

    results_raw = json.loads((tmp_data / "results.json").read_text(encoding="utf-8"))
    rows = results_raw["matches"] if isinstance(results_raw, dict) else results_raw
    current = next(r for r in rows if r.get("match_id") == mid)

    event = {
        "status": "FINISHED",
        "stage": "LEAGUE_STAGE",
        "home_team": home,
        "away_team": away,
        "home_score": int(current.get("home_score") or 0) + 1,
        "away_score": int(current.get("away_score") or 0) + 3,
    }

    provider = _CountingProvider(payload=[event])
    _CountingProvider.calls = 0
    monkeypatch.setattr(web.common, "get_data_provider",
                        lambda b, f, l=None: provider)
    monkeypatch.setattr(ucl_app, "DATA_DIR", tmp_data)

    repo_before = _hash_json_dir(UCL_DATA)
    ucl_app._fetch_live_data()

    assert _CountingProvider.calls == 1
    rep = ucl_app._refresh_report
    assert rep["attempted"] is True
    assert rep["success"] is True
    assert rep["stale"] is False

    stage_keys = {s.get("key") for s in rep.get("stages") or []}
    assert {"teams", "league", "playoff", "knockout", "champion"} <= stage_keys

    updated = json.loads((tmp_data / "results.json").read_text(encoding="utf-8"))
    updated_rows = updated["matches"] if isinstance(updated, dict) else updated
    row = next(r for r in updated_rows if r.get("match_id") == mid)
    assert row["home_score"] == event["home_score"]
    assert row["away_score"] == event["away_score"]

    assert _hash_json_dir(UCL_DATA) == repo_before, \
        "sandboxed ingestion must never mutate repository stores"
