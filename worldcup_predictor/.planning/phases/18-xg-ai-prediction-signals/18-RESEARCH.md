# Phase 18: xG & AI Prediction Signals — Research

**Researched:** 2026-06-19
**Domain:** BSD API xG integration + AI preview enrichment + CLI flags
**Confidence:** HIGH

## Summary

Phase 18 integrates two BSD API data sources into the existing codebase with minimal
architectural change. xG (`expected_home_goals`, `expected_away_goals`) from the
predictions endpoint becomes an optional lambda override in `precompute_matchup_lambdas()`,
replacing Elo-derived `expected_goals()` when available. AI preview text (`ai_preview.text`)
from the events endpoint is extracted inline in the existing enrichment pipeline and
displayed only when `--ai-preview` CLI flag is passed.

**xG is NOT a blender signal** — confirmed by BSD probe that xG fields are sibling fields
of the same v5.0 CatBoost probability predictions. Adding xG as an independent signal would
double-count the same model. Instead, xG provides more accurate Poisson lambda parameters
for scoreline distribution, improving tiebreaker resolution.

**Primary recommendation:** 3 plans — (1) xG extraction from catboost.py + lambda override in
groups.py, (2) AI preview enrichment in fetcher.py + output.py, (3) CLI wiring in main.py +
tests. Each plan independently testable.

**Total estimated changed lines:** ~60-80 across 6 source files + ~60-100 lines of tests.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** xG is NOT a blender signal. No `signal_keys` addition, no xg cache, no xg ledger entries, no calibration changes, no governance changes.
- **D-02:** `expected_home_goals` and `expected_away_goals` (from BSD predictions endpoint) become optional lambda overrides in `precompute_matchup_lambdas()`.
- **D-03:** New signature:
  ```python
  def precompute_matchup_lambdas(
      groups: dict,
      elo_ratings: dict[str, float],
      xg_overrides: dict[str, tuple[float, float]] | None = None,
  ) -> dict[str, tuple[float, float]]:
  ```
- **D-04:** When `xg_overrides` provided and `mid in xg_overrides`, use the xG values as (lambda_a, lambda_b). Otherwise fall back to Elo-derived `expected_goals()`.
- **D-05:** `xg_overrides` dict is populated from the predictions endpoint response — `expected_home_goals` → lambda_a, `expected_away_goals` → lambda_b, keyed by match_id. Match_id resolution uses the same team-pair matching logic as catboost.py.
- **D-06:** xG values are extracted during the existing catboost predictions fetch. No separate API call.
- **D-07:** `_simulate_single_match()` already accepts optional precomputed lambdas (line 123) — no change needed. `simulate_group_matches()` passes `matchup_lambdas` through — no change needed.
- **D-08:** Storage — `ai_preview` stored inline on played.json / played_groups.json entries, following Phase 17 enrichment pattern. No separate `ai_previews.json` file.
- **D-09:** Display — default console output unchanged. AI preview shown only when `--ai-preview` CLI flag is passed.
- **D-10:** Source — `ai_preview` field from BSD events endpoint. Extracted in the same enrichment step as Phase 17.
- **D-11:** Graceful degradation — missing `ai_preview` = no display. No warnings. No errors.
- **D-12:** No backfill of xG or AI preview for already-played matches.
- **D-13:** xG overrides are only useful pre-match. Predictions endpoint does not serve predictions for past matches.
- **D-14:** AI preview for played matches could be backfilled but Phase 18 skips it.
- **D-15:** xG collected for all future/upcoming matches from the predictions endpoint going forward.

### the agent's Discretion

- **How AI preview text is displayed:** One block at the end? Per-match inline? Formatting? (CONTEXT.md specifics suggest "print AI previews for all matches that have them in a single block")
- **Whether to add `extract_ai_preview()` to enrichment.py or inline in fetcher.py.** The CONTEXT.md says "add `ai_preview` extraction" in the entry construction, which suggests inline is simpler. But enrichment.py could be extended following Phase 17 pattern.
- **How to handle `ai_preview` for knockout vs. group entries** — both `process_matches()` and `process_group_matches()` need extraction.
- **Test structure** — unit vs. integration test split at the researcher's discretion.

