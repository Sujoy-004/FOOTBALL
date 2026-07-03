---
phase: 08-signal-blending-market-integration
plan: 02
subsystem: calibration
tags: calibration, log-loss, weights, replay, offline
requires:
  - phase: 06-simulation-modes
    provides: ReplayMatchResultProvider, replay data format
  - phase: 07-multi-signal-architecture
    provides: Signal, SignalOutput, SignalRegistry
  - phase: 08-01
    provides: BlendedPrediction, EnsembleEngine, compute_log_loss_weights
provides:
  - run_calibration() offline weight calibration pipeline
  - Default signal_weights.json bootstrap config file
  - 18-test calibration orchestration test suite
affects:
  - 09-calibration-uncertainty (consumes calibration output)
  - 10-calibration-improvement (builds on calibration pipeline)
tech-stack:
  added: []
  patterns:
    - Atomic write via tempfile.NamedTemporaryFile + os.replace()
    - Per-signal multi-class log-loss = average of 3 binary log-losses (home, draw, away)
    - Under-sampled signal exclusion with configurable threshold (default 20)
    - Bootstrapping: _EmptyResultProvider for RollingFormSignal during calibration
key-files:
  created:
    - competitions/ucl/src/calibrate.py
    - competitions/ucl/config/signal_weights.json
    - competitions/ucl/tests/test_calibrate.py
  modified: []
key-decisions:
  - "RollingFormSignal requires MatchResultProvider — added _EmptyResultProvider stub for calibration"
  - "Calibration uses default Elo 1500 for unknown teams — same behavior as signals without specific ratings"
  - "All replay data used; no train/test split (deferred to Phase 9 per Pitfall 5)"
  - "--season convenience flag deferred per D-07"
  - "calibrated_at: null in default config (set to ISO datetime by --calibrate)"
requirements-completed:
  - UCLB-01
  - UCLB-03
duration: 6min
completed: 2026-07-03
---

# Phase 8 Plan 2: Weight Calibration Pipeline + Default Config Summary

**Offline weight calibration via run_calibration() reading replay data, evaluating 5 signals, computing per-signal multi-class log-loss, and writing inverse-log-loss weights atomically; default signal_weights.json bootstrap config**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-03T05:31:00+05:30
- **Completed:** 2026-07-03T05:40:24+05:30
- **Tasks:** 3
- **Files created:** 3

## Accomplishments

- `competitions/ucl/config/signal_weights.json` — default weight config with 7 bootstrap signal entries, `calibrated_at: null`, weights summing to 1.0, per_signal metadata placeholders
- `competitions/ucl/src/calibrate.py` — `run_calibration()` with full offline pipeline: load replay data → evaluate all 5 registered signals → per-signal multi-class log-loss → inverse-log-loss weights → atomic write via `NamedTemporaryFile` + `os.replace()`
- `_build_signal_registry()` with `_EmptyResultProvider` to handle RollingFormSignal's MatchResultProvider requirement during calibration
- Under-sampled signal exclusion: signals with < threshold matches (default 20) excluded from blend, logged, and marked `excluded: true` in output
- `competitions/ucl/tests/test_calibrate.py` — 18 tests across 6 test classes covering: registry construction, calibration output schema, atomic write, under-sampled exclusion, error handling, per-signal log-loss computation, and default threshold parameter

## Task Commits

Each task was committed atomically:

1. **Task 1: Create default signal_weights.json** - `770455e` (feat)
2. **Task 2: Implement calibrate.py with run_calibration()** - `09e6213` (feat)
3. **Task 3: Create test_calibrate.py** - `39e2a3b` (test)

## Files Created

- `competitions/ucl/config/signal_weights.json` — Default weight config with 7 signal entries, bootstrapping placeholder weights (market_odds highest at 0.30 per D-04)
- `competitions/ucl/src/calibrate.py` — 218-line calibration pipeline with `run_calibration()`, `_build_signal_registry()`, `_get_default_output_path()`, and `_EmptyResultProvider` stub
- `competitions/ucl/tests/test_calibrate.py` — 347-line test suite with 18 tests across 6 classes

## Decisions Made

