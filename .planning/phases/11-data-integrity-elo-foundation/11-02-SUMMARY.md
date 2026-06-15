---
phase: 11-data-integrity-elo-foundation
plan: 02
subsystem: api, monitoring
tags: elo, sync, eloratings, output, main-loop, staleness
requires:
  - phase: 11-data-integrity-elo-foundation
    plan: 01
    provides: elo_sync module, cache, staleness detection
provides:
  - Startup Elo sync hook in main.py (D-01, D-18)
  - Periodic 24-hour sync timer in main loop (D-02)
  - Console sync results via print_sync_results()
  - Graduated staleness warnings via print_staleness_warning() (D-16)
  - Drift flag display via print_drift_flags()
affects: [11-03]
tech-stack:
  added: []
  patterns:
    - Startup sync after historical catch-up (Pitfall 7 ordering)
    - Periodic sync check on each poll iteration (O(1) timestamp comparison, no HTTP)
    - Cache fallback distinguishing first-run from subsequent failures
key-files:
  created: []
  modified:
    - worldcup_predictor/src/output.py
    - worldcup_predictor/main.py
    - worldcup_predictor/tests/test_main_loop.py
    - worldcup_predictor/tests/test_state.py
key-decisions:
  - "_run_elo_sync() updates _elo_last_sync_time on ANY successful sync (even empty corrections), fixing a plan ambiguity where empty-success would never advance the 24h timer"
  - "print_staleness_warning() runs every poll cycle but is O(1) and silent at green level — not a perf concern"
  - "Test _MockResp classes updated with .text attribute for eloratings TSV mock compatibility"
requirements-completed: [V2-01, V2-02]
duration: 11min
completed: 2026-06-15
---

# Phase 11 Plan 02: Elo Auto-Sync Integration into main.py Startup and Main Loop

**Elo sync lifecycle wired into main.py startup sequence and polling loop, with console output for sync results and graduated staleness warnings**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-15T11:25:00Z (approx)
- **Completed:** 2026-06-15T11:36:23Z
- **Tasks:** 2 (auto)
- **Files modified:** 4

## Accomplishments

- Added `print_sync_results()`, `print_staleness_warning()`, and `print_drift_flags()` to output.py — three new display functions for Elo sync lifecycle
- Implemented `_run_elo_sync()` helper in main.py with cache fallback logic for first-run vs subsequent failure scenarios per D-15/D-19/D-20
- Wired startup sync call after historical catch-up (Pitfall 7 ordering) and before first simulation (D-01, D-18)
- Added periodic 24h sync check in `_run_iteration()` — O(1) timestamp comparison, never blocks (D-04, D-22)
- Added staleness warning check using `print_staleness_warning()` when cache age exceeds 24h (D-16)
- Fixed `_run_elo_sync()` logic to update `_elo_last_sync_time` on any successful sync (even empty corrections), ensuring the 24h timer advances correctly
- Updated `_MockResp` in test_main_loop.py and test_state.py with `.text` attribute for eloratings TSV mock compatibility

## Task Commits

Each task was committed atomically:

1. **Task 1: Add sync result and staleness display functions to output.py** - `ec8182e` (feat)
2. **Task 2: Wire Elo sync into main.py startup and main loop** - `57e81b5` (feat)
3. **Task 2 fix: Add .text to MockResp for eloratings mock** - `3b7f107` (fix)

**Plan metadata:** This summary (commit pending)

## Files Created/Modified

- `worldcup_predictor/src/output.py` — Added `print_sync_results()`, `print_staleness_warning()`, `print_drift_flags()` with imports for `logging` and `get_staleness_level`
- `worldcup_predictor/main.py` — Added `_run_elo_sync()`, `_elo_last_sync_time` tracking, startup sync hook, periodic 24h sync check, staleness warning
- `worldcup_predictor/tests/test_main_loop.py` — Added `.text = ''` to `_MockResp` class in both runner helpers
- `worldcup_predictor/tests/test_state.py` — Added `.text = ''` to `_MockResp` class

## Decisions Made

- `_run_elo_sync()` handles the `sync_elo_from_eloratings()` return contract: `None` = fetch failure, `[]` = success/no drift, `[corrections]` = success with drift. The timer is always updated on success, even when no drift is found — this fixes a plan design ambiguity where empty-success would never advance the 24h timer.
- Staleness check uses `print_staleness_warning()` which is silent at green level — runs every poll cycle with negligible overhead.
- The `_MockResp.text` attribute added to test mocks is set to empty string, which causes `parse_eloratings_tsv` to return an empty list and `sync_elo_from_eloratings` to return `[]` gracefully.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added .text to test MockResp for eloratings mock compatibility**
- **Found during:** Task 2 verification (full test suite)
- **Issue:** `test_once_flag_runs_single_cycle` and `test_main_runs_successfully` both failed because `fetch_eloratings_tsv()` accesses `resp.text` on the mocked `requests.get` response. The existing `_MockResp` class did not have a `.text` attribute.
- **Fix:** Added `text = ''` class attribute to `_MockResp` in both `test_main_loop.py` (two runners) and `test_state.py` (one runner). Empty string is handled gracefully by the sync pipeline.
- **Files modified:** `tests/test_main_loop.py`, `tests/test_state.py`
- **Verification:** All 276 tests pass
- **Committed in:** `3b7f107` (Task 2 fix commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary for test compatibility with new startup sync hook. No scope creep.

## Issues Encountered

- The plan's `_run_elo_sync` design had an ambiguity where `sync_elo_from_eloratings` returns `[]` for both "fetch succeeded but no drift" and "fetch returned nothing" cases. Resolved by checking `corrections is None` — the actual `elo_sync.py` returns `None` on fetch failure, not `[]`. The implementation aligns with the actual `elo_sync.py` contract.
- The plan design didn't update `_elo_last_sync_time` when `corrections` is empty (successful sync with no drift). Fixed in implementation: always update timer on any successful sync.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Elo auto-sync fully integrated into main.py lifecycle
- Console output functions for sync results, drift flags, and staleness warnings complete
- Ready for Plan 03: test fixtures and comprehensive test suite

---
*Phase: 11-data-integrity-elo-foundation*
*Completed: 2026-06-15*
