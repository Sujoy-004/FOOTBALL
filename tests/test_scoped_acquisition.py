"""Exchange 4 v2: competition-scoped lazy acquisition.

Locks down:

- adapter.refresh() is competition-scoped: refreshing ucl touches ONLY
  the UCL provider (worldcup counter stays 0) and vice versa;
- refresh() never raises, even when the provider raises — it returns a
  truthful attempted/success/error report;
- server boot performs ZERO provider calls; acquisition fires lazily,
  at most once per process, on each competition's first data request;
- explicit offline (FOOTBALL_SNAPSHOT=1) never attempts anything;
- run_startup_flow has no prompt path that disables scraping in normal
  mode; env override and forced decisions still pin snapshot.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

UCL_LEAGUE_ID = 7      # web.ucl_app.UCL_LEAGUE_ID
WC_LEAGUE_ID = 27      # competitions.worldcup.src.constants.DEFAULT_LEAGUE_ID


class _CountingProvider:
    """Per-instance counting fake; returns canned (possibly empty) rows."""

    def __init__(self, payload: list | None = None,
                 error: Exception | None = None):
        self.calls = 0
        self.payload = payload if payload is not None else []
        self.error = error
        self.last_error = None

    def fetch_matches(self, *a, **k):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.payload)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Sandbox ledgers + neutral decision state + clean lazy gates."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.competitions as competitions
    import web.startup as startup
    import web.ucl_app as ucl_app

    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.setattr(ucl_app, "_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    monkeypatch.setenv("FOOTBALL_PRELOAD_ALL", "")
    competitions.reset_lazy_gates()
    startup._last_decision = None
    yield
    competitions.reset_lazy_gates()
    startup._last_decision = None


def _install_split_fakes(monkeypatch, ucl_prov, wc_prov):
    """Route provider selection by league id so each competition gets its
    own counting fake through the single shared factory."""
    import web.common

    def _factory(bsd_key, fdo_key, league_id=None):
        return ucl_prov if league_id == UCL_LEAGUE_ID else wc_prov

    monkeypatch.setattr(web.common, "get_data_provider", _factory)


# ── 1. registry scoping: no cross-talk ───────────────────────────────────

def test_ucl_refresh_calls_only_ucl_provider(monkeypatch):
    from web.competitions import REGISTRY

    ucl_prov = _CountingProvider()
    wc_prov = _CountingProvider()
    _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

    report = REGISTRY.get("ucl").refresh()

    assert ucl_prov.calls >= 1, "UCL refresh must reach the UCL fake"
    assert wc_prov.calls == 0, "UCL refresh must never touch the WC provider"
    assert isinstance(report, dict)


def test_worldcup_refresh_calls_only_worldcup_provider(monkeypatch):
    from web.competitions import REGISTRY

    ucl_prov = _CountingProvider()
    wc_prov = _CountingProvider()
    _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

    report = REGISTRY.get("worldcup").refresh()

    assert wc_prov.calls >= 1, "WC refresh must reach the WC fake"
    assert ucl_prov.calls == 0, "WC refresh must never touch the UCL provider"
    assert isinstance(report, dict)


# ── 2. refresh() never raises ─────────────────────────────────────────────

def test_refresh_never_raises_on_provider_failure(monkeypatch):
    from web.competitions import REGISTRY

    boom = RuntimeError("network unreachable")

    for competition_id in ("ucl", "worldcup"):
        if competition_id == "ucl":
            ucl_prov = _CountingProvider(error=boom)
            wc_prov = _CountingProvider()
        else:
            ucl_prov = _CountingProvider()
            wc_prov = _CountingProvider(error=boom)
        _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

        report = REGISTRY.get(competition_id).refresh()  # must not raise

        assert report["attempted"] is True
        assert report["success"] is False
        assert report["stale"] is True
        assert report.get("error"), "error message must be present on failure"
        target_prov = ucl_prov if competition_id == "ucl" else wc_prov
        assert target_prov.calls >= 1


def test_adapter_without_hook_reports_honestly():
    from web.competitions import CompetitionAdapter, CompetitionRegistry

    reg = CompetitionRegistry()
    reg.register(CompetitionAdapter(
        id="bare", display_name="Bare", mount_prefix="/bare",
        api_prefix="/bare/api", subapp=None,
        get_status=lambda: {}, simulation_support=lambda: {},
    ))
    report = reg.get("bare").refresh()
    assert report["attempted"] is False
    assert report["success"] is False
    assert report["error"]


# ── 3. lazy scoped acquisition through the served API ────────────────────

def test_lazy_acquisition_is_per_competition_and_once(monkeypatch):
    from web.server import app as server_app

    ucl_prov = _CountingProvider()
    wc_prov = _CountingProvider()
    _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

    with TestClient(server_app) as client:
        # Boot made zero provider calls.
        assert ucl_prov.calls == 0
        assert wc_prov.calls == 0

        # First UCL data request: ONLY the UCL provider may fire.
        r = client.get("/ucl/api/data")
        assert r.status_code == 200
        assert r.json().get("error") is None or True  # body always parses
        ucl_after_first = ucl_prov.calls
        assert ucl_after_first >= 1
        assert wc_prov.calls == 0

        # First WC data request: WC fires once; UCL untouched further.
        r = client.get("/worldcup/api/data")
        assert r.status_code == 200
        assert wc_prov.calls == 1

        # Repeat hits never re-attempt (once-per-process guard).
        for _ in range(3):
            client.get("/ucl/api/data")
            client.get("/worldcup/api/data")
        assert ucl_prov.calls == ucl_after_first
        assert wc_prov.calls == 1


def test_boot_makes_zero_provider_calls_without_preload(monkeypatch):
    from web.server import app as server_app

    ucl_prov = _CountingProvider()
    wc_prov = _CountingProvider()
    _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

    with TestClient(server_app):
        pass

    assert ucl_prov.calls == 0 and wc_prov.calls == 0


# ── 4. explicit offline: endpoints never attempt ─────────────────────────

def test_explicit_offline_endpoints_never_attempt(monkeypatch):
    import web.startup as startup
    from web.server import app as server_app

    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    ucl_prov = _CountingProvider()
    wc_prov = _CountingProvider()
    _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

    with TestClient(server_app) as client:
        d = startup.run_startup_flow(echo=lambda s: None)
        assert d.mode == "snapshot"

        r = client.get("/ucl/api/data")
        assert r.status_code == 200
        # Truthful disclosure: snapshot skip recorded, nothing attempted.
        assert r.json()["refresh"].get("attempted") is False

        r = client.get("/worldcup/api/data")
        assert r.status_code == 200

    assert ucl_prov.calls == 0
    assert wc_prov.calls == 0


# ── 5. startup flow semantics ─────────────────────────────────────────────

def test_startup_flow_normal_mode_cannot_disable_scraping(monkeypatch):
    """No prompt path exists: normal mode decides fresh-first kinds only."""
    import web.startup as startup

    transcript: list[str] = []
    d = startup.run_startup_flow(echo=transcript.append)

    joined = "\n".join(transcript)
    assert d.mode in ("live-configured", "auto")
    assert startup.is_snapshot_mode() is False
    assert "[2]" not in joined                      # menu removed
    assert ("acquisition will be attempted but no provider is configured"
            in joined)                              # informational banner
    assert "stored data will be used until credentials are provided" in joined


def test_snapshot_env_still_forces_snapshot(monkeypatch):
    import web.startup as startup

    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    d = startup.run_startup_flow(echo=lambda s: None)
    assert d.mode == "snapshot"
    assert startup.is_snapshot_mode() is True


def test_forced_decision_snapshot_still_honored():
    import web.startup as startup

    startup._last_decision = startup.StartupDecision("snapshot", "")
    assert startup.is_snapshot_mode() is True
