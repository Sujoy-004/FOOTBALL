# Implementation Plan (Revised)

> **Policy:** Each commit = one logical change. Independently reviewable. Independently revertible. Project must pass tests after every commit.
>
> **Style:** Casual commit messages. No Conventional Commits. No AI-sounding formality.
>
> **Status:** Planning only — do not implement until approved.

---

## WP-1: Constants Centralization

### Commit 1.1 — add missing constants to constants.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/constants.py` |
| **LOC** | +10 |
| **Tests to run** | `pytest` |

Add named constants. No removal of originals yet — additive only.

```python
MAX_EXPECTED_GOALS = 8.0
HOME_ADVANTAGE_MULTIPLIER = 1.05
POISSON_TABLE_BITS = 10
POISSON_TABLE_SIZE = 1 << POISSON_TABLE_BITS
TREND_THRESHOLD = 0.005
GOVERNANCE_INTERVAL_SECONDS = 3600
```

---

### Commit 1.2 — use constants in groups.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/groups.py` |
| **LOC** | ~6 changed |
| **Tests to run** | `pytest test_groups.py` |

Replace inline definitions and literals with `constants.NAME` imports. Every value is identical to the original.

---

### Commit 1.3 — use constant in output.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/output.py` |
| **LOC** | ~2 changed |
| **Tests to run** | `pytest test_output.py` |

Replace `threshold = 0.005` with `threshold = constants.TREND_THRESHOLD`.

---

### Commit 1.4 — use constant in main.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `main.py` |
| **LOC** | ~2 changed |
| **Tests to run** | `pytest` |

Replace `3600` in `_should_run_gov` with `constants.GOVERNANCE_INTERVAL_SECONDS`.

---

## WP-2: Private API Promotion

### Commit 2.1 — add public aliases to fetcher.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/fetcher.py` |
| **LOC** | +3 |
| **Tests to run** | `pytest test_fetcher.py` |

```python
normalize_team = _normalize_team
find_bracket_match = _find_bracket_match
find_group_match = _find_group_match
```

All existing callers (including `_`-prefixed uses within fetcher.py) continue to work unchanged.

---

### Commit 2.2 — update odds.py and catboost.py imports

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/predictors/odds.py`, `src/predictors/catboost.py` |
| **LOC** | ~4 lines changed per file |
| **Tests to run** | `pytest test_predictors/` |

Change imports from `_normalize_team` to `normalize_team` (same for all three functions). Update the two call sites in each file. The aliases from 2.1 resolve to the same underlying functions.

---

### Commit 2.3 — remove old private names from fetcher.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/fetcher.py` |
| **LOC** | ~3 removed |
| **Tests to run** | `pytest test_fetcher.py` |

Remove the aliases added in 2.1. Rename `_normalize_team` → `normalize_team`, `_find_bracket_match` → `find_bracket_match`, `_find_group_match` → `find_group_match` directly in the function definitions. No callers reference the old names anymore.

---

## WP-3: Dead Code Removal

All commits in WP-3 are **MECHANICAL** — every function has been verified to have zero production callers.

### Commit 3.1 — remove save_bracket

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/state.py`, `test_state.py` |
| **LOC** | ~-12 |
| **Tests to run** | `pytest test_state.py` |

Remove `save_bracket()` function and its single test case in `test_state.py`.

---

### Commit 3.2 — remove state_meta functions

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/state.py` |
| **LOC** | ~-20 |
| **Tests to run** | `pytest test_state.py` |

Remove `load_state_meta()` and `save_state_meta()`. No tests exist for these.

---

### Commit 3.3 — remove load_eval_baseline_report

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/state.py` |
| **LOC** | ~-15 |
| **Tests to run** | `pytest` |

Remove `load_eval_baseline_report()`. Verify it has no imports elsewhere.

---

### Commit 3.4 — remove load_backtest_report

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/state.py`, `test_governance.py` |
| **LOC** | ~-15 |
| **Tests to run** | `pytest test_governance.py` |

Remove `load_backtest_report()` and the test that exercises it.

---

### Commit 3.5 — remove loo_cv_blended_brier

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/blender.py`, `test_blender.py` |
| **LOC** | ~-40 |
| **Tests to run** | `pytest test_blender.py` |

Remove `loo_cv_blended_brier()` function and its 4 test cases.

---

### Commit 3.6 — remove compare_baselines

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/evaluation.py`, `test_evaluation.py` |
| **LOC** | ~-20 |
| **Tests to run** | `pytest test_evaluation.py` |

Remove `compare_baselines()` function and its 3 test cases.

---

## WP-4: Duplicate Code Consolidation

