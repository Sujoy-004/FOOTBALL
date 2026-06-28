---
phase: 02-ucl-knockout-phase
plan: 03
subsystem: knockout
tags: bracket, r16, knockout-tree, ucl

requires:
  - phase: 02-ucl-knockout-phase
    plan: 01
    provides: simulate_two_legged_tie, bracket_rules.json data file, playoff_pairings.json
  - phase: 02-ucl-knockout-phase
    plan: 02
    provides: simulate_playoff_round, playoff winners dict format

provides:
  - build_r16_bracket() — seeded R16 bracket construction from standings + playoff winners
  - _simulate_single_knockout_match() — single-match or two-legged tie dispatcher
  - simulate_knockout_tree() — full R16 -> QF -> SF -> Final tree traversal
  - Stage tracking per D-09 (R16/QF/SF/FINAL/CHAMPION)
  - Data-driven bracket validation with threat model compliance (T-02-08, T-02-09)

affects:
  - 02-ucl-knockout-phase (Plan 04: Monte Carlo integration)

tech-stack:
  added: []
  patterns:
    - Two-phase stage tracking: initial stage on loser + promotion after round complete
    - Single function dispatcher for both final (single-match) and non-final (two-legged)
    - Data-driven bracket construction with on-load validation

key-files:
  created: []
  modified:
    - competitions/ucl/src/knockout.py — added build_r16_bracket, _simulate_single_knockout_match, simulate_knockout_tree
    - competitions/ucl/src/__init__.py — added exports for build_r16_bracket, simulate_knockout_tree
    - competitions/ucl/tests/conftest.py — added sample_playoff_winners fixture
    - competitions/ucl/tests/test_knockout.py — added TestR16Bracket (6 tests), TestKnockoutTree (5 tests)

key-decisions:
  - "Stage tracking uses two-step approach: initial assignment at resolution time (for loser), promotion after round completion (for winner)"
  - "Final uses _simulate_single_knockout_match(is_final=True) for neutral-venue single match; non-finals delegate to simulate_two_legged_tie"
  - "Bracket data validation (T-02-08) validates required keys per round type on load — R16 needs home_seed/away_playoff_tie/quarter, later rounds need source_matches"
  - "Source match cross-reference validation (T-02-09) builds all_match_ids set, verifies each source_matches reference resolves"

patterns-established:
  - "Dispatcher pattern: _simulate_single_knockout_match routes to single-match or two-legged based on is_final flag"
  - "Defensive copying: bracket matchups list copied before iteration (T-02-09)"

requirements-completed: [UCLK-02, UCLK-03]

duration: 33min
completed: 2026-06-28
---

# Phase 02 Plan 03: Bracket Construction and Knockout Tree

**Seeded R16 bracket construction from league standings + playoff winners with top-4 protection, and full knockout tree simulation (R16 -> QF -> SF -> Final) with per-team stage tracking**

## Performance

- **Duration:** 33 min
- **Started:** 2026-06-28T08:34:00Z
- **Completed:** 2026-06-28T08:37:43Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `build_r16_bracket()` reads `bracket_rules.json`, constructs 8 seeded R16 matchups + 4 QF + 2 SF + 1 Final placeholder entries with top-4 protection (seeds 1-4 in separate quarters)
- `_simulate_single_knockout_match()` dispatches to single-match neutral-venue final or two-legged aggregate tie via `simulate_two_legged_tie()`
- `simulate_knockout_tree()` traverses R16 -> QF -> SF -> Final, simulating 15 total matches with per-team stage tracking (D-09)
- Threat model validation: required bracket entry keys (T-02-08), source_matches cross-reference resolution (T-02-09), defensive copy of matchups (T-02-09)
- 11 new tests across TestR16Bracket (6) and TestKnockoutTree (5) — all passing
- Integration test confirms end-to-end pipeline: league phase -> playoff -> bracket -> tree -> champion

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement build_r16_bracket with top-4 protection** (type: auto)
   - `328465c` — `feat(02-ucl-knockout-phase-03): implement build_r16_bracket with top-4 protection`

2. **Task 2: Implement simulate_knockout_tree** (type: tdd)
   - `641370c` — `test(02-ucl-knockout-phase-03): add failing tests for simulate_knockout_tree` (RED)
   - `b01e296` — `feat(02-ucl-knockout-phase-03): implement simulate_knockout_tree` (GREEN)

## Files Created/Modified

- `competitions/ucl/src/knockout.py` — Added `_simulate_single_knockout_match()`, `_validate_bracket_entry()`, `build_r16_bracket()`, `simulate_knockout_tree()` (308 lines added)
- `competitions/ucl/src/__init__.py` — Added `build_r16_bracket` and `simulate_knockout_tree` to imports and `__all__`
- `competitions/ucl/tests/conftest.py` — Added `sample_playoff_winners` fixture
- `competitions/ucl/tests/test_knockout.py` — Added imports, `TestR16Bracket` (6 tests), `TestKnockoutTree` (5 tests)

## Decisions Made

- **Stage tracking:** Two-step approach — initial assignment at resolution time (sets `R16`/`QF`/`SF`/`FINAL`/`CHAMPION`), followed by promotion of winners after round completes. This ensures losers get their correct terminal stage while winners advance.
- **Single-match final:** `_simulate_single_knockout_match(is_final=True)` uses neutral-venue Poisson simulation with no home advantage, matching real UCL final rules.
- **Defensive copy:** `simulate_knockout_tree()` makes a `list(bracket["matchups"])` copy before iterating, per T-02-09.
- **Input validation:** `_validate_bracket_entry()` validates round-specific required keys on load per T-02-08, raising `ValueError` for missing/invalid data.

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED  | `641370c` test(02-ucl-knockout-phase-03): add failing tests for simulate_knockout_tree | ✅ PASS |
| GREEN | `b01e296` feat(02-ucl-knockout-phase-03): implement simulate_knockout_tree | ✅ PASS |
| REFACTOR | Skipped — code clean, no refactoring needed | ⏭️ |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Pre-existing World Cup `worldcup_predictor/tests/test_knockout.py` error (`data/teams.json` not found) is unrelated to UCL changes — same error existed before plan execution. All UCL tests pass (93/93, 1 skipped = live API).

## Self-Check

- ✅ `competitions/ucl/src/knockout.py` exists and contains new functions
- ✅ `competitions/ucl/src/__init__.py` exports `build_r16_bracket` and `simulate_knockout_tree`
- ✅ `competitions/ucl/tests/conftest.py` has `sample_playoff_winners` fixture
- ✅ `competitions/ucl/tests/test_knockout.py` has `TestR16Bracket` (6) and `TestKnockoutTree` (5)
- ✅ All 34 knockout tests pass
- ✅ All 93 UCL tests pass (1 skipped = live API)
- ✅ `football_core` unchanged
- ✅ TDD gate: RED (test) + GREEN (feat) commits present in correct order
- ✅ Integration test: end-to-end pipeline produces valid champion

## Next Phase Readiness

- Ready for Plan 04: Monte Carlo integration — the knockout pipeline (`build_r16_bracket` + `simulate_knockout_tree`) is fully functional and can be called per MC iteration
- Stage tracking output (`result["stage"]`) maps directly to D-09 probability aggregation
- Champion output (`result["champion"]`) feeds champion_prob aggregation

---

*Phase: 02-ucl-knockout-phase*
*Completed: 2026-06-28*
