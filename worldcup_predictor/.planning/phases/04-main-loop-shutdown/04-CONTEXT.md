# Phase 4: Main Loop & Shutdown — Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

System runs autonomously — polls the Football-Data.org API continuously, detects new matches, triggers Elo updates and re-simulation, and shuts down gracefully on Ctrl+C with state persistence and final probability output. Does NOT include output formatting (Phase 5) or CLI flags (Phase 6).

Requirements: LOOP-01, SHUT-01

**Already decided (carried forward from Phase 3):**
- Fetcher handles retry (3x, 1s/2s/4s) + cached fallback — never crashes on API failure (D-13)
- API key validated on startup — fail fast on missing/403 (D-16)
- Per-match error handling, skip bad matches, continue (D-15)

</domain>

<decisions>
## Implementation Decisions

### Loop Structure
- **D-01:** `while True` loop with `signal.signal(signal.SIGINT)` handler setting a running flag (`running = False`). The loop checks the flag at the top of each iteration. Handles both SIGINT and SIGTERM cleanly. Not `try/except KeyboardInterrupt` (can't save state mid-sleep).
- **D-02:** Loop logic lives in `main.py`. No new module — the file is already the orchestrator. Extracting to `src/loop.py` would add a module boundary with no testability benefit since the loop is orchestration, not logic.

### Polling Interval
- **D-03:** Next-poll calculation — compute `next_poll = time.time() + POLL_INTERVAL` after each iteration, then `time.sleep(max(0, next_poll - time.time()))`. Prevents drift when fetch+simulate takes variable time. Important for rate limit accuracy.
- **D-04:** Default interval 60s, configurable via `POLL_INTERVAL` constant in `constants.py` (matches existing constants pattern: `K_FACTOR`, `API_TIMEOUT`).
- **D-05:** First poll fires immediately on startup (no initial 60s wait). User sees fresh data right away.

### Ctrl+C Shutdown
- **D-06:** Finish current iteration, then save and exit. Signal handler sets `running = False`, the loop completes any in-progress fetch/process/simulate, saves state (`save_teams`, `save_played`), prints final output, then returns cleanly.
- **D-07:** On shutdown, print `"=== Final Championship Probabilities ==="` banner followed by the probability table. Gives the user a snapshot to read before the terminal session ends.

### Hourly Re-sim Refresh
- **D-08:** Track `last_sim_time` in the loop. At the start of each iteration (before polling), check if `time.time() - last_sim_time > 3600`. If threshold exceeded with no new matches, force re-sim and print `"Auto-refresh simulation (no new matches)"`. Avoids fixed-counter approach which breaks if polling interval changes.

### the agent's Discretion
- Rate limiter implementation — simple last-request timestamp tracking is sufficient at 60s polling (1-2 req/min, well under 10 req/min limit). Track `last_request_time`, skip poll if `time.time() - last_request_time < 60`.
- Exact console log format for re-sim, shutdown, polling messages.
- Signal handler registration details (atexit module, signal.signal calls).
- `POLL_INTERVAL` name and placement in constants.py.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/ROADMAP.md` — Phase 4 goal: "System runs autonomously — polls continuously, detects new matches, triggers re-simulation, and shuts down gracefully on Ctrl+C."
- `.planning/REQUIREMENTS.md` — LOOP-01 (continuous polling), SHUT-01 (graceful shutdown)

### Phase 3 Decisions (carried forward)
- `.planning/phases/03-live-api-integration/03-CONTEXT.md` — D-13 (retry + fallback), D-15 (per-match errors), D-16 (API key validation)

### Technical Specifications
- `SOTs/TRD.md` §5.2 — Main loop specification (poll interval, shutdown sequence)
- `SOTs/PRD.md` §6 — Functional requirements FR8 (continuous polling), FR9 (graceful shutdown)

### Codebase Architecture
- `.planning/codebase/ARCHITECTURE.md` — Module boundaries, data flow
- `.planning/codebase/INTEGRATIONS.md` — API rate limits (10 req/min)

### Existing Source Files
- `worldcup_predictor/main.py` — Loop lives here (D-02). Currently loads state, fetches, simulates, prints.
- `worldcup_predictor/src/constants.py` — Add POLL_INTERVAL here (D-04).
- `worldcup_predictor/src/fetcher.py` — fetch_raw_matches() consumed inside the loop.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `main.py` — existing orchestration flow: load state → fetch → simulate → print. The loop wraps this.
- `constants.py` — constants pattern; `POLL_INTERVAL` to be added.
- `signal` module — stdlib, no new dependencies for SIGINT handling.

### Established Patterns
- Pure functional style — signal handler sets a module-level flag or closure variable.
- main.py as orchestrator — no new module needed for loop logic (D-02).
- Next-poll calculation: `time.sleep(max(0, next_poll - time.time()))`.

### Integration Points
- `main.py` — the existing flow is the loop body; wrap in while True, add signal handler.
- `constants.py` — add `POLL_INTERVAL: int = 60`.
- `state.save_teams()` / `state.save_played()` — called on shutdown to persist state.
- `main.py` print statements — final probability banner printed before exit.

</code_context>

<specifics>
## Specific Ideas

- "No new module" — the loop is orchestration, staying in main.py keeps things simple.
- "Signal handler, not KeyboardInterrupt" — cleaner shutdown path, handles SIGTERM too.
- "Fresh data on first run" — poll immediately, don't wait 60s before showing data.
- "Save first, then print final" — state persisted to disk before the final output is printed.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 4-Main Loop & Shutdown*
*Context gathered: 2026-06-13*
