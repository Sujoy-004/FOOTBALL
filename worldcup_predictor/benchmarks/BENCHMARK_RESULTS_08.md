# Phase 8: Group Stage Simulation Engine - Benchmark Results

**Date:** 2026-06-14
**Script:** `benchmarks/benchmark_groups.py`
**Data:** Real 48-team groups.json, teams.json, annex_c.json
**Seed:** 0 (fixed Random instance)

## Results

| Iterations | Time (s) | Match Simulations | Matches/s | Pass/Fail |
|------------|----------|-------------------|-----------|-----------|
|  1,000 | 0.754 |    72,000 |   95,490 | [PASS] |
| 10,000 | 7.920 |   720,000 |   90,914 | [PASS] |
| 50,000 | 35.524 | 3,600,000 |  101,341 | [FAIL] |

## Target Comparison

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| 50K iterations | < 15s | 35.524s | [FAIL] |
| Pipeline correctness | All standings valid | All automatic | [PASS] |

## Before/After Optimization

| Iterations | Before (s) | After (s) | Change |
|------------|------------|-----------|--------|
|  1,000 | 0.593 | 0.754 | 27.2% slower |
| 10,000 | 6.999 | 7.920 | 13.2% slower |
| 50,000 | 37.640 | 35.524 | 5.6% faster |

## Bottleneck Analysis

- **Poisson sampling:** Estimated ~70% of time
- **Standings computation:** Estimated ~20% of time
- **Annex C resolution:** Estimated ~5% of time
- **Random number generation:** Estimated ~5% of time

## Optimizations Applied

- **Local variable bindings** in benchmark_pipeline hot loop
- **Precomputed expected_goals lookup** (eliminates 7M+ function calls at 50K)
- **functools.lru_cache on expected_goals**: Tested but found ineffective (wrapper
  overhead exceeded computation cost for this float-only function)

## Notes

- Projected Phase 9 full pipeline time (72 group + 32 knockout): ~51.3s
- 60s poll interval headroom: ~9s

## Platform

- **Python:** 3.11.8 (tags/v3.11.8:db85d51, Feb  6 2024, 22:03:32) [MSC v.1937 64 bit (AMD64)]
- **Platform:** win32
