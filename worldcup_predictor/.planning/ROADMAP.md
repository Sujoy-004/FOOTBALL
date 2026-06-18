# Roadmap: World Cup Dynamic Prediction

## Milestones

- ✅ **v1.0 MVP** — Phases 1–6 (shipped 2026-06-14)
- ✅ **v1.1 World Cup 2026 Support** — Phases 7–10 (shipped 2026-06-14)
- 📋 **v2.0 Prediction Engine Modernization** — Phases 11–20 (active)

## Overview

The v2.0 milestone modernizes the prediction engine. The audit revealed that the Elo foundation is 63% wrong, draws are skipped, and the goal-difference K-multiplier is missing — while two critical free signals (market odds, BSD CatBoost) are completely unused. v2.0 fixes the foundation, adds multi-signal blending, and establishes model governance. See `worldcup_predictor/MODERNIZATION-PROPOSAL.md` for the full architecture.

## Phases

- [x] **Phase 7: 48-Team Dataset & Group Definitions** — Teams, groups, Annex C table, aliases, and validators
- [x] **Phase 8: Group Stage Simulation Engine** — Round-robin simulation, standings, tiebreakers, R32 matchup resolution
- [x] **Phase 9: Knockout Bracket with Annex C Routing** — Full 104-match simulation pipeline
- [x] **Phase 10: Integration, Tests & BSD Verification** — Live data, console display, E2E testing
- [x] **Phase 11: Data Integrity & Elo Foundation** — Fix Elo ratings, auto-sync from eloratings.net
- [x] **Phase 12: Draw Handling & Elo Math** — Fix draw pipeline, implement K-multiplier
- [x] **Phase 12b: Evaluation Infrastructure** — Brier, log loss, calibration, prediction history storage
- [x] **Phase 13: Signal Ingestion** — Market odds API, CatBoost predictions API
- [x] **Phase 14: Signal Blending** — Calibration layer, dynamic blender, simulation integration
- [x] **Phase 14a: Prediction Retention Architecture Fix** — Permanent prediction ledger for pre-match signal archival
- [x] **Phase 15: Context Signals** — Team form, lineup strength, player availability
- [~] **Phase 16: Model Governance** — Versioning, Brier monitoring, backtesting, alerts (3/3 plans, Task 3 of Plan 03 deferred to separate agent)
- [ ] **Phase 17: Enriched Match Context** — Live event fields (goals, cards, subs, possession, shots, corners, fouls), coach/venue/referee/weather data
- [ ] **Phase 18: xG & AI Prediction Signals** — xG predictions, AI preview/pre-match analysis ingestion
- [ ] **Phase 19: Multi-League Framework** — All 65 BSD leagues, --league CLI flag, per-league state isolation
- [ ] **Phase 20: Output Enhancement & Coverage Seal** — Signal breakdown, confidence intervals, probability log, 85% API coverage

## Phase Details

<details>
<summary>✅ v1.0 MVP (Phases 1–6) — SHIPPED 2026-06-14</summary>

### Phase 1: State & Elo Foundation

**Goal**: Tournament bracket and Elo ratings can be loaded, computed, validated, and persisted across restarts via JSON files.
**Plans**: 2 plans

Plans:

- [x] 01-01: Data Loading & Bracket Validation (scaffold, state.py load+validate, seed data, main.py entry)
- [x] 01-02: Elo Engine & State Persistence (elo.py, atomic save functions, integration test)

### Phase 2: Monte Carlo Simulation

**Goal**: System can simulate the remaining knockout tournament 50,000+ times and compute accurate championship probabilities from current Elo ratings.
**Plans**: 2 plans

Plans:

- [x] 02-01: Core simulation engine (simulation.py + tests + main.py wiring)
- [x] 02-02: Performance benchmark (benchmark script + verification)

### Phase 3: Live API Integration

**Goal**: System fetches live match results from Football-Data.org API with robust error handling.
**Plans**: 2 plans

