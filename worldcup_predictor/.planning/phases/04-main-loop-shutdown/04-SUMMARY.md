---
phase: 04-main-loop-shutdown
status: complete
tests_passing: 63/63
---

# Phase 4 Summary: Main Loop & Shutdown

## What Was Built

### 1. Polling Loop (`main.py`)
- `while _running:` loop with signal handler (SIGINT, SIGTERM, SIGBREAK on Windows)
- First poll fires immediately on startup (no initial 60s wait)
- Next-poll calculation: `time.time() + POLL_INTERVAL` prevents drift when fetch/sim takes variable time
- `_next_poll_sleep(interval)` — deadline-based sleep in 0.5s increments, responsive to Ctrl+C within 500ms
- `_run_iteration()` — single fetch→process→simulate→print cycle, returns `(last_sim_time, last_request_time)`

### 2. Graceful Shutdown
- Ctrl+C sets `_running = False`, loop finishes current iteration, then:
  1. Prints `=== Final Championship Probabilities ===` banner
  2. Runs final simulation with latest state
  3. Prints probability table
  4. Saves state (`save_teams`, `save_played`)
  5. Prints "State saved. Goodbye." and returns

### 3. Rate Limiter (`_run_iteration`)
- Tracks `last_request_time` across iterations
- If elapsed since last request < `POLL_INTERVAL`, sleeps the difference before making API call
- Prevents hitting Football-Data.org's 10 req/min limit

### 4. Hourly Re-sim (D-08)
- Tracks `last_sim_time` across iterations
- If `time.time() - last_sim_time > 3600` with no new matches, auto-refreshes simulation
- Prints "Auto-refresh simulation (no new matches)" and re-runs without API call
- Resets `last_sim_time` to keep the hourly cadence

### 5. Constants (`src/constants.py`)
- `POLL_INTERVAL: int = 60` — overridable via `POLL_INTERVAL` env var (for testing)

### 6. Test Coverage (`tests/test_main_loop.py`)
3 tests:
- `test_main_loop_runs_iterations` — subprocess-based: verifies >=2 "Fetched" lines in 5s with POLL_INTERVAL=1
- `test_main_loop_clean_shutdown` — subprocess-based: sends CTRL_BREAK_EVENT on Windows, verifies shutdown banner
- `test_hourly_resim_triggers` — unit test: monkeypatches `time.time` and `run_simulation`, verifies hourly re-sim fires without API call

## Key Decisions Executed
- D-01: `while True` + `signal.signal(SIGINT)` running flag (not try/except KeyboardInterrupt)
- D-02: Loop logic in main.py — no new module
- D-03: Next-poll calculation (not fixed sleep) prevents drift
- D-04: `POLL_INTERVAL = 60` default in constants.py
- D-05: First poll fires immediately
- D-06: Ctrl+C finishes iteration, saves state, prints final output
- D-07: `"=== Final Championship Probabilities ==="` banner + probability table on shutdown
- D-08: Track `last_sim_time`, hourly re-sim if >3600s with no new matches

## Verification Status

| Check | Status |
|-------|--------|
| `pytest -x` (full suite) | ✅ 63/63 passing |
| `test_main_loop_runs_iterations` | ✅ Multiple fetch cycles verified |
| `test_main_loop_clean_shutdown` | ✅ Shutdown banner + state save verified |
| `test_hourly_resim_triggers` | ✅ Hourly re-sim without API call verified |
| `test_main_runs_successfully` | ✅ Startup output preserved |
| Ctrl+C terminates within 500ms | ✅ 0.5s sleep granularity in `_next_poll_sleep` |

## Files Changed
- `worldcup_predictor/main.py` — full rewrite: signal handler, `_run_iteration`, `_print_probability_table`, `_next_poll_sleep`, new `main()` with loop
- `worldcup_predictor/src/constants.py` — added `POLL_INTERVAL` (env-overridable), added `import os`
- `worldcup_predictor/tests/test_main_loop.py` — new module (3 tests)
- `worldcup_predictor/tests/test_state.py` — updated `test_main_runs_successfully` for loop compatibility

## Next
- Phase 5: Console Output & Formatting (ANSI colors, delta tracking, live UI polish)
