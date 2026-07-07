# Plan 12-09 Summary — WC Calibrated Validation + Weights

## Goal
Add calibrated validation comparison (`--validate-calibrated`) and static weight override (`--weights`) to the World Cup batch simulator.

## Changes

### `competitions/worldcup/main.py`
- Added `--validate-calibrated` flag — compares prediction metrics before/after calibration
- Added `--weights K=V,K=V` flag — static blend weight override (normalizes to sum 1.0)
- Added `_parse_weights()` — validates K=V syntax, known signal names, non-negative values, normalizes
- Added `_find_actual_champion()` — traces bracket tree to identify actual tournament champion
- Added `_run_calibrated_validation()` — runs two simulations (uncalibrated + calibrated), computes Brier, Log Loss, ECE, TRPS, champion accuracy
- Added `_print_calibration_comparison()` — side-by-side table with Before/After/Delta columns, ANSI coloring (green for improvement, red for degradation)
- Wired both flags into `_parse_args()` and `_run_batch_mode()`
- Mode validation: both flags error if used without `--simulate`

## Verification
- All new functions import correctly
- `_parse_weights` handles normal, single-key, unknown-signal, and non-numeric cases
- `_print_calibration_comparison` renders with sample data and handles no-calibration case
- CLI flags render in `--help`
- Mode checks: `--validate-calibrated` and `--weights` without `--simulate` exit with clear error

## Next
Proceed to Wave 5: Plan 12-10 (smoke test + integration)
