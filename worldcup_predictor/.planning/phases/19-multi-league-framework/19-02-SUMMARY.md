---
phase: 19-multi-league-framework
plan: 02
subsystem: cli, state, data
tags: league-framework, cli-wiring, config, migration, data-isolation
requires:
  - "19-01 (LEAGUES dict, URL builders, league_id params)"
provides:
  - "--league CLI flag with config.json persistence support"
  - "--list-leagues CLI flag for available leagues display"
  - "_resolve_league_id() with precedence CLI > config.json > DEFAULT_LEAGUE_ID"
  - "_migrate_legacy_data() with idempotency guard"
  - "data_dir threaded through all main.py state calls"
  - "data_dir scoped elo_sync and governance operations"
  - "Test coverage for CLI flags, config, migration, and backward compatibility"
affects: [19-03, 19-04, main.py state isolation]

tech-stack:
  added: []
  patterns:
    - "league_id resolved via precedence: CLI --league > config.json > DEFAULT_LEAGUE_ID"
    - "Config.json stored at DATA_DIR.parent for cross-league persistence"
    - "Legacy migration runs once per directory with .migrated sentinel"
    - "data_dir threaded as parameter through all state functions (not global)"
    - "Warnings emitted for corrupt config.json, no hard crash"

key-files:
  created:
    - tests/test_config.py - 5 tests for _resolve_league_id()
    - tests/test_migration.py - 5 tests for _migrate_legacy_data()
  modified:
    - main.py - CLI args, config.json handling, _resolve_league_id(), _migrate_legacy_data(), data_dir threading
    - src/elo_sync.py - sync_elo_from_eloratings(data_dir) param
    - src/governance.py - _run_governance(data_dir) param
    - tests/test_cli.py - 6 new test methods for --league/--list-leagues
    - tests/test_elo.py - mock fix for save_elo_update_log(data_dir) signature
    - tests/test_main_loop.py - mock fixes for load/append_prediction_history(data_dir) signature

key-decisions:
  - "base_data_dir uses local variable to handle both Path (prod) and str (test monkeypatch) types"
  - "Shared data files (bracket.json, groups.json, annex_c.json, team_aliases.json) stay in data/ without per-league dirs"
  - "CLI --league flag does NOT persist to config.json — users must edit config.json manually for permanent change"
  - "Config.json auto-created with default league_id=27 on first run if missing"
  - "Corrupt config.json triggers warning and falls back to DEFAULT_LEAGUE_ID (27)"

requirements-completed: [V2-26]
---

# Phase 19 Plan 02: Multi-League Framework — CLI Flags, Config & Legacy Migration Summary

**Wired `--league` and `--list-leagues` CLI flags, config.json precedence with auto-creation/resilience, legacy data migration with idempotency, and data_dir threading through all state calls — with full test coverage and zero regressions**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-06-20T09:22:00Z
- **Completed:** 2026-06-20T09:44:13Z
- **Tasks:** 3
- **Files created:** 2
- **Files modified:** 6
- **Test suite:** 570 passed, 0 regressions

## Accomplishments

### Task 1: CLI flags & config.json (commit `7630e09`)
- `--league` CLI flag with argparse for per-session league override
- `--list-leagues` flag for displaying available leagues
- `_resolve_league_id()` with strict precedence: CLI > config.json > DEFAULT_LEAGUE_ID (27)
- Config.json auto-created at `DATA_DIR.parent / "config.json"` on first run with `{"league_id": 27}`
- Corrupt/unparseable config.json → warning printed, fallback to DEFAULT_LEAGUE_ID
- `--list-leagues` early-exit in `main()` before iteration begins

### Task 2: Legacy migration & data_dir threading (commit `9586653`)
- `_migrate_legacy_data(league_id, data_dir)` copies `teams.json`, `played.json`, `played_groups.json`, `signal_cache/`, `prediction_history.json` from `data/` to `data/{league_id}/`
- `.league_{league_id}_migrated` sentinel file ensures idempotency
- `league_id` guard: skips migration if league_id == DEFAULT_LEAGUE_ID
- Threaded `data_dir` through all 7 helper functions: `_load_calibration`, `_run_prediction_round`, `_run_historical_catch_up`, `_run_iteration`, `_load_state`, `_save_state`, `_run_elo_sync`
- Threaded `data_dir` through `elo_sync.sync_elo_from_eloratings()`
- Threaded `data_dir` through `governance._run_governance()`
- All call sites in `main()` pass the resolved `data_dir` from `main()`'s body

