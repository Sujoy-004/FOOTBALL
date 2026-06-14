# Roadmap: World Cup Dynamic Prediction

## Milestones

- ✅ **v1.0 MVP** — Phases 1–6 (shipped 2026-06-14)
- 🚧 **v1.1 World Cup 2026 Support** — Phases 7–10 (in progress)
- 📋 **v2.0 Enhanced Analytics** — Planned

## Overview

The v1.1 milestone migrates the tournament predictor from the 32-team knockout-only format to the full 48-team FIFA World Cup 2026 format with 12 groups, 72 round-robin matches, Annex C third-place routing, and the complete 104-match tournament tree. This requires new data files, a group stage simulation engine, an extended knockout bracket, and full integration with the live polling pipeline.

## Phases

- [ ] **Phase 7: 48-Team Dataset & Group Definitions** — Teams, groups, Annex C table, aliases, and validators
- [ ] **Phase 8: Group Stage Simulation Engine** — Round-robin simulation, standings, tiebreakers, R32 matchup resolution
- [ ] **Phase 9: Knockout Bracket with Annex C Routing** — Full 104-match simulation pipeline
- [ ] **Phase 10: Integration, Tests & BSD Verification** — Live data, console display, E2E testing

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

### 🚧 v1.1 World Cup 2026 Support (In Progress)

**Milestone Goal:** The predictor handles the full 48-team FIFA World Cup 2026 format — 12 groups of 4, 72 group matches, Annex C third-place routing, and the complete 104-match tournament tree — with live BSD API integration and verified correctness.

---

### Phase 7: 48-Team Dataset & Group Definitions

**Goal**: All 48 teams, 12 group definitions, 495-entry Annex C lookup table, and team aliases exist as validated, loadable data files that subsequent phases consume.

**Depends on**: Phase 6 (v1.0 CLI Interface & Polish)

**Requirements**: DATA2-01, DATA2-02, DATA2-03, DATA2-04, DATA2-05, DATA2-06

**Success Criteria** (what must be TRUE):
  1. `data/teams.json` contains exactly 48 teams with researched Elo ratings and group assignments matching the official FIFA 2026 qualified teams
  2. `data/groups.json` defines exactly 12 groups (A–L) with 4 teams each, matching the official FIFA 2026 draw
  3. `data/annex_c.json` contains exactly 495 entries with the correct sorted-letter key invariant, matching FIFA's official Annex C mappings
  4. `data/team_aliases.json` covers all 48 teams with BSD API name variations for reliable live match ingestion
  5. `validate_groups()` and `validate_annex_c()` pass without errors, catching invalid data (wrong team count, missing keys, incorrect structure)

**Plans**: TBD

---

### Phase 8: Group Stage Simulation Engine

**Goal**: Group stage works end-to-end — Poisson-scored round-robin match simulation, 7-step within-group tiebreaker chain, 5-step cross-group third-place ranking, advancement selection, and Annex C R32 matchup resolution.

**Depends on**: Phase 7

**Requirements**: GROUPS-01, GROUPS-02, GROUPS-03, GROUPS-04, GROUPS-05, GROUPS-06, GROUPS-07

**Success Criteria** (what must be TRUE):
  1. Group standings computed correctly per FIFA rules — points, goal difference, goals for/against — for all 12 groups after simulated matches
  2. Within-group tiebreaker resolves 2/3/4-team ties correctly using the full 7-step recursive chain (H2H pts → H2H GD → H2H GS → overall GD → overall GS → fair play → FIFA ranking)
  3. Cross-group third-place ranking selects exactly 8 of 12 third-placed teams using the correct 5-step tiebreaker (points → GD → GS → fair play → FIFA ranking), with the 8th/9th boundary clearly discernible
  4. R32 matchups resolve correctly via Annex C lookup for all 495 third-place scenarios — the combination key produces the correct group winner / runner-up / third-place pairings
  5. 50K full simulation iterations complete in < 15 seconds

