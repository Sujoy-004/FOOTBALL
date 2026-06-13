# Codebase Concerns

**Analysis Date:** 2026-06-13

## Tech Debt

### Hardcoded Bracket Structure for a Single Tournament
- **Issue:** The bracket tree (`bracket.json`) is hardcoded for a specific World Cup's knockout stage (Round of 16 → Quarterfinals → Semifinals → Final). There is no generic bracket builder. To support a different tournament (e.g., 2022 WC, 2030 WC), the entire JSON structure must be manually rewritten.
- **Files:** `SOTs/Backend_Schema.md` (lines 43–73), `SOTs/TRD.md` (lines 55–69)
- **Impact:** Zero reusability. Every tournament requires manual data entry. If the tournament format changes (e.g., 48-team WC with different knockout structure), the schema breaks entirely.
- **Fix approach:** Define a generic bracket generator that accepts a list of Round of 16 pairings and automatically constructs the tree. Store tournament metadata (year, format) as a parameter.

### All Configuration Hardcoded in constants.py
- **Issue:** Parameters like `K_FACTOR`, `POLL_INTERVAL_SECONDS`, `SIMULATION_COUNT`, `API_URL`, and `DEFAULT_ELO_START` are hardcoded in `constants.py`. Changing any parameter requires editing source code.
- **Files:** `SOTs/Backend_Schema.md` (lines 119–129), `SOTs/Appflow.md` (lines 258–263)
- **Impact:** Non-technical users cannot tune behavior. No way to run multiple instances with different configurations without code changes. This violates the PRD's "one command to run" goal but also creates a maintenance burden.
- **Fix approach:** Add a `config.json` file (optional, overrides defaults) and/or command-line arguments (e.g., `--poll-interval 30`, `--simulations 100000`).

### Single-Threaded Blocking Architecture
- **Issue:** The MVP is explicitly single-threaded and synchronous. API calls (HTTP requests taking 1–2 seconds) block the main loop. The simulation (CPU-bound, up to 5 seconds) also blocks polling.
- **Files:** `SOTs/Appflow.md` (lines 213–218), `SOTs/TRD.md` (lines 188–211)
- **Impact:** During the ~7 seconds of API + simulation, newly finished matches are not detected. If a match ends and the next poll is blocked, detection could exceed the 120-second latency target (NFR1).
- **Fix approach:** Move the simulation to a background thread so polling continues concurrently. For MVP this is acceptable, but should be tracked.

### No Logging Beyond Console
- **Issue:** All output goes to `print()` (stdout). There is no log file, no structured logging, and no way to review history after the terminal scrolls past.
- **Files:** `SOTs/UI_UX_Design.md` (lines 224–226), `SOTs/TRD.md` (line 253)
- **Impact:** If the terminal is closed, all history (matches detected, Elo changes, probability shifts) is lost. Debugging issues requires watching the script in real time. Cannot audit what happened overnight.
- **Fix approach:** Add optional `--log <file>` flag to write timestamped output to a file alongside console.

### Probability Deltas Computed Only In-Memory
- **Issue:** Previous probabilities are stored only in a local variable in the main loop. There is no historical record of probability changes. The "delta" shown on re-simulation is between the last run and current run only.
- **Files:** `SOTs/Implementation_plan.md` (lines 139–142), `SOTs/UI_UX_Design.md` (lines 71–77)
- **Impact:** Cannot analyze how predictions evolved over time. No data for post-tournament analysis or visualization (planned for v1.2 web dashboard).
- **Fix approach:** Append each simulation output to a `history.json` file with timestamps. This enables trend analysis and the future web dashboard.

---

## Known Bugs (Anticipated — No Code Yet)

### Probability Sum Drift from Floating Point Accumulation
- **Issue:** Monte Carlo simulation counts wins and divides by `n_simulations`. Due to floating-point arithmetic, the sum of all probabilities may differ from 1.0 by small amounts (1e-6 to 1e-3).
- **Files:** `SOTs/Implementation_plan.md` (line 174), `SOTs/Backend_Schema.md` (line 302)
- **Symptoms:** Console output shows probabilities like "34.2% + 27.9% + 15.1% + 12.3% + 10.5% = 100.0001%" causing minor confusion.
- **Trigger:** Every simulation run with large iteration counts.
- **Workaround:** Normalize probabilities to sum exactly to 1.0 before display. Accept ±0.001 tolerance as documented.

