---
phase: 16-model-governance
plan: 02
subsystem: governance
tags: drift-detection, console-dashlet, brier-monitoring, orchestrator

requires:
  - phase: 16-01
    provides: version tracking functions, state persistence, governance constants
  - phase: 14-signal-blending
    provides: compute_rolling_brier, blend_weights shape
  - phase: 12b-evaluation-infrastructure
    provides: brier_score, prediction_history entry structure

provides:
  - Drift detection engine with per-signal sigma (D-09 formula)
  - Cold-start guard (< 30 matches returns None from check_drift)
  - Deduplication of prediction_history entries for accurate metrics
  - Governance dashlet display (cold-start D-17 + active D-18 formats)
  - Drift alert block showing 5 fields (signal, reference, rolling, threshold, delta)
  - _run_governance() orchestrator building D-06 run snapshots
  - _should_run_gov() with startup + hourly cadence wired into main loop
  - Version ID attachment to prediction_history entries (D-05)

affects:
  - 16-03 (Backtesting)
  - main.py startup and _run_iteration hooks

tech-stack:
  added: none (stdlib only: math)
  patterns:
    - Per-signal sigma computation (not pooled) for drift detection
    - D-09 drift formula with configurable window and sigma threshold
    - Deduplication at read time (not modifying underlying file)
    - Lazy imports in orchestrator for clean module boundaries

key-files:
  created: none
  modified:
    - src/governance.py: Added _deduplicate_history, _per_match_briers, check_drift, compute_reference_baselines, _run_governance (5 new functions)
    - src/output.py: Added print_governance_dashlet, print_drift_alert (2 new functions)
    - main.py: Added _last_gov_time, _prev_history, _prev_cal_params globals, _should_run_gov(), governance hook at line ~690, startup governance at line ~828, version ID attachment after calibrate+blend, pre-mutation capture before merge
    - tests/test_governance.py: Added 19 new tests (6 dedup + 3 per_match_briers + 6 check_drift + 1 baselines + 3 _run_governance + 3 _should_run_gov)
    - tests/test_output.py: Added 4 new tests (dashlet cold/active/drift, drift alert)

key-decisions:
  - "D-09 drift formula implemented: rolling_mean > reference_baseline + 2 * sigma, using per-signal population std"
  - "Cold-start guard at 30 matches (COLD_START_THRESHOLD) returns None from check_drift"
  - "Deduplication on match_id at governance read time only (does not modify prediction_history file)"
  - "Lazy imports inside _run_governance for clean module dependency management"
  - "D-16 frequency: startup + hourly via _should_run_gov() with _last_gov_time guard"
  - "Version IDs attached entry-level at prediction_history top level, only for entries missing them"

requirements-completed:
  - V2-12
  - V2-13

duration: 10min
completed: 2026-06-18
---

# Phase 16 Plan 02: Governance Orchestrator & Drift Detection Summary

**Drift detection engine (D-09 per-signal sigma), cold-start-protected, with startup+hourly console dashlet and run snapshots — 35 governance tests + 31 output tests, zero regressions on 493 passing tests**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-18T23:49:35Z
- **Completed:** 2026-06-18T23:59:06Z
- **Tasks:** 3 (2 TDD: RED+GREEN, 1 auto)
- **Files modified:** 5

## Accomplishments

- **Drift detection engine** (`check_drift()`) — D-09 formula with per-signal sigma, configurable window (50) and sigma threshold (2.0). Cold-start guard returns None for <30 matches. Returns structured dict with signal, rolling_mean, reference_baseline, sigma, threshold, drifted flag, delta.
- **Per-match Brier extraction** (`_per_match_briers()`) — filters by signal availability, extracts ordered Brier scores for sigma computation. Shares filtering logic with `blender.compute_rolling_brier()`.
- **Entry deduplication** (`_deduplicate_history()`) — guards against Pitfall 7 (confirmed duplicate entries in prediction_history.json). Groups by match_id, keeps last entry chronologically.
- **Reference baseline computation** (`compute_reference_baselines()`) — fixed reference per D-08, computed from all entries as overall mean Brier.
- **Governance dashlet** (`print_governance_dashlet()`) — cold-start D-17 format (version info, match count, PENDING/DISABLED/READY statuses) and active D-18 format (per-signal Brier table with drift column). Conditional drift alert section via `print_drift_alert()` with 5 aligned fields.
- **Governance orchestrator** (`_run_governance()`) — dedup → compute Brier → check drift → build D-06 snapshot → save → display. Handles cold-start, healthy, and drift states.
- **Main loop wiring** — `_should_run_gov()` for startup + hourly cadence (D-16). Pre-mutation state capture for version detection (Architecture Q4+Q5). Version ID attachment entry-level after calibrate+blend (Pitfall 1+2). Startup governance after print_header(). Governance hook in `_run_iteration()` after signal warnings.
- **Run snapshots** per D-06 schema: run_version, data_version, model_version, timestamp, signal_counts, blend_weights, per_signal_brier, blended_brier, drift_status, drift_details.
- **19 new governance tests** + **4 new output tests** — zero regressions on 493 passing tests.

