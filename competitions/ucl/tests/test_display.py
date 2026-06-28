"""Stdout capture tests for UCL display functions.

Verifies:
    - League table produces all 36 rows with 6 columns
    - ANSI zone coloring appears when color is supported
    - Plain text fallback when stdout is piped (no TTY)
    - Summary metadata display
    - D-17 compliance (no simulation imports)
"""

from __future__ import annotations

import ast
import io
import sys

import pytest

from competitions.ucl import display
from competitions.ucl.result import SimulationResult

# ── D-17 static check ──────────────────────────────────────────────────

# Verify display.py source has zero imports from competitions.ucl.src (AST-level check).
# This is more robust than inspecting sys.modules because other test files in the
# same session may have already loaded simulation modules.

_DISPLAY_PATH = "competitions/ucl/display.py"
with open(_DISPLAY_PATH) as _f:
    _tree = ast.parse(_f.read())
_SRC_IMPORTS = []
for _node in ast.walk(_tree):
    if isinstance(_node, ast.ImportFrom) and _node.module:
        if "competitions.ucl.src" in _node.module:
            _SRC_IMPORTS.append(_node.module)
assert len(_SRC_IMPORTS) == 0, (
    f"D-17 violation: display.py imports from simulation modules: {_SRC_IMPORTS}"
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _capture(func, *args, **kwargs) -> str:
    """Redirect stdout to StringIO, call func, restore stdout, return captured output."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


class _TTYStringIO(io.StringIO):
    """A StringIO that pretends to be a TTY for testing ANSI color output."""

    def isatty(self) -> bool:
        return True


def _capture_tty(func, *args, **kwargs) -> str:
    """Capture output with a TTY-mocked stdout, forcing ANSI color codes."""
    buf = _TTYStringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


# ── Tests ──────────────────────────────────────────────────────────────


class TestSummary:
    """Tests for print_summary()."""

    def test_summary_shows_metadata(self, sample_result: SimulationResult):
        """Summary output contains iteration count, seed, and snapshot date."""
        output = _capture(display.print_summary, sample_result)
        assert "Iterations: 10000" in output
        assert "Seed: 42" in output
        assert "Snapshot: 2026-06-28" in output


class TestLeagueTable:
    """Tests for print_league_table()."""

    def test_league_table_prints_all_36_teams(self, sample_result: SimulationResult):
        """Captured output contains first (1.) and last (36.) position markers."""
        output = _capture(display.print_league_table, sample_result)
        assert "1." in output
        assert "36." in output

    def test_league_table_has_6_columns(self, sample_result: SimulationResult):
        """Captured output contains all 6 column headers: Pos, Team, Pts, GD, GS, Zone."""
        output = _capture(display.print_league_table, sample_result)
        for col in ("Pos", "Team", "Pts", "GD", "GS", "Zone"):
            assert col in output, f"Missing column header: {col}"

    def test_league_table_zone_colors(self, sample_result: SimulationResult):
        """ANSI escape codes appear for top_8 (green), playoff (yellow), eliminated (red) when TTY."""
        output = _capture_tty(display.print_league_table, sample_result)
        assert "\033[32m" in output, "Missing green ANSI code for top_8 zone"
        assert "\033[33m" in output, "Missing yellow ANSI code for playoff zone"
        assert "\033[31m" in output, "Missing red ANSI code for eliminated zone"

    def test_league_table_plain_text_when_piped(self, sample_result: SimulationResult):
        """No ANSI escape codes in output when stdout is piped (non-TTY)."""
        output = _capture(display.print_league_table, sample_result)
        assert "\033[" not in output, "ANSI codes should not appear in piped output"
        # But zone labels should still be visible in plain text
        assert "TOP_8" in output

    def test_print_league_table_zone_labels_all_present(self, sample_result: SimulationResult):
        """All three zone labels (TOP_8, PLAYOFF, ELIMINATED) appear in output."""
        output = _capture(display.print_league_table, sample_result)
        assert "TOP_8" in output
        assert "PLAYOFF" in output
        assert "ELIMINATED" in output

    def test_team_column_contains_known_team(self, sample_result: SimulationResult):
        """A known team name appears in the league table output."""
        output = _capture(display.print_league_table, sample_result)
        assert "Man City" in output