### Deferred Ideas (OUT OF SCOPE)

- Actual xG as evaluation metric
- xG display in console (Phase 20 — Output Enhancement)
- AI preview in backtest reports

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| V2-23 | BSD xG predictions (`expected_home_goals`, `expected_away_goals`) ingested as optional Poisson simulation lambda overrides | Confirmed BSD field names, confirmed they share the same model as catboost (not a separate signal). Integration point: `precompute_matchup_lambdas()` in groups.py. Extraction point: `parse_catboost_response()` in catboost.py. |
| V2-24 | BSD AI preview / pre-match analysis ingested and displayed | `ai_preview.text` field confirmed on events endpoint via BSD probe. Integration point: entry construction in `process_matches()` + `process_group_matches()`. Display: `--ai-preview` CLI flag. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| xG field extraction | API / Backend (catboost.py) | — | xG extracted from predictions endpoint response during existing parse_catboost_response() call. Same parse step as probabilities. |
| Lambda override substitution | API / Backend (groups.py) | — | precompute_matchup_lambdas() computes match lambdas. xG overrides slot into existing logic — minimal change. |
| xG wiring from cache to simulation | API / Backend (main.py) | — | runner.py / main.py reads cb_cache, builds xg_overrides dict, passes into run_full_simulation(). |
| AI preview extraction | API / Backend (fetcher.py) | enrichment.py (optional helper) | AI preview extracted from raw event dict in the same enrichment step (process_matches / process_group_matches). |
| AI preview storage | Database / Storage (played JSON files) | — | Stored inline on played.json / played_groups.json — no new files, no new state.py functions. |
| AI preview display | CLI / Console (output.py + main.py) | — | --ai-preview flag triggers console display of stored ai_preview text. New output function. |
| Test coverage | Test suite | — | Unit tests for lambda override, extraction, display. Integration tests for end-to-end flow. |

## Standard Stack

No new libraries needed. Everything uses existing project stack:

### Core (no new packages)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python standard library | 3.10+ | All logic | Already the project runtime |
| `requests` | 2.x (existing) | BSD API calls | Already used by fetcher.py, catboost.py, odds.py |
| `argparse` (stdlib) | — | CLI flag parsing | Already used by main.py for --once, --no-color, --seed |
| `pytest` | 7.x (existing) | Test framework | Already used by all 540+ existing tests |

### Alternatives Considered
Not applicable — no library choices in this phase.

## Package Legitimacy Audit

No new external packages are required for this phase. All integrations use existing project dependencies (`requests`, standard library modules) and existing source modules.

**Zero new packages to audit.**

## Architecture Patterns

### System Architecture Diagram

```
                 BSD API
                    │
      ┌─────────────┴─────────────┐
      │                           │
  /api/predictions/          /api/events/
      │                           │
      ▼                           ▼
parse_catboost_response()   process_matches() /
(catboost.py)               process_group_matches()
      │                           (fetcher.py)
      │                           │
      ├─ expected_home_goals      ├─ ai_preview.text
      │  expected_away_goals      │
      │                           ▼
      ▼                     played.json /
  cb_cache (TTL)            played_groups.json
      │                           │
      ▼                           ▼
  _run_iteration()           --ai-preview flag?
      │                           │
      ├─ Build xg_overrides       ├─ Yes → print AI preview text
      │  dict from cb_cache       │
      ▼                           └─ No → skip
  run_full_simulation()
      │
      ▼
  precompute_matchup_lambdas()
      │
      ├─ mid in xg_overrides? → use (xg_home, xg_away)
      └─ else → use expected_goals(ea, eb)
      │
      ▼
  simulate_group_matches()
  (uses matchup_lambdas unchanged)
```

