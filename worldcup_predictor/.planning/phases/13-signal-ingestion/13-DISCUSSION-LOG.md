# Phase 13: Signal Ingestion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 13-Signal-Ingestion
**Areas discussed:** Signal data model, CatBoost endpoint, Caching strategy, Odds source, Graceful degradation

---

## Signal Data Model & Evaluation Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Option A: 1 entry per signal | 3× entries per match, each with signal="elo"/"odds"/"catboost" | |
| Option B: Compound entry (modified) | 1 entry per match with nested signals dict including version/timestamp/available | ✓ |
| Option C: Per-signal history files | Separate files per signal | |
| Let Claude decide | Agent picks based on codebase patterns | |

**User's choice:** Option B, modified. One record per match. Signals dict with keys: elo, market_odds, catboost, blended. Each signal has probability, version, timestamp, available. Reason: match is natural evaluation unit, Phase 14 adds blended without new row, Phase 16 iterates signal keys, prevents sync issues.

## CatBoost Endpoint Specifics

| Option | Description | Selected |
|--------|-------------|----------|
| Let me check the docs | User looks up BSD API documentation | |
| I know the endpoint | User describes from memory | |
| Research it | Defer to gsd-phase-researcher to investigate | ✓ |

**User's choice:** Research it. Needs investigation of URL, response schema, auth, update frequency.

## Caching Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Unified cache file + separate TTLs | Single file with per-signal expiry | |
| Separate cache files per signal | Independent files, TTLs, schemas | ✓ |
| In-memory only + per-poll fetch | No disk cache | |
| Let Claude decide | Agent picks based on patterns | |

**User's choice:** Separate cache files per signal (odds_cache.json, catboost_cache.json). Consistent with existing architecture. Different schemas and refresh behaviors. Easier debugging and future signal addition. TTL deferred until endpoint research.

## Odds Source Selection

| Option | Description | Selected |
|--------|-------------|----------|
| The Odds API | Popular, free tier, World Cup markets | |
| BSD API | Existing provider, same quota | |
| Research it | Investigate options, pricing, coverage | ✓ |

**User's choice:** Research it. Needs comparison of The Odds API vs BSD vs alternatives.

## Graceful Degradation Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Silent degrade + available=false | Set available=false, no console noise | ✓ |
| Warn once per signal per poll | Aggregated warning per cycle | ✓ |
| Visual indicator in output | Show [?] in probability display | |

**User's choice:** Combine 1 + 2. Signal marked available=false with reason. Phase 14 skips and re-normalizes. One aggregated warning per poll cycle. No per-match warnings. No UI indicators in Phase 13 (deferred to Phase 17).

---

## Claude's Discretion

- Cache TTL values (after endpoint research reveals update frequency)
- Vig removal implementation details (basic normalization vs Shin's method)
- File naming convention for signal modules
- Whether odds and CatBoost fetching lives in src/predictors/ package or existing modules

## Deferred Ideas

- UI signal contribution indicators — Phase 17 (Output Enhancement)
