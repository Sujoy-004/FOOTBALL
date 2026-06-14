# Project Research Summary

**Project:** World Cup Dynamic Prediction
**Domain:** CLI-based live FIFA World Cup 2026 tournament prediction — 48-team format migration
**Researched:** 2026-06-14
**Confidence:** HIGH

## Executive Summary

This project is a **live, self-updating tournament predictor** that polls a football API, updates team Elo ratings after every real result, runs thousands of Monte Carlo simulations, and prints updated championship probabilities to the terminal. The v1.0 shipped on 2026-06-14 with a 32-team knockout-only simulator (R16→FINAL, 23 matches, ~1.3s for 50K iterations, 98 tests). This research covers the **migration to the full FIFA 2026 48-team format**: 12 groups of 4, 72 group matches, Annex C third-place routing, and the full 104-match tournament tree.

The research confirms a pure Python stdlib approach with **zero new dependencies** (`dataclasses`, `enum`, `itertools` are already in stdlib). The existing five-layer decomposition (Fetcher → State → Elo → Simulator → Output) remains valid, with one new module (`src/groups.py`) for group simulation, standings computation, tiebreaker chains, and Annex C resolution. The most significant architectural change is the addition of a **Poisson score model** for group matches (replacing the binary win/loss model) — needed because goal difference is the primary tiebreaker for both within-group standings and cross-group third-place ranking.

**Key risks** center on correctly implementing the FIFA 2026 rules: (1) tiebreaker order was **reversed** from pre-2026 World Cups (H2H first, not overall GD), (2) the 495-entry Annex C lookup table must be validated at startup or the simulation silently produces illegal brackets, (3) performance degrades ~7× (from ~1.3s to ~10-15s per 50K iterations) — still within the 60s poll interval but needs profiling, and (4) group match results must be stored separately from knockout matches to prevent data corruption. The recommended roadmap follows the **4-phase sequence** established in RESPONSE.md: Dataset → Group Engine → Knockout Bracket → Integration.

---

## Key Findings

### Recommended Stack

**Confidence: HIGH** — all recommended technologies are stdlib, no new dependencies needed.

The research (STACK.md) confirms the existing stack is fully sufficient for the 48-team format. No pip installs needed beyond the existing `requests`, `pytest`, `pytest-cov`, and `python-dotenv`.

**Core technologies (unchanged from v1.0):**
- **Python 3.10+** — Cross-platform runtime; fast enough for 50K × 104 simulation iterations
- **`random` (stdlib)** — Monte Carlo PRNG; sufficient via `random.seed()` for reproducibility; numpy not needed at this scale
- **`json` (stdlib)** — State persistence; human-readable, no database setup, proven in v1.0
- **`requests >= 2.31`** — HTTP client for live match API (BSD); battle-tested with exponential backoff support

**New stdlib additions for v1.1:**
- **`dataclasses`** — Structured group/team/match models; replaces raw dicts for standings and simulation state
- **`math` (stdlib)** — Already used for `expected_score`; extended for Poisson goal model
- **`itertools`** — Group round-robin pairings via `itertools.combinations(groups, 2)` → 6 matches per group
- **`enum`** — Round identifiers (R32, R16, QF, SF, TPP, FINAL) and group labels (A–L); replaces string constants

**New data files:**
- `data/groups.json` (~2 KB) — 12 groups, 4 teams each, 6 round-robin matches per group
- `data/annex_c.json` (~50 KB) — 495-entry third-place routing table, keyed by sorted group combination
- `data/teams.json` (extended to ~8 KB) — 48 teams (was 32), now with `group` field per team
- `data/bracket.json` (replaced, ~3 KB) — 40-match knockout bracket (R32→R16→QF→SF→TPP→FINAL)
- `data/played.json` (extended) — Same schema; now tracking group results too

