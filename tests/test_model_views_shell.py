"""Prediction Engine views — landing card routing + Elo/blend Overview views.

Structure-only pins, mirroring test_ui_normalization_shell.py: source substrings
plus a node --check syntax gate (no server boot, no headless browser). Covers
the four landing feature cards becoming real activators (data-focus + CTA +
keyboard path), the shared pending-focus replay, and the two real data views
(renderEloView / renderBlendView) mounted by all three competition modules.
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

# The Prediction Engine section of renderLanding() — the four feature cards.
CARDS = SHARED.split('ls-title">Prediction Engine', 1)[1] \
    .split('getElementById("statusBar")', 1)[0]


def test_shared_exposes_elo_and_blend_view_renderers():
    assert "function renderEloView(state)" in SHARED
    assert "function renderBlendView(state)" in SHARED
    assert "async function loadModelViews(apiPrefix)" in SHARED
    assert 'id="viewElo"' in SHARED          # stable scroll anchors
    assert 'id="viewBlend"' in SHARED
    # Honest empty states, never a fabricated rating or blend weight.
    assert "No Elo snapshot available yet." in SHARED
    assert 'const cold = !signals.length || status === "cold_start";' in SHARED


def test_prediction_engine_cards_are_clickable_activators():
    assert CARDS.count('role="link"') == 4
    assert CARDS.count('tabindex="0"') == 4
    assert CARDS.count('class="lfc-cta"') == 4
    assert CARDS.count('data-focus="elo"') == 1
    assert CARDS.count('data-focus="blend"') == 1
    assert CARDS.count('data-focus="simulation"') == 2
    assert CARDS.count('data-route="/worldcup"') == 3
    # What-If Analysis routes to LaLiga — the only app with a What-If UI.
    assert 'data-route="/laliga" data-focus="simulation"' in CARDS


def test_pending_focus_is_captured_and_replayed():
    assert 'let pendingFocus = "";' in SHARED
    assert 'pendingFocus = el.dataset.focus || "";' in SHARED
    assert "function applyPendingFocus(" in SHARED
    # simulation -> activate the tab; elo/blend -> reveal the Overview section
    assert '.tab-btn[data-tab="simulation"]' in SHARED
    assert 'focus === "elo" ? "viewElo" : focus === "blend" ? "viewBlend"' in SHARED
    # keyboard parity for the div activators (Enter/Space)
    assert 'addEventListener("keydown"' in SHARED
    assert 'e.target.closest("[data-route][data-focus]")' in SHARED


def test_every_competition_mounts_both_views_in_overview():
    for src, name in ((WC, "wc.js"), (UCL, "ucl.js"), (LALIGA, "laliga.js")):
        imps = src.split("import {", 1)[1].split('} from "./shared.js"', 1)[0]
        for sym in ("renderEloView", "renderBlendView", "loadModelViews"):
            assert sym in imps, (name, sym)
            assert sym + "(" in src, (name, sym)
        # Mounted inside the Overview tab, never promoted to a new tab.
        assert 'getElementById("tab-overview")' in src, name
        assert "tab-validation" not in src, name


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