### Commit 4.1 — fold _expected_score_for_match

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `main.py` |
| **LOC** | ~-6 |
| **Tests to run** | `pytest` |

The wrapper function does:
```python
def _expected_score_for_match(t_a, t_b, teams):
    from src.elo import expected_score
    return expected_score(teams[t_a]["elo"], teams[t_b]["elo"])
```

Remove the wrapper. Replace the single call site (line ~702) with the direct expression. The other call at line ~861 already uses `elo.expected_score()` directly. The resulting code is identical at runtime.

---

### Commit 4.2 — extract shared sigmoid function

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | (new) `src/math_utils.py` |
| **LOC** | +12 |
| **Tests to run** | `pytest` |

Create `src/math_utils.py` with identical sigmoid implementation. Nothing consumes it yet — additive only.

---

### Commit 4.3 — use shared sigmoid in form.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/predictors/form.py` |
| **LOC** | ~-10 |
| **Tests to run** | `pytest test_form.py` |

Remove inline `_sigmoid()` from form.py. Import `sigmoid` from `math_utils` and update the call site. The implementation is byte-for-byte identical.

---

### Commit 4.4 — remove duplicate constants from blender.py

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/blender.py` |
| **LOC** | ~-2 (two definitions) + 1 import |
| **Tests to run** | `pytest` |

Remove the duplicate definitions of `COLD_START_THRESHOLD = 30` and `BRIER_WINDOW_SIZE = 50` from `blender.py`. Both already exist in `src/constants.py` with identical values. Import them via `from src import constants` and prefix all four function-default references with `constants.`.

> **Planning note:** The original roadmap referenced `BASE_RATING` — that constant never existed. The actual WP-1 oversight was these two blender.py duplicates, which were added to `constants.py` but never removed from `blender.py`. This commit fixes that oversight.

---### Commit 4.5 — fix duplicate blend logic

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `main.py` |
| **LOC** | ~+2 / ~-5 |
| **Tests to run** | `pytest` + manual verification of match detail table |

**Why runtime behavior changes:**
The current `_gather_signal_data()` uses sequential averaging (order-dependent, equal weights, no calibration). This is incorrect — the comment itself says "same logic as blender" but it is not the same. Replacing it with `blender.blend_predictions()` uses proper Brier-weighted blending.

**Expected before/after difference:**
- **Before:** `blended = elo_prob; if odds: blended = (blended + odds_prob)/2; if cb: blended = (blended + cb_prob)/2` (sequential cascade, later signals diluted)
- **After:** `blended = blend_predictions({"elo": elo_prob, "odds": odds_prob, ...}, weights)` (all signals contribute proportionally to their Brier score)
- Probabilities in the match detail table will differ when multiple signals are available
- **Critical:** This is a **display-only** function. The main simulation uses `_run_calibrate_and_blend()` which already calls blender correctly. Simulation results are unaffected.

**Regression risk:** Low. Only display output changes. No persisted data is affected.

**Verification steps:**
1. Run with real data before the change — capture match detail table output
2. Apply the change
3. Run again — verify table renders valid probabilities (values will differ, but must be in [0,1], sum to 1.0 per match, no crashes)
4. Run full test suite

**Tests required before merge:**
- Existing blender tests already cover `blend_predictions()` behavior
- No new tests strictly required (testing display formatting is fragile), but a regression test for the match detail table rendering would add confidence

---

## WP-5: Module Boundary Enforcement

### Commit 5.1 — add base_rate parameter to expected_goals

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `src/groups.py`, `test_groups.py` |
| **LOC** | ~+3 / ~-4 |
| **Tests to run** | `pytest test_groups.py` |

**Why runtime behavior changes:**
The function signature changes from `expected_goals(rating_a, rating_b, base_rate=None)` to `expected_goals(rating_a, rating_b, base_rate)`. The parameter becomes required (caller must provide it). The internal cache lookup and blender import are removed.

**Expected before/after difference:**
If every caller passes the same `base_rate` value that the old code would have resolved (via cache → blender → constants), the mathematical result is identical. The risk is in the caller providing a stale or wrong value.

**Regression risk:** Medium. Behavior matches only if the caller passes the correct rate. The cache currently falls back to `constants.EXPECTED_GOALS_BASE_RATE` if blender fails — the new callers must replicate this fallback.

**Verification steps:**
1. Note the currently effective base rate (from cache or fallback)
2. Verify main.py passes the exact same value before calling group simulation
3. Run the same simulation with same seed — compare standings output

**Tests required before merge:**
- Update all direct calls to `expected_goals()` in tests to pass `base_rate`
- Add test that verifies passing a specific base rate produces expected goals
- Add test that verifies the fallback behavior (main.py computes rate, defaults to constant if blender fails)

---

### Commit 5.2 — thread base_rate through simulate_group_matches

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `src/groups.py`, `test_groups.py` |
| **LOC** | ~+2 |
| **Tests to run** | `pytest test_groups.py` |

**Why runtime behavior changes:**
`simulate_group_matches()` must now accept and forward `base_rate` to every `expected_goals()` call. Signature changes from `simulate_group_matches(groups, teams, elo, rng, ...)` to `simulate_group_matches(groups, teams, elo, rng, base_rate, ...)`.

**Expected before/after difference:** IDENTICAL (if base_rate is forwarded correctly from the caller in main.py — which doesn't happen until commit 5.3).

**Regression risk:** Low. This is a pass-through. The function itself does not compute or interpret the value.

**Verification steps:**
- No independent verification possible until 5.3 completes

**Tests required before merge:**
- Update all test calls to `simulate_group_matches()` to include `base_rate`
- The tests in 5.2 will be in a temporarily broken state if `main.py` tests reference the old signature. Order of commits matters — 5.2 must be followed by 5.3 before `pytest` passes on main.py tests.

---

### Commit 5.3 — update main.py callers for base_rate

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `main.py`, `src/groups.py` |
| **LOC** | ~+3 / ~-5 |
| **Tests to run** | `pytest` |

**Why runtime behavior changes:**
main.py must now compute or obtain the base rate and pass it to group simulation functions. The cache and balender import in `groups.py` are removed. This completes the dependency inversion.

**Expected before/after difference:** IDENTICAL — main.py must pass the exact same value that `_POISSON_BASE_RATE_CACHE` would have provided.

**Regression risk:** High if the value passed does not match what the cache would have returned. The cache path was: try `blender.compute_poisson_base_rate()` → if exception, fall back to `constants.EXPECTED_GOALS_BASE_RATE`. main.py must replicate this exactly.

**Verification steps:**
1. Before merge, instrument the old code to log the effective base rate
2. After change, verify the same rate is passed
3. Run simulation with same seed — verify same standings and probabilities

**Tests required before merge:**
- Integration test: run one full simulation iteration with old and new code, verify identical output

---

### Commit 5.4 — move governance print to caller

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/governance.py`, `main.py` |
| **LOC** | ~+5 / ~-5 |
| **Tests to run** | `pytest test_governance.py` |

