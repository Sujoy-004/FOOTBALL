# Plan 18-01 Summary: xG Extraction & Lambda Override

**Phase:** 18-xg-ai-prediction-signals | **Plan:** 01 | **Wave:** 1

## Objective

Extract `expected_home_goals` / `expected_away_goals` from BSD predictions endpoint during `parse_catboost_response()`, then make these values available as optional lambda overrides in `precompute_matchup_lambdas()`.

## Files Modified

| File | Change |
|------|--------|
| `src/predictors/catboost.py` | Added `_XG_HOME_FIELDS`, `_XG_AWAY_FIELDS` constants, `_extract_xg()` helper, xG extraction wired into `parse_catboost_response()` |
| `src/groups.py` | Added `xg_overrides` param to `precompute_matchup_lambdas()` with D-04 override-or-fallback logic |
| `src/knockout.py` | Added `xg_overrides` param to `run_full_simulation()`, forwarded to `precompute_matchup_lambdas()` |
| `tests/test_groups.py` | Added `TestPrecomputeMatchupLambdas` class with 4 test methods |

## Verification

- `_extract_xg()` returns float (no /100 division), None for missing/empty
- `_extract_xg({'expected_home_goals': 1.48}, ...) == 1.48` ✓
- `precompute_matchup_lambdas()` signature includes `xg_overrides` param ✓
- `run_full_simulation()` signature includes `xg_overrides` param ✓
- 4 xG tests pass (TestPrecomputeMatchupLambdas) ✓
- Full `test_groups.py`: 55 passed (51 existing + 4 new) — zero regressions ✓

## Key Decisions

- xG values NOT divided by 100 (already in Poisson lambda scale per BSD probe)
- When `xg_overrides` is None or match_id absent, falls back to Elo-derived `expected_goals()`
- No changes to `_simulate_single_match()`, `simulate_group_matches()`, blender, ledger, or governance
