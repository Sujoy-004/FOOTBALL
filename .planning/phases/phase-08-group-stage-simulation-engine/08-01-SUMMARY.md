---
phase: 08-group-stage-simulation-engine
plan: 01
subsystem: simulation
tags: poisson, elo, group-stage, monte-carlo, fair-play

# Dependency graph
requires:
  - phase: 07-48-team-dataset
    provides: groups.json, teams.json, constants
provides:
  - simulate_group_matches() — 72 round-robin matches per iteration
  - expected_goals() — Elo-to-goals lambda with home advantage
  - _poisson_sample() — Knuth algorithm Poisson sampler
  - _simulate_single_match() — full match with scores + fair play cards
affects: [08-02-standings, 08-03-advancement, 08-04-benchmark]

# Tech tracking
tech-stack:
  added: none (stdlib only — math, random)
  patterns: Knuth Poisson sampler, Elo-to-goals scoring model

key-files:
  created:
    - src/groups.py
    - tests/test_groups.py
  modified:
    - src/constants.py
    - tests/conftest.py

key-decisions:
  - "Home advantage multiplier of 1.05x applied to base goal rate for team_a"
  - "Knuth algorithm for Poisson sampling (stdlib-only, no numpy dependency)"
  - "Fair play cards drawn from Poisson(2.0) YC, Poisson(0.05) RC per team per match"
  - "simulate_group_matches() takes rng: random.Random for reproducibility (not module-level random)"
  - "Function does not mutate input groups dict — returns fresh results per iteration"

patterns-established:
  - "Pass rng: random.Random instance for seeded reproducibility in all group-stage functions"
  - "Return fresh dicts per iteration — never mutate shared data structures"
  - "Module docstring follows simulation.py pattern"

requirements-completed: [GROUPS-04]

# Metrics
duration: 8 min
completed: 2026-06-14
---

# Phase 8 Plan 1: Core Group Simulation Engine Summary

**Poisson score model with Elo-to-goals formula, home advantage, fair play card distribution, and 72-match group iteration — all stdlib Python**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-14T14:24:00Z
- **Completed:** 2026-06-14T14:32:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added `EXPECTED_GOALS_BASE_RATE = 1.25` constant to support Poisson goal model calibration
- Created `src/groups.py` with 4 functions: `expected_goals`, `_poisson_sample`, `_simulate_single_match`, `simulate_group_matches`
- `expected_goals()` computes Elo-to-goals lambda with 1.05x home advantage multiplier for team_a
- `_poisson_sample()` implements Knuth algorithm — stdlib-only, no numpy dependency
- `simulate_group_matches()` iterates all 12 groups (A–L) producing 72 match results with scores, winners, and fair play cards
- No mutation of input groups dict — returns fresh results per iteration
- Extended `conftest.py` with `sample_group_matches_results` and `sample_groups` fixtures
- 24 new tests in `test_groups.py` covering all functions, edge cases, and statistical distributions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add EXPECTED_GOALS_BASE_RATE constant** - `71e3418` (feat)
2. **Task 2: Create groups.py with simulation engine** - `314a23b` (feat)
3. **Task 3: Write tests for group match simulation** - `dc7e226` (test)

**Plan metadata:** (committed in this write)

## Files Created/Modified

- **`src/constants.py`** — Added `EXPECTED_GOALS_BASE_RATE: float = 1.25` with docstring
- **`src/groups.py`** — NEW: Complete group match simulation module (4 functions, ~120 lines)
- **`tests/conftest.py`** — Extended with `sample_group_matches_results` and `sample_groups` fixtures
- **`tests/test_groups.py`** — NEW: 24 tests across 5 test classes

## Decisions Made

- **Home advantage multiplier:** 1.05x applied to base goal rate for team_a (per D-03). At Elo-neutral conditions, team_a expects ~1.3125 goals vs team_b's ~1.25.
- **Knuth Poisson sampler:** Fewer than 15 lines, no external dependencies. Sufficient for Monte Carlo accuracy.
- **Fair play card distribution:** YC ~ Poisson(2.0), RC ~ Poisson(0.05) per D-04. Raw card counts stored (conduct deduction deferred to tiebreaker phase).
- **rng parameter pattern:** Accept `random.Random` instance (not module-level) for reproducibility, matching existing `simulation.py` pattern.
- **No input mutation:** `simulate_group_matches()` reads teams/groups dicts and returns a fresh results dict per iteration.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-existing test failure in `test_main_loop.py::test_once_flag_runs_single_cycle` caused by data mismatch between v1.0 bracket.json (references Nigeria) and v1.1 teams.json (does not include Nigeria). Not related to this plan's changes.
- Initial fair-play card test divided by `total_matches` (not `2 * total_matches`) — cards are per-team, each match has 2 teams. Fixed before commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `src/groups.py` ready for Phase 08-02 (Standings & Tiebreakers), which will consume `simulate_group_matches()` output to compute `compute_standings()`
- fixture `sample_group_matches_results` in conftest.py ready for standings test consumption
- All 4 functions exported and importable: `expected_goals`, `_poisson_sample`, `_simulate_single_match`, `simulate_group_matches`

---

## Self-Check: PASSED

- [x] `src/groups.py` exists with all 4 functions (`71e3418`, `314a23b`)
- [x] `src/constants.py` has `EXPECTED_GOALS_BASE_RATE = 1.25` (`71e3418`)
- [x] `tests/test_groups.py` has 24 tests passing (`dc7e226`)
- [x] All pre-existing tests pass (147/147 excluding pre-existing data-mismatch in test_main_loop)
- [x] No modifications to `simulation.py`, `main.py`, `fetcher.py`, `output.py`
- [x] Plan verification commands all pass

*Phase: 08-group-stage-simulation-engine*
*Completed: 2026-06-14*
