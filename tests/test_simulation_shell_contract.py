"""Phase 12D — shared Simulation Shell contract + state-transition pins.

Every pin in this file is source-structure only (plain string/regex against
web/static/*.js), mirroring test_ui_normalization_shell.py — no server boot,
no headless browser. Two responsibilities:

1. State-transition / regression pins (12D.9): the shared shell owns the
   five-state machine (available / not_needed / running / failed / completed
   with the hasResults gate), the launcher is never emitted under
   not_needed, the provenance footer always follows resultSlot and whatIf,
   competitions pass resultSlot callbacks, WC retains its decided-season
   copy + Bracket/Overview pointers, LaLiga's refreshLive is isolated from
   /simulation, and no private control plumbing or duplicate What-If UI
   survived the migration.
2. Architecture pins (12D.10): exactly one shell implementation, exactly
   one shared popup, `.sim-provenance` styled/shaped only in
   shared.js/shared.css, and the state machine defaulting lives in the
   shell — competitions feed state, they do not re-implement the machine.
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

# renderSimulationShell body (pure HTML generator) only — everything between
# its declaration and bindSimulationShell's declaration.
SHELL = SHARED.split("function renderSimulationShell(", 1)[1] \
    .split("\nfunction bindSimulationShell(", 1)[0]
BIND = SHARED.split("function bindSimulationShell(", 1)[1]


def _imports(src):
    """Named-import block up to `} from "./shared.js"`."""
    return src.split("import {", 1)[1].split('} from "./shared.js"', 1)[0]


def _fn_body(src, decl):
    """Body of the first function matching decl, up to the next top-level
    function declaration. Mirrors the split convention of the sibling
    normalization tests (tolerates CRLF via "\nfunction ")."""
    tail = src.split(decl, 1)[1]
    return tail.split("\nfunction ", 1)[0]


# ── 12D.9 state-transition pins ──────────────────────────────────────

def test_shell_branches_on_all_five_states():
    """The shared shell is the single state machine: it derives
    availability/request_state/hasResults and branches for not_needed /
    running / failed / idle-completed. Both defaulting and the idle/running/
    failed copy live here, not in the competitions."""
    assert 'const availability = st.availability || "available";' in SHELL
    assert 'const req = st.request_state || "not_requested";' in SHELL
    assert "const hasResults = !!st.hasResults;" in SHELL
    assert 'const notNeeded = availability === "not_needed";' in SHELL
    for marker in ('"not_needed"', '"running"', '"failed"'):
        assert marker in SHELL
    # The three user-visible state lines are defined once in shared.js and
    # referenced inside renderSimulationShell's own body.
    assert SHARED.count("_SIM_IDLE_LINE") == 2      # const def + shell use
    assert SHARED.count("_SIM_RUNNING_LINE") == 2   # const def + shell use
    assert "_SIM_IDLE_LINE" in SHELL and "_SIM_RUNNING_LINE" in SHELL
    assert "_SIM_FAILED_BODY" in SHELL


def test_shell_launcher_disabled_while_running():
    assert '_SIM_RUNNING_LINE' in SHELL
    assert 'id="simLaunchBtn"' in SHELL
    assert '(running ? " disabled" : "")' in SHELL


def test_shell_launcher_never_under_not_needed():
    """Structure pin: the not_needed boolean is computed, the launcher is
    emitted only inside the `if (!notNeeded)` guard, and the module-supplied
    notNeeded block renders separately (after, outside the guard)."""
    assert SHELL.count('id="simLaunchBtn"') == 1
    assert SHELL.count("o.notNeeded(") == 1
    assert SHELL.count("o.resultSlot(") == 1
    assert SHELL.index('availability === "not_needed"') \
        < SHELL.index("if (!notNeeded) {")
    assert SHELL.index("if (!notNeeded) {") \
        < SHELL.index('id="simLaunchBtn"')
    assert SHELL.index('id="simLaunchBtn"') < SHELL.index("o.notNeeded(")


def test_bind_disables_launcher_while_running():
    """bindSimulationShell mirrors the running-state disable so a repeat
    bind cannot silently enable a running simulation's button."""
    assert 'st.availability !== "not_needed" && st.request_state === "running"' in BIND
    assert "btn.disabled = running;" in BIND
    assert "if (btn.disabled) return;" in BIND


