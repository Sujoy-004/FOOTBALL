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
<details>
<summary>🔜 v2 Prediction Quality (Phases 5-11) — PLANNED</summary>

### Phase 5: Official Fixture Ingestion

**Goal**: Replace synthetic-only execution path with FixtureProvider abstraction — BSD as primary fixture source, repo JSON as fallback. Remove synthetic-only execution path.
**Depends on**: Phase 4 (BSD fetcher for validation, now repurposed for simulation)
**Plans**: 3 plans

- [ ] 05-01-PLAN.md — Interface contracts: FixtureProvider Protocol, FixtureSchedule schema, validation wiring + test scaffold
- [ ] 05-02-PLAN.md — Provider implementations: BSDFixtureProvider (BSD + cache) + RepoFixtureProvider (repo JSON) + provider tests
- [ ] 05-03-PLAN.md — CLI integration: --fixture-source flag, provider resolution chain, remove synthetic path

### Phase 6: Simulation Modes

**Goal**: Three-mode simulator — Simulation (full synthetic), Replay (inject real results), Live Conditioning (fetch real completed results, simulate forward). Unlocks historical backtesting and mid-tournament predictions.
**Depends on**: Phase 5 (FixtureProvider abstraction)
**Plans**: 3 plans

- [x] 06-01-PLAN.md — Engine: PlayedMatches injection in simulate_league_matches() + UCL pipeline threading (Wave 1)
- [x] 06-02-PLAN.md — MatchResultProvider + run_monte_carlo/build_simulation_result threading (Wave 1)
- [x] 06-03-PLAN.md — CLI --mode/--replay-data flags + mode routing + tests (Wave 2)
**Status**: Complete ✓ (2026-07-01)

### Phase 7: Prediction Signals

**Goal**: Multi-signal architecture — refined Elo, market odds, rolling form, squad value, rest days. SignalRegistry for plugin-style signal management. Each signal independently testable.
**Depends on**: Phase 5 (fixture source for signal data; no hard dependency, but logical order)
**Plans**: 3 plans

**Wave 1** *(parallel)*
- [x] 07-01-PLAN.md — Signal Protocol + SignalOutput + PredictionContext + SignalRegistry (foundation)
- [x] 07-02-PLAN.md — RefinedEloSignal + MarketOddsSignal (core signals)

**Wave 2** *(blocked on Wave 1)*
- [x] 07-03-PLAN.md — RollingFormSignal + SquadValueSignal + RestDaysSignal (advanced signals)
**Status**: Complete

### Phase 8: Signal Blending & Market Integration

**Goal**: Weighted ensemble with inverse-log-loss weights. Market odds as calibration baseline and blended signal. EnsembleEngine architecture.
**Depends on**: Phase 7 (signals to blend)
**Plans**: 3 plans

**Wave 1** *(foundation)*
- [x] 08-01-PLAN.md — BlendedPrediction dataclass + EnsembleEngine class + tests (UCLB-01)

**Wave 2** *(parallel, blocked on Wave 1)*
- [x] 08-02-PLAN.md — Calibration orchestration + signal_weights.json + tests (UCLB-01, UCLB-03)
- [x] 08-03-PLAN.md — CLI flags + display breakdown + value detection + tests (UCLB-01, UCLB-02, UCLB-03)
**Status**: Complete ✓ (2026-07-03)

### Phase 9: Tournament Validation

**Goal**: Three-tier validation framework — cross-tournament backtest, walk-forward match-level, replay validation. TRPS, Log Loss, ECE as primary metrics. Establishes uncalibrated baseline before calibration (Phase 10).
**Depends on**: Phase 6 (replay mode for Tier 3), Phase 8 (blended signals to validate)
**Plans**: 3 plans

**Wave 1** *(foundation)*
- [x] 09-01-PLAN.md — Core metrics: TRPS + multi-outcome evaluation (UCLV-10, UCLV-11)

**Wave 2** *(blocked on Wave 1)*
- [x] 09-02-PLAN.md — Walk-forward + replay validation framework (UCLV-08, UCLV-09)

**Wave 3** *(blocked on Wave 2)*
- [x] 09-03-PLAN.md — Cross-tournament backtest + baseline recording + CLI (UCLV-07, UCLV-12, UCLV-13, UCLV-14)
**Status**: Complete ✓ (2026-07-03)

### Phase 10: Probability Calibration & Uncertainty

**Goal**: Temperature scaling for match-level calibration. Bayesian/Glicko-style Elo with (μ, σ²) per team. Confidence intervals on champion probabilities. Improves on baseline established by Phase 9.
**Depends on**: Phase 7 (signals), Phase 8 (blended probabilities to calibrate)
**Plans**: 3 plans

**Wave 1** *(foundation)*
- [x] 10-01-PLAN.md — Calibration Pipeline: temperature scaling + CalibrationPipeline class (UCLC-01, UCLC-02)
- [x] 10-02-PLAN.md — Bayesian/Glicko-style Elo: (μ, σ²) per team + g(RD) deflation + variance floor (UCLC-03, UCLC-04, UCLC-05)

