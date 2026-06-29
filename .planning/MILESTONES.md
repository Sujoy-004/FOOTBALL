# Milestones

## v1.0 MVP

**Shipped:** 2026-06-29
**Phases:** 4 | **Plans:** 14
**Requirements:** 22/22 completed

**Delivered:** UEFA Champions League module with Swiss-system league phase, knockout bracket, Monte Carlo simulation, BSD API validation, and regression verification — all reusing `football_core` with zero modifications.

**Key accomplishments:**
- 36-team Swiss-system standings with correct UCL tiebreaker chain and pot-constrained fixtures
- Full knockout pipeline: two-legged playoff, seeded R16 bracket with top-4 protection, tree through final
- `ucl-predict` CLI with 5 display sections and JSON export, all stdlib-only
- Shared evaluation metrics extracted to `football_core` (Brier, Log Loss, calibration)
- BSD API fetcher, Elo-based prediction cross-check, performance benchmarks (39s at 50K)
- README + ARCHITECTURE.md documentation

**Known deferred items at close:** 10 pre-existing WC test_knockout.py errors (documented, human-approved)