**What NOT to use (confirmed anti-dependencies):**
- `numpy` — Overkill for 50K iterations; adds ~200ms import overhead for ~0.5s speed gain at current scale
- Database (SQLite, PostgreSQL) — Data fits in memory; JSON files + atomic writes are sufficient
- `pandas` — Massive dependency for simple sort/groupby operations
- ORM or data validation lib — CLI tool with ~3000 LOC doesn't need heavy abstractions
- `pydantic` / `attrs` — Overkill; `dataclasses` + simple validation methods are sufficient for a CLI tool

### Expected Features

**Confidence: HIGH** — tournament format verified against FIFA official sources (regulations PDF, FIFA.com, ESPN, Wikipedia, 3+ independent cross-references).

This research specifically addresses the **48-team format migration (v1.1)**. The core pipeline features (Elo, MC simulation, API polling, console output) are already shipped in v1.0.

**Must have (table stakes) for v1.1:**
1. **Correct 48-team bracket structure** — 12 groups of 4 → R32 (with Annex C) → R16 → QF → SF → TPP → FINAL (104 matches)
2. **Group stage tables** — Standings for 12 groups with 7-step tiebreaker application (H2H points → H2H GD → H2H GS → Overall GD → Overall GS → Fair play → FIFA ranking)
3. **Annex C 495-scenario lookup** — Required for determining which third-place teams face which group winners in R32
4. **Third-place ranking** — 8 of 12 third-placed teams selected via 5-tier tiebreaker (Points → GD → GS → Fair play → FIFA ranking)
5. **Round-by-round advancement probabilities** — Extended from v1.0 to include R32 and R16 stages
6. **Group stage simulation** — 72 round-robin matches per MC iteration with Poisson score model
7. **Live match result ingestion for groups** — API polling must detect and apply group match results to standings

**Should have (differentiators) for v1.1:**
1. **Bubble indicator for third-place teams** — Show 8th/9th ranked third-place teams with tiebreaker differences
2. **Group stage "advance probability" output** — Distinct from "champion probability" for meaningful group-stage display
3. **Stability metric for incomplete groups** — Track how many third-place slots change across iterations
4. **"Matches remaining" count per group** — Context for users checking partial tournament data

**Defer (v2.0+ as defined in PROJECT.md):**
- V2-01: Most-likely full bracket visualization
- V2-02: Dark horse detection (gap between Elo and probability)
- V2-03: Historical probability log
- V2-04: Simple web dashboard (Flask + Chart.js)
- V2-05: What-if mode (simulate hypothetical match results)
- V2-06: Backtesting against historical tournaments
- V2-07: NumPy-accelerated simulation for larger iterations

### Architecture Approach

**Confidence: HIGH** — architecture verified against official FIFA regulations, tournamental project code, and existing v1.0 codebase analysis.

The architecture maintains the existing five-layer decomposition with one critical addition: Poisson-based score modeling replaces binary win/loss for group matches only.

**Major components:**

1. **`src/groups.py` (NEW)** — Group stage simulation engine. Responsibilities:
   - Simulate 72 round-robin group matches per MC iteration (Poisson score model for unplayed matches)
   - Compute 12 group standings with 7-step FIFA tiebreaker chain (recursive narrowing for multi-team ties)
   - Rank all 12 third-placed teams via 5-tier cross-group tiebreaker
   - Select 24 auto-advancers (top 2 per group) + 8 best third-placed teams
   - Resolve Annex C lookup to determine R32 matchups
   - **Functions:** `simulate_group_matches()`, `compute_standings()`, `rank_third_placed()`, `select_advancers()`, `resolve_r32_matchups()`

2. **`src/simulation.py` (EXTENDED)** — Monte Carlo simulator. Changes:
   - `run_simulation()` → `run_full_simulation()` adds group pre-stage before knockout loop
   - New `_simulate_r32()` for Round of 32 (mirrors existing `_simulate_r16()` logic)
   - `_simulate_r16()` now reads from `source_matches` like QF/SF/FINAL
   - New `_simulate_tpp()` for third-place match (tracks SF losers)
   - Existing `_simulate_knockout_round()` reused for QF/SF/FINAL (unchanged logic)

