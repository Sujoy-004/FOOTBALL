---
phase: 5
plan: architectural-refactoring
subsystem: ucl
tags: [refactoring, pipeline, extraction, delegation]
requires: [4-consolidation]
provides: [pipeline-layer]
affects: [web/ucl_app.py, competitions/ucl/src/orchestrator.py]
tech-stack:
  added: [competitions/ucl/src/pipeline.py]
  patterns: [pure-functions, dependency-injection, delegation-wrappers]
key-files:
  created:
    - competitions/ucl/src/pipeline.py
  modified:
    - competitions/ucl/src/orchestrator.py
    - web/ucl_app.py
decisions:
  - "BSDDataProvider used instead of nonexistent BSDUCLDataProvider"
  - "team_aliases param added to run_mc_simulation and orchestrator functions"
  - "_was_in_semis/_was_in_qf helpers added to run_deterministic_compute"
metrics:
  duration: "~15 min"
  completed_date: "2026-07-25"
---

# Phase 5: Architectural Refactoring — Pipeline Extraction Summary

Extracted ~680 lines of pure computation from `web/ucl_app.py` (1583 → 837 lines) into `competitions/ucl/src/pipeline.py` and refactored `competitions/ucl/src/orchestrator.py`.

## What Was Done

### 1. Created `competitions/ucl/src/pipeline.py` (706 lines)

14 self-contained functions extracted from `ucl_app.py`, each accepting all dependencies as parameters:

| # | Function | Original Lines | Description |
|---|----------|---------------|-------------|
| 1 | `fetch_ucl_managers()` | 142-180 | BSD manager data fetch with team aliases |
| 2 | `compute_deterministic_standings()` | 383-436 | League standings from finished results |
| 3 | `build_deterministic_bracket()` | 448-511 | Knockout bracket display |
| 4 | `compute_signal_eval()` | 514-568 | Signal accuracy vs real results |
| 5 | `fetch_live_data()` | 183-360 | Live match data fetch + persist (returns stats, no web globals) |
| 6 | `load_results()` | 363-370 | JSON file loader |
| 7 | `load_knockout_results()` | 373-380 | JSON file loader |
| 8 | `build_league_matchdays()` | 439-445 | Group results by matchday |
| 9 | `ucl_form_trend()` | 1282-1296 | Last 5 results for a team |
| 10 | `ucl_head_to_head()` | 1299-1316 | H2H stats between two teams |
| 11 | `ucl_outcome_dist()` | 1319-1331 | Outcome distribution from blended prob |
| 12 | `ucl_insight_text()` | 1334-1358 | Natural-language match insight |
| 13 | `run_mc_simulation()` | 933-1078 | Full MC simulation pipeline |
| 14 | `run_calibration_task()` | 1126-1173 | Calibration against replay data |

### 2. Extended `competitions/ucl/src/orchestrator.py` (+312 lines)

Added two orchestrator functions:
- **`run_deterministic_compute()`** — Orchestrates deterministic computation from real results, delegates to pipeline functions. Accepts `data_dir`, `bsd_api_key`, `football_data_org_key`, `team_aliases`.
- **`run_compute_all()`** — Dispatches to results mode (when results.json + knockout_results.json exist) or simulation mode. Builds signal stats, bracket views, playoff display, odds display.

Both functions use `boot_step` from `web.common` for step logging and return structured dicts with a `boot` key.

### 3. Refactored `web/ucl_app.py` (-746 lines)

Replaced 16 function bodies with thin delegation wrappers:

- 11 pipeline wrappers: `_fetch_ucl_managers`, `_load_results`, `_load_knockout_results`, `_compute_deterministic_standings`, `_build_league_matchdays`, `_build_deterministic_bracket`, `_compute_signal_eval`, `_ucl_form_trend`, `_ucl_head_to_head`, `_ucl_outcome_dist`, `_ucl_insight_text`
- 2 orchestrator wrappers: `deterministic_compute`, `compute_all`
- 1 combined wrapper: `_run_mc_simulation` (pipeline call + snapshot.json write)
- 1 calibration wrapper: `_run_calibration_task` (pipeline call + thread state)
- Remain unchanged: `_fetch_live_data`, `_get_ucl_data_provider`, `_parse_what_if_scenario`, `_was_in_semis`, `_was_in_qf`, all API routes

## Line Counts Before/After

| File | Before | After | Delta |
|------|--------|-------|-------|
| `web/ucl_app.py` | 1583 | 837 | -746 |
| `competitions/ucl/src/pipeline.py` | — | 706 | +706 (new) |
| `competitions/ucl/src/orchestrator.py` | 369 | 592 | +223 |
| **Total** | 1952 | 2135 | +183 |

## Deviations from Plan

### [Rule 2 - Missing Functionality] Added team_aliases parameter to orchestration functions

**Found during:** Step 2 (orchestrator extension)
**Issue:** `fetch_ucl_managers()` in pipeline needs `team_aliases` to map BSD API team names to internal names, but `run_mc_simulation` and orchestrator functions had no way to pass it through.
**Fix:** Added `team_aliases: dict[str, str] | None = None` parameter to `run_mc_simulation()`, `run_deterministic_compute()`, and `run_compute_all()`. The ucl_app.py wrappers pass `_BSD_TEAM_ALIASES` through.
**Files modified:** `competitions/ucl/src/pipeline.py`, `competitions/ucl/src/orchestrator.py`, `web/ucl_app.py`

### [Rule 2 - Missing Functionality] Fixed BSD provider class reference

**Found during:** Step 1 (pipeline creation)
**Issue:** Plan specified `BSDUCLDataProvider` from `football_core.data_providers.bsd_ucl_provider` but that class/file doesn't exist. The actual class is `BSDDataProvider` from `football_core.data_providers.bsd_provider`.
**Fix:** Used `BSDDataProvider` directly.
**Files modified:** `competitions/ucl/src/pipeline.py`

### [Rule 2 - Missing Critical Functionality] Added _was_in_semis/_was_in_qf checks

**Found during:** Step 2
**Issue:** `run_deterministic_compute` in orchestrator didn't include the `_was_in_semis`/`_was_in_qf` checks for `sf_prob`/`qf_prob` odds display, unlike the original `deterministic_compute()` in ucl_app.py.
**Fix:** Added internal helper functions inside `run_deterministic_compute`.
**Files modified:** `competitions/ucl/src/orchestrator.py`

## Verification Results

```
pipeline imports: OK
orchestrator imports: OK
ucl_app app: OK
All 21 API routes preserved
```

## Self-Check: PASSED

- [x] pipeline.py created (706 lines, 14 functions)
- [x] orchestrator.py extended (run_deterministic_compute + run_compute_all)
- [x] ucl_app.py refactored (16 delegation wrappers, 1583 → 837 lines)
- [x] All module-level globals preserved (BSD_API_KEY, DATA_DIR, _BSD_TEAM_ALIASES)
- [x] All API routes preserved
- [x] pipeline imports OK
- [x] orchestrator imports OK
- [x] ucl_app imports OK
- [x] 3 atomic commits created
