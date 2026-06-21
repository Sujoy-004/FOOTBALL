---
phase: 17b-signal-pipeline-repair
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - main.py
autonomous: true
requirements:
  - V2-20
user_setup: []

must_haves:
  truths:
    - "Newly-finished matches detected during _run_iteration() get prediction_history entries created inline"
    - "Those entries have match_id, team_a, team_b, actual, and signals.elo with expected_score probability"
    - "Entries are created BEFORE _merge_signals_into_history() so market_odds/catboost/form/lineup are added from ledger"
    - "form_cache and lineup_cache are passed from _run_iteration() through to calibrate_and_blend() for match_probs computation"
    - "No duplicate entries created for matches already in prediction_history"
    - "Zero regression on 527+ existing tests"
  artifacts:
    - path: "main.py"
      provides: "Per-iteration prediction_history entry creation for newly-finished matches"
      changed_lines: "~40 lines added in _run_iteration() between line 621 and line 623"
    - path: "main.py"
      provides: "form_cache and lineup_cache passed to _run_calibrate_and_blend() for match_probs computation"
      changed_lines: "~5 lines changed in _run_calibrate_and_blend() call site and function body"
  key_links:
    - from: "main.py _run_iteration()"
      to: "src/state.append_prediction_history"
      via: "Called for each new match to create compound entry"
      pattern: "append_prediction_history"
    - from: "main.py _run_calibrate_and_blend()"
      to: "src/blender.calibrate_and_blend"
      via: "Passes form_cache and lineup_cache as new params"
      pattern: "form_cache.*lineup_cache"
---

<objective>
Repair: Per-iteration prediction_history creation for newly-finished matches (Defect B Gap 2), and pass form/lineup caches to blender for match_probs support.

Purpose: Two fixes in main.py:
1. `_run_iteration()` currently saves new matches to played.json/played_groups.json but never creates corresponding prediction_history entries. Without this, newly-finished matches have no history entries for `_merge_signals_into_history()` to populate with ledger signals (market_odds/catboost/form/lineup).
2. `_run_calibrate_and_blend()` doesn't pass form/lineup caches to `calibrate_and_blend()`, so the match_probs implementation (Defect D) cannot read form/lineup probabilities.

Output:
- `main.py` — prediction_history entries created per-iteration for new matches; form_cache + lineup_cache passed to blender
</objective>

<execution_context>
@C:/Users/KIIT0001/.config/opencode/get-shit-done/workflows/execute-plan.md
@C:/Users/KIIT0001/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/17b-signal-pipeline-repair/17b-CONTEXT.md
@main.py
@src/state.py
@src/blender.py

<interfaces>
From `main.py` — current flow of _run_iteration() lines 520-819:
- Lines 591-599: New knockout matches processed → saved to played.json
- Lines 614-621: New group matches processed → saved to played_groups.json
- Lines 623-681: Signal cache refresh + merge
- Lines 684: `blend_params = _run_calibrate_and_blend(teams, groups, bracket, odds_cache, cb_cache)`

From `main.py` — current _run_calibrate_and_blend() lines 106-148:
```python
def _run_calibrate_and_blend(teams, groups, bracket, odds_cache, cb_cache):
    ...
    blend_params = calibrate_and_blend(
        history=history,
        signal_keys=["elo", "market_odds", "catboost", "form", "lineup_strength"],
        elo_ratings=elo_ratings,
        groups_data=groups,
        bracket_data=bracket,
        odds_cache=odds_cache or {},
        cb_cache=cb_cache or {},
    )
```

From `main.py` — form_cache and lineup_cache are computed earlier in _run_iteration():
- Line 652-663: `form_cache = compute_form_signal(...)` 
- Line 665-672: `lineup_cache = compute_lineup_signal(...)`
- Both are scope-local variables available when `_run_calibrate_and_blend` is called at line 684

From `src/state.py:699-714` — append_prediction_history:
```python
def append_prediction_history(entry: dict, data_dir=None) -> None
```

