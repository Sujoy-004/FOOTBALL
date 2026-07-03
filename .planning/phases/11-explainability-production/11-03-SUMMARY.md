---
phase: 11-explainability-production
plan: 03
subsystem: "display-cli"
tags:
  - "display"
  - "cli"
  - "windows"
  - "utf-8"
  - "hardening"
requires: []
provides:
  - "_ensure_utf8_mode() UTF-8 reconfiguration"
  - "ANSI-documented os.system('') call"
  - "Type-guarded display functions"
  - "ASCII-compatibility test suite"
  - "`_get_console_width()` with shutil.get_terminal_size()"
affects: []
tech-stack:
  added:
    - "shutil.get_terminal_size() (stdlib)"
  patterns:
    - "`_require()` guard decorator for None-safe public API"
key-files:
  created: []
  modified:
    - "competitions/ucl/display.py"
    - "competitions/ucl/main.py"
    - "competitions/ucl/tests/test_cli.py"
    - "competitions/ucl/tests/test_display.py"
decisions:
  - "Use `getattr(..., None) or {}` for None-safe dict access instead of try/except"
  - "`_ensure_utf8_mode()` uses `sys.stdout.reconfigure()` (stdlib, no dependency)"
metrics:
  duration: null
  completed_date: "2026-07-03"
---

# Phase 11 Plan 03: Windows Printing & Output Hardening

**One-liner:** Added UTF-8 mode on Windows, hardened 6 display functions with `_require()` None guards and `.get()` fallbacks, added ASCII-compatibility tests validating all output is pure ASCII (< 128 code points).

## Changes

### 1. `main.py` — Windows UTF-8 mode and ANSI documentation

- **`_ensure_utf8_mode()`:** Reconfigures stdout/stderr to UTF-8 on Windows via `sys.stdout.reconfigure(encoding="utf-8")`
- Called at top of `main()` before any parsing or output
- Expanded `os.system("")` docstring explaining the ENABLE_VIRTUAL_TERMINAL_PROCESSING mechanism
- Pre-existing `_get_config_dir()` helper preserved as-is

### 2. `display.py` — Hardening pass (6 public functions)

Added a `_require()` helper that raises `TypeError` on None input, then applied it to:

| Function | Guard Strategy |
|----------|---------------|
| `print_summary(result)` | `_require()` + `getattr(..., 'N/A')` fallbacks |
| `print_league_table(result)` | `_require()` + early return for empty standings + `.get()` on row dicts |
| `print_playoff_rounds(result)` | `_require()` + early return for empty playoff_ties + `.get()` on tie dicts |
| `print_knockout_bracket(result)` | `_require()` + early return for empty bracket_rounds + `.get()` on match/result dicts |
| `print_odds(result)` | `_require()` + early return for empty teams_data + `.get()` on team dicts |
| `print_validation_summary(dict)` | `_require()` + `.get()` guard on prediction_metrics + calibration |
| `print_signal_breakdown(...)` | `_require()` on contributions + `champion_team` fallback |
| `print_counterfactual_comparison(...)` | `_require()` on both results + `change_descriptions = changes or []` |

All pre-existing display tests pass — the guards are purely defensive additions for unexpected None/corrupt data at runtime.

### 3. `test_display.py` — 8 new tests

- **`TestAsciiCompatibility`** (7 tests): `test_summary_is_ascii`, `test_league_table_is_ascii`, `test_odds_is_ascii`, `test_playoff_is_ascii`, `test_bracket_is_ascii`, `test_full_output_is_ascii` — capture each display function's output and assert every character < 128
- **`TestAnsiConsistency.test_ansi_consistency`** verifies zone colors (`\033[32m`, `\033[33m`, `\033[31m`) do NOT appear in non-zone sections (playoff, bracket, odds)

### 4. `test_cli.py` — Cross-phase merge fixes

- Added `calibrate_temp=False` to `TestArgValidation` Namespace constructions (Phase 10 attribute)
- Added `monkeypatch.delenv("BSD_API_KEY")` to `test_live_mode_needs_api_key` (`.env` file via `load_dotenv()` in conftest.py interferes)

### 5. Pre-existing display helpers (from earlier in this session)

- `_get_console_width()` using `shutil.get_terminal_size()` for TTY-aware line width
- `_capture_tty()` context manager for testing ANSI output under simulated TTY

## Test Results

```
437 passed, 1 skipped in 3.02s
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Cross-Phase Merge]** Fixed `TestAnsiConsistency` class duplication
- **Found during:** Test execution after TestAsciiCompatibility insertion
- **Issue:** Edit duplicated `TestAnsiConsistency` class — first was empty, second had broken indentation
- **Fix:** Removed empty class, restored method definition `test_ansi_consistency(self, sample_result)` with proper indentation
- **Files:** `competitions/ucl/tests/test_display.py`

**2. [Rule 2 - Missing calibration_temp field]** Added `calibrate_temp` to Namespace objects in TestArgValidation tests
- **Found during:** 2 test_cli.py failures — `_validate_args()` references `args.calibrate_temp` (Phase 10 feature)
- **Fix:** Added `calibrate_temp=False` to 4 Namespace constructions in TestArgValidation
- **Files:** `competitions/ucl/tests/test_cli.py`

**3. [Rule 2 - Missing env var isolation]** Added `monkeypatch.delenv("BSD_API_KEY")` to live-mode test
- **Found during:** `test_live_mode_needs_api_key` failed — `conftest.py` calls `load_dotenv()` loading `.env` which sets `BSD_API_KEY`
- **Fix:** Added `monkeypatch.delenv("BSD_API_KEY", raising=False)` to test
- **Files:** `competitions/ucl/tests/test_cli.py`

## Success Criteria Checklist

- [x] `_ensure_utf8_mode()` reconfigures stdout/stderr to UTF-8 on Windows
- [x] `os.system("")` ANSI call is documented with explanation
- [x] 6 public display functions hardened with None guards
- [x] All display output is ASCII-compatible (verified by test)
- [x] New tests validate ASCII output for all display sections
- [x] All 437 tests pass (1 skipped, no regressions)
- [x] No new external dependencies

**Commit:** `c79180f`

## Self-Check: PASSED

- [x] All 5 modified/created files exist
- [x] Commit `c79180f` found in git log
- [x] All 437 tests pass (1 skipped, zero regressions)
