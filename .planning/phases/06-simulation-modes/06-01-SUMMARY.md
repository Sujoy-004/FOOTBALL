---
phase: 06-simulation-modes
plan: 06-01
subsystem: engine
tags: football_core, played_matches, MatchResultProvider

requires:
  - phase: 05-official-fixture-ingestion
    provides: FixtureProvider Protocol pattern, football_core/provider.py
provides:
  - played_matches override parameter in simulate_league_matches()
  - MatchResultProvider Protocol in football_core/provider.py
affects: [06-02, 07-prediction-signals]

tech-stack:
  added: []
  patterns:
    - Bidirectional tuple-key lookup for played match injection
    - Protocol-based MatchResultProvider interface

key-files:
  created: []
  modified:
    - football_core/groups.py
    - football_core/provider.py

key-decisions:
  - "played_matches uses bidirectional (team_a, team_b) tuple lookup — both orientations checked"
  - "MatchResultProvider follows same @runtime_checkable Protocol pattern as FixtureProvider"
  - "Cards zeroed for injected matches (same approach as WC played_groups pattern)"

patterns-established:
  - "PlayedMatches injection: bidirectional tuple-key lookup with zeroed card fields"

requirements-completed: [UCLM-04, UCLM-05]

duration: 8min
completed: 2026-07-01
---

# Phase 6 Plan 06-01: Generic Primitive — Summary

**played_matches override in simulate_league_matches() + MatchResultProvider Protocol in football_core**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-01T12:00:00Z
- **Completed:** 2026-07-01T12:08:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `played_matches: dict[tuple[str, str], tuple[int, int]] | None` parameter to `simulate_league_matches()` in `football_core/groups.py` — builds bidirectional lookup, injects provided score with zeroed cards when match found
- Added `MatchResultProvider` as a `@runtime_checkable` Protocol in `football_core/provider.py` — follows same pattern as `FixtureProvider` from Phase 5

## Task Commits

Each task was committed atomically:

1. **Task 1: Add played_matches to simulate_league_matches()** - `dbb4bf8` (feat)
2. **Task 2: Add MatchResultProvider Protocol** - `1242601` (feat)

**Plan metadata:** pending (committed with plan completion)

## Files Created/Modified
- `football_core/groups.py` - Added `played_matches` parameter + bidirectional lookup + injection logic in `simulate_league_matches()`
- `football_core/provider.py` - Added `MatchResultProvider` Protocol with `load()` method

## Decisions Made
- Used bidirectional `(team_a, team_b)` tuple-key lookup (matching D-02 spec) rather than `match_id` lookup (WC pattern uses match_id, but D-02 mandates tuple-key for UCL)
- Cards zeroed for injected matches (same as WC `played_groups` pattern — conduct score step 9 rarely affects standings)
- `MatchResultProvider` uses `@runtime_checkable` Protocol to match `FixtureProvider` convention

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Generic `played_matches` primitive ready in `football_core` for Plan 06-02 UCL threading
- `MatchResultProvider` Protocol available for provider implementations in 06-02
