---
phase: 07-48-team-dataset-group-definitions
plan: 03
subsystem: state
tags: python validation groups annex-c 48-team
requires:
  - phase: 07-01
    provides: constants (GROUP_COUNT, TEAMS_PER_GROUP, MATCHES_PER_GROUP, ANNEX_C_ENTRIES)
provides:
  - validate_groups() — 7-step structural validation of groups.json
  - load_groups() — Load→Validate→Return for groups.json
  - validate_annex_c() — 6-step structural validation of annex_c.json
  - load_annex_c() — Load→Validate→Return for annex_c.json
affects:
  - Phase 8 (group simulation) — consumes load_groups/load_annex_c
  - Phase 9 (knockout bracket) — uses Annex C for R32 seeding

tech-stack:
  added: []
  patterns:
    - Sequential validation checks with ValueError on failure
    - Load→Validate→Return pattern (matching load_bracket)

key-files:
  created: []
  modified:
    - worldcup_predictor/src/state.py — 4 new public functions (+275 lines)
    - worldcup_predictor/tests/test_state_load.py — 6 new Annex C validation tests

key-decisions:
  - "validate_annex_c() filters _meta key before counting entries, allowing metadata in data file"
  - "Both load functions accept optional teams/teams dict for cross-reference, matching planned Future cross-validation"
  - "TDD for validate_annex_c: RED phase tests written before implementation, confirming test-driven approach"

patterns-established:
  - "Validation sequence: dict key/count check → per-element structural checks → cross-reference checks"
  - "Group match_id format: GS_{letter}_{NN} enforced by validator"

requirements-completed: [DATA2-05, DATA2-06]

duration: 18min
completed: 2026-06-14
---

# Phase 7 Plan 3: Group/Annex C Validation Layer Summary

**Group structure validation (A-L, 4 teams, 6 matches) and Annex C third-place routing table validation (495 entries) in state.py**

## Performance

- **Duration:** 18 min
- **Started:** 2026-06-14T13:10:00Z
- **Completed:** 2026-06-14T13:28:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `validate_groups()` with 7 sequential checks: groups key exists, exact GROUP_COUNT (12), keys A-L, per-group structure (4 teams, 6 matches), match_id format `GS_{letter}_{NN}`, no duplicate teams or match_ids across groups, optional teams dict cross-reference
- `load_groups()` following Load→Validate→Return pattern from `load_bracket()`, supporting optional teams parameter
- `validate_annex_c()` with 6 sequential checks: dict type, exact ANNEX_C_ENTRIES (495), sorted 8-letter keys from A-L, valid value keys (1A/1B/1D/1E/1G/1I/1K/1L), self-reference detection, out-of-key reference detection
- `load_annex_c()` following Load→Validate→Return pattern, filtering `_meta` key from entry count

## Task Commits

Each task was committed atomically:

1. **Task 1: Add validate_groups() and load_groups()** - `f7c824a` (feat)
2. **Task 2 (TDD RED): Add RED-phase tests** - `b20d790` (test)
3. **Task 2 (TDD GREEN): Implement validate_annex_c() and load_annex_c()** - `a792815` (feat)

## Files Created/Modified

- `worldcup_predictor/src/state.py` - Added 4 public functions: `validate_groups`, `load_groups`, `validate_annex_c`, `load_annex_c` (+275 lines)
- `worldcup_predictor/tests/test_state_load.py` - Added 6 Annex C validation tests (+109 lines including builder helper)

## Decisions Made

- **validate_annex_c() filters `_meta` key**: Allows the data file to contain a `_meta` key with provenance metadata (source, verification reference) without counting it as one of the 495 required entries
- **load_groups() accepts optional `teams` parameter**: Enables callers to cross-reference team names against the teams dict at load time, matching the planned Phase 8 consumption pattern
- **All validation errors raise ValueError**: Consistent with existing `validate_bracket()` pattern, caught by main.py's error handler

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **Pre-existing test failure in `test_main_loop.py`**: `test_once_flag_runs_single_cycle` fails with `KeyError: 'Nigeria'` in `simulation.py` — this is a pre-existing bug in the simulation module unrelated to this plan. All 35 state tests pass cleanly.

## Next Phase Readiness

- All 4 new functions are importable from `src.state`
- Ready for Phase 8 (group simulation) which will consume `load_groups()` and `load_annex_c()`
- Data files (`groups.json`, `annex_c.json`) must be created by plan 07-02 before load functions can be called at runtime

## Self-Check: PASSED

- [x] `worldcup_predictor/src/state.py` — exists with 4 new functions
- [x] `worldcup_predictor/tests/test_state_load.py` — exists with 6 Annex C tests
- [x] All 3 commits exist in git log
- [x] All 4 functions importable from `src.state`
- [x] 35 state tests pass (no regressions)
- [x] Plan-level verification scripts pass

---

*Phase: 07-48-team-dataset-group-definitions*
*Completed: 2026-06-14*
