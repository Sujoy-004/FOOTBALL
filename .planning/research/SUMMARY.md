# Project Research Summary

**Project:** World Cup Dynamic Prediction
**Domain:** Live Football Tournament Prediction (CLI · Elo · Monte Carlo)
**Researched:** 2026-06-13
**Confidence:** HIGH

---

## Executive Summary

This project is a **live, self-updating tournament predictor** that polls a football API, updates team Elo ratings after every real result, runs thousands of Monte Carlo simulations of the remaining knockout bracket, and prints updated championship probabilities to the terminal. The ecosystem of similar tools (FiveThirtyEight/Silver Bulletin PELE, ESPN SPI, open-source GitHub predictors) converges on a common pipeline: **team ratings → match probability model → Monte Carlo simulation → probability aggregation**. For a CLI tool, the correct architecture is a **synchronous poll-detect-update-simulate-output loop** with modular pure-function components and JSON file persistence.

The research recommends a tight Python stack: `requests` for API polling (async provides zero benefit at 10 req/min), custom Elo with football-specific adaptations (goal margin multiplier, match importance scaling), a Monte Carlo simulator that starts iterative and optimizes with `numpy` if profiling warrants it, and `rich` for terminal output. **`rich` must be Phase 1, not deferred** — raw `print()` produces unreadable output for 16+ team probability tables with deltas.

**Key risks** center on silently wrong predictions: (1) using raw chess Elo without football adaptations produces inaccurate ratings, (2) Monte Carlo error correlation yields overconfident point estimates, (3) API mapping drift causes missed matches without visible errors, (4) rate limit exhaustion stalls the pipeline. These must be mitigated with football-specific Elo formulas, startup bracket validation, client-side rate limiters, and documented confidence caveats. The recommended roadmap splits into **5 phases** — Core Engine → Live Loop → Rich Output → Analytics → Power Features — each building on verifiable, testable foundations.

---

## Key Findings

### Recommended Stack

The research (STACK.md, HIGH confidence across all recommendations) prescribes a minimal but deliberate dependency set:

**Core dependencies (Phase 1):**
- **`requests` ~= 2.32.x** — HTTP client for Football-Data.org v4 API. Sync-only is correct: 10 req/min means zero benefit from async I/O. Official API docs use `requests` in their Python examples.
- **`numpy` ~= 2.4.x** — Vectorized Monte Carlo engine for ≥50K sims. Generates all random numbers as a single contiguous C array — 0.1–0.3s vs 8–15s for pure Python loops. **Important nuance:** For a 16-team knockout (15 matches × 50K sims = 750K matches), iterative Python takes ~2–5s from ecosystem data. Recommendation: start with iterative Python, profile, add numpy if >5s threshold exceeded.
- **`rich` ~= 15.0.x** — Console output (formatted tables, colors, progress bars, live updates). De facto standard for Python CLI formatting (56.5K GitHub stars). **Must be Phase 1** — raw `print()` for 16-team probability tables with delta indicators is unacceptably unreadable.
- **`pydantic` ~= 2.10 + `pydantic-settings` ~= 2.11** — API response validation (nullable fields, nested objects, type coercion) and typed env-var configuration. Prevents "2 AM crash because API returned `null` for score" bugs. Rust-backed, 5–50× faster than v1.
- **`pytest` ~= 8.x + `hypothesis` ~= 6.120** — Testing. Hypothesis for property-based Elo invariant testing (total rating change = 0, expected scores sum to 1.0).

**Custom Elo (NOT a library):** ~15 lines of pure math, zero dependencies. Use World Football Elo Ratings modifications (goal difference multiplier, K=60 for World Cup knockouts). Avoid abandoned or wrong-domain libraries (`openskill`, `elo`, `player_ratings`).

**Anti-dependencies (confirmed excluded):** Flask/FastAPI (out of scope), SQLAlchemy (JSON persistence), pandas (overkill), tqdm (Rich replaces it), colorama (Rich handles Windows natively), matplotlib/plotly (console-only MVP).

### Expected Features

Research from FEATURES.md (HIGH confidence, verified against FiveThirtyEight, ESPN/SPI, and 6+ open-source GitHub predictors):

