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

## v2.0 Prediction Quality

**Planned:** 2026-06-29
**Phases:** 7 | **Plans:** 0/?
**Requirements:** 0/? completed

**Goal:** Transform the UCL module from a synthetic, Elo-only prototype into a production-quality prediction engine with real fixtures, multi-signal ensemble, calibrated probabilities, uncertainty quantification, rigorous tournament-level validation, and explainable output.

**Phases:**

| # | Phase | Depends On | Est. Effort | Status |
|---|-------|------------|-------------|--------|
| 5 | Official Fixture Ingestion | Phase 4 | 1-2 pw | Planned |
| 6 | Simulation Modes | Phase 5 | 1-2 pw | Planned |
| 7 | Prediction Signals | Phase 5 | 2-3 pw | Planned |
| 8 | Signal Blending & Market Integration | Phase 7 | 1-2 pw | Planned |
| 9 | Tournament Validation | Phases 6, 8 | 2-3 pw | Planned |
| 10 | Probability Calibration & Uncertainty | Phases 7, 8 | 2-3 pw | Planned |
| 11 | Explainability & Production | Phases 5-10 | 2-3 pw | Planned |

**Estimated cumulative effort:** 11-18 person-weeks
**Key dependency chain:** Phase 5 → Phase 6 → Phase 9, Phase 5 → Phase 7 → Phase 8 → Phase 9, Phase 5 → Phase 7 → Phase 8 → Phase 10
**Parallel tracks:** After Phase 5, Phases 6 and 7 are independent. After Phase 8, Phases 9 and 10 are independent — can run in parallel.
