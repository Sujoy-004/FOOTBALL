# Codebase Concerns

**Analysis Date:** 2026-06-16 (v2.0 update: 11 src modules, 329 tests)

## Tech Debt

### Hardcoded Bracket Structure for a Single Tournament
- **Issue:** The bracket tree (`bracket.json`) is hardcoded for the 2026 World Cup knockout stage (R32→R16→QF→SF→TPP→FINAL). No generic bracket builder exists.
- **Impact:** Zero reusability. Every tournament requires manual data entry. 48-team format with 40-match bracket is fully hardcoded.
- **Status:** Still open. Deferred to post-v2.0.

### All Configuration Hardcoded in constants.py
- **Issue:** Parameters like `K_FACTOR`, `SIMULATION_COUNT`, `API_URL` are hardcoded. Environment variable support added for `POLL_INTERVAL` only.
- **Impact:** Non-technical users cannot tune behavior without editing source code.
- **Partial fix:** `POLL_INTERVAL` now overridable via env var. CLI flags (`--seed`, `--once`) provide runtime control.
- **Remaining:** `K_FACTOR`, `SIMULATION_COUNT`, `DEFAULT_ELO`, `API_URL` still hardcoded.

### Single-Threaded Blocking Architecture
- **Issue:** API calls (HTTP requests) and simulation (CPU-bound, up to 15s at 50K iterations) both block the main thread.
- **Impact:** During simulation runs (~10-15s), newly finished matches are not detected. Combined with API latency, detection could exceed 120-second target.
- **Status:** Open. Mitigated by 60s poll interval leaving 45-50s headroom.

### No Logging Beyond Console
- **Issue:** All output to `print()` (stdout). No log file, no structured logging, no way to review history after terminal scrolls.
- **Impact:** If terminal is closed, all history (matches detected, Elo changes, probability shifts) is lost.
- **Status:** Open. Console-only remains.

### Probability Deltas Computed Only In-Memory
- **Issue:** Previous probabilities stored only in local variable. No historical record of probability changes.
- **Partial fix:** `prediction_history.json` now created by `evaluation.py` for post-hoc analysis. Delta display live in console.
- **Remaining:** No trend visualization, no built-in historical browser.

## Known Bugs

### Probability Sum Drift from Floating Point Accumulation
- **Issue:** Monte Carlo counts wins / n_simulations. Sum may differ from 1.0 by 1e-6 to 1e-3.
- **Status:** Partially addressed — probabilities normalized before display. ±0.001 tolerance documented.
- **Tests:** Covered by simulation probability sum assertions.

### Elo Update Applying to Wrong Team When API Returns "DRAW"
- **Issue:** If API returns `winner: "DRAW"`, Elo updater needs defensive handling.
- **Status:** Mitigated — `fetcher.py` handles draws for knockout matches via penalty resolution. Group matches naturally allow draws (winner=null).

### API Mapping File Drift
- **Issue:** `api_id_mapping.json` no longer used. BSD API uses event `id` deduplication with in-memory set + persisted `played.json`/`played_groups.json` match_id lookup. Team name normalization via `team_aliases.json` + `groups.json` team names handles identification.
- **Status:** **Resolved** — removed dependency on `api_id_mapping.json`. Match identification now uses team pair + group letter for groups, and direct match_id mapping for knockout.

### ANSI Colors Broken on Some Windows Terminals
- **Issue:** Windows Command Prompt and older PowerShell versions don't support ANSI escape codes natively.
- **Status:** Mitigated — `os.system("")` enables Console Host ANSI on modern Windows. `sys.stdout.reconfigure(encoding="utf-8")` for Unicode. `--no-color` flag as fallback.

## Security Considerations

### API Key Exposure via Environment Variable
- **Risk:** API key read from `BSD_API_KEY` environment variable. Could leak via error messages, child process environments, accidental `print()` debugging.
- **Mitigation:** `.env.example` exists with clear instructions. `.env` in `.gitignore`. Key validated on startup. Never logged.
- **Recommendations:** Same as v1.0 — never log key partially, validate format, don't echo API error responses verbatim.

### No Input Validation on JSON Files
- **Risk:** JSON files loaded with `json.load()` without schema validation. Corrupted data could cause crashes.
- **Partial fix:** `validate_groups()` and `validate_annex_c()` added in Phase 7. Bracket validation at startup (unique IDs, source_matches, no cycles).
- **Remaining:** No full schema validation for `teams.json`, `played.json`, `played_groups.json`. No jsonschema dependency.