Governance function builds a full snapshot dict internally. Instead of locally importing `print_governance_dashlet` and printing, it returns the snapshot. Main.py receives the snapshot and calls `output.print_governance_dashlet()` with it. Output is byte-for-byte identical.

---

### Commit 5.5 — pass history to evaluate_all_matches

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `src/evaluation.py`, `main.py`, `test_evaluation.py` |
| **LOC** | ~+5 / ~-2 |
| **Tests to run** | `pytest test_evaluation.py` |

**Why runtime behavior changes:**
`evaluate_all_matches()` currently calls `load_prediction_history()` internally. The new parameter `history` allows the caller to pass pre-loaded data. The old call (no argument) falls back to loading from disk — backward compatible.

**Expected before/after difference:** IDENTICAL when `history` is passed (same data, same computation). When `history=None`, the old behavior (load from disk) is preserved.

**Regression risk:** Low. Backward-compatible API change.

**Verification steps:**
1. Call with `history=` containing known data — verify metrics match hand calculation
2. Call with `history=None` — verify old behavior still works

**Tests required before merge:**
- Add test calling `evaluate_all_matches(history=[...])` with synthetic data
- Verify existing tests still pass with default `None` parameter

---

### Commit 5.5b — remove I/O import from evaluation.py

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `src/evaluation.py` |
| **LOC** | ~-2 |
| **Tests to run** | `pytest test_evaluation.py` |

**Why runtime behavior changes:**
Removes `from src.state import append_prediction_history, load_prediction_history`. Makes `history` a required parameter — no more fallback. Callers must now load data before calling.

**Expected before/after difference:** IDENTICAL — if all callers (main.py, tests) have been updated to pass `history` explicitly.

**Regression risk:** Low if callers are updated. High if any caller is missed — they'll get a TypeError.

**Verification steps:**
1. grep for all call sites of `evaluate_all_matches()`
2. Ensure every call now passes `history=`
3. pytest should catch any missed sites

**Tests required before merge:**
- Remove test cases that relied on the no-argument default
- Update all test call sites

---

