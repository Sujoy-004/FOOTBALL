---
plan: 05-02
phase: 05-console-output-formatting
executed: 2026-06-14
status: complete
---

# Plan 05-02 Summary: Lifecycle Output Blocks

## What Was Built

### Task 1 (RED) — Tests for remaining output blocks
- Extended `tests/test_output.py` with 13 new tests across 7 new test classes:
  - `TestHeader` — startup banner format and ANSI
  - `TestMatchAlert` — match result block with score/winner
  - `TestEloChanges` — old→new rating display with colored deltas
  - `TestHeartbeat` — single-line poll heartbeat
  - `TestAutoRefresh` — hourly re-sim one-liner
  - `TestShutdownBanner` — all-teams table, format, no deltas
  - `TestError` — bold red warning prefix
  - `TestTimestampConsistency` — timestamp on log-line blocks
- All tests initially failed (functions didn't exist) — RED phase verified

### Task 2 (GREEN) — 7 new output functions
- Added to `src/output.py`:
  - `print_header(teams, bracket, played, aliases)` — startup banner with `=` separators and counts
  - `print_match_alert(match)` — bold yellow match result block
  - `print_elo_changes(updates)` — old→new Elo with green/red deltas
  - `print_heartbeat()` — single dim-gray "Polling... no new matches."
  - `print_auto_refresh()` — hourly re-sim one-liner
  - `print_shutdown_banner(probs)` — all-teams green banner + "State saved. Goodbye."
  - `print_error(message)` — bold red `⚠` prefix to stderr
- Added `sys.stdout.reconfigure(encoding="utf-8")` for Windows Unicode support
- Imported `POLL_INTERVAL` from constants for header display

### Task 3 — Wire all lifecycle events in main.py
- Replaced 5 startup prints with single `output.print_header()` call
- Match detection uses `output.print_match_alert()` + `output.print_elo_changes()`
- Heartbeat replaces both "Polling..." and "No new matches from API" lines
- Hourly re-sim uses `output.print_auto_refresh()`
- Shutdown path uses `output.print_shutdown_banner()` (replaces 3 prints)
- Error paths use `output.print_error()` to stderr (replaces old print→stderr)
- Signal handler kept as plain text (user-facing)
- State saves moved inside match loop (save after each match)
- Updated test assertions in `test_main_loop.py` and `test_state.py`

## Encoding Fix
- Added `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at module init
- `print_error()` writes to stderr for proper error stream separation

## Tests
- 23 output tests pass (10 from Plan 01 + 13 new)
- 5 simulation tests pass
- 18 state tests pass (updated assertions for new header format + encoding)
- test_hourly_resim_triggers passes (3-value unpack)
- test_main_loop_runs_iterations: pre-existing Windows subprocess issue (unrelated)
- test_main_loop_clean_shutdown: pre-existing Windows signal delivery issue (unrelated)

## Deviations from Plan
- `print_error()` writes to stderr instead of stdout (corrected — errors belong on stderr)
- Added `sys.stdout.reconfigure()` for Windows Unicode support (required for ▲, ▼, ⚠)
- Updated `test_state.py` assertions for new header format

## Self-Check: PASSED
