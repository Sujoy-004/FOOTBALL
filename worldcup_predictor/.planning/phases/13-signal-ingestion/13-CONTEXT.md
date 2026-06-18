# Phase 13: Signal Ingestion — Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Add two new independent prediction signals — market odds (vig-removed) and CatBoost ML predictions — to complement Elo-based predictions. Both signals feed into the Phase 12b evaluation framework for per-signal Brier scoring, then into Phase 14 blending.

Scope: V2-05 (market odds → vig-removed probabilities) and V2-06 (CatBoost predictions for every match).

This phase does NOT blend, calibrate, or visualize signals — only ingest, cache, and measure per-signal Brier. Phase 13 owns the data model, cache architecture, and graceful degradation policy that Phase 14+ consume.

</domain>

<decisions>
## Implementation Decisions

### Signal Data Model (prediction_history.json)
- **D-01:** One record per match. Compound entry with nested signals dict:
  ```json
  {
    "match_id": "...",
    "actual": 1,
    "signals": {
      "elo": {"probability": 0.63, "version": "v1", "timestamp": "...", "available": true},
      "market_odds": {"probability": 0.71, "version": "v1", "timestamp": "...", "available": true},
      "catboost": {"probability": 0.68, "version": "v1", "timestamp": "...", "available": true},
      "blended": {"probability": 0.67, "version": "v1", "timestamp": "...", "available": true}
    }
  }
  ```
- **D-02:** Match is the natural unit of evaluation. Compound entry prevents synchronization issues from multiple rows per match.
- **D-03:** Phase 14 adds `blended` to the existing record. Phase 16 computes per-signal Brier by iterating signal keys. Phase 17 displays signal breakdown directly.

### Caching Strategy
- **D-04:** Separate cache files per signal — `data/odds_cache.json` and `data/catboost_cache.json`. Follows existing architecture pattern (played.json vs played_groups.json, eloratings_cache.json).
- **D-05:** Each cache owns its own schema, TTL, and refresh policy:
  ```json
  {
    "fetched_at": "...",
    "expires_at": "...",
    "matches": {...}
  }
  ```
- **D-06:** TTL values NOT decided yet — deferred until endpoint research reveals update frequency.

### Graceful Degradation
- **D-07:** Signal marked `available: false` with a `reason` field (e.g., `"cache_expired"`, `"api_error"`).
- **D-08:** Phase 14 blender skips unavailable signals and re-normalizes remaining weights.
- **D-09:** No per-match console warnings. One aggregated warning per poll cycle:
  ```
  ⚠ Market odds unavailable for 3 matches
  ⚠ CatBoost unavailable for 1 match
  ```
- **D-10:** No UI signal indicators in Phase 13 — that is a Phase 17 (Output Enhancement) decision.

### Evaluation Integration
- **D-11:** `evaluate_all_matches(signal_name=None)` accepts an optional `signal_name` parameter:
  - `signal_name=None` — all available signals
  - `signal_name="elo"` — Elo only
  - `signal_name="market_odds"` — market odds only
  - `signal_name="catboost"` — CatBoost only
  - `signal_name="blended"` — blended only
  First-class signal filtering prevents awkward evaluation code in Phase 14 where per-signal Brier is required for blender weight computation.
- **D-12:** `compare_baselines()` works per-signal — compare elo-only vs odds vs catboost at the same n_matches.

### Signal Probability Format
- **D-13:** Signal probabilities stored as canonical probabilities, not raw provider outputs. Example:
  ```json
  {
    "market_odds": {
      "probability": 0.54,
      "version": "v1",
      "timestamp": "...",
      "available": true
    }
  }
  ```
  Evaluation consumes probabilities. Blending consumes probabilities. Raw odds/features can be stored separately inside cache files if needed for debugging.

### Research Needed (deferred to gsd-phase-researcher)
- **R-01:** CatBoost endpoint — URL, response schema, auth requirements, update frequency, query parameters (match_id? team pair? date range?)
- **R-02:** Market odds source — The Odds API vs BSD-provided odds vs other. Free tier limits, coverage for World Cup 2026 matches, response format, vig-removal compatibility.