### Data Flow: xG Lambda Override

1. `fetch_and_cache_catboost()` → `parse_catboost_response()` reads `expected_home_goals`, `expected_away_goals` alongside probabilities, stores them in the entry dict
2. Entry gets written to prediction ledger via `ledger_upsert(mid, "catboost", entry)`
3. `_run_iteration()` reads `cb_cache = state.load_signal_cache(CATBOOST_CACHE_FILE)`
4. New step: build `xg_overrides` dict from `cb_cache["matches"]` — extract match_id → (expected_home_goals, expected_away_goals) for entries where both values exist
5. Pass `xg_overrides` into `run_full_simulation()` → eventually to `precompute_matchup_lambdas()`

### Data Flow: AI Preview

1. `fetch_raw_matches()` returns raw event dicts from `/api/events/`
2. `process_matches()` / `process_group_matches()` — during entry construction, extract `ai_preview` field
3. AI preview stored inline on the played entry dict
4. Display path: `--ai-preview` flag → iterate over played entries → print `ai_preview` if present

### Recommended Project Structure

No structural changes. All changes are in existing files:
```
src/
├── groups.py             # precompute_matchup_lambdas() — ~5 lines changed
├── predictors/
│   └── catboost.py       # parse_catboost_response() — ~8 lines added
├── fetcher.py            # process_matches/process_group_matches — ~6 lines added
├── enrichment.py         # Optional: extract_ai_preview() helper — ~15 lines
├── output.py             # print_ai_previews() — ~20 lines new function
├── main.py               # CLI flag + wiring — ~25 lines
tests/
├── test_groups.py        # xg_override unit tests — ~40 lines
├── test_fetcher.py       # ai_preview extraction tests — ~20 lines
├── test_enrichment.py    # Optional: extract_ai_preview tests — ~15 lines
└── test_output.py        # --ai-preview display test — ~15 lines
```

### Pattern 1: xG Extraction in parse_catboost_response()
**What:** Extract `expected_home_goals` and `expected_away_goals` from each prediction entry using the same priority-ordered fallback pattern as probability extraction.
**When to use:** During the existing parse loop — add xG field extraction alongside probability extraction.
**Evidence:** BSD probe confirmed these are flat top-level percentage-like fields (e.g., `expected_home_goals: 1.48`, `expected_away_goals: 0.92`) in the same prediction object as `home_probability`.

```
prediction entry shape (confirmed by BSD probe):
{
  "event_id": 1234,
  "home_team": "Mexico",
  "away_team": "South Africa",
  "home_probability": 52.3,
  "draw_probability": 25.1,
  "away_probability": 22.6,
  "expected_home_goals": 1.48,
  "expected_away_goals": 0.92,
  "confidence": 0.85,
  "model_version": "v5.0",
  "updated_at": "2026-06-19T10:00:00Z"
}
```

### Pattern 2: AI Preview via Inline Extraction
**What:** Extract `ai_preview` from raw events endpoint response during match processing. The field is a nested dict: `ai_preview: {"text": "...", "generated_at": "..."}`.
**When to use:** In `process_matches()` and `process_group_matches()`, after the entry dict is constructed. Add `entry["ai_preview"] = extract_ai_preview(match)` or inline the field extraction.
**Evidence:** BSD probe confirmed `ai_preview` exists on the events endpoint (not predictions endpoint) as a dict with `text` key containing markdown-formatted analysis.

