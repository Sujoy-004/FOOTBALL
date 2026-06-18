---
phase: 01-state-elo-foundation
plan: 02
subsystem: foundation
tags: python, elo, atomic-writes, json-persistence, pytest, integration

requires:
  - phase: 01-01
    provides: project scaffold, load functions, constants, seed data, conftest

provides:
  - elo.py with expected_score and update_ratings (standard Elo formula)
  - state.py with save_teams, save_bracket, save_played (atomic JSON writes)
  - Comprehensive Elo test suite: 9 tests (equal ratings, table values, 400-gap, standard update, underdog, custom K, large gap, invalid winner, no mutation)
  - Persistence test suite: 6 new tests (3 roundtrips + atomic safety + dir creation + valid JSON)
  - Integration test: end-to-end Elo update + persistence roundtrip
  - Atomic write pattern: mkstemp + os.replace + os.fsync + tempfile cleanup

affects:
  - 02-simulation (depends on elo.py for expected_score, update_ratings)
  - 03-api-integration (depends on state persistence for restart-proof state)

tech-stack:
  added:
    - Python stdlib math (elo calculations)
    - Python stdlib os (fsync, replace, unlink for atomic writes)
    - Python stdlib tempfile (mkstemp for safe temp file creation)
  patterns:
    - Atomic JSON write: tempfile.mkstemp → json.dump → flush → fsync → os.replace → unlink on failure
    - Elo formula: E_a = 1 / (1 + 10^((rating_b - effective_a) / 400))
    - No mutation contract: update_ratings returns new dict, never modifies input
    - Auto-create directories on save: path.mkdir(parents=True, exist_ok=True)

key-files:
  created:
    - worldcup_predictor/src/elo.py
    - worldcup_predictor/tests/test_elo.py
    - worldcup_predictor/tests/test_integration.py
  modified:
    - worldcup_predictor/src/state.py
    - worldcup_predictor/tests/test_state.py

key-decisions:
  - "Atomic write uses mkstemp (not NamedTemporaryFile) for Windows compatibility — NamedTemporaryFile holds exclusive lock on Windows"
  - "os.fsync() called after flush() to ensure data reaches disk before rename (flush() is not fsync())"
  - "Temp file created in same directory as target via dir=str(path.parent) to guarantee same-filesystem for atomic os.replace"
  - "update_ratings() computes new_elo_b = elo_b + K * ((1.0 - result_a) - expected_b) to be explicit about both teams' delta"
  - "Goal-difference K multiplier deferred post-MVP with TODO comment in elo.py"

patterns-established:
  - "Save functions accept optional data_dir: Path | str | None parameter for testability (mirrors load function pattern)"
  - "Atomic write pattern: _atomic_write_json as internal helper — all save functions delegate to it"
  - "Temp file cleanup: on any exception during write, temp file is deleted via os.unlink in except block before re-raising"

requirements-completed: [DATA-02, ELO-01]

duration: 12 min
completed: 2026-06-13
---

# Phase 1 Plan 2: Elo Engine & Atomic Persistence Summary

**Standard Elo formula with expected_score and update_ratings, atomic JSON save functions using mkstemp + os.replace + os.fsync, and programmatic integration test proving the full seed→save→load→Elo→save→reload roundtrip**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-13T07:21:58Z
- **Completed:** 2026-06-13T07:33:55Z
- **Tasks:** 3 (each with TDD cycle)
- **Files modified:** 5 (2 source, 3 test)

## Accomplishments

- Implemented `src/elo.py` with `expected_score()` (standard Elo formula) and `update_ratings()` (compute new ratings, no mutation of input, raises ValueError for invalid winner)
- Added `_atomic_write_json()` helper to `src/state.py` using `mkstemp()` + `os.replace()` + `os.fsync()` + temp file cleanup on failure
- Added `save_teams()`, `save_bracket()`, `save_played()` — all auto-create directories and use atomic write pattern
- Created 9-unit test suite for Elo covering equal ratings, table values, 400-point gap, standard update, underdog win, custom K-factor, large gap, invalid winner, and no-mutation contract
- Created 6 persistence tests for save functions covering roundtrips (teams, bracket, played), atomic safety, auto-directory creation, and valid JSON output
- Created integration test proving end-to-end roundtrip: seed → save → load → Elo update → save → reload → data matches
- Full test suite: 46 tests passing (30 original Plan 01 + 9 Elo + 6 persistence + 1 integration)

