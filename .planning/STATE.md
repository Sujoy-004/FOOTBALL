# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-27)

**Core value:** Adding a new competition requires only a new competition module — not changes to `football_core`
**Current focus:** UCL League Table Engine

## Current Position

Phase: 1 of 4 (UCL League Table Engine)
Plan: 3 of 3 in current phase
Status: Complete
Last activity: 2026-06-27 — Completed Plan 03: Monte Carlo simulation engine with 10K iteration verification

Progress: [########            ] 40%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 29 min
- Total execution time: 87 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-ucl-league-table-engine | 3 | 87 min | 29 min |

**Recent Trend:**
- Last 5 plans:
  1. 01-ucl-league-table-engine/01: 40 min (module scaffold, fixture data, validation)
  2. 01-ucl-league-table-engine/02: 32 min (ClubElo fetcher, match sim, 10-step tiebreaker standings)
  3. 01-ucl-league-table-engine/03: 15 min (MC simulation engine)
- Trend: Steady velocity, faster as modules build on prior work

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- (Roadmap): UCL-first build order confirmed — league table engine → knockout → orchestration → differentiators
- (Roadmap): 4 phases at standard granularity — natural groups, no padding
- (Roadmap): All 22 v1 requirements covered across 4 phases
- (Phase 1): ClubElo as Elo source for UCL teams — fetch-once, cache, snapshot reproducibility
- (Phase 1): MC output = zone probabilities + champion + all tiebreaker-chain averages
- (Phase 1/Plan 02): Single-request date-based ClubElo fetch instead of 36 individual requests
- (Phase 1/Plan 02): logging.warning() on ClubElo fallback for silent-failure prevention
- (Phase 1/Plan 02): Opponent stats from pre-tiebreak raw aggregates, not post-rank values
- (Phase 1/Plan 02): Defensive copy pattern to prevent input mutation
- (Phase 1/Plan 02): No H2H tiebreaker confirmed for Swiss system
- (Phase 1/Plan 03): Post-aggregation pattern — collect per-iteration results in flat lists, aggregate once after loop
- (Phase 1/Plan 03): Matchup lambdas precomputed once before iteration loop for ~2x performance gain
- (Phase 1/Plan 03): aggregate_mc_results() separated for isolated unit testing without running simulation

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-06-27
Stopped at: Completed 01-03-PLAN.md (Monte Carlo simulation engine with 10K verification)
Resume file: .planning/phases/01-ucl-league-table-engine/01-03-SUMMARY.md
