# Domain Pitfalls: Live Football Tournament Prediction (Elo + Monte Carlo)

**Domain:** Live World Cup knockout predictor (Python CLI, Elo ratings, Monte Carlo simulation, Football-Data.org API)
**Researched:** 2026-06-13
**Overall confidence:** HIGH (synthesized from official Elo references, research papers, API provider guides, and project-specific CONCERNS.md)

---

## Critical Pitfalls

Mistakes that cause silently wrong predictions, data loss, or fundamental architectural rewrites.

### Pitfall 1: Raw Chess Elo Without Football-Specific Adaptations
**What goes wrong:** Using the raw Arpad Elo formula (designed for chess) on football matches without home advantage, goal margin, or match importance adjustments produces inaccurate ratings that converge slowly and misrepresent team strength.

**Why it happens:** The project currently defines `K_FACTOR` as a single constant and the Elo formula as a straightforward `R_new = R_old + K × (S - E)`. This omits three critical football adaptations every production Elo system uses:

1. **Home advantage bonus** — Neutral-site World Cup matches don't need this, but the system architecture should support it. Established systems (eloratings.net, ClubElo) add **65–100 Elo points** to the home team before expected score calculation. Without it, away teams are systematically underestimated and home teams overestimated.
2. **Goal margin multiplier** — A 4–0 win conveys more information than a 1–0 win. Goal-difference-adjusted systems multiply K by a function of goal difference (e.g., `ln(GD + 1)` or `sqrt(GD)`). Eloratings.net uses `G = 1` for 1-goal wins, `1.5` for 2-goal, `(11+N)/8` for 3+ goal wins. Without this, all wins are treated equally, slowing convergence to true strength.
3. **Match importance weighting** — World Cup knockout matches should use higher K-values than friendlies. Eloratings.net uses `K = 60` for World Cup finals vs `K = 20` for friendlies. FIFA's adaptation uses 8 weight tiers.

**Consequences:** Elo ratings converge slower and stay less accurate. A 1–0 lucky win counts the same as a 4–0 dominant performance. Predictions built on these ratings inherit the noise.

**Sources:**
- World Football Elo Ratings methodology (eloratings.net/about) — HIGH confidence
- Wikipedia: World Football Elo Ratings — HIGH confidence (cites eloratings.net)
- BetsPlug Elo guide (betsplug.com/learn/elo-rating-explained) — MEDIUM confidence
- StatWire Elo explained (thestatwire.com/guides/elo-ratings-explained) — MEDIUM confidence

**Prevention:**
- Implement goal margin multiplier from day one using eloratings.net's `G` function
- Keep K-factor configurable per-match-type (constant in `config.json`, but allow match-importance scaling)
- Add home advantage as a configurable constant even if set to 0 for neutral World Cup — the framework should exist
- See `SOTs/Backend_Schema.md` for where the raw formula is defined

**Detection:** Compare Elo-predicted probabilities against actual match outcomes. If prediction accuracy is below 60% on historical World Cup data, the missing adaptations are likely the cause.

**Phase to address:** Elo implementation phase (before simulation depends on accurate ratings).

---

### Pitfall 2: Monte Carlo Error Correlation — The "Independence Assumption" Trap
**What goes wrong:** Monte Carlo simulations assume match outcomes are independent. In a knockout tournament with a fixed bracket, outcomes are **correlated through shared teams and path dependencies**. Ignoring this produces overconfident probability estimates — the "sharpening" problem documented in the "Misadventures in Monte Carlo" paper.

**Why it happens:** Each MC iteration independently flips weighted coins for every match. But in reality:
- If Team A loses its Round of 16 match, every subsequent simulated path for Team A is moot — yet many naive simulations still "simulate" Team A's hypothetical deeper runs in other branches.
- When an upset happens in one simulation branch, it affects the entire rest of that branch's bracket (a Cinderella run changes opponent quality for all subsequent matches).
- Most critically: **the variance across simulation iterations is narrower than true prediction uncertainty**, making probabilities appear more certain than they are.

