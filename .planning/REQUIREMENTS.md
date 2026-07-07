# Requirements: Football Prediction Engine

**Defined:** 2026-06-27
**Core Value:** Adding a new competition requires only a new competition module — not changes to `football_core`

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### UCL League Table Engine

- [x] **UCLT-00**: Validate fixture schedule against official UCL format — verify each team has exactly 8 opponents, correct pot distribution (2 per pot), no duplicate matchups
- [x] **UCLT-01**: Simulate 36-team league phase with 8 matches per team, pot-constrained opponents (2 from each of 4 pots)
- [x] **UCLT-02**: UCL-specific tiebreaker chain — GD → GS → away GS → wins → away wins → opponent points → opponent GD → opponent GS → disciplinary → UEFA coefficient
- [x] **UCLT-03**: Rank qualification zones (top 8 direct, 9–24 playoff, 25–36 eliminated)
- [x] **UCLT-04**: Load fixture schedule from UCL data files (pre-determined draw, not dynamic pairing)
- [x] **UCLT-05**: Produce per-team advancement probabilities from Monte Carlo simulation
- [x] **UCLT-06**: Reuse `football_core` Poisson match simulation for individual UCL matches (no core modifications)

### UCL Knockout Phase

- [x] **UCLK-01**: Simulate two-legged knockout ties with aggregate scoring (no away goals rule; extra time + penalties)
- [x] **UCLK-02**: Build seeded knockout bracket — top 8 vs playoff winners with position-based pairings (1/2 vs 15/18, 3/4 vs 13/20, etc.)
- [x] **UCLK-03**: Top-4 seeding protection — seeds 1–4 cannot meet each other until semifinals
- [x] **UCLK-04**: Simulate playoff round (teams 9–24) to determine final 8 R16 entrants
- [x] **UCLK-05**: Full knockout tree from R16 → QF → SF → Final with per-team stage probabilities

### UCL Orchestration + Display

- [x] **UCLO-01**: CLI entry point (`ucl-predict`) with configurable iterations and seed
- [x] **UCLO-02**: Display league table with qualification zones after simulation
- [x] **UCLO-03**: Display knockout bracket with matchups and per-team stage probabilities
- [x] **UCLO-04**: Display champion probabilities, final odds, and top-4 qualification odds

### UCL Validation & Production Readiness

- [x] **UCLV-01**: Live BSD API integration — fetch real UCL match results and validate against fixture schedule
- [x] **UCLV-02**: Cross-check predictions against real completed UCL matches
- [x] **UCLV-03**: Accuracy metrics — Brier score, Log Loss, calibration curve for UCL predictions
- [x] **UCLV-04**: Performance benchmarking — simulation time vs iteration count, identify bottlenecks
- [x] **UCLV-05**: Regression verification — WC test suite green (603 passed, 1 skipped, 10 pre-existing errors documented), Euro sim unchanged
- [x] **UCLV-06**: Documentation and release readiness — README, ARCHITECTURE.md update, known limitations

## v2 Requirements

Requirements for UCL Prediction Quality milestone (Phases 5-11). Each maps to roadmap phases.

### Phase 5: Official Fixture Ingestion

- [ ] **UCLF-01**: BSD API as primary fixture source for simulation — fetch real UCL fixture list from BSD, not just validation data
- [ ] **UCLF-02**: Repo `fixtures.json` as fallback when BSD is unreachable or API key absent
- [ ] **UCLF-03**: FixtureProvider abstraction — `BSDFixtureProvider` and `RepoFixtureProvider` implementing a common interface
- [ ] **UCLF-04**: Both providers return identical `FixtureSchedule` schema — zero changes to simulation engine
- [ ] **UCLF-05**: Provider selection logic — auto (try BSD, fall back), repo (force repo), bsd (force BSD)
- [ ] **UCLF-06**: Cache layer for BSD fixtures — file-based TTL (1 hour), reduces API calls during iteration
- [ ] **UCLF-07**: Schema validation at provider boundary — Pydantic model validates fixtures before passing to engine
- [ ] **UCLF-08**: Remove synthetic-only execution path — always resolved through provider chain