def test_every_competition_imports_and_calls_the_shared_shell():
    for src, name in ((UCL, "ucl.js"), (WC, "wc.js"), (LALIGA, "laliga.js")):
        imps = _imports(src)
        assert "renderSimulationShell" in imps, name
        assert "bindSimulationShell" in imps, name
        assert "renderSimulationShell(" in src, name
        assert "bindSimulationShell(" in src, name


def test_failed_branch_never_fabricates_result_slot():
    """A failed run shows the failed provenance banner only; resultSlot is
    gated behind showResults, which excludes the failed/not_needed paths, so
    no fabricated odds can appear under a failed state."""
    assert SHELL.count("o.resultSlot(") == 1
    assert '(req === "completed" || req === "running")' in SHELL
    assert SHELL.index("o.resultSlot(") < SHELL.index("else if (req === \"failed\") {")
    assert SHELL.index("o.resultSlot(") < SHELL.index("_simProvenanceFailed()")
    assert 'h += _simProvenanceFailed();' in SHELL


def test_every_competition_supplies_result_slot():
    for src, name in ((UCL, "ucl.js"), (WC, "wc.js"), (LALIGA, "laliga.js")):
        assert src.count("resultSlot:") == 1, name


def test_provenance_always_after_result_and_what_if():
    """Canonical order in the shell body: title/purpose/state -> launcher ->
    resultSlot -> whatIf -> provenance footer. Pinned by call-site index."""
    assert SHELL.count("o.whatIf(") == 1
    assert SHELL.count("_simProvenanceFooter(") == 2  # decided + preserved-run
    assert SHELL.index("o.resultSlot(") < SHELL.index("o.whatIf(")
    assert SHELL.index("o.whatIf(") < SHELL.index("_simProvenanceFooter(")


def test_what_if_gate_requires_completed_with_results():
    assert '!notNeeded && req === "completed" && hasResults' in SHELL


def test_laliga_refresh_live_isolated_from_simulation():
    """12D.8 regression pin (CRITICAL): LaLiga's live refresh is
    factual-only. It re-fetches /api/data and re-renders; it never re-fetches
    /api/simulation and never re-applies a simulation payload, so a held sim
    result survives ordinary refreshes. (Its explanatory comment mentions the
    endpoint textually, so absence is pinned on the fetch expression, not the
    word 'simulation'.)"""
    rl = _fn_body(LALIGA, "async function refreshLive()")
    assert 'API + "/data"' in rl
    assert rl.count("safeJson(") == 1            # exactly the /data fetch
    assert 'API + "/simulation"' not in rl       # no /simulation re-fetch
    assert "applySimulation" not in rl           # no re-apply
    assert "render();" in rl
    # Across the whole module, /simulation is fetched only by loadAll
    # (boot/season switch) and onComplete (a fresh completed run).
    assert LALIGA.count('API + "/simulation"') == 2
    # The live-reload hook registered with the shared manager is refreshLive.
    assert LALIGA.count("{ reload: refreshLive }") == 1


def test_laliga_render_rerenders_sim_from_held_state():
    """Completed-competition / live-refresh survival pin: the Simulation tab
    is re-rendered by render() from held appState.sim / appState.simMeta —
    never from a fetch. refreshLive must not touch those held fields."""
    rl = _fn_body(LALIGA, "async function refreshLive()")
    assert "appState.sim =" not in rl            # never re-applies a run
    assert "appState.simMeta =" not in rl
    html = _fn_body(LALIGA, "function _simulationHtml()")
    cfg = _fn_body(LALIGA, "function _simulationShellConfig()")
    assert "renderSimulationShell(cfg.state, cfg.opts)" in html
    assert "safeJson" not in html and "fetch(" not in html
    # The config derives shell state from held appState (sim / simMeta /
    # data); its only fetches are the onComplete rehydration callback.
    assert "appState.sim" in cfg
    assert cfg.count("safeJson(") == 2