### No Rate Limiting Enforcement for API Calls
- **Risk:** 60-second poll interval is a code default, not enforced client-side. If interval is set too low via `POLL_INTERVAL` env var, free tier (10 req/min) could be exceeded.
- **Status:** Still open — relies on human awareness of rate limit.

## Performance Bottlenecks

### Monte Carlo Simulation — 50,000 Iterations
- **Current:** Full 104-match simulation at 50K iterations takes ~10-15s (projected, actual varies). Group stage (72 Poisson matches) is the heaviest component.
- **Improvements implemented:**
  - Precomputed matchup lambdas in `groups.py` for Poisson score generation
  - No deep copies of bracket — recursive winner-only progression
  - Running totals during match simulation (not recomputed from scratch)
- **Remaining:** Still pure Python `random.random()` per call. `expected_score()` cache could help.

### API Call Blocks Main Loop
- **Problem:** `requests.get()` is synchronous. Typical response takes 1-2s; timeouts up to 10s (configured `API_TIMEOUT=10`).
- **Status:** Accepted limitation for single-threaded design.

### Disk I/O on Every Match Detection
- **Problem:** Every detected match triggers JSON writes for state persistence.
- **Status:** Acceptable. JSON serialization + atomic write for ~5-50KB files is <10ms.

## Fragile Areas

### Team Name Normalization (API → Internal)
- **Files:** `src/fetcher.py`, `data/team_aliases.json`
- **Why fragile:** BSD API team names may vary from canonical names (e.g., "Korea Republic" vs "South Korea"). All 48 teams need alias coverage.
- **Status:** `team_aliases.json` expanded for 48 teams. Group team names from `groups.json` also used for matching.
- **Test coverage:** Group integration tests (INTG-01 through INTG-07) cover team name matching.

### Bracket Tree Recursive Traversal
- **Files:** `src/knockout.py`
- **Why fragile:** Bracket is a nested recursive structure. Bug in traversal produces wrong champions or crash.
- **Mitigation:** Startup bracket validation (unique IDs, source_matches, no cycles). Test coverage for full simulation.

### Graceful Shutdown During Simulation
- **Files:** `main.py`
- **Why fragile:** `KeyboardInterrupt` could fire during JSON write, corrupting files.
- **Mitigation:** Deadline-based sleep (0.5s increments) enables responsive shutdown. `_running` flag checked between iterations.

## Scaling Limits

| Resource | Current Capacity | Limit | Scaling Path |
|---|---|---|---|
| API requests | 1 req/min | 10 req/min (free tier) | Upgrade to paid tier |
| Simulation iterations | 50,000 | ~15s on reference hardware | Parallelize or use NumPy |
| Concurrent users | 1 (console app) | 1 | Web backend + database |
| Tournament scope | 1 bracket (2026 WC) | Fixed hardcoded format | Generic bracket builder |
| State file size | ~50KB total | JSON fine at this scale | SQLite for >100MB |
| Memory | <500MB | Depends on simulation data | Streaming aggregation |

## Dependencies at Risk

### Python `requests` Library
- Low risk — well-maintained, ubiquitous. Only external HTTP dependency.

### BSD (Bzzoiro Sports Data) Free API
- **Risk:** External service could change endpoint, data format, rate limits, or shut down the free tier.
- **Migration:** `fetcher.py` interface designed so alternative APIs can be swapped in. Mock data provider exists for testing.

### `colorama` (Not Used)
- Not currently a dependency — pure stdlib ANSI via `os.system("")`. No colorama risk.

## Missing Critical Features

### No Data Validation Layer
- **Status:** Partially addressed — `validate_groups()`, `validate_annex_c()`, bracket validation exist. No full schema validation for all JSON files.
- **Priority:** Medium — startup validation catches most issues.

### No Health Check or Self-Diagnostics
- **Status:** Open. Script prints heartbeat but has no "time since last match detection" warning.
- **Priority:** Medium — silent failure mode exists.

## Test Coverage Gaps

| Untested Area | What's Not Tested | Risk | Priority |
|---|---|---|---|
| **Long-running stability** | Memory leak from dict accumulation, infinite loop from bracket bug | High | Medium |
| **BSD API failure cascade** | API fails → mock data fallback with different format → crash | High | High |
| **Elo edge cases** | Equal ratings, extreme differences, negative K-factor | Medium | Low |
| **Multiple new matches** | Two matches finish between polls, both detected in one cycle | Medium | Low |
| **Empty API response** | API returns empty or unexpected structure | High | Medium |
| **Ctrl+C during JSON write** | Shutdown signal during `json.dump()` or `os.rename()` | Medium | Medium |

---

*Concerns audit: 2026-06-16 (v2.0)*
