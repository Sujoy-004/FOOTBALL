---
phase: 08-group-stage-simulation-engine
plan: 03
subsystem: simulation
tags: third-place-ranking, annex-c, r32-advancement, tiebreaker, cross-group

# Dependency graph
requires:
  - phase: 08-02
    provides: compute_standings() with 7-step within-group tiebreaker, standings dict format
provides:
  - rank_third_placed() — 5-step cross-group third-place ranking (no H2H)
  - select_advancers() — 24 auto-advancers + 8 best third-placed team selection
  - resolve_r32_matchups() — full Annex C R32 matchup resolution (16 matches)
affects: [08-04-benchmark, 09-knockout-bracket, 10-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: cross-group 5-step tiebreaker with sorted() multi-key tuple, Annex C key construction from sorted advancing groups, R32 fixed + Annex C hybrid resolution

key-files:
  created: []
  modified:
    - src/groups.py (+217 lines: rank_third_placed, select_advancers, resolve_r32_matchups)
    - tests/test_groups.py (+447 lines: 14 new tests across 3 test classes)

key-decisions:
  - "5-step cross-group tiebreaker uses sorted() with tuple key per Pitfall 4 guard — never calls _tiebreak_group or uses H2H"
  - "Annex C resolver strips _meta key before lookup (T-08-SC mitigation), raises ValueError on missing key (T-08-09), not KeyError"
  - "Winner groups derived from R32 match structure (not hardcoded ANNEX_C_WINNER_GROUPS) — Anti-Pattern 4 guard"
  - "select_advancers always returns keys 1, 2, 3 for all 12 groups per T-08-11; 3 is None for non-advancing groups"

patterns-established:
  - "Cross-group third-place ranking: sorted() with tuple key (-pts, -gd, -gs, conduct, -elo) — no H2H"
  - "Annex C key: ','.join(sorted(advancing_groups)) — matches annex_c.json key format"
  - "R32 resolution: fixed structure of 16 matches, 8 via Annex C lookup, 8 via group_position lookup"

requirements-completed: [GROUPS-03, GROUPS-05, GROUPS-06]

# Metrics
duration: 5 min
completed: 2026-06-14
---

# Phase 8 Plan 3: Advancement, Third-Place Ranking & Annex C R32 Resolution Summary

**5-step cross-group third-place ranking (no H2H), 24+8 advancement selection, and 16-match R32 resolution via 495-entry Annex C lookup table**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-14T14:46:15Z
- **Completed:** 2026-06-14T14:51:27Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- `rank_third_placed()` ranks 12 third-placed teams across all groups using 5-step tiebreaker: points (-desc) → GD (-desc) → GS (-desc) → conduct_score (asc) → Elo-as-FIFA-rank-proxy (asc via -elo). Pitfall 4 guard: no H2H in cross-group ranking — uses `sorted()` with tuple key, not `_tiebreak_group()`.
- `select_advancers()` returns `{group: {1: winner, 2: runner_up, 3: third_team_or_none}}` with keys 1/2/3 for all 12 groups per T-08-11. 24 auto-advancers + 8 best third-placed = 32 advancing teams.
- `resolve_r32_matchups()` resolves all 16 R32 matches (M73-M88) using hybrid approach: 8 Anchhh C "winner vs third" matches via Annex C lookup, 8 fixed "group_position" matches via direct advancers lookup.
- Strips `_meta` key from annex_c dict before lookup (T-08-SC mitigation). Raises `ValueError` with descriptive message for missing keys (T-08-09), never `KeyError`.
- Winner groups that face third-place teams derived from R32 match structure — does not hardcode ANNEX_C_WINNER_GROUPS list (Anti-Pattern 4 guard).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add rank_third_placed() and select_advancers()** - `c3ea341` (feat)
2. **Task 2: Add resolve_r32_matchups() with Annex C lookup** - `fa4eb2a` (feat)
3. **Task 3: Write 14 advancement, third-place, Annex C, and R32 tests** - `a4e9bda` (test)

## Files Modified

- **`src/groups.py`** — Added `rank_third_placed()`, `select_advancers()`, `resolve_r32_matchups()`. Total: +217 lines.
- **`tests/test_groups.py`** — Added 14 new tests in `TestThirdPlaceRanking` (4 tests), `TestSelectAdvancers` (3 tests), `TestResolveR32` (7 tests). Added imports for new functions. Total: +447 lines.

## Decisions Made

- **5-step cross-group tiebreaker per D-15:** Uses `sorted()` with multi-key tuple `(-pts, -gd, -gs, conduct_score, -elo)`. No H2H — Pitfall 4 guard ensures the within-group `_tiebreak_group()` is never called for cross-group ranking. Elo used as FIFA ranking proxy per D-16 (higher Elo = better = lower rank number); Phase 10 to replace with real FIFA ranking.
- **Annex C key construction:** Built as `",".join(sorted(advancing_groups))` — comma-separated, sorted alphabetically, matching the key format in `annex_c.json`. Per T-08-08, this prevents tampering by deriving key from advancing groups rather than accepting external input.
- **select_advancers shape:** Always returns keys 1, 2, 3 for all 12 groups regardless of which third-placed teams advance. Key 3 is `None` for groups whose third-placed team does not advance. This per T-08-11 prevents elevation-of-privilege by ensuring consistent output shape.
- **Anti-Pattern 4 guard:** The 8 Annex C match winner groups are defined by the R32 match structure (which inherently maps to the 8 Annex C slots), not by a separate hardcoded `ANNEX_C_WINNER_GROUPS`. The `winner_to_third` mapping is derived from the assignment dict keys.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — all tasks executed smoothly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three group stage engine functions complete: `simulate_group_matches()` (08-01), `compute_standings()` (08-02), `rank_third_placed()` + `select_advancers()` + `resolve_r32_matchups()` (08-03).
- 51 group module tests pass; 174 total non-main_loop tests pass.
- Ready for Phase 08-04 (benchmark) and Phase 9 (knockout bracket integration).
- Requirements GROUPS-03, GROUPS-05, GROUPS-06 fully satisfied.

---

## Self-Check: PASSED

- [x] `from src.groups import rank_third_placed, select_advancers, resolve_r32_matchups` — all import correctly
- [x] 51 group tests pass (37 existing + 14 new)
- [x] 174 non-main_loop tests pass (zero regressions in any module)
- [x] Integration test with real `data/annex_c.json`: 16 R32 matchups resolved with non-null teams
- [x] Missing Annex C key raises `ValueError` (not `KeyError`) — negative test passes
- [x] `_meta` key filter test — meta-stripped annex_c works correctly
- [x] All acceptance criteria for each task verified passing before commit
- [x] Zero deviations from plan — all tasks executed as specified

---

*Phase: 08-group-stage-simulation-engine*
*Completed: 2026-06-14*
