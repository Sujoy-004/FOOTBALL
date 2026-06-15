---
phase: 12-draw-handling-elo-math
plan: 02
subsystem: core-elo
tags: [draw, penalty-shootout, elo, fetcher, historical-catchup, tdd]
requires:
  - phase: 12-draw-handling-elo-math
    provides: compute_k_factor and pk_winner support (12-01)
provides:
  - Draw entry production at all 3 skip sites (process_matches, process_group_matches, _run_historical_catch_up)
  - PK shootout detection (equal scores + BSD winner) at knockout sites
  - Test coverage for draw/PK entry shapes
affects:
  - 12-03: K-multiplier integration into apply_elo_update
  - main.py iteration loop (draw entries now flow to Elo updates)
tech-stack:
  added: []
  patterns:
    - Draw/PK detection via BSD winner field when home_score == away_score
    - Group path omits PK detection per Pitfall 4 guard
key-files:
  created: []
  modified:
    - worldcup_predictor/src/fetcher.py (process_matches, process_group_matches)
    - worldcup_predictor/main.py (_run_historical_catch_up)
    - worldcup_predictor/tests/test_fetcher.py (2 new tests)
    - worldcup_predictor/tests/test_group_integration.py (draw_skipped → draw_included)
    - worldcup_predictor/tests/test_main_loop.py (draw_skipped → draw_included, new pk test)
key-decisions:
  - "PK detection uses BSD winner field matched against normalized team names (D-06)"
  - "Group path omits PK detection — World Cup group matches never go to PKs (Pitfall 4)"
  - "True draws stored with winner=None, is_draw=True; PK entries with winner set, is_draw=False"
  - "is_draw computed via (winner is None) for historical catch-up, explicit bool for fetcher paths"
patterns-established: []
requirements-completed:
  - V2-03
duration: 5min
completed: 2026-06-15
---

# Phase 12 Plan 02: Fix Three Draw-Skip Sites Summary

**Draw entry production at all three code sites (knockout live, group live, knockout historic) with PK shootout detection via BSD winner field**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-15T13:11:57Z
- **Completed:** 2026-06-15T13:17:39Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- **process_matches() (knockout live):** Replaced `else: continue` with draw/PK detection — true draws get `winner: null, is_draw: true`, PK shootouts get `winner: <team>, is_draw: false`
- **process_group_matches() (group live):** Replaced `else: continue` with true draw detection (`winner: null, is_draw: true`) — no PK logic per Pitfall 4 guard
- **_run_historical_catch_up() (historic knockout):** Replaced draw-skip `continue` with draw/PK detection, preserving `played_bsd_event_ids` ordering per Pitfall 3
- **5 new/updated tests** covering draw and PK entry shapes at all 3 sites
- **290 total tests pass** (0 regressions, 1 skipped live smoke)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix knockout live draw skip — process_matches()** — `82b9076` (feat)
2. **Task 2: Fix group live draw skip — process_group_matches()** — `6cce444` (feat)
3. **Task 3: Fix historical knockout draw skip — _run_historical_catch_up()** — `0749581` (feat)

**Plan metadata:** Pending (SUMMARY.md will be committed with this file)

## Files Created/Modified

- `worldcup_predictor/src/fetcher.py` — Draw/PK detection in `process_matches()` (lines 122-153) and `process_group_matches()` (lines 307-347)
- `worldcup_predictor/main.py` — Draw/PK detection in `_run_historical_catch_up()` (lines 249-275)
- `worldcup_predictor/tests/test_fetcher.py` — Added `test_process_matches_draw` and `test_process_matches_pk`
- `worldcup_predictor/tests/test_group_integration.py` — Renamed `test_process_group_matches_draw_skipped` → `test_process_group_matches_draw_included` with draw entry assertions
- `worldcup_predictor/tests/test_main_loop.py` — Renamed `test_draw_skipped` → `test_draw_included` with draw entry + Elo assertions; added `test_knockout_pk_catch_up`

## Decisions Made

- **PK detection uses BSD `winner` field:** When `home_score == away_score` and BSD provides a `winner` that matches a team name, it's a PK shootout — winner is set, `is_draw=False`. The BSD winner field is validated against normalized team names with an unknown-winner fallback to draw (T-12-02 mitigation).
- **Group path omits PK detection:** Per Pitfall 4 — World Cup group matches never go to penalties. Group draws always produce `winner: null, is_draw: true`.
- **`is_draw` computed via `(winner is None)`** in main.py's historical catch-up (simpler when winner is derived in the same block). Fetcher paths use explicit `is_draw` booleans.

## Deviations from Plan

None — plan executed exactly as written.

### Auto-fixed Issues

None — all three sites fixed per specification.

---

**Total deviations:** 0
**Impact on plan:** No deviations. All changes are within planned scope.

## Issues Encountered

None

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All 3 draw-skip sites are fixed — draws and PK shootouts now produce entries that flow into the Elo pipeline
- Ready for **Plan 12-03**: K-multiplier integration into `apply_elo_update` and historical draw backfill
- The `apply_elo_update` function already handles `winner=None` for draws (D-05), so draw entries from this plan will be correctly processed

## Threat Flags

None — no new security-relevant surface introduced. BSD winner field validated against normalized team names with fallback (T-12-02 mitigated).

## Self-Check: PASSED

- [x] All 290 tests pass (1 skipped live smoke)
- [x] process_matches() no longer skips draws — produces is_draw entries for knockout live
- [x] process_group_matches() no longer skips draws — produces is_draw entries for group live
- [x] _run_historical_catch_up() no longer skips draws — produces is_draw entries for knockout historic
- [x] PK detection at all 3 knockout sites: equal scores + BSD winner → PK entry with is_draw=False
- [x] No PK detection in group path (Pitfall 4)
- [x] `continue # Draw` patterns removed from both fetcher.py and main.py
- [x] fetcher.py: 353 lines (≥ 340), contains "is_draw"
- [x] main.py: 564 lines (≥ 555), contains "is_draw"
- [x] All 3 commits verified in git log

---

*Phase: 12-draw-handling-elo-math*
*Completed: 2026-06-15*