### Task 3: Tests (commit `a87c45e`)
- **test_cli.py**: 6 new tests — `test_league_flag_override`, `test_league_default`, `test_list_leagues_flag`, `test_league_from_config`, `test_config_auto_create`, `test_list_leagues_exits`
- **test_config.py** (new): 5 tests — `test_resolve_cli_overrides_config`, `test_resolve_config_overrides_default`, `test_resolve_default_fallback`, `test_config_auto_created_on_first_run`, `test_resolve_corrupt_config_fallbacks`
- **test_migration.py** (new): 5 tests — `test_migration_copies_teams`, `test_migration_skips_default_league`, `test_migration_idempotency`, `test_migration_missing_data_dir`, `test_migration_partial_data`
- **test_elo.py**: Fixed `save_elo_update_log` mock to accept `data_dir` kwarg
- **test_main_loop.py**: Fixed `load_prediction_history` and `append_prediction_history` mocks for `data_dir` kwarg

## Task Commits

Each task was committed atomically:

1. **Task 1: CLI flags & config.json** — `7630e09` (feat)
2. **Task 2: Legacy migration & data_dir threading** — `9586653` (feat)
3. **Task 3: Tests for CLI, config, migration + mock fixes** — `a87c45e` (test)

## Files Created/Modified

### Created
- `tests/test_config.py` — 5 tests for `_resolve_league_id()` precedence, auto-creation, corrupt config fallback
- `tests/test_migration.py` — 5 tests for `_migrate_legacy_data()` copy logic, idempotency, skip conditions

### Modified
- `main.py` — Added `--league`, `--list-leagues` argparse; `_resolve_league_id()`; `_migrate_legacy_data()`; `data_dir` param on all helper functions; config.json auto-create and read
- `src/elo_sync.py` — `sync_elo_from_eloratings()` now accepts `data_dir` param
- `src/governance.py` — `_run_governance()` now accepts `data_dir` param
- `tests/test_cli.py` — 6 new test methods for CLI flag behavior
- `tests/test_elo.py` — Mock signature fix for `save_elo_update_log(data_dir)`
- `tests/test_main_loop.py` — Mock signature fixes for `load_prediction_history(data_dir)` and `append_prediction_history(data_dir)`

## Decisions Made

- **`base_data_dir` as local variable**: Uses a local `base_data_dir` in `_resolve_league_id()` to handle both `Path` (production, from `DATA_DIR`) and `str` (test monkeypatch remapping) types without code branches.
- **Shared data stays shared**: Bracket/groups/annex_c/aliases remain in `data/` without per-league directories — these are tournament-structure files shared across leagues.
- **CLI does not persist**: The `--league` flag overrides the session league but does NOT write back to config.json. Allowing a flag like `--league 4` to silently mutate persistent state is undesirable. Users edit config.json manually for permanent changes.
- **Corrupt config → fallback, not crash**: JSON decode error or missing `league_id` key prints a warning and falls through to `DEFAULT_LEAGUE_ID`. A previous session crash should not prevent a recovery run.
- **Sentinel-based migration idempotency**: A `.league_{league_id}_migrated` file in the destination directory prevents re-copying on subsequent runs. No checksum or timestamp comparison — simple presence check.
- **Mock signature fixes**: Two tests in `test_main_loop.py` and one in `test_elo.py` used lambda mocks without `*a, **kw` for functions that now receive `data_dir`. Fixed to use `lambda *a, **kw: ...` pattern.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Corrupt config.json resilience**
- **Found during:** Task 1
- **Issue:** Plan did not specify behavior for unparseable config.json (e.g., truncated write, JSON syntax error)
- **Fix:** Added `try/except (json.JSONDecodeError, KeyError)` in `_resolve_league_id()` — prints warning, falls back to DEFAULT_LEAGUE_ID
- **Files modified:** `main.py` (`_resolve_league_id` function)
- **Commit:** `7630e09`