### Phase 6: Simulation Modes

- [ ] **UCLM-01**: Simulation Mode — full hypothetical tournament from fixture source (current behavior)
- [ ] **UCLM-02**: Replay Mode — inject real completed match results, simulate remaining fixtures
- [ ] **UCLM-03**: Live Conditioning Mode — fetch real results from BSD, inject into standings, simulate forward
- [ ] **UCLM-04**: PlayedMatches override in `simulate_swiss_matches()` — use provided scores instead of simulating
- [ ] **UCLM-05**: Standings reconstruction from played results before simulating remaining matches
- [ ] **UCLM-06**: Mode selection via `--mode simulate|replay|live` CLI flag
- [ ] **UCLM-07**: Replay data file format — JSON matching BSD fetch output schema
- [ ] **UCLM-08**: Mode routing in orchestration layer, not in simulation engine

### Phase 7: Prediction Signals

- [ ] **UCLS-01**: Signal protocol/interface — each signal implements `predict(match, context) → SignalOutput`
- [ ] **UCLS-02**: SignalRegistry — plugin-style registry for adding/removing signals
- [ ] **UCLS-03**: RefinedEloSignal — ClubElo with configurable K-factor and goal-difference weighting
- [ ] **UCLS-04**: MarketOddsSignal — BSD odds with vig removal as match probabilities
- [ ] **UCLS-05**: RollingFormSignal — multi-window form features with exponential decay
- [ ] **UCLS-06**: SquadValueSignal — Transfermarkt-based strength ratio with log-transform
- [ ] **UCLS-07**: RestDaysSignal — rest days computed from fixture schedule
- [ ] **UCLS-08**: Each signal independently testable — no cross-signal imports
- [ ] **UCLS-09**: Signal execution produces per-match probability distributions (home, draw, away)

### Phase 8: Signal Blending & Market Integration

- [ ] **UCLB-01**: EnsembleEngine — weighted averaging of signal probabilities
- [ ] **UCLB-02**: Weight calibration via inverse log-loss on validation set
- [ ] **UCLB-03**: Configurable weights via JSON config file and CLI override
- [ ] **UCLB-04**: Market integration — calibration baseline (market as target)
- [ ] **UCLB-05**: Market integration — blended signal (market as one input)
- [ ] **UCLB-06**: Market integration — value detection (model - market probability delta)
- [ ] **UCLB-07**: Blended probabilities consumed by MC simulation

### Phase 9: Tournament Validation

- [x] **UCLV-07**: Tier 1 — Cross-tournament backtest: train on pre-Y data, predict tournament Y
- [x] **UCLV-08**: Tier 2 — Walk-forward match-level validation with temporal split
- [x] **UCLV-09**: Tier 3 — Replay validation: step through matchdays, inject results, score
- [x] **UCLV-10**: Tournament RPS (TRPS) metric implementation
- [x] **UCLV-11**: Full metrics suite: Log Loss (primary), TRPS (primary), ECE (primary), Brier (secondary)
- [x] **UCLV-12**: Automated validation report (JSON + CLI summary)
- [x] **UCLV-13**: Unified `ucl-predict --validate` with replay mode
- [x] **UCLV-14**: Store baseline metrics for before/after comparison with Phase 10

### Phase 10: Probability Calibration & Uncertainty

- [x] **UCLC-01**: Temperature scaling — single-parameter T minimizing log-loss on held-out data
- [x] **UCLC-02**: CalibrationPipeline — `fit()`, `transform()`, `save()`, `load()` lifecycle
- [ ] **UCLC-03**: Bayesian/Glicko-style Elo — per-team (μ, σ²) with closed-form update
- [ ] **UCLC-04**: g(RD) probability deflation when opponent uncertainty is high
- [ ] **UCLC-05**: Minimum variance floor preventing uncertainty collapse
- [x] **UCLC-06**: Confidence intervals on champion probabilities (p ± CI)
- [x] **UCLC-07**: Display calibrated probabilities with CIs in CLI output
- [x] **UCLC-08**: Re-run Phase 9 validation post-calibration for before/after comparison

### Phase 11: Explainability & Production

