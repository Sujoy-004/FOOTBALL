---
phase: 01-state-elo-foundation
plan: 01
subsystem: foundation
tags: python, elo, json, pytest, bracket-validation, dfs, pathlib

requires: []
provides:
  - Project scaffold with worldcup_predictor/src/, data/, tests/ directories
  - constants module with K_FACTOR, DEFAULT_ELO, DATA_DIR
  - state.py with load_teams, load_bracket, load_played, validate_bracket
  - Seed data: 32 teams with Elo ratings, 23-match bracket, empty played.json
  - Bracket validation with duplicate detection, reference integrity, cycle detection
  - main.py entry point with error handling
  - Test suite with 30 passing tests
affects:
  - 01-state-elo-foundation (Plan 02 — elo engine, save functions)
  - 02-simulation (dependent on state layer)
  - 03-api-integration (dependent on state layer, team_aliases)

tech-stack:
  added:
    - Python 3.11 stdlib (json, pathlib, tempfile, os)
    - pytest 9.0.2, pytest-cov 7.1.0
  patterns:
    - State module pattern: load/validate functions in state.py
    - Bracket validation: flat list with DFS cycle detection
    - Test pattern: tmp_path fixture, conftest shared fixtures
    - TDD per task: RED→GREEN→REFACTOR cycle

key-files:
  created:
    - worldcup_predictor/__init__.py
    - worldcup_predictor/src/__init__.py
    - worldcup_predictor/src/constants.py
    - worldcup_predictor/src/state.py
    - worldcup_predictor/data/teams.json
    - worldcup_predictor/data/bracket.json
    - worldcup_predictor/data/played.json
    - worldcup_predictor/data/team_aliases.json
    - worldcup_predictor/tests/__init__.py
    - worldcup_predictor/tests/conftest.py
    - worldcup_predictor/tests/test_scaffold.py
    - worldcup_predictor/tests/test_state.py
    - worldcup_predictor/tests/test_state_load.py
    - worldcup_predictor/main.py
    - worldcup_predictor/requirements.txt
  modified: []

key-decisions:
  - "DATA_DIR resolved as Path(__file__).resolve().parent.parent / 'data' (two levels up from src/constants.py)"
  - "_resolve_data_dir helper accepts Path, str, or None for test compatibility"
  - "validate_bracket uses 3-color DFS (not depth limits) for cycle detection"
  - "All load functions let FileNotFoundError and JSONDecodeError propagate naturally (no catch-and-wrap)"

patterns-established:
  - "Load functions accept optional data_dir parameter (defaults to constants.DATA_DIR) for testability"
  - "Bracket validation runs inside load_bracket — always validates on load"
  - "TDD per task: RED test file → GREEN implementation commit → optional REFACTOR"

requirements-completed: [VAL-01]

duration: 10 min
completed: 2026-06-13
---

# Phase 1 Plan 1: State Foundation Summary

**Project scaffold, JSON data loading, bracket validation with DFS cycle detection, and main.py entry point — the thinnest end-to-end slice of the data pipeline**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-13T07:09:20Z
- **Completed:** 2026-06-13T07:19:11Z
- **Tasks:** 3 (each with TDD RED→GREEN cycle)
- **Files modified:** 15 created, 0 modified (greenfield)

## Accomplishments

- Created `worldcup_predictor/` project scaffold with src/, data/, tests/ directories
- Implemented `src/constants.py` with K_FACTOR=60, DEFAULT_ELO=1500, DATA_DIR path
- Implemented `src/state.py` with 4 functions: load_teams, load_bracket, load_played, validate_bracket
- Created seed data: 32 World Cup 2026 teams with realistic Elo ratings (1770-2157)
- Created 23-match flat bracket (16 R16 + 4 QF + 2 SF + 1 FINAL) with chain integrity
- Implemented bracket validation: duplicate match_id detection, source_match reference integrity, 3-color DFS cycle detection
- Created `main.py` entry point with comprehensive error handling (ValueError, FileNotFoundError, JSONDecodeError)
- Established testing infrastructure: pytest with conftest shared fixtures, tmp_path-based file I/O tests
- All 30 tests pass covering scaffold, state functions, validation errors, and main.py execution