**2. [Rule 2 - Missing critical] Config.json auto-creation on missing file**
- **Found during:** Task 1
- **Issue:** Plan specified "config.json already created"; but `_resolve_league_id()` would crash on `FileNotFoundError` on first run
- **Fix:** Added auto-creation: if `config.json` doesn't exist, write `{"league_id": 27}` and use DEFAULT_LEAGUE_ID
- **Files modified:** `main.py` (`_resolve_league_id` function)
- **Commit:** `7630e09`

**3. [Rule 2 - Missing critical] Idempotency guard for _migrate_legacy_data**
- **Found during:** Task 2
- **Issue:** Plan specified migration should be "safe to call multiple times" but had no guard against redundant copies
- **Fix:** Added `.league_{league_id}_migrated` sentinel file; skip if present
- **Files modified:** `main.py` (`_migrate_legacy_data` function)
- **Commit:** `9586653`

**4. [Rule 1 - Bug] Test mocks incompatible with new data_dir parameter**
- **Found during:** Task 3 (verification)
- **Issue:** `test_per_iteration_creates_history_entries` and `test_per_iteration_backfills_missing_history` in `test_main_loop.py`, plus `test_backfill_logs_elo_change` in `test_elo.py` used `lambda: []` or `lambda e: ...` mocks that don't accept the new `data_dir` kwarg
- **Fix:** Changed all `load_prediction_history` mocks to `lambda *a, **kw: []` and `append_prediction_history` mocks to `lambda e, *a, **kw: captured_entries.append(e)`
- **Files modified:** `tests/test_main_loop.py`, `tests/test_elo.py`
- **Commit:** `a87c45e`

## Issues Encountered

- **`test_backfill_logs_elo_change` (test_elo.py)**: The mock for `save_elo_update_log` was `lambda *a: None` (accepts any positional args). When the function started receiving `data_dir` as a keyword argument (`save_elo_update_log(team, change, data_dir=...)`), the lambda still worked because of `*a`. Wait — re-checking: `lambda *a: None` would NOT accept keyword args like `data_dir=...`. The original is `lambda *a, **kw: None` — correct. But `load_prediction_history` was `lambda: []` which fails with `data_dir` passed. This was the actual bug.

## Threat Surface Scan

No new security-relevant surface introduced. CLI flags use argparse (no injection risk). Config.json is read and written with explicit paths under project root (no directory traversal). Migration copies files within project directory only. `data_dir` is derived from `DATA_DIR / str(league_id)`, scoped to project paths. All new parameters are typed (`int` for league_id, `str | Path` for data_dir).

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| LEAGUES only has league 27 | src/constants.py | ~10 | BSD API not available; inherited from plan 19-01 |

## Self-Check: PASSED

- [x] `main.py` contains `_resolve_league_id()`, `_migrate_legacy_data()`, `--league`, `--list-leagues`, threaded `data_dir` params
- [x] `src/elo_sync.py` has `sync_elo_from_eloratings(data_dir)` param
- [x] `src/governance.py` has `_run_governance(data_dir)` param
- [x] `tests/test_cli.py` has 6 new test methods
- [x] `tests/test_config.py` exists with 5 tests
- [x] `tests/test_migration.py` exists with 5 tests
- [x] Commit `7630e09` exists in git log
- [x] Commit `9586653` exists in git log
- [x] Commit `a87c45e` exists in git log
- [x] `pytest tests/ -x -q --ignore=tests/test_live_smoke.py` — 570 passed

## Next Phase Readiness

- Foundation complete for Phase 19-03 (state file isolation per league — `data/{league_id}/` for all per-league state files)
- All 19-02 deliverable commits exist and verified
- Legacy data migration ensures smooth transition for existing `data/` contents
- Zero regressions across full test suite

---
*Phase: 19-multi-league-framework*
*Completed: 2026-06-20*
