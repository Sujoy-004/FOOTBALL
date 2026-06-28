# Plan 02-04: MC Integration + Stage Probabilities

**Completed:** 2026-06-28
**Status:** ✓ Complete

## Summary

Integrated the full knockout pipeline (playoff → bracket → tree) into the Phase 1 Monte Carlo loop, adding per-team stage probability tracking across all 7 D-09 stages.

## Completed Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Implement `track_knockout_stages()` per D-09 | `4e1c568` |
| 2a (RED) | Add failing tests for MC knockout integration | `8397ddf` |
| 2b (GREEN) | Extend MC loop with knockout pipeline + D-09 stage probs | `35e8ebe` |
| 3 | Full MC + knockout pipeline smoke test (checkpoint) | Approved |

## Files Modified

| File | Change |
|------|--------|
| `competitions/ucl/src/knockout.py` | Added `track_knockout_stages()` |
| `competitions/ucl/src/simulation.py` | Extended `run_monte_carlo()` with knockout pipeline; extended `aggregate_mc_results()` with `stage_collectors`; added `STAGE_ORDER`/`STAGE_TO_VALUE` constants |
| `competitions/ucl/src/__init__.py` | Added `track_knockout_stages` export |
| `competitions/ucl/tests/conftest.py` | Added `sample_knockout_stage_result`, `sample_stage_collectors` fixtures |
| `competitions/ucl/tests/test_knockout.py` | Added `TestStageTracking` (6 tests) |
| `competitions/ucl/tests/test_monte_carlo.py` | Added `TestMonteCarloKnockout` (8 tests) |

## Implementation Deviations (Accepted)

| Deviation | Rationale |
|-----------|-----------|
| `top_8_prob <= knockout_r16` (not `==`) | Teams can reach R16 via playoff win, not just top-8 auto-qual |
| Lowercase stage normalization | D-09 spec uses lowercase; `simulate_knockout_tree()` produced uppercase |
| Top-8 zone → `r16` default | Missing override in original plan code for top-8 teams |
| Used `sample_elo_dict` in MC tests | 4-team fixture insufficient for 36-team schedule |

## Test Results

- 40/40 knockout tests pass (14 + 9 + 11 + 6)
- 105/106 UCL tests pass (1 skipped = live ClubElo API)
- Stage probabilities sum to 1.0 for all 36 teams
- Champion probability reflects knockout champion (not league position 1)
- `aggregate_mc_results()` backward compatible without `stage_collectors`
- WC regression: pre-existing `FileNotFoundError` in `worldcup_predictor/tests/` (unrelated)
- `football_core` unchanged

## Dependencies Satisfied

- UCLK-05: ✅ Full tree with stage probabilities
- D-07: ✅ Single MC loop with knockout integration
- D-08: ✅ Post-aggregation pattern for stage probabilities
- D-09: ✅ 7-stage granularity: Eliminated → Playoff → R16 → QF → SF → Final → Champion
- D-11: ✅ No football_core modifications
