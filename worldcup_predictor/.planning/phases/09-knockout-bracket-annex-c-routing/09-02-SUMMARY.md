---
phase: 09-knockout-bracket-annex-c-routing
plan: 02
subsystem: knockout
tags: [simulation, r32, annex-c, tpp, knockout]
---

# Dependency graph
requires:
  - phase: 09-01
    provides: bracket.json with 32-match R32 format
  - phase: 08-group-stage-simulation-engine
    provides: groups.py with all pipeline functions
provides:
  - knockout.py with run_full_simulation() orchestrator
  - Full 104-match pipeline: group stage -> Annex C -> R32 -> R16 -> QF -> SF -> TPP -> FINAL
affects:
  - 09-03 (validation, tests, main.py integration)
  - 10-integration

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "run_full_simulation() as top-level orchestrator importing from groups.py + elo.py"
    - "SF losers tracked in sf_losers dict for TPP resolution"
    - "R32 resolved via slot descriptors, R16+ via source_matches (unchanged v1.0 pattern)"

key-files:
  created:
    - src/knockout.py
  modified: []

key-decisions:
  - "run_full_simulation() returns same {team: {qf, sf, final, champion}} dict format as run_simulation() for backward compat"
  - "R32 handled via _simulate_r32_resolved() from resolve_r32_matchups output (slot descriptors resolved to team names before simulation)"
  - "R16 uses source_matches (unchanged v1.0 pattern) — R32 winners flow through winner_progression"
  - "TPP tracks SF losers during SF simulation via optional sf_losers parameter"
  - "round_map skips R32 entries (filtered in _build_round_map)"
  - "Poisson group simulation from groups.py; Elo-based binary knockout from elo.py"

requirements-completed:
  - BRKT-02
  - BRKT-03
  - BRKT-04
  - BRKT-05
  - BRKT-06

# Metrics
duration: 6min
completed: 2026-06-14
---

# Phase 9 Plan 2: Knockout Module with Full 104-Match Pipeline

**`src/knockout.py` created with `run_full_simulation()` orchestrator importing group stage engine and implementing R32 slot resolution, TPP tracking, and full knockout traversal.**

## Accomplishments

- Created `src/knockout.py` (198 lines) with 7 functions:
  - `_build_round_map()` — builds round_map skipping R32 entries
  - `_simulate_r32_resolved()` — simulates R32 from resolved matchups (team_a/team_b from slot descriptors)
  - `_simulate_r16()` — R16 using source_matches (new in v1.1, was hardcoded team_a/team_b in v1.0)
  - `_simulate_knockout_round()` — extended to track SF losers for TPP
  - `_simulate_tpp()` — third-place match from SF losers
  - `run_full_simulation()` — orchestrator:
    1. simulate_group_matches() → results
    2. compute_standings() → standings
    3. rank_third_placed() → third_ranked
    4. select_advancers() → advancers
    5. resolve_r32_matchups() → r32_matchups
    6. _simulate_r32_resolved() → winner_progression[M73-M88]
    7. _simulate_r16() → winner_progression[M89-M96]
    8. _simulate_knockout_round(QF) → winner_progression[QF_1-QF_4]
    9. _simulate_knockout_round(SF) → winner_progression[SF_1-SF_2] + sf_losers
    10. _simulate_tpp() → winner_progression[TPP]
    11. _simulate_knockout_round(FINAL) → winner_progression[FINAL]
    12. Count stage appearances + champion
  - Returns: `{team: {qf: float, sf: float, final: float, champion: float}}`

## Files Created/Modified

- `worldcup_predictor/src/knockout.py` — Full tournament simulator (198 lines, new)

## Next Phase Readiness

- Ready for 09-03: bracket validation, tests, main.py integration
- main.py still calls `run_simulation()` from `simulation.py` — needs update to `run_full_simulation()` from `knockout.py`

## Self-Check: PASSED

- [x] src/knockout.py exists with all 7 functions
- [x] run_full_simulation() imports correctly from groups.py and elo.py
- [x] Importable without errors: `python -c "from src.knockout import run_full_simulation"`
- [x] Committed as `b33f021`