### Anti-Patterns to Avoid
- **Adding xG to blender signal_keys:** xG and catboost are the same BSD model — would double-count. D-01 explicitly forbids.
- **Adding xG to prediction_history:** xG is not a prediction signal, it's a simulation parameter. No ledger entry needed beyond what catboost.py already writes.
- **Creating new cache files for xG:** xG lives in the same catboost cache object. D-06 says "no separate API call" which implies no separate cache.
- **Blocking on missing xG:** Some matches may not have predictions (pre-tournament, API gaps). Fallback design handles this — never crash.
- **Complex formatting for AI preview:** CLI constraints — plain text rendering, no markdown rendering required.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| xG as a standalone blender signal | New signal_key, new cache, new ledger, new evaluation | Lambda override in precompute_matchup_lambdas() | Same BSD v5.0 model as catboost — would double-count. D-01. |
| AI preview storage system | New ai_previews.json file, new state.py functions | Inline on played.json / played_groups.json | Phase 17 enrichment pattern already established. D-08. |
| xG API fetching | New HTTP call to predictions endpoint | Extract from existing catboost cache | catboost.py already calls /api/predictions/. xG is in the same response. D-06. |

**Key insight:** This phase is about leveraging existing data flows, not creating new infrastructure. The most expensive parts (API calls, caching, persistence, match_id resolution) are already built.

## Common Pitfalls

### Pitfall 1: xG field name ambiguity
**What goes wrong:** `expected_home_goals` / `expected_away_goals` may have different key names in different API versions or for different leagues.
**Why it happens:** BSD API uses different field conventions across endpoints (as seen with probability field names: `home_probability` vs `probability_home`).
**How to avoid:** Use priority-ordered fallback tuple (same pattern as `_HOME_FIELDS` in catboost.py). Add `_XG_HOME_FIELDS` and `_XG_AWAY_FIELDS` tuples.
**Warning signs:** xG values remain None for matches that should have predictions.

### Pitfall 2: xG type confusion — percentage vs raw value
**What goes wrong:** The BSD probe showed `expected_home_goals: 1.48` (raw expected goals, not a percentage). Unlike probabilities which are 0-100 percentages, xG values are already in the correct scale for Poisson lambdas.
**How to avoid:** Do NOT divide by 100. The values are already in the correct range (typically 0.3-3.0 for expected goals). Store as-is.
**Warning signs:** Scorelines become unrealistically high (if multiplying by 100) or zero (if treating as 0-1 probability).

### Pitfall 3: AI preview markdown in CLI
**What goes wrong:** AI preview text is markdown-formatted (headings, bullet points). Raw markdown in terminal looks cluttered.
**How to avoid:** Store raw text as-is. Display raw text. No markdown rendering needed for CLI. Simple text wrapping optional but not required for Phase 18.
**Warning signs:** Terminal output has raw `**bold**` or `# Heading` markers.

### Pitfall 4: Forgetting _compute_group_display() in main.py
**What goes wrong:** `_compute_group_display()` has its own `precompute_matchup_lambdas()` call that does NOT need xG overrides (display-only, one iteration).
**How to avoid:** No change needed for this call — `xg_overrides=None` (the default) skips xG, which is correct for display purposes.
**Warning signs:** Marking this call as needing an update when it doesn't.

### Pitfall 5: xG for matches without predictions
**What goes wrong:** Some matches may not have predictions in the BSD response (API gaps, future matches beyond prediction horizon).
**How to avoid:** The fallback design handles this — if `mid not in xg_overrides`, use Elo-derived lambdas. No warnings. No errors.
**Warning signs:** Missing predictions treated as errors rather than gracefully degraded.

### Pitfall 6: AI preview for group vs knockout — different extraction points
**What goes wrong:** Both `process_matches()` (knockout) and `process_group_matches()` (group) need AI preview extraction, but they receive the same raw event dicts from `fetch_raw_matches()`.
**How to avoid:** Extract in both functions. AI preview lives on the raw event, not the match type. Same `ai_preview` field at the same level.
**Warning signs:** AI preview only appears for knockout matches and not group matches (or vice versa).

## Code Examples

### 1. xG Extraction in parse_catboost_response()

