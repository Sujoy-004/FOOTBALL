# Phase 17: Enriched Match Context - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-19
**Phase:** 17-Enriched-Match-Context
**Areas discussed:** Enrichment pipeline stage, Graceful degradation model, Parser architecture, Storage integration pattern, Display strategy, Live BSD probe, Naming convention, BSD field-name change handling, P0 scope

---

## Prior Architecture Audit (RESPONSE.md)

8 architecture questions answered before discussion:

| Area | Decision |
|------|----------|
| Purpose classification | Data acquisition only — no field is immediate prediction feature |
| Data model | Inline in `played.json`/`played_groups.json` entries (not separate store) |
| Historical backfill | Future matches only |
| API strategy | Most fields in existing events response; coach needs separate endpoint; weather deferred |
| Governance impact | Zero |
| Prediction impact | Zero (Phase 17 is data acquisition only) |
| Storage growth | ~62KB for full tournament — negligible |
| Schema structure | Option B (`stats` + `context` groups) |

---

## Enrichment Pipeline Stage

| Option | Description | Selected |
|--------|-------------|----------|
| Inline during process_matches() | Enriched fields added at entry creation time in fetcher.py | ✓ |
| Separate step after process_matches() | Post-processing step in _run_iteration() | |
| Independent enrichment function | Called separately, not part of entry lifecycle | |

**User's choice:** Inline during `process_matches()` and `process_group_matches()`.
**Notes:** The raw BSD event dict is available in the loop — no reason to defer enrichment.

---

## Graceful Degradation Model

| Option | Description | Selected |
|--------|-------------|----------|
| Optional groups + sparse fields | stats/context keys optional on entry; within group, only fields API returned | ✓ |
| Whole group null | Entire stats or context group is null if any field missing | |
| Available flags per field | Each field has available: true/false like signal caches | |

**User's choice:** Optional groups + sparse fields. Store only fields actually returned. No null-filled stubs.

---

## Parser Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| One big enrich_match() | Single function extracts all 40+ fields | |
| split extract_stats() + extract_context() | Two functions: one for match events, one for venue/ref/coach | ✓ |
| Per-field extractors | Individual functions composed together | |

**User's choice:** Split into `extract_stats()` + `extract_context()` in new `src/enrichment.py` module. No further discussion needed.

---

## Display Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Storage-only | No console display in Phase 17 | ✓ |
| Always show condensed context | Brief context line per match in output | |
| Hide behind --context flag | Enriched data displayed only when flag is set | |

**User's choice:** Storage-only in Phase 17. Display deferred to Phase 20.

---

## Storage Integration Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Enrich at creation time | Enriched fields added in process_matches() before save | ✓ |
| Save then enrich later | save_played() first, then separate enrichment pass | |

**User's choice:** Enrich at creation time. Single canonical save.

---

## Live BSD Probe

| Option | Description | Selected |
|--------|-------------|----------|
| Mandatory before planning | Call live API to confirm actual field names | ✓ |
| Assume field names, adjust during testing | Use common BSD field names, fix in testing | |

**User's choice:** Mandatory before planning. Use actual BSD payloads, not assumed field names.

---

## Naming Convention

| Option | Description | Selected |
|--------|-------------|----------|
| snake_case with _home/_away suffix | Matches existing home_score/away_score. Example: yellow_cards_home | ✓ |
| Nested home/away objects | stats: { home: { yellow_cards }, away: { ... } } | |

**User's choice:** `snake_case` with `_home`/`_away` suffix. Normalized internal names only — do not persist raw BSD names.

---

## BSD Field-Name Change Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Fallback-chain mapping layer | Priority-ordered list of BSD field names per internal field. First match wins. | ✓ |
| Hardcoded single mapping | One BSD field name per internal field | |

**User's choice:** Fallback-chain mapping layer. BSD schema should never leak into storage.

---

## P0 Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal: cards + venue + referee | Yellow cards, red cards, venue, referee. 4 fields. | |
| Moderate: + shots on target + possession | Above + shots_on_target, possession. 6 fields. Foundation for Phase 18 xG. | ✓ |
| Ambitious: all match events | All stat fields. ~16 fields. Max Phase 20 coverage. | |

**User's choice:** Moderate (6 fields): yellow cards, red cards, shots on target, possession, venue, referee.

---

## the agent's Discretion

- Exact BSD field-name fallback chains (order and alternate names) — determined from live probe
- Whether `extract_stats()` and `extract_context()` share a common field-map pattern or use separate maps
- The exact `src/enrichment.py` function signatures beyond the `extract_stats()` / `extract_context()` split
- Whether to reuse `_build_alias_lookup()` from fetcher.py or build a standalone lookup for enrichment
- The `shots_on_target` naming variant (resolved by live probe)

## Deferred Ideas

- P1-P3 fields (coach, shots off target, corners, fouls, subs, weather) — Phase 20
- Console display of enriched data — Phase 20
- Historical backfill — Phase 18 if xG consumer emerges
- Coverage auditor — Phase 20 (V2-30)
