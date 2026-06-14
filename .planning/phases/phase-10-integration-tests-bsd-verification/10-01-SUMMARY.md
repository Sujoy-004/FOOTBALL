---
phase: 10-integration-tests-bsd-verification
plan: 01
subsystem: api, storage, simulation
tags: bsd-api, group-matches, played-groups, pipeline, persistence

requires:
  - phase: 09-knockout-bracket-annex-c-routing
    provides: run_full_simulation(), knockout pipeline, bracket.json
  - phase: 08-group-stage-simulation-engine
    provides: simulate_group_matches(), groups.json structure
  - phase: 07-48-team-dataset
    provides: groups.json, team_aliases.json

provides:
  - process_group_matches() for BSD API group match ingestion
  - played_groups.json persistence (load/save)
  - played_groups parameter wired through simulate_group_matches() and run_full_simulation()
  - Group match processing in main.py _run_iteration() polling cycle

affects:
  - Plan 02 (group standings display — will consume played_groups results)
  - Plan 03 (test fixes — 2 pre-existing failures remain)
  - Plan 04 (SOT batch update)

tech-stack:
  added: []
  patterns:
    - "Group match slot resolution via team pair set equality (mirrors _find_bracket_match())"
    - "Atomic JSON persistence via _atomic_write_json() (reused from state.py)"
    - "Alias lookup includes group team names (Pitfall 2 guard)"

key-files:
  created: []
  modified:
    - worldcup_predictor/src/fetcher.py
    - worldcup_predictor/src/state.py
    - worldcup_predictor/src/groups.py
    - worldcup_predictor/src/knockout.py
    - worldcup_predictor/main.py
    - worldcup_predictor/tests/test_main_loop.py

key-decisions:
  - "_find_group_match() accepts round_number parameter for future filtering, but match resolution uses team pair set equality (unambiguous per group, matching _find_bracket_match() pattern)"
  - "played_bsd_event_ids is an in-memory set scoped to each poll iteration (A5 — not persisted across restarts, acceptable for MVP)"
  - "Group match results don't affect Elo ratings (per D-09 scope)"
  - "Real group match results use 0 for card counts (no fair play data from BSD API)"

patterns-established:
  - "process_group_matches() follows same pattern as process_matches() — alias lookup, normalization, slot resolution, dedup"
  - "Alias lookup for group matches injects all group team names from groups.json to handle teams not in team_aliases.json"

requirements-completed: [INTG-01, INTG-02]

duration: 11min
completed: 2026-06-14
---

# Phase 10 Plan 01: Group Match Ingestion & Pipeline Wiring Summary

**BSD API group match ingestion pipeline: process_group_matches() in fetcher.py, played_groups.json persistence in state.py, played_groups param wired through simulate_group_matches() → run_full_simulation() → main.py**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-14T12:39:42Z
- **Completed:** 2026-06-14T12:50:37Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Added `process_group_matches()`, `_extract_group_letter()`, `_find_group_match()` to fetcher.py — BSD API group match ingestion with alias normalization (including group team names), slot resolution, dedup (BSD event id + match_id), and graceful log+skip for errors
- Added `load_played_groups()` and `save_played_groups()` to state.py — separate persistence file for group match results, graceful bootstrap to empty dict, atomic writes via `_atomic_write_json()`
- Wired `played_groups` parameter through `simulate_group_matches()` (skip+inject real results), `run_full_simulation()` (forward to group sim), and `main.py` (load, process new group matches, save, pass to simulation)
- Updated test mocks to accept `**kwargs` for forward-compatibility with new parameters
- 190 tests pass (2 pre-existing known failures unchanged — deferred to Plan 03)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add process_group_matches() and helpers to fetcher.py** - `0bda009` (feat)
2. **Task 2: Add load/save for played_groups.json to state.py** - `7ec1a31` (feat)
3. **Task 3: Wire played_groups through groups.py, knockout.py, main.py** - `a0911bf` (feat)

