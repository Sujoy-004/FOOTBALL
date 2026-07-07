---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: milestone
status: executing
stopped_at: Phase 12 context gathered
last_updated: "2026-07-07T18:30:00.000Z"
progress:
  total_phases: 12
  completed_phases: 11
  total_plans: 66
  completed_plans: 32
  percent: 92
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-07 after Phase 12 planning)

**Core value:** Adding a new competition requires only a new competition module — not changes to `football_core`
**Current focus:** Phase 12 — UCL Live Monitor + WC Batch Research

## Current Position

Milestone: v2.0 — UCL Prediction Quality + Cross-Platform Parity
Phase: 12 — PLANNED
Plans: 34 tasks across 2 parallel workstreams (A: 19 UCL, B: 15 WC)
Status: Planned — see `.planning/phases/12-ucl-live-wc-batch/PLAN.md`

### Changes Made (2026-07-03 execution)

**Phase 9 — Tournament Validation:**

- 09-01: TRPS + multi-class evaluation metrics in football_core/evaluation.py
- 09-02: ValidationSuite class with Tier 2 (walk-forward) + Tier 3 (replay validation)
- 09-03: Tier 1 (cross-tournament backtest) + run_all() + save_baseline() + CLI --tier flag

**Key outcomes:**

- TRPS implemented per Ekstrøm et al. (2021) with optional rank weighting — primary tournament-level metric
- Three-tier validation framework: cross-tournament (TRPS + champion accuracy + stage accuracy), walk-forward (log_loss, brier, ece), replay (calibration ECE)
- ValidationSuite class orchestrates all three tiers with ValidationResult dataclass
- Combined validation report (run_all) produces D-04 structured dict with match-level, tournament-level, and calibration sections
- Baseline recording at competitions/ucl/data/baseline_uncalibrated.json for Phase 10 before/after comparison
- CLI --validate and --tier flags fully integrated

**Phase 10 — Probability Calibration & Uncertainty:**

- [EXECUTED] 10-01: Temperature scaling pipeline — Brent's method log-loss minimization + CalibrationPipeline class with fit/transform/save/load lifecycle + --calibrate-temp CLI + prediction-time calibration loading
- 10-02: Bayesian/Glicko-style Elo — (μ, σ²) per team via Glicko-1 closed-form updates + g(RD) deflation + min variance floor + MC rating sampling
- 10-03: Bootstrap CI computation on champion probabilities + --calibrated/--show-ci/--use-glicko CLI flags + before/after validation comparison

**Key outcomes (10-01):**

- `temperature_scale()` — Simplex temperature scaling with identity at T=1.0, flood protection, all edge cases
- `_brent_minimize()` — Pure-Python Brent's method with parabolic interpolation + golden-section fallback
- `CalibrationPipeline` — Full lifecycle class with fit/transform/predict/save/load in football_core/blender.py
- `MatchOutcome` — Dataclass with result (1.0/0.5/0.0) and outcome_index (0/1/2) in evaluation.py
- `--calibrate-temp FILE` — CLI flag for offline temperature fitting on replay data
- `calibration.json` — Config file with α=1.0 default, updated after fitting
- Prediction-time application — Calibration loaded and applied to blended predictions when config exists
- 52 tests — All passing, covering identity, flatten/sharpen, save/load, error handling

**Phase 11 — Explainability & Production:**

- [EXECUTED] 11-01: Signal Contribution Breakdown — always-on per-signal decomposition in CLI output
- [EXECUTED] 11-02: Counterfactual Analysis & Reporting — --what-if flag, --report flag, side-by-side comparison
- [EXECUTED] 11-03: Windows Printing & Output Hardening — UTF-8 mode, display hardening, ASCII-compatibility tests

**Key outcomes:**

- Signal contribution breakdown (always-on) using additive decomposition from ensemble weights per D-01
- Counterfactual analysis via --what-if with side-by-side comparison display per D-02
- Structured reporting via --report matching RESPONSE.md pattern per D-03
- Config directory standardization, --verbose, centralized argument validation per D-04
- CLI flags: --what-if, --report, --verbose, --tier
- Windows UTF-8 mode via `_ensure_utf8_mode()` — stdout/stderr reconfigured to UTF-8
- 6 display functions hardened with `_require()` None guards and `.get()` fallbacks
- ASCII-compatibility test suite (7 tests) verifying all output is pure ASCII
- All plans in 2 waves: Wave 1 (11-01 foundation), Wave 2 (11-02 + 11-03 parallel)
- All 32 plans (v1.0 + v2.0) executed — complete project milestone