Plans:

- [x] 03-01: Core fetcher module + unit tests
- [x] 03-02: main.py integration + API key validation

### Phase 4: Main Loop & Shutdown

**Goal**: System runs autonomously — polls continuously, detects new matches, triggers re-simulation, and shuts down gracefully on Ctrl+C.
**Plans**: 1 plan

Plans:

- [x] 04-01: Main loop, signal handlers, graceful shutdown

### Phase 5: Console Output & Formatting

**Goal**: System displays colored, delta-tracking championship probabilities in the terminal.
**Plans**: 2 plans

Plans:

- [x] 05-01: Core probability table with ANSI colors, delta tracking, and risers/fallers
- [x] 05-02: Remaining output blocks (header, match alerts, heartbeat, shutdown, errors)

### Phase 6: CLI Interface & Polish

**Goal**: User controls the tool via command-line flags with full usage documentation.
**Plans**: 2 plans

Plans:

- [x] 06-01: Argparse + --help + --no-color
- [x] 06-02: --once + --seed

</details>

---

### ✅ v1.1 World Cup 2026 Support (Complete — Shipped 2026-06-14)

**Milestone Goal:** The predictor handles the full 48-team FIFA World Cup 2026 format — 12 groups of 4, 72 group matches, Annex C third-place routing, and the complete 104-match tournament tree — with live BSD API integration and verified correctness.

---

### Phase 7: 48-Team Dataset & Group Definitions

**Goal**: All 48 teams, 12 group definitions, 495-entry Annex C lookup table, and team aliases exist as validated, loadable data files.

**Depends on**: Phase 6

**Requirements**: DATA2-01, DATA2-02, DATA2-03, DATA2-04, DATA2-05, DATA2-06

**Success Criteria** (what must be TRUE):

- `data/teams.json` contains exactly 48 teams with researched Elo ratings and group assignments matching the official FIFA 2026 qualified teams
- `data/groups.json` defines exactly 12 groups (A–L) with 4 teams each, matching the official FIFA 2026 draw
- `data/annex_c.json` contains exactly 495 entries with correct sorted-letter key invariant, matching FIFA's official Annex C mappings
- `data/team_aliases.json` covers all 48 teams with BSD API name variations for reliable live match ingestion
- `validate_groups()` and `validate_annex_c()` pass without errors, catching invalid data (wrong team count, missing keys, incorrect structure)

**Plans**: 4 plans

Plans:

- [x] 07-01-PLAN.md — Constants & 48-Team Roster (Wave 1)
- [x] 07-02-PLAN.md — Groups, Annex C & Aliases Data Files (Wave 2)
- [x] 07-03-PLAN.md — State.py Load/Validate Extensions (Wave 2)
- [x] 07-04-PLAN.md — Tests & Production Data Verification (Wave 3)

---

### Phase 8: Group Stage Simulation Engine

**Goal**: Group stage works end-to-end — Poisson-scored round-robin match simulation, 7-step within-group tiebreaker chain, 5-step cross-group third-place ranking, advancement selection, and Annex C R32 matchup resolution.

**Depends on**: Phase 7

**Requirements**: GROUPS-01, GROUPS-02, GROUPS-03, GROUPS-04, GROUPS-05, GROUPS-06, GROUPS-07

**Success Criteria** (what must be TRUE):

- Group standings computed correctly per FIFA rules — points, goal difference, goals for/against — for all 12 groups after simulated matches
- Within-group tiebreaker resolves 2/3/4-team ties correctly using the full 7-step recursive chain (H2H pts → H2H GD → H2H GS → overall GD → overall GS → fair play → FIFA ranking)
- Cross-group third-place ranking selects exactly 8 of 12 third-placed teams using the correct 5-step tiebreaker (points → GD → GS → fair play → FIFA ranking), with the 8th/9th boundary clearly discernible
- R32 matchups resolve correctly via Annex C lookup for all 495 third-place scenarios — the combination key produces the correct group winner / runner-up / third-place pairings
- 50K full simulation iterations complete in < 15 seconds

