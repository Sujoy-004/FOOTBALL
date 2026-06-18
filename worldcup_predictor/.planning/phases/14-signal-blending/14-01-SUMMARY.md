---
phase: 14-signal-blending
plan: 01
type: execute
wave: 1
completed_at: "2026-06-17T10:05:00Z"
commits:
  - "2c7a727 feat(14-01): build blender.py core module with Platt scaling, blending, LOO-CV, Poisson rate"
files_created:
  - worldcup_predictor/src/blender.py
  - worldcup_predictor/tests/test_blender.py
tests_passed: 39
---

# Phase 14 Plan 01: Blender Core Module — Complete

## Objective Achieved
Built the core `src/blender.py` module containing all pure-computation functions for Platt scaling, Brier-weighted blending, rolling Brier computation, LOO-CV evaluation, Poisson base rate computation, and the full calibration+blend orchestration function.

## Implementation Summary

### src/blender.py — 8 Public Exports + 3 Private Helpers

**Module-level constants:**
- `EPS = 1e-15` — matches evaluation.py clamping convention
- `RIDGE = 1e-6` — ridge regularization for Hessian
- `MAX_ITER = 50` — Newton-Raphson convergence guard
- `CONV_TOL = 1e-6` — parameter step convergence threshold
- `COLD_START_THRESHOLD = 30` — identity calibration until 30+ matches
- `BRIER_WINDOW_SIZE = 50` — default rolling Brier window

**Private helpers:**
- `_sigmoid(x)` — numerically stable sigmoid with ±100 clamping
- `_log_odds(p)` — clamped log-odds transform
- `_platt_targets(actuals)` — Platt's target adjustment (n_pos+1)/(n_pos+2), etc.

**Public functions:**
1. `calibrate_signal(predictions, actuals, threshold=30)` — Newton-Raphson Platt fitting on log-odds; returns identity (1.0, 0.0) for n < threshold
2. `apply_calibration(p_raw, A, B)` — applies Platt transform via sigmoid; clamps and rounds to 6 decimals
3. `compute_rolling_brier(entries, signal_key, window=50)` — mean Brier over last `window` entries; returns 1.0 if no data
4. `compute_blend_weights(signal_briers)` — inverse Brier with 0.05 floor, normalized to sum=1.0
5. `blend_predictions(signal_preds, weights)` — weighted average with missing-signal re-normalization; returns 0.5 if no signals
6. `loo_cv_blended_brier(histories)` — LOO-CV with per-fold calibration and blending; returns 1.0 for n < 2
7. `compute_poisson_base_rate(path=None)` — computes goals/team/match from historical data; falls back to 1.25
8. `calibrate_and_blend(history, signal_keys, elo_ratings, groups_data, bracket_data, odds_cache, cb_cache)` — full pipeline orchestration; pure computation, no I/O

### tests/test_blender.py — 39 Tests Across 7 Classes

- `TestPlattCalibration` (4): cold start, non-identity fit, convergence, all draws
- `TestColdStart` (5): empty, below/at/above threshold, custom threshold
- `TestCalibrationEdgeCases` (5): zero/one prob clamping, negative log-odds, identity path, all-same predictions
- `TestApplyCalibration` (4): identity, calibrated, monotonic, rounding
- `TestBlendWeights` (6): formula, floor, single signal, equal briers, sum-to-one, zero-sum guard
- `TestBlend` (5): basic, missing signal, single signal, no signals, rounding
- `TestRollingBrier` (3): computes brier, empty, window
- `TestLOOCV` (4): perfect predictions, worse than climatology, two signals, insufficient data
- `TestPoissonBaseRate` (3): fallback default, fallback missing file, from data

## Verification Results

```
pytest tests/test_blender.py -x -v
============================= 39 passed in 0.18s ==============================
```

- All 39 tests pass
- All 8 public exports importable: ✓
- All 3 private helpers importable: ✓
- No numpy/sklearn/scipy imports: ✓
- Pure Python stdlib math only: ✓

## Acceptance Criteria Met

- `calibrate_signal([], [])` returns (1.0, 0.0) — empty input handled gracefully ✓
- `calibrate_signal([0.5]*20, [1.0]*20)` returns (1.0, 0.0) — cold start threshold works ✓
- `calibrate_signal` with biased predictions (n=31) returns non-identity params ✓
- `apply_calibration(0.5, 1.0, 0.0)` returns 0.5 — identity preserves value ✓
- `apply_calibration(0.8, 1.5, -0.3)` returns float in [0,1] — calibration shifts probability ✓
- `apply_calibration(0.0, 1.0, 0.0)` returns EPS — zero handling ✓
- `apply_calibration(1.0, 1.0, 0.0)` returns 1-EPS — one handling ✓
- `compute_blend_weights({a: 0.1, b: 0.2})` produces weights summing to 1.0 with correct ratio ✓
- `blend_predictions` with missing signal re-normalizes and sums to 1.0 ✓
- `loo_cv_blended_brier` returns float in [0,1] for aligned input ✓
- `compute_poisson_base_rate(None)` returns 1.25 — fallback works ✓

## Next Steps
Phase 14 Plan 02 (Wave 2): Integrate blender into simulation pipeline — modify `knockout.py` for `blend_params`, wire calibration pipeline into `main.py:_run_iteration()`, add calibration params persistence in `state.py`, and integrate Poisson base rate into `groups.py`.