## Performance Metrics

**Velocity:**

- Total plans completed (v1.0): 22
- Total plans completed (v2.0 plans): 13 (Phase 9: 3, Phase 10: 3, Phase 11: 3, Phase 10-03: 1, Phase 11-01: 1, Phase 11-02: 2)
- Total plans planned (v2.0): 32
- Average duration: 15 min
- Total execution time: 386 min

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- (v2 Roadmap): 7 phases at standard granularity — natural groups of dependent research topics
- (v2 Roadmap): 11 research topics consolidated into 7 implementation phases to avoid overhead
- (v2 Roadmap): Phase order follows dependency chain — fixtures → modes → signals → blending → validation (baseline) → calibration (improvement) → production
- (v2 Refinement): Validation moved before calibration — establishes uncalibrated baseline for objective before/after comparison
- (v2 Refinement): `football_core` restriction removed — generic, competition-agnostic functionality belongs in football_core
- (Phase 5, D-01): FixtureProvider abstraction with BSD primary, repo fallback
- (Phase 5, D-03): Auto-provider selection — try BSD, fall back to repo on failure
- (Phase 5, D-05): File-based TTL cache for BSD fixtures (1-hour)
- (Phase 5, D-06): Pydantic schema validation at provider boundary
- (Phase 6, D-01): Three-mode architecture — simulate, replay, live
- (Phase 6, D-02): PlayedMatches dict override pattern (matching WC)
- (Phase 6, D-05): Mode routing in orchestration layer, not engine
- (Phase 7, D-01): Signal protocol — each signal is standalone, independently testable
- (Phase 7, D-02): SignalRegistry plugin pattern
- (Phase 7, D-03): Implementation order: refined Elo → market odds → form → squad value → rest days
- (Phase 8, D-01): Weighted averaging (inverse log-loss weights) as primary method
- (Phase 8, D-03): Weight calibration on held-out season
- (Phase 8, D-04): 3-tier market integration — baseline → blended → value detection
- (Phase 9, D-01): Three-tier validation — cross-tournament, walk-forward, replay
- (Phase 9, D-02): TRPS primary tournament-level metric, weighted per Ekstrøm et al. (2021)
- (Phase 9, D-03): Primary metrics: Log Loss, TRPS, ECE. Secondary: Brier, champion prob, stage prob
- (Phase 9, D-04): Structured validation report (JSON + CLI summary)
- (Phase 9, D-05): Validation results recorded as uncalibrated baseline for Phase 10 comparison
- (Phase 9, D-06): ucl-predict --validate --tier {cross-tournament|walk-forward|replay|all} integration
- (Phase 10, D-01): Three-tier validation — cross-tournament, walk-forward, replay
- (Phase 10, D-02): Temperature scaling as primary calibrator (single T, robust @ ~144 matches)
- (Phase 10, D-03): CalibrationPipeline lifecycle — fit(), transform(), save(), load()
- (Phase 10, D-04): Glicko-1 closed-form updates with min variance floor
- (Phase 10, D-05): Bootstrap CIs on champion probabilities (percentile method, 1000 resamples)
- (Phase 10, D-06): Three plans: calibration → Glicko → display/comparison
- (Phase 10, D-07): --calibrated / --show-ci / --use-glicko / --validate-calibrated CLI flags
- (Phase 10, D-08): Normal-approximation bootstrap (rng.gauss per resample) — 3 OOM faster than Bernoulli per-resample
- (Phase 10, D-09): Wilson score interval for small-sample CIs (0 < champion_count < 5) — closed-form, no external deps
- (Phase 10, D-10): uncertainty_contribution = full CI width when using_glicko=True — integrates match randomness + rating uncertainty
- (Phase 11, D-01): Tiered explainability — signal breakdown (always-on) + counterfactual (on-demand)
- (Phase 12, D-01): Two independent workstreams in one phase — UCL Live Monitor + WC Batch Research. Zero file overlap, parallel execution.
- (Phase 12, D-02): UCL Live Monitor reuses `football_core.state` for persistence (already dual-proven by WC + UCL via Phase 4 validation fetcher). No new persistence code needed.
- (Phase 12, D-03): WC Batch Research reuses existing `run_full_simulation()` — it already accepts `blend_params`, `xg_overrides`, and `seed`. No engine changes needed.
- (Phase 12, D-04): Signal breakdown in WC reuses `_gather_signal_data()` which already produces per-match signal dicts. Only missing is the display function.
- (Phase 12, D-05): CI display in WC reuses `football_core.math_utils.wilson_score_ci` which WC `output.py` already imports. Just needs formatting.
- (Phase 12, D-06): `--weights` in WC skips Brier-optimized blending (calibrate_and_blend) and passes static weights to bled_predictions. No engine modification — blender.py already accepts parameters independently.