- **RollingFormSignal provider handling** — Added `_EmptyResultProvider` stub that returns empty results for RollingFormSignal during calibration. This is correct because calibration replay data format doesn't carry the match-level detail needed by the provider interface. RollingFormSignal returns `0.5` (neutral form) with no results — same as the no-results path in production.
- **Calibration with default Elo** — Signals run with empty Elo ratings dict during calibration, using default 1500. This produces plausible probabilities for weight computation even without tournament-specific Elo data.
- **No train/test split** — All replay matches used for weight computation per Pitfall 5 (deferred to Phase 9's responsibility).

## Deviations from Plan

**1. [Rule 3 - Blocking] RollingFormSignal requires MatchResultProvider in constructor**
- **Found during:** Task 2 (`_build_signal_registry()` import)
- **Issue:** `RollingFormSignal.__init__()` requires `result_provider` argument (changed in D-09 during Phase 7). Plan's `_build_signal_registry()` called `RollingFormSignal()` without arguments, causing `TypeError`.
- **Fix:** Added `_EmptyResultProvider` private class that conforms to the `MatchResultProvider` Protocol and returns empty results. Passed to `RollingFormSignal(result_provider=_EmptyResultProvider())`.
- **Files modified:** `competitions/ucl/src/calibrate.py`
- **Verification:** `_build_signal_registry()` now succeeds, all 5 signals registered, 18 tests pass, full UCL suite green
- **Committed in:** `09e6213` (Task 2 commit)

**2. [Rule 1 - Bug] Atomic write test fragile due to system temp .tmp files**
- **Found during:** Task 3 (test_calibrate test run)
- **Issue:** System temp directory contained 70 pre-existing `.tmp` files from other processes. Test asserted `len(tmp_files) == 0` against the system temp dir.
- **Fix:** Used pytest `tmp_path` fixture to isolate the atomic write test to a clean temp directory.
- **Files modified:** `competitions/ucl/tests/test_calibrate.py`
- **Verification:** Test passes in isolated tmp_path
- **Committed in:** `39e2a3b` (Task 3 commit)

**3. [Rule 1 - Bug] Rounding tolerance in three_equal_weights test**
- **Found during:** Task 3 (test_calibrate test run)
- **Issue:** `compute_log_loss_weights()` rounds to 6 decimal places, so `3 * 0.333333 = 0.999999`, which differs from 1.0 by `~1e-6`. Test asserted `abs(sum(weights) - 1.0) < 1e-10`.
- **Fix:** Relaxed tolerance to `< 1e-5` — consistent with the rounding behavior already documented in 08-01-SUMMARY.
- **Files modified:** `competitions/ucl/tests/test_calibrate.py`
- **Verification:** Test passes with relaxed tolerance
- **Committed in:** `39e2a3b` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bugs, 1 Rule 3 blocker)
**Impact on plan:** All auto-fixes necessary for correctness. The RollingFormSignal constructor issue was a pre-existing behavioral change from D-09 not reflected in the plan. No scope creep.

## Issues Encountered

None — all issues identified and resolved via deviation rules during task execution.

## User Setup Required

None — no external service configuration required.

## Verification Results

- `python -m pytest competitions/ucl/tests/test_calibrate.py -x -v` — **18/18 passed**
- `python -m pytest competitions/ucl/tests/ -x -v` — **296 passed, 1 skipped** (no regressions)
- `python -c "from competitions.ucl.src.calibrate import run_calibration; print('calibrate OK')"` — **OK**
- `json.load(open('competitions/ucl/config/signal_weights.json'))` weights sum to 1.0 — **OK**

## Next Phase Readiness

- Weight calibration pipeline ready for Phase 9 (calibration baseline) and Phase 10 (improvement)
- Default signal_weights.json provides bootstrap weights for immediate use by EnsembleEngine
- Next plan: 08-03 (Market integration: value detection, CLI flags, display)
- Full UCL test suite: 296 passed, 1 skipped — no regressions

## Self-Check: PASSED

All 3 files verified on disk:
- `[ -f competitions/ucl/config/signal_weights.json ]` — FOUND
- `[ -f competitions/ucl/src/calibrate.py ]` — FOUND
- `[ -f competitions/ucl/tests/test_calibrate.py ]` — FOUND

All 3 commits verified:
- `770455e` — FOUND
- `09e6213` — FOUND
- `39e2a3b` — FOUND

All 3 acceptance criteria verified:
- Calibration tests: 18/18 passed
- Full UCL test suite: 296 passed, 1 skipped
- Import checks pass

---

*Phase: 08-signal-blending-market-integration*
*Completed: 2026-07-03*
