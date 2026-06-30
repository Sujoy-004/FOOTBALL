# Phase 5: Official Fixture Ingestion — Context

**Gathered:** 2026-06-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the synthetic-only fixture execution path with a `FixtureProvider` abstraction that loads official UEFA fixtures from the BSD API as the primary source, falling back to the repository `fixtures.json` when BSD is unreachable, no API key is provided, or BSD does not return future-dated fixtures. This directly addresses Root Cause #2 (synthetic fixture schedule imbalance) and honors ADR-002.

The phase does NOT change the simulation engine, add new signals, or modify the validation pipeline.
</domain>

<decisions>
## Implementation Decisions

### D-01: FixtureProvider Interface
Introduce a `FixtureProvider` protocol/ABC in `football_core/` with two implementations:
- `BSDFixtureProvider` — fetches from BSD API, validates future-dated fixtures, caches with TTL, validates schema
- `RepoFixtureProvider` — loads from repo JSON, used when BSD is unreachable, API key absent, or BSD returns no future fixtures

### D-02: Return Schema
Both providers return the same `FixtureSchedule` dataclass matching the existing `fixtures.json` schema: `{teams: list[Team], matchdays: list[list[Match]]}`. This guarantees zero changes to the simulation engine.

### D-03: Provider Selection Logic
- If `BSD_API_KEY` is set: try `BSDFixtureProvider` first. On failure (HTTP error, parse error, empty response, no future-dated fixtures), fall back to `RepoFixtureProvider` with a warning log.
- If `BSD_API_KEY` is not set: use `RepoFixtureProvider` silently.

### D-04: CLI Flag for Provider
Add `--fixture-source` flag to `ucl-predict`:
- `auto` (default) — try BSD, fall back to repo
- `repo` — force repo fixtures
- `bsd` — force BSD, fail if unavailable

### D-05: Cache Layer
`BSDFixtureProvider` caches the fetched fixture list as `competitions/ucl/data/cached_fixtures.json` with a 1-hour TTL. Reduces API calls during iterative development.

### D-06: Schema Validation
Both providers validate output against a `FixtureSchedule` dataclass with manual validation methods at load time. Invalid fixtures raise a clear error message rather than failing silently in the simulation engine. Uses stdlib dataclasses — no new runtime dependencies.

### D-07: Remove Synthetic-Only Execution Path
After this phase, the simulation engine must never run without a fixture source. The `RepoFixtureProvider` serves as the guaranteed fallback, so the engine always has fixtures. The term "synthetic-only execution path" refers to the current state where there is no abstraction — fixtures always come from the repo. After this phase, the source is abstracted and always resolved.

### D-08: Provider Location
- `football_core/` — `FixtureProvider` interface, base classes, caching, validation, common loading pipeline
- `competitions/ucl/` — BSD endpoint details (league_id=7), UCL-specific normalization/configuration, provider subclasses with competition knowledge

The abstraction lives in the shared engine because fetching+caching+validating fixtures is inherently competition-agnostic. Only the competition-specific mapping (league IDs, normalization rules) lives in the competition module. Phase 6 (Simulation Modes) and future competitions reuse the interface directly.

### D-09: Validation Method — Dataclasses + Manual Validation
Provider boundary validation uses stdlib dataclasses with explicit `validate()` methods. No Pydantic — avoids adding a new runtime dependency. If Pydantic becomes justified for multiple subsystems in the future, it can be adopted in a refactor.

### D-10: BSD Future Fixture Validation
`BSDFixtureProvider` validates that the returned BSD fixture schedule contains future-dated (unplayed) fixtures. If BSD returns only past results or empty data, the provider logs a warning explaining the fallback reason and delegates to `RepoFixtureProvider`. This prevents silent failures when BSD cannot return the future UCL schedule.

### D-11: Testing Strategy
- **Unit tests:** Saved BSD JSON response fixtures (snapshots) to test parsing, validation, caching, and error handling — fully offline and deterministic.
- **Integration tests:** Conditional on `BSD_API_KEY` being set (`pytest.mark.skipif`). Hit the real BSD API to verify live connectivity and data format.
- **CI:** Runs both. Local devs can run the full unit suite without an API key.

### D-12: Type-Adaptation Boundary at build_simulation_result()
`build_simulation_result()` accepts `FixtureSchedule` from the provider chain, converts it to the legacy dict format (via `dataclasses.asdict()`) immediately before invoking the simulation engine. `competitions/ucl/src/simulation.py` remains unchanged throughout Phase 5. This keeps the phase boundary clean — the engine still sees the `fixtures: dict` it expects, while every path above the adapter speaks `FixtureSchedule`.

### the agent's Discretion
- Cache file path and naming within `competitions/ucl/data/`
- Warning message format for BSD fallback
- Dataclass field names and validation logic within `FixtureSchedule`
- Whether to extract BSD-specific provider config into a constants module or inline it
- Whether the cache uses simple TTL check or also validates fixture count/dates
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — UCLF-01 through UCLF-08 (Phase 5 requirements)
- `.planning/ROADMAP.md` — Phase 5 section, v2 milestone context
- `.planning/PROJECT.md` — Key decisions, constraints (no new deps, football_core rule)

