---
phase: 05-official-fixture-ingestion
plan: 02
subsystem: provider
tags: provider, bsd, caching, repo, pytest, protocol
requires:
  - phase: 05-official-fixture-ingestion
    plan: 01
    provides: FixtureProvider Protocol, FixtureSchedule/Team/Match dataclasses, test scaffold
provides:
  - BSDFixtureProvider with BSD API fetch + TTL caching
  - RepoFixtureProvider for repo JSON fallback
  - UCL-specific provider constants (league_id=7, BSD URL, cache TTL, cache filename)
  - Provider tests: RepoFixtureProvider (3) + BSDFixtureProvider (4)
affects: 05-03, Phase 6
tech-stack:
  added: none (stdlib: dataclasses, typing, json, os, logging, datetime)
  patterns: FixtureProvider Protocol conformance, monkeypatched HTTP for offline tests, cache-first then fetch lifecycle
key-files:
  created:
    - competitions/ucl/src/constants.py
    - competitions/ucl/src/provider.py
  modified:
    - competitions/ucl/tests/test_provider.py (added TestRepoFixtureProvider, TestBSDFixtureProvider)
    - competitions/ucl/tests/conftest.py (added sample_cached_fixtures fixture)
key-decisions:
  - "UCL constants in dedicated module (competitions/ucl/src/constants.py) following worldcup pattern"
  - "BSDFixtureProvider uses fetch_raw_matches() from football_core.fetcher — no HTTP reimplementation"
  - "Cache uses is_cache_valid() + _atomic_write_json() from football_core.state"
  - "Future-date filtering via datetime.now(timezone.utc) with fromisoformat() for tz-aware comparison"
  - "Duplicate _dict_to_schedule in both providers — acceptable duplication per two-class design"
requirements-completed: [UCLF-01, UCLF-02, UCLF-06, UCLF-07]
duration: 8 min
completed: 2026-06-30
---

# Phase 5 Plan 2: Provider Implementations Summary

**BSDFixtureProvider (BSD API + cache) and RepoFixtureProvider (repo JSON fallback) implementing the FixtureProvider Protocol, plus UCL-specific constants.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-29 (interrupted, finalized 2026-06-30)
- **Completed:** 2026-06-30
- **Tasks:** 3
- **Files created:** 2
- **Files modified:** 2
- **Tests:** 15 total (7 new for 05-02, 8 from 05-01)
- **Test result:** 164 passed, 1 skipped (live API)

## Accomplishments

- `competitions/ucl/src/constants.py` — UCL-specific constants: UCL_LEAGUE_ID=7, BSD_API_URL, CACHE_TTL_HOURS=1, CACHE_FILENAME
- `competitions/ucl/src/provider.py` — Two classes:
  - **RepoFixtureProvider** — loads from repo `fixtures.json`, builds FixtureSchedule via `_dict_to_schedule`, validates
  - **BSDFixtureProvider** — cache-first (TTL check via `is_cache_valid`), then fetches from BSD via `fetch_raw_matches`, filters future-dated events via `_filter_future_events`, builds schedule, validates, caches atomically via `_atomic_write_json`
- `test_provider.py` — 7 new tests across:
  - **TestRepoFixtureProvider** (3 tests): valid schedule load, missing file raises FileNotFoundError, invalid schedule raises ValueError
  - **TestBSDFixtureProvider** (4 tests): upcoming events parsed, empty response raises FixtureProviderError, only-finished events raises FixtureProviderError, cache hit skips fetch
- `conftest.py` — Added `sample_cached_fixtures` fixture for cache hit testing

## Task Commits

1. **Task 1: Create UCL provider constants module** — `af77398` (feat)
2. **Task 2: Implement BSDFixtureProvider and RepoFixtureProvider** — `f522cd3` (feat)
3. **Task 3: Add provider tests** — `b256252` (feat)

## Files Created/Modified

- `competitions/ucl/src/constants.py` — UCL_LEAGUE_ID=7, BSD_API_URL, CACHE_TTL_HOURS=1, CACHE_FILENAME
- `competitions/ucl/src/provider.py` — BSDFixtureProvider (load, cache, future-date filtering, schedule building) + RepoFixtureProvider (JSON load, schedule building) + shared _dict_to_schedule
- `competitions/ucl/tests/test_provider.py` — Added TestRepoFixtureProvider (3 tests) and TestBSDFixtureProvider (4 tests)
- `competitions/ucl/tests/conftest.py` — Added sample_cached_fixtures fixture

## Decisions Made

- **UCL constants module** follows the `competitions/worldcup/src/constants.py` pattern — keeps competition-specific config in the competition module
- **BSDFixtureProvider reuses `fetch_raw_matches()`** from `football_core/fetcher.py` rather than reimplementing HTTP retry/auth/pagination logic
- **Cache reuses `is_cache_valid()` and `_atomic_write_json()`** from `football_core/state.py` — consistent with how other caches work in the codebase (odds, Elo, CatBoost)
- **Future-date filtering** uses `datetime.now(timezone.utc)` and `datetime.fromisoformat()` for timezone-aware comparison, per Phase 5 CONTEXT.md D-10
- **Duplicate `_dict_to_schedule`** in both providers — acceptable per two-class design; shared extraction deferred until a third provider appears

## Deviations from Plan

None — plan executed exactly as written.

### Acceptance Criteria Verification

- `python -c "from competitions.ucl.src.provider import BSDFixtureProvider, RepoFixtureProvider; print('imports OK')"` — Passed
- RepoFixtureProvider.load() returns FixtureSchedule — Verified via test_loads_valid_schedule
- BSDFixtureProvider has all required methods — Verified via source grep and test suite
- BSDFixtureProvider uses `fetch_raw_matches` from `football_core.fetcher` — Verified via grep
- BSDFixtureProvider uses `is_cache_valid` and `_atomic_write_json` from `football_core.state` — Verified via grep
- Cache data structure has `expires_at`, `cached_at`, `schedule` keys — Verified via source read
- All 7 provider tests pass — Confirmed (164 total UCL tests pass)

## Issues Encountered

None.

## Next Phase Readiness

- Both provider implementations complete with 7 passing tests
- Ready for Plan 05-03: CLI Integration (--fixture-source flag, provider resolution chain, remove synthetic path)
- All integration points (main.py, build_simulation_result, CLI tests) are the target of Plan 05-03

---

*Phase: 05-official-fixture-ingestion*
*Completed: 2026-06-30*
