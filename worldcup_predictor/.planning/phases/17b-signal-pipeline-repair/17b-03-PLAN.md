---
phase: 17b-signal-pipeline-repair
plan: 03
type: execute
wave: 1
depends_on: []
files_modified:
  - src/blender.py
autonomous: true
requirements:
  - V2-07
  - V2-08
user_setup: []

must_haves:
  truths:
    - "Calibration fitting reads actual outcomes from entry['actual'] (not signal_data['actual']) — all 5 signals find training pairs"
    - "compute_rolling_brier() reads actual outcomes from entry['actual'] — Brier scores become meaningful"
    - "calibrate_and_blend() Flow C produces non-empty match_probs dict with blended probabilities"
    - "For each match in groups_data and bracket_data, match_probs contains a blended probability"
    - "match_probs uses calibration (apply_calibration) + blending (blend_predictions) for each signal"
    - "Missing signals for a match result in graceful re-normalization (not crash)"
    - "Zero regression on existing 40+ blender tests"
  artifacts:
    - path: "src/blender.py"
      provides: "Fixed actual-field reads (Defect C) and populated match_probs (Defect D)"
      changed_lines: "~5 lines for Defect C (actual reads), ~40 lines for Defect D (Flow C implementation)"
  key_links:
    - from: "src/blender.py calibrate_and_blend()"
      to: "entry['actual']"
      via: "Flow A reads actual from entry.get('actual') instead of signal_data.get('actual')"
      pattern: "entry.get\('actual'\)"
    - from: "src/blender.py compute_rolling_brier()"
      to: "entry['actual']"
      via: "Reads actual from entry.get('actual') instead of signal_data.get('actual')"
      pattern: "entry.get\('actual'\)"
    - from: "src/blender.py calibrate_and_blend() Flow C"
      to: "knockout.py _get_blended_prob()"
      via: "match_probs[match_id] consumed by simulation"
      pattern: "match_probs\["
---

<objective>
Repair: Calibration actual-field read location (Defect C) and empty match_probs implementation (Defect D).

Purpose: Two blender defects that prevent the multi-signal blending pipeline from producing meaningful output:
1. `calibrate_and_blend()` and `compute_rolling_brier()` read `signal_data.get("actual")`, but `actual` is only stored at `entry["actual"]` — never copied into signal sub-dicts. Result: all 5 signals find 0 training pairs, calibration returns identity parameters.
2. Flow C initializes `match_probs = {}` and never populates it — `_get_blended_prob()` always falls back to `expected_score()`, so simulation never uses blended probabilities.

Output:
- `src/blender.py` — actual field reads fixed to use `entry["actual"]`; Flow C implements per-match probability with calibration + blending
</objective>

<execution_context>
@C:/Users/KIIT0001/.config/opencode/get-shit-done/workflows/execute-plan.md
@C:/Users/KIIT0001/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/17b-signal-pipeline-repair/17b-CONTEXT.md
@src/blender.py
@src/elo.py
@src/knockout.py

<interfaces>
From `src/blender.py:164-200` — compute_rolling_brier() current actual read:
```python
signal_data = signals[signal_key]
probability = signal_data.get('probability')
actual = signal_data.get('actual')  # BUG — actual is at entry["actual"], never in signal_data
```

From `src/blender.py:368-453` — calibrate_and_blend() current Flow A:
```python
signal_data = signals[signal_key]
probability = signal_data.get('probability')
actual = signal_data.get('actual')  # BUG — same issue as compute_rolling_brier
```

From `src/blender.py:435-451` — Flow C (empty implementation):
```python
# Flow C — Match probabilities
match_probs = {}
# For group matches: look up team_a, team_b from groups_data → compute elo probability via expected_score()
# For market_odds and catboost: read from respective caches by match_id
# For each signal with data for this match: apply_calibration(p_raw, A, B)
# Blend calibrated probs via blend_predictions()

# This is a simplified implementation - the full implementation would need
# to iterate through all matches and compute probabilities

if calibration_params and blend_weights:
    return {
        "calibration_params": calibration_params,
        "blend_weights": blend_weights,
        "match_probs": match_probs
    }
```

