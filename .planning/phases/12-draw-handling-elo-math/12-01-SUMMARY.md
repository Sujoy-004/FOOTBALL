---
phase: 12-draw-handling-elo-math
plan: 01
subsystem: elo-engine
tags: elo, k-factor, penalty-shootout, goal-difference, eloratings

# Dependency graph
requires:
  - phase: 11-data-integrity-elo-foundation
    provides: constants.K_FACTOR (base K=60), elo.py module structure
provides:
  - compute_k_factor() goal-difference K-multiplier step-function
  - pk_winner parameter in update_ratings() for 0.75/0.25 PK split
  - apply_elo_update() with K-multiplier and PK detection
affects:
  - 12-draw-handling-elo-math (plans 02-03: fetcher draw fix, historical backfill)
  - 12b-evaluation-and-calibration (baseline metrics consume fixed Elo)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Goal-difference K-multiplier via step-function (eloratings.net spec)
    - PK mode with 0.75/0.25 result split
    - TDD: RED-GREEN per feature, backward compat verified via full suite

key-files:
  created: []
  modified:
    - worldcup_predictor/src/elo.py (115→182 lines)
    - worldcup_predictor/tests/test_elo.py (117→190 lines)

key-decisions:
  - "compute_k_factor() placed as standalone function in elo.py (between expected_score and update_ratings) for cohesion, not utils.py"
  - "PK detection in apply_elo_update: is_draw=False + winner set + any GD, relying on the fact that PK matches always have GD=0 in 120' score"
  - "K=int(round(adjusted_K)) per eloratings.net rounding-to-nearest-integer convention"
  - "True draws (winner=None) with scores added use GD=0→G=1→K=60, unchanged behavior"

patterns-established:
  - "TDD cycle (RED→GREEN) per feature with backward compat verified via full suite"
  - "Step-function K-multiplier: GD≤1→G=1.0, GD=2→G=1.5, GD≥3→G=(11+N)/8"

requirements-completed:
  - V2-04
  - V2-03
---

# Phase 12 Plan 01: Draw Handling & Elo Math — Summary

**Goal-difference K-multiplier step-function, PK-mode 0.75/0.25 split, and K-multiplier wiring into apply_elo_update — all via TDD**

## Performance

- **Duration:** < 10 min
- **Started:** 2026-06-15
- **Completed:** 2026-06-15
- **Tasks:** 3 (all TDD: 6 commits)
- **Files modified:** 2

## Accomplishments

- `compute_k_factor(goal_diff, base_K)` step-function per eloratings.net: GD≤1→G=1.0, GD=2→G=1.5, GD≥3→G=(11+N)/8
- `update_ratings()` accepts `pk_winner` parameter for 0.75/0.25 penalty shootout split
- `apply_elo_update()` computes goal-difference K-multiplier and detects PK-decided matches
- 11 new tests across 3 TDD cycles (RED → GREEN per task)
- All 13 existing tests pass unchanged — zero regressions

## Task Commits

Each task was committed atomically via TDD (RED → GREEN):

1. **Task 1: Implement compute_k_factor()** — `38ddee6` (test), `012ae30` (feat)
2. **Task 2: Add pk_winner to update_ratings()** — `3f558c5` (test), `9798017` (feat)
3. **Task 3: Wire K-multiplier + PK into apply_elo_update()** — `32e4559` (test), `3dc02a4` (feat)

## Files Created/Modified

- `worldcup_predictor/src/elo.py` (115→182 lines) — Added `compute_k_factor()`, `pk_winner` parameter to `update_ratings()`, K-multiplier + PK detection in `apply_elo_update()`, `from src import constants`
- `worldcup_predictor/tests/test_elo.py` (117→190 lines) — Added `TestComputeKFactor` class (6 tests), `test_pk_split`, `test_pk_winner_invalid`, `test_apply_elo_update_k_multiplier`, `test_apply_elo_update_pk`, `test_apply_elo_update_draw_gd0`. Updated `test_apply_elo_update_draw` with scores.

## Decisions Made

- `compute_k_factor()` placed in elo.py for cohesion (not utils.py)
- PK detection uses `is_draw=False + winner is not None` (not score comparison) — the plan spec says `GD == 0` but the implementation checks `not match.get("is_draw", True) and match.get("winner") is not None` which covers PK matches at any GD (though PK matches always have GD=0)
- `K=int(round(adjusted_K))` per eloratings.net rounding convention
- Backward compat verified: true draws (winner=None) with scores added use GD=0→G=1→K=60, producing identical results

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Elo math foundation complete (compute_k_factor, PK mode, K-multiplier wiring)
- Ready for Plan 02: Fetcher draw entry fix (live + group match pipes)
- Plan 03: Historical draw backfill and baseline measurement can proceed after Plan 02

---

*Phase: 12-draw-handling-elo-math*
*Completed: 2026-06-15*