### Commit 5.6 — extract wilson_score_ci to math_utils

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/output.py`, `src/math_utils.py`, `test_output.py` |
| **LOC** | ~+20 / ~-20 |
| **Tests to run** | `pytest test_output.py` |

Move `wilson_score_ci()` to `src/math_utils.py`. Keep `format_ci()` and `wilson_ci_from_prob()` in output.py (they import and call the moved function). Pure relocation.

---

### Commit 5.7 — extract coverage_audit

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/output.py`, (new) `src/audit.py`, `test_output.py` |
| **LOC** | ~+40 / ~-40 |
| **Tests to run** | `pytest test_output.py` |

Move `coverage_audit()` and its associated field lists (`_PREDICTION_FIELDS`, `_DISPLAY_FIELDS`, `_OPERATIONAL_FIELDS`) to a new `src/audit.py`. Keep `print_coverage_audit()` in output.py (it imports and calls the moved function). Pure relocation.

---

### Commit 5.8 — extract _compute_trend_arrow

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/output.py`, `src/stats.py` (or `src/math_utils.py`) |
| **LOC** | ~+20 / ~-20 |
| **Tests to run** | `pytest test_output.py` |

Move `_compute_trend_arrow()` to the most natural computation module (either `src/math_utils.py` if it already exists from 4.2, or a new `src/stats.py`). Keep `print_probability_table` importing and calling it. Pure relocation.

---

## WP-6: Hidden State Encapsulation

### Commit 6.1 — encapsulate main.py globals

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `main.py` |
| **LOC** | ~+30 / ~-10 |
| **Tests to run** | `pytest` |

**Why runtime behavior changes:**
Eight module-level variables (`_running`, `_elo_last_sync_time`, `_last_gov_time`, etc.) are currently declared at module scope and mutated via `global` inside functions. This changes to a `RunState` dataclass instance passed through functions. The state machine is the same but the delivery mechanism changes from implicit (module scope) to explicit (parameter).

**Expected before/after difference:** IDENTICAL — every function receives the same state object with the same default values. Mutations happen on the same fields. But the change touches every function that currently uses `global`, so there is surface area for error.

**Regression risk:** Medium. The largest single change to main.py's internals. Every `global` declaration must be replaced with a `state.` reference. If one is missed, the `global` keyword is silently redundant but the function reads stale data from module scope instead of the state object.

**Verification steps:**
1. Before: annotate which functions read and write which globals
2. After: verify every read/write goes through `state.` (grep for remaining `global` keywords in main.py — should be zero)
3. Run one full polling cycle — verify no regression in sync timing, governance scheduling, or shutdown behavior

**Tests required before merge:**
- Add test that creates a `RunState` with known values, passes it through each affected function, and checks expected mutations
- Run full test suite after every intermediate state to catch missed references

---

### Commit 6.2 — replace poisson table cache with lru_cache

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `src/groups.py` |
| **LOC** | ~-5 |
| **Tests to run** | `pytest test_groups.py` |

Replace:
```python
_POISSON_TABLES: dict[float, list[int]] = {}
def _build_poisson_table(lam: float) -> list[int]:
    if lam in _POISSON_TABLES:
        return _POISSON_TABLES[lam]
    ...compute...
    _POISSON_TABLES[lam] = table
    return table
```

With:
```python
@functools.lru_cache(maxsize=None)
def _build_poisson_table(lam: float) -> list[int]:
    ...compute...