```python
# In src/predictors/catboost.py — add alongside probability extraction

# Priority-ordered fallback for xG fields (Pitfall 1 guard)
_XG_HOME_FIELDS = ("expected_home_goals", "home_expected_goals", "xg_home")
_XG_AWAY_FIELDS = ("expected_away_goals", "away_expected_goals", "xg_away")

def _extract_xg(
    data: dict,
    field_names: tuple[str, ...],
) -> float | None:
    """Extract xG value by trying field names in priority order.
    
    xG values are already in the correct scale (0.3–3.0) for Poisson 
    lambdas — do NOT divide by 100 (Pitfall 2).
    """
    for name in field_names:
        val = data.get(name)
        if val is not None and isinstance(val, (int, float)):
            return float(val)
    return None
```

Inside the per-prediction loop in `parse_catboost_response()`:
```python
# After probability extraction, extract xG values (Pitfall 2: no /100)
home_xg = _extract_xg(prediction, _XG_HOME_FIELDS)
away_xg = _extract_xg(prediction, _XG_AWAY_FIELDS)

# Add to entry dict alongside existing fields
entry["expected_home_goals"] = home_xg
entry["expected_away_goals"] = away_xg
```

### 2. Lambda Override in precompute_matchup_lambdas()

```python
# In src/groups.py — modified signature per D-03

def precompute_matchup_lambdas(
    groups: dict,
    elo_ratings: dict[str, float],
    xg_overrides: dict[str, tuple[float, float]] | None = None,
) -> dict[str, tuple[float, float]]:
    """Precompute expected goals (λ) for every group match.
    
    λ values depend only on Elo ratings, which are fixed for a simulation run.
    Computing them once and reusing across iterations saves ~5.8s per 50K sims.
    
    When xg_overrides is provided, xG values replace Elo-derived lambdas
    for matching match_ids — providing more accurate scoreline distribution
    without introducing xG as a blender signal (D-01).
    
    Args:
        groups: Groups dict (with or without "groups" wrapper key).
        elo_ratings: Dict mapping team name → Elo rating.
        xg_overrides: Optional dict mapping match_id → (lambda_a, lambda_b)
                      from BSD xG predictions. When provided and mid is present,
                      overrides Elo-derived expected_goals.
    
    Returns:
        Dict mapping match_id → (lambda_a, lambda_b).
    """
    groups_data = groups.get("groups", groups)
    lambdas: dict[str, tuple[float, float]] = {}
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

### 3. Building xg_overrides in main.py

```python
# In src/main.py — inside _run_iteration(), after cb_cache is fetched

# ── Build xG overrides dict from CatBoost cache (D-02, D-06) ──
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

Then pass into `run_full_simulation()`:
```python
probs = run_full_simulation(
    teams, groups, bracket, annex_c, played,
    played_groups=played_groups, iterations=50000, seed=seed,
    blend_params=blend_params, xg_overrides=xg_overrides,
)
```

`run_full_simulation()` passes to `precompute_matchup_lambdas()`:
```python
# In src/knockout.py
matchup_lambdas = precompute_matchup_lambdas(
    groups, elo_ratings, xg_overrides=xg_overrides,
)
```

### 4. AI Preview Extraction

```python
# Option A: Inline in fetcher.py (simplest — no new module needed)

def _extract_ai_preview(raw_event: dict) -> str | None:
    """Extract AI preview text from a raw BSD event dict.
    
    AI preview is a nested dict: {"text": "...", "generated_at": "..."}.
    Returns the text string or None if absent.
    """
    preview = raw_event.get("ai_preview")
    if isinstance(preview, dict):
        text = preview.get("text")
        if text and isinstance(text, str):
            return text.strip()
    return None
```

Used in both `process_matches()` and `process_group_matches()`:
```python
# In entry construction, alongside stats/context extraction
entry = { ... }  # existing entry dict construction

# Phase 17 enrichment
stats = extract_stats(match)
if stats is not None:
    entry["stats"] = stats
ctx = extract_context(match)
if ctx is not None:
    entry["context"] = ctx

# Phase 18: AI preview (D-08, D-10)
ai_preview = _extract_ai_preview(match)
if ai_preview is not None:
    entry["ai_preview"] = ai_preview
```

