# Phase 17: Enriched Match Context - Context

**Gathered:** 2026-06-19
**Status:** Planned — BSD probe completed, field names confirmed, 3 plans created

<domain>
## Phase Boundary

Expand BSD event field coverage from ~10 fields to 40+ fields — live match statistics (yellow/red cards, shots on target, possession %, corners, fouls, shots off target, substitutions) plus match context data (venue name, referee name, coach names, weather). All enriched fields stored inline in `played.json` / `played_groups.json` within `stats` and `context` groups.

Scope: V2-21 (match event fields) and V2-22 (coach/venue/referee/weather) — Phase 17 implements P0 scope only. P1-P3 fields are deferred.

This phase does NOT create new prediction signals, modify Elo/form/lineup/blender, change governance, add console display, or backfill historical data.

</domain>

<decisions>
## Implementation Decisions

### Enrichment Pipeline
- **D-01:** Enrichment happens **inline** — inside `process_matches()` (knockout, `fetcher.py:86`) and `process_group_matches()` (group, `fetcher.py:236`). The raw BSD event dict (`match` in the loop) is available at entry creation time. Enriched fields are added to the result dict before appending.
- **D-02:** No separate enrichment pass after `save_played()` / `save_played_groups()`. The entry lifecycle is: create entry (with stats/context) -> process Elo -> save atomically. Single canonical save per entry.

### Parser Architecture
- **D-03:** Two extractor functions in a new `src/enrichment.py` module:
  - `extract_stats(raw_event: dict) -> dict | None` — extracts numerical match events from BSD event dict. Returns `None` if BSD returned no stats.
  - `extract_context(raw_event: dict) -> dict | None` — extracts venue, referee, coach info. Returns `None` if BSD returned no context data.
- **D-04:** `process_matches()` and `process_group_matches()` each call both extractors and attach results to the entry as `"stats"` and `"context"` keys respectively.

### Schema & Storage
- **D-05:** Schema design: **Option B** — two optional top-level groups on the entry:
  ```json
  {
    "match_id": "GS_A_01",
    "team_a": "Mexico", "team_b": "South Africa",
    "winner": null, "is_draw": false,
    "home_score": 2, "away_score": 1,
    "completed_at": "2026-06-18T03:00:00+00:00",
    "stats": {
      "yellow_cards_home": 2, "yellow_cards_away": 1,
      "red_cards_home": 0, "red_cards_away": 0,
      "shots_on_target_home": 6, "shots_on_target_away": 3,
      "possession_home": 58, "possession_away": 42
    },
    "context": {
      "venue": "Lusail Stadium",
      "referee": "Szymon Marciniak"
    }
  }
  ```
- **D-06:** Both `stats` and `context` are **optional keys** on the entry. If BSD returned no stats for a match, the entry has no `stats` key. If no context data, no `context` key. Consumers check with `.get("stats", {})`.

### Graceful Degradation
- **D-07:** Within a group, store **only fields BSD actually returned** — no null-filled stubs. If BSD returned possession but not shots, the entry has `possession_home/away` but no `shots_on_target_home/away`. Consumers check each field with `.get("stats", {}).get("shots_on_target_home")`.
- **D-08:** No `available` / `reason` flags inside `stats` or `context` — those are for prediction signals (Phase 13 pattern). Enriched data is post-match reality: absent field simply means API didn't provide it.

### Normalized Naming Convention
- **D-09:** All internal field names use `snake_case` with `_home` / `_away` suffix, matching existing `home_score` / `away_score` convention. Examples: `yellow_cards_home`, `shots_on_target_away`, `possession_home`. Match-level fields (venue, referee) have no suffix.
- **D-10:** BSD field names are NEVER persisted to storage. The mapping layer translates BSD names to internal names. BSD schema changes don't affect stored data.

### BSD Field-Name Change Handling
- **D-11:** A **fallback-chain mapping layer** translates BSD field names to internal names, following the same pattern as `catboost.py`'s field-name fallback chain (Phase 13-02). Each internal field has a priority-ordered list of BSD field names to try:
  ```python
  FIELD_MAP = {
      "yellow_cards_home": ["yellow_cards_home", "home_yellow_cards", "home_team_yellow_cards"],
      "yellow_cards_away": ["yellow_cards_away", "away_yellow_cards", "away_team_yellow_cards"],
      ...
  }
  ```
