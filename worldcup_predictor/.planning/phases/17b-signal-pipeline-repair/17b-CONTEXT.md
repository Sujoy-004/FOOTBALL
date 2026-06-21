# Phase 17b: Signal Pipeline Repair — Context

**Gathered:** 2026-06-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Repair four pipeline defects that prevent the multi-signal blending architecture (Phases 13–15) from operating as designed. The CatBoost parser, market odds ledger population, calibration actual-field reading, and match_probs implementation are all non-functional — simulation runs on pure Elo despite claiming to blend 5 signals.

Scope: Fix existing requirements V2-05, V2-06, V2-07, V2-08, V2-20 to operational state. No new requirements, no new signals, no xG, no AI preview.

</domain>

<decisions>
## Implementation Decisions

### A. CatBoost Parser — Field Name Map Fix
- **D-01:** Update `_HOME_FIELDS`, `_DRAW_FIELDS`, `_AWAY_FIELDS` in `catboost.py:41-43` to match the actual BSD predictions API response shape. The API returns FLAT top-level percentage fields (not a nested `predictions` sub-dict). Current field names (`home_probability`, `draw_probability`, `away_probability`) are for a sub-dict that doesn't exist.
- **D-02:** The API returns probabilities as percentages (0-100), not 0-1 floats. The parser must divide by 100 after extraction.
- **D-03:** Retain the existing fallback-chain pattern — it's correct. Only the field names and percentage→probability conversion need updating.
- **D-04:** Result must go through `ledger_upsert(match_id, "catboost", entry)` at fetch time (matching form/lineup pattern).

### B. Market Odds Merge — Combined Fix (root cause: two gaps)
**Root cause trace confirmed by runtime data analysis:**

- `fetch_and_cache_odds()` in `odds.py:165` returns a cache dict but NEVER calls `ledger_upsert()`. The 31 market_odds entries currently in the ledger were populated by a non-code path (no `ledger_upsert` call exists for `"market_odds"` anywhere in the codebase).
- `_run_iteration()` in `main.py:526` processes newly-finished matches (saves to played.json, updates Elo) but NEVER creates corresponding `prediction_history` entries. `_record_eval_baseline()` only runs at startup (line 893). The merge function iterates stale history — its 8 unique match_ids are for matches finished before prediction collection began.

**Evidence:** prediction_history has 8 unique match_ids (7 GS_*, 1 M*). Ledger has 72 entries but market_odds covers 31 different GS_* match_ids. Zero overlap between history match_ids and market_odds match_ids. Form and lineup_strength DO merge correctly because they call `ledger_upsert` and their match_ids overlap with history.

**Fix (two-part):**

- **D-05:** Add `ledger_upsert(match_id, "market_odds", entry)` call in `fetch_and_cache_odds()`, matching the pattern in `form.py:346-348` and `lineup.py:193-195`. This ensures market_odds enters the prediction ledger at fetch time.
- **D-06:** Ensure `_run_iteration()` creates prediction_history entries for newly-finished matches during normal operation. The exact mechanism is at the agent's discretion — options include calling `_record_eval_baseline()` per-iteration, or creating entries inline for newly-detected matches.

**Success criteria (all must pass):**
1. odds_cache populated and saved
2. ledger contains market_odds for match_ids in odds_cache
3. prediction_history contains entries whose match_ids overlap with ledger's market_odds
4. `_merge_signals_into_history()` successfully merges market_odds into those history entries
5. market_odds appears in calibration input (n_matches > 0 for calibration)

### C. Calibration Actual-Field — Data-Model Fix
- **D-07:** Fix the actual-value read location in `blender.py`. Currently `calibrate_and_blend()` and `compute_rolling_brier()` read `signal_data.get("actual")` — but the `actual` field is stored at `entry["actual"]` (the top-level history entry), never copied into signal sub-dicts. All 5 signals find 0 training pairs.
- **D-08:** Use approach C1: change blender functions to read `entry["actual"]` directly. This is a minimal change, preserves the existing data model, and avoids duplicating actual values into every signal sub-dict.
- **D-09:** Result: calibration params report `n_matches > 0` for at least one signal. Brier scores become meaningful.

### D. Empty match_probs — Implementation
- **D-10:** Implement the per-match probability computation in `calibrate_and_blend()` Flow C (blender.py:~435-451). Currently initializes `match_probs = {}` and never populates it. Comments describe the intended logic but no code follows.
- **D-11:** Implementation must:
  1. Iterate all matches (group + knockout)
  2. For each match, collect raw probabilities from each signal (cache/elo/form/etc.)
  3. Apply calibration to each raw probability via `apply_calibration(p_raw, A, B)`
  4. Blend calibrated probabilities via `blend_predictions()`
  5. Store result in `match_probs[match_id]`
- **D-12:** Result: `match_probs` is non-empty. `_get_blended_prob()` returns blended values instead of falling back to `expected_score()`. Simulation output differs from Elo-only baseline.

### Verification Criteria
- **V1-V4:** Tier 1 pipeline integrity (cache populated, ledger populated, calibration has data, match_probs non-empty)
- **V5:** `_get_blended_prob()` returns value different from `expected_score()` for at least one match (proves blend active)
- **V6 — Blended probabilities consumed by simulation.** Evidence required (all five):
  1. `calibrate_and_blend()` produces non-empty match_probs
  2. For at least one real match: `blended_probability != expected_score()`
  3. `_get_blended_prob()` returns the blended_probability for that match
  4. The simulation uses that blended_probability during execution
  5. Runtime trace demonstrates the Elo fallback path is NOT taken for that match