**Must have (table stakes) — Phase 1:**
1. Championship probability (%) per team — headline output of MC aggregation
2. Round-by-round advancement probabilities (R16 → QF → SF → Final → Win)
3. Live match result ingestion via API polling
4. Elo rating updates after each real match
5. Monte Carlo simulation engine (50K+ iterations)
6. Team rating display (current Elo + probability)
7. Match-level win probability (Elo → expected score)
8. Predictions update automatically on new results — **Phase 2**
9. Error-resilient operation (retry + cached fallback) — **Phase 2**
10. Console-formatted output (tables, percentages) — **Phase 1/3**

**Should have (differentiators) — Phases 3–5:**
1. Probability delta tracking ("▼ 3.2% since last match") — the strongest differentiator
2. Timeline/probability history with timestamps
3. Elo change annotations in match log ("Brazil +15.2 (2074 → 2089.2)")
4. Most likely full bracket (modal path across MC runs)
5. Most likely scoreline per match (Poisson from Elo expected goals) — **deferred**
6. Dark horse / surprise team detection
7. Configurable everything without code changes
8. Exportable JSON snapshot
9. Backtest accuracy on command — **deferred**
10. What-if scenario mode
11. Bookmaker odds comparison — **deferred** (requires paid API)
12. Compact terminal dashboard view

**Defer (v2+):**
- Poisson scoreline model (adds Dixon-Coles complexity; Elo W/D/L is sufficient for MVP)
- Backtest historical mode (needs separate data ingestion + evaluation pipeline)
- Group stage simulation (significant bracket logic; 12 groups → R32 for 2026 format)
- Bookmaker odds comparison (requires paid API)
- ML models (XGBoost, neural nets) — Elo is transparent and sufficient

### Architecture Approach

The ecosystem (ARCHITECTURE.md, HIGH confidence from 10+ GitHub projects and academic sources) converges on a **pipelines-with-aggregation architecture** organized around a synchronous Poll-Detect-Update-Simulate-Output loop. Every credible predictor decomposes into five layers with pure-function leaf modules:

**Major components:**
1. **State Manager** (`state.py`) — Load/save all JSON files with atomic writes (`write → .tmp → os.replace`). Loads: `teams.json` (Elo ratings), `bracket.json` (tournament structure), `played.json` (completed matches).
2. **Elo Engine** (`elo.py`) — Pure-function rating updates. `update_ratings(team_a, team_b, winner, elos_dict) → new_elos_dict`. No side effects, no dependencies.
3. **Fetcher** (`fetcher.py`) — HTTP GET via `requests`; parse, filter by `status == "FINISHED"`, match via API ID mapping, team name normalization. Retry with exponential backoff.
4. **Simulator** (`simulator.py`) — Bracket traversal + Monte Carlo aggregation. Iterative Python for MVP (2–5s at 50K sims). Bracket as JSON data file, not hardcoded code.
5. **Output Formatter** (`output.py`) — Rich-powered tables with delta computation, ANSI colors, timestamps.

**Key patterns:**
- **Bracket as data, not code:** Load `data/bracket.json` at startup. No hardcoded matchups.
- **Pure-function modules with zero circular dependencies:** `main.py` → all others. Leaf modules have no inter-dependencies.
- **Iterative MC simulation for MVP:** Flat ordered list bracket structure for O(n) traversal. `deepcopy` avoided in inner loop.
- **Atomic writes for all persistence:** Prevents JSON corruption on crash.

### Critical Pitfalls

**Top 5 from PITFALLS.md (HIGH confidence, verified against eloratings.net, academic papers, project CONCERNS.md):**

1. **Raw Chess Elo Without Football Adaptations** — Using `R_new = R_old + K × (S - E)` without goal margin multiplier or match importance scaling produces inaccurate ratings that converge slowly. *Prevention:* Implement `K × G(goal_diff)` from eloratings.net's formula and match-importance scaling from day one.

2. **Monte Carlo Error Correlation (Overconfidence Trap)** — MC assumes independent match outcomes, but bracket paths are correlated. Probability point estimates look precise but are systematically overconfident. *Prevention:* Document the caveat for MVP; implement perturbation analysis (vary Elo ±25, re-run MC → probability **range**) post-MVP.

3. **Silent Match Skipping from API Mapping Drift** — An unmapped API match ID causes the script to run normally but never detect results. Most dangerous pitfall because failure is invisible. *Prevention:* Startup validation that every `bracket.match_id` has a corresponding API mapping; "idle detection alarm" if no matches detected after N polls; `--force-map` CLI override.