**Research backing:** The paper "Misadventures in Monte Carlo" (Journal of Sports Analytics, 2018) demonstrates that Monte Carlo playoff probabilities are "substantially inaccurate" and "systematically overconfident" when error correlation is ignored. The paper found that "playoff probabilities are substantially inaccurate" in NBA season forecasting and showed that incorporating error correlation eliminated the overconfidence.

**Consequences:**
- A team shown at 35% might have a true 25–45% range — users trust the point estimate too much
- Small probability teams (<2%) may actually have 0% or 5% — the MC flattens extreme outcomes
- The console display of "34.2% + 27.9% + 15.1% + 12.3% + 10.5%" looks precise but is deceptively confident
- Adding more iterations (10K → 50K → 1M) **does not fix this** — it only makes the wrong answer more precise

**Sources:**
- Demsyn-Jones, "Misadventures in Monte Carlo" (Journal of Sports Analytics, 2018) — HIGH confidence
- WorldCupPro article on simulation engine failures (worldcuppro.com) — MEDIUM confidence
- Phylourny paper (Springer, 2023) — exact calculation vs simulation tradeoffs — MEDIUM confidence

**Prevention — This is subtle and requires phased handling:**
- **Phase 1 (MVP):** Accept the overconfidence. Document it in the README and output. Add a note: "These probabilities are precise but not accurate — true uncertainty is wider."
- **Phase 2 (reliability):** Implement a "perturbation analysis" — slightly vary input Elo ratings (e.g., ±25 points) and re-run the full MC to produce a probability **range** instead of a single percentage. Display as "France 34% (range: 28–41%)".
- **Phase 3 (advanced):** Implement the exact tournament win probability calculation from the Phylourny paper. For a 16-team knockout bracket, the exact calculation is feasible and two orders of magnitude faster than simulation.

**Detection:** Run the MC with 10K iterations, record win probabilities. Then re-run with the same input data. If probabilities fluctuate by >2% for the top 3 teams, iterations are insufficient or the bracket traversal has issues.

**Phase to address:** Simulation phase. MVP accepts the flaw but must document it. Post-MVP addresses with perturbation analysis.

---

### Pitfall 3: Silent Match Skipping From API Mapping Drift
**What goes wrong:** A real match finishes, the API returns the result, but the script never detects it because the API match ID doesn't map to any bracket slot. The script continues printing heartbeats — looking healthy — but falls permanently behind reality.

**Why it happens:** The `api_id_mapping.json` file is a static mapping from Football-Data.org match IDs to internal bracket slots (e.g., `"123456" → "R16_1"`). This mapping must be manually pre-filled before the tournament. Several failure modes exist:

1. **API ID format changes** — The API changes its ID scheme mid-tournament (rare but documented in API changelogs)
2. **Incomplete mapping** — The developer forgot to map one or more matches
3. **Bracket mismatch** — The tournament bracket structure doesn't match the actual draw (e.g., wrong pairings for Round of 16)
4. **Re-scheduled matches** — If a match is postponed and assigned a new API ID, the old mapping points nowhere
5. **API re-request ID drift** — Endpoint returns different IDs for the same match on different requests

This is **the most dangerous pitfall** in this project because it causes an invisible failure. The script runs, prints heartbeats, but never updates predictions. A user watching the console sees "Polling..." and thinks everything works.

**Sources:**
- Sportmonks blog: "5 Common Mistakes Developers Make with Football APIs" — HIGH confidence
- Project-specific: CONCERNS.md lines 56–60 ("API Mapping File Drift") — HIGH confidence
- football-data.org docs (no explicit ID stability guarantee) — MEDIUM confidence

