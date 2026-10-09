"""UCL future-season empty-provider UX — benign "deferred" vs real staleness.

Regression suite for the "Provider has no published match data yet" state
under the D-13 truthfulness contract (02-02):

- an explicitly active NON-historical season (2026/27) requested from a
  provider that answers SUCCESSFULLY with zero matches (HTTP 200, empty
  body) is a BENIGN outcome but NEVER a success: zero received matches
  DERIVE to ``success=False``, ``stale=True``, ``reason="deferred/provider-empty"``.
  ``status="deferred"`` tells the UI "not published yet" instead of
  "transport failure", and no factual store is touched. The draw-derived
  144 fixtures stay authoritative;
- a REAL transport/provider failure (``last_error`` set) keeps the legacy
  stale/error contract exactly (``status="skip"``, ``stale=True``);
- an empty result with NO pointer (or a historical pointer) is UNCHANGED
  ``"skip"``/stale — future-season deferral requires an explicitly active
  non-historical season;
- the web layer maps "deferred" to a ledger entry whose success is False
  and stale is True (the derived verdict travels through the ledger), and
  the UI carrier copy renders the accurate message in both cases.

No test mutates the repository's real data — every scenario runs against a
fresh tmp copy of the UCL data dir.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import pytest

import arch_util as au

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"
WEB_STATIC = ROOT / "web" / "static"


# ── stub providers ──────────────────────────────────────────────────────────

class _EmptyProvider:
    """Successfully-answering provider: HTTP 200 with zero matches.

    ``last_error`` stays None on the benign path; the pipeline only treats
    it as deferred when BOTH the season was explicitly requested AND no
    transport/provider error was recorded. Either way, the D-13 derivation
    reports success=False (zero received matches are never "success").
    """

    def __init__(self, last_error: Optional[str] = None):
        self.last_error = last_error
        self.season: object = "UNSET"
        self.calls = 0

    def fetch_matches(self, competition_id="CL", *, season=None, **kwargs):
        self.calls += 1
        self.season = season
        return []


class _SucceedingProvider:
    """Provider returning a single known finished event (2025/26 contract)."""

    def __init__(self, event: dict):
        self.last_error = None
        self._event = event

    def fetch_matches(self, competition_id="CL", *, season=None, **kwargs):
        return [self._event]


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Sandbox the freshness ledger + reset UCL in-memory report per test."""
    import web.startup as startup
    import web.ucl_app as ucl_app

    monkeypatch.setattr(
        ucl_app, "_refresh_report_path", lambda: tmp_path / "last_refresh.json"
    )
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    ucl_app._refresh_report = {}
    startup.set_session_decision(startup.StartupDecision("auto", ""))
    yield
    startup.set_session_decision(None)
    ucl_app._refresh_report = {}


# ── helpers ─────────────────────────────────────────────────────────────────

def _seed_ucl_dir(tmp_path: Path) -> Path:
    """Fresh copy of the real UCL data tree (all seasons + stores)."""
    dst = tmp_path / "ucl"
    shutil.copytree(UCL_DATA, dst, dirs_exist_ok=True)
    return dst


def _write_pointer(data_dir: Path, season: str | None) -> None:
    from competitions.ucl.src.seasons import set_current_season

    current_path = data_dir / "current.json"
    if season is None:
        current_path.unlink(missing_ok=True)
        return
    set_current_season(data_dir, season, basis="draw", provider="test")


def _run_fetch(data_dir: Path, provider):
    from competitions.ucl.src.pipeline import fetch_live_data

    return fetch_live_data(data_dir, "", "", provider=provider)


# ── 1. pipeline: benign deferred vs real staleness ──────────────────────────

class TestPipelineDeferred:
    def test_future_season_200_empty_is_deferred_and_preserves_stores(
        self, tmp_path
    ):
        """Active 2026/27 + successful-empty => deferred, derived failure, no writes."""
        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2026/27")
        before = au.snapshot_tree(dp)
        provider = _EmptyProvider()

        summary = _run_fetch(dp, provider)

        assert summary["status"] == "deferred"
        assert summary["reason"] == "deferred/provider-empty"
        assert summary["deferred"] is True
        assert summary["n_raw"] == 0
        assert provider.season == 2026, "the future season was requested explicitly"
        report = summary["report"]
        assert report["attempted"] is True
        # D-13: zero received matches derive to failure, never success.
        assert report["success"] is False
        assert report["stale"] is True
        assert report["error"] is None
        assert report["deferred"] is True
        assert report["reason"] == "deferred/provider-empty"
        # Root 2025/26 stores AND the future-season 2026/27 store are untouched.
        assert au.snapshot_tree(dp) == before

    def test_future_season_transport_failure_stays_stale(self, tmp_path):
        """Active 2026/27 + empty + last_error set => legacy stale/skip."""
        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2026/27")
        before = au.snapshot_tree(dp)
        provider = _EmptyProvider(last_error="HTTP 400: Your API token is invalid.")

        summary = _run_fetch(dp, provider)

        assert summary["status"] == "skip"
        assert summary["report"]["success"] is False
        assert summary["report"]["stale"] is True
        assert "HTTP 400" in summary["report"]["error"]
        assert summary["report"].get("deferred") is False
        assert au.snapshot_tree(dp) == before

    def test_no_pointer_empty_unchanged_skip(self, tmp_path):
        """No current pointer => old contract: empty fetch is stale, not deferred."""
        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, None)
        before = au.snapshot_tree(dp)

        summary = _run_fetch(dp, _EmptyProvider())

        assert summary["status"] == "skip"
        assert summary["report"]["success"] is False
        assert summary["report"]["stale"] is True
        # Zero received matches derive to provider-empty here as well.
        assert summary["reason"] == "deferred/provider-empty"
        assert au.snapshot_tree(dp) == before

    def test_historical_pointer_empty_unchanged_skip(self, tmp_path):
        """2025/26 active (historical) => requested_season None => stale skip."""
        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2025/26")
        before = au.snapshot_tree(dp)

        summary = _run_fetch(dp, _EmptyProvider())

        assert summary["status"] == "skip"
        assert summary["report"]["stale"] is True
        assert summary["reason"] == "deferred/provider-empty"
        assert au.snapshot_tree(dp) == before

    def test_historical_success_still_ok(self, tmp_path):
        """2025/26 active + real data => status ok, success, non-stale (unchanged)."""
        from competitions.ucl.src.seasons import normalize_season_token

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2025/26")
        event = au.ucl_league_events(dp, n=1)[0]
        assert normalize_season_token(event["season"]) == "2025/26"

        summary = _run_fetch(dp, _SucceedingProvider(event))

        assert summary["status"] == "ok"
        assert summary["report"]["success"] is True
        assert summary["report"]["stale"] is False
        assert summary["report"].get("deferred") is False
        assert summary["report"]["error"] is None