- [x] **UCLE-01**: Signal contribution breakdown in CLI output — "why X%?" per team
- [x] **UCLE-02**: Additive decomposition from ensemble weights
- [x] **UCLE-03**: Counterfactual analysis via `--what-if` CLI flag
- [x] **UCLE-04**: `--report` flag generating structured summary with validation metrics
- [x] **UCLE-05**: Configuration directory (`competitions/ucl/config/`) for weights, params, providers
- [x] **UCLE-06**: CLI cleanup — consistent flag naming, help text, argument validation

### Phase 12: UCL Live Monitor + WC Batch Research

#### Workstream A — UCL Live Monitor

- [ ] **UCL-LIVE-01**: State persistence for played matches, elo_applied, prediction_history across restarts
- [ ] **UCL-LIVE-02**: `competitions/ucl/src/live_state.py` — wrapper around `football_core.state` for UCL paths
- [ ] **UCL-LIVE-03**: `competitions/ucl/src/elo_updater.py` — incremental Elo updates + 24h ClubElo sync
- [ ] **UCL-LIVE-04**: `--watch` flag with configurable polling interval and graceful SIGINT shutdown
- [ ] **UCL-LIVE-05**: `_run_iteration()` extracted from existing `main()` body
- [ ] **UCL-LIVE-06**: `_historical_catch_up()` — fetch all prior finished BSD matches on first run
- [ ] **UCL-LIVE-07**: Periodic ClubElo sync (24h) with drift handling (<10 ignore, 11–30 blend, >30 overwrite)
- [ ] **UCL-LIVE-08**: Signal cache refresh + `_merge_signals_into_history()` on each poll
- [ ] **UCL-LIVE-09**: Delta display (`print_delta`), heartbeat (`print_heartbeat`), match alerts, Elo changes
- [ ] **UCL-LIVE-10**: `--once` flag for single-cycle execution
- [ ] **UCL-LIVE-11**: Mode routing — `--mode simulate` (default) single-run, `--mode live --watch` polling loop
- [ ] **UCL-LIVE-12**: Test persistence round-trip, Elo update edge cases, smoke test

#### Workstream B — WC Batch Research

- [ ] **WC-BATCH-01**: `--simulate` flag — offline simulation from data files, no API needed
- [ ] **WC-BATCH-02**: `--iterations N` / `-n` flag for iteration count override
- [ ] **WC-BATCH-03**: Mode routing — `--simulate` → batch mode; no flag → existing polling loop
- [ ] **WC-BATCH-04**: `--what-if TEAM.param=VALUE` (repeatable) — counterfactual Elo analysis
- [ ] **WC-BATCH-05**: `print_what_if_comparison()` — side-by-side baseline vs counterfactual table
- [ ] **WC-BATCH-06**: `--report FILE` — structured JSON export with full simulation snapshot
- [ ] **WC-BATCH-07**: `--show-breakdown [summary|match]` — per-signal probability contributions
- [ ] **WC-BATCH-08**: `print_signal_breakdown()` — signal_name → probability display
- [ ] **WC-BATCH-09**: `--show-ci [on|off|auto]` — Wilson confidence intervals on champion probabilities
- [ ] **WC-BATCH-10**: CI formatting in probability table (reuse `football_core.math_utils.wilson_score_ci`)
- [ ] **WC-BATCH-11**: `--validate-calibrated` — before/after calibration comparison
- [ ] **WC-BATCH-12**: `--weights K=V,K=V` — static blend weight override, skip Brier optimization
- [ ] **WC-BATCH-13**: `competitions/worldcup/benchmarks/benchmark_simulation.py`
- [ ] **WC-BATCH-14**: `tests/test_batch_mode.py` — reproducible output
- [ ] **WC-BATCH-15**: `tests/test_counterfactual.py` — Elo change shifts probs in expected direction

## v2 Deferred (Post-v2)

### UCL Differentiators (post-validation polish)

- **UCLD-01**: What-if scenario analysis (e.g., "what if Team X wins their remaining matches")
- **UCLD-02**: Path visualization (most-likely elimination path for a given team)
- **UCLD-03**: Strength-of-schedule impact reporting

