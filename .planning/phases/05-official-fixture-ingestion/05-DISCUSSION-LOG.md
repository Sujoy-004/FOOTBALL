# Phase 5: Official Fixture Ingestion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 5-Official Fixture Ingestion
**Areas discussed:** FixtureProvider location, Validation method, BSD viability for future fixtures, Testing strategy

---

## FixtureProvider location

| Option | Description | Selected |
|--------|-------------|----------|
| football_core/ | Shared from day one — Phase 6 imports directly. PROJECT.md removed the artificial restriction. | ✓ |
| competitions/ucl/ | Follows Rule of Two. Phase 6 imports from UCL or extracts later. | |

**User's choice:** `football_core/` for the abstraction interface, `competitions/ucl/` for competition-specific details (BSD endpoint config, league IDs, normalization).
**Notes:** The FixtureProvider abstraction (interface, caching, validation, provider selection) is inherently generic. Only competition-specific mapping belongs in the competition module. Phase 6 needs the abstraction in the shared engine for reuse.

---

## Validation method

| Option | Description | Selected |
|--------|-------------|----------|
| Dataclasses + manual validation | Stdlib only. Zero new deps. Keeps PROJECT.md constraint satisfied. | ✓ |
| Pydantic BaseModel | Rich validation + error messages. New dependency — requires updating constraint. | |

**User's choice:** Dataclasses + manual validation. No new runtime dependencies.
**Notes:** Pydantic can be adopted project-wide later if multiple subsystems justify it. Not worth the dependency for Phase 5 alone.

---

## BSD viability for future fixtures

| Option | Description | Selected |
|--------|-------------|----------|
| Build BSDFixtureProvider as designed | Fetch from BSD, cache, validate. If empty/fails, fall back with warning. | |
| Hybrid: try BSD, check for future dates | After fetching, verify future-dated fixtures exist. If only past results, treat as fallback. | ✓ |
| Start with RepoFixtureProvider only | Skip BSD in this phase. Add when fixture availability confirmed. | |

**User's choice:** Hybrid — try BSD, validate that returned schedule contains future-dated fixtures. Fall back to RepoFixtureProvider with warning explaining the cause.
**Notes:** Preserves the planned architecture. Prevents silent failures when BSD cannot serve future UCL fixtures. The warning should be informative enough for debugging.

---

## Testing strategy

| Option | Description | Selected |
|--------|-------------|----------|
| HTTP mocking for unit + integration | Mock requests.get() for unit tests. BSD_API_KEY for integration. | |
| API key only, documented as requirement | All tests hit real API. Skip if key absent. | |
| Fixture files + conditional integration | Saved BSD JSON responses for unit tests. Conditional live API tests. | ✓ |

**User's choice:** Fixture files (saved BSD JSON snapshots) for deterministic offline unit tests. Conditional integration tests (`pytest.mark.skipif`) when BSD_API_KEY is present.
**Notes:** Industry standard approach. CI runs both. Local developers run full unit suite without API key.

---

## Deferred Ideas

- Multi-season historical fixture ingestion — Phase 10
- Redis-backed cache — not needed at current scale
- WebSocket-based live fixture updates — premature for CLI tool
- Pydantic adoption — reconsider if multiple subsystems need it
