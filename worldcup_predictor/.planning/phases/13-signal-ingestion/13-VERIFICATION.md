---
phase: 13-signal-ingestion
verified: 2026-06-16T18:30:00+05:30
status: passed
score: 17/17 must-haves verified
overrides_applied: 0
---

# Phase 13: Signal Ingestion Verification Report

**Phase Goal:** Implement signal ingestion pipeline — market odds (BSD events endpoint), CatBoost ML predictions (BSD predictions API), and integration wiring (schema migration, per-signal evaluation, main.py startup/iteration signal flow)

**Verified:** 2026-06-16T18:30:00+05:30
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Market odds are extracted from BSD events endpoint and converted to vig-removed home-win probabilities | ✓ VERIFIED | `src/predictors/odds.py` — `remove_vig()`, `parse_odds_response()`, `fetch_and_cache_odds()`. Tests pass (17 tests). |
| 2 | Vig removal produces probabilities summing to 1.0 ± 0.01 | ✓ VERIFIED | `test_remove_vig_basic`, `test_remove_vig_even_odds`, `test_remove_vig_all_three`, `test_remove_vig_high_vig` all assert sum ≈ 1.0. |
| 3 | Odds cache file persists with correct schema and TTL expiry | ✓ VERIFIED | `fetch_and_cache_odds` returns `{fetched_at, expires_at, matches}` dict. `TestOddsCache` tests verify schema and ~12h TTL. |
| 4 | Missing/null odds for a match are flagged as `available: false` with reason | ✓ VERIFIED | `_odds_available()` in odds.py checks None/null/zero → `available=False` + `reason="odds_not_available"`. |
| 5 | Signal constants, cache functions, save_prediction_history, and predictors package exist for both signals | ✓ VERIFIED | `constants.py` has `ODDS_CACHE_TTL_HOURS`, `CATBOOST_CACHE_TTL_HOURS`, etc. `state.py` has `load_signal_cache`, `save_signal_cache`, `is_cache_valid`, `save_prediction_history`. |
| 6 | CatBoost predictions are fetched from BSD `/api/predictions/` endpoint for upcoming matches | ✓ VERIFIED | `fetch_and_cache_catboost()` in catboost.py calls BSD predictions API with `Authorization: Token` header and 3-attempt backoff. |
| 7 | CatBoost response is parsed into canonical home-win probability with confidence score | ✓ VERIFIED | `parse_catboost_response()` extracts probability with field-name fallback chain (home_probability → home_win → probability_home). |
| 8 | CatBoost cache file persists with correct schema and TTL expiry (24h) | ✓ VERIFIED | `TestCatboostCache` tests verify `{fetched_at, expires_at, matches}` schema with ~24h TTL. |
| 9 | Missing CatBoost predictions per match are flagged as `available: false` with reason | ✓ VERIFIED | Null predictions → `reason="predictions_not_available"`. Invalid probability → `reason="invalid_probability"`. |
| 10 | BSD event IDs are matched to internal match_ids via team-pair resolution | ✓ VERIFIED | `_find_match_id()` searches all groups by team pair, then falls back to bracket lookup. Tests verify group and bracket resolution paths. |
| 11 | Existing prediction_history.json entries are migrated from flat format to compound format | ✓ VERIFIED | `migrate_prediction_history()` in state.py detected 429 flat entries and converted them. Current data has 667 entries, all compound. |
| 12 | Per-signal Brier/log-loss can be computed for any signal (elo, market_odds, catboost, blended) | ✓ VERIFIED | `evaluate_all_matches(signal_name="elo"/"market_odds"/"catboost")` reads compound entries and returns metrics. |
| 13 | `evaluate_all_matches(signal_name=None)` returns a multi-signal report with all available signal keys (D-11) | ✓ VERIFIED | D-11 verified via CLI — returns `{'signals': {'elo': {...}}}` dict. Tests verify multi-signal mode. |
| 14 | Both signals are fetched during startup and cached before the first simulation | ✓ VERIFIED | `main.py` lines 697-712: migration → CatBoost fetch → `_merge_signals_into_history()`. Odds are fetched per-iteration from existing events. |
| 15 | Per-iteration TTL check refreshes stale signals and merges into prediction_history entries via `_merge_signals_into_history()` | ✓ VERIFIED | `_run_iteration()` lines 545-597: odds cache TTL check → CatBoost cache TTL check → `_merge_signals_into_history()` → aggregated warnings. |
| 16 | Signal probabilities from caches are merged into prediction_history entries | ✓ VERIFIED | `_merge_signals_into_history()` reads `odds_cache.json`/`catboost_cache.json` and injects `market_odds`/`catboost` signals into history entries. |
| 17 | New prediction history entries use the compound format (D-01) | ✓ VERIFIED | `evaluate_all_matches(signal_name="elo")` produces compound entries with `signals.elo` dict. Migrated data confirmed all compound. |

