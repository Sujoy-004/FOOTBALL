# Phase 2.5 — Canonical Data Repair Audit

> Generated: 2026-06-22

---

## 1. probability_log.json Migration Gap

### Current behavior

`_migrate_legacy_data()` at `main.py:1204-1210` lists 13 files to copy from `data/` to `data/27/`:

```python
league_scoped_files = [
    "played.json", "played_groups.json", "teams.json",
    "predictions_ledger.json", "prediction_history.json",
    "catboost_cache.json", "odds_cache.json", "form_cache.json",
    "lineup_cache.json", "elo_applied.json", "elo_update_log.json",
    "calibration_params.json", "versions.json",
]
```

`probability_log.json` is NOT in this list.

This file was introduced later (Phase 20-02, commit `100d42c`) — the migration list was defined in Phase 19-02 (commit `9586653`) and never updated.

### Consequences

| Scenario | Behavior |
|----------|----------|
| **Fresh install** (no data/27/) | Migration runs, copies 13 files. `probability_log.json` stays in root `data/`. New probability log snapshots go to `data/27/` because `append_probability_log()` is called with `data_dir=league_data_dir` at `main.py:1106`. **Result: probability_log.json in data/27/ is created with only post-migration entries.** |
| **Existing install** (data/27/ exists, guard file present) | Migration skipped. `probability_log.json` exists only in root. New snapshots go to `data/27/`. **Result: two diverged copies — root has old entries, data/27/ has new entries.** |
| **Deleting data/27/** | `probability_log.json` loses all post-migration entries (they were only in data/27/). Root still has pre-migration entries but they're stale. |

### Root cause

Migration list is hardcoded and was not updated when `probability_log.json` was added.

### Fix

Add `"probability_log.json"` to the `league_scoped_files` list in `_migrate_legacy_data()`.

---

## 2. eval_baseline.json Status

### Finding: Orphaned file — ZERO code references

ZERO references to `eval_baseline.json` exist in any `src/`, `main.py`, or `tests/` file.

The file contains an old baseline from Jun 15:
```json
{"brier": 0.178, "log_loss": 0.717, "n_matches": 3}
```

### What `_record_eval_baseline()` actually writes

`_record_eval_baseline()` at `main.py:565-591` writes to **`eval_baseline_report.json`** (not `eval_baseline.json`). Proof:
- Line 580: `from src.state import save_eval_baseline_report`
- Line 583: `save_eval_baseline_report(report, data_dir)`
- `state.py:969-979`: writes to `eval_baseline_report.json`

### Two separate files

| File | Size | Code references | Purpose |
|------|------|----------------|---------|
| `data/eval_baseline.json` | 138 B | **NONE** | Legacy artifact from pre-Phase 12b |
| `data/eval_baseline_report.json` (root) | 353 B | Active code | Phase 13 baseline — stale copy (n_matches=0) |
| `data/27/eval_baseline_report.json` | 2050 B | Active code | Canonical copy (n_matches=29 with calibration bins) |

### Verdict

`eval_baseline.json` is **safe to delete** — no code path reads it.

---

## 3. eval_backtest_report.json Ownership

### Current location: root `data/` only

`eval_backtest_report.json` exists ONLY in root `data/` (348 B). There is no copy in `data/27/`.

### Code flow

```
main.py:1399-1407  _run_governance(..., data_dir=league_data_dir)
  → governance.py:348  _run_backtest(teams)            ← NO data_dir passed!
    → governance.py:576  save_backtest_report(aggregate_report)  ← NO data_dir!
      → state.py:1119-1126  writes to DATA_DIR / "eval_backtest_report.json"
```

### Bug: data_dir is not threaded

`_run_governance()` receives `data_dir` (line 324) but does NOT pass it to `_run_backtest(teams)` at line 348. And `_run_backtest()` does not accept a `data_dir` parameter — its signature is `def _run_backtest(teams, historical_data_dir=None)`.

### Is this a problem for runtime correctness?

**No, for two reasons:**

1. The backtest only reads historical tournament files (`data/historical/2018.json`, `data/historical/2022.json`) which are shared across all leagues. It does NOT read per-league state.
2. The backtest report is informational (best signal ranking) — no runtime path depends on it being in a specific directory.

### However

If multi-league becomes active and different leagues have different backtest results, the report would overwrite itself in root `data/`. This is a latent correctness bug that will surface when leagues >1 are in use.

### Verdict

Fix: thread `data_dir` through `_run_backtest()` and `save_backtest_report()`. Currently benign (single league).

---

## 4. Stale Root Copy Read Verification

### All 6 diverged files — production code analysis

| File | All reads in main.py pass `data_dir`? | Any read without `data_dir`? | Verdict |
|------|---------------------------------------|------------------------------|---------|
| **prediction_history.json** | YES — lines 93, 849, 954, 980, 1002, 1060 — all pass `data_dir` | `test_evaluation.py:176` calls `load_prediction_history()` without `data_dir` | Production is clean. **Test has a stale read.** |
| **predictions_ledger.json** | YES — all calls pass `data_dir` via `ledger_upsert` or direct load/save | None found | Clean |
| **calibration_params.json** | YES — lines 955, 976 — both pass `data_dir` | None found | Clean |
| **form_cache.json** | YES — line 936 — `save_signal_cache(form_cache, FORM_CACHE_FILE, data_dir)` | None found | Clean |
| **lineup_cache.json** | YES — line 945 — `save_signal_cache(lineup_cache, LINEUP_CACHE_FILE, data_dir)` | None found | Clean |
| **odds_cache.json** | YES — lines 894, 900, 1449 — all pass `data_dir` or `league_data_dir` | None found | Clean |

### Edge case: `test_evaluation.py:176`

```python
from src.state import load_prediction_history
h = load_prediction_history()  # ← NO data_dir → reads from root data/
```

This test depends on the real `data/prediction_history.json` being populated. It reads from root `data/` instead of `data/27/`. If root is cleaned, this test breaks.

However, this is a **test bug**, not a production bug. The test was written in Phase 11 (before the multi-league framework) and was never updated.

### Other test code

All other test calls to `load_signal_cache`, `save_signal_cache`, `load_backtest_report` etc. use `data_dir=tmp_path` — no stale reads.

---

## A. Repair Plan

### Fix 1: Add probability_log.json to migration list

**File:** `main.py:1204-1210`

**Change:** Insert `"probability_log.json"` into `league_scoped_files` list.

This ensures fresh migrations include the file. Existing installs can manually copy `data/probability_log.json` to `data/27/probability_log.json` once (or just let it grow from scratch in data/27/).

### Fix 2: Thread data_dir through _run_backtest

**Files:** `src/governance.py:348, 463, 576`

**Changes:**
1. Add `data_dir` parameter to `_run_backtest(teams, data_dir=None, historical_data_dir=None)`
2. Pass it to `save_backtest_report(aggregate_report, data_dir)`
3. Update call site `_run_governance` to pass `data_dir=data_dir` to `_run_backtest`

Low urgency (single league, benign today). Do together with Fix 1 to minimize commits.

### Fix 3: Update test_evaluation.py to pass data_dir (optional)

**File:** `tests/test_evaluation.py:176`

**Change:** Pass `data_dir=<league_data_dir>` or use `tmp_path`. Prevents test from depending on real root `data/` files.

### Fix 4: Delete orphaned eval_baseline.json

Delete `data/eval_baseline.json` (138 B, zero code references).

### Recommended commit order

```
Fix 1 + Fix 2  →  "fix: thread data_dir through _run_backtest and add probability_log to migration list"
Fix 3          →  "test: update test_evaluation.py to use data_dir instead of root data/"
Fix 4          →  "chore: remove orphaned eval_baseline.json"
```

---

## B. Risk Analysis

| Fix | Risk | Mitigation |
|-----|------|------------|
| **Fix 1** (migration list) | No risk. File is copied if it exists. Data/27/probability_log.json starts clean if no root copy. | Guard file check prevents re-migration. |
| **Fix 2** (backtest data_dir) | Low risk. Changes save location from `data/` to `data/27/`. No reader depends on file being in `data/`. | Verify `load_backtest_report` is never called from elsewhere without `data_dir`. |
| **Fix 3** (test stale read) | Low risk. Test currently reads real data. Changing to `tmp_path` requires providing fixture data. | Simplest fix: just pass `data_dir=tmp_path` and assert on entries the test just created. |
| **Fix 4** (delete orphan) | Zero risk. No code path references it. | Verify with grep before deleting. |

### Regression test coverage

| Fix | Tests that cover it |
|------|-------------------|
| Fix 1 | `test_migration.py` — migration tests with `tmp_path` |
| Fix 2 | `test_governance.py:758-764` — verifies `save_backtest_report` is called |
| Fix 3 | `test_evaluation.py:169-183` — the test itself |
| Fix 4 | No test — orphan detection |

---

## C. Files That Become Removable After Repair

### Post-Fix 1 (probability_log migration)

The root `data/probability_log.json` becomes a stale copy that can be deleted. Data/27/probability_log.json becomes the canonical copy.

### Post-Fix 2 (backtest data_dir)

After this fix, `data/eval_backtest_report.json` (root) becomes stale. The canonical location would be `data/27/eval_backtest_report.json`. However, this only applies on next backtest run.

**Caveat:** If the backtest report is intentionally shared (not per-league), then root is correct and no change is needed. The question is: should backtest results be per-league? For current single-league usage, either location works.

### After all repairs + root cleanup

The following files become removable from root `data/`:

| File | Reason |
|------|--------|
| `probability_log.json` | Will exist in `data/27/` after Fix 1 migration (or fresh run) |
| `eval_baseline.json` | Orphan — no code references (Fix 4) |
| `eval_baseline_report.json` | Stale — canonical copy in `data/27/` |
| `prediction_history.json` | Stale — canonical copy in `data/27/` |
| `predictions_ledger.json` | Stale — canonical copy in `data/27/` |
| `calibration_params.json` | Stale — canonical copy in `data/27/` |
| `form_cache.json` | Stale (127 B empty) — canonical in `data/27/` |
| `lineup_cache.json` | Stale (127 B empty) — canonical in `data/27/` |
| `odds_cache.json` | Stale — canonical (or soon-to-be) in `data/27/` |
| `teams.json` | Stale — canonical in `data/27/` |
| `played_groups.json` | Stale (2 B empty) — canonical in `data/27/` |
| `played.json` | Both empty — keep until migration guard file check is confirmed |
| `versions.json` | Identical — keep until confirmed |
| `catboost_cache.json` | Both empty — keep until confirmed |
| `elo_applied.json` | Stale — canonical in `data/27/` |
| `elo_update_log.json` | Diverged — canonical in `data/27/` |
| `eloratings_cache.json` | Diverged — canonical in `data/27/` |

### Files that stay in root `data/` permanently

| File | Reason |
|------|--------|
| `bracket.json` | Shared — no `data_dir` passed in production |
| `groups.json` | Shared — no `data_dir` passed |
| `annex_c.json` | Shared — no `data_dir` passed |
| `team_aliases.json` | Shared — no `data_dir` passed |
| `team_values.json` | Shared — `load_team_values()` defaults to DATA_DIR |
| `eval_backtest_report.json` | Shared until Fix 2 is applied |

### Remaining unresolved decision

`eval_backtest_report.json`: should it be per-league (`data/27/`) or shared (`data/`)? Currently it's shared-only. The historical backtest data (2018, 2022) is shared, so root `data/` is arguably correct for now. If the decision is "keep shared," then Fix 2 changes nothing for this file.
