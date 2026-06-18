# Phase 11: Data Integrity & Elo Foundation — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 11-Data Integrity & Elo Foundation
**Areas discussed:** Sync Interval, HTML Parsing Strategy, Dynamic Elo Interaction, Caching & Fallback, Startup Validation

---

## Sync Interval

| Option | Description | Selected |
|--------|-------------|----------|
| Every poll cycle (60s) | Freshest data but more HTTP traffic + scraping reliability risk | |
| Every N polls (e.g., 10 min) | Balance freshness vs traffic | |
| Startup + daily | Startup sync, then once every 24h; never every poll cycle | ✅ |

**User's choice:** Startup sync → once every 24 hours → never every poll cycle. Catch up immediately if last sync > 36h.
**Notes:** eloratings.net updates are small per-match. Daily sync is purely a sanity check — real-time updates come from BSD dynamic Elo. Agreed with refinement for catch-up on wake from sleep.

---

## HTML Parsing Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Regex/BeautifulSoup on live table | Parse eloratings.net directly | |
| Structured mirror | Use international-football.net as alternative data source | |
| Separate fetch from parse | Network I/O separated from pure parsing; test fixtures for offline testing | ✅ |

**User's choice:** Separate fetch from parse. Add parser test fixtures. Parsing must be testable without network access.
**Notes:** stdlib `html.parser` is sufficient (avoids adding a dependency). Schema validation step after parsing catches structural changes. Save HTML snapshot as test fixture.

---

## Dynamic Elo Interaction

| Option | Description | Selected |
|--------|-------------|----------|
| Full replacement | Auto-sync overwrites everything; dynamic updates disabled | |
| Hybrid with threshold | Dynamic updates apply; daily sync corrects if drift > N pts | ✅ |
| Disable dynamic, full sync | Remove BSD-triggered Elo updates entirely | |

**User's choice:** Dynamic Elo remains primary. Auto-sync only seeds/corrects. Do NOT overwrite live tournament Elo every sync.
**Notes:** Graduated thresholds confirmed: < 10 pt drift → ignore (expected noise from different formulae); 10–30 pt drift → blend 50% toward source; > 30 pt drift → overwrite and flag. Hard overwrite would create audit noise. Different Elo systems ≠ bug.

---

## Caching & Fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Last-known-good cache | Use cached values when source unreachable | ✅ |
| Skip and warn | Continue operation without updating | ✅ |
| Fall back to dynamic-only | Use only BSD-driven Elo updates | ✅ |

**User's choice:** Last-known-good cache. Continue operation if source unavailable. Warn after 7 days stale. Never block prediction because a website is down.
**Notes:** Refined to graduated staleness: 24h green, 48h LOG only, 72h ⚠ yellow, 7 days 🚨 red (still no block). Retry 3x with exponential backoff before falling back.

---

## Startup Validation

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-sync on startup | Fetch fresh Elo before first simulation | ✅ |
| Warn and continue | If sync fails, use cache and warn | ✅ |
| Block if no cache | Only block on first-ever run with no cache | ✅ |

**User's choice:** Auto-sync on startup. If sync fails, warn and continue using cache. Block only if no cache exists and no successful sync has ever occurred.
**Notes:** Partial sync rule added — apply what you can for 40/48 teams, warn about unmapped, continue. Never block the main prediction loop.

---

## the agent's Discretion

- Parser implementation details (regex patterns, HTML element selection)
- Test fixture format (full HTML snapshot vs simplified table)

## Deferred Ideas

None — discussion stayed within phase scope.