### Prior Phase Context
- `.planning/phases/04-validation-production-readiness/04-CONTEXT.md` — D-08 (validation with synthetic fixtures, now superseded), BSD fetcher integration
- `.planning/phases/03-ucl-orchestration-display/03-CONTEXT.md` — SimulationResult contract, CLI patterns

### Codebase Maps
- `.planning/codebase/ARCHITECTURE.md` — Layered isolation, football_core → competitions dependency direction
- `.planning/codebase/INTEGRATIONS.md` — BSD API details, rate limiting, auth, endpoints, cache patterns
- `.planning/codebase/STACK.md` — Tech stack, no-new-deps constraint, existing runtime requirements

### Existing Code
- `football_core/fetcher.py` — Shared `fetch_raw_matches()` BSD HTTP client (reusable for BSDFixtureProvider)
- `competitions/ucl/src/fetcher.py` — Existing UCL BSD fetcher (Phase 4) — BSD endpoint config, alias resolution
- `competitions/ucl/main.py:252-255` — Current single-path fixture loading from repo JSON
- `competitions/ucl/data/fixtures.json` — Current synthetic fixture file, becomes fallback data source
- `.planning/decisions/ADR-002-synthetic-schedules.md` — synthetic→official gate criteria

### Research & Design
- `.planning/research/RESEARCH.md` — R-01: Official Fixture Ingestion (BSD as primary, repo as fallback, FixtureProvider trait)
- `.planning/RESPONSE.md` — Investigation 1 (fixture source), Root Cause #2 (synthetic schedule imbalance)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `football_core/fetcher.py` — `fetch_raw_matches()` with 3-retry exponential backoff, 10s timeout, shared BSD HTTP client. BSDFixtureProvider can reuse this for underlying HTTP calls.
- `competitions/ucl/src/fetcher.py` — `fetch_ucl_matches()` with UCL-specific alias resolution and event normalization. The BSD event→match mapping logic is reusable.
- `competitions/ucl/data/fixtures.json` — Existing schema `{schedule: {teams: [...], matchdays: [[...]]}}` defines the canonical return shape for both providers.

### Established Patterns
- **DataProvider pattern** — worldcup-oracle uses `SimProvider`/`ReplayProvider`/`LiveProvider` adapters with a shared trait. Phase 5 follows the same adapter pattern.
- **Error handling** — Graceful degradation: fetch failures return empty data, caller decides fallback. Consistent with how `fetcher.py` handles failures.
- **Atomic file writes** — `football_core/state.py:_atomic_write_json()` pattern for crash-safe cache writes.
- **TTL-based caching** — Used elsewhere in the codebase (odds=12h, CatBoost=24h, Elo=24h). `is_cache_valid()` helper in `football_core/state.py`.

### Integration Points
- `competitions/ucl/main.py` — CLI entry point gains `--fixture-source` flag. The fixture loading block (lines 252-255) is replaced with provider resolution.
- `competitions/ucl/src/` — Simulation modules consume `FixtureSchedule` (no schema changes needed).
- `football_core/` — Gains new `provider.py` module (interface + base classes) and `validators.py` (FixtureSchedule schema + validation).

### Creative Options
- The existing BSD HTTP client (`football_core/fetcher.py`) can be used directly or wrapped by BSDFixtureProvider — avoids duplicating retry/auth logic.
- BSD API may serve future fixtures under a different endpoint or with a different response shape — BSDFixtureProvider should handle this gracefully through the future-date validation (D-10).
</code_context>

<specifics>
## Specific Ideas

- BSDFixtureProvider should validate that at least N matchdays contain future-dated fixtures (not just 1). N could be the full UCL league phase (8 matchdays) or whatever the API returns.
- Warning message on fallback should include: "BSD returned {N} events, {M} with future dates — falling back to RepoFixtureProvider" so the developer knows why.
- The `FixtureSchedule` dataclass should be the canonical schema — both providers produce identical types so the engine never sees the source.
</specifics>

<scope_boundary>
## Phase Boundary — What's NOT in this phase

- **Simulation modes** (replay, live conditioning) — Phase 6
- **Any signal changes** — Phase 7
- **BSD fixture data used for validation** — validation already exists (Phase 4); this phase only changes fixture source for simulation
- **Historical fixture ingestion** — only current season (2025/26)
- **Cache invalidation beyond TTL** — simple TTL is sufficient for now
- **Pydantic or any new runtime dependency** — dataclasses + manual validation only
</scope_boundary>

<deferred>
## Deferred Ideas

- Multi-season historical fixture ingestion — needed for Phase 10 (cross-tournament backtest)
- Redis-backed cache — file-based TTL is sufficient at current scale
- WebSocket-based live fixture updates — premature for a CLI tool
- Pydantic adoption as a project-wide dependency — reconsider if multiple subsystems need rich validation
</deferred>

---

*Phase: 5-Official Fixture Ingestion*
*Context gathered: 2026-06-29*