**Prevention:**
- **Startup validation:** On startup, verify that every bracket `match_id` has exactly one corresponding API ID mapping. If incomplete, print a WARNING table of unmapped slots and abort.
- **Fail-open logging:** When an unmapped API match response arrives, log: `⚠️ UNMAPPED MATCH: API ID {id}, {team_a} vs {team_b}`. Do not silently skip.
- **Manual override flag:** Support a `--force-map` CLI option that lets the user map an API ID to a bracket slot at runtime.
- **Idle detection alarm:** Add a "time since last match update" counter. If no new matches detected after N consecutive polls (e.g., 20 polls = 20 minutes), emit a WARNING suggesting mapping may be stale.

**Detection:** The script's health check should include: "Last match detected: X minutes ago." If this exceeds a threshold with active tournament matches, surface a warning.

**Phase to address:** API integration phase. The idle detection alarm can be a Phase 2 enhancement.

---

### Pitfall 4: API Rate Limit Exhaustion Causing Complete Pipeline Stall
**What goes wrong:** The script polls every 60 seconds. Football-Data.org free tier allows 10 requests/minute. One API call per poll cycle leaves 9 unused requests — but if the script makes additional requests (e.g., fetching match details, retries), it hits the 10/min ceiling. The API starts returning HTTP 429. Without proper handling, the script enters an error loop or serves stale data forever.

**Why it happens:**
- The 60-second interval is a **code constant, not enforced by the API client**. If it's accidentally set to 30 seconds, the free tier (10 req/min) would be exceeded and the key could be throttled.
- The project mentions `requests` library with no explicit rate limiter
- During World Cup, API traffic spikes could cause higher latency, triggering retries that burn through the rate limit faster
- The API doesn't have a guarantee that every plan sees the same rate limit; a free-tier plan may be stricter than documented

**Sources:**
- football-data.org docs: "Registered clients are allowed for 50 requests per minute by default" — but free tier specific limits may differ
- Project-specific: CONCERNS.md lines 91–98 ("No Rate Limiting Enforcement for API Calls") — HIGH confidence
- EntitySport guide on handling football API rate limits — MEDIUM confidence
- Sportmonks "Mistake 2" — HIGH confidence on rate limit handling patterns

**Prevention:**
- **Client-side rate limiter:** Implement a token bucket or sliding window that tracks actual request timestamps and refuses to send if under limit. Do not rely on a sleep interval alone.
- **Minimum poll interval guard:** Raise a `ConfigurationError` if `POLL_INTERVAL` < 30 seconds in code (not just documentation).
- **429 handler:** When the API returns 429, parse the `Retry-After` header (if present) or use exponential backoff starting at 60 seconds. Log the throttling event with a WARNING.
- **Cache healthy responses:** When a 429 is received, continue serving the last known-good data with a "stale" indicator rather than showing zeros or blanks.
- **Monitor rate limit headers:** Track `X-RequestCounter-*` or similar headers (football-data.org may not expose these; if not, track locally).

**Detection:** Log `X-RateLimit-Remaining` or local count before each request. Warn when below 3 remaining.

**Phase to address:** API integration phase. Must be in initial implementation, not deferred.

---

### Pitfall 5: Bracket Recursive Traversal Producing Wrong Champions Without Detection
**What goes wrong:** The Monte Carlo simulation walks a recursive bracket tree (Round of 16 → Quarterfinal → Semifinal → Final). A bug in traversal — wrong key path, circular reference, off-by-one in round indexing, or incorrect winner propagation — produces wrong champions. Because all iterations use the same buggy traversal, every simulated path is wrong, and the output looks perfectly consistent.

**Why it happens:** This is an **invisible correctness bug**. Unlike a crash, the simulation completes normally and produces numbers that look like probabilities. The bracket data structure is a nested dict:

```python
bracket = {
    "R16_1": {"home": "TeamA", "away": "TeamB", "source": None},
    "QF_1": {"home": None, "away": None, "source": ["R16_1", "R16_2"]},
    # ...
}
```

