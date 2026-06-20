---
phase: 19-multi-league-framework
plan: 01
subsystem: api
tags: league-framework, constants, fetcher, catboost, parameterization
requires: []
provides:
  - LEAGUES dict with league_id->name mapping in constants.py
  - api_url_for_league() and predictions_url_for_league() URL builders
  - league_id parameter on build_historic_url(), fetch_raw_matches(), fetch_and_cache_catboost()
  - Test coverage for custom league_id URL construction
affects: [19-02, 19-03, main.py CLI wiring]

tech-stack:
  added: []
  patterns:
    - "URL construction via league_id parameter instead of hardcoded values"
    - "Dynamic league_id param with default=27 for backward compatibility"
    - "DEFAULT_LEAGUE_ID constant as single source of truth for default league"

key-files:
  created: []
  modified:
    - src/constants.py - Added LEAGUES dict, DEFAULT_LEAGUE_ID, api_url_for_league(), predictions_url_for_league()
    - src/fetcher.py - Added league_id param to build_historic_url() and fetch_raw_matches()
    - src/predictors/catboost.py - Added league_id param to fetch_and_cache_catboost()
    - tests/test_fetcher.py - Added test_build_historic_url_custom_league

key-decisions:
  - "Seed LEAGUES with league 27 = 'World Cup 2026'; TODO for remaining 64 leagues via BSD API"
  - "Default league_id=27 on all functions preserves backward compatibility for all existing callers"
  - "Existing API_URL constant preserved unchanged as default for fetch_raw_matches()"
  - "predictions_url_for_league imported directly in catboost.py (not via constants module)"

requirements-completed: [V2-25]

# Metrics
duration: 3 min
completed: 2026-06-20
---

# Phase 19 Plan 01: Multi-League Framework — League ID Parameterization Summary

**Parameterized all 4 hardcoded `league_id=27` sites with a static LEAGUES catalog, DEFAULT_LEAGUE_ID constant, URL builder functions, and league_id parameters on all fetch-layer functions**

## Performance

- **Duration:** 3 min
- **Started:** 2026-06-20T09:20:01Z
- **Completed:** 2026-06-20T09:23:56Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- LEAGUES dict in constants.py with seed entry (league 27 = "World Cup 2026") and TODO for BSD API population
- DEFAULT_LEAGUE_ID=27 as single source of truth for the default league
- api_url_for_league() and predictions_url_for_league() URL builders for dynamic league_id URL construction
- build_historic_url() accepts league_id param (default 27) instead of hardcoded URL
- fetch_raw_matches() accepts league_id param (default 27) and uses it in the league filter
- fetch_and_cache_catboost() accepts league_id param (default 27) and uses predictions_url_for_league()
- New test_build_historic_url_custom_league validates URL construction with non-default league
- All 19 fetcher tests pass; all 41 fetcher+catboost tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add LEAGUES dict, DEFAULT_LEAGUE_ID, URL functions** - `02ba8f6` (feat)
2. **Task 2: Add league_id params to fetch functions** - `12bb9d0` (feat)
3. **Task 3: Update test_fetcher.py for dynamic league_id** - `22968ed` (test)

## Files Created/Modified
- `src/constants.py` — Added DEFAULT_LEAGUE_ID, LEAGUES dict, api_url_for_league(), predictions_url_for_league()
- `src/fetcher.py` — build_historic_url(league_id) param, fetch_raw_matches(league_id) param and filter
- `src/predictors/catboost.py` — fetch_and_cache_catboost(league_id) param, predictions_url_for_league usage
- `tests/test_fetcher.py` — Added test_build_historic_url_custom_league for non-default league_id

## Decisions Made
- **Seed LEAGUES with one entry**: BSD API `/api/leagues/` not called during implementation. League 27 = "World Cup 2026" with a `# TODO` for remaining 64 leagues.
- **Default league_id=27 everywhere**: All new parameters default to 27 so existing callers (main.py, tests) continue working without changes.
- **Existing API_URL preserved**: The original `API_URL` constant is unchanged; `fetch_raw_matches()` still uses it as the default URL (already hardcoded to league_id=27).
- **Direct import of predictions_url_for_league**: Imported directly in catboost.py alongside the existing `from src import constants` import, per plan specification.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Threat Surface Scan

No new security-relevant surface introduced. league_id parameters are typed as `int`, preventing injection via Python format strings (mitigates T-19-01, T-19-02). No new packages or network endpoints added.

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| LEAGUES only has league 27 | src/constants.py | ~10 | BSD API not available; # TODO for remaining 64 leagues |

## Self-Check: PASSED

- Verified `src/constants.py` contains LEAGUES dict, DEFAULT_LEAGUE_ID, api_url_for_league(), predictions_url_for_league()
- Verified `src/fetcher.py` has league_id params on build_historic_url and fetch_raw_matches
- Verified `src/predictors/catboost.py` has league_id param on fetch_and_cache_catboost
- Verified `tests/test_fetcher.py` has test_build_historic_url_custom_league
- All 3 commits exist in git log

## Next Phase Readiness
- Foundation complete for Phase 19-02 (CLI wiring with `--league` flag and league isolation)
- Ready for Phase 19-03 (state file isolation per league)

---
*Phase: 19-multi-league-framework*
*Completed: 2026-06-20*
