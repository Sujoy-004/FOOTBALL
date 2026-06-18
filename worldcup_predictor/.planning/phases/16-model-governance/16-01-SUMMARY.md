---
phase: 16-model-governance
plan: 01
subsystem: governance
tags: versioning, governance, state-persistence

requires:
  - phase: 12b-evaluation-infrastructure
    provides: prediction_history entry structure, Brier/log-loss
  - phase: 14-signal-blending
    provides: calibration params shape, rolling Brier pattern
  - phase: 15-context-signals
    provides: form/lineup signal keys, signal lineup

provides:
  - Three-version tracking (data_version, model_version, run_version) in data/versions.json per D-01–D-07
  - 6 governance constants in src/constants.py
  - 6 state persistence functions in src/state.py (load_versions, save_versions, save_run_snapshot, load_run_snapshot, load_backtest_report, save_backtest_report)
  - Governance module src/governance.py with 4 pure version computation functions
  - Version increment logic: data_version increments per D-02 (new match / new signal only), model_version per D-03 (signal change / calibration refit), run_version per D-04 (ISO 8601 timestamp)

affects:
  - 16-02 (Governance orchestrator + drift detection)
  - 16-03 (Backtesting framework)
  - main.py startup and _run_iteration hooks

tech-stack:
  added: none (stdlib only: json, os, tempfile, pathlib, datetime)
  patterns:
    - Pure-data version computation functions (no I/O)
    - _atomic_write_json for atomic file persistence
    - Graceful bootstrap for missing versions.json (D0/M0/R0)
    - Retention enforcement for run snapshots (trim to GOV_RUN_SNAPSHOT_RETENTION)
    - Windows-safe run_id filenames (colons replaced with hyphens)

key-files:
  created:
    - src/governance.py: Pure version computation (4 functions, 167 lines)
    - tests/test_governance.py: 16 tests covering persistence + increment logic
  modified:
    - src/constants.py: Added 6 governance constants (GOV_DATA_FILE, GOV_RUNS_DIR, GOV_INTERVAL_HOURS, GOV_DRIFT_SIGMA_THRESHOLD, GOV_BACKTEST_TOURNAMENTS, GOV_RUN_SNAPSHOT_RETENTION)
    - src/state.py: Added 6 governance persistence functions (load_versions, save_versions, save_run_snapshot, load_run_snapshot, load_backtest_report, save_backtest_report)

key-decisions:
  - "D-01 through D-07: Three-version approach (data/model/run), D-02 increment conditions (new match OR new signal only), D-03 increment conditions (signal change OR calibration refit), D-04 run_version as ISO 8601 timestamp, D-06 run snapshot schema, D-07 versions.json file format"
  - "Run ID filenames sanitize colons to hyphens for Windows compatibility"
  - "Version increment functions are pure (no I/O) — state.py handles all persistence"
  - "Calibration_changed flag computed externally by comparing old/new calibration_params dict equality"

requirements-completed:
  - V2-12

duration: 6min
completed: 2026-06-18
---

# Phase 16 Plan 01: Version Tracking Foundation Summary

**Three-version tracking (data_version, model_version, run_version) with pure-data increment logic, state persistence, and 16 passing tests — 0 regressions on 469+ existing tests**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-18T23:37:05Z
- **Completed:** 2026-06-18T23:43:05Z
- **Tasks:** 2 (each TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments

- **6 governance constants** in `constants.py` — GOV_DATA_FILE, GOV_RUNS_DIR, GOV_INTERVAL_HOURS, GOV_DRIFT_SIGMA_THRESHOLD, GOV_BACKTEST_TOURNAMENTS, GOV_RUN_SNAPSHOT_RETENTION
- **6 persistence functions** in `state.py` — `load_versions()` with graceful bootstrap (D0/M0/R0 defaults), `save_versions()` atomic write, `save_run_snapshot()` with retention enforcement, `load_run_snapshot()`, `load_backtest_report()` returning None on missing file, `save_backtest_report()` atomic write
- **4 pure version functions** in `governance.py` — `_compute_data_version()` increments per D-02 (set-diff for new match_ids, signal-key comparison for new signals), `_compute_model_version()` increments per D-03 (signal lineup change or calibration refit), `_compute_run_version()` returns ISO 8601 timestamp, `_maybe_update_versions()` orchestrator with timestamp tracking
- **16 tests** in `test_governance.py` — 6 persistence tests (load/save round-trips, graceful bootstrap, missing file returns None, runs dir auto-creation), 8 version increment tests (data_version new match/signal/no-change/no-merge, model_version signal/calibration/no-change/values, run_version format), 2 model_version edge cases
- **Windows-safe filenames** — colons in ISO 8601 timestamps replaced with hyphens for filesystem compatibility

## Task Commits

Each task was committed atomically following TDD RED/GREEN protocol:

1. **Task 1 RED: Add failing tests for version persistence functions** — `9ef69ff` (test)
2. **Task 1 GREEN: Implement version persistence functions** — `4962ea0` (feat)
3. **Task 2 RED: Add failing tests for version increment logic** — `a79eb36` (test)
4. **Task 2 GREEN: Implement version increment logic** — `e72609e` (feat)

## Files Created/Modified

- `src/constants.py` — Added 6 governance constants after existing LINEUP_CACHE_FILE
- `src/state.py` — Added 6 governance functions before Helpers section, following `_atomic_write_json` and graceful bootstrap patterns
- `src/governance.py` — New module with 4 pure-data version computation functions
- `tests/test_governance.py` — 16 tests covering persistence round-trips, graceful bootstrap, version increment conditions

## Decisions Made

- **Windows-safe filenames**: ISO 8601 run_version timestamps contain colons which are invalid in Windows filenames. Replaced with hyphens in the storage path while preserving the original value in snapshot data.
- **Pure increment functions**: All version computation is stateless (no I/O). `calibration_changed` flag is passed from outside where the caller compares old/new `calibration_params.json` dicts.
- **Retention enforcement**: After saving each run snapshot, if count > 1000 (GOV_RUN_SNAPSHOT_RETENTION), oldest files are deleted by sorting ISO-timestamp filenames chronologically.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- **Windows colon-in-filename error**: `tempfile.mkstemp` prefix used the ISO 8601 run_id directly (containing colons), causing `OSError: [Errno 22] Invalid argument` on Windows. Fixed by sanitizing colons to hyphens in the filename construction.
- **Pre-existing test failures**: `test_main_loop_clean_shutdown` (Windows signal handling) and `test_teams_json_exists_and_valid` (float vs int assertion) are documented pre-existing issues, not regressions.

## Threat Surface

No new threat surface introduced — governance functions are pure data computations with no network, auth, or user input handling. Threat model T-16-01 (JSON parse corruption returns default dict) and T-16-02 (no loops in increment logic, O(n) bounded) both satisfied.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Version tracking foundation complete (V2-12 D-01 through D-07)
- Ready for Plan 16-02: Governance orchestrator + drift detection + dashlet
- All 4 governance.py functions ready to be wired into main.py startup and `_run_iteration()`

## Self-Check: PASSED

- [x] `src/constants.py` exists with 6 governance constants
- [x] `src/state.py` exists with 6 governance persistence functions
- [x] `src/governance.py` exists with 4 pure version computation functions
- [x] `tests/test_governance.py` exists with 16 passing tests
- [x] 4 commits: test(16-01) → feat(16-01) → test(16-01) → feat(16-01) (RED/GREEN per task)
- [x] Zero regressions on 469+ existing tests (2 pre-existing failures unchanged: Windows signal handling, float vs int assertion)

---

*Phase: 16-Model-Governance*
*Completed: 2026-06-18*