- **D-12:** First matching BSD field name wins. If none match, the internal field is simply absent — the sparse-fields convention (D-07) handles it.

### P0 Scope (Phase 17 Deliverables)
- **D-13:** Phase 17 implements **6 fields** (Moderate scope):
  - `stats`: `yellow_cards_home/away`, `red_cards_home/away`, `shots_on_target_home/away`, `possession_home/away`
  - `context`: `venue`, `referee`
- **Deferred to future phases:**
  - Phase 17 P1-P2 (shots off target, corners, fouls, coach) — Phase 17 stretch or Phase 20
  - Phase 17 P3 (substitutions, weather) — Phase 20 (coverage seal)

### Display Strategy
- **D-14:** Phase 17 is **storage-only**. No console display of enriched data. Display of match context and stats is deferred to Phase 20 (Output Enhancement & Coverage Seal) or later.

### Live BSD Probe Requirement (Satisfied)
- **D-15:** A live BSD API probe was executed before planning (see RESPONSE.md). `fetch_raw_matches()` retrieved 30 events; a finished match's full field list was dumped confirming exact BSD field names. All field-name fallback chains (D-11) are built from these probe results. Key confirmations: `live_stats.home.yellow_cards` is the exact leaf name, `ball_possession` is the BSD possession field, `venue.name` / `referee.name` / `home_coach.name` are always present on all events.

### Backfill
- **D-16:** Enrich only future matches. No historical backfill of already-played matches. Deferred to Phase 18 when an xG consumer emerges, or indefinitely.

### Governance & Prediction Impact
- **D-17:** Zero governance impact — enriched fields are not prediction signals, so `data_version`, `model_version`, drift detection, and backtesting are unaffected.
- **D-18:** Zero prediction impact — no field is consumed by Elo, form, lineup strength, or blender in Phase 17. Data acquisition only.

### the agent's Discretion
- Exact BSD field-name fallback chains (which alternate names to try and in what order) — determined from live probe
- Whether `extract_stats()` and `extract_context()` share a common field-map pattern or use separate maps
- The exact `src/enrichment.py` function signatures beyond the split described in D-03
- Whether to reuse `_build_alias_lookup()` from fetcher.py or build a standalone lookup for enrichment
- The `shots_on_target` naming variant (`shots_on_target` vs `shots_on_goal` vs `shots_on_target_home/away` — resolved by live probe)

### P1-P2-P3 Scope (deferred to later phases or Phase 20)

| Tier | Fields | Deferred To |
|------|--------|-------------|
| P1 | Coach name | Phase 17 stretch or Phase 20 |
| P1 | Shots off target | Phase 17 stretch or Phase 20 |
| P2 | Corners, Fouls | Phase 20 |
| P3 | Substitutions, Weather | Phase 20 |

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 17 definition: V2-21, V2-22 requirements, success criteria, dependencies on Phase 16.
- `.planning/REQUIREMENTS.md` — V2-21 (live match event fields), V2-22 (coach/venue/referee/weather).
- `.planning/PROJECT.md` — Project constraints: JSON-only storage, console-only output, BSD API as data source.

### Architecture Audit
- `RESPONSE.md` — Full Phase 17 architecture analysis: purpose classification, data model evaluation, storage growth, historical backfill, API strategy.

### Prior Phase Context
- `.planning/phases/16-model-governance/16-CONTEXT.md` — Governance decisions: D-01 through D-25. Establishes that enriched metadata does NOT trigger version increments.
- `.planning/phases/13-signal-ingestion/13-CONTEXT.md` — Signal ingestion patterns: field-name fallback chains, graceful degradation patterns, cache architecture.
- `.planning/phases/14-signal-blending/14-CONTEXT.md` — Blender decisions: D-01 (pure Python), D-03/D-04 (cold-start threshold), D-08 (rolling window).
- `.planning/phases/15-context-signals/15-CONTEXT.md` — Context signal patterns: `available`/`reason` flags, graceful degradation conventions.
- `.planning/phases/10-integration-tests-bsd-verification/10-CONTEXT.md` — BSD API response format, `group_name` routing.