4. **API Rate Limit Exhaustion** — Free tier: 10 req/min. A 60s poll interval leaves 9 unused but retries can burn through. Accidental 30s interval would exceed limit. *Prevention:* Client-side token bucket rate limiter (not just sleep), minimum poll interval guard (≥30s, enforced in code), 429 handler with `Retry-After` parsing, stale-data fallback.

5. **Bracket Recursive Traversal Bugs** — Self-referencing sources, orphan matches, wrong winner propagation — all produce consistent but wrong simulation output. *Prevention:* Startup bracket validation (reachability, circular ref detection, depth verification), equal-Elo smoke test (each team should get ~1/16 probability), deterministic unit test with forced win odds.

---

## Implications for Roadmap

The research prescribes a clear build order based on dependency chains, risk profiles, and ecosystem patterns. The recommended 5-phase structure:

### Phase 1: Core Engine (State + Elo + Simulator + Basic Output)

**Rationale:** This is the mathematical and data foundation. Every other component depends on correct Elo ratings and a working simulator. Build these first so they can be tested independently with mock data — before any API dependency.

**Delivers:** A prediction engine that can load a bracket, run 50K Monte Carlo simulations from configurable Elo ratings, and print champion probabilities. Works entirely offline.

**Addresses FEATURES.md:** Table stakes #1–7 (championship probability, round-by-round advancement, Elo updates, MC simulation, team display, match win probability, basic console output)

**Uses from STACK.md:** pydantic + pydantic-settings (typed config), custom Elo (no library), `rich` for basic formatted output (tables already needed here)

**Implements from ARCHITECTURE.md:** State Manager, Elo Engine, Simulator (iterative Python), basic Output Formatter; bracket JSON schema definition

**Avoids from PITFALLS.md:**
- Pitfall 1 (raw chess Elo) — implement football adaptations from day one
- Pitfall 5 (bracket traversal bugs) — startup validation + equal-Elo smoke test
- Pitfall 6 (JSON corruption) — atomic writes from day one
- Pitfall 8 (floating point drift) — normalize before display

**Research flags:** Needs verification of Elo K-factor for World Cup knockouts (eloratings.net uses 60). Evaluate `football-api` PyPI wrapper vs raw `requests` for future API work.

---

### Phase 2: Live Loop (API Integration + Auto-Simulation)

**Rationale:** Phase 1 needs real data to be useful. API integration adds the live-updating behavior that defines the product. This phase makes the predictor self-updating.

**Delivers:** Continuous polling loop that detects new match results, updates Elo, re-runs simulation, and outputs updated probabilities — running autonomously with error handling.

**Addresses FEATURES.md:** Table stakes #8–10 (automatic updates, error resilience, console output polish)

**Uses from STACK.md:** `requests` (HTTP client), rate limiter logic

**Implements from ARCHITECTURE.md:** Fetcher (API polling, response parsing, ID mapping, team name normalization), Main Loop orchestration

**Avoids from PITFALLS.md:**
- Pitfall 3 (silent match skipping) — startup mapping validation, idle detection alarm
- Pitfall 4 (rate limit exhaustion) — token bucket rate limiter, 429 handler, stale-data fallback
- Pitfall 7 (team name normalization) — comprehensive mapping dictionary, fuzzy fallback
- Pitfall 13 (no graceful degradation) — mock data provider, offline mode, circuit breaker
- Pitfall 16 (poll interval drift) — `time.monotonic()` delta sleep

**Research flags:** Football-Data.org free tier reliability during peak World Cup traffic (determines aggressiveness of fallback strategy). API ID stability guarantees (or lack thereof). This phase likely needs deeper research during planning.

---

### Phase 3: Rich Output + Probability History

**Rationale:** With a working live loop, the raw output needs polish. This phase transforms readable-but-basic console output into the differentiated, beauty-grade terminal experience that defines the product.

**Delivers:** Rich-formatted tables with ANSI colors, live-updating display, progress bars during simulation, probability delta tracking (▲/▼ arrows with percentages), Elo change annotations, timestamped logs, probability history persistence.

**Addresses FEATURES.md:** Differentiators #1 (delta tracking), #3 (Elo change annotations), #7 (configurable display)

