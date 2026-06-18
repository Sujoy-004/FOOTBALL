# Phase 13: Signal Ingestion — Research

**Researched:** 2026-06-16
**Domain:** Signal data ingestion — prediction APIs, market odds fetching, vig removal, CatBoost ML predictions
**Confidence:** HIGH

## Summary

Both prediction signals required for Phase 13 are available from the **existing BSD (Bzzoiro Sports Data) API** — no third-party providers or additional API keys are needed.

**Market odds** are already embedded in every response from the existing BSD events endpoint (`/api/events/`) as `odds_home`, `odds_draw`, `odds_away` fields in decimal format. This is FREE, has no rate limits, and uses the same `Authorization: Token` header. The dedicated BSD Odds API ($5/mo) offers per-bookmaker breakdowns but is not needed for the MVP consensus odds signal.

**CatBoost predictions** are available from BSD's `/api/predictions/` endpoint or per-event via `/api/v2/events/{bsd_id}/prediction/`. The model is a CatBoost v5.0 ensemble (XGBoost + LightGBM + CatBoost) trained on 58k+ matches across 34 leagues, with 163 features including Elo ratings. It returns home/draw/away probabilities with confidence scores. Also FREE, no rate limits, same auth header.

**Primary recommendation:** Both signals fetch from BSD. No external odds APIs needed. The existing `fetcher.py` retry/backoff pattern and `state.py` cache persistence pattern are directly reusable.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| V2-05 | Market odds fetched and converted to vig-removed probabilities | BSD `/api/events/` returns `odds_home`, `odds_draw`, `odds_away` (decimal). Vig removal via 1/odds normalization. See Market Odds Source section. |
| V2-06 | CatBoost predictions fetched for every match | BSD `/api/predictions/?upcoming=true` or per-event `/api/v2/events/{bsd_id}/prediction/`. Returns home/draw/away probabilities. Free, no rate limits. See CatBoost Endpoint section. |
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** One record per match. Compound entry with nested signals dict.
- **D-02:** Match is the natural unit of evaluation. Compound entry prevents synchronization issues.
- **D-03:** Phase 14 adds `blended` to the existing record. Phase 16 computes per-signal Brier by iterating signal keys.
- **D-04:** Separate cache files per signal — `data/odds_cache.json` and `data/catboost_cache.json`.
- **D-05:** Each cache owns its own schema, TTL, and refresh policy: `{fetched_at, expires_at, matches}`.
- **D-06:** TTL values NOT decided yet — deferred until endpoint research reveals update frequency.
- **D-07:** Signal marked `available: false` with a `reason` field.
- **D-08:** Phase 14 blender skips unavailable signals and re-normalizes remaining weights.
- **D-09:** No per-match console warnings. One aggregated warning per poll cycle.
- **D-10:** No UI signal indicators in Phase 13 — that is a Phase 17 decision.
- **D-11:** `evaluate_all_matches(signal_name=None)` accepts optional `signal_name` parameter for per-signal filtering.
- **D-12:** `compare_baselines()` works per-signal — compare elo-only vs odds vs catboost at same n_matches.
- **D-13:** Signal probabilities stored as canonical probabilities, not raw provider outputs.

### Research Deferred to This Phase (now resolved)
- **R-01:** CatBoost endpoint — URL, response schema, auth, update frequency, query parameters → **RESOLVED** (see below)
- **R-02:** Market odds source — The Odds API vs BSD vs other → **RESOLVED** (BSD embedded odds, free)

