"""Phase 12A — cross-competition UI/UX normalization static contract.

All three competitions must expose the shared primary shell (Overview →
Standings → Matches/Bracket/→ Simulation) with Simulation as a first-class
dedicated tab. LaLiga's pure-Elo Validation is preserved as an Overview
section — never a top-level tab. WC no longer ships its own third copy of the
simulation popup; it reuses the shared popup with WC bounds. Structure-only
pins, mirroring test_web_refresh_manager.py — no server boot, no behavior.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_STATIC = ROOT / "web" / "static"

SHARED = (WEB_STATIC / "shared.js").read_text(encoding="utf-8")
UCL = (WEB_STATIC / "ucl.js").read_text(encoding="utf-8")
WC = (WEB_STATIC / "wc.js").read_text(encoding="utf-8")
LALIGA = (WEB_STATIC / "laliga.js").read_text(encoding="utf-8")


# ── Shared shell contract ─────────────────────────────────────────────

def test_registry_exposes_simulation_as_first_class_tab_for_all():
    # worldcup + ucl share the knockout 4-tab order; laliga uses Fixtures
    # for its match tab. Simulation is a primary tab everywhere.
    assert SHARED.count('tabs: ["Overview", "Standings", "Bracket", "Simulation"]') == 2
    assert 'tabs: ["Overview", "Standings", "Fixtures", "Simulation"]' in SHARED


def test_shell_builds_tabs_generically_from_registry():
    assert "comp.tabs.map" in SHARED


def test_shell_marks_tablist_and_selected_state():
    # a11y: tab bar is a tablist with per-button aria-selected kept in sync
    # on switch (attribute-only, no focus-trap rewrite of the shell).
    assert 'role="tab"' in SHARED
    assert 'aria-selected' in SHARED
    assert 'setAttribute("aria-selected"' in SHARED


def test_shared_popup_bounds_are_competition_configurable():
    assert "opts.min" in SHARED
    assert "opts.max" in SHARED
    assert "opts.presets" in SHARED


# ── Per-module simulation tab ─────────────────────────────────────────

def test_every_module_renders_a_dedicated_simulation_tab():
    for src, name in ((WC, "wc.js"), (UCL, "ucl.js"), (LALIGA, "laliga.js")):
        assert "tab-simulation" in src, name


def test_ucl_simulation_isolated_from_live_refresh():
    """renderSimulation is called from loadAll (boot/season switch) but must
    NOT be re-rendered by refreshLive — the sim tab DOM survives ordinary
    refreshes so a completed run is never wiped by a quiet poll."""
    assert "renderSimulation" in UCL
    body = UCL.split("async function refreshLive()", 1)[1]
    body = body.split("\nfunction ", 1)[0]
    assert "renderSimulation" not in body


def test_wc_simulation_isolated_from_live_refresh():
    assert "renderSimulation" in WC
    body = WC.split("async function refreshLive()", 1)[1]
    body = body.split("\nfunction ", 1)[0]
    assert "renderSimulation" not in body


def test_wc_uses_shared_popup_no_duplicate():
    assert "function startSimulation" not in WC
    assert "simPopupOverlay" not in WC          # WC-local popup DOM removed
    assert "showSimPopup" in WC                 # reuses the shared popup


def test_wc_keeps_its_sim_entry_point_and_bounds():
    assert "window.__simulateAllRemaining" in WC
    assert "max: 1000000" in WC
    assert "min: 1" in WC


def test_wc_completion_renders_sim_tab_after_simmeta_update():
    """Regression for the Agent C finding: the Simulation tab must reflect a
    COMPLETED run in-session, not only after competition re-entry.

    1. Pre-run state: loadAll itself renders the sim tab on boot/reload.
    2. Completion fetches and commits simMeta.
    3. renderSimulation() is invoked AFTER the simMeta assignment.
    4. It reflects the run without re-entry: one loadAll, and it runs BEFORE
       the sim fetch — the render that follows the simMeta write is the only
       thing that refreshes the tab."""
    cb = WC.split("window.__simulateAllRemaining = function()", 1)[1]
    cb = cb.split("window.__openWhatIf", 1)[0]

    assert "onComplete: async function()" in cb
    assert "appState.simMeta = simResp.simulation_meta || null;" in cb
    assert cb.count("await loadAll();") == 1
    assert cb.index("appState.simMeta = simResp.simulation_meta || null;") \
        > cb.index("const gen = await loadAll();")
    assert cb.index("renderSimulation();") \
        > cb.index("appState.simMeta = simResp.simulation_meta || null;")

    load_all_body = WC.split("async function loadAll()", 1)[1]
    load_all_body = load_all_body.split("async function refreshLive()", 1)[0]
    assert "renderSimulation();" in load_all_body


# ── LaLiga: Validation relocated, sim controls wired on first render ──

def test_laliga_validation_is_an_overview_section_not_a_tab():
    assert "tab-validation" not in LALIGA
    assert "validationSection" in LALIGA
    assert "_evalBlock" in LALIGA
    assert 'getElementById("validationSection")' in LALIGA


def test_laliga_binds_simulation_controls_on_every_render():
    """Fix for the first-visit bug: bindSimulation() is invoked from render(),
    not only from the sim-completion callback, so the Simulation tab's
    controls work before any run has completed."""
    render_body = LALIGA.split("function render()", 1)[1]
    render_body = render_body.split("\nfunction ", 1)[0]
    assert "bindSimulation()" in render_body


# ── Syntax gate for the edited ES modules ─────────────────────────────

@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("name", ["shared.js", "ucl.js", "wc.js", "laliga.js"])
def test_esm_syntax_valid(name):
    """node --check parses ESM only when the extension is .mjs; copy and
    check each edited module so a broken edit fails here, not in a browser."""
    with tempfile.TemporaryDirectory() as tmp:
        mjs = Path(tmp) / (name.replace(".js", "") + ".mjs")
        mjs.write_bytes((WEB_STATIC / name).read_bytes())
        res = subprocess.run(
            ["node", "--check", str(mjs)],
            capture_output=True, text=True,
        )
        assert res.returncode == 0, res.stdout + res.stderr