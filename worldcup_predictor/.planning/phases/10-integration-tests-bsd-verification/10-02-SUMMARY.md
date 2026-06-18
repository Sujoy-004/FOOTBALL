---
phase: 10-integration-tests-bsd-verification
plan: 02
subsystem: console-display
tags: [box-drawing, group-standings, third-place-bubble, ansi]
requires:
  - phase: 10-integration-tests-bsd-verification
    provides: Plan 01 BSD API group match ingestion
provides:
  - print_group_standings() with box-drawing table for all 12 groups
  - print_third_place_bubble() showing 8th vs 9th cutoff with color coding
  - Updated print_header() with 48-team format counts including group match count
  - _compute_group_display() helper in main.py for single-iteration group sim
  - D-15 refresh behavior: show on new matches/hourly, skip on heartbeat
affects: [10-integration-tests-bsd-verification Plan 03, Plan 04]
tech-stack:
  added: []
  patterns:
    - Box-drawing group standings table with ANSI color
    - Single-iteration deterministic group sim for display (seed=0)
    - D-15 conditional display flag for refresh scenarios
key-files:
  created: []
  modified:
    - worldcup_predictor/src/output.py
    - worldcup_predictor/main.py
key-decisions:
  - "Team column width = 28 chars to accommodate longest team names (Bosnia and Herzegovina = 22 chars + position)"
  - "GD formatting: +X for positive, raw for <= 0 (includes 0)"
  - "Deterministic group sim for display via random.Random(0) — negligible overhead (~0.01s)"
  - "D-15 flag-based refresh: show_group_display = bool(new_group_matches)"
requirements-completed: [INTG-03, INTG-04, INTG-05]
duration: 8 min
completed: 2026-06-14
---

# Phase 10 Plan 02: Group Standings Console Display Summary

**Group standings console display with box-drawing tables for all 12 groups, third-place bubble indicator (8th vs 9th cutoff with color coding), and 48-team console header counts**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-14T18:22:00Z
- **Completed:** 2026-06-14T18:30:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `print_group_standings()` renders all 12 groups in a box-drawing table with Position, Team, Pts, GD, GS columns (D-10 through D-13)
- Empty standings placeholder: `(no group matches played yet)` on startup with no data (D-15)
- `print_third_place_bubble()` shows 8th ADVANCES in green, 9th OUT in red, with cutoff margin (D-14)
- `print_header()` now displays `12 groups (72 group matches)` for 48-team format (INTG-05)
- `_compute_group_display()` helper runs a single deterministic group simulation iteration for display data (seed=0, ~0.01s overhead)
- D-15 refresh behavior: standings display on new group matches or hourly refresh; skipped on heartbeat
- All 26 existing output tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Update print_header() and add print_group_standings() + print_third_place_bubble() to output.py** - `af418e6` (feat)
2. **Task 2: Wire group standings display into main.py _run_iteration()** - `53b063c` (feat)

**Plan metadata:** (committed with plan artifacts below)

## Files Created/Modified
- `worldcup_predictor/src/output.py` - Added `print_group_standings()`, `print_third_place_bubble()`, updated `print_header()`, imported `GROUP_COUNT`/`MATCHES_PER_GROUP`
- `worldcup_predictor/main.py` - Added `import random`, `_compute_group_display()` helper, wired group standings into `_run_iteration()` with D-15 refresh logic

## Decisions Made
- **Team column width = 28 chars:** Accommodates longest team name (Bosnia and Herzegovina, 22 chars) + position + padding
- **GD formatting:** `+X` for positive GD, raw number for zero/negative (matches explicit plan instruction)
- **Deterministic display seed:** `random.Random(0)` for single-iteration group sim — reproducible and negligible overhead (~0.01s)
- **D-15 flag implementation:** `show_group_display = bool(new_group_matches)` ensures standings show on new data, skip on heartbeat

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `test_main_loop_runs_iterations` and `test_expected_goals_very_strong_dominates` continue to fail (pre-existing, documented in STATE.md as deferred to D-22/D-23)
- No new issues introduced

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Group standings display ready for Plan 03 (BSD smoke test & fixture updates)
- Plan 03 can verify full pipeline: API fetch → process → simulate → display all 12 groups
- Plan 04 (SOT batch update) can reference this plan's INTG-03/04/05 completion

## Self-Check: PASSED

- `worldcup_predictor/src/output.py` — ✅ exists
- `worldcup_predictor/main.py` — ✅ exists
- `10-02-SUMMARY.md` — ✅ exists
- Commit `af418e6` — ✅ found
- Commit `53b063c` — ✅ found
- `from src.output import print_group_standings, print_third_place_bubble` — ✅ exports OK

---
*Phase: 10-integration-tests-bsd-verification*
*Completed: 2026-06-14*
