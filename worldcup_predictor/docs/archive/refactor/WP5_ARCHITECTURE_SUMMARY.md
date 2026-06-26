# WP-5 Architecture Summary: Module Boundary Enforcement

**Commits:** 5.1, 5.2a, 5.2b, 5.3 (4 commits)

---

## Public API Changes

### Signatures that changed

| Function | Before | After | Files affected |
|---|---|---|---|
| `expected_goals` | `(rating_a, rating_b, base_rate=None)` | `(rating_a, rating_b, base_rate)` | `src/groups.py`, `test_groups.py` |
| `precompute_matchup_lambdas` | `(groups, elo_ratings, xg_overrides=None, base_rate=1.25)` | `(groups, elo_ratings, base_rate, xg_overrides=None)` | `src/groups.py`, `main.py`, `src/knockout.py`, tests |
| `simulate_group_matches` | `(groups, teams, elo, rng, fair_play=True, ..., base_rate=1.25)` | `(groups, teams, elo, rng, base_rate, fair_play=True, ...)` | `src/groups.py`, `main.py`, `src/knockout.py`, benchmarks, tests |

All three moved `base_rate` from "optional with default" to "required (positional)". Every caller now provides the value explicitly.

### Signatures that remained stable

- `_simulate_single_match` — private function, only called internally from `simulate_group_matches` which always passes `base_rate` explicitly. Retained default as dead code for now.
- All functions in `main.py`, `knockout.py`, `blender.py`, `output.py`, `evaluation.py`, `governance.py`, `state.py`, `predictors/` — unchanged.

---

## Dependency Changes

### Dependencies removed

- `_POISSON_BASE_RATE_CACHE` module-level global in `src/groups.py` (54a42b2).
- `_reset_poisson_base_rate_cache()` function in `src/groups.py`.
- `from src.blender import compute_poisson_base_rate` inside `expected_goals()` (lazy import).
- All hidden fallback logic in `expected_goals` that tried blender, caught exceptions, and fell back to `constants.EXPECTED_GOALS_BASE_RATE`.

### Dependencies introduced

- None. The `base_rate` value originates from `constants.EXPECTED_GOALS_BASE_RATE` at every call site. No new imports.

### Cycles eliminated

- **Indirect cycle removed:** `groups.py` → `blender.py` (via lazy import in `expected_goals`). If `blender.py` ever imported from `groups.py` (now or in the future), it would have formed a cycle. The lazy import pattern was a symptom of this concern. Now `groups.py` has no import to `blender.py`.

---

## Boundary Improvements

### Modules that became more independent

**`src/groups.py`** is now self-contained for its simulation logic:
- Imports only: `math`, `random`, `defaultdict`, `src.constants`.
- No knowledge of `blender.py`, `evaluation.py`, or any predictor module.
- All data that controls its behavior (`base_rate`) arrives as a parameter, not as a hidden cache or lazy import.

**`src/knockout.py`** now imports `src.constants` and passes `base_rate` explicitly to groups functions. It no longer relies on groups.py resolving a value internally.

### Data that now flows explicitly instead of implicitly

| Before | After |
|---|---|
| `expected_goals` called `blender.compute_poisson_base_rate()` internally and cached the result in a module global. | `expected_goals` receives `base_rate` as a required parameter. The caller owns the value. |
| `precompute_matchup_lambdas` silently used `constants.EXPECTED_GOALS_BASE_RATE` when callers didn't pass `base_rate`. | Every caller must pass `base_rate` explicitly. No fallback. |
| `simulate_group_matches` fell back to the same hidden default. | `base_rate` is the 5th positional parameter — required. |

The data flow is now fully explicit: **`constants.EXPECTED_GOALS_BASE_RATE`** → caller (main.py, knockout.py, tests) → `precompute_matchup_lambdas` → `expected_goals`. No module in the chain guesses or resolves the value on its own.

---

## Validation

### Full test suite

**613 passed, 1 skipped** (`test_live_smoke` requires `BSD_API_KEY`). No regressions across all 4 commits.

### Live validation required?

**No.** Every WP-5 commit was classified as MECHANICAL (behavior: IDENTICAL). The runtime value of `base_rate` was `constants.EXPECTED_GOALS_BASE_RATE` (1.25) both before and after — the old cache always resolved to this same constant. No prediction output changed.

(The lone BEHAVIORAL classification in the original plan was for 5.3's cache removal, but the cache was dead code: `compute_poisson_base_rate()` with no arguments always returns 1.25, which equals the constant, so the cache was never populated.)

---

## Lessons Learned

### Callers-first, signature-last migration pattern

The original plan for Commit 5.2 required making `base_rate` required in `simulate_group_matches`, which temporarily broke 15 tests until Commit 5.3. During review, this was identified as avoidable. The improved pattern:

1. Update every caller while backward compatibility exists (default argument kept).
2. Verify the full suite is green.
3. Remove the default only after all callers have migrated.

This was validated in the revised 5.2a/5.2b split and applied again in 5.3 (single commit since all callers were in the same scope). The pattern is now a permanent project standard, documented in `IMPLEMENTATION_PLAN.md`.

### Automated caller verification

A Python script that parses all `.py` files and verifies every call site of a migrated function includes the required parameter is a fast safety net. Worth automating as a pre-commit hook for future API migrations.

### Default removal and positional reordering

When a parameter moves from "keyword with default" to "required positional", Python's syntax requires it to precede any remaining optional parameters. Using the callers-first pattern, this reordering is invisible because all external callers use keyword arguments (`base_rate=...`), not positional binding.

### Hidden defaults vs explicit parameters

The original design used module-level caches and lazy imports to make `expected_goals` "smart" about its own base rate. This created a hidden dependency chain (`groups.py` → `blender.py` → I/O → `constants.py`). Making `base_rate` explicit at every boundary simplified reasoning, eliminated a potential import cycle, and removed a mutable module-level cache that could cause state leakage between test cases.
