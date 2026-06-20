# Phase 20: Output Enhancement & Coverage Seal — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 20-Output Enhancement & Coverage Seal
**Areas discussed:** Signal breakdown layout, CI display, Probability log, Deferred display work

---

## Signal Breakdown Layout (V2-27)

| Option | Description | Selected |
|--------|-------------|----------|
| Mockup 1: Dedicated table (flag-gated) | 85-col table, all matches, 7 signals + Δ | ✓ (primary) |
| Mockup 2: Compact summary (always visible) | 73-col table, tightest matches only, filtered | Rejected |
| Mockup 3: Detailed match card | 84-col card, 7 signals + provenance + CI + per-signal Δ | ✓ (detail only) |

**User's choice:** Table + optional focus card. Table via `--match-detail`. Card from table row.
**Notes:** V2-27 drives the UI structure. V2-28, V2-29, and deferred display all depend on where/how information is presented.

### Sub-questions

**Q1:** What is the primary display target for V2-27?
**A:** B (Match prediction explanation) — requirement says "per-match". Championship explanation would be a new requirement.

**Q2:** What is the unit of the Δ column?
**A:** C — Blended Δ in table, full per-signal Δ only in focus card. (Table answers "did it move?" Card answers "which signal moved?")

**Q3:** Mockup 2 (tightest matches) as primary?
**A:** Rejected. "Per-match" means all matches, not filtered. Mockup 2 is discoverability, not explanation.

---

## CI Display (V2-28)

| Option | Description | Selected |
|--------|-------------|----------|
| Inline in championship table | `[.198,.270]` alongside champion prob | Rejected |
| Inline in per-match table | CI per cell in signal table | Rejected |
| Focus card only | CI column in Mockup 3 card | ✓ |

**User's choice:** Focus card only.
**Notes:** CI only has marginal utility at championship table level. In per-match table, it doubles each cell from 6→16 chars (~150 cols total). Focus card is the natural home.

---

## Probability Log (V2-29)

| Option | Description | Selected |
|--------|-------------|----------|
| Single rolling file | `probability_log.json` array | ✓ |
| Timestamped files | `data/runs/*_snapshot.json` | Deferred |
| Append-only CSV | `probability_log.csv` | Deferred |

**Cadence:** Every `_run_iteration()`.
**Trend:** ↑/↓/→ vs 5-run rolling window mean in championship table.
**User's choice:** Single rolling JSON, per-iteration snapshots, trend arrow in champion table.

---

## Deferred Display Work (Phase 17/18 fields)

| Option | Description | Selected |
|--------|-------------|----------|
| Focus card only | Coach, fouls, corners, shots_off_target, xG inside card | ✓ |
| Dedicated section (flag-gated) | Separate match-context section | Rejected |

**User's choice:** In focus card only. No separate section. Coach names extractable, stats already in `_STATS_FIELD_MAP`.

---

## V2-30 (previously resolved)

V2-30 was re-scoped before this discussion: changed from "85% BSD API field coverage" to "≥60% BSD API meaningful field coverage with automated auditor script". Value-based classification (Prediction + Display + Operational fields only, exclude No-Value noise). Denominator = 47 meaningful fields.

---

## Deferred Ideas

- Championship probability signal decomposition — new requirement (V2-31+), not Phase 20 scope
- Historical backfill of stats/context/xG — no consumer exists
- Interactive focus card selection (arrow keys) — post-MVP UX enhancement
- Probability log analysis/export — future phase

---

*Discussion log: 2026-06-21*
