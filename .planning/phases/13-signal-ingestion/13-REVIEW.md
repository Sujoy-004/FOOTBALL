---
phase: 13-signal-ingestion
reviewed: 2026-06-16T17:30:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - worldcup_predictor/src/constants.py
  - worldcup_predictor/src/state.py
  - worldcup_predictor/src/predictors/__init__.py
  - worldcup_predictor/src/predictors/odds.py
  - worldcup_predictor/src/predictors/catboost.py
  - worldcup_predictor/src/evaluation.py
  - worldcup_predictor/main.py
  - worldcup_predictor/tests/test_odds.py
  - worldcup_predictor/tests/test_catboost.py
  - worldcup_predictor/tests/test_state.py
  - worldcup_predictor/tests/test_evaluation.py
  - worldcup_predictor/tests/test_main_loop.py
findings:
  critical: 0
  warning: 7
  info: 4
  total: 11
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-06-16T17:30:00Z  
**Depth:** standard  
**Files Reviewed:** 12  
**Status:** issues_found  

## Summary

Reviewed 12 source files for the Phase 13 (Signal Ingestion) implementation. The core logic for market odds ingestion (`odds.py`) and CatBoost ML prediction ingestion (`catboost.py`) is sound, with proper caching, retry logic, and error handling. However, several cross-cutting issues exist: silent exception swallowing in the evaluation pipeline, dead parameters, unused imports, and importing private (`_`-prefixed) functions across module boundaries. No CRITICAL security vulnerabilities or data-loss bugs were found, but 7 WARNING-level issues should be addressed before shipping.

---

## Warnings

### WR-01: `except Exception: pass` silently swallows all errors in evaluation pipeline

**File:** `worldcup_predictor/src/evaluation.py:212-215`  
**Issue:** Inside `evaluate_all_matches(signal_name="elo")`, the call to `apply_elo_update()` is wrapped in a bare `try/except Exception: pass`. If `apply_elo_update` fails for any reason (missing team, corrupt data, key error), the error is completely suppressed — no log, no warning, no counter increment. The same pattern repeats on lines 240-244 for `append_prediction_history()`.

This means corrupted datasets or partial failures will silently produce incorrect evaluation reports without any diagnostic output. A user evaluating 100 matches might get results for only 80 and never know.

**Fix:** Replace silent `pass` with logging at minimum:

```python
try:
    apply_elo_update(m, replay_teams)
except Exception as e:
    logger.warning("Elo update failed for match %s: %s", m.get("match_id", "?"), e)
```

And same principle for lines 240-244:

```python
try:
    append_prediction_history(entry)
except Exception as e:
    logger.warning("Failed to append prediction history entry for %s: %s",
                   entry.get("match_id", "?"), e)
```

### WR-02: `is_cache_valid()` accepts a dead `ttl_hours` parameter that is never used

**File:** `worldcup_predictor/src/state.py:734-757`  
**Issue:** The `ttl_hours` parameter is documented as "used for logging, not expiry computation — expiry is read from the cache itself." However, `ttl_hours` is never referenced anywhere in the function body. No logging occurs. This is misleading API design — callers may expect `ttl_hours` to influence expiry behavior, but it is silently ignored.

Every call site passes this parameter (e.g., `is_cache_valid(odds_cache, ODDS_CACHE_TTL_HOURS)` on `main.py:550`), creating a false sense of configurability.

**Fix:** Either remove the parameter entirely, or actually use it (e.g., for cache-expiry fallback if `expires_at` is missing):

```python
def is_cache_valid(cache: dict, ttl_hours: int = 12) -> bool:
    if not cache:
        return False
    expires_at = cache.get("expires_at")
    if not expires_at:
        # Fallback: compute expiry from fetched_at + ttl_hours
        fetched_at = cache.get("fetched_at")
        if fetched_at:
            try:
                fetched = datetime.fromisoformat(fetched_at)
                return datetime.now(timezone.utc) < fetched + timedelta(hours=ttl_hours)
            except (ValueError, TypeError):
                pass
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) < expiry
    except (ValueError, TypeError):
        return False
```

### WR-03: `evaluate_all_matches(signal_name="elo")` has undocumented persistent side effects

**File:** `worldcup_predictor/src/evaluation.py:240-244` and `worldcup_predictor/src/evaluation.py:72-91` (docstring)  
**Issue:** The function `evaluate_all_matches` is named as a read-only evaluation function, but when called with `signal_name="elo"`, it writes prediction history entries to disk via `append_prediction_history()` (lines 240-244). This side effect is not documented in the function's docstring (lines 72-91).

A caller expecting a pure computation (metrics in, report out) will be surprised that the function mutates persistent state. This is especially dangerous in scripts that call this function for ad-hoc evaluation or testing — they will silently accumulate prediction history entries.

**Fix:** Add a clear docstring warning:

```
Note: When signal_name="elo", this function writes compound prediction history
entries to prediction_history.json via append_prediction_history(). This is a
persistent side effect — call with caution in read-only contexts.
```

### WR-04: `remove_vig()` has no input validation — relies entirely on callers

**File:** `worldcup_predictor/src/predictors/odds.py:22-44`  
**Issue:** `remove_vig()` performs no validation that its inputs are positive numbers. If called with zero or negative odds, it will raise a `ZeroDivisionError` or produce meaningless probabilities. Currently, the only call site (`parse_odds_response`, line 148) is guarded by `_odds_available()` which checks `val <= 0`, but this is a fragile pattern — a future caller or a test bypassing the guard will crash.

