---
phase: 17b-signal-pipeline-repair
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/predictors/catboost.py
  - src/predictors/odds.py
autonomous: true
requirements:
  - V2-05
  - V2-06
  - V2-20
user_setup: []

must_haves:
  truths:
    - "CatBoost parser correctly extracts percentage values from BSD flat-format API response and converts to 0-1 probabilities"
    - "CatBoost predictions are upserted into the prediction ledger at fetch time (matching form/lineup pattern)"
    - "Market odds predictions are upserted into the prediction ledger at fetch time (matching form/lineup pattern)"
    - "The prediction ledger contains both market_odds and catboost entries keyed by match_id"
    - "Existing 527+ tests continue to pass (zero regression)"
  artifacts:
    - path: "src/predictors/catboost.py"
      provides: "Fixed CatBoost parser — flat field names, percentage→float conversion, ledger_upsert call"
      changed_lines: "~10 lines (field defs at 41-43, parse logic at 163-203, fetch at 254-266)"
    - path: "src/predictors/odds.py"
      provides: "Market odds ledger_upsert call added to fetch_and_cache_odds()"
      changed_lines: "~8 lines added after line 194"
    - path: "data/predictions_ledger.json"
      provides: "Contains catboost entries after next CatBoost fetch; contains market_odds entries after next odds refresh"
  key_links:
    - from: "src/predictors/catboost.py"
      to: "src/state.py::ledger_upsert"
      via: "import + call in fetch_and_cache_catboost()"
      pattern: "ledger_upsert.*catboost"
    - from: "src/predictors/odds.py"
      to: "src/state.py::ledger_upsert"
      via: "import + call in fetch_and_cache_odds()"
      pattern: "ledger_upsert.*market_odds"
---

<objective>
Repair: CatBoost parser field mapping (Defect A) and market odds ledger upsert (Defect B Gap 1).

Purpose: Fix two signal ingestion defects that prevent CatBoost and market odds signals from being stored in the permanent prediction ledger. Without this, both signals are computed at fetch time but discarded on TTL expiry — never reaching the blender.

Output:
- `src/predictors/catboost.py` — parser reads flat top-level percentage fields, converts to 0-1, calls ledger_upsert
- `src/predictors/odds.py` — `fetch_and_cache_odds()` calls ledger_upsert matching form.py:346-348 pattern
</objective>

<execution_context>
@C:/Users/KIIT0001/.config/opencode/get-shit-done/workflows/execute-plan.md
@C:/Users/KIIT0001/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/17b-signal-pipeline-repair/17b-CONTEXT.md
@src/predictors/catboost.py
@src/predictors/odds.py
@src/predictors/form.py
@src/predictors/lineup.py
@src/state.py

<interfaces>
From `src/state.py:787-808` — ledger_upsert signature:
```python
def ledger_upsert(match_id: str, signal_name: str, entry: dict, data_dir=None) -> None
```

From `src/predictors/form.py:346-348` — reference ledger_upsert pattern:
```python
from src.state import ledger_upsert
for mid, entry in result.items():
    ledger_upsert(mid, "form", entry)
```

From `src/predictors/lineup.py:193-195` — same pattern:
```python
from src.state import ledger_upsert
for mid, entry in result.items():
    ledger_upsert(mid, "lineup_strength", entry)
```

From `src/predictors/catboost.py:38-43` — current field name tuples:
```python
_HOME_FIELDS = ("home_probability", "home_win", "probability_home")
_DRAW_FIELDS = ("draw_probability", "draw", "probability_draw")
_AWAY_FIELDS = ("away_probability", "away_win", "probability_away")
```