**Plans**: 4 plans

Plans:

- [x] 08-01-PLAN.md — Core Group Simulation (Poisson model, expected_goals, simulate_group_matches, fair play card draw)
- [x] 08-02-PLAN.md — Standings & Tiebreakers (compute_standings, 7-step recursive H2H-first tiebreaker)
- [x] 08-03-PLAN.md — Advancement & Annex C (rank_third_placed, select_advancers, resolve_r32_matchups)
- [x] 08-04-PLAN.md — Performance Benchmark (benchmark_groups.py, 50K < 15s verification)
  - **Result:** 50K in 12.66s — [PASS] (target < 15s)
  - Optimizations: fair_play=False, inverse-CDF table, MAX_EXPECTED_GOALS cap, precomputed lambdas, inlined hot-path simulation, direct `[]` access in compute_standings

---

### Phase 9: Knockout Bracket with Annex C Routing

**Goal**: Full 104-match simulation pipeline runs correctly — `run_full_simulation()` executes group stage → Annex C → R32 → R16 → QF → SF → TPP → FINAL with correct slot resolution at every round.

**Depends on**: Phase 8

**Requirements**: BRKT-01, BRKT-02, BRKT-03, BRKT-04, BRKT-05, BRKT-06, BRKT-07, BRKT-08

**Success Criteria** (what must be TRUE):

- `data/bracket.json` defines all 40 knockout matches (R32→R16→QF→SF→TPP→FINAL) using `group_position` and `annex_c_third` slot types — never hardcoded team names for R32
- R32 simulation correctly resolves `group_position` slots (e.g. A2, B1) to actual teams from group standings, and `annex_c_third` slots via Annex C lookup
- R16–FINAL simulation uses the existing `source_matches` pattern, unchanged from v1.0
- Third-place match correctly simulated from SF losers (two losing semi-finalists)
- `run_full_simulation()` completes the full 48-team pipeline without errors, returning championship probabilities for all 48 teams
- Bracket validation passes all checks: round counts, slot types, R16 wiring per FIFA Article 12.7
- All existing v1.0 knockout tests continue to pass unchanged

**Plans**: 3 plans

Plans:

- [x] 09-01-PLAN.md — R32 Bracket Data (32-match bracket.json with slot descriptors)
- [x] 09-02-PLAN.md — Knockout Module (knockout.py with run_full_simulation, R32 sim, TPP)
- [x] 09-03-PLAN.md — Integration, Validation & Tests (main.py wiring, 13 tests, bracket validation)

### Phase 10: Integration, Tests & BSD Verification — Complete 2026-06-14

**Goal**: Live 48-team predictor runs end-to-end — BSD API polls and ingests group matches, console displays group standings with third-place bubble indicator, all tests pass with updated fixtures, and real API smoke test completes successfully.

**Depends on**: Phase 9

**Requirements**: INTG-01, INTG-02, INTG-03, INTG-04, INTG-05, INTG-06, INTG-07, INTG-08, INTG-09, INTG-10

**Success Criteria** (what must be TRUE):

- ✅ BSD API polling detects group match results and correctly maps them to `groups.json` match slots via team-name inference
- ✅ Group match results stored in separate `played_groups.json` — no contamination of knockout bracket data
- ✅ Console output displays 12 group standings tables showing position, points, goal difference, and goals for each team
- ✅ Third-place bubble indicator shows the 8th vs 9th ranked third-place teams with their tiebreaker differences
- ✅ Console header updated for 48-team format ("48 teams, 12 groups, 40 bracket matches, 72 group matches, 495 Annex C scenarios")
- ✅ E2E test with mock data passes through the full 104-match pipeline
- ✅ Live BSD smoke test scaffolding created (`test_live_smoke.py` with skipif for API key)
- ✅ Pre-existing `test_main_loop_runs_iterations` failure is fixed
- ✅ Full test suite passes with **0 failures** (212 passed, 1 skipped — live smoke requires BSD_API_KEY)
- ✅ All 7 Sources of Truth (PRD, TRD, MVP, Appflow, Backend Schema, UI/UX, Implementation Plan) batch-updated for 48-team format