From `src/evaluation.py:194-211` — reference compound entry shape:
```python
history_entries.append({
    "match_id": m.get("match_id", ""),
    "timestamp": now_iso,
    "team_a": t_a,
    "team_b": t_b,
    "actual": actual_a,
    "signals": {
        "elo": {
            "probability": round(p_a, 4),
            "version": "v1",
            "timestamp": now_iso,
            "available": True,
        }
    },
})
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create prediction_history entries for newly-finished matches in _run_iteration</name>
  <files>main.py</files>
  <read_first>
    main.py — lines 526-819 (_run_iteration function), especially:
      - Lines 590-621: new match processing (both knockout and group)
      - Lines 623-681: signal cache refresh + merge section
      - Lines 66-103: _merge_signals_into_history (what happens after merge)
      - Lines 683-732: calibrate+blend and version attachment
    src/state.py — lines 699-714 (append_prediction_history)
    src/evaluation.py — lines 194-211 (reference compound entry shape)
    17b-CONTEXT.md — decision D-06
  </read_first>
  <action>
    Add prediction_history entry creation for newly-finished matches detected during _run_iteration() (per D-06).

    Insert this code after the group match processing block (after line 621 `state.save_teams(teams)`) and before the signal cache refresh section (line 623's `# ── Signal cache refresh, merge into prediction_history ──` comment).

    Implementation:
    1. Import `append_prediction_history` from `src.state` and `expected_score` from `src.elo` at the top of the function (or inline — inline is fine).
    2. Check if `new_matches` or `new_group_matches` is non-empty.
    3. Collect all new matches into a single list: `all_new = list(new_matches or []) + list(new_group_matches or [])`.
    4. For each new match `m` in `all_new`:
       a. Verify `team_a` and `team_b` exist in `teams` dict (skip if either is missing).
       b. Compute `p_a = expected_score(teams[team_a]["elo"], teams[team_b]["elo"])`.
       c. Determine `actual_a` from `winner` field:
          - `winner is None` → actual = 0.5 (draw)
          - `winner == team_a` → actual = 1.0
          - `winner == team_b` → actual = 0.0
          - otherwise → skip (unexpected winner)
       d. Build compound entry matching the shape in `evaluation.py:194-211`:
          - `match_id` = m["match_id"]
          - `timestamp` = ISO-8601 UTC now
          - `team_a`, `team_b` from m
          - `actual` = actual_a
          - `signals` = `{"elo": {"probability": round(p_a, 4), "version": "v1", "timestamp": ..., "available": True}}`
       e. Call `append_prediction_history(entry)`.

    5. **Deduplication guard**: Before creating entries, check existing history match_ids to avoid duplicates. Load prediction_history via `state.load_prediction_history()`, collect existing match_ids into a set, and skip any `m` whose match_id is already in history. This prevents duplicate entries on re-iteration for matches already recorded.

    6. Use try-except wrapping the entire block — failure to create history entries must NOT crash the iteration (graceful degradation).

    The key ordering requirement: this code runs BEFORE `_merge_signals_into_history()` at line 681 and BEFORE `_run_calibrate_and_blend()` at line 684, so that:
    - New entries exist in prediction_history when merge runs (gets market_odds/catboost/form/lineup from ledger)
    - New entries are visible during calibration parameter fitting
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_main_loop.py -x --tb=short -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    When _run_iteration() detects new_matches or new_group_matches, prediction_history entries are created for each.
    Each entry has match_id, team_a, team_b, actual, signals.elo with expected_score probability.
    Entries are created BEFORE _merge_signals_into_history() so merge adds ledger signals.
    No duplicate entries for matches already in history.
  </done>
</task>

<task type="auto">
  <name>Task 2: Pass form_cache and lineup_cache to _run_calibrate_and_blend for blender match_probs</name>
  <files>main.py</files>
  <read_first>
    main.py — lines 106-148 (_run_calibrate_and_blend function)
    main.py — line 684 (call site in _run_iteration)
    main.py — lines 652-672 (form_cache and lineup_cache computation)
  </read_first>
  <action>
    Update `_run_calibrate_and_blend()` to accept and forward `form_cache` and `lineup_cache` to `calibrate_and_blend()`, so that the Flow C match_probs implementation (Defect D in Plan 17b-03) can read form and lineup probabilities.

    Two changes:

    **Change 1 — Function signature and call site:**
    At line 106, change the function signature to accept two additional optional parameters after `cb_cache`:
    ```python
    def _run_calibrate_and_blend(
        teams, groups, bracket, odds_cache, cb_cache,
        form_cache=None, lineup_cache=None,
    )
    ```

    At line 684 (the call site in _run_iteration), add `form_cache` and `lineup_cache` as named arguments:
    ```python
    blend_params = _run_calibrate_and_blend(
        teams, groups, bracket, odds_cache, cb_cache,
        form_cache=form_cache, lineup_cache=lineup_cache,
    )
    ```
    Both `form_cache` and `lineup_cache` are local variables in _run_iteration scope at that point (computed at lines 652-672).

    **Change 2 — Forward caches to calibrate_and_blend:**
    At lines 129-137 (the call to `calibrate_and_blend()` inside `_run_calibrate_and_blend`), add:
    ```python
    blend_params = calibrate_and_blend(
        ...
        odds_cache=odds_cache or {},
        cb_cache=cb_cache or {},
        form_cache=form_cache or {},   # NEW
        lineup_cache=lineup_cache or {},  # NEW
    )
    ```

    Use `or {}` defaults so the parameters are always non-None dicts for the blender.

    Do NOT change any other callers of `_run_calibrate_and_blend`. There are two other call sites:
    - Line 990: shutdown path — already passes `shutdown_odds` and `shutdown_cb`, will get defaults for form/lineup.
    - Line 129 in `_run_calibrate_and_blend` is the internal call to `calibrate_and_blend` — already handled above.

    This change is safe because both `form_cache` and `lineup_cache` have default `None` values, so existing callers (shutdown path at line 990) continue to work unchanged.
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_main_loop.py -x --tb=short -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    `_run_calibrate_and_blend()` accepts `form_cache` and `lineup_cache` params and forwards them.
    Call site at line 684 passes the local `form_cache` and `lineup_cache` variables.
    Existing callers (shutdown path) continue to work with default None values.
    All existing tests pass.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| _run_iteration → prediction_history | New match results written to persistent history |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-17b-04 | Tampering | append_prediction_history | mitigate | Uses atomic write via _atomic_write_json (existing in state.py) |
| T-17b-05 | DoS | _run_iteration crash | mitigate | Entire history-creation block wrapped in try-except — failure is non-fatal |
| T-17b-06 | Information Disclosure | Match data in history | accept | Match results are public tournament data; no PII in entries |
</threat_model>

<verification>
1. `python -m pytest tests/test_main_loop.py -x --tb=short` passes
2. Manual code review: history entries created before merge, duplicate guard present
3. `python -m pytest -x --tb=short` (full suite) passes — zero regression
</verification>

<success_criteria>
- New prediction_history entries created per-iteration for newly-finished matches
- Entries include match_id, team_a, team_b, actual, signals.elo with expected_score
- Deduplication guard prevents entry bloat for matches already in history
- form_cache and lineup_cache passed to _run_calibrate_and_blend → forwarded to calibrate_and_blend
- Zero regression on full test suite
</success_criteria>
