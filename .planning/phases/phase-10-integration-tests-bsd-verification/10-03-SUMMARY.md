---
phase: 10-integration-tests-bsd-verification
plan: 03
subsystem: testing
tags: [pytest, integration-tests, smoke-tests, group-matches, bsd-api]

requires:
  - phase: 10-integration-tests-bsd-verification
    provides: Plan 01 (group match ingestion), Plan 02 (output helpers)

provides:
  - Fixed test_expected_goals_very_strong_dominates assertion (D-23)
  - Fixed test_main_loop_runs_iterations assertion (D-22)
  - 18 group integration tests covering INTG-01 through INTG-07
  - test_live_smoke.py for manual BSD API smoke testing (INTG-08)
  - Full test suite at 212 passed, 1 skipped, 0 failures

affects: [Phase 10 verification close-out]

tech-stack:
  added: []
  patterns:
    - "Test class per integration concern (Ingestion, Persistence, Standings, Pipeline, Bubble)"
    - "tmp_path roundtrip pattern for played_groups persistence tests"
    - "Skipif for live API tests that require BSD_API_KEY"

key-files:
  created:
    - tests/test_group_integration.py: 18 integration tests for group match pipeline
    - tests/test_live_smoke.py: Manual BSD API smoke test scaffolding
  modified:
    - tests/test_groups.py: Fixed assertion from > 10.0 to == 8.0 with cap rationale comment
    - tests/test_main_loop.py: Fixed assertion from "Fetched" to "Polling" with updated docstring

key-decisions:
  - "Group integration tests use inline group fixtures (data/groups.json fallback) to avoid file dependencies while enabling realistic testing"
  - "test_live_smoke_once uses per-test skipif instead of module-level pytestmark to allow non-API tests to run unconditionally"
  - "Integration tests cover 8 process_group_matches scenarios (basic, two-events, BSD dedup, match_id dedup, unmatchable, draw, invalid group, null group)"
  - "Additional importable-module test verifies module chain works without live API key"

patterns-established:
  - "Group integration tests follow existing test structure: MockResponse patterns from test_fetcher.py, tmp_path from test_integration.py, conftest fixtures"
  - "Dedup tests use shared mutable set for BSD event id tracking and separate set for match_id"
  - "Third-place bubble tests build 12-group standings with varying point values to exercise ranking and cutoff logic"

requirements-completed: [INTG-06, INTG-07, INTG-08, INTG-09]

duration: 14 min
completed: 2026-06-14
---

# Phase 10 Plan 03: Integration Tests & BSD Smoke Test Summary

**Fixed 2 pre-existing test failures, created 18 group integration tests covering INTG-01 through INTG-07, and added manual BSD API smoke test scaffolding**

## Performance

- **Duration:** 14 min
- **Started:** 2026-06-14 (implicit)
- **Completed:** 2026-06-14
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- Fixed `test_expected_goals_very_strong_dominates` — assertion changed from `> 10.0` to `== 8.0` with detailed comment documenting the `MAX_EXPECTED_GOALS=8.0` cap rationale (D-23)
- Fixed `test_main_loop_runs_iterations` — assertion changed from `"Fetched"` to `"Polling"` and docstring updated to reflect current heartbeat text (D-22)
- Created 18 integration tests across 5 test classes covering all group match pipeline scenarios
- Created manual BSD smoke test scaffold with skipif for API key, plus module importability regression guard
- Full test suite: **212 passed, 1 skipped, 0 failures**

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix two pre-existing test failures** - `e374041` (fix)
2. **Task 2: Create test_group_integration.py** - `fc9cde6` (test)
3. **Task 3: Create test_live_smoke.py** - `4384c68` (test)

**Plan metadata:** (committed below)

## Files Created/Modified

- `tests/test_group_integration.py` (NEW) - 18 integration tests:
  - `TestProcessGroupMatches` (8 tests): basic ingestion, BSD event dedup, match_id dedup, unmatchable team, draw skip, invalid group name, null group name
  - `TestPlayedGroupsPersistence` (3 tests): roundtrip, empty bootstrap, multi-entry
  - `TestStandingsWithPlayedGroups` (2 tests): standings reflect real results, remaining matches simulated normally
  - `TestFullPipeline` (1 test): end-to-end mock BSD → process → persist → simulate → standings
  - `TestThirdPlaceBubble` (4 tests): 12-group calculation, ordering, cutoff points, tiebreaker
- `tests/test_live_smoke.py` (NEW) - BSD smoke test scaffolding:
  - `test_live_smoke_once` (skipped without BSD_API_KEY): live API call through --once flow
  - `test_smoke_test_description`: documentation-only, always passes
  - `test_live_smoke_modules_importable`: verifies import chain without API key
- `tests/test_groups.py` (MODIFIED) - Fixed `test_expected_goals_very_strong_dominates` assertion
- `tests/test_main_loop.py` (MODIFIED) - Fixed `test_main_loop_runs_iterations` assertion

## Decisions Made

- **Per-test skipif vs module-level:** Applied `@pytest.mark.skipif` only to `test_live_smoke_once` so that documentation and importability tests run unconditionally — prevents accidental test suite gaps when running without API key
- **Inline groups fixture:** Uses conftest-style inline groups for process_group_matches tests to avoid file dependencies while enabling realistic BSD event processing
- **Comprehensive edge case coverage:** Extended beyond plan's 7 minimum tests to 18, covering draw handling, null group_name filtering, multi-entry persistence, and cutoff-point verification for third-place bubble

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required. BSD_API_KEY only needed for `test_live_smoke_once`.

## Next Phase Readiness

- All deferred Phase 8/9 test failures now fixed (INTG-09)
- Full group match pipeline covered by integration tests (INTG-01 through INTG-07)
- BSD API smoke test scaffold ready (INTG-08)
- Ready for Phase 10 close-out and SOT batch update (INTG-10)

---
*Phase: 10-integration-tests-bsd-verification*
*Completed: 2026-06-14*