**Plans**: 4 plans

Plans:

- [x] 10-01-PLAN.md — Group Match Ingestion & Persistence (Wave 1)
- [x] 10-02-PLAN.md — Group Standings Console Display (Wave 2)
- [x] 10-03-PLAN.md — Test Fixes & E2E Tests (Wave 3)
- [x] 10-04-PLAN.md — SOT Batch Update & Smoke Test (Wave 4)

---

### Phase 11: Data Integrity & Elo Foundation

**Goal:** Fix the Elo foundation — correct all 48 Elo ratings to match eloratings.net, apply missing updates from early tournament matches, and implement auto-sync so Elo values self-heal without manual entry for the rest of the tournament.

**Depends on:** Phase 10

**Requirements**: V2-01, V2-02

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-01 | All 48 Elo ratings match eloratings.net within 5 points | ✅ |
| V2-02 | Elo values auto-sync from eloratings.net every N minutes | ✅ |

**Success Criteria** (what must be TRUE):

- All 48 teams in teams.json have Elo ratings within 5 points of eloratings.net values
- Missing Elo updates from early tournament matches (5 rounds) are applied to affected teams
- Auto-sync fetches current Elo ratings from eloratings.net on a configurable interval
- Team name mapping resolves all 48 teams correctly (inverse alias lookup)
- Drift detection flags unusual Elo movements (> 2σ from typical change)
- Startup validation compares every team's Elo against eloratings.net and warns on > 50-point discrepancies
- All existing tests continue to pass (212 passed, 1 skipped)

**Plans:** 3 plans

Plans:

- [x] 11-01-PLAN.md — Core Elo Sync Infrastructure (constants, state persistence, elo_sync module) — Wave 1
- [x] 11-02-PLAN.md — main.py & output.py Integration (startup sync, 24h timer, console display) — Wave 2
- [x] 11-03-PLAN.md — Tests & Fixtures (TSV fixtures, test_elo_sync.py with 7 test classes) — Wave 2

---

### Phase 12: Draw Handling & Elo Math

**Goal:** Fix the draw pipeline — stop skipping draws in both live and historical processing, apply correct Elo updates for draws, and implement the goal-difference K multiplier per eloratings.net formula.

**Depends on:** Phase 11

**Requirements**: V2-03, V2-04

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-03 | Draw results are ingested and Elo-updated correctly | ✅ |
| V2-04 | Goal-difference K multiplier implemented per eloratings.net formula | ✅ |

**Success Criteria** (what must be TRUE):

- Draw matches in `played.json` and `played_groups.json` trigger Elo updates instead of being skipped
- `fetcher.py:126` (knockout, live), `fetcher.py:314` (group, live), `main.py:251` (knockout, historic) all route draws to `update_ratings()` instead of skipping
- Goal-difference K-multiplier uses eloratings.net step-function: G=1 (draw/1-goal win), G=1.5 (2-goal win), G=(11+N)/8 (3+ goal win, where N=goal difference)
- Elo updates for blowout wins (>3 goal margin) have larger impact than narrow wins (G=1.75 for 3-goal win, 2.0 for 5-goal win)
- Update test coverage: draw match fixtures, K-multiplier unit tests
- Baseline Brier/log-loss recorded on historical replay for comparison against Phase 13+

**Plans:** 3 plans

Plans:

- [x] 12-01-PLAN.md — Elo Engine Extensions: K-multiplier & PK Mode (Wave 1)
- [x] 12-02-PLAN.md — Draw Pipeline Fix: Three Code Sites (Wave 1)
- [x] 12-03-PLAN.md — Historical Backfill & Baseline Metrics (Wave 2)

---

