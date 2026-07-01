---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: UCL Prediction Quality
status: executing
stopped_at: Phase 7 complete — all 3 plans executed. Ready for Phase 8.
last_updated: "2026-07-01T12:00:00.000Z"
progress:
  total_phases: 11
  completed_phases: 7
  total_plans: 23
  completed_plans: 23
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-29 after v2.0 planning)

**Core value:** Adding a new competition requires only a new competition module — not changes to `football_core`
**Current focus:** Phase 08 — Signal Blending & Market Integration

## Current Position

Milestone: v2.0 — UCL Prediction Quality
Phase: 07 — Complete
Plans: 3 of 3 (complete)
Status: Phase 7 executed — all 5 signals implemented and tested

### Changes Made (2026-07-01 execution)

**D-07 (signal code location):** Added `decisions: [D-07]` to all 3 plan frontmatter. Plans already conform with signals in `football_core/signals/`.

**D-08 (SignalRegistry.evaluate()):** Updated 07-01-PLAN.md:

- Added `evaluate()` method to SignalRegistry — iterates registered signals, catches exceptions per signal, returns uniform (1/3, 1/3, 1/3) for failures
- Added 4 new test cases (evaluate_returns_dict, evaluate_values_are_signal_output, evaluate_failing_signal_returns_uniform, evaluate_failing_signal_does_not_affect_others)
- Added T-07-07 threat: DoS via broken signal mitigated by per-signal exception catching
- Added `decisions: [D-07, D-08]` to frontmatter

**D-09 (RollingFormSignal uses MatchResultProvider):** Updated 07-03-PLAN.md:

- Defined `MatchResultProvider` Protocol in `football_core/result_provider.py` with `@runtime_checkable` and `get_team_results()` method
- Updated `RollingFormSignal.__init__()` to require a `MatchResultProvider` parameter instead of reading `context.played_results`
- Replaced `sample_played_results` conftest fixture with `sample_match_result_provider` and `empty_result_provider` fixtures using `_MockMatchResultProvider` stub
- Updated test methods to use provider-based data access
- Added `decisions: [D-07, D-09]` to frontmatter

**Cross-cutting:** Updated 07-VALIDATION.md with D-08 and D-09 verification entries. Updated 07-01 must_haves with result_provider.py artifact.

Progress: [######################--] 55% (5 completed phases, 2 planned, 4 remaining)

## Performance Metrics

**Velocity:**

- Total plans completed (v1.0): 22
- Average duration: 16 min
- Total execution time: 351 min

**By Phase (v1.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-ucl-league-table-engine | 3 | 87 min | 29 min |
| 02-ucl-knockout-phase | 4 | 115 min | 29 min |
| 03-ucl-orchestration-display | 3 | 16 min | 5 min |
| 04-validation-production-readiness | 4 | 78 min | 19.5 min |

**Recent Trend:**

- Last 5 plans (v1.0):
   1. 03-01: 8 min (CLI entry point + SimulationResult dataclass)
   2. 03-02: 2 min (league table display + ANSI zone coloring)
   3. 03-03: 6 min (bracket display + odds + JSON export)
   4. 04-01: 5 min (BSB API fetcher + tests)
   5. 04-02: 18 min (evaluation extraction + validation cross-check)
   6. 04-03: 9 min (benchmark script + run)
   7. 04-04: 6 min (documentation + regression verification)

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
- (Phase 9, D-01): Temperature scaling over isotonic (limited data)
- (Phase 9, D-04): Bayesian Elo (Glicko-style) with (μ, σ²) per team
- (Phase 10, D-01): Three-tier validation — cross-tournament, walk-forward, replay
- (Phase 11, D-01): Tiered explainability — signal breakdown (always-on) + counterfactual (on-demand)

### Pending Todos

- Plan and execute Phase 6 (Simulation Modes)

### Blockers/Concerns

- BSD API may require paid tier for 2025/26 UCL fixtures (league_id=7 may not return future fixtures) — Phase 5 risk
- No multi-season UCL data currently collected — Phase 10 (cross-tournament backtest) requires sourcing historical data
- Temperature scaling calibration data limited to ~1 season — Phase 9 risk

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

Last session: 2026-07-01
Stopped at: Session resumed, proceeding to plan Phase 6 (Simulation Modes)