### Codebase Architecture
- `src/fetcher.py:86-159` — `process_matches()` — enrichment integration point for knockout matches.
- `src/fetcher.py:236-353` — `process_group_matches()` — enrichment integration point for group matches.
- `src/state.py:79-200` — `load_played()`, `save_played()`, `load_played_groups()`, `save_played_groups()` — atomic persistence patterns.
- `src/constants.py` — `DATA_DIR` and data file constants.
- `main.py:580-621` — `_run_iteration()` fetch/process/save pipeline.
- `src/predictors/odds.py` — Reference pattern: extracting odds from BSD events response with field-name fallback chains.
- `src/predictors/catboost.py` — Reference pattern: field-name fallback chain for BSD API response variations.

### Prior Research
- `.planning/phases/13-signal-ingestion/13-RESEARCH.md` — BSD API response format research, odds fields embedded in events, field-name variations.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/fetcher.py:fetch_raw_matches()` — Returns raw BSD event dicts. Already paginates, filters by league_id=27, handles auth. Enrichment reads from the same `match` dict in the processing loop.
- `src/fetcher.py:_build_alias_lookup()` — Team name normalization pattern. Enrichment may need its own field-name mapping layer (different domain).
- `src/predictors/odds.py:extract_event_odds()` or `fetch_and_cache_odds()` — Existing pattern for extracting BSD fields from raw events. Uses `raw` list directly. Phase 17 follows the same "zero extra API calls" approach.
- `src/state.py:_atomic_write_json()` — Atomic write primitive used by all persistence. `save_played()` and `save_played_groups()` both use it — enrichment adds keys to the same write, no new persistence surface.

### Established Patterns
- **Field-name fallback chain** (catboost.py, odds.py): Priority-ordered list of BSD field names → internal name. First match wins.
- **Atomic JSON write** (state.py: tempfile + os.rename): All state persistence follows this pattern. Phase 17 adds keys to existing entries — same pattern, no new save function needed.
- **Graceful degradation** (signal modules): Each signal has `available` / `reason` / `probability` fields. Phase 17's enriched data uses NO `available` flags (D-08) — simpler contract.
- **`_run_iteration()` flow** (main.py:580-750): Fetch → process knockout → process group → signal refresh → calibrate → simulate → print. Enrichment happens inside "process" steps — no new flow step.

### Integration Points
- `src/fetcher.py:148-157` — `process_matches()` result dict construction. Phase 17 adds `"stats"` and `"context"` keys before appending.
- `src/fetcher.py:342-351` — `process_group_matches()` result dict construction. Same pattern.
- `src/fetcher.py:86-159` — Top of `process_matches()`: raw BSD `match` dict is available as the loop variable. `extract_stats(match)` and `extract_context(match)` called here.
- `main.py:580-621` — No new enrichment orchestration needed — enrichment is transparent to the caller.

</code_context>

<specifics>
## Specific Ideas

- "Phase 17 is a data acquisition phase only." No field feeds a prediction model in this phase.
- "BSD schema should never leak into storage." The fallback-chain mapping layer is the boundary.
- The live BSD probe was mandatory because we had zero cached raw BSD event responses — only processed caches (odds_cache, catboost_cache) existed. Field names are now confirmed (see RESPONSE.md).
- The catboost field-name fallback chain pattern is the direct precedent: `home_probability → home_win → probability_home` style fallbacks for each internal field.
- `extract_stats()` returning `None` vs `{}` vs partial dict: returns `None` if BSD returned no stats at all; returns partial dict if some stats present; never returns empty `{}`.

</specifics>

<deferred>
## Deferred Ideas

### P1-P3 Fields
| Tier | Fields | Deferred To |
|------|--------|-------------|
| P1 | Coach name (available from events endpoint — `home_coach.name` / `away_coach.name`, always present, zero extra API calls) | Phase 17 stretch or Phase 20 |
| P1 | Shots off target, Corners, Fouls | Phase 20 coverage seal |
| P3 | Substitutions, Weather | Phase 20 |

### Display of Enriched Data
- Console display of match context and stats. Deferred to Phase 20 (Output Enhancement & Coverage Seal).

### Historical Backfill
- Enriching already-played matches with stats/context from historical API data. Deferred to Phase 18 when/if a consumer (xG model) emerges.

### Coverage Auditor
- Phase 20 V2-30 requires 85% BSD API field coverage. The `stats` + `context` schema structure was designed specifically to make this auditor easy: count fields populated within each group vs total possible fields. But the auditor itself is Phase 20 scope.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 17-Enriched-Match-Context*
*Context gathered: 2026-06-19*