### Phase 12b: Evaluation Infrastructure

**Goal:** Build the measurement framework that every subsequent phase uses to prove improvement — Brier score, log loss, calibration curves, and persistent prediction history for retrospective analysis.

**Depends on:** Phase 12

**Requirements**: V2-18, V2-19

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-18 | Baseline prediction evaluation framework (Brier, log loss, calibration) computed per match | ✅ |
| V2-19 | Match-level prediction history stored persistently for analysis | ✅ |

**Success Criteria** (what must be TRUE):

- ✅ `BrierScore` computed for each match prediction: (p - outcome)² where outcome ∈ {0, 0.5, 1}
- ✅ Log loss computed: -[y·log(p) + (1-y)·log(1-p)]
- ✅ Calibration curve bins available (decile-based, ECE computed)
- ✅ Prediction history persisted to JSON (match_id, probabilities per outcome, actual outcome, signal breakdown)
- ✅ Historical replay can walk through all completed matches and produce aggregate Brier/log-loss
- ✅ Baseline measurements recorded after Phase 12 (draw-fixed Elo only) for future A/B comparison
- ✅ All evaluation functions tested (28 tests)

**Plans:** 1 plan

Plans:

- [x] 12b-01-PLAN.md — Evaluation Infrastructure (State, evaluate, baseline, tests)

---

### Phase 13: Signal Ingestion

**Goal:** Add two new independent prediction signals — market odds (vig-removed) and CatBoost ML predictions — to complement Elo-based predictions.

**Depends on:** Phase 12b

**Requirements**: V2-05, V2-06

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-05 | Market odds fetched and converted to vig-removed probabilities | 🔲 |
| V2-06 | CatBoost predictions fetched for every match | 🔲 |

**Success Criteria** (what must be TRUE):

- Market odds endpoint integrated (e.g., The Odds API or equivalent)
- Basic vig removal applied: normalized probabilities = 1/(1+decimal_odds) / sum(margin)
- Backtest: vig removal produces probabilities summing to 1.0 ± 0.01
- CatBoost API (BSD-provided) queried for every upcoming match
- Both signals cached aggressively — odds cache TTL configurable, CatBoost TTL match-level
- Graceful degradation: if odds unavailable for a match, flag as missing rather than crashing
- Per-signal Brier computed (using Phase 12b framework) to establish individual signal accuracy

**Plans:** 3/3 plans complete

Plans:

- [x] 13-01-PLAN.md — Foundation & Market Odds Signal (Wave 1): constants, state.py cache helpers, predictors package, odds.py with vig removal, tests
- [x] 13-02-PLAN.md — CatBoost ML Predictions (Wave 2): catboost.py with BSD predictions API fetch, parse, cache; tests
- [x] 13-03-PLAN.md — Migration, Evaluation Extension & Main.py Wiring (Wave 3): prediction_history migration, per-signal Brier via evaluate_all_matches(signal_name=), signal fetch/refresh in main.py

---

### Phase 14: Signal Blending

**Goal:** Combine Elo, market odds, and CatBoost into a single calibrated prediction via Platt scaling per signal and dynamic Brier-weighted ensemble.

**Depends on:** Phase 13

**Requirements**: V2-07, V2-08, V2-09

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-07 | Signal calibration layer (Platt scaling) implemented per signal | ✅ |
| V2-08 | Dynamic signal blender (Brier-weighted) integrated into simulation | ✅ |
| V2-09 | Calibrated Poisson base rate from historical World Cup data | ✅ |

**Success Criteria** (what must be TRUE):

- Platt scaling fitted per signal (logistic regression on log-odds of prediction vs. actual outcome)
- Calibrated probabilities closer to empirical frequencies (calibration curve slope closer to 1)
- Dynamic blender weights each signal by inverse of its rolling Brier score (window: configurable, default 50 matches)
- Blended probability outperforms best individual signal by ≥0.02 Brier on held-out data
- Poisson base rate computed from historical WC group match scoring rates
- Base rate integrated as a prior that anchors blended probabilities in data-sparse regimes
- Blender degrades gracefully when signals are missing (re-normalizes weights)

