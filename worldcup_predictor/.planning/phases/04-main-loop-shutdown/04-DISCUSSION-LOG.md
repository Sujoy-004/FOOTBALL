# Phase 4 Discussion Log

**Date:** 2026-06-13
**Phase:** 4 — Main Loop & Shutdown
**Mode:** Interactive (default)

## Areas Discussed

### 1. Loop Structure
- **Options presented:** `while True` + signal handler vs `try/except KeyboardInterrupt`
- **Selected:** `while True` + signal handler (handles SIGINT and SIGTERM, cleaner shutdown)
- **Second question:** New module vs keep in main.py?
- **Selected:** Keep in main.py (no new module, orchestration stays in entry point)
- **Notes:** Signal handler sets `running = False` flag, loop checks at top of each iteration.

### 2. Polling Interval
- **Options presented:** next-poll calculation vs fixed `time.sleep(60)`
- **Selected:** Next-poll calculation (prevents drift, important for rate limit accuracy)
- **Second question:** Default 60s hardcoded vs configurable constant?
- **Selected:** 60s default via `POLL_INTERVAL` constant in constants.py
- **Third question:** Poll immediately on startup vs wait 60s?
- **Selected:** Poll immediately on startup

### 3. Ctrl+C Shutdown
- **Options presented:** Finish current iteration vs abort immediately
- **Selected:** Finish current iteration, then save and exit
- **Second question:** Print final probability table on exit vs save quietly?
- **Selected:** Print "=== Final Championship Probabilities ===" banner + table

### 4. Hourly Re-sim Refresh
- **Options presented:** Track `last_sim_time` vs fixed counter
- **Selected:** Track `last_sim_time`, re-sim if `> 3600s` with no new matches

## Not Discussed (Agent's Discretion)
- Rate limiter implementation — simple timestamp tracking sufficient at 60s polling
- Signal handler registration details
- Exact console log format for polling, shutdown messages

## Deferred Ideas
None.

## Follow-up Items
- Add `POLL_INTERVAL` to constants.py (value: 60)
- Update main.py with while True loop, signal handler, next-poll calculation
- Shutdown: save state, print final banner + probability table
