# 14-02 SUMMARY — Simulation Pipeline Integration

**Phase:** 14 (Signal Blending)  
**Plan:** 2 of 2 — Wave 2  
**Status:** ✅ Complete  
**Date:** 2026-06-17  

## Goal
Integrate the blender core module (Plan 01) into the live simulation pipeline so that `run_full_simulation` can optionally blend Elo with market odds and CatBoost signals.

## Files Changed

| File | Change |
|------|--------|
| `src/knockout.py` | Added `_get_blended_prob()` helper; updated `_simulate_r32_resolved`, `_simulate_r16`, `_simulate_knockout_round`, `_simulate_tpp`, and `run_full_simulation` to accept optional `blend_params` argument |
| `src/state.py` | Added `load_calibration_params()` and `save_calibration_params()` with atomic write |
| `src/constants.py` | Added `CALIBRATION_PARAMS_FILE`, `COLD_START_THRESHOLD`, `BRIER_WINDOW_SIZE` |
| `src/groups.py` | Added `_POISSON_BASE_RATE_CACHE` + auto-warming in `expected_goals()`; added `_reset_poisson_base_rate_cache()` for tests |
| `main.py` | Added `_run_calibrate_and_blend()` orchestrator; wired `blend_params` into simulation calls in `_run_iteration()`; added Poission base rate warmup at startup; wired blend_params into shutdown path |
| `tests/test_blender.py` | Added `TestBlendPipeline` integration test (40 total blender tests) |

## Architecture

```
main.py _run_iteration()
  ↓ load_signal_cache (odds, catboost)
  ↓ _run_calibrate_and_blend()
    → calibrate_and_blend() [blender.py]
      → calibrate_signal() per signal (Platt)
      → compute_rolling_brier() per signal
      → compute_blend_weights() from Brier scores
      → blend_predictions() for upcoming matches
  ↓ run_full_simulation(teams, ..., blend_params=result)
    → knockout helpers use _get_blended_prob(match_id, blend_params)
      → blend_params["match_probs"][match_id] || Elo fallback
```

## Verification

- 40 blender tests pass (1 new: `TestBlendPipeline::test_end_to_end_with_mock_data`)
- 427 total tests pass (1 skipped — live smoke needs BSD_API_KEY)
- 0 regressions

## Commits

- `c92f065` — feat(14-02): integrate blender pipeline into simulation

## Key Details

- `blend_params: dict | None` — `None` preserves pure Elo behavior (backward compatible)
- `_get_blended_prob()`: lookup in `match_probs` dict; fallback to `match_probs_elo` or default 0.5
- Cold start: `calibrate_and_blend()` returns `None` when history < `COLD_START_THRESHOLD` (30)
- Poisson base rate cached globally — computed once via historical match data, default 1.25
- Shutdown path also computes blend_params for final printed probabilities