**Plans:** 2 plans

Plans:

- [x] 14-01-PLAN.md — Blender Core Module (Wave 1): Platt scaling, blending functions, LOO-CV, Poisson base rate function, test_blender.py
- [x] 14-02-PLAN.md — Simulation & Pipeline Integration (Wave 2): knockout.py blend_params, main.py calibration pipeline, Poisson rate wiring, state.py persistence

---

### Phase 14a: Prediction Retention Architecture Fix

**Goal:** Bridge the architectural gap between signal ingestion (Phase 13) and evaluation (Phase 12b) — pre-match predictions must persist beyond TTL expiry so that multi-signal Brier and calibration can be computed for finished matches.

**Discovery:** Design flaw found during operational validation of Phases 13-14. The TTL-based cache architecture loses predictions for every match once it finishes, making `_merge_signals_into_history()` find zero overlap. Without this fix, market_odds and catboost Brier can never be computed, and blending has no calibration data.

**Depends on:** Phase 14

**Requirements**: V2-20

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-20 | Pre-match predictions retained permanently for historical Brier computation | ✅ |

**Success Criteria** (what must be TRUE):

- `data/predictions_ledger.json` exists and accumulates predictions across TTL refreshes
- Every odds fetch upserts its entries into the ledger (never deletes)
- Every CatBoost fetch upserts its entries into the ledger (never deletes)
- `_merge_signals_into_history()` reads from the ledger (not TTL caches), matching by `match_id`
- Predictions for matches that have finished are still present in the ledger
- TTL caches unchanged — continue serving live freshness for dashboard

**Plans:** 1 plan

Plans:

- [x] 14a-01-PLAN.md — Permanent prediction ledger: constants, state, odds/catboost wiring, merge source change

---

### Phase 15: Context Signals

**Goal:** Add team-level context signals — recent form and lineup strength — to further refine predictions before matches.

**Depends on:** Phase 14

**Requirements**: V2-10, V2-11

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-10 | Team form signal (last 5 matches) computed and integrated | 🔶 In Progress (form.py complete) |
| V2-11 | Lineup strength factor (market value proxy) computed | 🔶 In Progress (lineup.py complete) |

**Success Criteria** (what must be TRUE):

- Form signal computed via Elo-based residual sum over configurable rolling window (default 5)
- Form signal as independent 4th signal (key: "form"), NOT an Elo modifier
- Lineup strength: total squad market value from static `data/team_values.json` (not BSD API)
- Market value converted via log-ratio: `p = sigmoid(k * ln(home / away))`
- Both signals persist to permanent prediction ledger (Phase 14a pattern)
- Both signals go through Platt calibration + Brier blending alongside odds/catboost/Elo
- Both signals use `available: false` with `reason` for graceful degradation when data missing
- Model degrades gracefully when context data unavailable (skips signal, uses base blend)

**Plans:** 3 plans

Plans:

- [x] 15-01-PLAN.md — Data Layer & Constants (Wave 1): constants, team_values.json, load_team_values()
- [x] 15-02-PLAN.md — Signal Modules (Wave 2): form.py, lineup.py, __init__.py update
- [x] 15-03-PLAN.md — Integration & Tests (Wave 3): main.py wiring, test_form.py, test_lineup.py

---

### Phase 16: Model Governance

**Goal:** Add the three pillars of governance — versioning (data/model/run), Brier monitoring per signal with drift detection, and backtesting against historical World Cups.

**Depends on:** Phase 15

**Requirements**: V2-12, V2-13, V2-14

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-12 | Model version, data version, and run version tracked | ✅ |
| V2-13 | Per-signal Brier scoring with drift detection | 🔲 |
| V2-14 | Backtesting framework against historical World Cups | 🔲 |

**Success Criteria** (what must be TRUE):