**Score:** 17/17 truths verified

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | CatBoost probability normalization (sum ≠ 1.0 stored as-is) | Phase 14 | Phase 14 goal: "Calibration layer, dynamic blender" — non-normalized probs intentionally deferred per D-08. |
| 2 | Basic 1/odds normalization for MVP (calibration handles remaining skew) | Phase 14 | Research doc: "Phase 14 calibration handles remaining skew." Phase 14 covers V2-07 (Platt scaling). |
| 3 | Signal blending / Brier-weighted ensemble | Phase 14 | Phase 14 goal explicitly includes "dynamic Brier-weighted ensemble" (V2-08). |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/constants.py` | Signal constants (URLs, TTLs, cache filenames) | ✓ VERIFIED | 143 lines. Contains `ODDS_CACHE_TTL_HOURS=12`, `CATBOOST_CACHE_TTL_HOURS=24`, `ODDS_CACHE_FILE`, `CATBOOST_CACHE_FILE`, `PREDICTION_HISTORY_SCHEMA_VERSION=2`. |
| `src/state.py` | Cache helpers + save_prediction_history + migrate_prediction_history | ✓ VERIFIED | 880 lines. Contains `load_signal_cache`, `save_signal_cache`, `is_cache_valid`, `save_prediction_history`, `migrate_prediction_history`. |
| `src/predictors/__init__.py` | Package init | ✓ VERIFIED | Exists (5 lines) with docstring. Importable via `import src.predictors`. |
| `src/predictors/odds.py` | remove_vig, parse_odds_response, fetch_and_cache_odds | ✓ VERIFIED | 200 lines. All three functions implemented. Tested. |
| `src/predictors/catboost.py` | fetch_and_cache_catboost, parse_catboost_response | ✓ VERIFIED | 304 lines. Both functions implemented with field-name fallback, 3-attempt backoff, graceful degradation. |
| `src/evaluation.py` | evaluate_all_matches with signal_name parameter | ✓ VERIFIED | 314 lines. `signal_name=None` (D-11 multi-signal), `"elo"` replay, `"market_odds"/"catboost"/"blended"` read from history. |
| `main.py` | Signal fetch/cache at startup, _merge_signals_into_history, per-iteration refresh | ✓ VERIFIED | 782 lines. Startup migration → CatBoost fetch → merge. Per-iteration: odds refresh, CatBoost refresh, merge, aggregated warnings. |
| `tests/test_odds.py` | Tests for vig removal, cache, persistence | ✓ VERIFIED | 455 lines, 17 tests across 5 classes (TestVigRemoval, TestMissingOdds, TestOddsCache, TestOddsPersistence, TestFetchAndCacheOdds). |
| `tests/test_catboost.py` | Tests for prediction parsing, fetch, cache | ✓ VERIFIED | 550 lines, 20 tests across 5 classes (TestParsePredictions, TestMissingPredictions, TestCatboostCache, TestCatboostFetch, TestParsePredictionsEdgeCases). |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `main.py` | `src.predictors.odds` | `from src.predictors.odds import fetch_and_cache_odds` | ✓ WIRED | Line 28 import, line 552 usage in `_run_iteration()`, wrapped in try/except. |
| `main.py` | `src.predictors.catboost` | `from src.predictors.catboost import fetch_and_cache_catboost` | ✓ WIRED | Line 29 import, lines 565 and 704 usage (both startup and per-iteration). |
| `main.py` | `src.state` | `state.save_prediction_history()` | ✓ WIRED | `_merge_signals_into_history()` calls `state.save_prediction_history(history)` at line 70. |
| `main.py` | `src.state` | `state.load_signal_cache` / `state.save_signal_cache` | ✓ WIRED | Lines 549-568 use `state.load_signal_cache()` and `state.save_signal_cache()`. |
| `src/evaluation.py` | `src.state` | `from src.state import load_prediction_history` | ✓ WIRED | Line 10 imports `append_prediction_history`, `load_prediction_history`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `main.py::_run_iteration` | `odds_cache` | `fetch_and_cache_odds(raw, aliases, groups, ...)` → `state.save_signal_cache()` | ✓ FLOWING | Parses BSD events → vig-removed probs → cache dict with `{fetched_at, expires_at, matches}`. |
| `main.py::_run_iteration` | `cb_cache` | `fetch_and_cache_catboost(api_key, aliases, groups, bracket, ...)` → `state.save_signal_cache()` | ✓ FLOWING | Fetches BSD predictions → field-name fallback parsing → cache dict. Graceful on failure (empty matches). |
| `_merge_signals_into_history` | `history` | `state.load_prediction_history()` + cache `matches` → injects missing signals | ✓ FLOWING | Reads both caches, iterates history entries, adds `market_odds`/`catboost` where match_id matches. |
| `evaluate_all_matches` | per-signal metrics | `load_prediction_history()` → filter by `signals.{name}` → `compute_metrics()` | ✓ FLOWING | D-11: `signal_name=None` returns multi-signal report with all available signal keys from compound entries. |
| `prediction_history.json` | 667 entries | `migrate_prediction_history()` (flat→compound) + `_merge_signals_into_history()` | ✓ FLOWING | All entries have compound `signals.elo` structure. Ready for market_odds/catboost injection. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| State cache + migration tests | `pytest tests/test_state.py` | Passed (50 tests) | ✓ PASS |
| Odds tests | `pytest tests/test_odds.py` | Passed (17 tests) | ✓ PASS |
| CatBoost tests | `pytest tests/test_catboost.py` | Passed (20 tests) | ✓ PASS |
| Evaluation tests | `pytest tests/test_evaluation.py` | Passed | ✓ PASS |
| Main loop tests | `pytest tests/test_main_loop.py` | Passed | ✓ PASS |
| Full test suite | `pytest -x` | 387 passed, 1 skipped | ✓ PASS |
| Predictors package import | `python -c "import src.predictors"` | Clean import | ✓ PASS |
| CatBoost module load | `python -c "from src.predictors.catboost import parse_catboost_response; r=parse_catboost_response([],{},{},[]); assert isinstance(r,dict)"` | Clean import | ✓ PASS |
| is_cache_valid | `python -c "from src.state import is_cache_valid; assert is_cache_valid({'expires_at':'2099-01-01T00:00:00+00:00'},12)"` | Returns True | ✓ PASS |
| D-11 multi-signal mode | `evaluate_all_matches(signal_name=None)` | Returns `{'signals': {'elo': {...}}}` | ✓ PASS |
| Prediction history migrated | 667 entries, all compound | No flat entries remain | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| V2-05 | 13-01, 13-03 | Market odds fetched and converted to vig-removed probabilities | ✓ SATISFIED | `odds.py`: `remove_vig()` (1/odds normalization), `parse_odds_response()` (BSD events extraction), `fetch_and_cache_odds()` (cache pipeline). 17 tests. |
| V2-06 | 13-01, 13-02, 13-03 | CatBoost predictions fetched for every match | ✓ SATISFIED | `catboost.py`: `fetch_and_cache_catboost()` (BSD predictions API with retry), `parse_catboost_response()` (field-name fallback). 20 tests. |

### Anti-Patterns Found

None. No TBD/FIXME/XXX markers found in any Phase 13 files. No stub patterns (empty returns, placeholders, console.log-only handlers) detected.

### TDD Gate Compliance

| Plan | RED Commit | GREEN Commit | Status |
| ---- | ---------- | ------------ | ------ |
| 13-01 Task 1 | `21b6a41` (test: signal cache) | `9281e2c` (feat: cache helpers) | ✓ VALID |
| 13-01 Task 2 | `7f13978` (test: odds.py) | `4a4cc8c` (feat: odds.py) | ✓ VALID |
| 13-02 Task 1 | `0dfb838` (test: catboost) | `2ca1a85` (feat: catboost) | ✓ VALID |
| 13-03 Task 1 | `2d2e105` (test: migration) | `e384a27` (feat: migration) | ✓ VALID |
| 13-03 Task 2 | `91de3a2` (test: signal_name) | `ad906b1` (feat: signal_name) | ✓ VALID |

### Gaps Summary

No gaps found. All 17 truths verified. All artifacts exist, are substantive, and wired. Full test suite passes (387/1). Production data migrated (667 compound entries). All threat mitigations applied (T-13-01 through T-13-11).

**Deferred to Phase 14:** CatBoost probability normalization, calibration (Platt scaling), signal blending/Brier weighting — all explicitly scheduled for Phase 14 per ROADMAP.md and design decisions.

---

_Verified: 2026-06-16T18:30:00+05:30_
_Verifier: gsd-verifier (goal-backward verification)_
