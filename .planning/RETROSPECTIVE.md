# Retrospective

## Milestone: v1.0 — MVP

**Shipped:** 2026-06-29
**Phases:** 4 | **Plans:** 14 (UCL) / 22 (total repo)
**Timeline:** 2026-06-13 → 2026-06-29 (16 days)

### What Was Built

- **UCL League Table Engine** — 36-team Swiss-system standings with correct UCL tiebreaker chain, fixture validation, pot-constrained opponents, Monte Carlo advancement probabilities
- **UCL Knockout Phase** — Two-legged playoff (9–24), seeded R16 bracket with top-4 protection, full knockout tree with 7-stage probability tracking
- **UCL Orchestration + Display** — `ucl-predict` CLI, 5 display sections (summary, league table, playoffs, bracket, odds), JSON export
- **Validation & Production Readiness** — BSD API fetcher, shared evaluation metrics in `football_core`, Elo-based cross-check, performance benchmarks, README + ARCHITECTURE.md

### What Worked

- **Data-driven architecture**: Playoff pairings, bracket rules, and fixture schedule as JSON data files — competition structure is replaceable data, not hardcoded logic
- **Three-layer separation**: SimulationResult contract → display layer (stdlib only) → CLI orchestration — clean dependencies, D-17 enforced via static analysis
- **Rule of Two extraction**: Evaluation metrics extracted from WC to football_core when UCL became the second consumer — pattern proven correct
- **Wave-based execution**: Parallel Waves (1→3 in Phase 4) reduced total wall-clock time; early standalone plans (benchmarks, fetcher) unblocked later validation work
- **Subagent worktree parallelism**: Phase 3 executed in 16 min total (avg 5 min/plan) — 3-4× faster than Phases 1-2 — due to established patterns and parallel agent execution
- **Monitoring thought model**: checkpoint plans with human approval gates caught 0 deviations but provided confidence for autonomous execution

### What Was Inefficient

- **REQUIREMENTS.md drift**: Requirements were never updated after Phase 1 — 15/22 checkboxes were stale at milestone close. Fix: update traceability table after each phase.
- **Medium granularity phases**: Phase 4 had 4 plans (some taking only 5-6 min) — too fine-grained for MVP mode. Consider fewer, larger plans for validation/documentation phases.
- **Heterogeneous plan detail**: Detailed plans for Phases 1-2 vs. lightweight plans for Phases 3-4. The lightweight plans worked well for well-understood patterns (CLI, display) but might miss edge cases for novel subsystems.
- **Pre-existing WC errors**: 10 test_knockout.py errors from earlier repo restructure (bb25807) — these should have been fixed or documented earlier to avoid confusion at milestone close.

### Patterns Established

- **Data-driven competition structure**: Competition rules encoded as JSON data files, not Python code — makes future competitions faster to add
- **Post-aggregation MC pattern**: Collect per-iteration results in flat lists, aggregate once after loop — enables fast iteration and clean separation
- **D-17 display isolation**: Display layer imports ONLY the result contract + stdlib — verifiable via static grep; enforces architectural boundary
- **Eval extraction via verbatim copy**: When extracting shared functions, copy bodies exactly to preserve existing test regression suites
- **Standalone benchmark pattern**: Each competition gets `benchmarks/benchmark_{subsystem}.py` matching WC convention

### Key Lessons

1. **Update REQUIREMENTS.md after each phase** — prevents 15-item stale checkbox pileup at milestone close
2. **Lightweight plans work for established patterns** — CLI, display, and docs plans can skip detailed task breakdown if the pattern is well-understood
3. **Cache warm for benchmarks matters** — first run was 74.9s vs 39.3s warm for 50K; always note cold vs warm state
4. **Windows encoding is persistent challenge** — Unicode arrows (→) fail in cp1252 terminal; use ASCII alternatives in display functions

### Cross-Milestone Trends

(First milestone — no trends yet)
