---
phase: 05-official-fixture-ingestion
plan: 03
subsystem: cli
tags: cli, argparse, provider-resolution, --fixture-source, synthetic-path
requires:
  - phase: 05-official-fixture-ingestion
    plan: 02
    provides: BSDFixtureProvider, RepoFixtureProvider
provides:
  - --fixture-source CLI flag (auto/repo/bsd)
  - Provider resolution chain in main()
  - FixtureSchedule type throughout main()
  - Removal of synthetic-only execution path
affects: None (completes Phase 5)
tech-stack:
  added: logging (stdlib — no new dependencies)
  patterns: Provider resolution chain, graceful degradation in auto mode, FixtureSchedule type adaptation at build_simulation_result boundary
key-files:
  created: []
  modified:
    - competitions/ucl/main.py (fixture_source arg, provider resolution, FixtureSchedule typing)
    - competitions/ucl/tests/test_cli.py (TestFixtureSource, TestNoSyntheticPath, TestProviderResolution)
key-decisions:
  - "D-12 honored: FixtureSchedule converted to dict via asdict() at build_simulation_result boundary — engine unchanged"
  - "auto mode: try BSD, catch FixtureProviderError, log warning, fall back to RepoFixtureProvider"
  - "repo mode: always use RepoFixtureProvider regardless of API key"
  - "bsd mode: use BSDFixtureProvider, let errors propagate (no fallback)"
  - "teams_data extracted from repo fixtures.json once, reused for BSD provider construction"
requirements-completed: [UCLF-05, UCLF-08]
duration: 10 min
completed: 2026-06-30
---

# Phase 5 Plan 3: CLI Integration Summary

**--fixture-source CLI flag, provider resolution chain in main(), FixtureSchedule typing, removal of synthetic-only execution path.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-30
- **Completed:** 2026-06-30
- **Tasks:** 3
- **Files modified:** 2
- **Tests:** 172 passed, 1 skipped (live API)
- **WC regression:** 613 passed (no regressions)

## Accomplishments

- `main.py` — Added `--fixture-source` argument (default "auto", choices: auto/repo/bsd) to `_parse_args()`
- `main.py` — Provider resolution chain in `main()`:
  - **repo** mode or **auto + no API key**: uses `RepoFixtureProvider` directly
  - **auto + API key**: tries `BSDFixtureProvider`, catches `FixtureProviderError`, logs warning, falls back to `RepoFixtureProvider`
  - **bsd** mode: uses `BSDFixtureProvider`, lets errors propagate
- `main.py` — `build_simulation_result()` updated to accept `FixtureSchedule` instead of raw dict, converts via `asdict()` at the type-adaptation boundary (per D-12)
- `main.py` — `team_names` extraction uses `[t.name for t in fixtures_schedule.teams]` (attribute access, not dict)
- `main.py` — Validation section uses `asdict(fixtures_schedule)` for `fetch_ucl_matches()` compatibility
- `test_cli.py` — Added 3 new test classes (8 new tests):
  - **TestFixtureSource** (5 tests): default, repo flag, bsd flag, invalid choice, compatibility with other flags
  - **TestNoSyntheticPath** (2 tests): verifies main.py uses provider pattern, verifies build_simulation_result accepts FixtureSchedule
  - **TestProviderResolution** (1 test): verifies RepoFixtureProvider returns valid FixtureSchedule

## Task Commits

1. **Task 1: Add --fixture-source CLI flag to argparse** — included in main.py changes
2. **Task 2: Replace fixture loading block with provider resolution chain** — included in main.py changes
3. **Task 3: Add CLI tests for --fixture-source selection and verify synthetic path removed** — included in test_cli.py changes

## Files Modified

- `competitions/ucl/main.py` — `_parse_args()` gains `--fixture-source` argument; `main()` gains provider resolution chain; `build_simulation_result()` accepts `FixtureSchedule`; added `logging` import and logger
- `competitions/ucl/tests/test_cli.py` — Added TestFixtureSource (5 tests), TestNoSyntheticPath (2 tests), TestProviderResolution (1 test)

## Decisions Made

- **D-12 honored**: `FixtureSchedule` → `asdict()` → `{"schedule": asdict(fixtures)}` conversion at the `build_simulation_result()` boundary keeps the simulation engine unchanged
- **Graceful degradation in auto mode**: BSD failure logs a warning with the error message, then falls back silently to RepoFixtureProvider
- **`teams_data` loaded from repo fixtures**: Needed for BSDFixtureProvider construction (team names, pots, clubelo names, coefficients). Not used for the schedule itself when in BSD mode.
- **No `provider` variable in auto/BSD success path**: `fixtures_schedule` is set directly from `bsd_provider.load()`, avoids double-loading

## Deviations from Plan

None — plan executed exactly as written.

### Acceptance Criteria Verification

- `python -c "from competitions.ucl.main import _parse_args; a=_parse_args([]); assert a.fixture_source=='auto'"` — Passed
- `python -c "from competitions.ucl.main import _parse_args; a=_parse_args(['--fixture-source','repo']); assert a.fixture_source=='repo'"` — Passed
- `python -c "from competitions.ucl.main import _parse_args; a=_parse_args(['--fixture-source','bsd']); assert a.fixture_source=='bsd'"` — Passed
- `python -c "from competitions.ucl.main import _parse_args; _parse_args(['--fixture-source','invalid'])"` raises SystemExit — Confirmed via test
- `build_simulation_result` signature uses `fixtures: FixtureSchedule` — Confirmed via test and inspect
- Team names extracted via `t.name` from `fixtures_schedule.teams` — Confirmed via source read
- main() has provider instantiation logic for both providers — Confirmed via source read
- auto mode without api_key silently uses RepoFixtureProvider — Confirmed via source read
- bsd mode propagates FixtureProviderError — Confirmed via source read
- Full UCL test suite: 172 passed, 1 skipped — Confirmed
- WC regression suite: 613 passed — Confirmed

## Issues Encountered

- Initial implementation had a double-load bug in auto mode: `provider = bsd_provider` was set in the try block, then `provider.load()` was called again after the if/else. Fixed by setting `fixtures_schedule` directly inside the try block and removing the post-if/else `provider.load()` call.

## Next Phase Readiness

- Phase 5 **complete** — all 3 plans executed
- Ready for Phase 6 (Simulation Modes): three-mode architecture, PlayedMatches override
- FixtureProvider abstraction in `football_core/provider.py` ready for Phase 6 provider variants
- All UCL tests green (172 passed), WC regression green (613 passed)

---

*Phase: 05-official-fixture-ingestion*
*Completed: 2026-06-30*
