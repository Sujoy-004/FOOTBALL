---
phase: 17b-signal-pipeline-repair
plan: 04
type: execute
wave: 2
depends_on:
  - 17b-01
  - 17b-02
  - 17b-03
files_modified:
  - tests/test_catboost.py
  - tests/test_odds.py
  - tests/test_blender.py
  - tests/test_main_loop.py
autonomous: true
requirements:
  - V2-05
  - V2-06
  - V2-07
  - V2-08
  - V2-20
user_setup: []

must_haves:
  truths:
    - "CatBoost parser tests use flat-format percentage fixtures (not nested predictions sub-dict)"
    - "CatBoost fetch test verifies ledger_upsert was called with signal_name='catboost'"
    - "Odds fetch test verifies ledger_upsert was called with signal_name='market_odds'"
    - "Blender tests verify actual-field is read from entry['actual'] — signals find non-zero training pairs"
    - "Blender tests verify match_probs is non-empty after calibrate_and_blend with realistic data"
    - "Blender tests verify match_probs values differ from raw Elo expected_score when calibration is non-identity"
    - "Main loop test verifies prediction_history entries are created for newly-finished matches"
    - "Full suite: zero regression, all 527+ existing tests + new tests pass"
  artifacts:
    - path: "tests/test_catboost.py"
      provides: "Updated test fixtures for flat-format API response + ledger_upsert test"
    - path: "tests/test_odds.py"
      provides: "New test for ledger_upsert call in fetch_and_cache_odds"
    - path: "tests/test_blender.py"
      provides: "New tests for actual-field fix and match_probs population"
    - path: "tests/test_main_loop.py"
      provides: "New test for per-iteration prediction_history entry creation"
  key_links:
    - from: "tests/test_catboost.py"
      to: "src/predictors/catboost.py"
      via: "Fixtures now match flat percentage format (not nested predictions dict)"
      pattern: "home_probability.*64"
    - from: "tests/test_blender.py"
      to: "src/blender.py"
      via: "match_probs tests verify non-empty dict with correct match_ids"
      pattern: "match_probs"
---

<objective>
Verification: Tests and integration checks for all four defect repairs.

Purpose: Ensure each defect fix is tested and the pipeline verification criteria from CONTEXT.md are satisfied. New tests cover the CatBoost flat-format parser, ledger_upsert calls in both odds and catboost, prediction_history entry creation, the actual-field fix, and match_probs population — plus the 5-part evidence chain (V6).

Output:
- Updated test files with new test classes for each defect fix
- Full test suite passes with zero regressions
</objective>

<execution_context>
@C:/Users/KIIT0001/.config/opencode/get-shit-done/workflows/execute-plan.md
@C:/Users/KIIT0001/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/17b-signal-pipeline-repair/17b-CONTEXT.md
@tests/test_catboost.py
@tests/test_odds.py
@tests/test_blender.py
@tests/test_main_loop.py

<interfaces>
Existing test patterns:
- `test_catboost.py` — TestParsePredictions class with _make_valid_prediction() fixture method
- `test_odds.py` — TestOddsCache class with test_cache_produces_valid_schema
- `test_blender.py` — TestBlendPipeline class with test_end_to_end_with_mock_data
- `test_main_loop.py` — Various test classes with monkeypatch fixtures