3. **`src/state.py` (EXTENDED)** — JSON persistence and validation. Adds:
   - `load_groups()` — load and validate `data/groups.json`
   - `load_annex_c()` — load and validate `data/annex_c.json` (495 entries, correct structure)
   - `validate_groups()` — 12 groups, 4 teams each, 6 matches per group, valid team references
   - `validate_annex_c()` — exactly 495 keys, sorted 8-letter keys, 8 assignments per entry
   - `validate_bracket()` extended — R32 slot type checks, round counts, FIFA Article 12.7 wiring

4. **`src/fetcher.py` (EXTENDED)** — Live data integration. Changes:
   - `_find_group_match()` — match API results to group match slots (scoped search to `groups.json`)
   - `process_matches()` extended to handle `"group"` vs `"knockout"` match types
   - Results stored in separate `played_groups.json` to prevent knockout bracket contamination

5. **`src/output.py` (EXTENDED)** — Console display. Adds:
   - Group standings tables (12 group tables showing positions, points, GD, GS)
   - Third-place bubble indicator (8th vs 9th ranked teams)
   - Updated match count header ("Loaded 48 teams, 12 groups, 40 bracket matches, 72 group matches, 495 Annex C scenarios")

**Key architectural decisions:**
- **Data separation:** `groups.json` + `bracket.json` — never combined into one artifact
- **R32 slot types:** `group_position` (fixed slots like A2 vs B2) + `annex_c_third` (third-place teams resolved via lookup table)
- **Score model:** Poisson (Knuth algorithm, ~15 lines of pure Python, no numpy) for group stage; binary Elo for knockout (unchanged)
- **Third-place match:** Track SF losers explicitly, simulate separately from winner progression
- **Dependency direction:** `main.py → groups.py → simulation.py → elo.py` — no circular imports
- **Annex C source:** Static `data/annex_c.json` file, loaded at startup, not hardcoded in Python

### Critical Pitfalls

**Confidence: HIGH** — pitfalls cross-referenced against FIFA regulations, tournamental project code, and known implementation bugs documented in DEV.to and community sources.

**Top 5 pitfalls that can break the v1.1 migration:**

1. **Tiebreaker Step Reversal** — FIFA reversed the tiebreaker order for 2026 (H2H first, not overall GD). Developers copying pre-2026 code get **5 of 7 steps wrong**. The recursive narrowing approach for multi-team ties is the #1 bug area. **Prevention:** Write tiebreaker as recursive function, test with 2/3/4-team ties, including the "circular" 3-team case (each beats one, loses to one). **Phase:** 8.

2. **Annex C Lookup Failures** — Silent wrong brackets when the 495-entry lookup table has missing keys, wrong combination key sorting, or reversed mapping direction. A missing key crashes the simulation silently or produces illegal matchups. **Prevention:** Validate all 495 entries at startup (`validate_annex_c()`), derive winner groups from data (not hardcoded), maintain sorted-key invariant. **Phase:** 7 (dataset) + 9 (validation).

3. **Performance Regression** — Jump from 15 to 104 matches per iteration (5.2M match simulations at 50K) increases time from ~1.3s to ~10-15s. Hidden cost: standings computation with tiebreaker recursion. **Prevention:** Profile first (1K iterations → measure), maintain running totals during match simulation, precompute `expected_score` lookup table, consider reducing to 25K iterations if group stage stabilizes earlier. **Phase:** 8.

4. **Third-Place Ranking Confusion** — Cross-group third-place ranking uses a **different tiebreaker** (5 steps, no H2H) than within-group standings (7 steps with H2H). Reusing the same function produces meaningless H2H comparisons (teams never played each other). **Prevention:** Two separate functions: `resolve_group_standings()` and `rank_third_placed()`. Test with tied 8th/9th boundary scenarios. **Phase:** 8.

