# ADR-002: Synthetic Schedules for Development, Official Schedules for Validation

**Status:** Accepted  
**Date:** 2026-06-28  
**Applies to:** All competitions (UCL, World Cup, Euro, leagues)

## Context

Phase 1 of the UCL module used a synthetically generated fixture schedule (randomized greedy + BFS, seed 737) because no official UEFA 2025/26 fixture list was available. An audit quantified the impact:

- Schedule-induced points σ: 0.93 per team (avg), max 1.20
- ~12% additional variance on top of Poisson MC noise
- ~1–2% zone misclassification rate at playoff boundaries
- << 1 position shift for most teams

This raised a general question: when are synthetic schedules acceptable?

## Decision

Synthetic schedules are acceptable for:

1. **Architecture development** — proving the competition module structure, data flows, and core integrations
2. **Engine evolution** — developing simulation logic, tiebreaker chains, MC aggregation, and output formatting
3. **Regression testing** — verifying that code changes don't alter results for a fixed schedule

Official competition schedules become mandatory before:

1. **Validation** — any claim about prediction accuracy, calibration, or model quality
2. **Benchmarking** — comparing performance across seasons, competitions, or model variants
3. **Public reporting** — any output presented as representative of real competition outcomes

## Rationale

- Synthetic schedules preserve the structural properties (correct pot assignments, match counts per opponent, no self-plays) while being reproducible and free
- The ~12% added variance is acceptable for engine development but would confound accuracy measurements
- This rule is competition-agnostic: every module follows the same standard

## Consequences

Positive:
- Development is unblocked for any competition, regardless of official schedule availability
- Clear gate criteria for when synthetic→official swap is required

Negative:
- Teams adopting the engine must source official schedules before validation
- Two code paths per competition (synthetic generation + official data ingestion) may be needed

## Related

- ADR-001: (placeholder for future cross-reference)
- Phase 1 audit: `.planning/phases/01-ucl-league-table-engine/01-VERIFICATION.md`
- Schedule variance analysis: `competitions/ucl/tests/test_schedule_audit.py`
