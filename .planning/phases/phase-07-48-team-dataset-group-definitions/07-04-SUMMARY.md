---
phase: 07-48-team-dataset-group-definitions
plan: 04
subsystem: testing
tags: pytest, validation, groups, annex-c, production-data
requires:
  - phase: 07-02
    provides: groups.json and annex_c.json production data files
  - phase: 07-03
    provides: validate_groups, validate_annex_c, load_groups, load_annex_c in state.py
provides:
  - 23 new test functions covering all validation error paths for groups and Annex C
  - Production data verification confirming groups.json and annex_c.json are structurally valid
affects:
  - phase 08 (simulation core) — validation gates prevent corrupted data from reaching simulation
tech-stack:
  added: []
  patterns:
    - Test helper functions (_make_valid_groups, _make_valid_annex_c) generating complex test fixtures
    - Production data verification tests using real files via MAIN_DIR path resolution
key-files:
  created: []
  modified:
    - worldcup_predictor/tests/test_state.py (303 → 546 lines)
key-decisions:
  - "Used offset-based self-reference fallback in _make_valid_annex_c to generate valid 495-entry data without self-references"
  - "match_id duplicate test adjusted to trigger within-group duplicate (prefix check fires before duplicate check in validate_groups)"
patterns-established:
  - "Test fixtures for combinatorial data use itertools.combinations for correctness"
  - "Production data verification tests live alongside unit tests to prevent silent data corruption"
requirements-completed:
  - DATA2-05
  - DATA2-06
duration: 8 min 27 sec
completed: 2026-06-14
---

# Phase 07 Plan 04: Test Group and Annex C Validators Summary

**23 new test functions for validate_groups, load_groups, validate_annex_c, load_annex_c plus production data verification that groups.json and annex_c.json pass their respective validators**

## Performance

- **Duration:** 8 min 27 sec
- **Started:** 2026-06-14T22:10:00Z
- **Completed:** 2026-06-14T22:18:27Z
- **Tasks:** 2
- **Tests added:** 23 (41 total, 0 regressions)
- **File growth:** 303 → 546 lines (+80%)

## Accomplishments

- **Validate groups coverage (12 tests):** All validation paths tested — correct structure passes, wrong group/team/match count fails, duplicate teams and match_ids fail, invalid match_id prefix fails, cross-reference missing team fails, all load error paths (missing file, corrupt JSON, invalid data)
- **Validate Annex C coverage (9 tests):** All validation paths tested — correct 495-entry table passes, wrong count fails, unsorted key fails, missing value key fails, self-references fail, out-of-key references fail, invalid group letter fails, file-not-found load
- **Production data verified (2 tests):** Real `groups.json` passes `validate_groups(teams=teams)` with full cross-reference. Real `annex_c.json` passes `validate_annex_c()`
- **Zero regressions:** All 18 pre-existing tests continue to pass unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: validate_groups + load_groups tests** — `c5c4749` (test)
   - 12 tests: _make_valid_groups helper, 8 validate error paths, 4 load paths
2. **Task 2: validate_annex_c + load_annex_c + production verification** — `ae323d3` (test)
   - 11 tests: _make_valid_annex_c helper, 7 validate error paths, 2 load paths, 2 production data verification

## Files Created/Modified

- `worldcup_predictor/tests/test_state.py` — Extended from 303 to 546 lines with 23 new test functions covering groups and Annex C validation

## Decisions Made

- **Self-reference avoidance in test helper:** `_make_valid_annex_c` uses offset `combo[(i+1)%8]` with fallback to `combo[(i+2)%8]` when the first offset produces a self-reference. This guarantees all 495 entries are valid without needing complex assignment logic
- **Within-group duplicate test:** For `test_valid_groups_duplicate_match_id`, creating a duplicate within the same group (both prefix and index-based duplicate checks) ensures the duplicate-detection path is exercised rather than the prefix check

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- **Self-reference in _make_valid_annex_c on first attempt:** Using `combo[i % 8]` produced self-references when a winner group letter appeared at index `i` in the combo. Fixed with offset-based assignment with a fallback. Traced through the combinatorics to verify correctness for all C(12,8)=495 combinations
- **Duplicate match_id test needed adjustment:** The prefix check in `validate_groups` runs before the duplicate check, so setting group B's match_id to a group A value triggered the wrong error. Fixed by creating a within-group duplicate (both occurrences have the correct GS_B_ prefix)

## Known Stubs

None — all tests are fully wired with real fixtures or production data.

## Threat Flags

None — test code only, no new network endpoints or trust boundary surface.

## Self-Check: PASSED

- [x] `tests/test_state.py` exists at 546 lines (≥100 min_lines ✓)
- [x] `c5c4749` commit verified via `git log`
- [x] `ae323d3` commit verified via `git log`
- [x] All 41 tests pass: `python -m pytest tests/test_state.py -x -q` returns 0

## Next Phase Readiness

- All validation functions for group definitions and Annex C lookup are comprehensively tested
- Production data files confirmed valid — no corruption risk for simulation phase
- Ready for Phase 08 (simulation core) where validated data will drive match outcomes

---

*Phase: 07-48-team-dataset-group-definitions*
*Completed: 2026-06-14*