- `versions.json` tracks data_version, model_version, run_version with increment semantics
- Every prediction logged with its signal-specific version IDs
- Rolling Brier window computed per signal, logged to `runs/` directory
- Drift alert triggered when any signal's 50-match Brier exceeds 2σ from its baseline
- Backtesting framework replays past World Cup matches through current pipeline
- Backtest report: aggregate Brier, log loss, calibration ECE across historical tournaments
- Governance dashlet in CLI shows: versions, per-signal Brier trend, last drift check timestamp

**Plans:** 3 plans (1 complete, 2 remaining)

Plans:

- [x] 16-01: Version Tracking Foundation (governance constants, state persistence, pure version computation, 16 tests) — Complete 2026-06-18
- [ ] 16-02: Governance Orchestrator + Drift Detection + Dashlet
- [ ] 16-03: Backtesting Framework

---

### Phase 17: Enriched Match Context

**Goal:** Expand BSD event field coverage from ~10 to 40+ fields — live match stats (goals, cards, subs, possession, shots, corners, fouls), plus coach, venue, referee, and weather data.

**Depends on:** Phase 16

**Requirements**: V2-21, V2-22

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-21 | Live match event fields (goals, cards, subs, possession, shots, corners, fouls) ingested from BSD for each match | 🔲 |
| V2-22 | Coach, venue, referee, and weather data ingested and accessible for match context | 🔲 |

**Success Criteria** (what must be TRUE):

- BSD event feed parsed for all major event types (goals, yellow/red cards, substitutions, possession %, shots on/off target, corners, fouls)
- Coach name, venue name, referee name, and weather conditions extracted per match
- All enriched fields stored in `played.json` / `played_groups.json` per match
- Graceful degradation when fields are missing from API response
- Console optionally displays match context summary (--context flag)
- Zero regression on existing test suite

**Plans:** TBD

Plans:

- *(to be planned via /gsd-plan-phase 17)*

---

### Phase 18: xG & AI Prediction Signals

**Goal:** Integrate BSD's xG predictions and AI-powered pre-match analysis as additional prediction signals feeding into the blender.

**Depends on:** Phase 17

**Requirements**: V2-23, V2-24

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-23 | BSD xG predictions ingested as independent prediction signal | 🔲 |
| V2-24 | BSD AI preview / pre-match analysis ingested and displayed | 🔲 |

**Success Criteria** (what must be TRUE):

- xG data points (home_xg, away_xg) extracted from BSD match predictions endpoint
- xG converted to match outcome probabilities via Poisson-based xG model
- AI preview text ingested and stored per match
- xG registered as a 5th signal in the blender alongside Elo/odds/catboost/form/lineup
- AI preview displayed in console output when available
- Missing xG or AI preview degrades gracefully (signal marked unavailable)
- Zero regression on existing test suite

**Plans:** TBD

Plans:

- *(to be planned via /gsd-plan-phase 18)*

---

### Phase 19: Multi-League Framework

**Goal:** Refactor from single-league lock (league_id=27) to support all 65 BSD leagues — users select any league via CLI flag or config, with per-league state isolation.

**Depends on:** Phase 18

**Requirements**: V2-25, V2-26

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-25 | League selection via CLI flag (--league) and config, supporting all 65 BSD leagues | 🔲 |
| V2-26 | Multi-league data isolation (separate state files per league namespace) | 🔲 |

**Success Criteria** (what must be TRUE):

- `--league` CLI flag accepts any league ID from BSD's 65-league catalog
- League ID removed from hardcoded constants; configurable via flag or `config.json`
- State files namespaced per league (e.g. `data/27/played.json`, `data/65/played.json`)
- League catalog displayed via `--list-leagues` flag (name + ID)
- Elo sync scoped to teams within the selected league
- All existing functionality continues to work with default league (27 = World Cup)
- Zero regression on existing test suite

**Plans:** TBD

Plans:

- *(to be planned via /gsd-plan-phase 19)*

---

### Phase 20: Output Enhancement & Coverage Seal

**Goal:** Surface signal-level prediction details in console output, add confidence intervals, persist historical probability log, and reach 85% BSD API field coverage.

**Depends on:** Phase 19

**Requirements**: V2-27, V2-28, V2-29, V2-30

**Requirements Traceability:**

| ID | Requirement | Status |
|----|------------|--------|
| V2-27 | Per-match signal breakdown display (blended + per-signal) in console | 🔲 |
| V2-28 | Confidence intervals (Clopper-Pearson) alongside probabilities | 🔲 |
| V2-29 | Historical probability log across tournament duration with trend tracking | 🔲 |
| V2-30 | 85% BSD API field coverage (monitored and reported) | 🔲 |

**Success Criteria** (what must be TRUE):

- Per-match prediction shows: blended + Elo + odds + CatBoost + form + lineup + xG (when available)
- Confidence interval (Clopper-Pearson, 95%) displayed alongside blended probability
- Δ column shows change in each probability since last run
- Full probability snapshot persisted after every run (all teams, all stages)
- Trend arrows (↑ ↓ →) for champion probability vs. last snapshot
- Coverage auditor script reports % of BSD API fields utilized; target ≥85%
- Console output fits within terminal width (no wrapping)
- Historical deltas not shown on first run (no baseline to diff against)
- Zero regression on existing test suite

**Plans:** TBD

Plans:

- *(to be planned via /gsd-plan-phase 20)*

---

## Progress

**Execution Order:** 7 → 8 → 9 → 10 → 11 → 12 → 12b → 13 → 14 → 14a → 15 → 16 → 17 → 18 → 19 → 20

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. State & Elo Foundation | v1.0 | 2/2 | Complete | 2026-06-14 |
| 2. Monte Carlo Simulation | v1.0 | 2/2 | Complete | 2026-06-14 |
| 3. Live API Integration | v1.0 | 2/2 | Complete | 2026-06-14 |
| 4. Main Loop & Shutdown | v1.0 | 1/1 | Complete | 2026-06-14 |
| 5. Console Output & Formatting | v1.0 | 2/2 | Complete | 2026-06-14 |
| 6. CLI Interface & Polish | v1.0 | 2/2 | Complete | 2026-06-14 |
| 7. 48-Team Dataset & Group Definitions | v1.1 | 4/4 | Complete | 2026-06-14 |
| 8. Group Stage Simulation Engine | v1.1 | 4/4 | Complete | 2026-06-14 |
| 9. Knockout Bracket with Annex C Routing | v1.1 | 3/3 | Complete | 2026-06-14 |
| 10. Integration, Tests & BSD Verification | v1.1 | 4/4 | Complete | 2026-06-14 |
| 11. Data Integrity & Elo Foundation | v2.0 | 3/3 | Complete | 2026-06-15 |
| 12. Draw Handling & Elo Math | v2.0 | 3/3 | Complete | 2026-06-15 |
| 12b. Evaluation Infrastructure | v2.0 | 1/1 | Complete | 2026-06-15 |
| 13. Signal Ingestion | v2.0 | 3/3 | Complete   | 2026-06-16 |
| 14. Signal Blending | v2.0 | 2/2 | Complete | 2026-06-17 |
| 14a. Prediction Retention Fix | v2.0 | 1/1 | Complete | 2026-06-17 |
| 15. Context Signals | v2.0 | 3/3 | Complete | 2026-06-17 |
| 16. Model Governance | v2.0 | 2/3 | In Progress | 2026-06-18 |
| 17. Enriched Match Context | v2.0 | 0/0 | Defined | — |
| 18. xG & AI Prediction Signals | v2.0 | 0/0 | Defined | — |
| 19. Multi-League Framework | v2.0 | 0/0 | Defined | — |
| 20. Output Enhancement & Coverage Seal | v2.0 | 0/0 | Defined | — |
