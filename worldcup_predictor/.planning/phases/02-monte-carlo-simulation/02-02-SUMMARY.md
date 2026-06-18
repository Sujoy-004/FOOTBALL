---
phase: 02-monte-carlo-simulation
plan: 02
status: complete
tests_passing: 5/5
benchmark: PASS (1.268s for 50K iterations)
implemented: 2026-06-13
---

# Phase 2, Plan 2 Summary: Performance Benchmark

## Objective

Create a standalone benchmark script that measures Monte Carlo simulation performance, confirms the 50K-iterations-under-5-seconds target, and provides a baseline for any future NumPy optimization decision.

## What Was Built

### `scripts/benchmark_simulation.py` (61 lines)

Standalone CLI script:

- **Argparse:** `--iterations` flag (default 50,000), `--help` with description
- **Data loading:** Loads real `teams.json`, `bracket.json`, `played.json` via `src.state`
- **Warmup:** 100-iteration run before timing (CPU cache + module init)
- **Timing:** `time.perf_counter()` around the main `run_simulation()` call
- **Output:** Formatted report with Iterations, Elapsed, Rate, Threshold, Status (PASS/FAIL), Champion sum
- **Exit code:** 0 on PASS, 1 on FAIL (scriptable)

## Benchmark Result

```
$ python scripts/benchmark_simulation.py
Monte Carlo Simulation Benchmark
------------------------------------------------
  Iterations:       50000
  Elapsed:          1.268s
  Rate:             39432 sims/sec
  Threshold:        5.000s
  Status:            PASS
------------------------------------------------
  Champion sum:    1.0000
```

- **50,000 iterations:** 1.268 seconds
- **Rate:** 39,432 simulations/second
- **Threshold:** 5.000 seconds
- **Status:** PASS (well under threshold)
- **Champion sum:** 1.0000 (sanity check passed)

No NumPy optimization needed — pure Python meets the 5-second target by a wide margin (3.7× headroom).

## Key Decisions Implemented

| Decision | Implementation |
|----------|---------------|
| D-11: Separate benchmark script | `scripts/benchmark_simulation.py` — developer-run, not CI |
| D-12: Benchmark output format | Iterations, elapsed, rate, PASS/FAIL with threshold |
| D-13: Performance gate | PASS — 1.268s < 5.0s, no NumPy fallback needed |
