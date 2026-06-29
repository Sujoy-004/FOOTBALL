# Roadmap: Football Prediction Engine — UCL Module

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-06-29)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-4) — SHIPPED 2026-06-29</summary>

### Phase 1: UCL League Table Engine

**Goal**: Users can simulate the UCL league phase with correct 36-team Swiss-system standings — fixture validation, pot-constrained opponents, complete tiebreaker chain, qualification zones, and Monte Carlo advancement probabilities
**Depends on**: Nothing (first phase)
**Plans**: 3 plans

- [x] 01-01-PLAN.md — Fixture schedule loading and validation (data files, pot distribution validation, duplicate detection)
- [x] 01-02-PLAN.md — Match simulation + 36-team standings engine (ClubElo fetcher, football_core Poisson reuse, UCL 10-step tiebreaker chain, zone classification)
- [x] 01-03-PLAN.md — Monte Carlo simulation + advancement probabilities (N-iteration loop, zone/champion probabilities, per-team tiebreaker stat averages)

### Phase 2: UCL Knockout Phase

**Goal**: Users can simulate the complete UCL knockout pipeline — two-legged playoff (9–24), seeded R16 bracket construction with exact UEFA pairings, top-4 seeding protection, and full knockout tree (R16 → QF → SF → Final) with per-team stage probabilities
**Depends on**: Phase 1
**Plans**: 4 plans

- [x] 02-01-PLAN.md — Two-legged tie simulation + data files (`simulate_two_legged_tie()`, dedicated competition data files)
- [x] 02-02-PLAN.md — Playoff round simulation (`simulate_playoff_round()`, 8 ties from positions 9-24)
- [x] 02-03-PLAN.md — R16 bracket construction + knockout tree (`build_r16_bracket()`, `simulate_knockout_tree()`, top-4 protection)
- [x] 02-04-PLAN.md — MC integration + stage probabilities (extend `run_monte_carlo()`, D-09 stage tracking)

### Phase 3: UCL Simulation Orchestration + Display

**Goal**: Users can run complete UCL simulations from the CLI (`ucl-predict`) with configurable parameters and view formatted results — league table with qualification zones, knockout bracket with matchups, champion/top-4 odds
**Depends on**: Phase 2
**Plans**: 3 plans

- [x] 03-01-PLAN.md — CLI entry point (`ucl-predict`) + SimulationResult dataclass + conftest fixture + argparse unit tests
- [x] 03-02-PLAN.md — League table display with ANSI zone coloring + print_summary + display tests
- [x] 03-03-PLAN.md — Knockout bracket display + champion/qualification odds + JSON export + full display tests

### Phase 4: Validation & Production Readiness

**Goal**: Users can validate UCL predictions against real match results, measure accuracy (Brier, Log Loss, calibration), benchmark performance, and verify regression — the engine is proven correct before v2 features
**Depends on**: Phase 3
**Plans**: 4 plans

**Wave 1** *(parallel)*
- [x] 04-01-PLAN.md — BSD API fetcher for UCL match results
- [x] 04-03-PLAN.md — Performance benchmarking suite

**Wave 2** *(blocked on Wave 1)*
- [x] 04-02-PLAN.md — Prediction cross-check engine with accuracy metrics

**Wave 3** *(blocked on Waves 1-2)*
- [x] 04-04-PLAN.md — Regression verification, documentation, release readiness

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. UCL League Table Engine | v1.0 | 3/3 | ✓ Complete | 2026-06-27 |
| 2. UCL Knockout Phase | v1.0 | 4/4 | ✓ Complete | 2026-06-28 |
| 3. UCL Simulation Orchestration + Display | v1.0 | 3/3 | ✓ Complete | 2026-06-28 |
| 4. Validation & Production Readiness | v1.0 | 4/4 | ✓ Complete | 2026-06-29 |