## Files Created/Modified

- `worldcup_predictor/src/fetcher.py` — Added `_extract_group_letter()`, `_find_group_match()`, `process_group_matches()` (+123 lines net)
- `worldcup_predictor/src/state.py` — Added `load_played_groups()`, `save_played_groups()` (+35 lines)
- `worldcup_predictor/src/groups.py` — Added `played_groups` param to `simulate_group_matches()` with injection logic
- `worldcup_predictor/src/knockout.py` — Added `played_groups` param to `run_full_simulation()`
- `worldcup_predictor/main.py` — Imported and called `process_group_matches()`, added `played_groups` to `_run_iteration()` and `main()`
- `worldcup_predictor/tests/test_main_loop.py` — Updated mock sim functions to accept `**kwargs`

## Decisions Made

- **Alias lookup includes group team names:** `process_group_matches()` builds the alias lookup from team_aliases.json PLUS all team names from groups.json teams arrays. This prevents the Pitfall 2 scenario where group-exclusive teams (like "South Africa") are unmatchable.
- **Round_number in signature:** `_find_group_match()` accepts `round_number` per D-03 spec, but match resolution uses team pair set equality (unambiguous since each team pair appears exactly once per group).
- **No Elo updates for group matches:** Per D-09 scope, group match results update played_groups.json but don't trigger Elo recalculations. This avoids the complexity of updating displayed standings mid-poll from Elo changes.
- **In-memory BSD event id dedup:** Per A5, `played_bsd_event_ids` is a local set created fresh each iteration. Cross-restart dedup is handled by match_id in played_groups.json.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_extract_group_letter()` empty string edge case**
- **Found during:** Task 1 (Acceptance criteria verification)
- **Issue:** Python's `'' in "ABC"` returns True (empty string is a substring of any string), causing `_extract_group_letter("Group ")` to return `''` instead of None
- **Fix:** Added `len(group_name) < 7` guard and `not letter` check before the substring membership test
- **Files modified:** worldcup_predictor/src/fetcher.py
- **Verification:** All acceptance criteria pass: `_extract_group_letter("Group A")` → `"A"`, `_extract_group_letter("Group ")` → `None`, `_extract_group_letter(None)` → `None`
- **Committed in:** 0bda009 (Task 1 commit)

**2. [Rule 3 - Blocking] Mock sim functions don't accept `played_groups` kwarg**
- **Found during:** Task 3 (Verification — test_once_flag_runs_single_cycle failed)
- **Issue:** `run_full_simulation()` now accepts `played_groups` kwarg, but test mocks in `test_main_loop.py` had fixed signatures that rejected unknown kwargs
- **Fix:** Changed all 4 mock sim definitions to use `*args, **kwargs` pattern
- **Files modified:** worldcup_predictor/tests/test_main_loop.py
- **Verification:** `test_once_flag_runs_single_cycle` passes; 190 total tests pass
- **Committed in:** a0911bf (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

- Pre-existing `test_main_loop_runs_iterations` failure (asserts "Fetched" but code uses "Polling") — deferred to Plan 03 (D-22)
- Pre-existing `TestExpectedGoals.test_expected_goals_very_strong_dominates` failure (asserts >10.0 but MAX_EXPECTED_GOALS=8.0 caps at 8.0) — deferred to Plan 03 (D-23)

## User Setup Required

None - no external service configuration required. played_groups.json bootstraps as empty `{}` on first run.

## Next Phase Readiness

- Group match ingestion pipeline fully wired: BSD API → process_group_matches() → played_groups.json → simulate_group_matches() override
- Plan 02 can now display group standings (consumes compute_standings() output)
- All acceptance criteria for INTG-01 and INTG-02 satisfied
- 190/192 tests pass (2 known failures deferred to Plan 03)

---

*Phase: 10-integration-tests-bsd-verification*
*Completed: 2026-06-14*