### Pending Todos

- [x] Plan Phase 9 (Tournament Validation) ✓ Complete
- [x] Execute Phase 9 (Tournament Validation) ✓ Complete
- [x] Plan Phase 10 (Calibration & Uncertainty) ✓ Complete
- [x] Execute Phase 10 Plan 01 (Temperature Scaling) ✓ Complete
- [x] Execute Phase 10 Plan 02 (Glicko Elo) ✓ Complete
- [x] Execute Phase 10 Plan 03 (Bootstrap CI & Display) ✓ Complete
- [x] Plan Phase 11 (Explainability & Production) ✓ Complete
- [x] Execute Phase 11 Plan 01 (Signal Contribution Breakdown) ✓ Complete
- [x] Execute Phase 11 Plan 02 (Counterfactual Analysis & Reporting) ✓ Complete
- [x] Execute Phase 11 Plan 03 (Windows Printing & Output Hardening) ✓ Complete
- [ ] Plan Phase 12 (UCL Live Monitor + WC Batch Research) ✓ Complete
- [ ] Execute Phase 12 — 34 tasks across 2 parallel workstreams

### Blockers/Concerns

- BSD API may require paid tier for 2025/26 UCL fixtures (league_id=7 may not return future fixtures) — Phase 5 risk
- No multi-season UCL data currently collected — Tier 1 cross-tournament backtest requires sourcing historical data for meaningful results
- Temperature scaling calibration data limited to ~1 season — Phase 10 risk
- UCL Live Monitor workstream A requires Phase 6 (`--mode live`, `BSDMatchResultProvider`) — already complete ✓
- UCL `--watch` mode may hit BSD API rate limits at default 60s polling — mitigable with `--poll-interval` flag
- WC `--simulate` mode may expose stale data file issues if `teams.json` hasn't been synced recently — add staleness warning

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v1.0 deferred | 10 pre-existing WC test_knockout.py errors | documented, human-approved | v1.0 close |
| v2 scope | xG model (R-03 medium-term signal) | deferred from Phase 7 | v2 planning |
| v2 scope | Injury/lineup flags (R-03 long-term signal) | deferred from Phase 7 | v2 planning |
| v2 scope | Stacked meta-learner (R-04 upgrade) | deferred until 5+ seasons of data | v2 planning |
| v2 scope | Isotonic regression (R-05 upgrade) | deferred until >500 calibration samples | v2 planning |
| v2 scope | Hierarchical Bayesian Poisson (R-06) | deferred until match database mature | v2 planning |
| v2 scope | SHAP analysis (R-10 Tier 2) | deferred; weighted ensemble provides sufficient explanation | v2 planning |

## Session Continuity

Last session: 2026-07-07
Stopped at: Phase 12 planning — complete
Next: Phase 12 — UCL Live Monitor + WC Batch Research execution
Workstream A (UCL): Create live_state.py → elo_updater.py → wire polling loop → display → tests
Workstream B (WC): Create --simulate mode → --what-if → --report → --show-breakdown → --show-ci → --validate-calibrated → --weights → benchmarks → tests
Parallel execution: Both workstreams can run simultaneously with zero file contention
