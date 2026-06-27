---
phase: 01-ucl-league-table-engine
plan: 03
subsystem: simulation
tags: ['monte-carlo', 'ucl', 'league-phase', 'poisson-simulation', 'probability-agg']
requires:
  - phase: 01-02
    provides: Swiss match simulation, 10-step tiebreaker standings
provides:
  - N-iteration Monte Carlo simulation loop (default 10,000)
  - Per-team zone probabilities (top_8, playoff, eliminated)
  - Per-team champion probability
  - Per-team tiebreaker stat averages (pts, gd, gs, away_gs, wins, away_wins, position)
  - Isolated aggregation function for testability
  - Deterministic seeding for reproducible results
affects: [02-visualization, 03-analysis]
tech-stack:
  added: []
  patterns:
    - Post-aggregation pattern — collect per-iteration positions/stats, aggregate once after loop
    - Separated aggregation function for unit testing without running simulation
    - Precomputed matchup lambdas outside the loop (Pitfall 4 avoidance)
key-files:
  created:
    - competitions/ucl/src/simulation.py
    - competitions/ucl/tests/test_monte_carlo.py
  modified:
    - competitions/ucl/src/__init__.py
    - competitions/ucl/tests/conftest.py
key-decisions:
  - "Post-aggregation pattern: collect per-iteration results in flat lists, aggregate once after loop (avoids O(N) dict merges)"
  - "Matchup lambdas precomputed once before the iteration loop for ~2x performance gain"
  - "aggregate_mc_results() separated from run_monte_carlo() for isolated unit testing"
patterns-established:
  - "MC simulation: precompute constants → initialize collectors → N-iteration loop → aggregate → return"
  - "Fixture data loaded via conftest.py fixtures (sample_fixture_schedule returns real 36-team schedule)"
requirements-completed: [UCLT-05]
duration: 8.2s (10K iterations) + ~12min development
completed: 2026-06-27
---

# Phase 1 Plan 3: Monte Carlo Simulation Engine Summary

**N-iteration Monte Carlo simulation loop over 36-team UCL league phase with per-team zone probabilities, champion probability, and tiebreaker stat averages using post-aggregation pattern**

## Performance

- **Duration:** ~15 min (development + 10K verification run)
- **Started:** 2026-06-27
- **Completed:** 2026-06-27
- **Tasks:** 3 (including verification)
- **Files modified:** 6 (650 lines added)

## Accomplishments

- `simulate_league_phase()` — orchestrates one complete league phase iteration (lambdas → matches → standings)
- `run_monte_carlo()` — N-iteration loop with per-team collectors, post-aggregation pattern
- `aggregate_mc_results()` — isolated aggregation computing zone probabilities, champion prob, and all 6 tiebreaker stat averages
- `test_monte_carlo.py` — 13 unit tests covering determinism, output keys, zone sum invariant, champion tracking, seed independence, aggregation correctness, N=1 edge case, N=100 smoke test
- 10K iteration verification passed: champion probs sum to 1.0, no NaN/out-of-range values, all zone probs sum to 1.0 per team, avg positions in [1,36]

## Task Commits

Each task was committed atomically:

1. **Task 1: MC fixtures + simulate_league_phase** — `e7a811e` (feat)
2. **Task 2: Monte Carlo loop (TDD: RED)** — `75f0afe` (test)
3. **Task 2: Monte Carlo loop (TDD: GREEN)** — `a25d1cb` (feat)
4. **Task 2: Monte Carlo loop (TDD: REFACTOR)** — `db98db2` (refactor)

**Plan metadata:** `093082a` (docs: complete Summary), `85a8794` (docs: update STATE.md)

## Files Created/Modified

- `competitions/ucl/src/simulation.py` — Monte Carlo simulation orchestrator: `simulate_league_phase`, `run_monte_carlo`, `aggregate_mc_results`
- `competitions/ucl/tests/test_monte_carlo.py` — 13 unit tests (8 MC loop + 4 aggregation + 1 import)
- `competitions/ucl/tests/conftest.py` — MC test fixtures: `sample_full_fixture_path`, `sample_mc_output`
- `competitions/ucl/src/__init__.py` — exports simulation module functions

## Verification Results (10,000 iterations)

```
Fixture validation: PASSED
10K iterations: 8.2s
Champion probs sum: 1.000000
All teams (36): no NaN values, no out-of-range values
All zone probabilities sum to 1.0 per team

Top 5 by top_8_prob:
  Man City       top8=96.6%  champ=34.0%  avg_pos=3.0
  Real Madrid    top8=93.7%  champ=18.4%  avg_pos=4.0
  Bayern         top8=93.0%  champ=20.2%  avg_pos=3.9
  Liverpool      top8=79.6%  champ=8.4%   avg_pos=5.6
  Barcelona      top8=75.2%  champ=5.5%   avg_pos=6.3

Bottom 5 by top_8_prob:
  Slovan Bratislava  top8=0.0%  eliminated=100.0%  avg_pos=35.2
  Bodo/Glimt         top8=0.0%  eliminated=99.1%   avg_pos=32.7
  Girona             top8=0.0%  eliminated=98.6%   avg_pos=32.7
  Maccabi Tel Aviv   top8=0.0%  eliminated=96.7%   avg_pos=31.4
  Sparta Prague      top8=0.0%  eliminated=77.8%   avg_pos=27.5
```

Results are statistically plausible: Pot 1 teams dominate top_8 probabilities, Pot 4 teams have near-certain elimination probability.

## Decisions Made

- **Post-aggregation pattern:** Collect raw positions/stats per team during iteration loop, aggregate once at the end. Avoids O(N) dict merging and simplifies testing.
- **Precomputed lambdas:** `precompute_swiss_matchup_lambdas()` called once before the loop, not on every iteration (per RESEARCH §Performance Pitfall 4).
- **Separated aggregation:** `aggregate_mc_results()` is independently testable without running simulation — unit tests use synthetic collector data.

## Deviations from Plan

None — plan executed exactly as written.

## TDD Gate Compliance

- **RED gate:** `75f0afe` — `test(01-ucl-league-table-engine-03): add failing tests for Monte Carlo simulation` ✓
- **GREEN gate:** `a25d1cb` — `feat(01-ucl-league-table-engine-03): implement Monte Carlo loop with per-team zone/champion probabilities` ✓
- **REFACTOR gate:** `db98db2` — `refactor(01-ucl-league-table-engine-03): remove unused defaultdict import from simulation.py` ✓

## Issues Encountered

None.

## Next Phase Readiness

- Monte Carlo engine complete and verified with 10K iterations
- All 13 unit tests passing
- Output format matches D-06/D-07 specification consumed by visualization (Phase 2) and analysis (Phase 3)
- UCLT-05 requirement fulfilled

## Self-Check: PASSED

- [x] SUMMARY.md exists
- [x] All 4 commits verified in git log (e7a811e, 75f0afe, a25d1cb, db98db2)
- [x] simulation.py exports all 3 functions
- [x] All 13 MC unit tests pass
- [x] Full UCL suite: 59 passed, 1 skipped

---

*Phase: 01-ucl-league-table-engine*
*Completed: 2026-06-27*