# ── 2. web layer: deferred is not a refresh failure ─────────────────────────

class TestWebLayer:
    @pytest.fixture
    def forward_provider(self, monkeypatch, tmp_path):
        """Route ucl_app at the WEB boundary onto a tmp future-season dir."""

        def _install(provider):
            import web.ucl_app as ucl_app

            dp = _seed_ucl_dir(tmp_path)
            _write_pointer(dp, "2026/27")
            monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
            monkeypatch.setattr(
                "football_core.runtime_support.get_data_provider", lambda b, f, l=None: provider
            )
            return ucl_app

        return _install

    def test_web_deferred_report_not_stale(self, forward_provider):
        import web.ucl_app as ucl_app

        ucl_app = forward_provider(_EmptyProvider())
        ucl_app._fetch_live_data()

        rep = ucl_app._refresh_report
        assert rep["attempted"] is True
        # D-13: the derived failure travels through the ledger — the UI reads
        # `deferred` to render "not published yet" instead of "refresh failed".
        assert rep["success"] is False
        assert rep["stale"] is True
        assert rep["deferred"] is True
        assert rep["reason"] == "deferred/provider-empty"
        assert rep["status"] == "deferred"
        assert rep["error"] is None
        assert rep["active_season"] == "2026/27"
        assert rep["provider"] == "_EmptyProvider"

    def test_web_real_failure_still_stale(self, forward_provider):
        import web.ucl_app as ucl_app

        ucl_app = forward_provider(
            _EmptyProvider(last_error="HTTP 400: Your API token is invalid.")
        )
        ucl_app._fetch_live_data()

        rep = ucl_app._refresh_report
        assert rep["attempted"] is True
        assert rep["success"] is False
        assert rep["stale"] is True
        assert rep["error"]
        assert "deferred" not in rep
        assert rep.get("status") == "skip"

    def test_web_historical_success_report_ok(self, tmp_path, monkeypatch):
        """2025/26 successful live refresh keeps status="ok", non-stale."""
        import web.ucl_app as ucl_app

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2025/26")
        monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
        event = au.ucl_league_events(dp, n=1)[0]
        monkeypatch.setattr(
            "football_core.runtime_support.get_data_provider",
            lambda b, f, l=None: _SucceedingProvider(event),
        )
        ucl_app._fetch_live_data()

        rep = ucl_app._refresh_report
        assert rep["success"] is True
        assert rep["stale"] is False
        assert rep.get("status") == "ok"
        assert "deferred" not in rep
        assert rep["error"] is None


# ── 3. UI carrier copy (source-level, per repo convention) ──────────────────

class TestUiCarrierCopy:
    def test_ucl_js_renders_accurate_deferred_message(self):
        src = (WEB_STATIC / "ucl.js").read_text(encoding="utf-8")
        assert "Provider has no published match data yet" in src
        assert "provider_empty" in src
        assert "refresh.deferred" in src
        # The benign branch must be checked BEFORE the stale branch so a
        # deferred response never falls through to the failure message.
        assert src.index("refresh.deferred") < src.index("live refresh failed")

    def test_ucl_js_keeps_real_stale_message(self):
        """02-08 relocated the stale copy into the shared carrier.

        The exact string must still exist once, and UCL must *delegate* to it
        via the shared renderer rather than hardcoding a second copy.
        """
        shared = (WEB_STATIC / "shared.js").read_text(encoding="utf-8")
        assert "STALE - live refresh failed; showing last known data" in shared
        ucl = (WEB_STATIC / "ucl.js").read_text(encoding="utf-8")
        assert "./shared.js" in ucl
        assert "renderAvailabilityBanner" in ucl
        assert "STALE - live refresh failed; showing last known data" not in ucl

    def test_shared_panel_renders_notice_line(self):
        src = (WEB_STATIC / "shared.js").read_text(encoding="utf-8")
        assert "acq-notice-line" in src
        assert "acq.notice" in src

    def test_wc_js_delegates_stale_copy_to_shared(self):
        """02-08 also routes the WC banner/stale copy through the shared carrier.

        WC must import the shared renderer and must not carry a private copy of
        the stale string or the shared notice-line markup (single source of copy).
        """
        src = (WEB_STATIC / "wc.js").read_text(encoding="utf-8")
        assert "./shared.js" in src
        assert "renderAvailabilityBanner" in src
        assert "STALE - live refresh failed; showing last known data" not in src
        assert "acq-notice-line" not in src