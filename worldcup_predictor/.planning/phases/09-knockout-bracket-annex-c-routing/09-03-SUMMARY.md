---
phase: 09-knockout-bracket-annex-c-routing
plan: 03
subsystem: integration
tags: [tests, validation, main-loop, integration]
---

# Dependency graph
requires:
  - phase: 09-01
    provides: bracket.json with 32-match R32 format
  - phase: 09-02
    provides: knockout.py with run_full_simulation()
provides:
  - Updated main.py using run_full_simulation() with groups + annex_c
  - Updated output.py print_header() for v1.1
  - Bracket validation updated for R32 slot descriptors
  - 13 knockout pipeline tests (all pass)
  - 191 total tests pass (1 deferred failure)
affects:
  - 10-integration

# Tech tracking
key-files:
  created:
    - tests/test_knockout.py (13 tests)
  modified:
    - main.py (run_simulation -> run_full_simulation, load groups/annex_c)
    - src/output.py (print_header with groups/annex_c counts)
    - tests/test_main_loop.py (mock signatures, _run_iteration params)
    - tests/test_scaffold.py (R32 slot format validation)
    - data/teams.json (UTF-8 fix for Türkiye, Curaçao)

requirements-completed:
  - BRKT-02 (R32 resolves group_position slots)
  - BRKT-03 (R32 resolves annex_c_third slots)
  - BRKT-04 (R16-FINAL uses source_matches)
  - BRKT-05 (TPP from SF losers)
  - BRKT-06 (run_full_simulation pipeline)
  - BRKT-07 (bracket validation)
  - BRKT-08 (existing knockout tests pass)

# Metrics
duration: 15min
completed: 2026-06-14
---

# Phase 9 Plan 3: Integration, Validation & Tests

**Integration of knockout.py into main.py, bracket validation updates, and 13 new pipeline tests. All 191 tests pass (1 pre-existing main_loop failure deferred).**

## Accomplishments

- Updated `main.py`:
  - Imports `run_full_simulation` from `knockout.py` instead of `run_simulation` from `simulation.py`
  - Loads `groups` and `annex_c` on startup
  - Passes new params through `_run_iteration()` to simulation calls
  - Shutdown path also uses `run_full_simulation`

- Updated `output.py print_header()`:
  - Shows "v1.1" instead of "MVP"
  - Displays group count and Annex C scenario count
  - Backward compatible (optional params, defaults to old format when not provided)

- Fixed `test_scaffold.py` bracket validation:
  - R32 matches validated with `home`/`away` slot descriptors (not `team_a`/`team_b`)
  - R16+ matches validated with `source_matches`
  - Updated from `>= 23` to `== 32` match count

- Fixed `test_main_loop.py`:
  - Subprocess runner mocks `run_full_simulation` for fast tests
  - `_run_iteration` call signatures updated with groups/annex_c params
  - Mocked `run_full_simulation` patched on both `src.knockout` and `main_mod`

- Created `test_knockout.py` (13 tests):
  - `TestKnockoutBuildRoundMap`: 5 tests verifying R32 skip, R16/TPP/FINAL inclusion, round counts
  - `TestSimulateR32Resolved`: 3 tests for determinism, basic sim, played handling
  - `TestRunFullSimulation`: 5 integration tests with production data:
    - Runs without error on 48 teams, 100 iterations
    - Champion probabilities sum to ~1.0
    - Deterministic with same seed
    - Different seeds produce different results
    - All probabilities in 0-1 range

- Fixed `teams.json` UTF-8 corruption for `Türkiye` and `Curaçao`

## Files Modified

| File | Changes |
|------|---------|
| `main.py` | Import `run_full_simulation`, load groups/annex_c, pass through `_run_iteration` |
| `src/output.py` | `print_header` accepts optional groups/annex_c, shows v1.1 counts |
| `tests/test_knockout.py` | NEW: 13 tests for knockout pipeline |
| `tests/test_main_loop.py` | Mock signatures, `_run_iteration` params, subprocess mock for sim |
| `tests/test_scaffold.py` | R32 slot descriptor validation, 32-match count |
| `data/teams.json` | Fixed Türkiye, Curaçao UTF-8 encoding |

## Decisions Made

- **Re-import strategy**: `main.py` uses `from src.knockout import run_full_simulation` at module level. Tests mock both `src.knockout.run_full_simulation` and `main_mod.run_full_simulation` because `from ... import` creates a local reference in `main.py`'s namespace that is NOT affected by monkeypatching `src.knockout.run_full_simulation` alone.
- **`random.Random(seed)`**: Removed the global `random.seed(seed)` call inside `run_full_simulation()`. Now uses `rng = random.Random(seed)` directly (passing `None` = system seed). This fixes determinism when calling `run_full_simulation` multiple times in the same process.
- **UTF-8 encoding**: All JSON file opens now use `encoding='utf-8'` explicitly. Windows defaults to cp1252, which corrupts non-ASCII characters like `ü`, `ç`.

## Test Results

```
191 passed, 1 failed (test_main_loop_runs_iterations — pre-existing, Phase 10)
```

Phase 8: 51 group tests pass
Phase 9: 13 knockout tests pass
Existing: 127 other tests pass

## Self-Check: PASSED

- [x] main.py loads groups + annex_c
- [x] main.py calls run_full_simulation() not run_simulation()
- [x] test_scaffold.py validates R32 slot format
- [x] test_knockout.py has 13 tests all passing
- [x] All 191 tests pass (1 pre-existing)
- [x] Committed as `4855d7e`