## Task Commits

Each task was committed atomically following the TDD cycle:

1. **Task 1: Project scaffold, constants, test fixtures, seed data**
   - `3e7f7e9` (test) — RED: failing test for project scaffold and seed data
   - `5dcbf6e` (feat) — GREEN: implement scaffold, constants, data, fixtures

2. **Task 2: state.py — load functions and bracket validation**
   - `02edfa7` (test) — RED: failing test for state.py load and validate functions
   - `89d496e` (feat) — GREEN: implement state.py with load/validate

3. **Task 3: main.py entry point and bracket validation tests**
   - `75c8df2` (test) — RED: failing tests for main.py and comprehensive state tests
   - `f7bc1a9` (feat) — GREEN: implement main.py and fix path handling

## Files Created/Modified

- `worldcup_predictor/__init__.py` — Top-level package marker
- `worldcup_predictor/src/__init__.py` — Source package marker
- `worldcup_predictor/src/constants.py` — K_FACTOR (60), DEFAULT_ELO (1500), DATA_DIR (Path)
- `worldcup_predictor/src/state.py` — load_teams, load_bracket, load_played, validate_bracket, _resolve_data_dir
- `worldcup_predictor/data/teams.json` — 32 World Cup 2026 teams with pre-tournament Elo ratings
- `worldcup_predictor/data/bracket.json` — 23-match flat bracket (R16→QF→SF→FINAL)
- `worldcup_predictor/data/played.json` — Empty dict `{}` (seed for played matches)
- `worldcup_predictor/data/team_aliases.json` — Known name ambiguities (USA, Iran, South Korea)
- `worldcup_predictor/tests/__init__.py` — Test package marker
- `worldcup_predictor/tests/conftest.py` — Shared fixtures (sample_teams, sample_bracket, sample_played)
- `worldcup_predictor/tests/test_scaffold.py` — Scaffold/data file validation tests (7 tests)
- `worldcup_predictor/tests/test_state.py` — Comprehensive state and main.py tests (12 tests)
- `worldcup_predictor/tests/test_state_load.py` — Initial state load/validate tests (11 tests)
- `worldcup_predictor/main.py` — Entry point with error handling and startup summary
- `worldcup_predictor/requirements.txt` — pytest>=9.0, pytest-cov>=7.1

## Decisions Made

- **DATA_DIR resolution:** `Path(__file__).resolve().parent.parent / "data"` — two levels up from `src/constants.py` to reach the project root, then into `data/`. (Plan said `.parent.parent.parent` which was incorrect — fixed during execution.)
- **Path type flexibility:** All load functions and `_resolve_data_dir` accept `Path | str | None` for `data_dir` parameter, ensuring compatibility with test code that passes string paths from `tmp_path`.
- **Validation approach:** 3-color DFS for cycle detection (0=unvisited, 1=in-progress, 2=done) — robust against DAG depth exceeding 4 levels.
- **Bracket format:** Flat list per D-07 decision, with all match objects in a single array rather than nested rounds. Source_matches field links rounds together.
- **Team names for bracket:** Used all 32 teams from teams.json as participants in the Round-of-16, eliminating `null` team_a/team_b entries for first-round matches.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Fixed DATA_DIR path in constants.py**
- **Found during:** Task 1 (GREEN phase verification)
- **Issue:** `Path(__file__).resolve().parent.parent.parent / "data"` resolved to the project root level (`FIFA-WC/data/`), not `worldcup_predictor/data/`. Constants.py is at `src/constants.py`, so `.parent.parent` is the project root.
- **Fix:** Changed to `.parent.parent / "data"` (removed one `.parent`)
- **Files modified:** `worldcup_predictor/src/constants.py`
- **Verification:** `python -c "from src.constants import DATA_DIR; print(DATA_DIR)"` now shows `worldcup_predictor/data`
- **Committed in:** `5dcbf6e` (Task 1 feat commit)

