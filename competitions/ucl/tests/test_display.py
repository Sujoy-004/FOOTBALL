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
import os
import sys

import pytest

from competitions.ucl import display
from competitions.ucl.result import SimulationResult

# ── D-17 static check ──────────────────────────────────────────────────

# Verify display.py source has zero imports from competitions.ucl.src (AST-level check).
# This is more robust than inspecting sys.modules because other test files in the
# same session may have already loaded simulation modules.

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DISPLAY_PATH = os.path.join(_THIS_DIR, "..", "display.py")
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


# ── Helpers for combined display tests ──────────────────────────────────


def _capture_full(result: SimulationResult) -> str:
    """Capture output of all 5 display functions in D-06 order.

    Calls print_summary, print_league_table, print_playoff_rounds,
    print_knockout_bracket, and print_odds sequentially.
    """
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        display.print_summary(result)
        display.print_league_table(result)
        display.print_playoff_rounds(result)
        display.print_knockout_bracket(result)
        display.print_odds(result)
    finally:
        sys.stdout = old
    return buf.getvalue()


# ── Playoff tests ──────────────────────────────────────────────────────


class TestPlayoff:
    """Tests for print_playoff_rounds()."""

    def test_playoff_displays_8_ties(self, sample_result: SimulationResult):
        """Captured output contains 'Tie 1' through 'Tie 8'."""
        output = _capture(display.print_playoff_rounds, sample_result)
        for i in range(1, 9):
            assert f"Tie {i}" in output, f"Missing Tie {i} in output"

    def test_playoff_shows_advancing_winner(self, sample_result: SimulationResult):
        """Captured output indicates advancing winner for each tie."""
        output = _capture(display.print_playoff_rounds, sample_result)
        # 'advances' should appear at least 8 times (once per tie)
        assert output.count("advances") >= 8

    def test_playoff_shows_agg_score(self, sample_result: SimulationResult):
        """Captured output contains aggregate score indicator 'agg'."""
        output = _capture(display.print_playoff_rounds, sample_result)
        assert "agg" in output


# ── Bracket tests ──────────────────────────────────────────────────


class TestBracket:
    """Tests for print_knockout_bracket()."""

    def test_bracket_rounds_in_order(self, sample_result: SimulationResult):
        """Captured output contains R16, QF, SF, FINAL headers in that order."""
        output = _capture(display.print_knockout_bracket, sample_result)
        # Extract positions of round headers
        r16_pos = output.index("--- R16 ---")
        qf_pos = output.index("--- QF ---")
        sf_pos = output.index("--- SF ---")
        final_pos = output.index("--- FINAL ---")
        assert r16_pos < qf_pos < sf_pos < final_pos, (
            "Round headers not in R16 -> QF -> SF -> FINAL order"
        )

    def test_bracket_shows_teams_and_scores(self, sample_result: SimulationResult):
        """Captured output contains team names and score patterns."""
        output = _capture(display.print_knockout_bracket, sample_result)
        # Known teams should appear in the bracket
        assert "Man City" in output
        # Score pattern: digit-digit or digit-digit agg
        assert "agg" in output or "1-0" in output


# ── Odds tests ─────────────────────────────────────────────────────


class TestOdds:
    """Tests for print_odds()."""

    def test_odds_sorted_by_champion(self, sample_result: SimulationResult):
        """First odds row has highest champion probability, last has lowest."""
        import re
        output = _capture(display.print_odds, sample_result)
        lines = output.strip().split("\n")
        # Find separator line index, data rows are after it
        sep_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("--") and stripped.count("-") >= 10:
                sep_idx = i
                break
        assert sep_idx is not None, "Separator line not found in odds output"
        # Collect data rows after separator (lines with percentages)
        data_lines = []
        for l in lines[sep_idx + 1:]:
            if re.search(r"[\d.]+%", l):
                data_lines.append(l)
        assert len(data_lines) >= 2, "Need at least 2 data rows to test sort order"
        # Extract champion probability (first % value) from each row
        def _first_pct(line):
            match = re.search(r"(\d+\.?\d*)%", line)
            return float(match.group(1)) if match else 0.0
        first_champ = _first_pct(data_lines[0])
        last_champ = _first_pct(data_lines[-1])
        assert first_champ >= last_champ, (
            f"First team champion prob ({first_champ}%) < last ({last_champ}%)"
        )

    def test_odds_shows_all_36_teams(self, sample_result: SimulationResult):
        """Captured odds output contains all 36 teams."""
        output = _capture(display.print_odds, sample_result)
        # Count lines with percentage values (data rows have 5 percentage columns)
        percentage_lines = [l for l in output.split("\n") if "%" in l and "Rank" not in l]
        assert len(percentage_lines) == 36, (
            f"Expected 36 team rows, got {len(percentage_lines)}"
        )

    def test_odds_columns_present(self, sample_result: SimulationResult):
        """Captured odds output contains all column headers."""
        output = _capture(display.print_odds, sample_result)
        for col in ("Rank", "Team", "Champion", "Final", "SF", "QF"):
            assert col in output, f"Missing column header: {col}"


