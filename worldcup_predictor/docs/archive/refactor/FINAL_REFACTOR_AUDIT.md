# Final Refactor Audit

**Audit date:** June 26, 2026
**Refactor scope:** WP-1 through WP-6 (Phase 1-4 of the refactoring roadmap)
**Commit range:** 6 work packages, ~25 commits across 4 phases

---

## Repository Health

### Architecture

| Dimension | Assessment |
|---|---|
| **Constants** | All magic constants centralized in `src/constants.py`. No inline literals remaining in groups.py, output.py, or main.py. |
| **Private API** | `_normalize_team`, `_find_bracket_match`, `_find_group_match` promoted to public in `fetcher.py`. All external callers updated. |
| **Dead code** | 7 functions with zero production callers removed (incl. tests). |
| **Duplicated code** | 3 instances resolved: (1) sigmoid extracted to `math_utils.py`, (2) `_expected_score_for_match` wrapper inlined, (3) duplicate constants in blender.py removed. |
| **Module boundaries** | `groups.py → blender.py` dependency fully removed. `base_rate` flows explicitly through all 3 function boundaries. |
| **Hidden state** | All 8 main.py globals encapsulated in `RunState` dataclass. `_POISSON_TABLES` cache in groups.py replaced with `functools.lru_cache`. |
| **God object** | Not addressed. main.py remains at 1531 LOC with 21 functions. |

### Module Boundaries

#### Clean (no violations)

| Module | Imports from |
|---|---|
| `src/groups.py` | `math`, `random`, `functools`, `defaultdict`, `src.constants` |
| `src/elo.py` | `src.constants` |
| `src/constants.py` | (none) |
| `src/math_utils.py` | (none) |
| `src/fetcher.py` | `src`, `src.enrichment` |
| `src/predictors/odds.py` | `src`, `src.fetcher`, `src.state` |
| `src/predictors/catboost.py` | `src`, `src.constants`, `src.fetcher`, `src.state` |
| `src/predictors/form.py` | `src`, `src.elo`, `src.math_utils`, `src.state` |
| `src/predictors/lineup.py` | `src`, `src.math_utils`, `src.state` |
| `src/blender.py` | `src`, `src.elo` |
| `src/state.py` | `src`, `src.constants` |

#### Remaining violations

| Module | Violation | Severity |
|---|---|---|
| `src/evaluation.py` | Imports `append_prediction_history`, `load_prediction_history` from `state` — computation module doing I/O | HIGH |
| `src/governance.py` | Imports `print_governance_dashlet` from `output` — governance module doing display | HIGH |
| `src/governance.py` | Imports `save_run_snapshot`, `save_backtest_report` from `state` — governance module doing I/O | MEDIUM |
| `main.py` | 1531 LOC, imports from every module, 20 lazy imports | HIGH |

### Dependency Graph

All dependencies flow **down** the stack (orchestration → display → computation → I/O → config) except for the two violations above. No circular imports exist.

```
main.py ─→ output.py ─→ math_utils.py
  │                     constants.py
  ├─→ groups.py         elo.py
  ├─→ knockout.py
  ├─→ evaluation.py ───→ state.py  ← VIOLATION (computation → I/O)
  ├─→ governance.py ───→ output.py ← VIOLATION (governance → display)
  │                    ─→ state.py  ← VIOLATION (governance → I/O)
  ├─→ blender.py
  ├─→ fetcher.py ─────→ enrichment.py
  ├─→ state.py
  └─→ predictors/*.py
```

### Test Health

| Metric | Value |
|---|---|
| **Total tests** | 614 (613 pass, 1 skipped) |
| **Skip reason** | `test_live_smoke` requires `BSD_API_KEY` |
| **Flaky tests** | `test_main_loop_clean_shutdown` — timing race on shutdown signal |
| **Coverage** | Not measured (no coverage tool configured) |
| **Test time** | ~49s full suite |

### Documentation

| Document | Status |
|---|---|
| `REFACTORING_ROADMAP.md` | Updated through WP-6 |
| `IMPLEMENTATION_PLAN.md` | Updated through WP-6 |
| `ARCHITECTURE_VALIDATION.md` | Present (not reviewed) |
| `WP5_ARCHITECTURE_SUMMARY.md` | Written |
| `WP6_ARCHITECTURE_SUMMARY.md` | Written |