**2. [Rule 2 - Missing Critical] _resolve_data_dir needs str handling**
- **Found during:** Task 2 (GREEN phase — acceptance criteria verification)
- **Issue:** `_resolve_data_dir` used `Path | None` type but didn't handle string paths, causing `str / str: TypeError` when test code or modified constants passed a string
- **Fix:** Updated type to `Path | str | None` and added `isinstance(result, str)` check to convert strings to Path
- **Files modified:** `worldcup_predictor/src/state.py`
- **Verification:** `load_teams(data_dir="/tmp")` now works correctly
- **Committed in:** `f7bc1a9` (Task 3 feat commit)

**3. [Rule 3 - Blocking] Fixed sample_bracket fixture reference error**
- **Found during:** Task 3 (RED phase — test_state.py failed on valid bracket)
- **Issue:** `conftest.py` sample_bracket had `QF_2` referencing `R16_3` and `R16_4` which didn't exist in a 4-match bracket
- **Fix:** Expanded sample_bracket to 7 matches: 4 R16 + 2 QF + 1 SF
- **Files modified:** `worldcup_predictor/tests/conftest.py`
- **Verification:** All 30 tests pass
- **Committed in:** `75c8df2` (Task 3 test commit)

---

**Total deviations:** 3 auto-fixed (2 missing critical, 1 blocking)
**Impact on plan:** All fixes necessary for correctness. No scope creep.

## Issues Encountered

- **DATA_DIR path resolution:** The plan specified `.parent.parent.parent` which was off by one level. Constants.py is at `src/constants.py`, so only two `.parent` calls needed.
- **Window paths in subprocess tests:** Testing `main.py` error handling with custom data directories required patching `constants.DATA_DIR` at runtime via `importlib.reload`. The `!r` string formatting in f-strings added unwanted quotes, requiring the `_resolve_data_dir` fix to handle string paths.
- **TDD overhead for scaffold tasks:** The first task (creating data JSON files) was awkward for TDD because tests verify file contents rather than function behavior. The pattern worked but required the test file to be a structural validator rather than a behavioral test.

## Known Stubs

- `data/team_aliases.json` — Reference file created, but alias resolution logic deferred to Phase 3 (DATA-04 per D-12, D-13)
- `data/played.json` — Empty dict `{}` seed. Will be populated by match recording in Plan 02 or Phase 3.

## TDD Gate Compliance

| Plan | RED | GREEN | REFACTOR | Status |
|------|-----|-------|----------|--------|
| Task 1 | `3e7f7e9` | `5dcbf6e` | — | Pass |
| Task 2 | `02edfa7` | `89d496e` | — | Pass |
| Task 3 | `75c8df2` | `f7bc1a9` | — | Pass |

All three tasks completed the RED→GREEN cycle. No RED→REFACTOR phases were needed (implementations were minimal and no cleanup was required).

## Threat Surface

| Flag | File | Description |
|------|------|-------------|
| threat_flag: tampering | `src/state.py` | JSON loading from local filesystem — accepts user-created files (already accepted in threat model T-01-02) |
| threat_flag: information_disclosure | `main.py:36-44` | Error messages include file paths in exception strings (already accepted in threat model T-01-04) |

No new threat surface beyond what's documented in the plan's threat model.

## Next Phase Readiness

- State loading layer complete for simulation dependency
- Bracket validation ensures tournament structure before simulation runs
- Ready for Plan 02: Elo engine (`elo.py`) with expected_score and update_ratings
- Ready for Plan 02: State save functions with atomic write pattern
- `test_state_load.py` will be cleaned up in the next plan (duplicates coverage from test_state.py)

---

*Phase: 01-state-elo-foundation*
*Completed: 2026-06-13*