From `src/blender.py:38-43` — calibrate_and_blend signature:
```python
def calibrate_and_blend(history, signal_keys, elo_ratings, groups_data, bracket_data,
                        odds_cache, cb_cache, brier_window=50, cold_start_threshold=30)
```
(Will receive form_cache and lineup_cache from Plan 17b-02 Task 2 — they are NOT in the current signature but will be added by that plan. For consistency, the PLAN 17b-03 implementation should only assume what's in the current signature: `odds_cache` and `cb_cache`. Form and lineup for match_probs will be read from the `history` entries via `_merge_signals_into_history()`.)

From `src/elo.py` — expected_score signature:
```python
def expected_score(rating_a: float, rating_b: float) -> float
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Fix actual-field read location in calibrate_and_blend and compute_rolling_brier</name>
  <files>src/blender.py, tests/test_blender.py</files>
  <read_first>
    src/blender.py — lines 164-200 (compute_rolling_brier), lines 368-426 (calibrate_and_blend Flow A)
    17b-CONTEXT.md — decisions D-07, D-08, D-09
    src/evaluation.py — lines 120-145 for reference on correct actual-field access pattern (entry.get("actual"))
  </read_first>
  <behavior>
    - Test 1: compute_rolling_brier with history entries that have actual at entry["actual"] (NOT in signal_data) returns Brier < 1.0
    - Test 2: calibrate_and_blend Flow A with actual at entry["actual"] produces calibration_params with n_matches > 0 for each signal
    - Test 3: Existing test_end_to_end_with_mock_data still passes (mock data uses entry["actual"])
  </behavior>
  <action>
    Fix the actual-field read location in two functions (per D-07, D-08, D-09).

    **Change 1 — `compute_rolling_brier()` at line 184:**
    Change `actual = signal_data.get('actual')` to `actual = entry.get('actual')`.
    This reads the actual outcome from the history entry's top-level `actual` key, where it is stored during prediction_history creation (see `evaluation.py:200` and Plan 17b-02's entry creation).

    **Change 2 — `calibrate_and_blend()` Flow A at line 404:**
    Change `actual = signal_data.get('actual')` to `actual = entry.get('actual')`.
    Same rationale — actual is at entry level, never in signal sub-dicts.

    Both changes are minimal (one line each). The data model is unchanged — no need to duplicate actual values into signal sub-dicts per D-08.

    Result: calibration_params report `n_matches > 0` for at least one signal because the actual values are now found at the correct key. Brier scores become meaningful per D-09.
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_blender.py -x --tb=short -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    `compute_rolling_brier()` uses `entry.get('actual')` instead of `signal_data.get('actual')`.
    `calibrate_and_blend()` Flow A uses `entry.get('actual')` instead of `signal_data.get('actual')`.
    calibration_params for signals with >30 entries show `n_matches > 0`.
    All existing blender tests pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement match_probs computation in calibrate_and_blend Flow C</name>
  <files>src/blender.py, tests/test_blender.py</files>
  <read_first>
    src/blender.py — full file (460 lines), especially:
      - Lines 368-453 (calibrate_and_blend function)
      - Lines 119-161 (apply_calibration)
      - Lines 234-257 (blend_predictions)
      - Lines 57-116 (calibrate_signal)
    src/elo.py — expected_score function
    17b-CONTEXT.md — decisions D-10, D-11, D-12
    src/evaluation.py — lines 168-211 for reference on match iteration pattern
  </read_first>
  <behavior>
    - Test 1: calibrate_and_blend with groups_data containing 1 group match returns match_probs with that match_id
    - Test 2: match_probs value for a match is different from raw Elo expected_score when calibration is non-identity
    - Test 3: match_probs for all matches are blended probabilities (not individual signal values)
    - Test 4: bracket_data matches are included in match_probs
    - Test 5: Missing caches (empty dict) for odds/catboost/form/lineup result in graceful re-normalization via blend_predictions
  </behavior>
  <action>
    Implement the per-match probability computation in Flow C of `calibrate_and_blend()` (lines 435-451, per D-10, D-11, D-12).

    Replace lines 437-451 (from `match_probs = {}` through the `if calibration_params and blend_weights: return` block) with a full implementation.

    **Implementation:**

    1. **Collect all matches** from `groups_data` and `bracket_data` into a single list:
       - Group matches: iterate all groups in `groups_data.get("groups", groups_data)`, then for each group's `matches` list, collect each match dict.
       - Bracket matches: iterate `bracket_data` directly.
       - Each match has `match_id`, `team_a`, `team_b`.

    2. **Build per-signal calibration lookup** from `calibration_params`:
       - For each signal_key in signal_keys, get `params = calibration_params.get(signal_key, {})` → `A = params.get("A", 1.0)`, `B = params.get("B", 0.0)`.
       - If params is empty (signal not in calibration_params), default to identity (1.0, 0.0).

    3. **For each match**, compute the blended probability:
       a. Determine `elo_probability`: `expected_score(elo_ratings[team_a], elo_ratings[team_b])`.
       b. Read `odds_probability` from `odds_cache.get("matches", {}).get(match_id, {}).get("probability")`.
       c. Read `cb_probability` from `cb_cache.get("matches", {}).get(match_id, {}).get("probability")`.
       d. Read `form_probability` from `form_cache.get("matches", {}).get(match_id, {}).get("probability")` — (form_cache will be None/empty if Plan 17b-02 hasn't run yet; handle empty gracefully).
       e. Read `lineup_probability` from `lineup_cache.get("matches", {}).get(match_id, {}).get("probability")` — same graceful handling.
       
       Note: The function signature currently does NOT include `form_cache` and `lineup_cache` params. These will be added by Plan 17b-02 Task 2. To keep the plan set working regardless of execution order, handle missing params:
       - Accept `form_cache=None, lineup_cache=None` as new optional parameters (add to function signature).
       - Inside the function, default to `{}` if either is None: `form_cache = form_cache or {}`.

       Also: For form and lineup, if the cache dict has entries but individual match_id is missing, mark that signal unavailable for that match (don't include in blend).

       e. Build a `raw_probs` dict: `{signal_key: probability}` for each signal where the probability is not None AND the signal has a calibration param with `n_matches > 0` (or cold-start identity is fine — identity calibration still produces a valid calibrated probability).
       
       f. Apply calibration to each raw probability via `apply_calibration(raw_probs[sig], A, B)` using that signal's calibration params. Store calibrated results in `calibrated_probs` dict.
       
       g. Blend calibrated probabilities via `blend_predictions(calibrated_probs, blend_weights)`.
       
       h. Store `match_probs[match_id] = blended_probability`.

    4. **Handle edge cases gracefully**:
       - If `team_a` or `team_b` not in `elo_ratings`, skip that match (simulation won't be able to use it either).
       - If no probabilities are available for a match, store `match_probs[match_id] = 0.5` (uniform prior per D-22/blend_predictions behavior).
       - Wrap the entire Flow C in try-except — if computation fails for any match, continue to next match. Log nothing (pure computation).

    5. **Update the function signature** to add `form_cache` and `lineup_cache`:
       ```python
       def calibrate_and_blend(history, signal_keys, elo_ratings, groups_data, bracket_data,
                               odds_cache, cb_cache, brier_window=50, cold_start_threshold=30,
                               form_cache=None, lineup_cache=None)
       ```
       This matches what Plan 17b-02 Task 2 passes via `_run_calibrate_and_blend()`.

    6. **Remove the placeholder comments** at lines 438-444 (the prose describing what should be done). Replace with the actual implementation.

    The return statement stays the same — `match_probs` is now populated.
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_blender.py -x --tb=short -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    `calibrate_and_blend()` accepts optional `form_cache` and `lineup_cache` params.
    Flow C iterates all group + bracket match_ids and computes a blended probability for each.
    Each match probability goes through: raw prob → apply_calibration → blend_predictions.
    match_probs dict is non-empty and contains all matches from groups_data + bracket_data.
    Missing signals gracefully excluded (blend_predictions re-normalizes weights).
    Existing blender tests pass.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| calibration_params → apply_calibration | Trusted internal data (calibrate_and_blend produces and consumes within same call) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-17b-07 | Tampering | Flow C match_probs | mitigate | Values clamped to [EPS, 1-EPS] by apply_calibration + blend_predictions (existing) |
| T-17b-08 | DoS | Malformed match entries | mitigate | try-except wrapping entire Flow C — failure is non-fatal, returns empty match_probs |
| T-17b-09 | DoS | Missing team in elo_ratings | mitigate | Guard: skip match if team not in elo_ratings |
</threat_model>

<verification>
1. `python -m pytest tests/test_blender.py -x --tb=short` — all 40+ blender tests pass
2. Verify calibration_params show n_matches > 0 for signals with history entries (actual field fix)
3. Verify match_probs is non-empty with correct match_ids
4. `python -m pytest -x --tb=short` — full suite passes, zero regression
</verification>

<success_criteria>
- compute_rolling_brier reads actual from entry["actual"] — Brier values become meaningful (not 1.0)
- calibrate_and_blend Flow A reads actual from entry["actual"] — n_matches > 0 for signals with ≥cold_start_threshold entries
- Flow C produces non-empty match_probs dict
- Each match probability is calibrated + blended (not raw Elo expected_score)
- Missing signals handled gracefully via blend_predictions re-normalization
- Zero regression on full test suite (527+ tests)
</success_criteria>