**Fix:** Add input validation with a clear error message:

```python
def remove_vig(odds_home: float, odds_draw: float, odds_away: float) -> dict[str, float]:
    if odds_home <= 0 or odds_draw <= 0 or odds_away <= 0:
        raise ValueError(f"Odds must be positive: home={odds_home}, draw={odds_draw}, away={odds_away}")
    p_home = 1.0 / odds_home
    p_draw = 1.0 / odds_draw
    p_away = 1.0 / odds_away
    ...
```

### WR-05: Private (`_`-prefixed) functions imported from `src.fetcher` across module boundaries

**File:** `worldcup_predictor/src/predictors/odds.py:17`  
**File:** `worldcup_predictor/src/predictors/catboost.py:30-34`  
**Issue:** Both `odds.py` and `catboost.py` import private functions from `src.fetcher`:

```python
from src.fetcher import _find_bracket_match, _find_group_match, _normalize_team
```

Python convention reserves the `_` prefix for internal module implementation details. Importing these from other modules creates a fragile API surface — if `src.fetcher` ever renames or refactors these functions, the two predictor modules will silently break. Testing the fetcher module in isolation also becomes harder because its "private" interface has external consumers.

**Fix:** One of:
1. Make these functions public in `src.fetcher` (rename to `find_bracket_match`, etc.) and update imports.
2. Create a shared `src.matchers` module that exports the team-resolution helpers publicly.
3. At minimum, document in `fetcher.py` that these functions are considered semi-public and consumed by the predictors package.

### WR-06: `_merge_signals_into_history` crashes on corrupt cache entries

**File:** `worldcup_predictor/main.py:63-67`  
**Issue:** When merging signal cache data into prediction history entries, the function uses `dict(odds_matches[mid])` and `dict(cb_matches[mid])` assuming the cache values are always dicts. If a cache file is corrupted (e.g., a value is `None`, a number, or a list instead of a dict), this will raise `TypeError: cannot convert dictionary update sequence element #0 to a sequence`, crashing the main loop.

The cache files are written by `save_signal_cache` / `_atomic_write_json`, which generally produces valid JSON, but manual editing or disk corruption could cause this.

**Fix:** Add a type guard before the conversion:

```python
if mid in odds_matches and "market_odds" not in signals:
    val = odds_matches[mid]
    if isinstance(val, dict):
        signals["market_odds"] = dict(val)
        changed = True
    else:
        logger.warning("Expected dict for odds match %s, got %s", mid, type(val).__name__)
```

Same for catboost on line 66.

### WR-07: `evaluate_all_matches` function exceeds 200 lines with high cyclomatic complexity

**File:** `worldcup_predictor/src/evaluation.py:72-301`  
**Issue:** The function `evaluate_all_matches()` spans 230 lines (72-301) with three major branching paths (`signal_name is None`, `signal_name == "elo"`, and the fallthrough other-signal case). Each path has distinct logic for data loading, metric computation, and result formatting. This makes the function difficult to test exhaustively and easy to introduce bugs in one path while modifying another.

The function also mixes concerns: data loading (from files), computation (metrics), and persistence (writing history).

**Fix:** Extract each major branch into its own named function:

```python
def _evaluate_all_signals(history: list[dict]) -> dict: ...
def _evaluate_elo_signal(teams, played, played_groups) -> dict: ...
def _evaluate_named_signal(history, signal_name) -> dict: ...
```

Then `evaluate_all_matches` becomes a dispatcher calling the appropriate helper.

---

## Info

### IN-01: Unused imports in `main.py`

**File:** `worldcup_predictor/main.py:8,12`  
**Issue:** `import copy` (line 8) and `import math` (line 12) are never referenced in any function body in `main.py`. `copy.deepcopy` is used in `evaluation.py`, not in `main.py`.

**Fix:** Remove both unused imports.

### IN-02: Unused imports in `test_evaluation.py`

**File:** `worldcup_predictor/tests/test_evaluation.py:3,5`  
**Issue:** `import json` (line 3) and `import os` (line 5) are imported but never used in any test function.

**Fix:** Remove both unused imports.

### IN-03: `50%%` in docstring should be `50%`

**File:** `worldcup_predictor/src/constants.py:68`  
**Issue:** The docstring for `ELO_BLEND_THRESHOLD` contains `50%%` which is likely a double-escaped format specifier. Since this is a regular string (not an f-string or format string), it appears literally as `50%%`. This is cosmetic but could confuse readers.

**Fix:** Replace `50%%` with `50%`.

```python
ELO_BLEND_THRESHOLD: int = 30
"""Drift above this threshold triggers overwrite+flag; below triggers 50% blend (D-11)."""
```

### IN-04: `os.system("")` for Windows ANSI support creates unnecessary subprocess

**File:** `worldcup_predictor/main.py:661`  
**Issue:** The `os.system("")` call on line 661 enables ANSI escape sequence processing on Windows by spawning `cmd /c ""`. While this works, it launches an unnecessary child process on every startup. More targeted approaches exist:

- `kernel32.SetConsoleMode()` via ctypes to enable `ENABLE_VIRTUAL_TERMINAL_PROCESSING` directly
- Using `colorama.just_fix_windows_console()` if colorama is available

**Fix:** Use ctypes-based approach for minimal overhead:

```python
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
```

---

_Reviewed: 2026-06-16T17:30:00Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
