# Phase 18: xG & AI Prediction Signals — Pattern Map

**Mapped:** 2026-06-19
**Files analyzed:** 12 (6 source modifications + 1 source addition + 5 test additions)
**Analogs found:** 12 / 12

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/predictors/catboost.py` | predictor/model | CRUD (extract) | `src.predictors.catboost` — same file, `_extract_probability()` L49-70 | exact |
| `src/groups.py` | service | CRUD (compute) | `src.groups.precompute_matchup_lambdas()` L181-205 — same function | exact |
| `src/fetcher.py` | fetcher/enricher | CRUD (entry construction) | `src.fetcher.process_matches()` L87-170 / `process_group_matches()` L247-374 — Phase 17 enrichment pattern | exact |
| `src/output.py` | display/utility | request-response | `src.output.print_match_alert()` L272-282 — same module display function pattern | role-match |
| `src/main.py` | controller/orchestrator | request-response | `src.main._parse_args()` L191-228 — CLI flag pattern + `_run_iteration()` signal cache wiring L689-722 | exact |
| `src/knockout.py` | controller/simulation | CRUD (orchestration) | `src.knockout.run_full_simulation()` L251-289 — forwarding pattern for optional params | exact |
| `tests/test_groups.py` | test | unit | `tests.test_groups.TestExpectedGoals` L27-68 | exact |
| `tests/test_fetcher.py` | test | unit | `tests.test_fetcher` L1-248 | role-match |
| `tests/test_output.py` | test | unit | `tests.test_output._capture()` L61-70 + `TestProbabilityTable` L73-99 | exact |
| `tests/test_group_integration.py` | test | integration | `tests.test_group_integration` fixtures L27-99 | exact |
| `tests/test_main_loop.py` | test | integration | `tests.test_main_loop._runner_code_with_flag()` L59-100 | exact |
| `tests/test_cli.py` | test | unit | `tests.test_cli.TestParseArgs` L6-60 | exact |

## Pattern Assignments

### `src/predictors/catboost.py` (predictor/model, CRUD)

**Analog:** Same file — `_extract_probability()` lines 49-70. The xG extraction follows the identical priority-ordered fallback chain pattern.

**Imports pattern** (lines 22-34):
```python
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from src import constants
from src.fetcher import (
    _find_bracket_match,
    _find_group_match,
    _normalize_team,
)
```

**Priority-ordered fallback pattern** — Field name tuples (lines 38-43) — copy convention for xG:
```python
_HOME_FIELDS = ("home_probability", "home_win", "probability_home")
_DRAW_FIELDS = ("draw_probability", "draw", "probability_draw")
_AWAY_FIELDS = ("away_probability", "away_win", "probability_away")
```

**NEW: xG fallback field tuples** (add alongside existing, before `_extract_probability`):
```python
_XG_HOME_FIELDS = ("expected_home_goals", "home_expected_goals", "xg_home")
_XG_AWAY_FIELDS = ("expected_away_goals", "away_expected_goals", "xg_away")
```

**Probability extraction pattern** — `_extract_probability()` lines 49-70 (copy pattern for `_extract_xg()`):
```python
def _extract_probability(
    data: dict,
    field_names: tuple[str, ...],
) -> float | None:
    """Extract a single probability value by trying field names in priority order."""
    for name in field_names:
        val = data.get(name)
        if val is not None and isinstance(val, (int, float)):
            return float(val) / 100.0
    return None
```

**KEY DIFFERENCE for xG:** Do NOT divide by 100. xG values (e.g., 1.48) are already in correct Poisson lambda scale.

**Entry construction pattern** — Inside `parse_catboost_response()` lines 166-193 (add xG extraction after probability extraction):
```python
# BSD predictions API returns flat top-level fields (percentages 0-100),
# not a nested "predictions" sub-dict. Read directly from prediction dict.
home_prob = _extract_probability(prediction, _HOME_FIELDS)
draw_prob = _extract_probability(prediction, _DRAW_FIELDS)
away_prob = _extract_probability(prediction, _AWAY_FIELDS)

entry: dict = {
    "probability": None,
    "confidence": prediction.get("confidence"),
    "model_version": prediction.get("model_version"),
    "timestamp": timestamp,
}

if home_prob is None or draw_prob is None or away_prob is None:
    entry["available"] = False
    entry["reason"] = "predictions_not_available"
