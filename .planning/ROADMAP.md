# Roadmap: Football Prediction Engine — UCL Module

## Overview

Build a UEFA Champions League competition module for the existing football prediction engine. The UCL module introduces the 2025+ Swiss-system format (36-team league phase, 8 matches per team, pot-constrained opponents), a two-legged knockout playoff (positions 9–24), a seeded R16 bracket with top-4 protection, and full Monte Carlo simulation — all without modifying `football_core`. Four phases deliver the module in dependency order: league table engine first (foundation), knockout phase second (playoff→bracket→final), orchestration+display third (CLI + formatted output), and validation last (BSD API, accuracy metrics, benchmarks, documentation).

## Phases

- [x] **Phase 1: UCL League Table Engine** — 36-team Swiss-system standings with correct tiebreaker chain, fixture validation, Monte Carlo advancement probabilities *(completed 2026-06-27)*
- [x] **Phase 2: UCL Knockout Phase** — Two-legged playoff, seeded R16 bracket, top-4 protection, full knockout tree through final *(completed 2026-06-28)*
- [ ] **Phase 3: UCL Simulation Orchestration + Display** — `ucl-predict` CLI, formatted league table and bracket display, champion/qualification odds
- [ ] **Phase 4: Validation & Production Readiness** — Live BSD API validation, accuracy metrics (Brier, Log Loss), performance benchmarking, regression verification, documentation

## Phase Details

### Phase 1: UCL League Table Engine
**Goal**: Users can simulate the UCL league phase with correct 36-team Swiss-system standings — fixture validation, pot-constrained opponents, complete tiebreaker chain, qualification zones, and Monte Carlo advancement probabilities
**Mode**: mvp
**Depends on**: Nothing (first phase)
**Requirements**: UCLT-00, UCLT-01, UCLT-02, UCLT-03, UCLT-04, UCLT-05, UCLT-06
**Success Criteria** (what must be TRUE):
  1. User can load UCL fixture schedule from data files and validate that each team has exactly 8 opponents with 2 from each pot and no duplicate matchups
  2. User can simulate the 36-team league phase using `football_core` Poisson match simulation (no core modifications), producing correct standings for all 36 teams
  3. User can verify standings use the complete UCL tiebreaker chain: GD → GS → away GS → wins → away wins → opponent points → opponent GD → opponent GS → disciplinary → UEFA coefficient (no H2H, which doesn't apply to Swiss system)
  4. User can see qualification zones: top 8 direct to R16, positions 9–24 to playoff, 25–36 eliminated
  5. User can run Monte Carlo simulation to produce per-team advancement probabilities for all 36 teams
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Fixture schedule loading and validation (data files, pot distribution validation, duplicate detection)
- [x] 01-02-PLAN.md — Match simulation + 36-team standings engine (ClubElo fetcher, football_core Poisson reuse, UCL 10-step tiebreaker chain, zone classification)
- [x] 01-03-PLAN.md — Monte Carlo simulation + advancement probabilities (N-iteration loop, zone/champion probabilities, per-team tiebreaker stat averages)

### Phase 2: UCL Knockout Phase
**Goal**: Users can simulate the complete UCL knockout pipeline — two-legged playoff (9–24), seeded R16 bracket construction with exact UEFA pairings, top-4 seeding protection, and full knockout tree (R16 → QF → SF → Final) with per-team stage probabilities
**Mode**: mvp
**Depends on**: Phase 1
**Requirements**: UCLK-01, UCLK-02, UCLK-03, UCLK-04, UCLK-05
**Success Criteria** (what must be TRUE):
  1. User can simulate two-legged playoff ties (positions 9–24) with aggregate scoring, extra time (reduced Poisson lambda), and penalty shootouts — no away goals rule
  2. User can verify the R16 bracket is correctly seeded: top 8 vs playoff winners using the exact UEFA pairing table (1/2 vs 15/18, 3/4 vs 13/20, etc.)
  3. User can confirm seeds 1–4 are protected from meeting each other until semifinals
  4. User can simulate the full knockout tree (R16 → QF → SF → Final) and get per-team stage probabilities for each round
**Plans**: 4 plans

Plans:
- [x] 02-01-PLAN.md — Two-legged tie simulation + data files (`simulate_two_legged_tie()`, dedicated competition data files)
- [x] 02-02-PLAN.md — Playoff round simulation (`simulate_playoff_round()`, 8 ties from positions 9-24)
- [x] 02-03-PLAN.md — R16 bracket construction + knockout tree (`build_r16_bracket()`, `simulate_knockout_tree()`, top-4 protection)
- [x] 02-04-PLAN.md — MC integration + stage probabilities (extend `run_monte_carlo()`, D-09 stage tracking)

### Phase 3: UCL Simulation Orchestration + Display
**Goal**: Users can run complete UCL simulations from the CLI (`ucl-predict`) with configurable parameters and view formatted results — league table with qualification zones, knockout bracket with matchups, champion/top-4 odds
**Mode**: mvp
**Depends on**: Phase 2
**Requirements**: UCLO-01, UCLO-02, UCLO-03, UCLO-04
**Success Criteria** (what must be TRUE):
  1. User can run `ucl-predict` CLI with configurable iteration count and random seed
  2. User can view a formatted 36-row league table showing position, team, points, GD, GS, and qualification zone highlighting
  3. User can view the knockout bracket with round matchups and per-team stage probabilities
  4. User can view champion probabilities, final odds, and top-4 qualification odds
**Plans**: 3 plans

Plans:
- [ ] 03-01: CLI entry point (`ucl-predict`) with argparse options for iterations, seed, and output flags
- [ ] 03-02: League table display with qualification zone formatting (36-row table, zone highlighting)
- [ ] 03-03: Knockout bracket display and odds output (matchups, stage probabilities, champion odds)

### Phase 4: Validation & Production Readiness
**Goal**: Users can validate UCL predictions against real match results, measure accuracy (Brier, Log Loss, calibration), benchmark performance, and verify regression — the engine is proven correct before v2 features
**Mode**: mvp
**Depends on**: Phase 3
**Requirements**: UCLV-01, UCLV-02, UCLV-03, UCLV-04, UCLV-05, UCLV-06
**Success Criteria** (what must be TRUE):
  1. User can run live BSD API integration to fetch real UCL match results and validate against the fixture schedule
  2. User can cross-check predictions against real completed UCL matches with accuracy metrics (Brier score, Log Loss, calibration curve)
  3. User can run performance benchmarks (simulation time vs iteration count) and identify bottlenecks
  4. User can verify regression: WC test suite green (613 pass, 1 skip), Euro sim identical
  5. User can read documentation covering architecture, known limitations, and release notes
**Plans**: 4 plans

Plans:
- [ ] 04-01: Live BSD API integration for fetching real UCL match results
- [ ] 04-02: Prediction cross-check engine with accuracy metrics (Brier, Log Loss, calibration)
- [ ] 04-03: Performance benchmarking suite
- [ ] 04-04: Regression verification, documentation, and release readiness

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. UCL League Table Engine | 3/3 | ✓ Complete | 2026-06-27 |
| 2. UCL Knockout Phase | 4/4 | ✓ Complete | 2026-06-28 |
| 3. UCL Simulation Orchestration + Display | 0/3 | Not started | - |
| 4. Validation & Production Readiness | 0/4 | Not started | - |