def test_laliga_state_maps_availability_and_gates_what_if():
    assert '"not_needed"' in LALIGA
    assert "notNeeded:" in LALIGA
    # The in-tab what-if is passed only for a live (not decided) season.
    assert 'whatIf: availability !== "not_needed" ? _simulationWhatIf : null' in LALIGA
    assert LALIGA.count("function _simulationWhatIf()") == 1


def test_laliga_decided_season_preserves_prior_projections():
    assert "The season is fully played out; the final table is a matter of record, not projection." in LALIGA
    assert "The archived projections below are from a run completed earlier." in LALIGA


def test_wc_decided_fact_and_bracket_overview_pointers():
    """WC retains the canonical completed-season copy and the notNeeded block
    points at Bracket (real tree) and Overview (final standings)."""
    assert "Simulation is not needed" in WC
    assert "notNeeded:" in WC
    assert "The tournament is decided" in WC
    assert "See the Bracket tab for the real knockout tree and the Overview tab for the final standings." in WC
    assert 'class="sim-provenance"' not in WC     # banner lives in the shell


def test_ucl_decided_season_is_factual_copy():
    assert "Season completed - results are factual." in UCL
    assert "Per-match What-If" in UCL             # pointer to bracket match what-if


def test_no_leftover_private_control_plumbing():
    # UCL inline sim controls / polling / entry points are gone.
    for token in ("uclSimStartBtn", "uclSimCustom", "uclSimSeed",
                  "_uclSimPolling", "startUclSimulation",
                  "bindSimulationControls", "_selectedRuns"):
        assert token not in UCL, token
    assert "__simulateAllRemaining" not in WC
    # LaLiga modal what-if rerun entry + live-refresh widgets removed.
    for token in ("openWhatIf", "whatifOpenBtn", "rofRefreshBtn",
                  "setUpRefreshBtn"):
        assert token not in LALIGA, token


def test_exactly_one_what_if_entry_remains_per_competition():
    """LaLiga keeps exactly one whole-competition what-if (the in-tab panel);
    UCL and WC pass no whatIf slot to the shell (their What-If is per-match,
    only on the Bracket tab)."""
    assert LALIGA.count("whatIf:") == 1
    assert LALIGA.count("function _simulationWhatIf()") == 1
    assert "whatIf:" not in UCL
    assert "whatIf:" not in WC


# ── 12D.10 architecture pins ─────────────────────────────────────────

def test_exactly_one_shell_implementation():
    assert SHARED.count("function renderSimulationShell(") == 1
    assert SHARED.count("function bindSimulationShell(") == 1
    for src, name in ((UCL, "ucl.js"), (WC, "wc.js"), (LALIGA, "laliga.js")):
        assert "function renderSimulationShell" not in src, name
        assert "function bindSimulationShell" not in src, name


def test_exactly_one_shared_popup():
    """showSimPopup + its helpers are declared only in shared.js; the three
    competitions never even reference the popup — bindSimulationShell wires it."""
    assert SHARED.count("function showSimPopup(") == 1
    assert SHARED.count("async function _startSim(") == 1
    assert SHARED.count("function createSimPopup(") == 1
    for src, name in ((UCL, "ucl.js"), (WC, "wc.js"), (LALIGA, "laliga.js")):
        assert "showSimPopup" not in src, name
        assert "function createSimPopup" not in src, name
        assert "async function _startSim" not in src, name
        assert "setInterval" not in src, name    # no private polling loop
        assert "simPopupOverlay" not in src, name  # no comp-owned popup DOM


