"""UCL refresh/status metadata is season-scoped — no cross-season leak.

Regression suite for the defect where UCL refresh status was a SINGLE
per-process global: after an explicitly-active 2026/27 deferral (HTTP 200
+ empty provider, ``status="deferred"``), the complete 2025/26 season view
inherited the 2026/27 "Provider has no published match data yet" state.

The fix keys every recorded outcome by season (display id, e.g. "2026/27"):

- the 2026/27 deferred outcome stays attached to 2026/27 only and is what
  the API serves WHILE 2026/27 is active (HTTP 200, zero matches);
- a season with NO recorded report this process (settled 2025/26) is served
  a store-truthful synthesized entry — ``attempted=False``, ``success=True``,
  ``stale=False``, ``deferred=False``, ``status="ok"``. Switching
  2026/27 -> 2025/26 -> 2026/27 never reuses the other season's status;
- a REAL transport/provider failure still surfaces as stale, scoped to the
  season it happened on;
- the legacy ``last_refresh.json["ucl"]`` entry and the newer
  ``"ucl_seasons"`` map both load, and reports recorded THIS process always
  win over file state;
- an explicit snapshot session keeps serving its truthful skipped report.

No test mutates the repository's real data — every scenario runs against a
fresh tmp copy of the UCL data dir and a tmp freshness ledger.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import pytest

import arch_util as au

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


# ── stub providers ──────────────────────────────────────────────────────────

class _EmptyProvider:
    """Successfully-answering provider: HTTP 200 with zero matches."""

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
def isolated_season_refresh_state(tmp_path, monkeypatch):
    """Sandbox the ledger and reset ALL UCL refresh state per test.

    Resets the umbrella report, the season-scoped store, the seed flag,
    the process-wide lazy-gates and the startup decision so no test can
    inherit another test's (or the repo ledger's) refresh status.
    """
    import web.competitions as competitions
    import web.startup as startup
    import web.ucl_app as ucl_app

    monkeypatch.setattr(
        ucl_app, "_refresh_report_path", lambda: tmp_path / "last_refresh.json"
    )
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)
    monkeypatch.delenv("FOOTBALL_PRELOAD_ALL", raising=False)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    startup._last_decision = startup.StartupDecision("auto", "")
    competitions.reset_lazy_gates()
    ucl_app._refresh_report = {}
    ucl_app._refresh_reports = {}
    ucl_app._refresh_reports_seeded = False
    yield
    startup._last_decision = None
    competitions.reset_lazy_gates()
    ucl_app._refresh_report = {}
    ucl_app._refresh_reports = {}
    ucl_app._refresh_reports_seeded = False


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


# ── served API: the future-season deferral stays on the future season ───────

class TestSeasonScopedServedRefresh:
    def test_active_2026_27_deferred_served_through_api(self, tmp_path, monkeypatch):
        """2026/27 active + HTTP 200 + 0 matches => deferred, still served."""
        import web.common
        import web.ucl_app as ucl_app
        from fastapi.testclient import TestClient

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2026/27")
        monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
        provider = _EmptyProvider()
        monkeypatch.setattr(
            web.common, "get_data_provider", lambda b, f, l=None: provider
        )

        with TestClient(ucl_app.ucl_app) as client:
            r = client.get("/api/data")
            assert r.status_code == 200
            payload = r.json()
            assert payload["n_played"] == 0
            refresh = payload["refresh"]
            assert refresh["active_season"] == "2026/27"
            assert refresh["attempted"] is True
            assert refresh["deferred"] is True
            assert refresh["status"] == "deferred"
            assert refresh["reason"] == "provider_empty"
            assert refresh["stale"] is False

        assert provider.calls >= 1, "lazy acquisition actually fired"
        assert provider.season == 2026, "the future season was requested explicitly"

    def test_switch_2026_27_to_2025_26_never_inherits_deferred(
        self, tmp_path, monkeypatch
    ):
        """2026/27 deferred -> 2025/26 store-truth -> back: statuses never mix."""
        import web.common
        import web.ucl_app as ucl_app
        from fastapi.testclient import TestClient

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2026/27")
        monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
        monkeypatch.setattr(
            web.common, "get_data_provider",
            lambda b, f, l=None: _EmptyProvider(),
        )

        with TestClient(ucl_app.ucl_app) as client:
            # 2026/27 active: the deferred state belongs here.
            first = client.get("/api/data").json()["refresh"]
            assert first["status"] == "deferred"
            assert first["active_season"] == "2026/27"

            # Switch to the settled 2025/26 season: no deferred leak, a
            # store-truthful synthesized entry instead.
            switched = client.post("/api/season", json={"season": "2025/26"})
            assert switched.status_code == 200
            back = client.get("/api/data").json()
            assert back["season"] == "2025/26"
            refresh = back["refresh"]
            assert refresh["active_season"] == "2025/26"
            assert refresh.get("deferred") is not True
            assert refresh.get("reason") != "provider_empty"
            assert refresh["stale"] is False
            assert refresh["status"] == "ok"
            assert refresh["attempted"] is False
            assert refresh["synth"] is True

            # Switch back: 2026/27 still shows its OWN deferred state.
            re = client.post("/api/season", json={"season": "2026/27"})
            assert re.status_code == 200
            again = client.get("/api/data").json()["refresh"]
            assert again["status"] == "deferred"
            assert again["active_season"] == "2026/27"

        # The three statuses seen across the walk NEVER mix season-to-season.
        assert [first["status"], back["refresh"]["status"], again["status"]] == (
            ["deferred", "ok", "deferred"]
        )

    def test_real_failure_still_stale_scoped_to_its_season(
        self, tmp_path, monkeypatch
    ):
        """A genuine transport failure stays stale — but only for ITS season."""
        import web.common
        import web.ucl_app as ucl_app
        from fastapi.testclient import TestClient

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2026/27")
        monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
        monkeypatch.setattr(
            web.common, "get_data_provider",
            lambda b, f, l=None: _EmptyProvider(
                last_error="HTTP 400: Your API token is invalid."
            ),
        )

        with TestClient(ucl_app.ucl_app) as client:
            r = client.get("/api/data")
            assert r.status_code == 200
            refresh = r.json()["refresh"]
            assert refresh["status"] == "skip"
            assert refresh["stale"] is True
            assert "HTTP 400" in refresh["error"]
            assert refresh.get("deferred") is not True

        # The same process switch presents 2025/26 as store-truth, not as the
        # failed season.
        from web.ucl_app import _refresh_report_for

        other = _refresh_report_for("2025/26")
        assert other["active_season"] == "2025/26"
        assert other["stale"] is False
        assert other.get("deferred") is not True
        assert other["status"] == "ok"
        assert other["synth"] is True

    def test_snapshot_skipped_report_still_served_as_is(self, tmp_path, monkeypatch):
        """Explicit snapshot sessions keep serving the truthful skipped report."""
        import web.startup as startup
        import web.ucl_app as ucl_app
        from fastapi.testclient import TestClient

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2025/26")
        monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
        startup._last_decision = startup.StartupDecision("snapshot", "")

        with TestClient(ucl_app.ucl_app) as client:
            refresh = client.get("/api/data").json()["refresh"]
            assert refresh.get("skipped_reason") == "snapshot mode selected at startup"
            assert refresh.get("attempted") is False

    def test_synthesized_report_reflects_completed_season(self, tmp_path, monkeypatch):
        """2025/26 synthesis reports the real played count (144/144)."""
        import web.ucl_app as ucl_app

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2025/26")
        monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
        report = ucl_app._synthesize_season_report("2025/26")
        assert report["status"] == "ok"
        assert report["stale"] is False
        assert report["attempted"] is False
        assert report["n_matches"] == 144, "the complete season is fully played"


# ── persisted ledger: backward-compatible seeding ───────────────────────────

class TestLedgerSeeding:
    def test_legacy_ucl_entry_loads_under_its_active_season(self, tmp_path):
        """The single legacy 'ucl' entry folds in keyed by active_season."""
        import web.ucl_app as ucl_app

        dp = _seed_ucl_dir(tmp_path)
        (tmp_path / "last_refresh.json").write_text(json.dumps({
            "ucl": {
                "active_season": "2026/27", "attempted": True, "success": True,
                "error": None, "stale": False, "deferred": True,
                "reason": "provider_empty", "status": "deferred",
                "last_refresh": "2026-01-01T00:00:00+00:00",
                "mode": "ucl.data_providers.bsd_provider",
                "n_matches": 0, "n_updated": 0, "provider": "BSDProvider",
            },
        }), encoding="utf-8")

        served = ucl_app._refresh_report_for("2026/27")
        assert served["active_season"] == "2026/27"
        assert served["status"] == "deferred"

    def test_seasons_map_forward_compatible(self, tmp_path):
        """The newer 'ucl_seasons' map loads per season without legacy."""
        import web.ucl_app as ucl_app

        dp = _seed_ucl_dir(tmp_path)
        (tmp_path / "last_refresh.json").write_text(json.dumps({
            "ucl_seasons": {
                "2026/27": {
                    "active_season": "2026/27", "attempted": True,
                    "success": True, "deferred": True, "reason": "provider_empty",
                    "status": "deferred", "stale": False,
                    "last_refresh": "2026-01-02T00:00:00+00:00",
                },
            },
        }), encoding="utf-8")

        served = ucl_app._refresh_report_for("2026/27")
        assert served["status"] == "deferred"
        assert served["last_refresh"] == "2026-01-02T00:00:00+00:00"

    def test_inprocess_report_wins_over_file_state(self, tmp_path, monkeypatch):
        """A fetch recorded THIS process overrides seeded file state."""
        import web.common
        import web.ucl_app as ucl_app

        dp = _seed_ucl_dir(tmp_path)
        _write_pointer(dp, "2025/26")
        monkeypatch.setattr(ucl_app, "DATA_DIR", dp)
        (tmp_path / "last_refresh.json").write_text(json.dumps({
            "ucl": {
                "active_season": "2025/26", "attempted": True, "success": False,
                "error": "old file failure", "stale": True, "status": "skip",
                "last_refresh": "2025-12-31T00:00:00+00:00",
            },
        }), encoding="utf-8")

        # Before an in-process fetch, the seeded stale entry IS the truth for
        # that season (real failure semantics preserved).
        seeded = ucl_app._refresh_report_for("2025/26")
        assert seeded["stale"] is True

        # An in-process successful fetch then wins.
        event = au.ucl_league_events(dp, n=1)[0]
        monkeypatch.setattr(
            web.common, "get_data_provider",
            lambda b, f, l=None: _SucceedingProvider(event),
        )
        ucl_app._fetch_live_data()

        served = ucl_app._refresh_report_for("2025/26")
        assert served["status"] == "ok"
        assert served["stale"] is False