- **V7-V9:** Correctness (blend weights not equal, graceful re-normalization, zero regression on 527+ tests)

**Success gate:** V1 + V1b + V1c + V2 + V3 + V4 + V5 + V6 + V9 = PASS

### the agent's Discretion
- Exact mechanism for per-iteration prediction_history entry creation (D-06): inline creation vs calling evaluate_all_matches
- Whether to also fix the CatBoost ledger_upsert call as part of Defect A or as a note in Defect B's scope
- The number of matches to use for initial calibration warm-start (already 30 per Phase 14 D-03)
- Test fixture design (fixtures for each of the four defect fixes)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 17b is a corrective phase. Requirements V2-05 through V2-08, V2-20.
- `.planning/REQUIREMENTS.md` — V2-05 (market odds), V2-06 (CatBoost), V2-07 (calibration), V2-08 (blender), V2-20 (prediction retention).

### Prior Phase Context (repairs code from these phases)
- `.planning/phases/13-signal-ingestion/13-CONTEXT.md` — Signal data model (D-01 compound entry), graceful degradation (D-07/D-08).
- `.planning/phases/14-signal-blending/14-CONTEXT.md` — Blender architecture (Platt scaling, Brier weights, cold-start threshold).
- `.planning/phases/14a-prediction-retention-architecture-fix/` — Prediction ledger design. NOTE: No CONTEXT.md found (Phase 14a was executed without formal context capture).
- `.planning/phases/15-context-signals/15-CONTEXT.md` — Form/lineup signal patterns (ledger_upsert pattern that odds must follow).
- `.planning/phases/16-model-governance/16-CONTEXT.md` — Version tracking, Brier monitoring.

### Code Locations (all defects + fix sites)
- `src/predictors/catboost.py:38-43` — `_HOME_FIELDS`, `_DRAW_FIELDS`, `_AWAY_FIELDS` (Defect A fix site)
- `src/predictors/catboost.py:166` — `prediction.get("predictions")` reads nested dict that doesn't exist (Defect A fix site)
- `src/predictors/odds.py:165-200` — `fetch_and_cache_odds()` missing `ledger_upsert()` call (Defect B Gap 1 fix site)
- `main.py:526-819` — `_run_iteration()` missing prediction_history creation for new matches (Defect B Gap 2 fix site)
- `main.py:66-103` — `_merge_signals_into_history()` (merge architecture — confirmed working for form/lineup)
- `src/blender.py` (multiple locations) — `calibrate_and_blend()` and `compute_rolling_brier()` actual-field read (Defect C fix site)
- `src/blender.py:~435-451` — Empty `match_probs = {}` (Defect D fix site)
- `src/knockout.py` — `_get_blended_prob()` fallback path (affected by Defect D)

### Data Files (evidence for root cause)
- `data/prediction_history.json` — 453 entries, 8 unique match_ids, only elo+form+lineup_strength signals
- `data/predictions_ledger.json` — 72 entries, 31 with market_odds, 41 without
- `data/odds_cache.json` — 29 matches with valid market_odds (source truth)
- `data/catboost_cache.json` — 0 matches (empty — parser never worked)

### Design Document
- `RESPONSE.md` — Full defect classification and runtime verification evidence

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/predictors/form.py:346-348` — `ledger_upsert(mid, "form", entry)` pattern. Directly replicable for odds and catboost.
- `src/predictors/lineup.py:193-195` — Same pattern, confirms the approach.
- `src/state.py:787-808` — `ledger_upsert()` function — already exists, just needs callers.

### Established Patterns
- **Compound entry model** (Phase 13 D-01): history entries have `signals: {signal_name: {probability, available, ...}}`.
- **Graceful degradation**: every signal marks `available: false` with a `reason` when data is missing.
- **Pure stdlib math**: no numpy/pandas/sklearn. All math via `math` module.

### Integration Points
- `main.py:627-637` — Odds cache refresh: add `ledger_upsert` after cache save.
- `main.py:591-620` — New match processing: add prediction_history creation after saved to played.json/played_groups.json.
- `main.py:681` — `_merge_signals_into_history()` call: destination for both Gap 1 (ledger data) and Gap 2 (new entries).

</code_context>

<specifics>
## Specific Ideas

- The merge architecture itself is sound and proven — form and lineup_strength correctly merge into history. Only the missing `ledger_upsert` call for odds/catboost and missing prediction_history creation for new matches prevent market_odds from merging.
- The 31 existing market_odds entries in the ledger were populated by a non-code path. This is evidence that someone manually verified the data would be correct — the code just never called `ledger_upsert`. The fix is to add that call.

</specifics>

<deferred>
## Deferred Ideas

- Coverage auditor for Phase 20 — not related
- Historical backfill of enriched data — Phase 17 scope not changed
- Coach data extraction (Phase 17 P1, deferred) — not related

</deferred>

---

*Phase: 17b-Signal-Pipeline-Repair*
*Context gathered: 2026-06-19*