### Elo Update Applying to Wrong Team When API Returns "DRAW"
- **Issue:** The design assumes knockout matches always have a winner (penalties resolve draws). But if the API returns `winner: "DRAW"` (possible if the endpoint changes behavior or for group stage in future), the Elo updater would not know how to update ratings.
- **Files:** `SOTs/TRD.md` (lines 136–143), `SOTs/Backend_Schema.md` (lines 194–198)
- **Symptoms:** Unhandled `winner` value could cause a crash, incorrect Elo update, or silently skip the match.
- **Trigger:** API returns `"DRAW"` for a match (edge case).
- **Workaround:** Treat `"DRAW"` as both teams get `result = 0.5` in Elo calculation. Even though knockout has no draws, defensive coding is needed.

### API Mapping File Drift
- **Issue:** The `api_id_mapping.json` file maps external API match IDs to internal bracket `match_id`s (e.g., `"123456" → "R16_1"`). If the API changes its ID scheme, or if the mapping is incomplete, new matches will be silently ignored.
- **Files:** `SOTs/Backend_Schema.md` (lines 106–118), `SOTs/Implementation_plan.md` (lines 110–113)
- **Symptoms:** Real matches finish but the script never detects them because the API ID doesn't map to any bracket slot.
- **Trigger:** Missing mapping entry, API ID format change, tournament bracket mismatch.
- **Workaround:** Log a warning when an unmapped API ID is received, and provide a mechanism to manually map it at runtime (or fail with a clear error).

### ANSI Colors Broken on Some Windows Terminals
- **Issue:** Windows Command Prompt and older PowerShell versions do not support ANSI escape codes natively. The UI spec uses colored output (green/red/bold).
- **Files:** `SOTs/UI_UX_Design.md` (lines 86–103), `SOTs/Implementation_plan.md` (lines 176, 282)
- **Symptoms:** Garbled output with raw escape codes visible instead of colors. "←[32m▲ +0.6←[0m" appearing in console.
- **Trigger:** Running on Windows without `colorama` or with `--no-color` flag not set.
- **Workaround:** Use `colorama` library (import and `colorama.init()` for Windows). The `--no-color` fallback is planned but must strip ANSI codes, not just hide them.

---

## Security Considerations

### API Key Exposure via Environment Variable
- **Issue:** The API key is read from `FOOTBALL_API_KEY` environment variable. While better than hardcoding, this is still a risk: env vars can be leaked through error messages, child process environments, or accidental `print()` debugging.
- **Files:** `SOTs/Backend_Schema.md` (lines 354–363), `SOTs/Implementation_plan.md` (line 283)
- **Current mitigation:** Using `os.environ.get()` with a `ValueError` if missing. `.env` file planned to be in `.gitignore`.
- **Recommendations:**
  - Never log the API key value, even partially (e.g., `f"Key starts with {key[:4]}"` is risky).
  - Validate key format (length, prefix) before making API calls.
  - Ensure error responses from the API (which may echo the key) are not printed verbatim.

### No Input Validation on JSON Files
- **Issue:** JSON files (`teams.json`, `bracket.json`, `played.json`) are loaded with `json.load()` without schema validation. Corrupted or malicious modifications could cause crashes or unexpected behavior.
- **Files:** `SOTs/Backend_Schema.md` (lines 293–302)
- **Current mitigation:** Validation rules are documented but not enforced in code.
- **Recommendations:**
  - Validate loaded data against expected schema (keys, types, ranges).
  - Use `jsonschema` or simple assertion checks after loading.
  - Reject files with negative Elo ratings, missing required fields, or circular bracket references.

### No Rate Limiting Enforcement for API Calls
- **Issue:** The 60-second poll interval is a code constant, not enforced by the API client. If the interval is accidentally set to 5 seconds, the free tier (10 req/min) would be exceeded and the API key could be throttled or banned.
- **Files:** `SOTs/TRD.md` (lines 101–103)
- **Current mitigation:** Implicit — the constant defaults to 60 seconds.
- **Recommendations:**
  - Add a minimum poll interval check in code (e.g., raise error if POLL_INTERVAL < 30 seconds).
  - Track request timestamps and enforce rate limiting client-side.

---

## Performance Bottlenecks

### Monte Carlo Simulation — 50,000 Iterations in Pure Python
- **Problem:** The target is 50,000 tournament simulations in <5 seconds. Each simulation walks the bracket tree, looks up Elo ratings, and calls `random.random()`. Deep copies of the bracket dict per iteration would be catastrophic.
- **Files:** `SOTs/TRD.md` (lines 159–166), `SOTs/Implementation_plan.md` (lines 95–97, 281)
- **Cause:** Python's loop overhead, dict lookups, and the `random` module's PRNG calls. Each of 50,000 iterations runs ~15 match simulations = 750,000 `random.random()` calls.
- **Improvement path:**
  - Avoid deep copies of the bracket; use a recursive function that only copies winners upward.
  - Use `lru_cache` on `expected_score` calculations as suggested in implementation plan.
  - Use `numpy.random` for faster random number generation.
  - Reduce default simulation count to 20,000 if 5-second target cannot be met.
  - Profile aggressively during development.