5. **Group Match Persistence Collision** — Same team pair may appear in both group stage and knockout (e.g., Argentina vs Nigeria). The fetcher's `_find_bracket_match()` returns the wrong match slot, contaminating both standings and bracket. **Prevention:** Scoped search (`_find_group_match()` for groups, `_find_bracket_match()` for knockout), separate `played_groups.json` storage, distinct match_id scheme (`GRP_A_M1` vs `R32_M73`). **Phase:** 7 (data structure) + 10 (integration).

**Additional pitfalls:** BSD integration with partial group results (high probability variance), fair play scoring card deduction logic (2YC→RC = −3, not −5), bracket validation for 104-match DAG (needs round count, slot type, and FIFA Article 12.7 checks).

---

## Implications for Roadmap

Based on combined research, the 48-team format migration requires **4 sequential phases** (Phases 7–10, following the existing v1.0 Phases 1–6). The ordering is strict due to data dependencies.

### Phase 7: 48-Team Dataset & Group Definitions
**Rationale:** Foundation phase — all subsequent phases need the correct data shapes, especially the 495-entry Annex C table and 48-team roster. Must come first because Phase 8 (Group Engine) consumes `groups.json` and Phase 9 (Knockout Bracket) consumes `annex_c.json`.

**Delivers:**
- `data/groups.json` — 12 groups × 4 teams, 72 round-robin match definitions
- `data/annex_c.json` — All 495 Annex C entries (sourced from FIFA regulations PDF or verified mirror)
- `data/teams.json` — Extended to 48 teams with Elo ratings + group assignments
- `data/team_aliases.json` — Expanded aliases for all 48 teams (BSD API name normalization)
- `src/state.py` extensions: `validate_groups()`, `validate_annex_c()`, `load_groups()`, `load_annex_c()`

**Addresses features:** Table stakes #1 (48-team bracket structure), #13 (Annex C lookup), #6 (48 teams)

**Avoids pitfalls:** Pitfall #2 (Annex C validation), Pitfall #5 (data separation — separate `played_groups.json` design)

**Research flag:** ⚠️ Need deeper research during planning — the Annex C data source is not yet embedded. Must be extracted from FIFA regulations PDF or tournamental repo's `fifa-2026-annex-c-assignments.json` (which is a verified cross-reference). The 48 team Elo ratings for the 16 new teams need initial values assigned.

**Confidence:** HIGH — data structures are well-defined by FIFA regulations; no ambiguity.

---

### Phase 8: Group Stage Simulation Engine
**Rationale:** This is the core new capability. Must come after Phase 7 (needs `groups.json` shapes) but before Phase 9 (needs group engine working to test full simulation). The tiebreaker logic and Poisson score model are the highest-risk code in the migration.

**Delivers:**
- `src/groups.py` — Complete group simulation module
- Round-robin group match simulation (6 matches per group × 12 groups)
- Poisson score model (Knuth algorithm, pure Python, no numpy)
- 7-step within-group tiebreaker with recursive narrowing for multi-team ties
- 5-step cross-group third-place ranking (separate function!)
- Advancement selection: top 2 per group + 8 best third-placed
- R32 matchup resolution (Annex C lookup integrated)
- Standings computation (running totals maintained during match simulation)
- 40+ new unit tests covering tiebreaker scenarios (2/3/4-team ties, fair play, FIFA ranking)

**Addresses features:** Table stakes #12 (48-team bracket), #14 (group stage tables), #4 (advancement probabilities R32+)

**Avoids pitfalls:** Pitfall #1 (tiebreaker order), Pitfall #3 (performance — profile at this phase), Pitfall #4 (third-place ranking separate function), Pitfall #8 (fair play scoring)

**Performance benchmarks (acceptance criteria):**
- 1K iterations: < 0.3s
- 10K iterations: < 3s
- 50K iterations: < 15s

**Research flag:** ⚠️ Needs deeper research during planning — the Poisson goal model parameters (base rate, Elo→goals conversion formula) need validation against real World Cup match data. The fair play card distribution for Monte Carlo (probabilistic card assignment per team) needs historical baseline data.

**Confidence:** MEDIUM — tiebreaker complexity is high (3+ way ties, recursive narrowing), Poisson parameters need calibration.

