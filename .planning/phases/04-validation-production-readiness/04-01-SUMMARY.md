---
phase: 04-validation-production-readiness
plan: 01
subsystem: api
tags: bsd-api, fetcher, team-aliases, odds, ucl

requires:
  - phase: 02-ucl-knockout-phase
    provides: BSD UCL params (league_id=7), team_aliases.json, fixtures.json
provides:
  - UCL-specific BSD data fetcher with team alias resolution
  - Fixture schedule matching by (team_a, team_b) pair
  - Market odds extraction with vig removal
affects: [04-validation-production-readiness (Plan 02: validation cross-check)]

tech-stack:
  added: []
  patterns:
    - "BSD fetcher pattern: import fetch_raw_matches from football_core, build fixture lookup from matchdays dict, resolve aliases via _build_alias_lookup, extract odds with remove_vig"
    - "Test monkeypatching: patch competitions.ucl.src.fetcher.fetch_raw_matches to avoid real network calls"

key-files:
  created:
    - competitions/ucl/src/fetcher.py
    - competitions/ucl/tests/test_fetcher.py
  modified: []

key-decisions:
  - "Fixture lookup uses bidirectional (team_a, team_b) -> match_id dict for matching BSD events with possible reversed home/away orientation"
  - "Fixture teams registered into alias lookup to handle teams missing from BSD aliases"
  - "Monkeypatch target is the imported reference in competitions.ucl.src.fetcher (not football_core.fetcher) due to Python from-X-import name binding"

patterns-established:
  - "BSD fetcher stub: UCL fetcher follows WC pattern but omits bracket matching, enrichment extraction, and stats/context fields"
  - "Fixture team registration: fixture schedule teams are added to alias_lookup to ensure resolution even if BSD API uses different naming"

requirements-completed:
  - UCLV-01

duration: 5min
completed: 2026-06-29
---

# Phase 4 Plan 1: BSD API Fetcher for UCL Match Results — Summary

**UCL BSD data fetcher with alias resolution, fixture matching, and vig-removed odds extraction — following the WC fetcher pattern**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-29T09:21:29Z
- **Completed:** 2026-06-29T09:26:51Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `competitions/ucl/src/fetcher.py` — UCL-specific BSD data fetcher that imports shared HTTP fetch from `football_core.fetcher`, resolves team names through `_build_alias_lookup`, matches BSD events to UCL fixture schedule by (team_a, team_b), and extracts market odds with vig removal via `football_core.predictors.odds.remove_vig`
- Created 13 unit tests covering all scenarios: empty events, unfinished events filtered, team normalization (including PSG alias resolution), home/away/draw score extraction, unmatchable teams, unmatched fixtures, bidirectional lookup, odds extraction with vig removal, and events without odds
- All tests use monkeypatching — zero real network calls
- UCL test suite remains green: 142 passed, 1 skipped (13 new tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create UCL BSD fetcher module** — `ead39b6` (feat)
2. **Task 2: Create UCL fetcher tests** — `6d0c390` (test)

**Plan metadata:** Pending (final commit)

## Files Created/Modified

- `competitions/ucl/src/fetcher.py` — UCL BSD fetcher: `build_ucl_url()` + `fetch_ucl_matches(api_key, aliases, fixtures_schedule)` with alias resolution, fixture matching, score extraction, odds extraction (126 lines)
- `competitions/ucl/tests/test_fetcher.py` — 13 unit tests: `TestBuildUclUrl` (1 test) + `TestFetchUclMatches` (12 tests) covering all BSD fetch scenarios (292 lines)

## Decisions Made

- **Monkeypatch target:** Patched `competitions.ucl.src.fetcher.fetch_raw_matches` (the local imported reference) rather than `football_core.fetcher.fetch_raw_matches` — Python's `from X import Y` creates a local name binding, so patching the source module does not affect already-imported references
- **Bidirectional fixture lookup:** Fixture lookup stores both (team_a, team_b) and (team_b, team_a) orientations so BSD events with swapped home/away still match their fixture entry
- **Fixture team registration:** Fixture schedule teams are added to alias_lookup in addition to BSD aliases — handles teams that might appear with exact canonical names in BSD data

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all tests passed on second run after correcting monkeypatch target path.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- UCL BSD fetcher ready for Plan 02 (validation cross-check) — `main.py` can import `fetch_ucl_matches`, call it with BSD_API_KEY, team_aliases, and fixture schedule
- All scenarios validated through unit tests — fetcher behavior is well-understood before integration
- Threat model T-4-01 satisfied: API key never hardcoded, always passed as parameter; 401 handled gracefully by `fetch_raw_matches`

---
*Phase: 04-validation-production-readiness*
*Completed: 2026-06-29*