## Task Commits

Each task was committed atomically (TDD RED/GREEN for Tasks 1-2):

1. **Task 1 RED: Add failing tests for drift detection functions** — `487ff82` (test)
2. **Task 1 GREEN: Implement drift detection functions** — `38199a3` (feat)
3. **Task 2 RED: Add failing tests for governance dashlet and drift alert** — `9cd8ed8` (test)
4. **Task 2 GREEN: Implement governance dashlet and drift alert display** — `4456d7f` (feat)
5. **Task 3: Build governance orchestrator + wire into main loop** — `e713a65` (feat)

## Files Created/Modified

- `src/governance.py` — Added `_deduplicate_history()`, `_per_match_briers()`, `check_drift()`, `compute_reference_baselines()`, `_run_governance()` (+ math import, + brier_score import)
- `src/output.py` — Added `print_governance_dashlet()`, `print_drift_alert()` (2 new functions, 113 lines)
- `main.py` — Added `_last_gov_time`, `_prev_history`, `_prev_cal_params` globals, `_should_run_gov()`, governance hook at line ~690, startup governance at line ~828, version ID attachment after calibrate+blend, pre-mutation capture before merge (+40 lines)
- `tests/test_governance.py` — 19 new tests: 6 dedup tests, 3 per_match_briers tests, 6 check_drift tests (healthy/drifted/cold_start/sigma), 1 baselines test, 3 _run_governance tests (shape/cold_start/healthy), 3 _should_run_gov tests (startup/hourly/within)
- `tests/test_output.py` — 4 new tests: dashlet cold_start, dashlet active, dashlet drift format, drift alert format

## Decisions Made

- **D-09 drift formula**: `rolling_mean > reference_baseline + 2 * sigma` with population std per-signal. Verified that the 2-sigma threshold correctly handles high-variance signals (Pitfall 3 prevention).
- **Cold-start guard**: `check_drift()` returns `None` for < 30 matches. The orchestrator sets `drift_status = "COLD_START"` and dashlet shows "COLD START" with DISABLED drift check.
- **Deduplication at read time**: `_deduplicate_history()` groups by match_id, keeps last entry. Does NOT modify the underlying prediction_history.json file (Pitfall 7 fix).
- **Lazy imports**: `_run_governance()` imports `compute_rolling_brier`, `save_run_snapshot`, and `print_governance_dashlet` inside the function body to maintain clean module boundaries.
- **Main loop timing**: Pre-mutation capture happens AFTER signal computation but BEFORE merge. Governance hook runs after signal warnings but BEFORE simulation. Startup governance runs after print_header() but BEFORE first `_run_iteration()`. Version IDs attached after calibrate+blend but before signal warning aggregation.
- **Snapshot storage**: Run snapshots saved to `data/runs/` via existing `state.save_run_snapshot()` with retention enforcement.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- **Pre-existing failures**: `test_main_loop_clean_shutdown` (Windows signal handling) and `test_teams_json_exists_and_valid` (float vs int assertion) are documented pre-existing issues, not regressions from this plan.

## Threat Surface

All mitigations from threat register T-16-03 (deduplication at governance read time) and T-16-04 (try/except around governance hook in main.py) are implemented. No new threat surface introduced — all functions operate on local JSON data with no network, auth, or user input.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- V2-12 (version tracking) — complete (16-01 + 16-02 wiring)
- V2-13 (drift detection) — complete: check_drift(), dashlet display, run snapshots
- V2-14 (backtesting) — next plan (16-03)
- Ready for Plan 16-03: Backtesting framework

## Self-Check: PASSED

- [x] `src/governance.py` has `_run_governance()`, `check_drift()`, `_per_match_briers()`, `compute_reference_baselines()`, `_deduplicate_history()`
- [x] `src/output.py` has `print_governance_dashlet()` + `print_drift_alert()`
- [x] `main.py` has governance hook in `_run_iteration()` (line ~690) and startup governance init (line ~828)
- [x] Per-entry version IDs attached to prediction_history entries
- [x] Run snapshots saved via `state.save_run_snapshot()`
- [x] D-16 frequency enforced (startup + hourly, not every heartbeat)
- [x] 35 governance tests pass, 31 output tests pass, 493 total passing (0 regressions)
- [x] 5 commits: test(16-02) → feat(16-02) → test(16-02) → feat(16-02) → feat(16-02) (TDD RED/GREEN for Tasks 1-2)

---

*Phase: 16-Model-Governance*
*Completed: 2026-06-18*