### League Competitions (La Liga / Premier League)

- **LEAG-01**: Double round-robin fixture generation (circle method, ~40 lines)
- **LEAG-02**: League standings with configurable tiebreakers (H2H for La Liga, GD for PL)
- **LEAG-03**: Promotion/relegation logic (3 up, 3 down, with play-off variants)
- **LEAG-04**: European qualification placement
- **LEAG-05**: Season-long Monte Carlo simulation (38 matchdays × 20 teams = 380 matches)
- **LEAG-06**: Performance optimization for 50K+ iteration league simulation

### Euro Refactoring

- **EURO-01**: Refactor shared group/advancement logic into `football_core`
- **EURO-02**: Remove `sys.path` mutation from `competitions/euro/__init__.py`

### Packaging

- **PKG-01**: pip-installable `football-core` package with `pyproject.toml`
- **PKG-02**: Published public API with documented interface for competition modules

## Out of Scope

| Feature | Reason |
|---------|--------|
| Web UI / dashboard | Engine-only; web layer is separate project |
| Mobile app | Not relevant to engine architecture |
| Real-time live betting | Predictions are tournament-forecast, not in-play |
| ML model training pipeline | CatBoost models are consumed, not trained |
| Injury/suspension modeling | Too dynamic for Monte Carlo forecasting; relies on unavailable data |
| Transfer window modeling | Club-level only; unpredictable by nature |
| pyproject.toml / pip package | Deferred until 3 competitions are proven stable |

## Traceability

### v1 Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| UCLT-00 | Phase 1 | Completed (Plan 01) |
| UCLT-01 | Phase 1 | Completed (Plan 02) |
| UCLT-02 | Phase 1 | Completed (Plan 02) |
| UCLT-03 | Phase 1 | Completed (Plan 02) |
| UCLT-04 | Phase 1 | Completed (Plan 01) |
| UCLT-05 | Phase 1 | Completed (Plan 03) |
| UCLT-06 | Phase 1 | Completed (Plan 02) |
| UCLK-01 | Phase 2 | Completed (Plan 01) |
| UCLK-02 | Phase 2 | Completed (Plan 02) |
| UCLK-03 | Phase 2 | Completed (Plan 02) |
| UCLK-04 | Phase 2 | Completed (Plan 01) |
| UCLK-05 | Phase 2 | Completed (Plans 03, 04) |
| UCLO-01 | Phase 3 | Completed (Plan 01) |
| UCLO-02 | Phase 3 | Completed (Plan 02) |
| UCLO-03 | Phase 3 | Completed (Plan 03) |
| UCLO-04 | Phase 3 | Completed (Plan 03) |
| UCLV-01 | Phase 4 | Completed (Plan 01) |
| UCLV-02 | Phase 4 | Completed (Plan 02) |
| UCLV-03 | Phase 4 | Completed (Plan 02) |
| UCLV-04 | Phase 4 | Completed (Plan 03) |
| UCLV-05 | Phase 4 | Completed (Plan 04) |
| UCLV-06 | Phase 4 | Completed (Plan 04) |

