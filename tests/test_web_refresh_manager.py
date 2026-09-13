"""Exchange 9C — shared refresh-manager wiring regression tests.

The manager's timing/visibility logic itself is covered by its node:test
unit suite (web/static/refresh.test.mjs). These tests (a) run that suite
when node is available and (b) pin the static structure of the wiring:
each competition module registers its live-reload hook exactly once, the
dead WC auto-poll (toggleAuto/doRefresh) and the dead UCL reloadData are
gone, and the shared shell owns exactly one manager instance and one
visibilitychange listener.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_STATIC = ROOT / "web" / "static"

SHARED = (WEB_STATIC / "shared.js").read_text(encoding="utf-8")
UCL = (WEB_STATIC / "ucl.js").read_text(encoding="utf-8")
WC = (WEB_STATIC / "wc.js").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_refresh_manager_unit_suite():
    """The manager's own fake-clock suite must stay green."""
    res = subprocess.run(
        ["node", "--test", str(WEB_STATIC / "refresh.test.mjs")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stdout + res.stderr


# ── Static contract checks (structure, not behavior) ─────────────────

def test_each_module_registers_live_reload_exactly_once():
    assert UCL.count("configureCompetitionRefresh(") == 1
    assert WC.count("configureCompetitionRefresh(") == 1


def test_shared_shell_owns_one_manager_and_one_visibility_listener():
    assert SHARED.count("createRefreshManager(") == 1
    assert SHARED.count('addEventListener("visibilitychange"') == 1


def test_registry_has_per_competition_live_refresh_config():
    assert "liveRefresh: { enabled: true, intervalMs: 45000, refreshOnActivation: true }" in SHARED
    assert "liveRefresh: { enabled: true, intervalMs: 90000, refreshOnActivation: true }" in SHARED


def test_wc_dead_auto_poll_removed():
    assert "toggleAuto" not in WC
    assert "doRefresh" not in WC
    assert "autoTimer" not in WC
    assert "autoRefreshOn" not in WC


def test_ucl_dead_reload_data_removed():
    assert "reloadData" not in UCL


def test_refresh_live_captures_not_increments_generation():
    """loadAll is the ONLY generation-token incrementer; refreshLive captures
    the token and relies on _stale() guards so full loads always outrank
    live refreshes at commit time."""
    for src, name in ((UCL, "ucl.js"), (WC, "wc.js")):
        assert src.count("++_transitionGen") == 1, name
        assert "async function refreshLive()" in src, name
        assert "const gen = _transitionGen;" in src, name


def test_wrappers_exported_for_modules():
    export_section = SHARED.split("export {", 1)[1]
    for symbol in ("configureCompetitionRefresh", "activateCompetitionRefresh",
                   "requestCompetitionRefresh", "stopAllCompetitionRefresh"):
        assert symbol + "," in export_section


def test_shell_activates_and_stops_refresh_in_lifecycle():
    assert "activateCompetitionRefresh(slug)" in SHARED
    assert "stopAllCompetitionRefresh()" in SHARED
    assert "requestCompetitionRefresh(slug)" in SHARED