Verification criteria from CONTEXT.md:
- V1-V4: Tier 1 pipeline integrity (cache populated, ledger populated, calibration has data, match_probs non-empty)
- V5: `_get_blended_prob()` returns value different from `expected_score()` for at least one match
- V6: 5-part evidence chain (non-empty match_probs → blended_prob ≠ expected_score → returned by _get_blended_prob → consumed by simulation → Elo fallback NOT taken)
- V7-V9: Correctness (blend weights not equal, graceful re-normalization, zero regression)
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update and add CatBoost + Odds tests for flat-format parser and ledger_upsert</name>
  <files>tests/test_catboost.py, tests/test_odds.py</files>
  <read_first>
    tests/test_catboost.py — full file (550 lines), especially:
      - TestParsePredictions class (lines 19-120+)
      - _make_valid_prediction fixture (lines 48-65)
      - test_parse_valid_prediction (lines 74-85)
      - test_parse_null_predictions (lines 101-110)
    tests/test_odds.py — full file (455 lines), especially:
      - TestOddsCache class (lines 187-455)
      - test_cache_produces_valid_schema (lines 190-200+)
    src/predictors/catboost.py — after Plan 17b-01 changes
    src/predictors/odds.py — after Plan 17b-01 changes
  </read_first>
  <action>
    Update test fixtures and add ledger_upsert verification tests for catboost and odds.

    **test_catboost.py updates:**

    1. **Fix `_make_valid_prediction()` fixture** (lines 48-65):
       - Remove the nested `"predictions"` sub-dict.
       - Move `"home_probability"`, `"draw_probability"`, `"away_probability"` to top level.
       - Change values from 0-1 floats to 0-100 percentages: 0.64 → 64.0, 0.20 → 20.0, 0.17 → 17.0.
       - Move `"confidence"` and `"model_version"` to top level (remove from nested dict).
       - The fixture should match the actual BSD API flat format:
         ```python
         pred = {
             "event_id": 12345,
             "home_team": "Argentina",
             "away_team": "Algeria",
             "home_probability": 64.0,
             "draw_probability": 20.0,
             "away_probability": 17.0,
             "confidence": 0.88,
             "model_version": "catboost-v5.0",
             "event_date": "2026-06-17T05:00:00+00:00",
             "updated_at": "2026-06-16T12:00:00+00:00",
         }
         ```

    2. **Update `test_parse_valid_prediction`**: Assert `entry["probability"] == 0.64` (parser converts 64.0% → 0.64).

    3. **Update `test_parse_null_predictions`**: Change from setting `{"predictions": None}` to setting all three probability fields to None:
       - Use overrides: `{"home_probability": None, "draw_probability": None, "away_probability": None}`.
       - Assert `available is False, reason="predictions_not_available"`.

    4. **Add new test `test_parse_flat_percentage_format`**: Send fixture with percentage values, verify parser converts correctly (64.0 → 0.64).

    5. **Add new test `test_fetch_upserts_ledger`**: Test that `fetch_and_cache_catboost()` calls `ledger_upsert`. Use monkeypatch to mock `src.state.ledger_upsert`, call `fetch_and_cache_catboost`, then assert `ledger_upsert` was called with `(match_id, "catboost", entry)` for each parsed match.

    **test_odds.py updates:**

    6. **Add new test `test_fetch_upserts_market_odds_ledger`** in or near TestOddsCache:
       - Use monkeypatch to mock `src.state.ledger_upsert`.
       - Call `fetch_and_cache_odds()` with valid events.
       - Assert `ledger_upsert` was called at least once with `signal_name="market_odds"`.
       - Assert the match_id matches the expected group match_id from the fixture.

    7. **Add new test `test_fetch_upserts_market_odds_with_unavailable`** (optional but recommended):
       - Send events with None odds.
       - Assert `ledger_upsert` is still called (unavailable entries need to be in ledger too).
       - Verify the entry has `available=False`.

    All tests must be self-contained (use inline fixtures, no external dependencies).
    All tests must use the existing test patterns (same imports, assert style).
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_catboost.py tests/test_odds.py -x --tb=short -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    CatBoost test fixtures use flat-format percentage values at top level (not nested predictions dict).
    `test_parse_valid_prediction` asserts probability=0.64 (converted from 64.0%).
    New ledger_upsert test verifies catboost signals are written to ledger.
    New ledger_upsert test verifies market_odds signals are written to ledger.
    All catboost and odds tests pass.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add blender tests for actual-field fix and match_probs population</name>
  <files>tests/test_blender.py</files>
  <read_first>
    tests/test_blender.py — full file (426 lines), especially:
      - TestRollingBrier class (lines 257-310)
      - TestBlendPipeline class (lines 385-423)
      - test_end_to_end_with_mock_data (lines 388-422)
    src/blender.py — after Plan 17b-03 changes
    17b-CONTEXT.md — verification criteria V1-V9
  </read_first>
  <action>
    Add new test classes for the actual-field fix and match_probs population.

    **New test class: `TestActualFieldFix` — somewhere near the existing TestRollingBrier / TestBlendPipeline classes:**

    1. `test_rolling_brier_reads_entry_actual`: Create history entries where `actual` is at `entry["actual"]` (NOT in `signal_data`). Each entry has `signals={"test_sig": {"probability": 0.6, "available": True}}` and `entry["actual"] = 1.0`. Call `compute_rolling_brier(entries, "test_sig")`. Assert the returned Brier < 1.0 (proves non-zero pairs were found). If Brier == 1.0, the fix hasn't worked.

    2. `test_calibrate_and_blend_actual_from_entry`: Call `calibrate_and_blend()` with history entries where `actual` is ONLY at `entry["actual"]` and not in signal_data. Use 31+ entries (above cold-start threshold). Assert that `calibration_params["test_sig"]["n_matches"] > 0`.

    3. Add to existing `test_end_to_end_with_mock_data` (line 418) — strengthen the match_probs assertion:
       - Assert `result["match_probs"]` is a non-empty dict.
       - Assert the match_ids in `match_probs` include "GS_A_00" (from groups_data fixture).
       - Assert each probability value is between 0.0 and 1.0.

    **New test class: `TestMatchProbs` — new class near end of file:**

    4. `test_match_probs_non_empty`: Call `calibrate_and_blend()` with 35+ history entries, groups_data with 2 matches, elo_ratings. Assert `match_probs` has exactly 2 entries (one per group match).

    5. `test_match_probs_different_from_elo`: Create history with 31+ entries that have a systematic bias (e.g., all predictions=0.8, actuals=1.0 for 20, 0.0 for 11). This trains a non-identity calibration. For a group match where Elo `expected_score` says 0.55, assert `match_probs[match_id] != 0.55` (proves calibration + blend is active, not just returning raw Elo).

    6. `test_match_probs_graceful_missing_cache`: Call `calibrate_and_blend()` with empty odds_cache and cb_cache (both `{}`). Assert function does not crash and `match_probs` is non-empty (Elo-only signals should still produce probabilities).

    7. `test_match_probs_bracket_matches`: Include `bracket_data` with one match in addition to groups_data. Assert match_probs contains both the group match and the bracket match.

    All tests should be self-contained (no file I/O, pure function calls).
    Use inline fixture data (not external files).
    Use the existing mock_history pattern from `test_end_to_end_with_mock_data` (lines 390-402).
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_blender.py -x --tb=short -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    compute_rolling_brier test proves actual is read from entry["actual"].
    calibrate_and_blend test proves actual is read from entry["actual"] (n_matches > 0).
    match_probs is non-empty after calibrate_and_blend with realistic data.
    match_probs values differ from raw Elo when calibration is non-identity.
    Empty odds/cb caches handled gracefully (match_probs from Elo only).
    Bracket matches included in match_probs.
  </done>