**Wave 2** *(blocked on Wave 1)*
- [x] 10-03-PLAN.md — CI propagation + CLI display + before/after validation comparison (UCLC-06, UCLC-07, UCLC-08)
**Status**: Complete ✓ (2026-07-04)

### Phase 11: Explainability & Production

**Goal**: Prediction breakdown (signal contribution), counterfactual analysis, reporting improvements, production architecture refinements (config management, CLI cleanup).
**Depends on**: Phases 5-10 (all prerequisite)
**Plans**: 3 plans

**Wave 1** *(foundation)*
- [x] 11-01-PLAN.md — Signal Contribution Breakdown: always-on per-signal decomposition in CLI output (UCLE-01, UCLE-02)

**Wave 2** *(parallel, blocked on Wave 1)*
- [x] 11-02-PLAN.md — Counterfactual Analysis & Reporting: --what-if flag, --report flag, side-by-side comparison (UCLE-03, UCLE-04)
- [x] 11-03-PLAN.md — Production Architecture Refinements: CLI cleanup, --verbose, centralized argument validation, config standardization (UCLE-05, UCLE-06)
**Status**: Complete ✓ (2026-07-03)

### Phase 12: UCL Live Monitor + WC Batch Research

**Goal**: Two parallel workstreams cross-pollinating features between competition modules. UCL gets the continuous polling, state persistence, and incremental Elo that WorldCup already has. WorldCup gets the offline simulation, counterfactual analysis, structured reports, and signal breakdown that UCL already has.
**Depends on**: Phase 6 (UCL simulation modes for workstream A). Workstream B has no phase dependency.
**Plans**: 10 plans (5 UCL + 5 WC) across 5 waves

**Wave 1** *(foundation — parallel)*:
- [ ] 12-01-PLAN.md — live_state.py: UCL state persistence wrapper (UCL-LIVE-01, UCL-LIVE-02)
- [ ] 12-06-PLAN.md — --simulate mode: offline batch routing (WC-BATCH-01, WC-BATCH-02, WC-BATCH-03)

**Wave 2** *(parallel within workstreams)*:
- [ ] 12-02-PLAN.md — elo_updater.py: incremental Elo + 24h ClubElo sync (UCL-LIVE-03, UCL-LIVE-07)
- [ ] 12-04-PLAN.md — display + signal cache: delta, heartbeat, alerts, cache refresh (UCL-LIVE-08, UCL-LIVE-09)
- [ ] 12-07-PLAN.md — --what-if: counterfactual JSON analysis (WC-BATCH-04, WC-BATCH-05)

**Wave 3** *(serial, depends on wave 2)*:
- [ ] 12-03-PLAN.md — polling loop: --watch, _run_iteration, _historical_catch_up (UCL-LIVE-04, UCL-LIVE-05, UCL-LIVE-06, UCL-LIVE-10, UCL-LIVE-11)
- [ ] 12-08-PLAN.md — report + breakdown + CI: --report, --show-breakdown, --show-ci (WC-BATCH-06, WC-BATCH-07, WC-BATCH-08, WC-BATCH-09, WC-BATCH-10)

**Wave 4** *(testing + advanced features)*:
- [ ] 12-05-PLAN.md — UCL: test_live_state, test_elo_updater, test_live_smoke (UCL-LIVE-12)
- [ ] 12-09-PLAN.md — WC: --validate-calibrated, --weights (WC-BATCH-11, WC-BATCH-12)

**Wave 5** *(WC final)*:
- [ ] 12-10-PLAN.md — WC: benchmarks + test_batch_mode + test_counterfactual (WC-BATCH-13, WC-BATCH-14, WC-BATCH-15)

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. UCL League Table Engine | v1.0 | 3/3 | ✓ Complete | 2026-06-27 |
| 2. UCL Knockout Phase | v1.0 | 4/4 | ✓ Complete | 2026-06-28 |
| 3. UCL Simulation Orchestration + Display | v1.0 | 3/3 | ✓ Complete | 2026-06-28 |
| 4. Validation & Production Readiness | v1.0 | 4/4 | ✓ Complete | 2026-06-29 |
| 5. Official Fixture Ingestion | v2.0 | 3/3 | ✓ Complete | 2026-06-30 |
| 6. Simulation Modes | v2.0 | 3/3 | ✓ Complete | 2026-07-01 |
| 7. Prediction Signals | v2.0 | 3/3 | ✓ Complete | 2026-07-01 |
| 8. Signal Blending & Market Integration | v2.0 | 3/3 | ✓ Complete | 2026-07-03 |
| 9. Tournament Validation | v2.0 | 3/3 | ✓ Complete | 2026-07-03 |
| 10. Probability Calibration & Uncertainty | v2.0 | 3/3 | ✓ Complete | 2026-07-04 |
| 11. Explainability & Production | v2.0 | 3/3 | ✓ Complete | 2026-07-03 |
| 12. UCL Live Monitor + WC Batch Research | v2.0 | 0/10 | 🟡 Planned | — |