### 5. CLI Flag and Display

```python
# In main.py _parse_args() — add to existing parser
parser.add_argument(
    "--ai-preview",
    action="store_true",
    dest="ai_preview",
    help="Display AI-powered pre-match analysis for played matches",
)

# In _run_iteration(), after output.print_probability_table()
if args.ai_preview:
    output.print_ai_previews(played, played_groups)
```

```python
# In src/output.py — new function
def print_ai_previews(played: dict, played_groups: dict) -> None:
    """Print AI preview text for all played matches.
    
    Args:
        played: Dict of played knockout matches.
        played_groups: Dict of played group matches.
    """
    from src.constants import GROUP_COUNT
    
    has_any = False
    
    # Group matches
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
                print(f"\n{bold(match['team_a'])} vs {bold(match['team_b'])}:")
                print(preview)
    
    # Knockout matches (after group, so they appear after group section)
    if played:
        for mid in sorted(played):
            match = played[mid]
            preview = match.get("ai_preview")
            if preview:
                if not has_any:
                    print(_bold_white("\n─── AI Previews ───"))
                    has_any = True
                print(f"\n{bold(match['team_a'])} vs {bold(match['team_b'])}:")
                print(preview)
    
    if not has_any:
        print(_dim("No AI previews available."))
```

## Runtime State Inventory

> Not a rename/refactor/migration phase. Greenfield integration into existing data flows.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — xG extracted from predictions cache (TTL), not stored permanently. AI preview stored inline on existing played.json / played_groups.json (same files, new optional field). | No migration needed. |
| Live service config | None | — |
| OS-registered state | None | — |
| Secrets/env vars | None | — |
| Build artifacts | None | — |