From `src/predictors/catboost.py:166-201` — current parsing logic that reads nested `prediction.get("predictions")` sub-dict
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix CatBoost parser and add ledger upsert</name>
  <files>src/predictors/catboost.py</files>
  <read_first>
    src/predictors/catboost.py — full file (304 lines)
    src/predictors/form.py — lines 343-350 for the ledger_upsert pattern
    17b-CONTEXT.md — decisions D-01 through D-04
  </read_first>
  <action>
    Fix the CatBoost parser to handle the BSD API's flat percentage field format (per D-01, D-02, D-03), and add ledger_upsert call (per D-04).

    Key changes:
    1. **Remove nested `predictions` sub-dict read** — At line 166, the code reads `prediction.get("predictions")` which returns None because the BSD API returns flat fields at the top level. Replace the entire block from line 166 (`predictions_dict = prediction.get("predictions")`) through line 201 (`result[match_id] = entry`) with direct reads from the `prediction` dict.

    2. **Extract probabilities from top-level** — Read `home_prob`, `draw_prob`, `away_prob` using `_extract_probability(prediction, _HOME_FIELDS)` etc. directly from the `prediction` dict (not a sub-dict). The field name tuples at lines 41-43 are correct — `home_probability`, `draw_probability`, `away_probability` are the actual top-level keys. Keep the tuples unchanged.

    3. **Percentage→float conversion** — Per D-02, the API returns 0-100 percentages, not 0-1 floats. After extracting each raw value, divide by 100.0. If any value is None, the signal is `available: false`. After conversion, validate the 0-1 range.

    4. **confidence and model_version** — Read `confidence` and `model_version` from top-level `prediction` dict (not from a sub-dict), matching the flat API response shape.

    5. **ledger_upsert call** — In `fetch_and_cache_catboost()` (around line 258, after `parsed = parse_catboost_response(...)` and before the `return` statement), add a ledger_upsert loop matching the form.py:346-348 pattern:
       - Try-except wrapping the loop
       - Import `ledger_upsert` from `src.state` inside the try block
       - For each `(mid, entry)` in `parsed.items()`: call `ledger_upsert(mid, "catboost", entry)`
       - On exception: log warning with `exc_info=True` (non-fatal — cache is still returned)

    6. **Preserve fallback chain** — The `_extract_probability()` function and the field-name fallback tuple pattern are correct per D-03. Do not change `_extract_probability()` or the field name tuples at lines 41-43.

    The exact replacement for lines 166-201 should implement:
    - Extract raw percentage values via `_extract_probability(prediction, _HOME_FIELDS)` etc.
    - Convert each: `val / 100.0` if not None, else None
    - If any is None → `available: false, reason: "predictions_not_available"`
    - If any is outside [0, 1] after conversion → `available: false, reason: "invalid_probability"`
    - Otherwise → store `probability=home_prob`, `available: true`
    - `confidence` = `prediction.get("confidence")` (top-level)
    - `model_version` = `prediction.get("model_version")` (top-level)
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_catboost.py -x -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    Existing catboost tests are updated to match new fixture shape and pass.
    `_extract_probability` is used against the top-level `prediction` dict.
    Percentage values (0-100) are divided by 100.0 during extraction.
    `ledger_upsert(mid, "catboost", entry)` is called for every parsed entry.
    Ledger is saved with catboost entries after the function runs.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add ledger_upsert call to fetch_and_cache_odds</name>
  <files>src/predictors/odds.py</files>
  <read_first>
    src/predictors/odds.py — full file (200 lines), especially lines 165-200 (fetch_and_cache_odds)
    src/predictors/form.py — lines 343-350 for the ledger_upsert pattern
    17b-CONTEXT.md — decisions D-05
  </read_first>
  <action>
    Add `ledger_upsert` call to `fetch_and_cache_odds()` (per D-05).

    The function currently builds the return cache dict at line 196 and returns it at line 200. Between lines 195 and 196 (after `parsed = parse_odds_response(...)` and before `return`), insert a ledger_upsert loop matching the form.py:346-348 pattern.

    Implementation:
    - Guard with `if parsed:` — only upsert if there are matches
    - Inside try-except block (import `ledger_upsert` from `src.state` inside try)
    - Iterate `for mid, entry in parsed.items():` and call `ledger_upsert(mid, "market_odds", entry)`
    - On exception: `logger.warning("Failed to upsert market_odds into prediction ledger", exc_info=True)`
    - This is non-fatal — the cache dict is still returned regardless

    The `logger` variable is already defined at module level (line 19). No import needed.

    Exact insertion point: after line 194 `parsed = parse_odds_response(...)` and before line 196 `return {`. Add the ledger_upsert code between them. This ensures the ledger is populated before the cache dict is returned to the caller.
  </action>
  <verify>
    <automated>cd /worldcup_predictor && python -m pytest tests/test_odds.py -x -v 2>&1 | Select-String -Pattern "passed|failed|ERROR"</automated>
  </verify>
  <done>
    `fetch_and_cache_odds()` calls `ledger_upsert(mid, "market_odds", entry)` for every parsed match.
    Odds existing tests pass with zero regressions.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| BSD API → prediction ledger | Untrusted API response written to local ledger file |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-17b-01 | Tampering | ledger_upsert call | mitigate | ledger_upsert writes via atomic tmpfile+os.replace (existing in state.py) |
| T-17b-02 | DoS | Malformed API values | mitigate | percentage→float guarded by isinstance check in _extract_probability; divide-by-100 on validated numeric |
| T-17b-03 | Information Disclosure | BSD_API_KEY | accept | Existing pattern — key in Authorization header, never logged; no change in this plan |
| T-17b-SC | Tampering | npm/pip/cargo installs | accept | No new packages (pure stdlib + requests already in project) |
</threat_model>

<verification>
1. `python -m pytest tests/test_catboost.py tests/test_odds.py -x --tb=short` passes
2. CatBoost fixture updated to flat-format percentages, parser returns correct 0-1 probabilities
3. Ledger upsert test: monkeypatch `ledger_upsert` in both test suites, verify called with correct args
</verification>

<success_criteria>
- CatBoost parser: flat top-level field names, percentage→float conversion at /100, available=False when fields missing
- fetch_and_cache_odds: ledger_upsert call added matching form.py pattern
- Both ledger_upsert calls are idempotent (existing state.py implementation — upsert, not append)
- Zero regression on 527+ test suite
</success_criteria>
