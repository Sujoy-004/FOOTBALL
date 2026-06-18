# Phase 14a, Plan 01 — Prediction Retention Architecture Fix

## Design Flaw

Phase 13 (Signal Ingestion) caches pre-match predictions in TTL-based files (12h odds, 24h CatBoost) that are evicted after expiry. By the time a match finishes and enters `prediction_history`, its pre-match predictions have already been discarded. This makes multi-signal Brier computation and calibration impossible.

## Solution

Permanent prediction ledger (`data/predictions_ledger.json`). Every prediction is written once at fetch time, keyed by `match_id`. Never deleted. TTL caches continue to serve live freshness; the ledger serves as the historical archive.

## Implementation

### 1. `src/constants.py`
- Add `PREDICTION_LEDGER_FILE = "predictions_ledger.json"`

### 2. `src/state.py`
- Add `load_prediction_ledger()` — load ledger dict from disk
- Add `save_prediction_ledger()` — atomic write
- Add `ledger_upsert(match_id, signal_name, entry)` — load → update → save

### 3. `src/predictors/odds.py`
- In `fetch_and_cache_odds()`, after building cache `matches` dict, upsert each match into the ledger

### 4. `src/predictors/catboost.py`
- In `fetch_and_cache_catboost()`, after building cache `matches` dict, upsert each match into the ledger

### 5. `src/main.py`
- `_merge_signals_into_history()` — change source from TTL caches to ledger

## Verification

1. Run test suite (427+ tests should pass)
2. Start with `--once`, verify `predictions_ledger.json` is created with odds + catboost entries
3. Verify `_merge_signals_into_history` reads from ledger