## Task Commits

Each task was committed atomically following the TDD cycle:

1. **Task 1: elo.py — expected_score and update_ratings**
   - `ad33ce8` (test) — RED: failing tests for elo functions (9 test cases)
   - `5bc2b22` (feat) — GREEN: implement elo.py with standard formula

2. **Task 2: state.py — atomic save functions and persistence tests**
   - `9c7e12b` (test) — RED: failing tests for save functions (6 test cases)
   - `17c989a` (feat) — GREEN: implement atomic write helper + 3 save functions

3. **Task 3: Integration test — Elo update + persistence roundtrip**
   - `c76c0de` (test) — integration test for end-to-end roundtrip

## Files Created/Modified

- `worldcup_predictor/src/elo.py` — Created: expected_score() and update_ratings() with standard World Football Elo formula
- `worldcup_predictor/src/state.py` — Modified: added _atomic_write_json(), save_teams(), save_bracket(), save_played()
- `worldcup_predictor/tests/test_elo.py` — Created: 9 test cases in TestExpectedScore and TestUpdateRatings classes
- `worldcup_predictor/tests/test_state.py` — Modified: added 6 persistence tests (3 roundtrips + atomic safety + dir creation + valid JSON)
- `worldcup_predictor/tests/test_integration.py` — Created: end-to-end roundtrip test

## Decisions Made

- **Atomic write helper pattern:** A single `_atomic_write_json()` internal helper handles all three save functions — consistent implementation, single point of maintenance for the atomic write pattern.
- **mkstemp over NamedTemporaryFile:** Per RESEARCH.md: Windows exclusive lock issue with NamedTemporaryFile. mkstemp returns a raw file descriptor with no lock.
- **os.fsync() after flush():** flush() pushes Python's buffer to the OS buffer; fsync() ensures data reaches disk before the rename operation.
- **Same-directory temp files:** Using `dir=str(path.parent)` guarantees same-filesystem for `os.replace()`, which is atomic only on the same filesystem.
- **update_ratings explicit formula:** Uses `new_elo_b = elo_b + K * ((1.0 - result_a) - expected_b)` to be explicit about the computation for both teams rather than using `1 - expected_a`.
- **TODO for goal-difference K multiplier:** Added comment in elo.py — deferred to post-MVP per research recommendation.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- **TDD for Task 3:** The integration test was written after both elo.py and state.py save functions existed, so the test passed immediately. This is expected behavior (components already built) — no RED→GREEN cycle was needed since no additional source code was being implemented.

## TDD Gate Compliance

| Plan | RED | GREEN | REFACTOR | Status |
|------|-----|-------|----------|--------|
| Task 1 (elo.py) | `ad33ce8` | `5bc2b22` | — | Pass |
| Task 2 (save funcs) | `9c7e12b` | `17c989a` | — | Pass |
| Task 3 (integration) | — | `c76c0de` | — | Pass (no source impl needed) |

Tasks 1 and 2 completed the full RED→GREEN cycle. Task 3 was integration test coverage for already-implemented functionality — no separate RED→GREEN needed since both source modules were already built.

## Threat Surface

No new threat surface beyond what's documented in the plan's threat model (T-01-07 through T-01-11, T-01-SC). All mitigations are applied:
- T-01-07: `tempfile.mkstemp()` creates non-predictable temp file names
- T-01-08: Extreme Elo gaps produce mathematically correct results (no crash)
- T-01-09: Same-directory temp file guarantees same-filesystem atomic rename
- T-01-10: `os.fsync()` ensures data reaches disk before `os.replace()`
- T-01-SC: No new external packages — Python stdlib only

## Known Stubs

None — all implemented functionality is production-ready for the MVP scope.

## Next Phase Readiness

- Phase 1 complete — state persistence (load + save) and Elo engine ready for simulation
- Integration test proves the full data pipeline works end-to-end
- Data pipeline ready: load → validate → compute → save → reload → data matches
- Ready for Phase 2: Monte Carlo simulation building on Elo engine and state layer

---

*Phase: 01-state-elo-foundation*
*Completed: 2026-06-13*