elif not (0 <= home_prob <= 1 and 0 <= draw_prob <= 1 and 0 <= away_prob <= 1):
    entry["available"] = False
    entry["reason"] = "invalid_probability"
else:
    entry["probability"] = home_prob
    entry["available"] = True

result[match_id] = entry
```

**NEW: xG extraction snippet** (add inside per-prediction loop, after entry dict built):
```python
# Phase 18: xG extraction — values are raw expected goals, not percentages (D-02)
# No /100 division (Pitfall 2 guard)
home_xg = _extract_xg(prediction, _XG_HOME_FIELDS)
away_xg = _extract_xg(prediction, _XG_AWAY_FIELDS)
if home_xg is not None:
    entry["expected_home_goals"] = home_xg
if away_xg is not None:
    entry["expected_away_goals"] = away_xg
```

---

### `src/groups.py` (service, CRUD)

**Analog:** Same file — `precompute_matchup_lambdas()` lines 181-205. Minimal modification.

**Existing function** (lines 181-205):
```python
def precompute_matchup_lambdas(
    groups: dict,
    elo_ratings: dict[str, float],
) -> dict[str, tuple[float, float]]:
    """Precompute expected goals (λ) for every group match."""
    groups_data = groups.get("groups", groups)
    lambdas: dict[str, tuple[float, float]] = {}
    for group_data in groups_data.values():
        for match in group_data["matches"]:
            mid = match["match_id"]
            ta, tb = match["team_a"], match["team_b"]
            ea, eb = elo_ratings[ta], elo_ratings[tb]
            lambdas[mid] = (expected_goals(ea, eb), expected_goals(eb, ea))
    return lambdas
```

**Modified signature** (D-03: add `xg_overrides` param):
```python
def precompute_matchup_lambdas(
    groups: dict,
    elo_ratings: dict[str, float],
    xg_overrides: dict[str, tuple[float, float]] | None = None,
) -> dict[str, tuple[float, float]]:
```

**Modified inner loop** (D-04: xG check):
```python
    for group_data in groups_data.values():
        for match in group_data["matches"]:
            mid = match["match_id"]
            ta, tb = match["team_a"], match["team_b"]
            ea, eb = elo_ratings[ta], elo_ratings[tb]
            
            # D-04: xG override when available, else Elo-derived
            if xg_overrides and mid in xg_overrides:
                lambdas[mid] = xg_overrides[mid]
            else:
                lambdas[mid] = (expected_goals(ea, eb), expected_goals(eb, ea))
    return lambdas
```

**No changes needed to:**
- `_simulate_single_match()` (L121-178) — already accepts optional `lambda_a`/`lambda_b` via D-07
- `simulate_group_matches()` (L208-330) — already forwards `matchup_lambdas` unchanged

---

### `src/fetcher.py` (fetcher/enricher, CRUD)

**Analog:** Same file — `process_matches()` lines 149-167 and `process_group_matches()` lines 353-370. Follows Phase 17 enrichment pattern (stats/context extraction).

**Process matches enrichment pattern** (lines 160-166):
```python
entry: dict = {
    "match_id": bracket_id,
    "team_a": home_norm,
    "team_b": away_norm,
    "winner": winner,
    # ... other keys
}

stats = extract_stats(match)
if stats is not None:
    entry["stats"] = stats

ctx = extract_context(match)
if ctx is not None:
    entry["context"] = ctx
```

**NEW: AI preview extraction** (add after context extraction in both `process_matches()` and `process_group_matches()`):
```python
# Phase 18: AI preview (D-08, D-10) — inline extraction
preview = match.get("ai_preview")
if isinstance(preview, dict):
    text = preview.get("text")
    if text and isinstance(text, str):
        entry["ai_preview"] = text.strip()
```

**NEW: Helper function** (add to fetcher.py module level):
```python
def _extract_ai_preview(raw_event: dict) -> str | None:
    """Extract AI preview text from a raw BSD event dict.
    
    AI preview is a nested dict: {"text": "...", "generated_at": "..."}.
    Returns the text string or None if absent.
    
    Graceful degradation (D-11): missing preview = None. No warnings. No errors.
    """
    preview = raw_event.get("ai_preview")
    if isinstance(preview, dict):
        text = preview.get("text")
        if text and isinstance(text, str):
            return text.strip()
    return None
```

**Applied in** `process_matches()` line ~167 (after context) and `process_group_matches()` line ~371 (after context):
```python
ai_preview = _extract_ai_preview(match)
if ai_preview is not None:
    entry["ai_preview"] = ai_preview
