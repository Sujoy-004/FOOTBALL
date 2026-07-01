---
phase: 06-simulation-modes
plan: 06-03
subsystem: orchestration
tags: CLI, orchestrator, --mode, --replay-data, tests

requires:
  - phase: 06-simulation-modes
    provides: played_matches threading, MatchResultProvider implementations
provides:
  - Orchestrator module with mode routing
  - --mode and --replay-data CLI flags
  - Comprehensive test coverage for all three modes
affects: [07-prediction-signals, 09-tournament-validation]

tech-stack:
  added: []
  patterns:
    - Mode routing in orchestrator.py, not in main.py or engine (D-05)
    - Lazy imports to avoid circular dependencies

key-files:
  created:
    - competitions/ucl/src/orchestrator.py
    - competitions/ucl/tests/test_replay.py
    - competitions/ucl/tests/test_live.py
    - competitions/ucl/tests/test_orchestrator.py
  modified:
    - competitions/ucl/main.py
    - competitions/ucl/tests/test_cli.py

key-decisions:
  - "Mode routing lives in orchestrator.py, not main.py (D-05)"
  - "Cross-import: orchestrator imports build_simulation_result lazily from main.py"
  - "All mode logic: resolve_played_matches() in orchestrator; engine stays mode-agnostic"

patterns-established:
  - "Orchestration layer: resolve_played_matches() + run_simulation() entry point"

requirements-completed: [UCLM-01, UCLM-03, UCLM-06, UCLM-08]

duration: 18min
completed: 2026-07-01
---

# Phase 6 Plan 06-03: Orchestrator Module + CLI Flags + Tests — Summary

**Mode routing in orchestrator.py, --mode/--replay-data CLI flags, and full test coverage for simulate/replay/live modes**

## Performance

- **Duration:** 18 min
- **Started:** 2026-07-01T12:20:00Z
- **Completed:** 2026-07-01T12:38:00Z
- **Tasks:** 7
- **Files modified:** 6

## Accomplishments
- Created `competitions/ucl/src/orchestrator.py` with `resolve_played_matches()` and `run_simulation()`
- Added `--mode simulate|replay|live` and `--replay-data FILE` CLI flags to `_parse_args()`
- Delegated `main()` to orchestrator (mode routing NOT in engine — D-05)
- Created `test_replay.py` (9 tests: injection, determinism, data loading, protocol checks)
- Created `test_live.py` (2 tests: BSD provider load, live integration)
- Created `test_orchestrator.py` (3 tests: simulate returns None, replay without data exits, live without key exits)
- Added `TestModeFlags` to `test_cli.py` (7 tests: defaults, flags, rejection, compatibility)

## Task Commits

1. **Task 1: Create orchestrator.py** - `17b49c2` (feat)
2. **Task 2: Add --mode and --replay-data flags** - `17b49c2` (feat)
3. **Task 3: main() delegates to orchestrator** - `17b49c2` (feat)
4. **Task 4: TestModeFlags in test_cli.py** - `17b49c2` (feat)
5. **Task 5: Create test_replay.py** - `17b49c2` (feat)
6. **Task 6: Create test_live.py** - `17b49c2` (feat)
7. **Task 7: Create test_orchestrator.py** - `17b49c2` (feat)

## Files Created/Modified
- `competitions/ucl/src/orchestrator.py` - NEW: mode routing, resolve_played_matches(), run_simulation()
- `competitions/ucl/main.py` - Added --mode and --replay-data flags; main() delegates to orchestrator
- `competitions/ucl/tests/test_replay.py` - NEW: 9 tests across 3 classes
- `competitions/ucl/tests/test_live.py` - NEW: 2 tests for BSD live mode
- `competitions/ucl/tests/test_orchestrator.py` - NEW: 3 tests for resolve_played_matches()
- `competitions/ucl/tests/test_cli.py` - Added TestModeFlags class (7 tests)

## Decisions Made
- Cross-import: `orchestrator.py` imports `build_simulation_result` from `main.py` inside `run_simulation()` (lazy import); `main.py` imports `run_simulation` inside `main()` — circular-safe
- Lazy imports follow existing pattern from `main.py` (`fetch_ucl_matches` inside `if args.validate` blocks)
- Return type of `run_simulation()` is `object` (not `SimulationResult`) to avoid circular import; long-term refactor would move `build_simulation_result` into `orchestrator.py`

## Deviations from Plan

**1. [Rule 3 - Blocking] Fixed test fixture pairs to match actual UCL fixture schedule**
- **Found during:** Task 5-7 (test creation and verification)
- **Issue:** Tests used `("Man City", "Bayern")` and `("Bayern", "Man City")` pairs, but these teams are not opponents in the actual UCL 2025/26 fixture schedule — causing assertion failures
- **Fix:** Replaced with actual fixture pairs: `("Barcelona", "Man City")`, `("Atletico Madrid", "Man City")`
- **Files modified:** test_replay.py, test_live.py
- **Verification:** All 21 new tests pass
- **Committed in:** b5df357, b8e3dde

**2. [Rule 3 - Blocking] Fixed orchestrator test for BSD_API_KEY env var**
- **Found during:** Task 7 (orchestrator test)
- **Issue:** `.env` file sets BSD_API_KEY, causing `resolve_played_matches` to bypass the exit check and attempt file I/O
- **Fix:** Added `monkeypatch.delenv("BSD_API_KEY")` in the live mode test
- **Files modified:** test_orchestrator.py
- **Verification:** orchestrator tests pass
- **Committed in:** b8e3dde

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Necessary test corrections; no scope creep.

## Issues Encountered
- Test fixture pairs need to match actual fixture schedule — updated to use `Barcelona vs Man City` and `Atletico Madrid vs Man City`
- `.env` file interference with orchestrator test for live mode — used `monkeypatch.delenv()`

## Next Phase Readiness
- Phase 6 complete — three-mode simulator ready (simulate, replay, live)
- Phase 7 (Prediction Signals) can use live mode for real data + signal predictions
- Phase 9 (Tournament Validation) can use replay mode for historical backtesting