### Technical Debt

#### Eliminated during refactor

- **7 dead functions** removed (save_bracket, load_state_meta, save_state_meta, load_eval_baseline_report, load_backtest_report, loo_cv_blended_brier, compare_baselines)
- **8 module-level globals** in main.py → encapsulated in `RunState` dataclass
- **5 `global` keywords** eliminated
- **1 manual cache** (`_POISSON_TABLES`) → `functools.lru_cache`
- **3 duplicated code** instances consolidated
- **1 hidden module dependency** (groups.py → blender.py) removed
- **2 latent bugs** fixed (governance timer, dead module-level declarations)
- **1 lazy import** removed (blender.py in groups.py)
- **4 private API** functions promoted to public
- **Magic constants** centralized across 4 modules

#### Remaining

See "Remaining Issues" below.

---

## Production Readiness

### Ready to merge

**Yes, with follow-up items.**

The refactor has:
- Zero behavioral regressions in prediction computation (verified by test suite)
- Zero breaking API changes to external interfaces
- Improved code quality across all 6 work packages
- Full test suite passing (613/614)

The repository is in a strictly better state than before the refactor began. Every commit was independently reviewable and independently revertible. The test suite has been green after every commit (except the one intentional revert in 5.2 → 5.2a).

---

## Remaining Issues

### Critical (must fix before production deployment)

None.

### High (should fix in the next work cycle)

| # | Issue | Location | Detail |
|---|---|---|---|
| H1 | **God object** | `main.py` (1531 LOC, 21 functions) | WP-7 planned but not executed. main.py is still the largest module, imports from every module, and contains 20 lazy imports. |
| H2 | **Computation → I/O violation** | `src/evaluation.py` | Imports `append_prediction_history`, `load_prediction_history` from `state`. WP-5.5b planned but not executed. `evaluate_all_matches()` reads from disk internally. |
| H3 | **Governance → display violation** | `src/governance.py` | Imports `print_governance_dashlet` from `output`. WP-5.4 planned but not executed. `run_governance()` prints instead of returning data. |
| H4 | **Large output module** | `src/output.py` (952 LOC) | Contains math functions (`wilson_score_ci`, `coverage_audit`) mixed with display formatting. WP-5.6-5.8 planned but not executed. |

### Medium

| # | Issue | Location | Detail |
|---|---|---|---|
| M1 | **Governance → I/O violation** | `src/governance.py` | Imports `save_run_snapshot`, `save_backtest_report` from `state`. Not planned in any WP. |
| M2 | **Lazy imports** | `main.py` (20 instances) | Strategic (avoids circular imports, improves startup), but masks the god object problem. |
| M3 | **Flaky test** | `test_main_loop_clean_shutdown` | Timing race when sending shutdown signal. ~10% failure rate. |
| M4 | **No coverage tooling** | Project root | No `--cov` configuration or coverage threshold in CI. |

### Low

| # | Issue | Location | Detail |
|---|---|---|---|
| L1 | `_simulate_single_match` default | `src/groups.py` | `base_rate=1.25` default retained on private function. Dead code — only called internally with explicit `base_rate`. |
| L2 | `_normalize` name | `main.py` | Internal normalization function named `_normalize` — inconsistent with `normalize_team` in `fetcher.py`. |
| L3 | Skip test | `test_live_smoke` | Requires `BSD_API_KEY` env var. Not run in CI. |

---

## Future Work

Improvements that are **outside the scope of this refactor** and were never planned:

1. **Test coverage instrumentation** — add `pytest-cov` and set a coverage floor (e.g., 70%).
2. **Type annotations** — many functions lack full type annotations.
3. **CI pipeline** — no CI/CD configuration in the repository.
4. **Documentation generator** — no Sphinx or equivalent setup.
5. **Pre-commit hooks** — no linting, formatting, or type-checking hooks.
6. **Performance profiling** — no benchmark suite for simulation performance.
7. **Thread safety audit** — the `_state` object in main.py is mutated by `_signal_handler` from a signal context (signal handlers run in the main thread, so this is safe, but not documented).
8. **CLI evaluation flags** (`--eval`, `--backtest`) — WP-8, optional, never planned.
9. **Remaining lazy imports in main.py** — WP-7 would naturally resolve these via module extraction.