```

---

### `src/output.py` (display/utility, request-response)

**Analog:** `print_match_alert()` lines 272-282 — same module's display function pattern. Also `print_group_standings()` L176-216 for section-header pattern.

**Imports pattern** (lines 6-8):
```python
import logging
import sys
import time
from typing import Callable

from src.constants import GROUP_COUNT, MATCHES_PER_GROUP, POLL_INTERVAL
```

**Display function pattern** (follow `print_match_alert` L272-282 approach):
```python
def print_match_alert(match: dict) -> None:
    """Print highlighted match result block with bold yellow banner."""
    print()
    print(_bold_yellow("=" * 60))
    print(_bold_yellow("  NEW MATCH DETECTED!"))
    team_a = _bold_white(match["team_a"])
    team_b = _bold_white(match["team_b"])
    print(f"  {team_a} {match['home_score']} - {match['away_score']} {team_b}")
    print(f"  Winner: {match['winner']}")
    print(_bold_yellow("=" * 60))
```

**NEW: `print_ai_previews()` function** — follow same docstring + print conventions:
```python
def print_ai_previews(played: dict, played_groups: dict) -> None:
    """Print AI preview text for all played matches.
    
    Args:
        played: Dict of played knockout matches.
        played_groups: Dict of played group matches.
    
    Graceful degradation (D-11): missing ai_preview = skipped. No warnings. No errors.
    """
    has_any = False
    
    # Group matches (chronological by match_id prefix)
    for group_letter in "ABCDEFGHIJKL"[:GROUP_COUNT]:
        group_matches = [m for m in played_groups.values() 
                        if m.get("match_id", "").startswith(f"GS_{group_letter}_")]
        if not group_matches:
            continue
        for match in sorted(group_matches, key=lambda m: m.get("match_id", "")):
            preview = match.get("ai_preview")
            if preview:
                if not has_any:
                    print(_bold_white("\n─── AI Previews ───"))
                    has_any = True
                print(f"\n{_bold_white(match['team_a'])} vs {_bold_white(match['team_b'])}:")
                print(preview)
    
    # Knockout matches (after group section)
    if played:
        for mid in sorted(played):
            match = played[mid]
            preview = match.get("ai_preview")
            if preview:
                if not has_any:
                    print(_bold_white("\n─── AI Previews ───"))
                    has_any = True
                print(f"\n{_bold_white(match['team_a'])} vs {_bold_white(match['team_b'])}:")
                print(preview)
    
    if not has_any:
        print(_dim("No AI previews available."))
```

**ANSI wrappers available** (L39-46) — reuse: `_bold_white`, `_dim`, `_bold_cyan`:
```python
_dim = _ansi("2")
_bold_cyan = _ansi("1;36")
_green = _ansi("32")
_red = _ansi("31")
_bold_green = _ansi("1;32")
_bold_white = _ansi("1;37")
_bold_yellow = _ansi("1;33")
_bold_red = _ansi("1;31")
```

---

### `src/main.py` (controller/orchestrator, request-response)

**Analog:** `_parse_args()` lines 191-228 for CLI flag pattern + `_run_iteration()` signal cache wiring lines 689-722 for xG wiring pattern.

**CLI argument pattern** (lines 209-227):
```python
parser.add_argument(
    "--once",
    action="store_true",
    dest="once",
    help="Run a single fetch→simulate→print cycle, then exit",
)
parser.add_argument(
    "--no-color",
    action="store_true",
    dest="no_color",
    help="Disable ANSI color output (overrides terminal auto-detection)",
)
parser.add_argument(
    "--seed",
    type=int,
    default=None,
    metavar="N",
    help="Random seed for reproducible simulation (same seed + same data = same results)",
)
```

**NEW: `--ai-preview` flag** (add to `_parse_args()` alongside existing flags):
```python
parser.add_argument(
    "--ai-preview",
    action="store_true",
    dest="ai_preview",
    help="Display AI-powered pre-match analysis for played matches",
)
```

**xG wiring pattern** — In `_run_iteration()`, after CatBoost cache is loaded (around L690-700), build xg_overrides dict:
```python
# ── Phase 18: Build xG overrides dict from CatBoost cache (D-02, D-06) ──
xg_overrides: dict[str, tuple[float, float]] | None = None
cb_matches = cb_cache.get("matches", {}) if cb_cache else {}
for mid, entry in cb_matches.items():
    home_xg = entry.get("expected_home_goals")
    away_xg = entry.get("expected_away_goals")
    if home_xg is not None and away_xg is not None:
        if xg_overrides is None:
            xg_overrides = {}
        xg_overrides[mid] = (home_xg, away_xg)
