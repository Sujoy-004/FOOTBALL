---
phase: 20-output-enhancement-coverage-seal
plan: 02
status: complete
verification: passed
duration: ~10 min
---

# Plan 20-02: Probability Log & Trend Tracking — Summary

## What Was Built

Added persistent probability log with per-iteration snapshots and trend arrow column in championship table.

### Task 1: PROBABILITY_LOG_FILE constant + state persistence

- `src/constants.py`: Added `PROBABILITY_LOG_FILE = "probability_log.json"`
- `src/state.py`: Added `load_probability_log()` and `append_probability_log()` — direct analog of prediction_history pattern, uses internal import to avoid circular imports
- `tests/test_state.py`: `TestProbabilityLog` class with 3 tests (load empty, append+load, multiple appends)

### Task 2: Wire snapshot into main.py _run_iteration()

- `main.py`: Added try/except block at end of `_run_iteration()` (after display, before return) capturing `{timestamp, probabilities}` snapshot and appending via `state.append_probability_log()`
- Failure does not propagate — caught exception prints warning to stderr

### Task 3: Trend arrow + Trend column in championship table

- `src/output.py`: Added `_compute_trend_arrow()` — threshold=0.005, 5-window rolling mean, returns ↑/↓/→/space
- `src/output.py`: Modified `print_probability_table()` to accept optional `prob_log` param — backward compatible (default None hides Trend column)
- Trend column appears only when prob_log has ≥6 entries; hidden on first run
- `tests/test_output.py`: `TestTrendColumn` class with 6 tests covering arrow directions, hidden first run, printed column, insufficient data

## Verification

- `pytest -x -q`: **588 passed, 1 skipped, 0 failures** — zero regressions
- All must-haves verified: probability_log persistence, main.py snapshot capture, trend arrow logic, backward-compatible table API
