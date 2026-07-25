# Phase 1: Pipeline Extraction Summary

**Objective:** Extract 7 compute functions from `web/wc_app.py` into `competitions/worldcup/src/pipeline.py`, replacing original function bodies with thin import wrappers.

---

## What was created

### `competitions/worldcup/src/pipeline.py` (new, 862 lines)

Seven self-contained functions extracted from `web/wc_app.py`. Each function receives all dependencies as parameters — no module-level globals.

| # | Function | Original in wc_app.py | Key changes |
|---|----------|----------------------|-------------|
| 1 | `fetch_live_data()` | `_fetch_live_data()` (lines 668-792) | Inlined `_get_data_provider()`, parameterised `bsd_api_key`, `football_data_org_key`, `data_dir` |
| 2 | `build_chronological_matches()` | `build_chronological_matches()` (lines 215-275) | Replaced `load_json()` with direct `json.loads(path.read_text())` |
| 3 | `build_knockout_tree()` | `build_knockout_tree()` (lines 278-291) | Replaced `load_json()` with direct reads; lazy-imports `compute_full_bracket` from web |
| 4 | `collect_downstream_matches()` | `_collect_downstream_matches()` (lines 1183-1200) | Pure function — no web dependencies |
| 5 | `simulate_from_match()` | `_simulate_from_match_sync()` (lines 1093-1180) | Parameterised `data_dir`; lazy-imports `_build_engine_from_caches` from web |
| 6 | `run_simulation_compute()` | core of `_run_simulation_task()` (lines 888-1029) | Returns `dict` instead of mutating global `cache` / `active_simulations` |
| 7 | `run_calibration_compute()` | core of `_run_calibration_task()` (lines 1363-1447) | Returns `dict` instead of mutating global `active_simulations` |

## What was changed

### `web/wc_app.py` (473 lines removed, line count 1482 → 1054)

**7 function bodies replaced** with thin wrappers using lazy imports (avoids circular dependency at module-load time):

- `_fetch_live_data()` → `from competitions.worldcup.src.pipeline import fetch_live_data`
- `build_chronological_matches()` → pipeline wrapper
- `build_knockout_tree()` → pipeline wrapper
- `_run_simulation_task()` → keeps `active_simulations` mgmt + `cache` writing; delegates computation to `run_simulation_compute()`
- `_simulate_from_match_sync()` → pipeline wrapper
- `_collect_downstream_matches()` → pipeline wrapper
- `_run_calibration_task()` → keeps `active_simulations` mgmt; delegates to `run_calibration_compute()`

**Import cleanup** — removed unused imports:
- `sys`, `copy`, `requests`
- `ThreadPoolExecutor`, `FuturesTimeout`
- `HTMLResponse`, `StaticFiles`
- `PredictionContext`, `save_signal_cache`, `save_calibration_params`
- `run_calibrate_and_blend`, `_build_engine_from_caches`
- `select_advancers`, `resolve_r32_matchups`
- All 12 signal cache filename constants
- `load_json_list`

**Removed dead function:** `_get_data_provider()` — inlined into `pipeline._get_data_provider()`

## What was preserved (unchanged)

- All FastAPI routes (`/api/overview`, `/api/simulate`, `/api/calibrate`, etc.)
- `active_simulations` management and `sim_lock` threading
- Global `cache` dict and snapshot writing to disk
- Remaining web-level functions: `compute_full_bracket`, `compute_signal_eval`, `compute_overview`, `compute_bracket_display`, `compute_group_standings`, `compute_signal_stats`, `compute_signal_detail`, `compute_blend_info`, what-if engine, etc.
- `compute_team_strengths_from_predictions` remains imported from `web.engine_helpers`

## Verification

```
All pipeline imports OK
All wc_app imports OK
```

## Key decisions

1. **Lazy imports** (`import inside function body`) used in both pipeline.py (for `web.wc_app.compute_full_bracket`, `web.engine_helpers._build_engine_from_caches`) and wc_app.py (for pipeline functions) to avoid circular imports at module-load time.
2. **`run_simulation_compute` returns a result dict** rather than mutating web-layer state. The web wrapper (`_run_simulation_task`) handles `active_simulations` updates, `cache` assignment, and snapshot file writing.
3. **Architecture debt** remains in 3 function calls that still import from web modules: `compute_signal_eval`, `compute_full_bracket`, and `compute_overview` (targeted for Phase 2), plus `_build_engine_from_caches` (targeted for Phase 3).

## Commit

```
455dd63 feat(phase1-pipeline): extract compute pipeline from web.wc_app
```

## Self-Check: PASSED

- [x] All 7 pipeline functions importable
- [x] All wc_app imports work (including refactored wrappers)
- [x] Syntax check passes for both files
- [x] Commit created with all changes