```

**Pass xg_overrides through to simulation** — modify `run_full_simulation()` call (L858):
```python
probs = run_full_simulation(
    teams, groups, bracket, annex_c, played,
    played_groups=played_groups, iterations=50000, seed=seed,
    blend_params=blend_params, xg_overrides=xg_overrides,
)
```

**AI preview display** — After `output.print_probability_table()` in `_run_iteration()` (~L868):
```python
if args.ai_preview:
    output.print_ai_previews(played, played_groups)
```

**IMPORTANT:** `_compute_group_display()` (L246-275) calls `precompute_matchup_lambdas()` without xG overrides — this is CORRECT per D-04 fallback (display uses Elo lambdas).

---

### `src/knockout.py` (controller/simulation, CRUD)

**Analog:** Same file — `run_full_simulation()` lines 251-318. Modify signature and internal wiring.

**Existing signature** (lines 251-261):
```python
def run_full_simulation(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    played: dict[str, dict],
    iterations: int = 50000,
    seed: int | None = None,
    played_groups: dict[str, dict] | None = None,
    blend_params: dict | None = None,
) -> dict[str, dict[str, float]]:
```

**Modified signature** (add `xg_overrides` param):
```python
def run_full_simulation(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    played: dict[str, dict],
    iterations: int = 50000,
    seed: int | None = None,
    played_groups: dict[str, dict] | None = None,
    blend_params: dict | None = None,
    xg_overrides: dict[str, tuple[float, float]] | None = None,
) -> dict[str, dict[str, float]]:
```

**Modified internal wiring** (line 289). Change from:
```python
matchup_lambdas = precompute_matchup_lambdas(groups, elo_ratings)
```
To:
```python
matchup_lambdas = precompute_matchup_lambdas(
    groups, elo_ratings, xg_overrides=xg_overrides,
)
```

---

## Test Patterns

### `tests/test_groups.py` — TestPrecomputeMatchupLambdas class

**Analog:** `TestExpectedGoals` class lines 27-68 — test class structure pattern.

**Fixture pattern** (from `test_group_integration.py` L27-48):
```python
@pytest.fixture
def sample_groups():
    """Minimal 1-group fixture."""
    return {
        "groups": {
            "A": {
                "teams": ["Mexico", "South Africa"],
                "matches": [
                    {"match_id": "GS_A_01", "team_a": "Mexico", "team_b": "South Africa", ...},
                ],
            }
        }
    }

@pytest.fixture
def elo_ratings():
    return {"Mexico": 1850.0, "South Africa": 1700.0}
```

**Test pattern** (new test class):
```python
class TestPrecomputeMatchupLambdas:
    """Tests for xG override behavior in precompute_matchup_lambdas()."""
    
    def test_xg_overrides_applied(self, sample_groups, elo_ratings):
        """When xg_overrides provided and match_id present, use xG values."""
        xg_overrides = {"GS_A_01": (2.5, 0.8)}
        lambdas = precompute_matchup_lambdas(sample_groups, elo_ratings, xg_overrides=xg_overrides)
        assert lambdas["GS_A_01"] == (2.5, 0.8)
    
    def test_fallback_when_no_xg(self, sample_groups, elo_ratings):
        """When xg_overrides is None, use Elo-derived expected_goals()."""
        lambdas = precompute_matchup_lambdas(sample_groups, elo_ratings)
        la, lb = lambdas["GS_A_01"]
        assert la > 0
        assert lb > 0
        # Elo: Mexico(1850) vs South Africa(1700) → home expected_goals > away
        assert la > lb
    
    def test_fallback_when_mid_absent(self, sample_groups, elo_ratings):
        """When match_id not in xg_overrides, use Elo-derived lambdas."""
        xg_overrides = {"GS_B_01": (3.0, 1.0)}  # different match
        lambdas = precompute_matchup_lambdas(sample_groups, elo_ratings, xg_overrides=xg_overrides)
        la, lb = lambdas["GS_A_01"]
        # Must be Elo-derived, not from xg_overrides
        assert la != 3.0
        assert lb != 1.0
