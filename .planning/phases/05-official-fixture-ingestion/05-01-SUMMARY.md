---
phase: 05-official-fixture-ingestion
plan: 01
subsystem: provider
tags: protocol, dataclass, validation, pytest, bsd-api

# Dependency graph
requires:
  - phase: 04-validation-production-readiness
    provides: BSD fetcher, validation pipeline, test infrastructure
provides:
  - FixtureProvider Protocol contract for provider implementations
  - FixtureSchedule/Team/Match dataclass schemas
  - FixtureSchedule.validate() wiring to existing validate_ucl_fixtures()
  - BSD API snapshot response for offline unit tests
  - bsd_live skip marker for conditional integration tests
  - Test scaffold for Protocol conformance and validation
affects: 05-02, 05-03, Phase 6

# Tech tracking
tech-stack:
  added: dataclasses, typing.Protocol (stdlib — no new dependencies)
  patterns: FixtureProvider Protocol pattern, FixtureSchedule manual validation delegate pattern

key-files:
  created:
    - football_core/provider.py
    - competitions/ucl/tests/fixtures/bsd_response.json
    - competitions/ucl/tests/test_provider.py
  modified:
    - competitions/ucl/tests/conftest.py

key-decisions:
  - "FixtureProvider as typing.Protocol with @runtime_checkable for structural subtyping"
  - "FixtureSchedule.validate() delegates to existing validate_ucl_fixtures() via inline import to avoid circular dependency"
  - "BSD snapshot built with 4 upcoming + 2 finished events, using BSD-form team names"

patterns-established:
  - "Provider stub + isinstance() check for Protocol conformance testing"
  - "Manual FixtureSchedule construction from JSON for validation tests before provider implementations exist"

requirements-completed: [UCLF-03, UCLF-04, UCLF-07]

# Metrics
duration: 12 min
completed: 2026-06-29
---

# Phase 5 Plan 1: Interface Contracts Summary

**FixtureProvider Protocol contract, shared dataclass schemas (FixtureSchedule/Team/Match), validation wiring to existing validate_ucl_fixtures(), BSD API snapshot fixture, and Protocol conformance + validation test scaffold**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-29T16:34:17Z
- **Completed:** 2026-06-29T16:46:30Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- `football_core/provider.py` — FixtureProvider Protocol, FixtureSchedule/Team/Match dataclasses, FixtureProviderError, FixtureSchedule.validate() delegating to existing 166-line validate_ucl_fixtures()
- `bsd_response.json` — 6 BSD API events (4 upcoming, 2 finished) in documented BSD response shape for deterministic offline unit tests
- `conftest.py` — `bsd_live` skipif marker, `bsd_response_data` fixture, `sample_36_teams_data` fixture for building Team dataclass instances
- `test_provider.py` — 8 passing tests across TestFixtureProviderProtocol (4 tests: is_protocol, has_load, bsd_conforms, repo_conforms) and TestFixtureScheduleValidation (4 tests: valid_passes, invalid_teams, invalid_matchdays, delegation)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create FixtureProvider Protocol, FixtureSchedule dataclasses, and FixtureProviderError** - `aa6d06f` (feat)
2. **Task 2: Create BSD snapshot test fixture + conftest extensions** - `b2e2f91` (test)
3. **Task 3: Create test_provider.py with Protocol conformance and FixtureSchedule validation tests** - `2351e94` (test)

**Plan metadata:** `docs(05-01): complete interface contracts plan`

## Files Created/Modified
- `football_core/provider.py` — FixtureProvider Protocol (runtime_checkable), Team/Match/FixtureSchedule dataclasses, FixtureProviderError, FixtureSchedule.validate()
- `competitions/ucl/tests/fixtures/bsd_response.json` — 6 BSD API events in snapshot format (4 upcoming, 2 finished)
- `competitions/ucl/tests/conftest.py` — Added `bsd_live` skipif marker, `bsd_response_data` fixture, `sample_36_teams_data` fixture
- `competitions/ucl/tests/test_provider.py` — 8 tests across 2 classes: TestFixtureProviderProtocol, TestFixtureScheduleValidation

## Decisions Made
- **FixtureProvider as Protocol (not ABC):** Structural subtyping means any class with a `load() -> FixtureSchedule` method automatically conforms without explicit inheritance. Phase 6 provider variants can be added without modifying the interface module.
- **Inline import in validate():** `from competitions.ucl.src.validation import validate_ucl_fixtures` is inside the method body, not at module level. This avoids a circular import risk (provider.py → validation.py → ... → provider.py) and keeps the import lazy.
- **BSD response uses BSD-form team names:** "Manchester City" (BSD form) not "Man City" (canonical form) — matches what the real API returns, making the snapshot a faithful offline replica.
- **Manual schedule construction in tests:** TestFixtureScheduleValidation builds from JSON directly rather than depending on provider implementations that don't exist yet (Plan 05-02).

## Deviations from Plan

None - plan executed exactly as written.

### Acceptance Criteria Verification
- `python -c "from football_core.provider import FixtureProvider, FixtureSchedule, Team, Match, FixtureProviderError; print('imports OK')"` — Passed
- FixtureSchedule.validate() calls validate_ucl_fixtures() — Verified via source grep
- FixtureProvider is runtime_checkable Protocol — Verified via `_is_protocol` and `_is_runtime_protocol` attributes
- `bsd_response.json` exists with 3+ events — 6 events (4 upcoming, 2 finished)
- conftest.py has bsd_live, bsd_response_data, sample_36_teams_data — All verified
- All 8 tests in test_provider.py pass — Confirmed

## Issues Encountered
- Python 3.11 `@runtime_checkable` uses `_is_runtime_protocol` rather than `__protocol__` as the sentinel attribute. The acceptance criteria's `hasattr(FixtureProvider, '__protocol__')` check doesn't work on 3.11+; using `_is_protocol` and `_is_runtime_protocol` instead while preserving the same semantic check.

## Next Phase Readiness
- Interface contracts complete and verified with 8 passing tests
- Ready for Plan 05-02: BSDFixtureProvider and RepoFixtureProvider implementations
- Test scaffold (bsd_response.json, conftest fixtures, test_provider.py) ready for provider tests

---

*Phase: 05-official-fixture-ingestion*
*Completed: 2026-06-29*