</task>

<task type="auto">
  <name>Task 3: Add main loop test for per-iteration prediction_history creation</name>
  <files>tests/test_main_loop.py</files>
  <read_first>
    tests/test_main_loop.py — full file (700+ lines), especially:
      - Any existing tests that call _run_iteration or test prediction_history behavior
      - Test patterns: monkeypatch fixtures, mock data setup
    main.py — after Plan 17b-02 changes
    src/state.py — append_prediction_history, load_prediction_history
  </read_first>
  <action>
    Add a new test class `TestPerIterationHistory` to `tests/test_main_loop.py`.

    1. **test_per_iteration_creates_history_entries**: 
       - Set up mock state: mock `state.load_prediction_history()` to return empty list `[]`.
       - Mock `state.append_prediction_history()` using a spy (capture calls in a list).
       - Set up realistic match data: a raw API response that contains one finished knockout match.
       - Call `_run_iteration()` with the mock data.
       - Assert `append_prediction_history` was called at least once.
       - Assert the first call's argument has: `match_id`, `team_a`, `team_b`, `actual`, `signals.elo.probability`.

    2. **test_per_iteration_no_duplicates**:
       - Mock `state.load_prediction_history()` to return a list that already contains an entry with the same match_id as the new match being processed.
       - Mock `state.append_prediction_history()` as a spy.
       - Call `_run_iteration()`.
       - Assert `append_prediction_history` was NOT called (the deduplication guard in Plan 17b-02 Task 1 prevents creating entries for matches already in history).

    3. **test_per_iteration_elo_probability_matches_expected_score**:
       - Mock state functions including load_prediction_history → [].
       - Mock append_prediction_history as a spy.
       - Call _run_iteration with known teams/elo ratings.
       - Assert the captured append_prediction_history call has `signals.elo.probability` equal to `expected_score(team_a_elo, team_b_elo)`.

    Use these mocking techniques (consistent with existing test_main_loop.py patterns):
    - `monkeypatch.setattr("src.state.load_prediction_history", lambda: [])`
    - `monkeypatch.setattr("src.state.append_prediction_history", spy)`
    - For teams fixture: use `monkeypatch.setattr("main.state.load_teams", lambda: {...})` or pass mock teams through _run_iteration.

    Follow the existing test conventions in test_main_loop.py for imports, fixture setup, and assertion style.
    Ensure tests are fast (< 1s each) — no real API calls, no file I/O.
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_main_loop.py -x --tb=short -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    `test_per_iteration_creates_history_entries` passes — proves _run_iteration creates prediction_history entries for newly-finished matches.
    `test_per_iteration_no_duplicates` passes — proves deduplication guard works.
    `test_per_iteration_elo_probability_matches_expected_score` passes — proves Elo prob is computed via expected_score.
    All main_loop tests pass.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Test fixtures → production code | Mock data exercises production code paths |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-17b-10 | Tampering | Test fixtures | accept | Test data is local-only, never persisted to production files |
| T-17b-SC | Tampering | Test dependencies | accept | No new packages — pytest already present |
</threat_model>

<verification>
1. Full test suite: `python -m pytest -x --tb=short` — all 527+ existing + new tests pass
2. New catboost tests: `python -m pytest tests/test_catboost.py -x -v` — flat-format + ledger_upsert tests pass
3. New odds tests: `python -m pytest tests/test_odds.py -x -v` — ledger_upsert tests pass
4. New blender tests: `python -m pytest tests/test_blender.py -x -v` — actual-field + match_probs tests pass
5. New main_loop tests: `python -m pytest tests/test_main_loop.py -x -v` — prediction_history creation tests pass
</verification>

<success_criteria>
- All 527+ existing tests pass (zero regression)
- CatBoost parser correctly handles flat percentage format (tested)
- ledger_upsert called for catboost and market_odds (tested)
- compute_rolling_brier reads actual from entry["actual"] (tested)
- calibrate_and_blend Flow A reads actual from entry["actual"] (tested)
- match_probs non-empty after calibrate_and_blend (tested)
- match_probs value differs from expected_score when calibration non-identity (tested)
- Per-iteration prediction_history entries created for new matches (tested)
- Deduplication guard prevents entry bloat (tested)
- Verification criteria V1-V9 satisfied
</success_criteria>