```

### `tests/test_fetcher.py` — AI preview extraction tests

**Analog:** Existing test patterns in `test_fetcher.py` using `SAMPLE_MATCHES` L31-42 fixture + `MockResponse` L11-28.

**Test pattern**:
```python
def test_ai_preview_extracted(monkeypatch):
    """AI preview extracted from raw event and stored inline."""
    match = {
        "id": 12345,
        "status": "finished",
        "home_team": "Mexico",
        "away_team": "South Africa",
        "home_score": 2,
        "away_score": 0,
        "event_date": "2026-06-11T23:00:00Z",
        "group_name": "Group A",
        "round_number": 1,
        "league": {"id": 27},
        "ai_preview": {"text": "Mexico expected to dominate possession."},
    }
    # ... call _extract_ai_preview or process_group_matches
    # Assert ai_preview in result entry

def test_ai_preview_missing(monkeypatch):
    """Missing ai_preview produces no warnings or errors."""
    match = {
        "id": 12346,
        "status": "finished",
        # ... same, but no ai_preview key
    }
    # ... call _extract_ai_preview or process_group_matches
    # Assert no ai_preview key in result entry
    # Assert no crashes
```

### `tests/test_output.py` — print_ai_previews display test

**Analog:** `_capture()` helper L61-70 and `TestProbabilityTable` L73-99.

**Capture pattern**:
```python
def _capture(func, *args, **kwargs):
    """Run func(*args, **kwargs) and return captured stdout string."""
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = real
    return buf.getvalue()
```

**Test pattern**:
```python
def test_print_ai_previews_shows_text():
    """print_ai_previews displays AI preview text for matches that have it."""
    played_groups = {
        "GS_A_01": {
            "match_id": "GS_A_01",
            "team_a": "Mexico", "team_b": "South Africa",
            "ai_preview": "Mexico favored to win.",
        }
    }
    output = _capture(print_ai_previews, {}, played_groups)
    assert "Mexico" in output
    assert "South Africa" in output
    assert "Mexico favored to win." in output

def test_print_ai_previews_no_data():
    """When no matches have ai_preview, prints 'No AI previews available.'"""
    played_groups = {
        "GS_A_01": {"match_id": "GS_A_01", "team_a": "Mexico", "team_b": "South Africa"}
    }
    output = _capture(print_ai_previews, {}, played_groups)
    assert "No AI previews available." in output
```

### `tests/test_cli.py` — --ai-preview flag test

**Analog:** `TestParseArgs` class lines 6-60.

**Test pattern**:
```python
def test_ai_preview_flag(self):
    """--ai-preview flag sets ai_preview=True."""
    args = _parse_args(["--ai-preview"])
    assert args.ai_preview is True
```

### `tests/test_main_loop.py` — --ai-preview integration test

**Analog:** `_runner_code_with_flag()` pattern lines 59-100. Each test invokes main.py as subprocess with mocked API.

### `tests/test_group_integration.py` — xG override integration test

**Analog:** Existing `test_group_integration.py` fixtures L27-99.

**Test pattern** — Set xg_overrides on a group fixture, call `precompute_matchup_lambdas()`, call `simulate_group_matches()`, verify scoreline distribution uses xG values:
```python
def test_xg_override_affects_simulation(group_a_fixture, elo_ratings, teams_dict):
    """xG overrides flow through to group match results."""
    xg_overrides = {"GS_A_01": (3.5, 0.5)}  # Mexico heavily favored
    lambdas = precompute_matchup_lambdas(
        group_a_fixture, elo_ratings, xg_overrides=xg_overrides
    )
    results = simulate_group_matches(
        group_a_fixture, teams_dict, elo_ratings, random.Random(42),
        fair_play=False, matchup_lambdas=lambdas,
    )
    match_1 = results["A"]["GS_A_01"]
    # Given lambda_a=3.5 vs lambda_b=0.5, Mexico should almost always win
    assert match_1["winner"] == "Mexico"
```

---

## Shared Patterns

### Pattern: Priority-Ordered Field Name Fallback
**Source:** `src/predictors/catboost.py` lines 38-43, 49-70
**Apply to:** xG field extraction in `catboost.py`

The BSD API may return fields under different key names across API versions. Use a tuple of field names tried in priority order plus a helper function. For xG, DO NOT divide by 100 (values are already in Poisson lambda scale, e.g., 1.48).

```python
_XG_HOME_FIELDS = ("expected_home_goals", "home_expected_goals", "xg_home")
_XG_AWAY_FIELDS = ("expected_away_goals", "away_expected_goals", "xg_away")