---

### Phase 9: Knockout Bracket with Annex C Routing
**Rationale:** Must come after Phase 8 (needs group engine for R32 resolution) and Phase 7 (needs `annex_c.json`). This phase integrates group simulation output into the knockout pipeline, creating the full 104-match simulation loop.

**Delivers:**
- `data/bracket.json` — Replaced with 40-match structure (R32→R16→QF→SF→TPP→FINAL)
- R32 slot resolution: `group_position` + `annex_c_third` slot types resolved to actual teams
- `_simulate_r32()` — New function in `simulation.py`
- `_simulate_tpp()` — Third-place match (tracks SF losers)
- `_simulate_r16()` repurposed — Now reads from `source_matches` like QF/SF/FINAL
- `run_full_simulation()` — Complete 48-team simulation entry point
- `validate_2026_bracket()` — Comprehensive bracket validation (10+ sub-checks)
- 20+ new unit tests for full simulation pipeline

**Addresses features:** Table stakes #1–5 (full probability pipeline), #12 (48-team bracket structure)

**Avoids pitfalls:** Pitfall #7 (bracket validation), Pitfall #3 (performance regression — reuse existing knockout code where possible)

**Research flag:** ✅ Standard patterns — knockout simulation logic (`_simulate_knockout_round`) is well-tested in v1.0 and reused with minimal changes. R16 wiring is fixed per FIFA Article 12.7. No deeper research needed.

**Confidence:** HIGH — knockout traversal pattern is proven in v1.0 (98 tests passing). The main risk (Annex C resolution) is mitigated by Phase 7's validation and Phase 8's group engine.

---

### Phase 10: Integration, Tests & BSD Verification
**Rationale:** Final integration phase. Must come after Phase 9 (needs full simulation pipeline). This phase connects all modules into the end-to-end application, updates the live data pipeline (fetcher) to handle group matches, and validates against real BSD API data.

**Delivers:**
- `main.py` updated — Loads groups + annex_c on startup, calls `run_full_simulation()`
- `fetcher.py` updated — `_find_group_match()`, scoped search, group match detection
- `output.py` updated — Group standings display, updated header, third-place bubble indicator
- `data/played_groups.json` — Separate persistence for group match results
- All test fixtures updated for 48-team format
- E2E test with mock data through full 104-match pipeline
- Live BSD smoke test with `--once` flag
- All 7 SOTs batch-updated (PRD, TRD, MVP, Appflow, Backend Schema, UI/UX, Implementation Plan)

**Addresses features:** Table stakes #3 (live match ingestion for groups), #8 (predictions update automatically), #9 (error-resilient operation)

**Avoids pitfalls:** Pitfall #5 (group match persistence separation), Pitfall #6 (BSD integration with partial data)

**Research flag:** ⚠️ Needs deeper research during planning — BSD API response format for group stage matches needs verification. Specifically: does the API annotate which group a match belongs to? If not, the group inference logic (matching team names against `groups.json` team lists) needs careful design. Team aliases for 16 new teams (BSD may use different naming conventions).

**Confidence:** MEDIUM — BSD API behavior for group matches is unverified (v1.0 only handles knockout matches). Team alias completeness for 48 teams is unknown.

---

### Phase Ordering Rationale

**Why this specific order:**
1. **Phase 7 → Phase 8 → Phase 9 → Phase 10** is enforced by data dependencies: you can't simulate groups without group definitions, you can't build knockout bracket without group engine, you can't integrate without the full pipeline.
2. **Phase 7 first** because the Annex C validation is critical for safety — catching a missing entry at Phase 7 is cheap; catching it at Phase 9 requires backtracking.
3. **Phase 8 before Phase 9** because the group engine is the highest-risk component (tiebreaker logic, Poisson model). Building and testing it in isolation (Phase 8) before integrating with knockout (Phase 9) makes debugging tractable.
4. **Phase 10 last** because it depends on all other phases being stable. BSD integration testing is only meaningful with a complete, correct pipeline.