Common bug patterns:
- **Self-referencing source:** A match's `source` points to itself → infinite recursion
- **Orphan match:** A match is not reachable from the final → simulation skips it silently
- **Wrong winner propagation:** The winner of R16_1 feeds into QF_1's `away` instead of `home` → correct team, wrong bracket position, downstream matches simulate wrong opponents
- **Double-winner bug:** The same team advances through two different bracket paths (e.g., both R16 winners reference the same team) → a team can win by beating itself

**Sources:**
- Project-specific: CONCERNS.md lines 144–148 ("Bracket Tree Recursive Traversal") — HIGH confidence
- General software: recursive data structure bugs are a well-known class of subtle failures — MEDIUM confidence

**Prevention:**
- **Startup bracket validation:** On every startup, run a validation pass:
  - Every match is reachable from the final via `source` chains
  - No circular `source` references (use Floyd's or visited-set detection)
  - Every `source` reference points to an existing match_id
  - No structural cycles in the bracket graph
  - The bracket tree depth equals the expected number of rounds (log2N for knockout)
- **Unit test with known bracket:** Simulate a deterministic bracket (R16 pairings with forced 100% win odds for one half) and verify the champion is always the expected team. Run this as a CI gate.
- **Smoke test:** Run the simulation with all teams at equal Elo (1500). Each team should have exactly `1/16` = 6.25% win probability (within MC tolerance). Deviations indicate bracket traversal bugs.
- **Visualization for debugging:** Log or dump a single simulation path (chosen randomly) showing the full winner propagation chain. A human can spot structural issues.

**Detection:** The equal-Elo smoke test is the best detection mechanism. If the simulation is correct, equal ratings produce equal probabilities. Any deviation >1% points to a bracket bug.

**Phase to address:** Simulation implementation phase. Must include validation tests.

---

## Moderate Pitfalls

### Pitfall 6: JSON File Corruption on Crash During Write
**What goes wrong:** The process is killed (Ctrl+C, power loss, OOM killer) while writing `teams.json`, `bracket.json`, or `played.json`. The file is left half-written, truncated, or containing invalid JSON. On restart, `json.load()` throws an exception or loads partial data. Elo ratings reset to defaults, played matches are lost.

**Why it happens:** The project uses standard `json.dump()` → file write. A write to disk is not atomic — the OS buffers data, and a crash mid-write leaves inconsistent state. The project acknowledges atomic writes (`write → temp → rename`) in CONCERNS.md but this pattern must be implemented correctly.

**Consequences:**
- **State loss:** All Elo ratings revert to defaults. All "played" match history is lost. The script effectively forgets the entire tournament progress.
- **Corrupted data detection:** If partial JSON is valid (e.g., 3 out of 16 matches written), the system silently loads incomplete data and produces wrong predictions.
- **Time-to-recovery:** Without crash recovery, a restart mid-tournament requires manually reconstructing state from memory or logs.

**Sources:**
- Project-specific: CONCERNS.md lines 201–205 ("No Unit Test for State Persistence (Atomic Writes)") — HIGH confidence
- CONCERNS.md lines 150–153 ("Graceful Shutdown During Simulation") — HIGH confidence
- General software: atomic write pattern is well-documented for JSON persistence in Python — MEDIUM confidence

**Prevention:**
1. **Atomic write pattern (non-negotiable for MVP):**
   ```python
   import os, tempfile, json
   def atomic_write(path, data):
       tmp = path + ".tmp"
       with open(tmp, "w") as f:
           json.dump(data, f)
           f.flush()
           os.fsync(f.fileno())
       os.replace(tmp, path)  # atomic on POSIX, near-atomic on Windows
   ```
2. **Schema validation on load:** After `json.load()`, validate all expected keys, types, and value ranges exist. Reject and log files that don't match.
3. **Crash recovery checkpoint:** Maintain a backup (e.g., `teams.json.bak`) from the last successful write. If the primary file fails validation, attempt to load the backup.
4. **Signal-safe shutdown:** Use a `shutdown_flag` approach — catch SIGINT, set a flag, check it between MC iterations and before writes. Do not catch KeyboardInterrupt inside atomic write sections.

**Detection:** Unit test that kills the process mid-write and verifies the original file remains intact (or backup recovers).

**Phase to address:** State persistence implementation phase. Must be in initial code, not deferred.

---

### Pitfall 7: Team Name Normalization Failure (API ↔ Canonical)
**What goes wrong:** The API returns "United States", but the internal `teams.json` uses "USA". Or "Korea Republic" vs "South Korea". Or "Côte d'Ivoire" vs "Ivory Coast". The mapping fails, the match is silently skipped, and the prediction pipeline falls behind reality.

**Why it happens:** Sports APIs are notorious for inconsistent team naming. The same team may appear as different strings across endpoints (fixtures endpoint vs standings endpoint), across tournaments (World Cup vs qualifying), or even across seasons. The mapping dictionary in `fetcher.py` must cover all variations.

**How it manifests:**
- **Silent skip:** The API returns a match with `homeTeam: "USA"`, but the internal bracket expects "United States". The mapping dict returns `None`. The match is logged as "unrecognized team" and skipped.
- **Partial update:** The match is detected but only one team's name matches. The system updates Elo for one team and skips the other, causing asymmetric rating updates.
- **Delayed detection:** The user manually adds "USA" to the mapping. By then, 3 match days have passed, and the predictions were wrong for days.

**Sources:**
- Project-specific: CONCERNS.md lines 132–136 ("Team Name Normalization") — HIGH confidence
- Sportmonks blog: "Mistake 4" — API data may have unexpected field values — MEDIUM confidence

**Prevention:**
1. **Comprehensive mapping dictionary with test coverage:** Pre-populate with all known variations for all 32 World Cup teams before the tournament starts. Source from Football-Data.org's own team names and Wikipedia's country name variations.
2. **Fuzzy fallback:** If exact match fails, attempt case-insensitive match, then substring match, then Levenshtein distance > 0.8. Log the guessed mapping for user confirmation.
3. **Fail-open with user input:** On startup, warn about any unmapped API team names. In a CLI application, prompt the user to map them interactively.
4. **Log every team name seen vs expected:** On each poll cycle, log the API's team names alongside internal names for easy debugging.

**Detection:** Startup validation that all 32 expected team names have at least one API name mapping.

**Phase to address:** API fetcher implementation phase. Must have comprehensive test data.

---

### Pitfall 8: Probability Sum Drift From Floating Point Accumulation (Cosmetic but Confusing)
**What goes wrong:** Monte Carlo simulation counts wins per team and divides by `n_simulations`. After 50,000 iterations, the sum of all probabilities equals 0.99997 or 1.00003 due to floating-point arithmetic. Console output shows "100.0001%" causing confusion and eroding trust.

**Why it happens:** This is expected behavior for large Monte Carlo simulations. The win counts are exact integers, but division produces floating-point fractions that don't sum to 1.0.

**Prevention:**
- Normalize probabilities before display: `pct[i] = 100 * wins[i] / sum(wins)`
- Document the normalization and expected tolerance (±0.01%)
- Log raw (un-normalized) win counts in verbose mode for debugging

**Detection:** Standard test: after each simulation, verify sum of probabilities is within ±0.1% of 100% after normalization.

**Phase to address:** Display/output phase. Minor fix, but should be in initial implementation to avoid confusing early users.

---

### Pitfall 9: No Probability History — Delta Shown Is Only Last-Run Difference
**What goes wrong:** The console shows "△: ▲ +2.3%" but only between the current and previous simulation run. If the terminal scrolls past or the script restarts, all history of how probabilities evolved is lost. Cannot answer questions like "What was France's probability before the quarterfinal?"

**Why it happens:** Previous probabilities are stored only in a local variable in the main loop. Not persisted to disk. This is acknowledged in CONCERNS.md.

**Consequences:**
- No post-tournament analysis capability
- Cannot detect trends (e.g., "Team X's probability has been dropping for 3 match days")
- Debugging is impossible after terminal closes
- Planned v1.2 web dashboard would have no historical data

**Prevention:**
- Append each simulation output to a `history.json` file with timestamps: `[{"timestamp": "...", "probabilities": {...}}, ...]`
- Keep only the last N entries (configurable) to prevent unbounded file growth
- On startup, load the most recent entry as the "previous" state for delta calculation

**Phase to address:** Can be deferred to a reliability-focused phase after MVP. But the data model should anticipate it: keep probability snapshots in memory from the start.

---

### Pitfall 10: Single-Threaded Architecture Blocks Match Detection During Simulation
**What goes wrong:** During the ~5 seconds that Monte Carlo runs (50,000 iterations), the API polling loop is blocked. If a match ends during this window, detection is delayed by up to 5 seconds. Combined with the 60-second poll interval, some matches may not be detected for 65+ seconds.

**Why it happens:** The MVP design is explicitly single-threaded. API calls and simulation run sequentially in the main loop. CONCERNS.md documents this but accepts it as an MVP limitation.

**Consequences:**
- During rapid-fire tournament endings (e.g., two matches finishing within 60 seconds of each other), the second match's detection could be delayed by an additional simulation cycle
- The 120-second latency target (if defined as an NFR) may be violated during peak periods

**Prevention:**
- **MVP:** Accept the limitation. Document that predictions update within ~65 seconds of a match ending.
- **Phase 2:** Move MC simulation to a background thread (`threading.Thread`). The main loop polls while simulation runs in the background. Use a lock to swap simulation results atomically when complete.
- **Note:** Python's GIL is acceptable here — the simulation is CPU-bound and the polling is I/O-bound, so threading works well.

**Phase to address:** Document for MVP. Implement threading as a post-MVP reliability enhancement.

---

### Pitfall 11: Using `random.random()` Instead of `numpy.random` or `secrets` for Simulation
**What goes wrong:** 50,000 iterations × 15 matches = 750,000 calls to `random.random()` per simulation cycle. Python's Mersenne Twister (`random.random()`) is slow in pure Python and its period (2^19937-1) is overkill for this use case. The simulation may take 5–10 seconds instead of <3 seconds.

**Why it happens:** `random` is the intuitive choice. Developers don't realize that `numpy.random` is 10–50x faster for bulk random number generation because it generates arrays of random numbers in C.

**Sources:**
- CONCERNS.md lines 103–112 ("Monte Carlo Simulation — 50,000 Iterations in Pure Python") — HIGH confidence

**Prevention:**
- Profile early: if simulation takes >5 seconds, switch to `numpy.random` for generating the random values used in match outcome determination
- Consider pre-generating an array of `n_simulations × n_matches` random values before the simulation loop, then iterating through the pre-generated values (avoids per-call overhead)
- **Caveat:** Adding NumPy as a dependency is a tradeoff — the project aims for minimal dependencies. Evaluate performance against the 5-second target before committing.

**Phase to address:** Performance optimization phase after MVP is working.

---

### Pitfall 12: Ignoring Penalty Shootout Probability Distribution
**What goes wrong:** In the MC simulation, each knockout match that would be a draw in regular time goes to extra time and penalties. The simplest approach treats penalty outcomes as 50/50. But penalty win rates correlate with squad quality, goalkeeper quality, and historical penalty performance — not directly with Elo rating.

**Why it happens:** The project scope explicitly limits simulation to "Elo determines win probability." But Elo doesn't model penalty shootouts well — a team's Elo reflects overall match strength, not penalty-taking ability.

**Consequences:**
- Close matches (which Elo says are ~50/50) are correctly modeled at 50/50
- But the simulation underestimates the variance: in reality, weaker teams have better penalty odds than their Elo suggests, because penalties compress skill differences

**Prevention:**
- **MVP:** Accept the simplification. Document that penalty shootouts are modeled as Elo-predicted odds.
- **Phase 2:** Add a separate "penalty rating" (e.g., based on historical penalty shootout records, or adjust Elo toward 50/50 for penalty outcomes). Use a weighted blend: `P(win on pens) = 0.7 × Elo_prob + 0.3 × 0.5`.

**Phase to address:** Simulation implementation (MVP with simplification). Enhancement post-MVP.

---

### Pitfall 13: No Graceful Degradation When API Is Down
**What goes wrong:** The Football-Data.org API goes down during a World Cup match (due to traffic spikes, maintenance, or infrastructure issues). The script receives a 500 or timeout. Without graceful degradation, the script either crashes completely or enters a tight error loop that burns rate limits.

**Why it happens:** The project currently has planned retry logic but no fallback data mechanism. If the API is down for minutes or hours, the script has nothing to display.

**Sources:**
- Project-specific: CONCERNS.md lines 177–184 ("Football-Data.org Free API" dependency risk) — HIGH confidence

**Prevention:**
1. **Mock data provider:** Maintain a mock fetcher that returns pre-recorded match results for the current tournament. Switchable via `--mock-data` flag or automatically on API failure.
2. **Stale data serving:** When API is unavailable, continue serving last-known probabilities with a prominent "⚠️ Stale data" indicator and timestamp.
3. **Circuit breaker:** After 3 consecutive API failures, switch to mock data mode and alert the user. Re-check API availability at increasing intervals.
4. **Offline mode:** The core prediction pipeline (Elo + MC) works from JSON state alone. The user should be able to run `--offline` to continue from last-saved state without any API calls.

**Phase to address:** API integration phase. Mock data provider should exist from day one for development.

---

## Minor Pitfalls

### Pitfall 14: ANSI Color Codes Broken on Windows Terminals
**What goes wrong:** Colored output (green for positive deltas, red for negative) displays raw escape codes like `←[32m▲ +0.6←[0m` on Windows Command Prompt or older PowerShell.

**Prevention:**
- Use `colorama` library with `colorama.init()` on Windows startup
- Provide `--no-color` flag that strips all ANSI codes
- Test on Windows Terminal, PowerShell 5.x, and Command Prompt

**Phase to address:** CLI/output implementation phase.

---

### Pitfall 15: API Key Leaked Through Logging or Error Messages
**What goes wrong:** During debugging, a developer adds `print(response.text)` or logs the full API response, which includes the auth header. The API key appears in console output, potentially in screenshots or shared logs.

**Prevention:**
- Never log the full request or response headers
- Validate API key format (length, expected prefix) on startup and fail fast with a generic error
- Sanitize any logged HTTP responses to redact auth-related fields

**Phase to address:** Security hardening phase (or during API integration if flagged).

---

### Pitfall 16: Poll Interval Drift Over Long Runs
**What goes wrong:** Using `time.sleep(60)` in a loop means the actual poll interval is `60 + time_to_execute`. Over a 24-hour run (1,440 cycles), this could drift by 30+ minutes, causing the script to desync from real match timing.

**Prevention:**
- Use `time.monotonic()` to track elapsed time and sleep only the remaining delta: `sleep_time = max(0, POLL_INTERVAL - (time.monotonic() - start_time))`
- Log effective poll interval on each cycle for monitoring

**Phase to address:** Main loop implementation phase. Easy fix, include from the start.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|-------------|---------------|----------|------------|
| Elo Implementation | Raw chess Elo without football adaptations (Pitfall 1) | Critical | Add goal margin + home advantage from day one |
| Elo Implementation | Win/draw/loss encoding wrong (0/0.5/1) for knockout penalties | High | Ensure penalty wins map to `S=1` for winner, `S=0` for loser (not 0.5/0.5) |
| MC Simulation | Error correlation overconfidence (Pitfall 2) | Critical | Document for MVP; add perturbation analysis post-MVP |
| MC Simulation | Bracket traversal bug (Pitfall 5) | Critical | Startup validation + equal-Elo smoke test |
| MC Simulation | Floating point sum drift (Pitfall 8) | Low | Normalize before display |
| API Integration | Silent match skipping from mapping drift (Pitfall 3) | Critical | Startup validation + idle alarm |
| API Integration | Rate limit exhaustion (Pitfall 4) | Critical | Client-side rate limiter + 429 handling |
| API Integration | Team name mismatch (Pitfall 7) | High | Comprehensive name mapping + fuzzy fallback |
| API Integration | No graceful degradation (Pitfall 13) | Medium | Mock data provider + stale data mode |
| State Persistence | JSON corruption on crash (Pitfall 6) | Critical | Atomic writes + schema validation |
| State Persistence | No probability history (Pitfall 9) | Medium | Append to history.json |
| Main Loop | Poll interval drift (Pitfall 16) | Low | Use time.monotonic() delta sleep |
| Main Loop | Single-threaded blocking (Pitfall 10) | Medium | Thread simulation post-MVP |
| CLI/Output | ANSI on Windows (Pitfall 14) | Low | colorama + --no-color flag |
| CLI/Output | API key in logs (Pitfall 15) | Medium | Sanitize logged responses |

---

## Research Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Elo pitfalls | **HIGH** | Verified against multiple football Elo implementations (eloratings.net, ClubElo, Wikipedia, academic comparisons) |
| MC simulation overconfidence | **HIGH** | Directly from peer-reviewed "Misadventures in Monte Carlo" paper (JSA 2018) |
| API integration pitfalls | **HIGH** | Sportmonks guide (2025) + project-specific CONCERNS.md + football-data.org docs |
| Bracket traversal bugs | **MEDIUM** | General software correctness issue; specific to this project's recursive structure |
| JSON corruption | **HIGH** | Well-understood pattern; CONCERNS.md confirms the risk |
| Team name mismatch | **HIGH** | CONCERNS.md + known issue across sports APIs |
| Penalty modeling | **MEDIUM** | Theoretical; specific penalty Elo research is limited for football |
| Window ANSI | **HIGH** | Well-documented Python/Windows issue; colorama is the standard fix |

## Gaps to Address

- **Elo K-factor optimization research:** What specific K-factor works best for World Cup knockout matches? Eloratings.net uses 60 but this deserves validation with historical data. Flag for phase-specific research during Elo implementation.
- **Penalty shootout Elo correlation:** Is there published research on how Elo correlates with penalty shootout win rates? If not, a pragmatic 50/50 assumption (or 0.7/0.3 blend) may be the best available option. Flag for validation.
- **Exact tournament probability calculation:** The Phylourny paper (Springer 2023) offers an exact calculation for 16-team brackets that's 100× faster than MC. Evaluate whether to implement this instead of (or alongside) MC simulation. Flag for architecture decision before simulation phase.
- **Football-Data.org free tier reliability:** How has the free tier performed during peak World Cup periods historically? This affects whether the fallback strategy needs to be aggressive (auto-switch to mock data) or lenient (wait for recovery). Flag for pre-tournament testing.

---

*Sources consulted: eloratings.net, Wikipedia (World Football Elo Ratings), "Misadventures in Monte Carlo" (Demsyn-Jones, JSA 2018), Sportmonks blog (2025), football-data.org docs, BetsPlug Elo guide, StatsUltra Elo Python guide, StatWire Elo guide, WorldCupPro simulation article, Phylourny paper (Springer 2023), project CONCERNS.md.*
