# Changelog

## v1.2.0-refactor (2026-06-26)

Systematic refactoring across 6 work packages. Zero regressions. All existing behavior preserved.

### WP-1: Constants Centralization (4 commits)
- Added `MAX_EXPECTED_GOALS`, `HOME_ADVANTAGE_MULTIPLIER`, `POISSON_TABLE_BITS`, `POISSON_TABLE_SIZE`, `TREND_THRESHOLD`, `GOVERNANCE_INTERVAL_SECONDS` to `src/constants.py`
- Replaced inline literals in `groups.py`, `output.py`, `main.py` with named constant references

### WP-2: Private API Promotion (3 commits)
- Promoted `_normalize_team`, `_find_bracket_match`, `_find_group_match` to public API in `src/fetcher.py`
- Updated all import sites in `odds.py` and `catboost.py`

### WP-3: Dead Code Removal (7 commits)
- Removed 7 unused functions: `save_bracket`, `load_state_meta`, `save_state_meta`, `load_eval_baseline_report`, `load_backtest_report`, `loo_cv_blended_brier`, `compare_baselines`
- Removed corresponding test cases

### WP-4: Duplicate Code Consolidation (6 commits)
- Inlined `_expected_score_for_match` wrapper (3 lines → direct call)
- Extracted shared `sigmoid` to `src/math_utils.py`; replaced duplicates in `form.py` and `lineup.py`
- Removed duplicate `COLD_START_THRESHOLD`/`BRIER_WINDOW_SIZE` from `blender.py` (use `constants.*`)
- Replaced sequential averaging in `_gather_signal_data` with Brier-weighted `blend_predictions` (fixes display-only formula)

### WP-5: Module Boundary Enforcement (4 commits)
- Removed `_POISSON_BASE_RATE_CACHE` and `groups.py → blender.py` lazy import
- Made `base_rate` a required parameter in `expected_goals`, `simulate_group_matches`, `precompute_matchup_lambdas`
- Used callers-first, signature-last migration pattern (established as project standard)
- Every caller now passes `constants.EXPECTED_GOALS_BASE_RATE` explicitly

### WP-6: Hidden State Encapsulation (2 commits)
- Replaced 8 module-level mutable globals in `main.py` with `RunState` dataclass
- Removed all 5 `global` keywords
- Replaced `_POISSON_TABLES` dict with `functools.lru_cache` on `_build_poisson_table`
- Fixed 2 latent bugs: governance timer never updated (local shadowing); dead module-level declarations

### Remaining items (not in scope)
- WP-7: God Object Decomposition (main.py: 1531 LOC, 21 functions) — deferred
- WP-8: CLI Evaluation Entry Point (`--eval`/`--backtest` flags) — deferred
- `evaluation.py` still imports `state` (I/O at computation layer) — deferred
- `governance.py` still imports `output` (display at governance layer) — deferred

### Full test suite
613 passed, 1 skipped (requires BSD_API_KEY), 1 flaky (timing race in shutdown test).

---

*For full details see `docs/archive/refactor/`.*