**Nothing found in category:** All categories verified — no pre-existing state needs modification.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.x |
| Config file | `pytest.ini` (in root) |
| Quick run command | `pytest tests/test_groups.py -x -q` |
| Full suite command | `pytest -x --tb=short -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| V2-23 | `precompute_matchup_lambdas()` accepts `xg_overrides` param — when provided, overrides Elo lambdas | unit | `pytest tests/test_groups.py::TestPrecomputeMatchupLambdas -x -q` | ❌ Wave 0 |
| V2-23 | When `xg_overrides` is None or match_id absent, falls back to Elo-derived lambdas | unit | `pytest tests/test_groups.py::TestPrecomputeMatchupLambdas -x -q` | ❌ Wave 0 |
| V2-23 | xG values flow through full simulation (integration) | integration | `pytest tests/test_group_integration.py -x -q -k "xg"` | ❌ Wave 0 |
| V2-24 | `ai_preview` extracted from raw event and stored inline on entry | unit | `pytest tests/test_fetcher.py -x -q -k "ai_preview"` | ❌ Wave 0 |
| V2-24 | Missing `ai_preview` produces no warning/error | unit | `pytest tests/test_fetcher.py -x -q -k "ai_preview_missing"` | ❌ Wave 0 |
| V2-24 | `--ai-preview` CLI flag accepted and triggers display | unit | `pytest tests/test_main_loop.py -x -q -k "ai_preview"` | ❌ Wave 0 |
| V2-23/V2-24 | Zero regression on existing suite | regression | `pytest -x --tb=short -q` | ✅ |

### Sampling Rate
- **Per task commit:** `pytest tests/test_groups.py -x -q` (xG) + `pytest tests/test_fetcher.py -x -q` (AI preview)
- **Per wave merge:** `pytest -x --tb=short -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_groups.py` — `TestPrecomputeMatchupLambdas` class (3-4 test methods)
- [ ] `tests/test_fetcher.py` — ai_preview extraction tests (2 test methods)
- [ ] `tests/test_output.py` — `print_ai_previews` display test (1 test method)
- [ ] `tests/test_group_integration.py` — xG override integration test (1 test method)
- [ ] `tests/test_main_loop.py` — `--ai-preview` flag test (1 test method)

## Security Domain

> `security_enforcement` is not explicitly disabled — treat as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | BSD_API_KEY already handled by existing validate_api_key() |
| V3 Session Management | No | Stateless — no sessions |
| V4 Access Control | No | No user access control |
| V5 Input Validation | yes | xG values validated as float before use (type check, range check for positivity) |
| V6 Cryptography | No | No encryption needed |

### Known Threat Patterns for project

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| xG value injection/modification | Tampering | Values come from trusted BSD API only, not user input. Already validated via HTTPS. |
| Missing xG causing simulation crash | Denial of Service | Graceful fallback to Elo-derived lambdas per D-04. Null-check before override. |
| AI preview XSS (display in terminal) | Spoofing | CLI display === raw text. No HTML rendering. Terminal escape sequence risk is low but mitigated by printing raw text only. |

## Sources

### Primary (HIGH confidence)
- **Codebase scan** — Verified all integration points by reading source files: `groups.py:181-205`, `catboost.py:106-195`, `fetcher.py:87-170+247-374`, `main.py:530-872`, `output.py:54-526`, `knockout.py:251-319`
- **18-CONTEXT.md** — 15 locked decisions (D-01 through D-15) with exact code locations and signatures
- **18-DISCUSSION-LOG.md** — BSD probe evidence confirming field names, endpoints, model version
- **Existing test patterns** — Verified via `test_enrichment.py`, `test_fetcher.py`, `test_groups.py`, `test_group_integration.py`, `test_output.py`

### Secondary (MEDIUM confidence)
- **.planning/phases/17-enriched-match-context/17-CONTEXT.md** — Phase 17 enrichment pattern reference for AI preview inline storage

### Tertiary (LOW confidence)
- None — all findings verified against live codebase or phase context documents.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `expected_home_goals` values are already in the correct scale for Poisson lambdas (not percentages) | Code Examples / Pitfall 2 | If they ARE percentages (0-100), they'd need dividing by 100 first. BSD probe showed `1.48` which is clearly expected goals, not percentage. |
| A2 | `ai_preview` field exists at top level of events endpoint response | Code Examples | If it's nested differently, extraction code needs adjustment. BSD probe confirmed it at top level. |
| A3 | No changes needed in knockout.py `_simulate_knockout_round()` because GROUP stage simulation is the only point where xG lambdas are used | Don't Hand-Roll | Confirmed by reading knockout.py — `_simulate_knockout_round()` uses `_get_blended_prob()` not Poisson lambdas. Only group stage uses Poisson scoreline simulation. |

**If this table is empty:** Not applicable — see above.

## Open Questions

1. **AI preview display grouping — group vs knockout order?**
   - What we know: CONTEXT.md says "print AI previews for all matches that have them in a single block"
   - What's unclear: Should group match previews and knockout previews be interleaved or separate sections?
   - Recommendation: Print group match previews first (chronological), then knockout matches. Use section headers.

2. **xG override for knockout matches?**
   - What we know: Group stage uses Poisson simulation (72 matches x 50K iterations). Knockout uses `_get_blended_prob()` which is Elo/blender based.
   - What's unclear: Should xG overrides also apply to knockout Poisson simulation?
   - Recommendation: No — knockout doesn't use `precompute_matchup_lambdas()`. xG only affects group stage scoreline distribution. This is correct behavior.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `python` | All code | ✓ | 3.10+ | — |
| `requests` | BSD API calls | ✓ | 2.x | — |
| `pytest` | Tests | ✓ | 7.x | — |
| BSD API key | Live data | ✓ (from env) | — | Tests use mocks/fixtures |

**Missing dependencies with no fallback:** None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new packages needed, all verified against codebase
- Architecture: HIGH - All integration points read and confirmed via source code traversal
- Pitfalls: HIGH - Root causes verified against real BSD API behavior and codebase patterns

**Research date:** 2026-06-19
**Valid until:** 2026-07-03 (BSD API field names may change — stable pattern)
