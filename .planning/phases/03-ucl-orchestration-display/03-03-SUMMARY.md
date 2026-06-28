---
phase: 03-ucl-orchestration-display
plan: 03
subsystem: display
tags: playoff, bracket, odds, ansii, display, stdout-capture, json-schema

requires:
  - phase: 03-02
    provides: league table display, captured stdout test helpers
provides:
  - Playoff result display (8 ties with aggregate + ET/Pens)
  - Knockout bracket display (R16 → QF → SF → FINAL round-by-round)
  - Champion/qualification odds display (all 36 teams, sorted descending)
  - Complete 5-section display pipeline in D-06 tournament chronology
  - JSON export with stable schema (all 11 top-level keys)
affects: Phase 4 (BSD validation will consume JSON schema, may reference odds schema)

tech-stack:
  added: none (stdlib only)
  patterns:
    - Display-before-export order in main.py (text stdout first, then JSON write)
    - Combined ET/Pens format with comma separator: (1-1 ET, 4-3 pens)
    - Fixed-width column formatting for odds table using % specifiers
    - D-17 enforced: display.py imports only result.py + stdlib

key-files:
  created: []
  modified:
    - competitions/ucl/display.py — added print_playoff_rounds, print_knockout_bracket, print_odds
    - competitions/ucl/main.py — all 5 display functions wired in D-06 order
    - competitions/ucl/tests/test_display.py — 11 new tests (playoff, bracket, odds, JSON, order, ANSI)
    - competitions/ucl/tests/conftest.py — stage_final_prob, stage_sf_prob, stage_qf_prob in sample_result

key-decisions:
  - "ET/Pens combined format uses comma: (1-1 ET, 4-3 pens) instead of separate parentheses"
  - "Bracket uses bold ANSI for round headers, no zone colors in non-table sections (D-10)"
  - "Odds separator line: 64 dashes matching column width; header bold via _bold()"

patterns-established:
  - "Display suffix construction: build score_line plus optional suffix string (ET/Pens/empty)"
  - "Odds sort key: (-champion_prob, team_name) for deterministic tie-breaking by name"
  - "Bracket round-order array: R16 → QF → SF → FINAL; section headers bold-wrapped"

requirements-completed:
  - UCLO-03
  - UCLO-04

duration: 6 min
completed: 2026-06-28
---

# Phase 03 Plan 03: UCL Orchestration & Display — Playoff, Bracket, and Odds Summary

**Playoff results, knockout bracket with round-by-round matchups, and champion/qualification odds display — completing the 5-section D-06 pipeline for `ucl-predict`**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-28T18:18:14Z
- **Completed:** 2026-06-28T18:24:10Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Added `print_playoff_rounds()` — 8 playoff ties with aggregate scores, advancing winners, and conditional ET/Pens display
- Added `print_knockout_bracket()` — round-by-round match list (R16 → QF → SF → FINAL) with two-legged aggregates and single-match final
- Added `print_odds()` — all 36 teams sorted by champion probability descending with columns per D-09
- Wired all 5 display functions into `main()` in D-06 tournament chronology order
- Added 11 new tests covering playoff, bracket, odds, JSON schema, display order, and ANSI consistency
- Enriched `sample_result` fixture with stage probabilities for odds testing
- Full UCL test suite: 129 passed, 1 skipped (stable)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend display.py with playoff, bracket, and odds** — `a284ce2` (feat)
   - display.py: 3 new functions with ET/Pens format, bold headers, odds table
   - conftest.py: stage probability keys in sample_result fixture
2. **Task 2: Wire 5 display sections into main.py** — `e8bf33f` (feat)
   - Import all 5 functions, call in D-06 order, JSON export unchanged
3. **Task 3: Add tests for playoff, bracket, odds, JSON schema** — `1ad4ec1` (test)
   - 11 new test functions across 6 test classes, _capture_full helper

## Files Created/Modified
- `competitions/ucl/display.py` — Extended with print_playoff_rounds, print_knockout_bracket, print_odds (+149 lines)
- `competitions/ucl/main.py` — All 5 display functions imported and called in D-06 order (+9 lines)
- `competitions/ucl/tests/test_display.py` — 11 new tests, _capture_full helper (+208 lines)
- `competitions/ucl/tests/conftest.py` — stage_final_prob, stage_sf_prob, stage_qf_prob in sample_result

## Decisions Made
- **ET/Pens combined format:** When both ET and penalties occur, format uses comma separator: `(1-1 ET, 4-3 pens)` instead of separate parenthetical groups. This matches the plan's examples and is more compact.
- **ANSI bold for section headers only:** Playoff, bracket, and odds sections use `_bold()` for section header lines only — no zone colors (per D-10). Zone colors (green/yellow/red) are exclusive to the league table.
- **Fixed-width odds columns:** Rank=4 (right-aligned), Team=24 (left-aligned), probability columns=8 (right-aligned, `%.1%` format). Separator = 64 dashes matching total width.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
- PowerSell terminal encoding issue with `→` (U+2192) character in stdout — only affects direct terminal printing in Windows cp1252 environments. Python string operations and pipe-redirected output work correctly. All tests use StringIO capture (not affected).

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- All 5 display sections complete for ucl-predict CLI output
- JSON export schema stable with 11 top-level keys (snapshot_date, n_iterations, seed, standings, teams, playoff_ties, playoff_winners, bracket_rounds, bracket_champion, stages, stage_order)
- Ready for Phase 4 (BSD validation) which will consume JSON schema and may enrich data with live match results
- Full UCL test suite at 129 passed (1 skipped for live API guard)

## Self-Check: PASSED

All 5 files exist, all 4 commits verified, full test suite green (129/130), both modules load correctly.
