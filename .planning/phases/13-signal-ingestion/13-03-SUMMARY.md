---
phase: 13-signal-ingestion
plan: 03
subsystem: evaluation
tags: migration, brier, signal, prediction-history, evaluation, main-loop
requires:
  - phase: 12b-evaluation-infrastructure
    provides: prediction_history, evaluate_all_matches, brier_score
  - phase: 13-signal-ingestion
    provides: odds cache, catboost cache, fetch_and_cache functions
provides:
  - prediction_history compound schema migration (flat→compound)
  - per-signal evaluation via evaluate_all_matches(signal_name=...)
  - _merge_signals_into_history() data flow wiring
  - main.py signal startup fetch + per-iteration TTL refresh
  - aggregated availability warnings per D-09
affects:
  - 14-signal-blending
  - 16-model-governance
  - 17-output-enhancement
tech-stack:
  added: []
  patterns:
    - Compound signal entry schema (D-01)
    - Per-signal evaluation via signal_name parameter (D-11)
    - Graceful degradation for signal fetch failures (D-07/D-08)
key-files:
  created: []
  modified:
    - src/state.py
    - src/evaluation.py
    - main.py
    - data/prediction_history.json
    - tests/test_state.py
    - tests/test_evaluation.py
    - tests/test_main_loop.py
key-decisions:
  - "migrate_prediction_history() is idempotent — detects flat entries by 'signal' key"
  - "evaluate_all_matches(signal_name=None) default returns multi-signal report per D-11"
  - "evaluate_all_matches(signal_name='elo') produces compound entries (signals dict, no flat keys)"
  - "_merge_signals_into_history() is the critical data flow — injects cache data into prediction_history"
  - "Odds refresh reuses existing BSD events (no extra API call); CatBoost needs dedicated API call"
  - "All signal fetches wrapped in try/except — never blocks prediction loop"
patterns-established:
  - "Compound entries store per-signal data under signals.{name} dicts"
  - "Elapsed signals (market_odds, catboost, blended) read from prediction_history; elo replayed through pipeline"
  - "D-09 aggregated warnings printed once per poll cycle"
requirements-completed:
  - V2-05
  - V2-06
duration: Xmin
completed: 2026-06-16
---

# Phase 13 Plan 03: Wiring Summary

**Prediction history schema migration, per-signal evaluation with multi-signal default (D-11), and main.py signal wiring with TTL-based refresh and aggregated availability warnings**

## Performance

- **Duration:** [duration]
- **Started:** 2026-06-16T06:00:00Z (approx)
- **Completed:** 2026-06-16T[time]Z
- **Tasks:** 3 (6 commits across TDD cycles)
- **Files modified:** 7

## Accomplishments

- `migrate_prediction_history()` converts 429 flat entries to compound format (D-01) — idempotent, preserves team_a_elo/team_b_elo inside signals.elo dict
- `evaluate_all_matches(signal_name=None)` returns multi-signal report with all available signal keys (D-11)
- `evaluate_all_matches(signal_name="elo")` replays matches and produces compound entries
- `evaluate_all_matches(signal_name="market_odds"/"catboost")` reads from prediction_history compound entries
- `_merge_signals_into_history()` injects odds/catboost cache data into prediction_history — the critical data flow that prevents evaluate_all_matches from returning n_matches=0
- Startup sequence: migration → CatBoost fetch → merge → Elo sync
- Per-iteration: odds refresh from existing events (no extra API), CatBoost refresh if TTL expired, merge into history, aggregated warnings (D-09)
- All signal fetches wrapped in try/except — never blocks prediction loop

## Task Commits

Each task was committed atomically (TDD tasks have RED + GREEN commits):

1. **Task 1: migrate_prediction_history()** — `2d2e105` (test: RED) + `e384a27` (feat: GREEN)
2. **Task 2: evaluate_all_matches signal_name** — `91de3a2` (test: RED) + `ad906b1` (feat: GREEN)
3. **Task 3: main.py signal wiring** — `11d1021` (feat: GREEN)

## Files Created/Modified

- `src/state.py` — Added `migrate_prediction_history()` function (flat→compound conversion, idempotent)
- `src/evaluation.py` — Extended `evaluate_all_matches()` with `signal_name` parameter; default `None` returns multi-signal report per D-11; `"elo"` mode produces compound entries
- `main.py` — Added `_merge_signals_into_history()`, imports for odds/catboost/signal cache, startup migration + CatBoost fetch, per-iteration signal refresh + merge + aggregated warnings
- `data/prediction_history.json` — Migrated from flat to compound format (429 entries)
- `tests/test_state.py` — Added `TestMigratePredictionHistory` (6 tests)
- `tests/test_evaluation.py` — Added `TestEvaluateAllMatchesSignalName` (7 tests); updated existing tests for new default
- `tests/test_main_loop.py` — Updated assertion for compound entry format

## Decisions Made

- **D-01 compliance:** All new prediction history entries use compound format with nested signals dict
- **D-11 compliance:** `evaluate_all_matches(signal_name=None)` iterates all compound entry signal keys
- **Migration idempotent:** Detects flat entries by top-level `"signal"` key; already-compound entries untouched
- **Elo replay produces compound entries:** No top-level `"prediction"` or `"signal"` keys
- **Graceful degradation:** All signal fetches wrapped in `try/except` — failure prints warning, never crashes
- **Aggregated warnings (D-09):** `"⚠ Market odds unavailable for N match(es)"` format per poll cycle

## Deviations from Plan

None - plan executed as written with appropriate adjustments for existing code patterns.

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added system import for state module in merge function**
- **Found during:** Task 3
- **Issue:** `_merge_signals_into_history()` initially used direct `load_prediction_history` imports from `from src.state import`, but the function lives in main.py which already imports `state` as a module. Used `state.load_prediction_history()` and `state.save_prediction_history()` for consistency.
- **Fix:** Used module-qualified calls `state.load_prediction_history()`, `state.save_signal_cache()` etc.
- **Files modified:** main.py
- **Verification:** 387 tests pass
- **Committed in:** 11d1021

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Minor code-style alignment. No behavior change.

## Issues Encountered

None

## Next Phase Readiness

- Phase 13 complete — all 3 plans (odds, catboost, wiring) executed
- prediction_history data migrated to compound format with 429 entries
- Per-signal evaluation framework ready for Phase 14 (blending)
- `evaluate_all_matches(signal_name=None)` provides multi-signal reports for blender weight computation
- Ready for Phase 14: Signal Blending

---

*Phase: 13-signal-ingestion*
*Completed: 2026-06-16*