### Claude's Discretion
- Cache TTL values (after endpoint research reveals update frequency)
- Vig removal implementation details (basic normalization vs Shin's method)
- File naming convention for signal modules (src/predictors/odds.py, src/predictors/catboost.py or similar)
- Whether odds and CatBoost fetching lives in a new `src/predictors/` package or in existing modules

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 13 definition: V2-05 and V2-06 requirements, success criteria, dependencies on Phase 12b.
- `.planning/REQUIREMENTS.md` — V2-05 (market odds → vig-removed probabilities), V2-06 (CatBoost predictions).

### Prior Phase Context
- `.planning/phases/12b-evaluation-infrastructure/12b-CONTEXT.md` — Phase 12b decisions: prediction history format, evaluation pipeline, compare_baselines interface. Phase 13 extends these.
- `.planning/phases/12-draw-handling-elo-math/12-CONTEXT.md` — D-18 (baseline recording), D-15 (historical replay pattern).
- `.planning/phases/11-data-integrity-elo-foundation/11-CONTEXT.md` — D-09 (eloratings.net as sole Elo source of truth), caching patterns (D-14 through D-17), graceful degradation philosophy (D-22: never block).

### Codebase Architecture
- `.planning/codebase/INTEGRATIONS.md` — Existing BSD integration patterns, caching patterns, API key handling.
- `.planning/codebase/ARCHITECTURE.md` — System architecture showing data flow and module boundaries. Phase 13 adds two parallel data sources feeding into the existing pipeline.
- `.planning/codebase/STACK.md` — Technology stack: Python stdlib, requests, JSON persistence.

### External Sources (for reference, not checked in)
- `https://the-odds-api.com/` — Potential market odds provider. Free tier: 500 requests/month.
- `https://sports.bzzoiro.com/api/` — Existing BSD API base URL. CatBoost endpoint TBD.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/evaluation.py` — `evaluate_all_matches()`, `compare_baselines()`, `brier_score()`, `log_loss()`. Phase 13 extends these to handle multi-signal predictions.
- `src/state.py` — `load_eval_baseline_report()`, `save_eval_baseline_report()`, atomic write pattern, `_atomic_write_json()` helper. Reuse for cache persistence.
- `src/fetcher.py` — HTTP fetch with retry/backoff pattern, API key header pattern. Both new signals follow this pattern.
- `src/constants.py` — Centralized constant definitions. Add signal URLs, TTLs, cache filenames here.

### Established Patterns
- **Separate data files per domain** — played.json, played_groups.json, eloratings_cache.json, elo_update_log.json. Phase 13 adds odds_cache.json and catboost_cache.json.
- **Atomic JSON writes** — write to temp, rename. All new cache files use this.
- **Graceful degradation** — Phase 11 D-22 established "never block the prediction loop" as a principle.
- **API key via environment variable** — `BSD_API_KEY` pattern. Odds API key follows same pattern (`ODDS_API_KEY`).

### Integration Points
- `main.py` startup sequence — new signals fetched during startup and cached. _run_iteration refreshes based on TTL.
- `main.py:_record_eval_baseline()` — extended to compute per-signal Brier from cached signal data.
- `src/evaluation.py:evaluate_all_matches()` — extended to read multi-signal prediction_history entries and report per-signal metrics.

</code_context>

<specifics>
## Specific Ideas

- The compound signal entry model (D-01 through D-03) is the foundational decision for this phase — it determines how all downstream phases (14–18) access signal-level data.
- "Separate cache files per signal" (D-04) was chosen over unified cache because different refresh behaviors, schemas, and the trajectory toward adding more signals (form, lineup in Phase 15).
- Graceful degradation approach (D-07 through D-10) follows Phase 11's principle: never block the prediction loop, always degrade gracefully with clear logging.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 13-Signal-Ingestion*
*Context gathered: 2026-06-15*
