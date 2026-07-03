---
phase: 10-probability-calibration-uncertainty
plan: 02
subsystem: core-ratings
tags: glicko, bayesian, elo, uncertainty, monte-carlo, rating-system

# Dependency graph
requires:
  - phase: 10-01
    provides: CalibrationPipeline, temperature scaling infrastructure
  - phase: 09
    provides: ValidationSuite, MC simulation engine
provides:
  - Glicko-1 closed-form (μ, σ²) rating updates with g(RD) deflation
  - RatingSystem class with serialization and point-estimate shim
  - Goal-difference K-factor weighting for Glicko
  - Monte Carlo iteration sampling from N(μ, σ²) per team
  - --use-glicko CLI flag wired through main.py and orchestrator
  - RatingSystem fetcher from ClubElo API with cache
affects: [10-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Glicko-1 closed-form Bayesian rating updates (not Glicko-2 MCMC)
    - Per-iteration N(μ, σ²) sampling for uncertainty propagation in MC
    - RatingSystem abstraction with to_elo_dict() compatibility shim

key-files:
  created:
    - football_core/glicko.py
    - tests/test_glicko.py
  modified:
    - competitions/ucl/src/elo_fetcher.py
    - competitions/ucl/src/orchestrator.py
    - competitions/ucl/src/simulation.py
    - competitions/ucl/main.py
    - competitions/ucl/src/__init__.py
    - football_core/glicko.py

key-decisions:
  - "g(RD) includes Q² factor for mathematical correctness (g(0)=1, monotonic, known values verified)"
  - "k_multiplier applied to both d² (variance reduction) and μ innovation (rating movement) for goal-difference weighting"
  - "run_monte_carlo_glicko() as separate function from run_monte_carlo() to preserve backward compatibility"
  - "Precomputed matchup lambdas use mean ratings (μ); per-iteration sampling only affects match simulation and knockout"
  - "ClubElo fetch assigns DEFAULT_SIGMA=350 to all teams (API doesn't expose RD)"

patterns-established:
  - "Glicko-1 additive pattern: new module football_core/glicko.py alongside existing football_core/elo.py"
  - "Backward compatibility: existing point-estimate functions unchanged, RatingSystem via to_elo_dict()"
  - "MC sampling: _sample_glicko_elos() clamped to [0, 3000] for stability with large σ"

requirements-completed: [UCLC-03, UCLC-04, UCLC-05]

# Metrics
duration: 18min
completed: 2026-07-03
---

# Phase 10 Plan 02: Bayesian/Glicko-style Elo with Uncertainty

**Glicko-1 closed-form (μ, σ²) rating system with g(RD) probability deflation, goal-difference weighting, MC uncertainty propagation, and --use-glicko CLI integration**

## Performance

- **Duration:** 18 min
- **Started:** 2026-07-03T12:33:20Z
- **Completed:** 2026-07-03T12:51:30Z
- **Tasks:** 5 (merged Tasks 1+2 into single commit as same file)
- **Files modified:** 7 (1 created, 6 modified)

## Accomplishments

- `football_core/glicko.py` with Glicko-1 core: g(RD), expected_score_bayesian(), update_glicko(), TeamRating, RatingSystem, compute_glicko_k_factor()
- `RatingSystem` class with get/set/update_ratings, to_dict/from_dict serialization, to_elo_dict() compatibility shim
- `run_monte_carlo_glicko()` in simulation.py with per-iteration N(μ, σ²) sampling clamped to [0, 3000]
- `fetch_team_ratings()` and `fetch_or_init_ratings()` in elo_fetcher.py wrapping ClubElo API
- `--use-glicko` CLI flag routed through orchestrator and build_simulation_result
- 39 tests covering all functions with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1+2: Glicko-1 Core + K-Factor** — `4f21769` (feat: create Glicko-1 Bayesian rating system with uncertainty)
2. **Task 3a: Elo Fetcher Migration** — `c74a11f` (feat: add RatingSystem fetchers and Glicko orchestrator support)
3. **Task 4: MC Simulation with Glicko** — `7933e34` (feat: add Glicko MC sampling and run_monte_carlo_glicko)
4. **Task 3b: CLI Flag and Wiring** — `fff7670` (feat: wire --use-glicko CLI flag and Glicko simulation path)
5. **Task 5: Test Suite** — `44d7e18` (test: add comprehensive Glicko-1 test suite with 39 tests)

**Plan metadata:** (final commit to be created after SUMMARY.md)

## Files Created/Modified

- `football_core/glicko.py` — Glicko-1 Bayesian rating engine (348 lines, new)
- `tests/test_glicko.py` — 39 tests for all Glicko components (395 lines, new)
- `football_core/__init__.py` — unchanged (empty package marker, convention is direct import)
- `competitions/ucl/src/elo_fetcher.py` — added fetch_team_ratings(), fetch_or_init_ratings()
- `competitions/ucl/src/orchestrator.py` — run_simulation() accepts optional rating_system
- `competitions/ucl/src/simulation.py` — added _sample_glicko_elos(), run_monte_carlo_glicko()
- `competitions/ucl/main.py` — added --use-glicko CLI flag, Glicko path in build_simulation_result() and main()
- `competitions/ucl/src/__init__.py` — exported run_monte_carlo_glicko

## Decisions Made

- **g(RD) includes Q² factor** — The plan's formula omits Q² but the correct Glicko-1 mathematics requires it. g(0)=1.0, g(100)≈0.953, g(350)≈0.669 (monotonic, deflates probability for uncertain opponents).
- **k_multiplier on both variance and mean** — Applied via d²/k (variance precision scaling) and direct innovation multiplication for the μ update. This produces both more rating movement and more uncertainty reduction for larger goal differences.
- **Separate run_monte_carlo_glicko()** — Keeps existing run_monte_carlo() unchanged for WC/Euro backward compatibility. The Glicko variant differs in taking a RatingSystem and sampling elos per iteration.
- **Mean ratings for precomputation** — Matchup lambdas (Poisson rates) are computed once from μ rather than sampled, avoiding O(N_iter × N_matches) recomputation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Added teams() method to RatingSystem**
- **Found during:** Task 4 (_sample_glicko_elos implementation)
- **Issue:** _sample_glicko_elos() called rating_system.teams() which didn't exist
- **Fix:** Added teams() method returning list of (team, TeamRating) pairs
- **Files modified:** football_core/glicko.py
- **Verification:** 39 tests pass, import succeeds
- **Committed in:** 7933e34 (Task 4 commit)

**2. [Rule 1 — Bug] k_multiplier=0 caused mu change test failure**
- **Found during:** Task 5 (test suite execution)
- **Issue:** k=0 divided d² by zero (inf), then σ² was still reduced but μ didn't change — inconsistent behavior
- **Fix:** Added early return for k_multiplier <= 0.0 (no update)
- **Files modified:** football_core/glicko.py
- **Verification:** test_zero_k_multiplier_no_update passes
- **Committed in:** 44d7e18 (Task 5 commit, amended glicko.py)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes necessary for API completeness and mathematical correctness. No scope creep.

## Issues Encountered

- **k_multiplier direction:** The Glicko-1 formula for d²/k reduces σ²_new, which paradoxically reduces Δμ (since Δμ = Q × σ²_new × g × (s-E)). Applied direct innovation multiplication (×k) to produce the desired "more information → more movement" behavior.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Glicko-1 rating system ready for consumption by Phase 10-03 (Bootstrap CI display)
- `--use-glicko` flag available for CLI users
- Rating uncertainty propagated into champion probability variance via per-iteration N(μ, σ²) sampling
- ClubElo fetched ratings start with DEFAULT_SIGMA=350 (conservative uncertainty) that narrows as matches are processed

## Self-Check: PASSED

- [x] All created files exist (2/2)
- [x] All modified files exist (5/5)
- [x] All task commits present (5/5)
- [x] 39/39 Glicko tests pass
- [x] 52/52 calibration tests pass (no regressions)

---
*Phase: 10-probability-calibration-uncertainty*
*Completed: 2026-07-03*