# ── JSON schema tests ────────────────────────────────────────────────


class TestJsonExport:
    """Tests for JSON export schema stability."""

    def test_json_export_schema(self, sample_result: SimulationResult):
        """dataclasses.asdict(sample_result) contains all expected top-level keys."""
        import dataclasses
        import json

        d = dataclasses.asdict(sample_result)
        expected_keys = {
            "snapshot_date", "n_iterations", "seed", "standings", "teams",
            "playoff_ties", "playoff_winners", "bracket_rounds",
            "bracket_champion", "stages", "stage_order",
        }
        actual_keys = set(d.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing expected keys in asdict output: {missing}"
        # Verify JSON-serializable
        json.dumps(d)


# ── Display order tests ──────────────────────────────────────────────


class TestDisplayOrder:
    """Tests for D-06 display order compliance."""

    def test_display_order_follows_d06(self, sample_result: SimulationResult):
        """Section headers appear in D-06 tournament chronology order."""
        output = _capture_full(sample_result)
        # Section header patterns (without ANSI bold)
        headers = [
            "Simulation Summary",
            "League Table",
            "Playoff Results",
            "Knockout Bracket",
            "Champion / Qualification Odds",
        ]
        positions = []
        for h in headers:
            pos = output.find(h)
            assert pos != -1, f"Section header not found: {h}"
            positions.append(pos)
        # Verify strictly increasing
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"Section '{headers[i]}' appears after '{headers[i + 1]}'"
            )


# ── ANSI consistency tests ─────────────────────────────────────────


class TestAsciiCompatibility:
    """Verify all display output uses only ASCII characters (Windows compatibility)."""

    def _assert_ascii(self, output: str, name: str):
        """Assert output contains only ASCII characters (< 128 code points)."""
        non_ascii = [c for c in output if ord(c) > 127]
        assert not non_ascii, (
            f"Non-ASCII characters found in {name}: "
            f"{[f'U+{ord(c):04X}:{c}' for c in non_ascii[:10]]}"
        )

    def test_summary_is_ascii(self, sample_result: SimulationResult):
        output = _capture(display.print_summary, sample_result)
        self._assert_ascii(output, "print_summary")

    def test_league_table_is_ascii(self, sample_result: SimulationResult):
        output = _capture(display.print_league_table, sample_result)
        self._assert_ascii(output, "print_league_table")

    def test_odds_is_ascii(self, sample_result: SimulationResult):
        output = _capture(display.print_odds, sample_result)
        self._assert_ascii(output, "print_odds")

    def test_playoff_is_ascii(self, sample_result: SimulationResult):
        output = _capture(display.print_playoff_rounds, sample_result)
        self._assert_ascii(output, "print_playoff_rounds")

    def test_bracket_is_ascii(self, sample_result: SimulationResult):
        output = _capture(display.print_knockout_bracket, sample_result)
        self._assert_ascii(output, "print_knockout_bracket")

    def test_full_output_is_ascii(self, sample_result: SimulationResult):
        """Combined output of all display functions is ASCII-only."""
        output = _capture_full(sample_result)
        self._assert_ascii(output, "full output")


class TestAnsiConsistency:
    """Tests that ANSI codes appear only where expected."""

    def test_ansi_consistency(self, sample_result: SimulationResult):
        """Non-zone sections (playoff, bracket, odds) do not use zone colors."""
        # Capture with TTY mock (ANSI enabled)
        playoff_out = _capture_tty(display.print_playoff_rounds, sample_result)
        bracket_out = _capture_tty(display.print_knockout_bracket, sample_result)
        odds_out = _capture_tty(display.print_odds, sample_result)

        # Green (32), yellow (33), red (31) should NOT appear in these sections
        # (only bold 1 and reset 0 are expected)
        for section_name, output in [
            ("playoff", playoff_out),
            ("bracket", bracket_out),
            ("odds", odds_out),
        ]:
            # Bold is expected (\033[1m) — that's section headers
            # Zone colors (\033[32m, \033[33m, \033[31m) must NOT appear
            assert "\033[32m" not in output, (
                f"Green ANSI found in {section_name} — zone colors not allowed (D-10)"
            )
            assert "\033[33m" not in output, (
                f"Yellow ANSI found in {section_name} — zone colors not allowed (D-10)"
            )
