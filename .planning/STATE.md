# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-14)

**Core value:** A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.
**Current focus:** Phase 10 — Integration, Tests & BSD Verification

## Completed Milestones

### v1.0 MVP — Shipped 2026-06-14

- 6 phases, 10 plans, all complete
- 98 passing tests, ~2,200 LOC Python
- Full details: `.planning/milestones/v1.0-ROADMAP.md`

### v1.1 World Cup 2026 Support — Shipped 2026-06-14

- 4 phases, 15 plans, 34 commits, all complete
- 48-team dataset, 12 groups, 495-entry Annex C
- Group stage simulation + full 104-match pipeline
- BSD API integration with group match ingestion
- 212 passing tests, 0 failures, ~3,200 LOC Python
- Console output: box-drawing group standings + third-place bubble

### Phase 7: 48-Team Dataset & Group Definitions — Complete 2026-06-14

- 4 plans across 3 waves, all complete
- 48-team teams.json with researched Elo ratings, "USA"→"United States" rename
- 12 groups (A-L) with 72 round-robin match definitions matching official FIFA 2026 draw
- 495-entry Annex C lookup table with all structural invariants validated
- 48-entry team_aliases.json with 1:1 coverage against teams.json
- 4 new state.py functions: validate_groups, load_groups, validate_annex_c, load_annex_c
- 23 new tests, 41 total test_state.py tests pass (zero regressions)
- Production data verified: groups.json + annex_c.json pass all validators

## Current Position

Phase: 10 of 10 (Integration, Tests & BSD Verification)
Plans: 4 plans in 4 waves — all complete
Status: Complete
Last activity: 2026-06-14 — Phase 10 all plans executed, all 14 docs batch-updated

Progress: [████████████████] 100% (v1.1 milestone complete)

## Completed Phases

### v1.0 MVP — Shipped 2026-06-14
- 6 phases, 10 plans, all complete
- 98 passing tests, ~2,200 LOC Python

### Phase 7: 48-Team Dataset & Group Definitions — Complete 2026-06-14
- 4 plans, 3 waves, all complete
- 48-team teams.json, 12 groups (A-L), 495-entry Annex C table

### Phase 8: Group Stage Simulation Engine — Complete 2026-06-14 (GROUPS-07 resolved)
- 4 plans, 4 waves, 10 commits, all executed
- 51 group tests + 174 total pass
- Poisson match simulation, 7-step H2H-first tiebreaker, Annex C R32 resolution
- GROUPS-07: 50K iterations in 12.66s (target < 15s) [PASS]
  - Optimizations applied: fair_play=False, inverse-CDF table, MAX_EXPECTED_GOALS cap,
    precomputed matchup lambdas, inlined simulation, .get() -> []

### Phase 9: Knockout Bracket & Full Pipeline — Complete 2026-06-14
- 3 plans, 3 waves, 5 commits, all executed
- 32-match R32 bracket.json with slot descriptors
- knockout.py with run_full_simulation() orchestrator
- TPP from SF losers, bracket validation, 13 new tests
- 191 tests pass (1 pre-existing main_loop failure deferred)
- BRKT-01 through BRKT-08 all satisfied

### Phase 10: Integration, Tests & BSD Verification — Complete 2026-06-14
- 4 plans, 4 waves, all executed
- BSD API group match ingestion + played_groups.json persistence
- 12-group standings display with box-drawing and third-place bubble
- 2 deferred test failures fixed, 18 new group integration tests
- Full test suite: 212 passed, 1 skipped (live smoke), 0 failures
- All 7 SOTs batch-updated for 48-team format
- v1.1 milestone: complete

## Performance Metrics

**Velocity:**
- Total plans completed: 25 (10 v1.0 + 4 P7 + 4 P8 + 3 P9 + 4 P10)
- Average duration: ~10 min per plan (Phase 10)
- Total commits in v1.1: 34 (7 P7 + 10 P8 + 1 BSD + 6 P9 + 10 P10)

**By Phase:**
| Phase | Plans | Duration | Avg/Plan |
|-------|-------|----------|----------|
| 7 | 4 | 48 min | 12 min |
| 8 | 4 | 39 min | 10 min |
| 9 | 3 | 26 min | 9 min |
| 10 | 4 | ~38 min | ~10 min |

**Performance (Phase 8 GROUPS-07):**
| Metric | Value | Status |
|--------|-------|--------|
| 50K iterations | 12.66s | [PASS] (target < 15s) |
| 1K iterations | 0.295s | [PASS] |
| Matches/s | 284,473 | [PASS] |
| Optimization gain | 35.5s -> 12.66s (64% reduction) | [PASS] |

## Accumulated Context

### Decisions

- Phase numbering continues from v1.0: v1.1 starts at Phase 7
- Phase ordering enforced by data dependencies: Dataset → Group Engine → Knockout Bracket → Integration
- Requirements map cleanly: DATA2→P7, GROUPS→P8, BRKT→P9, INTG→P10
- No UI/frontend work in v1.1 — purely console CLI (same as v1.0)

### Resolved in Phase 10

| Category | Item | Resolution |
|----------|------|-----------|
| test | `test_main_loop_runs_iterations` checks "Fetched" → "Polling" | Fixed in Plan 03 — assertion changed to match current heartbeat text |
| test | `test_expected_goals_very_strong_dominates` expects >10.0, MAX_EXPECTED_GOALS=8.0 | Fixed in Plan 03 — assertion changed to `== 8.0` with cap rationale comment |
| main_loop | `test_main_loop_runs_iterations` failure | Fixed in Plan 03 — docstring updated, test passes |
| integration | BSD API group match ingestion + played_groups.json | Implemented in Plan 01 |
| display | Group standings box-drawing + third-place bubble | Implemented in Plan 02 |
| e2e | Full pipeline integration tests | Implemented in Plan 03 (18 new tests) |

### Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| verification | End-to-end with real Football-Data.org API key (superseded by BSD) | Deferred | v1.0 close |
| smoke | Live BSD smoke test requires manual BSD_API_KEY | Deferred to user setup | Phase 10 |
| utf8 | JSON encoding on Windows must use `encoding='utf-8'` (default is cp1252) | Phase 10 audit all open() calls | Phase 9 close |

### Research Flags (from SUMMARY.md)

| Phase | Flag | Status |
|-------|------|--------|
| Phase 7 | ⚠️ Annex C data source extraction; 48-team Elo rating initialization | ✅ Resolved — Annex C sourced from verified FIFA mirror, Elo assigned via formula |
| Phase 8 | ⚠️ Poisson goal model calibration; fair play card distribution data | Calibrate base rate, research historical card data |
| Phase 8 | ⚠️ Poisson goal model calibration; fair play card distribution data | ✅ Calibrated base_rate=1.25, fair play Poisson(2.0 YC, 0.05 RC) | |
| Phase 9 | ⚠️ R32 bracket integration with Annex C routing; TPP match simulation | ✅ R32 slot descriptors, Annex C, TPP all implemented | |
| Phase 10 | ⚠️ BSD API group match response format; 48-team alias coverage | ✅ Resolved — `group_name` field identified for split routing, aliases expanded to group team names | | |

## Session Continuity

Last session: 2026-06-14
Stopped at: v1.1 milestone complete — all 10 phases done
Resume file: None