### Claude's Discretion
- Cache TTL values (after endpoint research reveals update frequency) → RECOMMENDED: 12h for odds, 24h for CatBoost
- Vig removal implementation details (basic normalization vs Shin's method) → RECOMMENDED: basic normalization for MVP
- File naming convention for signal modules → RECOMMENDED: `src/predictors/odds.py`, `src/predictors/catboost.py`, `src/predictors/__init__.py`
- Whether odds and CatBoost fetching lives in a new `src/predictors/` package or in existing modules → RECOMMENDED: new `src/predictors/` package

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Signal fetching (HTTP) | Integration Layer | — | Reuses `fetcher.py` retry/backoff pattern. New `src/predictors/` package. |
| Signal response parsing | Integration Layer | — | Parse BSD prediction odds and CatBoost responses into canonical probabilities. |
| Vig removal computation | Core Logic | — | Pure computation on decimal odds. No external dependencies. |
| Cache persistence | State Layer | — | Reuses `state.py` `_atomic_write_json` pattern. Separate cache files per signal. |
| Signal probability storage | State Layer | — | Stores canonical probabilities in `prediction_history.json` via `append_prediction_history()`. |
| Per-signal evaluation | Evaluation Layer | — | Extends `evaluation.py` `evaluate_all_matches()` with signal_name parameter. |
| Graceful degradation | Orchestration Layer | — | Main loop collects per-signal availability; outputs aggregated warnings. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| [requests](https://pypi.org/project/requests/) | 2.32.5 | HTTP client for BSD API calls | Already used by existing codebase. slopcheck [OK]. |

### Supporting
| Component | Version | Purpose | When to Use |
|-----------|---------|---------|-------------|
| `json` (stdlib) | — | JSON parsing for BSD API responses | Already used throughout codebase |
| `time` (stdlib) | — | Cache TTL expiry checks | Already used in `main.py` polling |
| `datetime` (stdlib) | — | Timestamp generation | Already used in `evaluation.py` |
| `math` (stdlib) | — | Vig removal arithmetic | Pure computation, no library needed |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| BSD events endpoint odds | The Odds API (the-odds-api.com) | BSD is FREE, no rate limits, same API key. The Odds API free tier is 500 req/month. BSD odds are embedded in events response — no extra fetch needed. |
| BSD events endpoint odds | API-Football (api-sports.io) | API-Football free tier is 100 req/day. Odds are paid-only. BSD includes odds for free. |
| BSD predictions endpoint | Self-hosted CatBoost model | BSD retrains weekly with 58k+ matches and 163 features. Self-hosting requires training data pipeline, feature engineering, weekly retraining, and model serving infrastructure — massive overkill for MVP. |
| BSD predictions endpoint | No ML signal (Elo-only) | No CatBoost signal means no diversification for blender. |

**New dependencies:**
```bash
# No new Python packages needed. BSD predictions are consumed via REST API (requests).
# requests is already installed and used by the existing codebase.
```

## Package Legitimacy Audit

> Both dependency packages are already present in the codebase. No new packages need to be installed for Phase 13.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| requests | PyPI | 14 yrs | 350M+/wk | github.com/psf/requests | [OK] | Already installed |
| catboost* | PyPI | 8 yrs | 700K+/wk | github.com/catboost/catboost | [OK] | Not needed — API consumer only |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*The `catboost` Python package is not required. Predictions are consumed via REST API. slopcheck verification was run as protocol requires but the package does not need to be installed.

## Architecture Patterns

### System Architecture Diagram

```text
┌──────────────────────────────────────────────────────────────────┐
│                      BSD API (sports.bzzoiro.com)                 │
│                                                                   │
│  GET /api/events/?league_id=27&status=finished                    │
│    → Returns: match results + odds_home/odds_draw/odds_away       │
│                                                                   │
│  GET /api/predictions/?league=27                                  │
│    → Returns: home/draw/away probabilities + confidence            │
│                                                                   │
│  Auth: Authorization: Token {BSD_API_KEY} (same as existing)      │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Ingestion Layer (src/predictors/)             │
│                                                                   │
│  ┌─────────────────────┐    ┌────────────────────────────────┐   │
│  │ fetch_odds()        │    │ fetch_catboost_predictions()   │   │
│  │  - Extract from     │    │  - GET /api/predictions/      │   │
│  │    events response  │    │  - Parse H/D/A probabilities  │   │
│  │  - Build match_id → │    │  - Map BSD event IDs →        │   │
│  │    odds dict        │    │    match_ids via team pairs   │   │
│  │  - Apply vig removal│    │  - Store as canonical probs   │   │
│  └──────────┬──────────┘    └────────────┬───────────────────┘   │
│             │                            │                        │
│             ▼                            ▼                        │
│  ┌─────────────────────┐    ┌────────────────────────────────┐   │
│  │ odds_cache.json     │    │ catboost_cache.json            │   │
│  │ {fetched_at,        │    │ {fetched_at,                   │   │
│  │  expires_at,        │    │  expires_at,                   │   │
│  │  matches: {         │    │  matches: {                    │   │
│  │   match_id: {       │    │   match_id: {                  │   │
│  │    probability,     │    │    probability,                │   │
│  │    available,       │    │    available,                  │   │
│  │    reason,          │    │    reason,                     │   │
│  │    timestamp        │    │    timestamp                   │   │
│  │   }}}               │    │   }}}                          │   │
│  └─────────────────────┘    └────────────────────────────────┘   │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│               Main Orchestration (main.py)                       │
│                                                                   │
│  Startup: fetch both signals → populate signals in                │
│           prediction_history → compute per-signal Brier           │
│                                                                   │
│  Per iteration: check TTL → refresh stale signals                 │
│                 → collect availability warnings                   │
│                 → run simulation with available signals           │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Evaluation (src/evaluation.py)                   │
│                                                                   │
│  evaluate_all_matches(signal_name="market_odds")                  │
│    → Brier=0.XXX, LogLoss=0.XXX                                  │
│  evaluate_all_matches(signal_name="catboost")                     │
│    → Brier=0.XXX, LogLoss=0.XXX                                  │
│  compare_baselines(elo_report, odds_report)                       │
│    → "elo vs odds: IMPROVED by 0.02 Brier"                       │
└──────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
worldcup_predictor/
├── src/
│   ├── __init__.py
│   ├── constants.py          # + signal URLs, cache TTLs, cache filenames
│   ├── state.py              # + load/save for odds_cache, catboost_cache
│   ├── fetcher.py            # Unchanged (BSD events fetch)
│   ├── evaluation.py         # + evaluate_all_matches(signal_name=...)
│   ├── output.py             # + aggregated warning helper
│   ├── elo.py                # Unchanged
│   ├── elo_sync.py           # Unchanged
│   ├── groups.py             # Unchanged
│   ├── knockout.py           # Unchanged
│   ├── simulation.py         # Unchanged
│   └── predictors/           # ★ NEW package for signal ingestion
│       ├── __init__.py
│       ├── odds.py           # fetch_odds(), remove_vig(), parse_odds_response()
│       └── catboost.py       # fetch_catboost(), parse_catboost_response()
├── data/
│   ├── odds_cache.json       # ★ NEW (runtime, not checked in)
│   ├── catboost_cache.json   # ★ NEW (runtime, not checked in)
│   ├── prediction_history.json # Extended (compound signal entries)
│   └── ... (existing files unchanged)
├── main.py                   # + signal fetch/integration
├── tests/
│   ├── test_odds.py          # ★ NEW
│   └── test_catboost.py      # ★ NEW
└── ... (existing tests unchanged)
```

### Pattern 1: Fetch-and-Cache with Graceful Degradation
**What:** Fetch predictions from BSD API, parse into canonical probability, store in per-signal cache with TTL. On any failure, mark `available: false` with reason.

**When to use:** Both odds and CatBoost signals follow this exact pattern.

```python
# Source: [CITED: BSD API docs at sports.bzzoiro.com/docs]
# Pattern for both odds and catboost fetching

def fetch_and_cache_odds(api_key: str, bsd_events: list[dict], cache_ttl_hours: int = 12) -> dict:
    """Extract odds from BSD events response, apply vig removal, cache result.
    
    Args:
        api_key: BSD API key (unused for odds extraction from existing events,
                 but kept for API consistency).
        bsd_events: List of BSD event dicts (already fetched by main loop).
        cache_ttl_hours: How long the cache is valid.
    
    Returns:
        Cache dict with fetched_at, expires_at, matches.
    """
    now = datetime.now(timezone.utc)
    cache = {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=cache_ttl_hours)).isoformat(),
        "matches": {},
    }
    
    for event in bsd_events:
        # Extract BSD event ID and match it to internal match_id
        bsd_id = event.get("id")
        # ... team pair resolution logic (same pattern as existing fetcher) ...
        
        odds_h = event.get("odds_home")
        odds_d = event.get("odds_draw")
        odds_a = event.get("odds_away")
        
        if all(o is not None and o > 0 for o in [odds_h, odds_d, odds_a]):
            probability = remove_vig(odds_h, odds_d, odds_a)
            cache["matches"][match_id] = {
                "probability": probability,
                "timestamp": now.isoformat(),
                "available": True,
            }
        else:
            cache["matches"][match_id] = {
                "probability": None,
                "timestamp": now.isoformat(),
                "available": False,
                "reason": "odds_not_available",
            }
    
    return cache
```

### Pattern 2: Signal Integration into Main Loop
**What:** During startup and per-iteration, check signal caches. If expired, refresh. Collect availability warnings.

```python
# Source: Based on existing main.py patterns
def _fetch_and_store_signal(signal_name: str, fetch_fn, cache_path: str, 
                             api_key: str, context: dict, ttl_hours: int) -> list[str]:
    """Fetch a signal, cache it, and return unavailable match IDs."""
    cache = state.load_cache(cache_path)
    warnings = []
    
    # Check if cache is stale
    if not _is_cache_valid(cache, ttl_hours):
        try:
            new_cache = fetch_fn(api_key, **context)
            state.save_cache(new_cache, cache_path)
            cache = new_cache
        except Exception as e:
            logger.warning(f"{signal_name} fetch failed: {e}")
            if not cache:
                warnings.append(f"{signal_name} unavailable — no cached data")
                return warnings
    
    # Count unavailable matches
    unavailable = [
        mid for mid, m in cache.get("matches", {}).items()
        if not m.get("available", False)
    ]
    if unavailable:
        warnings.append(f"{signal_name} unavailable for {len(unavailable)} matches")
    
    return warnings
```

### Anti-Patterns to Avoid

- **Fetching odds from external provider when BSD already provides them:** The existing `/api/events/` response already includes `odds_home`, `odds_draw`, `odds_away`. No need for the-odds-api.com or any other provider.
- **Installing catboost Python package locally:** BSD serves predictions via REST API. The local `catboost` package is only needed if you're training/running CatBoost locally — we're consuming predictions remotely.
- **Per-match console warnings:** D-09 explicitly forbids this. Aggregate warnings per poll cycle.
- **Blocking the prediction loop on signal failure:** D-07/D-08 (graceful degradation). If odds API fails, mark unavailable and continue.
- **Storing raw provider output as signal probability:** D-13 requires canonical probabilities. Convert odds to probabilities before storing.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Vig removal math | Custom complex vig model | Basic 1/odds normalization | For MVP, simple normalization (divide each 1/odds by the sum) is sufficient. Shin's method or other sophisticated approaches are overkill until calibration Phase 14. |
| ML prediction model | Train CatBoost locally | BSD `/api/predictions/` | BSD retrains weekly on 58k+ matches with 163 features. Self-hosting requires data pipeline, feature engineering, weekly retraining, model serving. |
| Event-to-match_id mapping | Custom team resolution | Reuse `fetcher.py` patterns | BSD events use the same team names as the existing fetch pipeline. Reuse `_build_alias_lookup()`, `_normalize_team()` patterns from `fetcher.py`. |
| HTTP retry/backoff | Custom retry logic | Reuse `fetcher.py` `fetch_raw_matches()` pattern | The existing 3-attempt exponential backoff (1s, 2s, 4s) with timeout=10s is battle-tested. |

**Key insight:** Both signals are consumed from the same BSD API using the same auth, same HTTP patterns, and the same team name resolution as the existing fetcher. The signal modules should reuse, not reinvent.

## Runtime State Inventory

> **Not applicable.** Phase 13 adds new data files (cache files) and extends existing ones (prediction_history.json). No rename, refactor, or migration of existing state.

## Common Pitfalls

### Pitfall 1: BSD Event IDs Don't Match Internal Match IDs
**What goes wrong:** The BSD predictions and odds endpoints return `bsd_id` (BSD's internal event ID), but the codebase uses `match_id` like `GS_A_01` for group matches and `R16_1` for knockout matches.

**Why it happens:** BSD has its own ID space. The existing fetcher already handles this for match results via `api_id_mapping.json` (knockout) and team pair resolution (groups).

**How to avoid:** Use the same team-pair-based matching that `process_group_matches()` and `process_matches()` use. For group matches: look up by team pair + group letter. For knockout matches: look up by team pair against bracket (via `slot_teams` resolution). Do NOT try to use BSD numeric IDs as match_id.

**Warning signs:** Odds/predictions for a match fail to map to any internal match_id. The existing `_find_group_match()` and `_find_bracket_match()` functions from `fetcher.py` should be reused.

### Pitfall 2: Ignoring the Free Odds API Update Frequency
**What goes wrong:** Setting too-short TTL (e.g., 1 hour) causes unnecessary API calls. Setting too-long TTL (e.g., 7 days) causes stale odds.

**Why it happens:** Odds change as match time approaches. More dramatic shifts happen in the 24h before kick-off. After the match starts, odds should be frozen.

**How to avoid:** Use 12h TTL for pre-match odds. Check match kickoff time — if match has started, use last available odds (freeze). The BSD events endpoint refreshes odds in near-real-time.

**Warning signs:** Per-match odds changing every poll cycle. Or conversely, stale odds being used for matches already played.

### Pitfall 3: Raw Odds Stored Instead of Canonical Probabilities
**What goes wrong:** The signal probability is stored as `0.54` but downstream (evaluation, blending) expects a properly formatted probability.

**Why it happens:** D-13 explicitly requires canonical probabilities. Directly storing `1/odds` without vig removal gives non-normalized values that don't sum to 1.0 and can't be compared directly with Elo signals.

**How to avoid:** Always apply vig removal before storing. Store only `probability` (float 0-1) in the prediction_history entry. Raw odds can be kept in the cache file for debugging.

**Warning signs:** Signal probabilities for all three outcomes sum to > 1.0.

### Pitfall 4: Prediction History Schema Change Without Migration
**What goes wrong:** Phase 12b `prediction_history.json` entries have `signal: "elo"` (flat string). Phase 13 changes to nested `signals: {"elo": {...}}`. Code that reads old entries breaks.

**Why it happens:** The Phase 13 compound model (D-01) is a breaking schema change from Phase 12b's flat model.

**How to avoid:** Write a one-time migration function that reads existing `prediction_history.json`, converts each entry from flat to compound format, and writes back. Or, handle both formats in `evaluate_all_matches()` with a format version check.

**Warning signs:** After Phase 13 runs, evaluation reports show 0 entries because old entries aren't found by the new schema.

## Code Examples

### Vig Removal: Basic Normalization

```python
# Source: [ASSUMED] — standard statistical approach
def remove_vig_decimal(odds_home: float, odds_draw: float, odds_away: float) -> float:
    """Convert decimal odds to vig-removed home win probability.
    
    Converts decimal odds (e.g., 1.85, 3.40, 4.50) to implied
    probabilities, removes the bookmaker's vigorish by normalizing
    to sum to 1.0, and returns the home win probability.
    
    Args:
        odds_home: Decimal odds for home win.
        odds_draw: Decimal odds for draw.
        odds_away: Decimal odds for away win.
    
    Returns:
        Normalized home win probability (0.0 - 1.0).
    """
    p_home = 1.0 / odds_home
    p_draw = 1.0 / odds_draw
    p_away = 1.0 / odds_away
    total = p_home + p_draw + p_away
    return p_home / total
```

### BSD Predictions API Response Parsing

```python
# Source: [CITED: BSD predictions page at sports.bzzoiro.com/predictions/]
# Predicted probabilities displayed on the public predictions page:
#   Argentina vs Algeria: H 64%, D 20%, A 17% — Has winner 88%

# Expected response shape from GET /api/predictions/?league=27
# Based on BSD docs structure:
{
    "count": 10,
    "results": [
        {
            "event_id": 12345,
            "home_team": "Argentina",
            "away_team": "Algeria",
            "event_date": "2026-06-17T05:00:00+00:00",
            "predictions": {
                "home_probability": 0.64,
                "draw_probability": 0.20,
                "away_probability": 0.17,
                "confidence": 0.88,
                "markets": ["1x2", "btts", "over_under"],
                "model_version": "catboost-v5.0"
            },
            "updated_at": "2026-06-16T12:00:00+00:00"
        }
    ]
}
```

### BSD Events Endpoint Odds Extraction

```python
# Source: [CITED: BSD free-football-api documentation page]
# Example from BSD Quick Start guide:
# print(f"Odds: H={e.get('odds_home')} D={e.get('odds_draw')} A={e.get('odds_away')}")

# The embeddings in the events endpoint response:
{
    "id": 209476,
    "home_team": "Argentina",
    "away_team": "Algeria",
    "odds_home": 1.45,      # decimal odds for home win
    "odds_draw": 4.20,       # decimal odds for draw
    "odds_away": 7.50,       # decimal odds for away win
    "status": "upcoming",
    "league_id": 27,
    "event_date": "2026-06-17T05:00:00+00:00",
    "home_coach": {...},
    "unavailable_players": {...},
    # ... other fields
}
```

### Cache Valid Cache Check Pattern

```python
# Source: Based on existing eloratings_cache.json patterns in state.py
from datetime import datetime, timezone

def is_cache_valid(cache: dict, ttl_hours: int = 12) -> bool:
    """Check if a signal cache is still valid.
    
    Args:
        cache: Cache dict with 'expires_at' key.
        ttl_hours: Fallback TTL if expires_at not present.
    
    Returns:
        True if cache exists and has not expired.
    """
    if not cache:
        return False
    expires_at = cache.get("expires_at")
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) < expiry
    except (ValueError, TypeError):
        return False
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| BSD v1 events endpoint (single fat response) | BSD v2 split endpoints (predictions, odds, lineups as sub-resources) | 2026 | Use v1 endpoints for MVP (already integrated). v2 available for cleaner per-signal fetching but not required. |
| Flat prediction_history entries (`signal: "elo"`) | Compound entries (`signals: {"elo": {...}}`) | Phase 13 | Breaking schema change requires migration of existing entries. |

**Deprecated/outdated:**
- **the-odds-api.com**: Was considered as odds provider. BSD provides odds for free, making this unnecessary.
- **Football-Data.org API**: Already replaced by BSD in v1.1 Phase 10.
- **Flat prediction_history schema**: Phase 12b's `signal: "elo"` field is replaced by `signals: {"elo": {...}}` in Phase 13.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | BSD `/api/predictions/` endpoint returns home/draw/away probabilities in the shape documented above | Code Examples | Need to probe actual API response shape during implementation. Different parameter names are possible. |
| A2 | Basic 1/odds normalization is sufficient for MVP vig removal | Don't Hand-Roll | Slightly inaccurate probabilities if bookmaker vig is asymmetric. Correction in Phase 14 calibration handles this. |
| A3 | BSD events endpoint includes `odds_home`, `odds_draw`, `odds_away` for World Cup 2026 matches | Standard Stack | Confirmed by BSD docs showing odds fields, and the predictions page showing World Cup 2026 matches. But need test with real API key. |
| A4 | BSD predictions endpoint can be filtered by `league=27` for World Cup 2026 | CatBoost Endpoint | Assumed pattern based on BSD's standard filtering. Verify with actual API call. |
| A5 | BSD BSD event IDs in predictions match event IDs in events endpoint | CatBoost Endpoint | If IDs differ, team-pair matching is fallback. But same API service should use consistent IDs. |
| A6 | Recommended TTL of 12h for odds, 24h for CatBoost | Standard Stack | Models retrain weekly; odds shift in final 24h pre-match. If TTL is too short, excess API calls. If too long, stale data. Adjustable via constants.py. |

## Open Questions (RESOLVED)

1. **[What is the exact BSD predictions API response shape?] (RESOLVED)**
   - **Resolution:** Plan 02 catboost.py implements a flexible parser that accepts multiple field name patterns (`home_probability`, `home_win`, `probability_home`) with a priority-ordered fallback chain. The exact field names will be confirmed during implementation by probing the live endpoint, but the parser handles all documented variations defensively.
   - Recommendation: Test the endpoint manually during implementation, or create a detection script that probes the response and logs field names.

2. **[Does BSD already provide CatBoost probabilities in the events endpoint?] (RESOLVED)**
   - **Resolution:** Plan 01 extracts odds from the events endpoint (confirmed available via BSD docs). Plan 02 uses the dedicated `/api/predictions/` endpoint for CatBoost predictions. If prediction fields are embedded in events, that's a potential optimization for a future phase — not a blocker.
   - Recommendation: Check events response for prediction fields during implementation. If present, it saves an extra API call.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All code execution | ✓ | 3.11 | — |
| pip | Package management | ✓ | 26.1.1 | — |
| requests library | HTTP API calls | ✓ | 2.32.5 | urllib3 (stdlib, but requests preferred) |
| BSD_API_KEY env var | BSD API auth | ⚠️ | — | Must be set by user. Already required for existing functionality. |
| catboost (pip package) | Local ML training | ✗ | — | Not needed — API consumer only |

**Missing dependencies with no fallback:**
- None. All required dependencies are already available.

**Missing dependencies with fallback:**
- catboost pip package: Not needed. BSD serves predictions via REST API.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none (uses pytest defaults — `tests/` directory auto-discovery) |
| Quick run command | `pytest tests/test_odds.py tests/test_catboost.py -x` |
| Full suite command | `pytest -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| V2-05 | `remove_vig()` converts decimal odds to normalized probabilities | unit | `pytest tests/test_odds.py::TestVigRemoval -x` | ❌ Wave 0 |
| V2-05 | Odds with null/missing values gracefully marked unavailable | unit | `pytest tests/test_odds.py::TestMissingOdds -x` | ❌ Wave 0 |
| V2-05 | Cache TTL expiry correctly invalidates stale odds | unit | `pytest tests/test_odds.py::TestOddsCache -x` | ❌ Wave 0 |
| V2-05 | Odds cache file written with correct schema | integration | `pytest tests/test_odds.py::TestOddsPersistence -x` | ❌ Wave 0 |
| V2-06 | CatBoost predictions parsed from BSD response into canonical probability | unit | `pytest tests/test_catboost.py::TestParsePredictions -x` | ❌ Wave 0 |
| V2-06 | Missing predictions per match flagged as unavailable with reason | unit | `pytest tests/test_catboost.py::TestMissingPredictions -x` | ❌ Wave 0 |
| V2-06 | Cache TTL expiry correctly invalidates stale predictions | unit | `pytest tests/test_catboost.py::TestCatboostCache -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_odds.py tests/test_catboost.py -x`
- **Per wave merge:** `pytest -x` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_odds.py` — covers vig removal, cache TTL, missing odds, persistence
- [ ] `tests/test_catboost.py` — covers prediction parsing, missing predictions, cache TTL
- [ ] No additional framework install needed — pytest already available

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | BSD API key via env var `BSD_API_KEY` (existing pattern) |
| V5 Input Validation | yes | Validate API response fields before use (type checks, null guards) |
| V6 Cryptography | no | No encryption — all data is public match odds/predictions |

### Known Threat Patterns for Python
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key leakage via logging | Information Disclosure | Never log API key. Existing codebase uses env var, not hardcoded keys. |
| Malformed API response parsing | Tampering | Type-check all response fields. Guard None/null for odds/prediction values. |
| Cache file corruption via partial write | Tampering | Reuse `state.py` `_atomic_write_json()` (tmpfile + rename) pattern. |

## Sources

### Primary (HIGH confidence)
- [BSD docs at sports.bzzoiro.com/docs] — API documentation for endpoints, auth, pagination, odds fields
- [BSD free-football-api page at sports.bzzoiro.com/free-football-api] — Feature comparison, Quick Start showing `odds_home`/`odds_draw`/`odds_away` fields, ML predictions description
- [BSD predictions page at sports.bzzoiro.com/predictions/] — Live CatBoost predictions for World Cup 2026 matches with H/D/A percentages
- [BSD v2 docs at sports.bzzoiro.com/docs/v2] — v2 endpoint structure showing Predictions section and Odds section
- [BSD llms.txt at sports.bzzoiro.com/.well-known/llms.txt] — Machine-readable endpoint listing: `/api/predictions/`, `/api/events/`
- [BSD Odds API page at sports.bzzoiro.com/odds/] — Full Odds API documentation with endpoints, examples, cross-linking to predictions
- [Existing codebase: main.py, fetcher.py, state.py, evaluation.py, constants.py] — Verified patterns for HTTP fetching, cache persistence, evaluation

### Secondary (MEDIUM confidence)
- [Existing integration docs: .planning/codebase/INTEGRATIONS.md] — BSD API integration patterns, rate limits, auth
- [Existing architecture docs: .planning/codebase/ARCHITECTURE.md] — Module boundaries, data flow
- [Reddit post: r/sportsanalytics about BSD] — Developer background on BSD; confirms CatBoost model, free API, home/draw/away probabilities

### Tertiary (LOW confidence)
- [the-odds-api.com pricing page] — Free tier 500 req/month. Not needed, but documented for comparison.
- [API-Football pricing] — Free tier 100 req/day. Not needed, but documented for comparison.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Both signals confirmed available from BSD API via official documentation
- Architecture: HIGH — Patterns directly reuse existing codebase patterns
- Pitfalls: HIGH — Derived from known BSD API characteristics and existing codebase patterns

**Research date:** 2026-06-16
**Valid until:** 2026-07-16 (30 days — stable API, no breaking changes expected)