### API Call Blocks Main Loop
- **Problem:** `requests.get()` is synchronous. A typical API response takes 1–2 seconds; timeouts could take 30+ seconds (default timeout). During this time, no polling, no simulation, no output updates.
- **Files:** `SOTs/Appflow.md` (lines 213–218), `SOTs/TRD.md` (lines 105–109)
- **Cause:** Single-threaded blocking architecture by design.
- **Improvement path:**
  - Set explicit `timeout` parameter on `requests.get()` (e.g., 10 seconds).
  - For MVP, accept the blocking. Track as a known limitation.

### Disk I/O on Every Match Detection
- **Problem:** Every detected match triggers two JSON writes: `save_teams()` and `save_played_matches()`. JSON serialization + disk write for ~5KB files is fast (<10ms), but on slow disks or high-frequency updates, this could compound.
- **Files:** `SOTs/Implementation_plan.md` (lines 157–158), `SOTs/Appflow.md` (lines 88–90)
- **Cause:** Design calls for saving after every match update to ensure crash recovery.
- **Improvement path:** The atomic write pattern (write → temp → rename) adds an extra file operation but is necessary for data integrity. Acceptable for MVP.

---

## Fragile Areas

### Team Name Normalization (API → Internal)
- **Files:** `SOTs/TRD.md` (lines 108–109, 300), `SOTs/Implementation_plan.md` (lines 108, 280)
- **Why fragile:** The API may return team names like "United States", "USA", "Korea Republic", "South Korea", "Côte d'Ivoire", "Ivory Coast" — all referring to the same team. The internal `teams.json` uses one canonical name. If a new variation appears, the mapping fails silently or with a warning, and the match is skipped.
- **Safe modification:** Maintain a comprehensive mapping dictionary in `fetcher.py` with test coverage for known variations. Log a WARNING with the unmapped name when skipping.
- **Test coverage gap:** No test verifies that all 32 expected team names appear in API responses with their canonical forms.

### API Match ID → Internal Match ID Mapping
- **Files:** `SOTs/Backend_Schema.md` (lines 106–118), `SOTs/TRD.md` (line 240)
- **Why fragile:** The `api_id_mapping.json` is a static file that must be manually pre-filled before the tournament. If the mapping is wrong, or if the API assigns different IDs for the same match (e.g., on re-request), the system won't detect matches.
- **Safe modification:** Add a startup validation that every bracket `match_id` has a corresponding API ID mapping. Log all unmapped API responses.
- **Test coverage gap:** No test validates that the mapping covers all expected matches for the tournament.

### Bracket Tree Recursive Traversal
- **Files:** `SOTs/Backend_Schema.md` (lines 43–79), `SOTs/Appflow.md` (lines 189–194)
- **Why fragile:** The bracket is a nested recursive structure. A bug in traversal (wrong key path, infinite loop from circular reference, off-by-one in round indexing) would produce wrong champions or crash. Hard to debug without visualization.
- **Safe modification:** Add bracket validation at startup: verify all `source_matches` exist, no circular dependencies, every match is reachable from the final.
- **Test coverage gap:** Only basic simulation tests planned. No test validates bracket tree integrity.

### Graceful Shutdown During Simulation
- **Files:** `SOTs/Appflow.md` (lines 269–286), `SOTs/Implementation_plan.md` (lines 144)
- **Why fragile:** `KeyboardInterrupt` could be raised in the middle of a Monte Carlo simulation (deep inside the loop). The signal handler needs to save state, but if the interrupt occurs during a JSON write, the file could be corrupted.
- **Safe modification:** Use a signal flag approach: set a `shutdown_flag = True` on interrupt, check it between simulation iterations, and save state when safe. Avoid catching `KeyboardInterrupt` inside atomic write sections.

---

## Scaling Limits

| Resource/System | Current Capacity | Limit | Scaling Path |
|---|---|---|---|
| API requests | 1 req/min | 10 req/min (free tier) | Upgrade to paid API tier or use multiple free keys |
| Simulation iterations | 50,000 | ~5 sec on reference hardware | Parallelize with `multiprocessing`, use PyPy, or switch to NumPy |
| Concurrent users | 1 (console app) | 1 (single process) | Web backend (Flask/FastAPI) + database for multi-user |
| Tournament scope | 1 knockout bracket | Fixed 16-team tree | Generic bracket builder supporting groups + any format |
| State file size | ~5 KB per file | JSON becomes slow at >100 MB | Migrate to SQLite or PostgreSQL |
| Memory | <500 MB | Depends on simulation data structures | Streaming aggregation instead of storing full result arrays |