**Uses from STACK.md:** `rich` full feature set (Table, Live, Progress, colors)

**Implements from ARCHITECTURE.md:** Full Output Layer with delta computation, history persistence

**Avoids from PITFALLS.md:**
- Pitfall 9 (no probability history) — append history.json with timestamps
- Pitfall 14 (ANSI on Windows) — Rich handles this natively v13+, add `--no-color` flag
- Pitfall 15 (API key in logs) — sanitize logged responses
- Pitfall 12 (penalty modeling) — document simplification; add optional penalty adjustment

---

### Phase 4: Analytics + Power User Features

**Rationale:** With polished output, add the features that differentiate this tool from every other predictor — things web dashboards don't do in CLI form.

**Delivers:** Most likely full bracket output, dark horse / surprise team detection, compact live dashboard view (like `top` for predictions), JSON export command, fully configurable parameters without code changes.

**Addresses FEATURES.md:** Differentiators #4 (most likely bracket), #6 (dark horse detection), #8 (JSON export), #12 (dashboard view)

**Research flags:** Modal bracket tracking across MC runs needs algorithmic design. Dark horse threshold selection needs historical validation.

---

### Phase 5: Optimization + Power Modes

**Rationale:** Phase 4 covers all core features. Phase 5 addresses performance, advanced interaction modes, and historical analysis — features that benefit from a stable base.

**Delivers:** NumPy-accelerated simulation (if profiling shows need), what-if scenario mode (`--set-result Brazil 2-1 Serbia`), backtest mode against 2022 World Cup, timeline/probability history visualization (ASCII sparklines or JSON export).

**Addresses FEATURES.md:** Differentiators #2 (timeline/history), #9 (backtest), #10 (what-if mode)

**Avoids from PITFALLS.md:**
- Pitfall 2 (MC overconfidence) — perturbation analysis for probability ranges
- Pitfall 11 (slow `random.random()`) — numpy optimization if needed
- Pitfall 10 (blocking during simulation) — threaded simulation if needed

---

### Post-MVP (Future Milestones)

- **Poisson scoreline model** — Dixon-Coles bivariate Poisson; adds scoreline distributions
- **Group stage simulation** — 12 groups → R32; adds group standings, tiebreakers, third-place qualifiers
- **Bookmaker odds comparison** — requires paid odds API subscription
- **Machine learning models** — XGBoost vs Elo comparison track

---

### Phase Ordering Rationale

- **Phase 1 before Phase 2:** The simulator and Elo engine must be correct before adding API data. Building with mock data first enables faster iteration and isolates correctness bugs from API integration issues.
- **Phase 2 before Phase 3:** Basic output works in Phase 2; richer formatting is additive, not foundational. The live loop must work before polish matters.
- **Phase 3 before Phase 4:** Delta tracking (Phase 3) is a prerequisite for dark horse detection and dashboard views (Phase 4).
- **Phase 5 last:** Optimization should follow proven correctness. What-if and backtest modes benefit from a stable, tested base.
- **`rich` in Phase 1 (not deferred):** Formatted tables are necessary for reading 16-team probability output. Raw `print()` produces unreadable output even in Phase 1 testing.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 1 (Elo):** K-factor optimization for World Cup knockouts — validate eloratings.net's K=60 against historical data. Also evaluate `football-api` PyPI wrapper as alternative to raw `requests` + manual Pydantic models.
- **Phase 2 (API):** Football-Data.org free tier behavior during peak World Cup load — determine auto-fallback aggressiveness. Verify API ID stability guarantees.
- **Phase 4 (Analytics):** Modal bracket tracking algorithm design. Dark horse threshold research from historical tournaments.
- **Phase 5 (Backtest):** Historical World Cup data sourcing (who has free-accessible 2022 match data with Elo ratings?).

