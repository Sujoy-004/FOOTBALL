---
phase: 10
plan: 01
name: Calibration Pipeline — Temperature Scaling
subsystem: football_core
tags:
  - calibration
  - temperature-scaling
  - simplex-scaling
  - brent-method
  - cli
  - config
requires:
  - 08-01 (EnsembleEngine blending)
  - 09-01 (Validation baseline)
provides:
  - Temperature-calibrated probabilities at prediction time
  - CLI flag for offline temperature fitting
  - Config persistence for calibration parameters
affects:
  - football_core/blender.py
  - competitions/ucl/main.py
  - competitions/ucl/config/calibration.json
tech-stack:
  added:
    - Brent's method (pure Python, 1D optimization)
    - Simplex temperature scaling (exponentiation + L¹ norm)
  patterns:
    - CalibrationPipeline lifecycle (fit/transform/predict/save/load)
    - Bounded 1D optimization via Brent's method
    - Config file resolution with fallback to identity
metrics:
  duration_minutes: 12
  completed_date: "2026-07-03"
key-files:
  created:
    - tests/test_calibration_pipeline.py
    - competitions/ucl/config/calibration.json
  modified:
    - football_core/blender.py
    - football_core/evaluation.py
    - competitions/ucl/main.py
decisions:
  - "Simplex temperature scaling (q_i = p_i^α / Σ p_j^α) over logit scaling — correct for probability-only ensembles"
  - "Brent's method for 1D optimization — pure Python stdlib, no numpy/scipy dependency"
  - "α bounded [0.1, 10.0] corresponding to T ∈ [0.1, 10.0]"
  - "MatchOutcome dataclass in evaluation.py — actual match result with result and outcome_index properties"
  - "Default calibration.json ships with α=1.0 (T=1.0, identity) — no effect until calibrated"
  - "Prediction-time calibration loads config file and applies temperature_scale to blended predictions"
---

# Phase 10 Plan 01: Calibration Pipeline — Temperature Scaling

## Objective

Implement temperature scaling as the primary calibration mechanism for match-level blended probabilities. Simplex temperature scaling corrects the overconfidence problem (Root Cause #4) by learning a single parameter T that flattens (T>1) or sharpens (T<1) probability distributions.

## What Was Built

### 1. Temperature Scaling (`football_core/blender.py`)
- `temperature_scale(prediction, T)` — Applies simplex temperature scaling: qᵢ = pᵢ^α / Σⱼ pⱼ^α where α = 1/T
- Pure elementwise exponentiation and L¹ normalization (no logit transform)
- Safe exponentiation with underflow protection for extreme probabilities
- Handles edge cases: p=0 → EPS, p=1 → 1-EPS, T=∞ → uniform, T≤0 → ValueError
- Preserves `signal_breakdown` and `weights_applied` through calibration

### 2. Brent's Method Optimizer (`football_core/blender.py`)
- `_brent_minimize(f, a, b)` — 1D minimization with parabolic interpolation + golden-section fallback
- Pure Python stdlib — no numpy/scipy dependency
- Verified on quadratics, absolute value, and higher-degree functions (all converge to < 1e-4)

### 3. CalibrationPipeline Class (`football_core/blender.py`)
- `fit(predictions, outcomes)` — Optimizes α via Brent's method to minimize multiclass log-loss
- `transform(predictions)` — Applies fitted temperature to multiple predictions
- `predict(prediction)` — Convenience wrapper for single predictions
- `save(path)` — Serializes α, T, log_loss, n_samples to JSON
- `load(path)` — Restores from JSON (supports both `alpha` and legacy `T` keys)
- RuntimeError guards on unfitted operations

### 4. MatchOutcome Dataclass (`football_core/evaluation.py`)
- `@dataclass MatchOutcome(home_goals, away_goals)`
- `result` property: 1.0 home win, 0.5 draw, 0.0 away win
- `outcome_index` property: 0 home, 1 draw, 2 away

### 5. CLI Integration (`competitions/ucl/main.py`)
- `--calibrate-temp FILE` flag — reads replay data, fits CalibrationPipeline, saves to config/calibration.json
- Prints: "Calibrated: α={α:.4f} (T={T:.4f}) log-loss improved from {before:.4f} to {after:.4f}"
- `_load_calibration()` helper loads config at prediction time
- Temperature scaling applied automatically to blended predictions when config exists with T ≠ 1.0
- Validation in `_validate_args()`: --calibrate-temp requires --replay-data

### 6. Config File (`competitions/ucl/config/calibration.json`)
- Default: α=1.0, T=1.0, log_loss=null, n_samples=0
- Updated by --calibrate-temp with fitted parameters
- Missing or invalid file results in no calibration (identity transform)

### 7. Test Suite (`tests/test_calibration_pipeline.py`)
- 52 tests across 6 test classes
- Covers: MatchOutcome, temperature_scale, _brent_minimize, CalibrationPipeline, multiclass_log_loss, imports

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Simplex scaling over logit scaling | Probability-only ensembles don't have pre-softmax logits; simplex scaling (elementwise exponent + L¹ norm) is the correct multiclass generalization |
| Brent's method over grid search | Faster convergence; pure Python without numpy/scipy |
| α bounded [0.1, 10.0] | Prevents degenerate solutions; corresponds to T ∈ [0.1, 10.0] |
| Calibration before MC loop | Calibrated match probabilities feed into the simulation for accurate tournament-level probabilities |
| Identity-at-1.0 default | Ships with no calibration effect until explicitly fitted |

## Deviations from Plan

None — plan executed exactly as written with 4 tasks and all acceptance criteria met.

## Stub Tracking

No stubs identified. All implementations are complete:
- `temperature_scale()` fully implemented with all edge cases
- `CalibrationPipeline` has full lifecycle (fit/transform/predict/save/load)
- `_brent_minimize()` converges to high precision
- Tests cover all acceptance criteria

## Threat Flags

None — no new network endpoints, auth paths, or schema changes.

## Self-Check: PASSED

- [x] `temperature_scale()` implemented in football_core/blender.py
- [x] `CalibrationPipeline` class with fit/transform/save/load in football_core/blender.py
- [x] `_brent_minimize()` optimizer with bracketing and convergence criteria
- [x] `--calibrate-temp` CLI flag wired into UCL main.py
- [x] `calibration.json` created in config directory
- [x] Calibration applied automatically at prediction time when config exists
- [x] Identity property holds: α=1.0 returns original probabilities
- [x] All 52 tests pass
- [x] All imports succeed
- [x] `_brent_minimize(lambda x: (x-2.5)**2, 0, 5)` returns ≈ 2.5
- [x] Synthetic overconfident data returns α < 1.0 (T > 1.0)