---

## Dependencies at Risk

### Python `requests` Library
- **Risk:** The only external dependency for MVP. Low risk — well-maintained, ubiquitous.
- **Impact:** If `requests` has a breaking change, API calls break. Low probability.
- **Migration plan:** Use `urllib` from stdlib as fallback (no additional dependency).

### Football-Data.org Free API
- **Risk:** External service could change endpoint, data format, rate limits, or shut down the free tier entirely. This is a single point of failure.
- **Files:** `SOTs/TRD.md` (lines 96–103), `SOTs/PRD.md` (lines 187–188)
- **Impact:** The entire prediction pipeline stops working. No matches can be fetched.
- **Migration plan:**
  - Keep a mock data provider in the codebase that can substitute for development/demo.
  - Design the `fetcher.py` interface so alternative APIs (ESPN, OpenLigaDB, API-Football) can be swapped in without changing other modules.
  - Document fallback options in README.

### `colorama` (Optional Windows Support)
- **Risk:** Only needed for Windows ANSI color support. Lightweight dependency, but if unmaintained, colors break on Windows.
- **Impact:** Garbled ANSI output on Windows terminals.
- **Migration plan:** Strip ANSI codes with `--no-color` as fallback. The symbols (▲, ▼, ⚠) work without colorama.

---

## Missing Critical Features

### No Data Validation Layer
- **Problem:** There is no explicit data validation module. JSON files are loaded as-is, and invalid data is only caught downstream (if at all).
- **Files:** `SOTs/Backend_Schema.md` (lines 293–302)
- **Blocks:** Detecting corrupted JSON files before they cause incorrect probabilities or crashes. Team name mismatches are caught only as warnings, not errors.
- **Priority:** High — a startup validation check for all JSON files should be implemented before Phase 4.

### No Unit Test for State Persistence (Atomic Writes)
- **Problem:** The atomic write pattern (write to temp file, then rename) is mentioned but no test verifies that it handles crashes during write correctly.
- **Files:** `SOTs/Implementation_plan.md` (lines 75–76, 157–158)
- **Blocks:** Confidence in crash recovery. If the atomic write is buggy, the rename could fail, leaving no valid file.
- **Priority:** Medium — implement a test that kills the process mid-write and verifies the original file is intact.

### No Health Check or Self-Diagnostics
- **Problem:** The script has no way to report its own health status. If it stops detecting matches (e.g., API changed, mapping stale), the console continues printing heartbeats but never detects new matches.
- **Files:** `SOTs/Appflow.md` (lines 52–63)
- **Blocks:** Silent failure — user thinks the script is working but no data flows.
- **Priority:** Medium — add a "time since last match detection" counter that warns after N polls with no new matches.

---

## Test Coverage Gaps

| Untested Area | What's Not Tested | Files | Risk | Priority |
|---|---|---|---|---|
| **Bracket traversal** | Recursive match resolution, source_match chains, edge cases like fewer than 16 teams | `SOTs/simulator.py` (planned) | Wrong champions in simulation | High |
| **Team name mapping** | API returns unexpected name format → fallback behavior | `SOTs/fetcher.py` (planned) | Silent match skipping | High |
| **API failure cascade** | API fails → mock data used → but mock data has different format → crash | `SOTs/fetcher.py`, `SOTs/main.py` | Script crash on fallback | High |
| **JSON atomic writes** | Process killed mid-write, temp file rename fails, disk full | `SOTs/state.py` (planned) | Corrupted JSON, state loss | Medium |
| **Floating point tolerance** | Probability sum > 1.001 or < 0.999 | `SOTs/simulator.py` (planned) | Display artifacts | Low |
| **Ctrl+C during JSON write** | Shutdown signal during `json.dump()` or `os.rename()` | `SOTs/main.py` (planned) | Corrupted JSON file | Medium |
| **Elo edge cases** | Equal ratings (both 2000), extreme differences (2500 vs 1300), negative K-factor | `SOTs/elo.py` (planned) | Incorrect ratings update | Medium |
| **Empty API response** | API returns `{"matches": []}` or `{}` or null | `SOTs/fetcher.py` (planned) | Crash on unexpected structure | High |
| **Multiple new matches** | Two matches finish between polls (both detected within one poll cycle) | `SOTs/main.py` (planned) | Processing order issues | Medium |
| **Long-running stability** | Memory leak from dict accumulation, infinite loop from bracket bug | All modules | Script crash after hours | High |

---

*Concerns audit: 2026-06-13*
