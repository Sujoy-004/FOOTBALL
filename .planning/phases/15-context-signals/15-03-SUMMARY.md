---
phase: 15-context-signals
plan: 15-03
subsystem: prediction-pipeline
tags:
  - signal-ingestion
  - form-signal
  - lineup-signal
  - main-loop
  - unit-tests
requires:
  - 15-02 (form + lineup module implementation)
provides:
  - form+lineup wiring in main.py
  - test_form.py (28 tests)
  - test_lineup.py (23 tests)
affects:
  - main.py (_run_iteration, _merge_signals_into_history, _run_calibrate_and_blend)
tech-stack:
  added: []
  patterns:
    - Signal computation wrapped in try/except with graceful degradation
    - Signal cache saved to data/ via state.save_signal_cache
    - Unavailable match warnings aggregated per signal (D-09)
key-files:
  created:
    - tests/test_form.py
    - tests/test_lineup.py
  modified:
    - main.py
decisions:
  - Monkeypatch src.state.ledger_upsert (not module-level) because form.py/lineup.py import it locally via from src.state import ledger_upsert
metrics:
  duration: ~10 minutes
  completed_date: 2026-06-17
---

# Phase 15 Plan 03: Wire Form + Lineup Signals into Prediction Pipeline

**One-liner:** Wire `compute_form_signal` and `compute_lineup_signal` into main.py's `_run_iteration()` loop with cache persistence, merge into prediction history, extend blender signal keys, and validate with 51 unit tests.

## Tasks Completed

| #  | Name                    | Type | Files                          |
| -- | ----------------------- | ---- | ------------------------------ |
| 1  | Wire form/lineup in main.py    | auto | main.py (58 insertions, 12 deletions) |
| 2  | Create tests/test_form.py      | auto | tests/test_form.py (496 lines) |
| 3  | Create tests/test_lineup.py    | auto | tests/test_lineup.py (263 lines) |

## Commits

| Hash    | Type | Message                                                    |
| ------- | ---- | ---------------------------------------------------------- |
| a94e85e | feat | wire form and lineup signals into main.py                  |
| dec97e8 | test | add comprehensive unit tests for form signal                |
| 3abf912 | test | add comprehensive unit tests for lineup signal              |

## Detailed Changes

### Task 1 — Wire form/lineup in main.py (5 changes)

**Change A:** Added imports for `compute_form_signal`, `compute_lineup_signal`, `FORM_CACHE_FILE`, `LINEUP_CACHE_FILE`.

**Change B:** Added context signal computation block in `_run_iteration()` after CatBoost fetch, before signal merge:
- Form signal: calls `compute_form_signal()` with teams, groups, bracket, played, played_groups; saves to `form_cache.json`
- Lineup signal: calls `compute_lineup_signal()` with groups, bracket; saves to `lineup_cache.json`
- Both wrapped in try/except with graceful degradation warnings

**Change C:** Extended `_merge_signals_into_history()` to merge `form` and `lineup_strength` keys from prediction ledger into history entries.

**Change D:** Extended `signal_keys` in `_run_calibrate_and_blend()` to include `"form"` and `"lineup_strength"`.

**Change E:** Added unavailable match warnings for form and lineup signals (same pattern as odds/catboost warnings).

### Task 2 — Tests: test_form.py (28 tests)

- **TestSigmoid** (6): Zero, positive, negative, symmetry, overflow
- **TestFormResiduals** (4): Basic residual, draw, missing team name, team not in data
- **TestBuildTeamResiduals** (3): Basic build, recency sort, non-dict skip
- **TestComputeMatchFormSignal** (3): Basic available, team not found, unavailable if no matches
- **TestFormSignal** (7): Basic, form delta sign, available flag, unavailable if no matches, bracket included, unresolved bracket skipped, timestamp keys
- **TestWindowSize** (3): Window limits, zero matches, fewer than window
- **TestFormLedger** (2): Ledger upsert called, key is "form"

### Task 3 — Tests: test_lineup.py (23 tests)

- **TestSigmoid** (6): Same coverage as form
- **TestLineupSignal** (6): Basic, stronger home, lower-value underdog, equal values, available flag, extreme ratio clamped
- **TestLineupEdgeCases** (5): Missing home, missing away, both missing, non-positive value, negative value
- **TestLineupComputeSignal** (4): Basic integration, unresolved bracket skipped, resolved bracket included, timestamp keys
- **TestLineupLedger** (2): Ledger upsert called, key is "lineup_strength"

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Test monkeypatch path] Fixed incorrect monkeypatch target for ledger_upsert**
- **Found during:** Task 2 (first test run)
- **Issue:** `monkeypatch.setattr("src.predictors.form.ledger_upsert", ...)` failed because `ledger_upsert` is imported locally inside `compute_form_signal()` via `from src.state import ledger_upsert`, not as a module-level attribute of `src.predictors.form`.
- **Fix:** Changed all monkeypatch targets to `"src.state.ledger_upsert"` — the function's canonical location. When patched before the import runs, the local import picks up the patched version.
- **Files modified:** `tests/test_form.py`

**2. [Rule 2 — Test assertion] Fixed `pytest.approx` operator error in test_basic_residual**
- **Found during:** Task 2 (first test run)
- **Issue:** `res_a == 1.0 - pytest.approx(0.521, abs=0.05)` caused `TypeError` because Python's `-` operator doesn't support `ApproxScalar` on the right side.
- **Fix:** Replaced with range assertion `0.4 < res_a < 0.6` and `res_b < -0.4`, plus zero-sum check.
- **Files modified:** `tests/test_form.py`

## Verification Results

1. ✅ `python -m pytest tests/test_form.py tests/test_lineup.py -v --tb=short` → **51 passed**
2. ✅ `python -c "from main import _run_iteration, _merge_signals_into_history; from src.predictors.form import compute_form_signal; from src.predictors.lineup import compute_lineup_signal; print('main.py wiring OK')"` → **OK**
3. ✅ `python -c "import inspect; ... assert 'form' in src and 'lineup_strength' in src; print('merge handles both keys OK')"` → **OK**
4. ✅ `python -c "import inspect; ... assert 'form' in src and 'lineup_strength' in src; print('signal_keys OK')"` → **OK**

## Known Stubs

None. Both form and lineup signals perform real computation with no placeholder data. Tests use inline fixtures (no real data file dependencies).

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries beyond what was already defined in form.py and lineup.py (Phase 15-02).

## Self-Check: PASSED

- ✅ `tests/test_form.py` exists (496 lines)
- ✅ `tests/test_lineup.py` exists (263 lines)
- ✅ Commit a94e85e: feat(15-03): wire form and lineup signals into main.py
- ✅ Commit dec97e8: test(15-03): add comprehensive unit tests for form signal
- ✅ Commit 3abf912: test(15-03): add comprehensive unit tests for lineup signal
- ✅ 51 tests passing
- ✅ All 4 verification commands pass
