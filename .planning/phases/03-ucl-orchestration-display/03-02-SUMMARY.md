---
phase: 03-ucl-orchestration-display
plan: 02
subsystem: display
tags: ansi-colors, terminal-display, formatted-table, zone-highlighting

requires:
  - phase: 03-01
    provides: SimulationResult dataclass, main.py CLI entry point, sample_result fixture

provides:
  - display.py with print_summary and print_league_table
  - ANSI color helpers with auto-detection (green for top_8, yellow for playoff, red for eliminated)
  - 36-row league table with Pos/Team/Pts/GD/GS/Zone columns
  - Integrated display calls in main.py main() (D-06 order: summary first, table second)
  - 7 stdout-capture tests covering output format, ANSI codes, and plain-text fallback
  - D-17 enforcement via AST-level import check

affects:
  - 03-03 (will add playoff, bracket, odds display sections)

tech-stack:
  added: none (stdlib only — sys, io, ast)
  patterns: stdout capture test pattern with _capture helper, TTY-mock StringIO for ANSI testing, zone-based color mapping via _zone_color factory

key-files:
  created:
    - competitions/ucl/display.py
    - competitions/ucl/tests/test_display.py
  modified:
    - competitions/ucl/main.py

key-decisions:
  - "Used _zone_color factory function mapping zone strings to color wrappers — avoids if/elif chains in print_league_table"
  - "Used _TTYStringIO subclass for ANSI color testing instead of mocking NO_COLOR — cleaner separation"
  - "Column widths based on acceptance criteria minimums: Pos=2, Team=22, Pts=3, GD=4, GS=3, Zone=10"

requirements-completed:
  - UCLO-02

# Metrics
duration: 2m
completed: 2026-06-28
---

# Phase 3 Plan 2: League Table Display Summary

**League table display with ANSI zone highlighting — 36-row table, 6 columns, color-coded qualification zones, plain-text fallback, and integrated into main()**

## Performance

- **Duration:** 2 min
- **Started:** 2026-06-28T18:13:41Z
- **Completed:** 2026-06-28T18:16:02Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Created `display.py` with `print_summary()` (simulation metadata) and `print_league_table()` (36-row formatted table)
- ANSI color system with automatic TTY detection (D-11) and zone-based mapping (D-10)
- Replace basic `print()` in `main.py` with proper display calls in D-06 order
- 7 tests covering metadata output, 36-team table, 6 column headers, ANSI zone coloring, plain-text fallback, zone label presence, and D-17 compliance

## Files Created/Modified

- `competitions/ucl/display.py` — Pure display functions: `print_summary`, `print_league_table`, `_supports_color`, `_ansi` factory, zone color wrappers. Zero imports from `competitions.ucl.src` (D-17 compliant).
- `competitions/ucl/main.py` — Added `print_summary(result)` and `print_league_table(result)` calls after assembly, before JSON export. Removed basic summary print.
- `competitions/ucl/tests/test_display.py` — 7 tests using stdout capture pattern. D-17 static check via AST import analysis.

## Decisions Made

- Used `_zone_color(zone)` factory returning the correct color wrapper — keeps display logic clean and extensible for future sections
- Column widths derived from acceptance criteria: Zone padded to 10 chars (accommodating "ELIMINATED")
- Used `_TTYStringIO` (subclass of `StringIO` overriding `isatty()`) for ANSI color tests — avoids mutating module state

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- **D-17 runtime check incompatibility:** The `sys.modules` check in the test file failed because pytest loads simulation modules in the same process from other test files. Fixed by using AST analysis to verify the source code's import statements instead of inspecting runtime module state.
- **Standard git hook:** No pre-commit hooks were triggered.

## Next Phase Readiness

Ready for Plan 03-03 which will add playoff results, knockout bracket, and champion/qualification odds display sections. The display module pattern is established — future sections follow the same `print_*(result: SimulationResult) -> None` signature.

---

*Phase: 03-ucl-orchestration-display*
*Completed: 2026-06-28*