```

Same caching behavior, same API, no mutable dict at module scope. The cache is thread-safe and automatically cleared between test runs.

---

## WP-7: God Object Decomposition

All commits in WP-7 are **MECHANICAL** — they extract functions into new modules while keeping behavior identical.

### Commit 7.1 — pull cli parsing into its own file

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | (new) `src/cli.py`, `main.py` |
| **LOC** | +60 / -60 |
| **Tests to run** | `pytest` + `python main.py --help` |

Move `_parse_args()`, `_resolve_league_id()`, `validate_api_key()` to `src/cli.py`. Import and call from `main.py`. All imports needed by these functions move with them.

---

### Commit 7.2 — pull signal gathering into its own file

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | (new) `src/signals.py`, `main.py` |
| **LOC** | +80 / -80 |
| **Tests to run** | `pytest` + manual smoke test |

Move `_collect_matches_from_groups()`, `_collect_matches_from_bracket()`, `_gather_signal_data()`, `_merge_signals_into_history()` to `src/signals.py`.

---

### Commit 7.3 — pull migration helpers into own file

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | (new) `src/migration.py`, `main.py` |
| **LOC** | +70 / -70 |
| **Tests to run** | `pytest` |

Move `_migrate_legacy_data()`, `_merge_probability_log()` to `src/migration.py`.

---

### Commit 7.4 — pull historical sync into own file

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | (new) `src/historical_sync.py`, `main.py` |
| **LOC** | +170 / -170 |
| **Tests to run** | `pytest` + manual smoke test |

Move `_run_historical_catch_up()`, `_run_draw_backfill()`, `_run_elo_sync()` to `src/historical_sync.py`.

---

### Commit 7.5 — pull main loop into orchestrator

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | (new) `src/orchestrator.py`, `main.py` |
| **LOC** | +420 / -420 |
| **Tests to run** | `pytest` + full end-to-end smoke test (one polling cycle) |

Move `_run_iteration()`, `_next_poll_sleep()`, `_should_run_gov()`, `_signal_handler()`, `_run_calibrate_and_blend()`, `_compute_group_display()`, `_record_eval_baseline()` to `src/orchestrator.py`. The orchestrator owns a `RunState` and runs the polling loop. Main.py creates the orchestrator and starts it.

---

### Commit 7.6 — slim main.py to just entry point

| Field | Value |
|---|---|
| **Classification** | MECHANICAL |
| **Expected runtime behavior** | IDENTICAL |
| **Files touched** | `main.py` |
| **LOC** | ~-100 (down to ~50 lines) |
| **Tests to run** | `pytest` + manual smoke test |

After all extractions, main.py should contain only: `if __name__ == "__main__": main()` and `def main()` — parses args, resolves league, creates orchestrator, starts loop, handles shutdown.

---

## WP-8: CLI Evaluation Entry Point

### Commit 8.1 — add --eval flag

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `src/cli.py`, `main.py` or `src/orchestrator.py` |
| **LOC** | ~+30 |
| **Tests to run** | `pytest` + `python main.py --eval` |

**Why runtime behavior changes:**
A new command-line flag `--eval` is added. When present, the program runs the evaluation pipeline and exits instead of entering the infinite polling loop. The default behavior (no flags) is unchanged.

**Expected before/after difference:**
- `python main.py` (no flags): runtime behavior IDENTICAL — same polling loop
- `python main.py --eval`: new behavior — runs `evaluate_all_matches()`, prints results, exits
- The `--eval` path calls existing functions, just in a new entry flow

**Regression risk:** Low. New code path; no existing code path is modified. The flag defaults to `False`, so existing callers are unaffacted.

**Verification steps:**
1. `python main.py --help` — verify `--eval` appears in help text
2. `python main.py --eval` — verify evaluation report is printed and process exits
3. `python main.py` (no args) — verify polling loop runs as before

**Tests required before merge:**
- Test that `--eval` invokes `evaluate_all_matches`
- Test that evaluation results print to stdout
- Test that the process exits after evaluation (no polling)

---

### Commit 8.2 — add --backtest flag

| Field | Value |
|---|---|
| **Classification** | BEHAVIORAL |
| **Files touched** | `src/cli.py`, `main.py` or `src/orchestrator.py` |
| **LOC** | ~+30 |
| **Tests to run** | `pytest` + `python main.py --backtest` |

**Why runtime behavior changes:**
A new `--backtest` flag is added. When present, runs `backtest_tournament()` from governance/evaluation modules, prints results, and exits. Default behavior unchanged.

**Expected before/after difference:**
- `python main.py`: IDENTICAL — polling loop
- `python main.py --backtest`: new behavior — runs backtest, prints, exits

**Regression risk:** Low. New code path only.

**Verification steps:**
1. `python main.py --help` — verify `--backtest` appears
2. `python main.py --backtest` — verify backtest report is printed, process exits
3. `python main.py` (no args) — verify polling loop unchanged

**Tests required before merge:**
- Test that `--backtest` invokes `backtest_tournament`
- Test that backtest results print to stdout
- Test that process exits after backtest

---

## Summary

| Package | Commits | Mechanical | Behavioral | Phase |
|---|---|---|---|---|
| WP-1: Constants | 4 | 4 | 0 | 1 |
| WP-2: Private API | 3 | 3 | 0 | 1 |
| WP-3: Dead Code | 6 | 6 | 0 | 1 |
| WP-4: Duplicates | 5 | 4 | 1 | 2 |
| WP-5: Boundaries | 8 | 4 | 4 | 3 |
| WP-6: State | 2 | 1 | 1 | 4 |
| WP-7: Decompose | 6 | 6 | 0 | 5 |
| WP-8: CLI (opt) | 2 | 0 | 2 | 6 |
| **Total** | **36** | **28** | **8** | — |

28 mechanical commits (behavior: IDENTICAL).
8 behavioral commits requiring explicit verification before merge.