def test_no_direct_simulate_post_outside_shared_poll():
    """The POST /simulate path exists exactly once, inside the shared popup;
    competitions route through it via bindSimulationShell, never directly."""
    assert SHARED.count('"/simulate"') == 1
    assert 'fetch(apiPrefix + "/simulate", {' in SHARED
    for src, name in ((UCL, "ucl.js"), (WC, "wc.js"), (LALIGA, "laliga.js")):
        assert '"/simulate"' not in src, name
        assert 'API + "/simulate"' not in src, name


def test_provenance_markup_only_in_shared_js():
    holders = []
    for p in sorted(WEB_STATIC.glob("*.js")):
        text = p.read_text(encoding="utf-8")
        if 'class="sim-provenance"' in text:
            holders.append(p.name)
    assert holders == ["shared.js"]
    assert SHARED.count('class="sim-provenance') == 2  # base + failed banner


def test_provenance_styles_live_in_shared_css():
    assert ".sim-provenance {" in CSS
    assert ".sim-provenance .title {" in CSS
    assert ".sim-provenance .body {" in CSS
    assert ".sim-provenance.failed {" in CSS
    # Competition-palette overrides shipped with the shell.
    assert ".competition-laliga .sim-provenance {" in CSS
    assert ".competition-worldcup .sim-provenance {" in CSS


def test_state_machine_markers_never_leak_to_competitions():
    """The rendering machine (state-line constants, showResults gate,
    provenance callers, result-slot gating) exists only in shared.js."""
    for src, name in ((UCL, "ucl.js"), (WC, "wc.js"), (LALIGA, "laliga.js")):
        for marker in ("_SIM_", "showResults", "_simProvenanceFooter",
                       "_simProvenanceFailed"):
            assert marker not in src, (name, marker)


# ── 12D.10 cross-competition trajectory pins ─────────────────────────

def test_ucl_seed_reaches_body_builder_and_compare_kept():
    assert "bodyBuilder: function(iters, seed)" in UCL
    assert "(seed != null) ? { iterations: iters, seed: seed } : { iterations: iters }" in UCL
    assert "seed: true" in UCL
    assert "presets: [1000, 5000, 10000, 100000]" in UCL
    assert "sim-team-toggle" in UCL               # team-compare toggle retained
    assert "resultSlot: _uclProjectionBlock" in UCL


def test_wc_bounds_and_non_seeded_popup():
    assert "min: 1" in WC and "max: 1000000" in WC
    assert "seed: false" in WC
    assert "bodyBuilder: iters => ({ iterations: iters })" in WC


def test_laliga_what_if_endpoint_and_iterations():
    assert 'API + "/what-if"' in LALIGA
    assert "iterations: 10000" in LALIGA          # in-tab what-if run count
    assert "iterations: iters" in LALIGA          # shell popup count


def test_laliga_per_match_insight_retained():
    """Removing the modal What-If rerun entry must not have removed per-match
    intelligence: openMatchModal still hydrates from /match/insight."""
    assert "function openMatchModal(" in LALIGA
    assert 'API + "/match/insight?match_id="' in LALIGA
    assert "Insight" in LALIGA


def test_laliga_validation_remains_in_overview():
    assert "_evalBlock" in LALIGA
    assert 'id="validationSection"' in LALIGA
    assert "tab-validation" not in LALIGA


# ── Syntax gate (mirrors the normalization suite) ────────────────────

@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("name", ["shared.js", "ucl.js", "wc.js", "laliga.js"])
def test_esm_syntax_valid(name):
    with tempfile.TemporaryDirectory() as tmp:
        mjs = Path(tmp) / (name.replace(".js", "") + ".mjs")
        mjs.write_bytes((WEB_STATIC / name).read_bytes())
        res = subprocess.run(
            ["node", "--check", str(mjs)],
            capture_output=True, text=True,
        )
        assert res.returncode == 0, res.stdout + res.stderr