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
CSS = (WEB_STATIC / "shared.css").read_text(encoding="utf-8")


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


# ── Phase 12B — LaLiga exclusive background ──────────────────────────

def test_laliga_body_background_uses_its_own_image():
    block = CSS.split(".competition-laliga {", 1)[1].split("\n}", 1)[0]
    assert 'url("images/laliga.webp")' in block
    assert "linear-gradient" in block          # darkening overlay for readability
    assert "fixed no-repeat" in block


def test_laliga_landing_card_background_uses_its_own_image():
    block = CSS.split(".lc-card.laliga {", 1)[1].split("\n}", 1)[0]
    assert 'url("images/laliga.webp")' in block


def test_background_paths_are_relative_and_never_absolute():
    assert "Pictures" not in CSS
    assert "laliga_oil_paint" not in CSS
    assert "C:\\" not in CSS
    assert "C:/" not in CSS
    assert ":\\" not in CSS and file_drive_residue_check(CSS)


def file_drive_residue_check(css):
    # No windows drive-letter absolute path residue ("x:\..." or "x:/...").
    import re
    return not re.search(r"[a-zA-Z]:[\\/]", css)


def test_laliga_background_image_ships_in_static_assets():
    assert (WEB_STATIC / "images" / "laliga.webp").is_file()


# ── Phase 12B — Overview parity ──────────────────────────────────────

def test_laliga_overview_uses_shared_stats_strip():
    body = LALIGA.split("function _overviewHtml()", 1)[1].split("\nfunction ", 1)[0]
    assert 'class="stats-row"' in body
    assert 'class="stat-card"' in body
    assert "Season" in body and "Matchday" in body


def test_laliga_overview_uses_shared_eval_tables():
    assert "Top of the Table" in LALIGA
    assert "Signal Evaluation" in LALIGA
    assert 'class="eval-table"' in LALIGA
    assert "ol-signal-list" not in LALIGA


def test_laliga_overview_drops_private_primitives():
    assert "section-title" not in LALIGA
    assert "cteam" not in LALIGA


def test_laliga_acquisition_panel_is_wired_not_dead():
    """The #acqHost div was rendered empty (renderAcquisitionPanel imported
    but never called). render() must fill it on every render."""
    render_body = LALIGA.split("function render()", 1)[1].split("\nfunction ", 1)[0]
    assert "renderAcquisitionPanel(acqHost" in render_body
    assert 'getElementById("acqHost")' in render_body


# ── Phase 12B — Simulation layout contract ───────────────────────────

def test_laliga_sim_controls_lead_results_provenance_trails():
    sim = LALIGA.split("function _simulationHtml()", 1)[1].split("\nfunction ", 1)[0]
    ctrl = sim.index("Simulation Controls")
    summary = sim.index("Projected Championship")
    prov = sim.index("sim-provenance")
    assert ctrl < summary, "controls must render before result summaries"
    # Provenance trails the result blocks; the what-if and live-refresh
    # sections are competition-specific slots that render after it.
    assert summary < prov, "provenance must come after the results"


def test_laliga_sim_uses_shared_table_and_bar_primitives():
    sim = LALIGA.split("function _simulationHtml()", 1)[1].split("\nfunction ", 1)[0]
    assert 'class="eval-table"' in sim
    assert 'class="champ-bar-row"' in sim
    assert 'class="cname"' in sim


def test_ucl_sim_controls_lead_results():
    sim = UCL.split("async function renderSimulation()", 1)[1].split("\nfunction ", 1)[0]
    assert sim.rindex('id="uclSimStartBtn"') < sim.rindex("_uclProjectionBlock()")


def test_wc_sim_banners_use_shared_provenance_class():
    sim = WC.split("function renderSimulation()", 1)[1].split("\nfunction ", 1)[0]
    assert 'class="sim-provenance"' in sim
    assert 'class="sim-provenance failed"' in sim
    assert "Simulation is not needed" in sim


# ── Phase 12B — shared primitives shipped in the stylesheet ──────────

def test_shared_css_primitives_exist():
    for sel in (".sim-provenance", ".phase-card", ".status-btn.sim-preset.active",
                ".pred-cell", ".form-field"):
        assert sel in CSS, sel
    assert "\n.m-sub {" in CSS          # bare .m-sub exists, not only the .modal override
    assert '\n.dim { color:' in CSS


def test_new_primitives_are_competition_palette_bounded():
    assert ".competition-laliga .sim-provenance" in CSS
    assert ".competition-worldcup .sim-provenance" in CSS
    assert ".competition-laliga .phase-card" in CSS
    assert ".competition-worldcup .phase-card" in CSS