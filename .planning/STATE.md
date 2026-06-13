# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-13)

**Core value:** A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.
**Current focus:** Phase 4: Main Loop & Shutdown

## Current Position

Phase: 4 of 6 (Main Loop & Shutdown)
Plan: 0 of 0 in current phase
Status: Phase 4 context gathered — ready for planning
Last activity: 2026-06-13 — Phase 4 context gathered (4 areas discussed)

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: ~11 min
- Total execution time: ~22 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 2 | 2 | ~11 min |

**Recent Trend:**
- Last 5 plans: 01-01 (10 min), 01-02 (12 min)
- Trend: Stable

*Updated after each plan completion*

## Phase 3 Decisions (Live API Integration)

- **D-01:** Team-name matching only — no api_id_mapping.json for MVP
- **D-02:** Match by both team names (deterministic per unique knockout match pairings)
- **D-03:** Unmatchable matches → log warning with raw data + skip
- **D-04:** Single `src/fetcher.py` for HTTP + processing
- **D-05:** Two functions: `fetch_raw_matches()` + `process_matches()`
- **D-06:** Full match record returned by process_matches()
- **D-07:** Monkeypatch requests.get for testing — no extra test deps
- **D-08:** Single `test_fetcher.py` following existing patterns
- **D-09:** Minimal JSON fixtures matching only consumed fields
- **D-10:** Case-insensitive alias lookup via team_aliases.json — no fuzzy matching
- **D-11:** Normalization logic inside fetcher.py (private function)
- **D-12:** Aliases loaded by main.py, passed as explicit parameter
- **D-13:** Retry 3x with exponential backoff (1s, 2s, 4s) → cached fallback → continue
- **D-14:** HTTP 429 respects Retry-After header or 60s wait
- **D-15:** Data errors → log + skip that match, continue processing others
- **D-16:** API key validated on startup — fail fast on missing/403
- **D-17:** API_TIMEOUT in constants.py (10s)

## Accumulated Context

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Phase 4 Decisions (Main Loop & Shutdown)

- **D-01:** `while True` loop with `signal.signal(SIGINT)` handler — running flag pattern
- **D-02:** Loop logic in main.py — no new module
- **D-03:** Next-poll calculation (not fixed sleep) — prevents drift
- **D-04:** Default polling interval 60s, configurable via `POLL_INTERVAL` in constants.py
- **D-05:** First poll fires immediately on startup
- **D-06:** Ctrl+C finishes current iteration, then saves and exits
- **D-07:** On shutdown, print "Final Championship Probabilities" banner + table
- **D-08:** Track `last_sim_time`, force re-sim if >3600s with no new matches

## Session Continuity

Last session: 2026-06-13
Stopped at: Phase 4 context gathered
Resume file: .planning/phases/04-main-loop-shutdown/04-CONTEXT.md
