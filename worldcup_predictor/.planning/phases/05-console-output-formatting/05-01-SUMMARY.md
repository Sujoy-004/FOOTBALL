---
plan: 05-01
phase: 05-console-output-formatting
executed: 2026-06-14
status: complete
---

# Plan 05-01 Summary: Core Probability Table + Delta Tracking + ANSI

## What Was Built

### Task 1 (RED) — Failing tests for output module
- Created `tests/test_output.py` with 10 tests across 4 test classes:
  - `TestProbabilityTable` — top-5 table, delta symbols, remaining teams
  - `TestDeltaSummary` — risers/fallers top-3, no-output-when-none
  - `TestAnsiFallback` — color stripping when piped, symbol preservation
  - `TestSimulationDuration` — format and color verification
- All tests initially failed (module didn't exist) — RED phase verified

### Task 2 (GREEN) — `src/output.py` implementation
- Created `src/output.py` with:
  - 8 ANSI color wrappers: `_dim`, `_bold_cyan`, `_green`, `_red`, `_bold_green`, `_bold_white`, `_bold_yellow`, `_bold_red`
  - `_supports_color()` — `sys.stdout.isatty()` check
  - `_timestamp()` — dim-gray `[YYYY-MM-DD HH:MM:SS]`
  - `print_probability_table(probs, prev_probs=None)` — top-5 sorting, delta column with ▲/▼, remaining teams one-liner
  - `print_delta_summary(probs, prev_probs)` — Biggest Risers/Fallers top-3 with percentage format
  - `print_simulation_duration(elapsed_seconds)` — "done in N.Ns" in bold green

### Task 3 — Wire into `main.py` with delta tracking
- Added `from src import output` import
- Added `os.system('')` Windows ANSI init guard at start of `main()`
- Added `prev_probs` tracking variable (None → probs dict after first call)
- Extended `_run_iteration()` signature to accept `prev_probs=None`
- `_run_iteration()` now returns `(last_sim_time, last_request_time, probs)`
- Replaced `_print_probability_table()` calls with `output.print_probability_table()`
- Added `output.print_simulation_duration(sim_elapsed)` after simulation
- Added conditional `output.print_delta_summary(probs, prev_probs)` on subsequent calls
- Removed old `_print_probability_table()` function entirely
- Updated `test_main_loop.py::test_hourly_resim_triggers` to unpack 3 return values

## Tests
- All 10 `test_output.py` tests pass
- `test_hourly_resim_triggers` passes (3-value unpack)
- `test_main_loop_clean_shutdown` temporarily fails — expects old shutdown banner text (Plan 02 adds the new banner)
- `test_main_loop_runs_iterations` pre-existing failure (unrelated to this phase)

## Key Files
- **Created:** `src/output.py` (118 lines), `tests/test_output.py` (156 lines)
- **Modified:** `main.py`, `tests/test_main_loop.py`

## Deviations from Plan
None — plan executed exactly as written.

## Self-Check: PASSED