**Phases with standard patterns (skip research-phase):**
- **Phase 3 (Rich Output):** Rich library is well-documented, standard patterns. Use the `Table` + `Live` + `Progress` API directly.
- **Phase 1 (State Persistence):** Atomic JSON write pattern is standard. Use `os.replace()` after `json.dump()`.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** | All recommendations verified against current PyPI releases (requests 2.32.3, numpy 2.4.6, rich 15.0.0, pydantic 2.10.x) and official documentation. Anti-dependency decisions confirmed by project scope. |
| Features | **HIGH** | Table stakes verified against FiveThirtyEight PELE, ESPN SPI, and 6+ open-source GitHub predictors. Differentiators drawn from gaps in CLI tool ecosystem and community requests. Anti-features consistent with PROJECT.md scope. |
| Architecture | **HIGH** | Five-layer decomposition confirmed across 10+ ecosystem projects (goal-analytics, world-cup-2026-forecast, mundial-monte, chessswissprediction, etc.). Pure-function module pattern is universal in Python CLI tools. |
| Pitfalls | **HIGH** | Elo pitfalls verified against eloratings.net and Wikipedia. MC overconfidence from peer-reviewed Journal of Sports Analytics paper (2018). API pitfalls from Sportmonks engineering blog + project CONCERNS.md. Bracket bug patterns from general recursive data structure knowledge. |

**Overall confidence:** HIGH

### Gaps to Address

1. **Elo K-factor for World Cup knockouts:** Eloratings.net recommends K=60 for World Cup finals, but this needs validation against historical WC data. Needs phase-specific research during Phase 1 planning.

2. **Football-Data.org free tier reliability:** How has the free tier performed during peak World Cup periods? Determines whether fallback should be aggressive (auto-switch to mock data) or lenient (wait for recovery). Needs testing before tournament.

3. **Exact tournament probability (Phylourny):** The Phylourny paper (Springer 2023) offers exact win probability calculation for 16-team brackets — 100× faster than MC. Evaluate whether to implement this alongside MC as a Phase 5 enhancement. Flagged for architecture decision.

4. **Penalty shootout Elo correlation:** No published research on how Elo correlates with penalty shootout win rates. Current recommendation: accept 50/50 simplification with documented caveat. Post-MVP: adjust Elo toward 50/50 for penalty outcomes.

5. **NumPy vs iterative performance for 16-team bracket:** The research is slightly split — STACK.md warns of 8–15s for pure Python loops; ARCHITECTURE.md ecosystem data shows 2–5s. Resolve with profiling in Phase 1: if >5s, add numpy optimization in Phase 5.

---

## Sources

### Primary (HIGH confidence)
- **Official docs:** football-data.org v4 API docs (v4/coding/python.html, v4/policies.html) — API usage patterns, rate limits
- **PyPI:** numpy 2.4.6, rich 15.0.0, requests 2.32.3, pydantic 2.10.x — current versions verified
- **Eloratings.net** — World Football Elo Ratings methodology (K-factors, goal margin multiplier, home advantage)
- **Wikipedia: World Football Elo Ratings** — Academic verification of Elo modifications for football
- **Demsyn-Jones, "Misadventures in Monte Carlo"** (Journal of Sports Analytics, 2018) — MC overconfidence in playoff prediction
- **Pydantic v2 docs** (pydantic.dev) — Rust-backed validation patterns
- **Rich readthedocs** — Cross-platform ANSI, Windows support

### Secondary (HIGH confidence — ecosystem sources)
- **goal-analytics** (nithinnarla/goal-analytics, 2026-04) — Elo → Poisson → MC pipeline, project structure
- **world-cup-2026** (steodose/world-cup-2026, 2026-06) — Vectorized numpy MC, 50K sims <1s
- **world-cup-2026-forecast** (manuelpeba, 2026-03) — Production-style modular architecture
- **mundial-monte** (MPG-Paradox, 2026-05) — Live update loop, weekly re-simulation
- **chessswissprediction** (geckods, 2025-09) — Elo-based MC, module separation
- **MarchMadSim** (jordydavelaar, 2025-03) — NCAA bracket simulator, MC + round-by-round modes
- **FiveThirtyEight SPI / Silver Bulletin PELE** — State-of-the-art reference for Elo-based tournament prediction
- **ESPN Soccer Power Index** — Official methodology documentation
- **Sportmonks blog: "5 Common Mistakes Developers Make with Football APIs"** — API integration pitfalls

### Tertiary (MEDIUM confidence — used with caution)
- **Phylourny paper** (Springer, 2023) — Exact tournament probability calculation; needs evaluation
- **football-api PyPI wrapper** (v0.1.1, 2026-02) — New, may have incomplete endpoint coverage
- **Project CONCERNS.md** — Project-specific risk documentation (internal, authoritative for this project)

---

*Research completed: 2026-06-13*
*Ready for roadmap: yes*