**Plans**: TBD

---

### Phase 9: Knockout Bracket with Annex C Routing

**Goal**: Full 104-match simulation pipeline runs correctly — `run_full_simulation()` executes group stage → Annex C → R32 → R16 → QF → SF → TPP → FINAL with correct slot resolution at every round.

**Depends on**: Phase 8

**Requirements**: BRKT-01, BRKT-02, BRKT-03, BRKT-04, BRKT-05, BRKT-06, BRKT-07, BRKT-08

**Success Criteria** (what must be TRUE):
  1. `data/bracket.json` defines all 40 knockout matches (R32→R16→QF→SF→TPP→FINAL) using `group_position` and `annex_c_third` slot types — never hardcoded team names for R32
  2. R32 simulation correctly resolves `group_position` slots (e.g. A2, B1) to actual teams from group standings, and `annex_c_third` slots via Annex C lookup
  3. R16–FINAL simulation uses the existing `source_matches` pattern, unchanged from v1.0
  4. Third-place match correctly simulated from SF losers (two losing semi-finalists)
  5. `run_full_simulation()` completes the full 48-team pipeline without errors, returning championship probabilities for all 48 teams
  6. Bracket validation passes all checks: round counts, slot types, R16 wiring per FIFA Article 12.7
  7. All existing v1.0 knockout tests continue to pass unchanged

**Plans**: TBD

---

### Phase 10: Integration, Tests & BSD Verification

**Goal**: Live 48-team predictor runs end-to-end — BSD API polls and ingests group matches, console displays group standings with third-place bubble indicator, all tests pass with updated fixtures, and real API smoke test completes successfully.

**Depends on**: Phase 9

**Requirements**: INTG-01, INTG-02, INTG-03, INTG-04, INTG-05, INTG-06, INTG-07, INTG-08, INTG-09, INTG-10

**Success Criteria** (what must be TRUE):
  1. BSD API polling detects group match results and correctly maps them to `groups.json` match slots via team-name inference
  2. Group match results stored in separate `played_groups.json` — no contamination of knockout bracket data
  3. Console output displays 12 group standings tables showing position, points, goal difference, and goals for each team
  4. Third-place bubble indicator shows the 8th vs 9th ranked third-place teams with their tiebreaker differences
  5. Console header updated for 48-team format ("48 teams, 12 groups, 40 bracket matches, 72 group matches, 495 Annex C scenarios")
  6. E2E test with mock data passes through the full 104-match pipeline
  7. Live BSD smoke test with `--once` flag returns valid 48-team predictions without errors
  8. Pre-existing `test_main_loop_runs_iterations` failure is fixed
  9. All 7 Sources of Truth (PRD, TRD, MVP, Appflow, Backend Schema, UI/UX, Implementation Plan) batch-updated for 48-team format

**Plans**: TBD

## Progress

**Execution Order:** 7 → 8 → 9 → 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. State & Elo Foundation | v1.0 | 2/2 | Complete | 2026-06-14 |
| 2. Monte Carlo Simulation | v1.0 | 2/2 | Complete | 2026-06-14 |
| 3. Live API Integration | v1.0 | 2/2 | Complete | 2026-06-14 |
| 4. Main Loop & Shutdown | v1.0 | 1/1 | Complete | 2026-06-14 |
| 5. Console Output & Formatting | v1.0 | 2/2 | Complete | 2026-06-14 |
| 6. CLI Interface & Polish | v1.0 | 2/2 | Complete | 2026-06-14 |
| 7. 48-Team Dataset & Group Definitions | v1.1 | 0/TBD | Not started | - |
| 8. Group Stage Simulation Engine | v1.1 | 0/TBD | Not started | - |
| 9. Knockout Bracket with Annex C Routing | v1.1 | 0/TBD | Not started | - |
| 10. Integration, Tests & BSD Verification | v1.1 | 0/TBD | Not started | - |