def _extract_xg(
    data: dict,
    field_names: tuple[str, ...],
) -> float | None:
    """Extract xG value by trying field names in priority order.
    
    xG values are already in the correct scale (0.3–3.0) for Poisson
    lambdas — do NOT divide by 100 (Pitfall 2 guard).
    """
    for name in field_names:
        val = data.get(name)
        if val is not None and isinstance(val, (int, float)):
            return float(val)
    return None
```

### Pattern: Inline Enrichment Extraction (Phase 17)
**Source:** `src/fetcher.py` lines 160-166 (stats) + 164-166 (context)
**Apply to:** AI preview extraction in `process_matches()` and `process_group_matches()`

Extract enrichment field from raw event dict after entry construction, store only if non-None. Graceful degradation: None = no key added, no warnings.

```python
# Phase 18: AI preview inline extraction
ai_preview = _extract_ai_preview(match)  # returns str | None
if ai_preview is not None:
    entry["ai_preview"] = ai_preview
```

### Pattern: CLI Argument Addition
**Source:** `main.py` lines 209-227
**Apply to:** `--ai-preview` flag in `main.py`

Follow the existing pattern of `action="store_true"` with `dest`, `help`. Match the coding style (backslash-escaped Unicode arrow for `→`).

### Pattern: Optional Parameter Forwarding
**Source:** `src/knockout.py` line 289 (blend_params forwarding), `simulate_group_matches()` L245-246
**Apply to:** `xg_overrides` forwarding through `run_full_simulation()` → `precompute_matchup_lambdas()`

Optional dict param with `None` default throughout the call chain. No intermediate function inspects the param — just forwards it downstream. The terminal function (`precompute_matchup_lambdas()`) applies the logic.

### Pattern: Graceful Degradation — Missing Data
**Source:** `src/predictors/catboost.py` lines 182-191 (available=False patterns)
**Apply to:** xG (fallback to Elo lambda) and AI preview (no display) — D-04, D-11

Two flavors:
- **xG:** Missing → fall back to existing Elo-derived `expected_goals()` when `mid not in xg_overrides`. Silent fallback.
- **AI preview:** Missing → no key in entry dict. Display prints "No AI previews available." No warnings, no errors.

### Pattern: Test with `_capture` stdout helper
**Source:** `tests/test_output.py` lines 61-70
**Apply to:** `print_ai_previews` display tests

```python
def _capture(func, *args, **kwargs):
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = real
    return buf.getvalue()
```

### Pattern: Unit Test for CLI Parsing
**Source:** `tests/test_cli.py` lines 6-60
**Apply to:** `--ai-preview` flag in `tests/test_cli.py`

Direct call to `_parse_args()` with a list of flag strings. Assert the expected Namespace attribute.

### Pattern: Integration Test with Subprocess Runner
**Source:** `tests/test_main_loop.py` lines 59-100 (`_runner_code_with_flag`)
**Apply to:** `--ai-preview` flag integration test

Patches `sys.argv` then runs `main.main()` via inline Python passed to subprocess. Mocks `requests.get` and `run_full_simulation` to isolate from network.

---

## No Analog Found

All 12 files have strong analogs in the existing codebase. No file requires greenfield pattern creation.

| File | Role | Data Flow | Analog Source | Rationale |
|------|------|-----------|---------------|-----------|
| All | — | — | — | Every change follows existing patterns in the same file or adjacent files |

## Metadata

**Analog search scope:** `src/` (all Python files), `tests/` (all Python files)
**Files scanned:** 18 (all source + test files in project)
**Pattern extraction date:** 2026-06-19

**Key findings:**
1. **xG extraction** follows identical pattern to probability extraction (priority-ordered fallback, helper function) but WITHOUT /100 division
2. **xG override** is a 5-line change to `precompute_matchup_lambdas()` signature + inner loop
3. **AI preview extraction** follows Phase 17 enrichment pattern (inline, optional key, graceful degradation)
4. **AI preview display** follows existing `print_*` function conventions in `output.py`
5. **CLI flag** follows existing `--once`/`--no-color`/`--seed` pattern
6. **Test patterns** are well-established — unit tests with fixtures, integration tests with subprocess runners