### v2 Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| UCLF-01 | Phase 5 | Planned |
| UCLF-02 | Phase 5 | Planned |
| UCLF-03 | Phase 5 | Planned |
| UCLF-04 | Phase 5 | Planned |
| UCLF-05 | Phase 5 | Planned |
| UCLF-06 | Phase 5 | Planned |
| UCLF-07 | Phase 5 | Planned |
| UCLF-08 | Phase 5 | Planned |
| UCLM-01 | Phase 6 | Planned |
| UCLM-02 | Phase 6 | Planned |
| UCLM-03 | Phase 6 | Planned |
| UCLM-04 | Phase 6 | Planned |
| UCLM-05 | Phase 6 | Planned |
| UCLM-06 | Phase 6 | Planned |
| UCLM-07 | Phase 6 | Planned |
| UCLM-08 | Phase 6 | Planned |
| UCLS-01 | Phase 7 | Planned |
| UCLS-02 | Phase 7 | Planned |
| UCLS-03 | Phase 7 | Planned |
| UCLS-04 | Phase 7 | Planned |
| UCLS-05 | Phase 7 | Planned |
| UCLS-06 | Phase 7 | Planned |
| UCLS-07 | Phase 7 | Planned |
| UCLS-08 | Phase 7 | Planned |
| UCLS-09 | Phase 7 | Planned |
| UCLB-01 | Phase 8 | Planned |
| UCLB-02 | Phase 8 | Planned |
| UCLB-03 | Phase 8 | Planned |
| UCLB-04 | Phase 8 | Planned |
| UCLB-05 | Phase 8 | Planned |
| UCLB-06 | Phase 8 | Planned |
| UCLB-07 | Phase 8 | Planned |
| UCLV-07 | Phase 9 | Completed (Plan 03) |
| UCLV-08 | Phase 9 | Completed (Plan 02) |
| UCLV-09 | Phase 9 | Completed (Plan 02) |
| UCLV-10 | Phase 9 | Completed (Plan 01) |
| UCLV-11 | Phase 9 | Completed (Plan 01) |
| UCLV-12 | Phase 9 | Completed (Plan 03) |
| UCLV-13 | Phase 9 | Completed (Plan 03) |
| UCLV-14 | Phase 9 | Completed (Plan 03) |
| UCLC-01 | Phase 10 | Completed (Plan 01) |
| UCLC-02 | Phase 10 | Completed (Plan 01) |
| UCLC-03 | Phase 10 | Planned |
| UCLC-04 | Phase 10 | Planned |
| UCLC-05 | Phase 10 | Planned |
| UCLC-06 | Phase 10 | Completed (Plan 03) |
| UCLC-07 | Phase 10 | Completed (Plan 03) |
| UCLC-08 | Phase 10 | Completed (Plan 03) |
| UCLE-01 | Phase 11 | Completed (Plan 01) |
| UCLE-02 | Phase 11 | Completed (Plan 01) |
| UCLE-03 | Phase 11 | Completed (Plan 02) |
| UCLE-04 | Phase 11 | Completed (Plan 02) |
| UCLE-05 | Phase 11 | Completed (Plan 03) |
| UCLE-06 | Phase 11 | Completed (Plan 03) |
| UCL-LIVE-01 | Phase 12 | Planned |
| UCL-LIVE-02 | Phase 12 | Planned |
| UCL-LIVE-03 | Phase 12 | Planned |
| UCL-LIVE-04 | Phase 12 | Planned |
| UCL-LIVE-05 | Phase 12 | Planned |
| UCL-LIVE-06 | Phase 12 | Planned |
| UCL-LIVE-07 | Phase 12 | Planned |
| UCL-LIVE-08 | Phase 12 | Planned |
| UCL-LIVE-09 | Phase 12 | Planned |
| UCL-LIVE-10 | Phase 12 | Planned |
| UCL-LIVE-11 | Phase 12 | Planned |
| UCL-LIVE-12 | Phase 12 | Planned |
| WC-BATCH-01 | Phase 12 | Planned |
| WC-BATCH-02 | Phase 12 | Planned |
| WC-BATCH-03 | Phase 12 | Planned |
| WC-BATCH-04 | Phase 12 | Planned |
| WC-BATCH-05 | Phase 12 | Planned |
| WC-BATCH-06 | Phase 12 | Planned |
| WC-BATCH-07 | Phase 12 | Planned |
| WC-BATCH-08 | Phase 12 | Planned |
| WC-BATCH-09 | Phase 12 | Planned |
| WC-BATCH-10 | Phase 12 | Planned |
| WC-BATCH-11 | Phase 12 | Planned |
| WC-BATCH-12 | Phase 12 | Planned |
| WC-BATCH-13 | Phase 12 | Planned |
| WC-BATCH-14 | Phase 12 | Planned |
| WC-BATCH-15 | Phase 12 | Planned |

**Coverage:**
- v1 requirements: 22 total — Completed: 22
- v2 requirements: 85 total — Completed: 52, Planned: 33
- Mapped to phases: 85
- Unmapped: 0 ✓

---

*Requirements defined: 2026-06-27*
*Last updated: 2026-07-07 after Phase 12 planning*