**What this delivers:**
- After Phase 7: Runnable project with 48-team data files (but no group simulation yet)
- After Phase 8: Group simulation works in isolation (testable via unit tests)
- After Phase 9: Full 104-match simulation works (testable via unit tests + benchmark)
- After Phase 10: End-to-end live prediction pipeline with BSD integration

**How this avoids pitfalls:**
- Tiebreaker bugs (Pitfall #1) caught in Phase 8 before Phase 9 integration
- Annex C data integrity (Pitfall #2) ensured in Phase 7, used by Phase 9
- Performance regression (Pitfall #3) benchmarked in Phase 8, optimized before Phase 9
- Data separation (Pitfall #5) designed in Phase 7, implemented in Phase 10
- Bracket validation (Pitfall #7) implemented in Phase 9 alongside bracket construction

---

### Research Flags

**Phases needing deeper research during planning (`/gsd-plan-phase --research-phase <N>`):**

| Phase | Reason | What to Research |
|-------|--------|------------------|
| **Phase 7** | Annex C data source extraction; 48-team Elo rating initialization | Identify verified Annex C mirror (tournamental repo's JSON is top candidate). Assign initial Elo ratings for 16 new teams (use FIFA world ranking → Elo conversion formula) |
| **Phase 8** | Poisson goal model calibration; fair play card distribution data | Research base goal rate for World Cup matches (~1.2 goals/team/match at Elo=1500). Find historical card distribution data for probabilistic fair play assignment |
| **Phase 10** | BSD API group match response format; 48-team alias coverage | Fetch sample BSD API response for a group match to verify `status`, team naming, group annotation. Expand `team_aliases.json` for all 48 teams |

**Phases with standard patterns (skip `research-phase`):**

| Phase | Reason |
|-------|--------|
| **Phase 9** | Knockout simulation pattern is proven in v1.0 (98 tests). R16 wiring is fixed per FIFA Article 12.7. The bracket structure is defined by regulations. No research needed beyond this document |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** | Pure Python stdlib fully sufficient for 48-team + 104-match simulation. No new dependencies. Confirmed via v1.0 codebase analysis and performance projections from existing `simulation.py` |
| Features | **HIGH** | Tournament format verified against FIFA official regulations, FIFA.com, ESPN, Wikipedia, and 3+ independent cross-references. All 12 group / 104-match / 495-scenario details confirmed by multiple HIGH-confidence sources |
| Architecture | **HIGH** | Verified against RESPONSE.md, tournamental project code (GitHub), existing v1.0 codebase (simulation.py, state.py, elo.py). The groups.py module design, bracket slot types, and R16 wiring match FIFA Article 12.7 |
| Pitfalls | **MEDIUM** | Tiebreaker rules cross-referenced against FIFA PDF and 3+ secondary sources. However, fair play card scoring edge cases and BSD API behavior for group matches are unverified in production. The "Looks Done But Isn't" checklist flags items that can't be verified until implementation |

**Overall confidence: HIGH** — the 48-team format migration is well-understood, the FIFA regulations are clearly documented, and the existing v1.0 codebase provides a proven foundation. The risks are manageable with proper validation (Annex C at startup, tiebreaker unit tests, performance benchmarks).

### Gaps to Address

1. **Annex C data source:** The 495-entry table must be extracted from a verified source. The tournamental project (`github.com/0800tim/tournamental`) has a verified `fifa-2026-annex-c-assignments.json`. This needs to be sourced and embedded as `data/annex_c.json`. **Action:** Investigate tournamental repo licensing, extract JSON, validate all 495 entries match FIFA regulations.

2. **Poisson goal model parameters:** The `expected_goals()` function needs a calibrated base rate. Research suggests ~1.2 goals/match at Elo 1500 for World Cup tournaments. **Action:** Cross-reference against 2022 World Cup goal statistics to calibrate. Default to base_rate=1.2 with config override.

3. **48-team Elo ratings for new teams:** 16 teams not in the current 32-team dataset need initial Elo ratings. FIFA world ranking can be converted to Elo via a linear mapping or Elo's built-in tournament seeding. **Action:** Assign initial Elo from FIFA ranking using formula: `Elo = 1500 + (32 - FIFA_rank) * 4` or similar.

4. **BSD API group match behavior:** The API response format for group matches is unverified in this project (v1.0 only processes knockout matches). The group letter may not be present in the API response, requiring team-name-based inference. **Action:** Fetch a sample group match result from BSD API pre-tournament, verify response fields.

5. **Fair play scoring calibration:** For Monte Carlo simulation, probabilistic card assignment needs historical baseline data per team. **Action:** Gather average YC/RC per match for each team from 2022 World Cup or recent qualifiers. Default to uniform distribution if unavailable.

6. **Team aliases for 48 teams:** The current `team_aliases.json` has only 11 entries. BSD may use "Korea Republic" while teams.json uses "South Korea". All 48 teams need alias coverage. **Action:** Compile BSD naming conventions for all 48 qualified teams before Phase 7 implementation.

---

## Sources

### Primary (HIGH confidence)
- **FIFA Official 2026 Format & Tiebreakers** — 12 groups of 4, 48 teams, 104 matches, 7-step group tiebreaker, 5-step third-place ranking. Confidence: HIGH (official source)
- **FIFA 2026 Regulations PDF (Articles 11-13, Annex C)** — 495-entry Annex C table, R16 wiring (Article 12.7), fair play scoring. Confidence: HIGH (official regulations)
- **FIFA Ticket Support Format FAQ** — Confirms 12 groups, R32, 8-match champion path. Confidence: HIGH (official FIFA support)
- **ESPN Format Guide** — Full schedule with R32 matchups confirmed. Confidence: HIGH (major sports news, cross-referenced with FIFA)
- **Wikipedia "2026 FIFA World Cup knockout stage"** — Complete Annex C table, full bracket tree, all 16 R32 matchups. Confidence: HIGH (community-maintained but cross-referenced with official sources)
- **Project codebase (v1.0)** — `simulation.py`, `state.py`, `fetcher.py`, `main.py`, `elo.py`, `output.py`. Confidence: HIGH (verified existing architecture)
- **RESPONSE.md** — Project architecture decisions, phase ordering, Annex C structure, R16 wiring. Confidence: HIGH (internal planning document)

### Secondary (MEDIUM confidence)
- **tournamental project (0800tim)** — GitHub repo with verified Annex C JSON data, R32 fixture verification code. Confidence: MEDIUM (independent implementation, cross-verified against Wikipedia and FIFA PDF)
- **DEV.to article by Mark** — Practical Annex C implementation guide (495 entries as JSON, combination key sorting). Confidence: MEDIUM (community consensus, cross-checked against official data)
- **Bracket2026.com** — Format overview, third-place rules, fair play scoring details. Confidence: MEDIUM (commercial predictor, verified against FIFA)
- **Sporting News / Goal.com / FOX Sports** — Tiebreaker order and fair play deduction values. Confidence: MEDIUM (major publishers, cross-consistent with FIFA but some published pre-2026 order)
- **myteamkickoff.com** — Identified the H2H vs Overall GD reversal as a common misconception. Confidence: MEDIUM (specialist blog, cited specific rule change)
- **World Football Elo Ratings** — Elo rating patterns for football, base rate calibration. Confidence: MEDIUM (community-maintained, widely used)

### Tertiary (LOW confidence)
- **Sports StackExchange** — Forum discussion on Annex C algorithm proof. Confidence: LOW (forum, no authoritative sourcing)
- **steodose/world-cup-2026 (GitHub)** — Reference implementation with vectorized Monte Carlo. Confidence: LOW (single source, unverified against official data)
- **Sportmonks blog** — Bracket API integration patterns. Confidence: LOW (vendor blog, but practical API integration insight)

---

*Research completed: 2026-06-14*
*Ready for roadmap: yes*
