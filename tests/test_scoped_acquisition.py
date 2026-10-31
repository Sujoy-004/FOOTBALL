"""Competition-scoped acquisition with pure reads (Exchange 4 v2, plan 02-06).

Locks down:

- boot makes ZERO provider calls (roadmap criterion 2, "during boot");
- plain data reads on ALL THREE apps make ZERO provider calls — reads are
  pure; ingestion happens only via adapter.refresh() (explicit endpoint,
  FOOTBALL_PRELOAD_ALL preload, or a test);
- adapter.refresh() is competition-scoped: refreshing ucl touches ONLY
  the UCL provider (worldcup counter stays 0) and vice versa;
- refresh() never raises, even when the provider raises — it returns a
  truthful attempted/success/error report;
- explicit offline (FOOTBALL_SNAPSHOT=1) never attempts anything;
- FOOTBALL_PRELOAD_ALL=1 preload refreshes each registered competition
  exactly once and consumes its once-per-process gate (the sanctioned
  boot-time exception);
- run_startup_flow has no prompt path that disables scraping in normal
  mode; env override and forced decisions still pin snapshot.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent



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


def _sandbox_data_dir(monkeypatch, tmp_path, module, name: str) -> None:
    """Point a competition app at a THROWAWAY copy of its data dir.

    A refresh may re-serialise the tracked runtime stores even when the
    provider returns nothing, so a test that refreshes must never write the
    repository's own data (same guard as test_refresh_endpoint_contract).
    """
    import shutil

    src = Path(module.DATA_DIR)
    dst = tmp_path / name
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DATA_DIR", dst)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Sandbox ledgers + neutral decision state + clean lazy gates."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    import web.competitions as competitions
    import web.laliga_app as laliga_app
    import web.startup as startup
    import web.ucl_app as ucl_app
    import web.wc_app as wc_app

    monkeypatch.setattr(wc_pipeline, "_last_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.setattr(ucl_app, "_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    monkeypatch.setattr(laliga_app, "_refresh_report_path",
                        lambda: tmp_path / "last_refresh.json")
    _sandbox_data_dir(monkeypatch, tmp_path, wc_app, "wcdata")
    _sandbox_data_dir(monkeypatch, tmp_path, ucl_app, "ucldata")
    _sandbox_data_dir(monkeypatch, tmp_path, laliga_app, "laligadata")
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    monkeypatch.setenv("FOOTBALL_PRELOAD_ALL", "")
    # UCL refresh state is module-level: reset it so one scenario's
    # explicit refresh cannot leak into another's served report.
    ucl_app._refresh_report = {}
    ucl_app._refresh_reports = {}
    ucl_app._refresh_reports_seeded = False
    competitions.reset_lazy_gates()
    startup.set_session_decision(None)
    yield
    ucl_app._refresh_report = {}
    ucl_app._refresh_reports = {}
    ucl_app._refresh_reports_seeded = False
    competitions.reset_lazy_gates()
    startup.set_session_decision(None)


def _install_split_fakes(monkeypatch, ucl_prov, wc_prov):
    """Route provider selection so each competition gets its
    own counting fake through the single shared factory."""

    class SplitProvider:
        last_error = None
        def fetch_matches(self, competition_id="WC", *a, **k):
            if competition_id in ("CL", "ucl"):
                return ucl_prov.fetch_matches(competition_id, *a, **k)
            return wc_prov.fetch_matches(competition_id, *a, **k)

    monkeypatch.setattr("football_core.runtime_support.get_data_provider", lambda *a, **k: SplitProvider())


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


# ── 3. reads are pure: acquisition happens only on an explicit trigger ───

def test_plain_reads_make_zero_provider_calls(monkeypatch):
    """Roadmap criterion 2 (plan 02-06): boot AND plain reads make ZERO
    provider calls on every app; the only trigger is an explicit
    adapter.refresh(), and that trigger stays competition-scoped."""
    from web.server import app as server_app
    from web.competitions import REGISTRY

    ucl_prov = _CountingProvider()
    wc_prov = _CountingProvider()
    _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

    with TestClient(server_app) as client:
        # Boot made zero provider calls.
        assert ucl_prov.calls == 0
        assert wc_prov.calls == 0

        # Plain reads on all three apps: still zero. Reads never acquire.
        reads = ("/worldcup/api/data", "/ucl/api/data", "/laliga/api/data")
        for path in reads:
            assert client.get(path).status_code == 200
        assert ucl_prov.calls == 0
        assert wc_prov.calls == 0

        # The ONLY trigger: explicit refresh, scoped to its competition.
        REGISTRY.get("ucl").refresh()
        assert ucl_prov.calls >= 1
        assert wc_prov.calls == 0

        # Repeated plain reads still never re-attempt.
        for _ in range(3):
            for path in reads:
                client.get(path)
        assert ucl_prov.calls >= 1
        assert wc_prov.calls == 0


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

    startup.set_session_decision(startup.StartupDecision("snapshot", ""))
    assert startup.is_snapshot_mode() is True


# ── 6. FOOTBALL_PRELOAD_ALL eager preload (the sanctioned boot exception) ─

def test_preload_all_refreshes_each_adapter_once_and_consumes_gates(monkeypatch):
    """Plan 02-06 verification: ``_preload_registered_competitions`` (the
    FOOTBALL_PRELOAD_ALL=1 hook, web/server.py:86-99) still works after the
    lazy read path was removed — every registered competition is refreshed
    exactly once and its once-per-process gate is marked consumed, so the
    preload stays the only sanctioned boot-time acquisition.

    Adapters are wrapped (not mocked away): the real scoped refresh runs
    against the counting fakes, so the test also proves scoping holds under
    preload (each provider is reached by its own competition only).
    """
    import web.competitions as competitions
    import web.server as server

    ucl_prov = _CountingProvider()
    wc_prov = _CountingProvider()
    _install_split_fakes(monkeypatch, ucl_prov, wc_prov)

    ids = competitions.REGISTRY.ids()
    assert set(ids) == {"worldcup", "ucl", "laliga"}, f"unexpected registry: {ids}"

    calls: dict[str, int] = {cid: 0 for cid in ids}
    real_refresh = competitions.CompetitionAdapter.refresh

    def _counted(adapter_self):
        # Class-level patch: the adapters are frozen dataclasses, so the
        # counter wraps the real method instead of an instance attribute.
        calls[adapter_self.id] += 1
        return real_refresh(adapter_self)

    monkeypatch.setattr(competitions.CompetitionAdapter, "refresh", _counted)

    server._preload_registered_competitions()

    assert calls == {cid: 1 for cid in ids}, (
        f"preload must refresh each registered competition exactly once: {calls}"
    )
    for cid in ids:
        assert competitions.lazy_gate_fired(cid), (
            f"{cid}: preload must consume the once-per-process gate"
        )
    # Scoped acquisition still holds under preload: UCL's fake was reached
    # (by UCL alone) and the non-UCL fake was reached (WC + LaLiga).
    assert ucl_prov.calls >= 1, "preload never touched the UCL provider"
    assert wc_prov.calls >= 1, "preload never touched the WC/LaLiga provider"
