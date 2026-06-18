# Phase 17: Output Enhancement - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-17
**Phase:** 17-Output-Enhancement
**Areas discussed:** Per-match prediction display, Confidence intervals, --signals flag behavior, Per-signal championship probability source

---

## Per-match prediction display

| Option | Description | Selected |
|--------|-------------|----------|
| Enriched championship table | Add per-signal columns to existing team-level table | |
| Match-level prediction table | NEW section showing upcoming individual matches with per-signal breakdown | |
| Signal contribution section | Decompose champion prob into per-signal contributions for top teams | |
| Both tables | Keep championship as-is + add match-level section | ✓ |

**User's choice:** Both tables — keep championship table unchanged (Section 1), add NEW Upcoming Match Predictions section (Section 2). Only Section 2 gets per-signal breakdown.

| Option | Description | Selected |
|--------|-------------|----------|
| Compact table row per match | Single line per match with all signals inline | |
| Multi-line block per match | 2-3 lines per match with indented breakdown | |
| Condensed range display | Blended prob + signal range, expand with --signals | ✓ |

**User's choice:** Condensed range display. Default: blended prob + signal count + [min-max] range. Full per-signal expansion only with `--signals` flag.

| Option | Description | Selected |
|--------|-------------|----------|
| Blended + range | "0.723 [0.698-0.745]" | |
| Blended + count + range | "0.723 (4 sigs) [0.698-0.745]" | ✓ |
| Blended + direction arrow | "0.723 (+0.011) Elo-driven" | |

**User's choice:** Blended + count + range format: "Argentina vs Nigeria — 0.723 (5 sigs) [0.698-0.745]"

---

## Confidence intervals

| Option | Description | Selected |
|--------|-------------|----------|
| Blended match prob only | Clopper-Pearson CI from MC for match predictions | |
| Both blended + champion | CI on both match-level and championship probs | |
| No CI on match predictions | Signal range as confidence metric instead | ✓ |

**User's choice:** Match predictions: signal range only (no CI). The range captures model disagreement between signals, which is more informative than MC sampling error. Championship probabilities: optional Clopper-Pearson CI from MC trials. "Not CI everywhere. Not range everywhere. Use the uncertainty measure that matches the quantity being displayed."

| Option | Description | Selected |
|--------|-------------|----------|
| Always on | Show CI for top-5 champion probs in main table | |
| Toggleable via --confidence flag | Hidden by default, toggle with CLI flag | ✓ |
| Separate CI section | Optional section below table | |

**User's choice:** `--confidence` flag to add CI to championship table. Default: clean table (no CI). Independent from `--signals`.

---

## --signals flag behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Toggle Section 2 on/off | Without flag: no match section. With flag: show it | |
| Control detail level | Section 2 always shown. Flag controls condensed vs expanded | ✓ |
| Toggle full columns everywhere | Flag expands both match section AND champ table | |

**User's choice:** `--signals` controls detail level of Section 2, not visibility. Section 2 always shown. Default: condensed range. `--signals`: expanded per-signal multi-line block.

| Option | Description | Selected |
|--------|-------------|----------|
| All upcoming matches | All unplayed matches listed | |
| Next round only | Only next scheduled round (R32, then R16, etc.) | ✓ |
| Top-5 most competitive | Closest to 0.50 only | |
| CLI-configurable count | --top-matches N flag | |

**User's choice:** Next round only. Most relevant to user, avoids overwhelming output, fits CLI constraints.

| Option | Description | Selected |
|--------|-------------|----------|
| After championship table | Champ Table → Match Predictions → Delta Summary | ✓ |
| Before championship table | Match Predictions → Champ Table → Delta Summary | |
| At startup only | Near governance dashlet, not on every heartbeat | |

**User's choice:** After championship table. Championship table is primary product output; match predictions provide explanation/context. Natural top-down flow.

---

## Per-signal championship probability source

This area was auto-resolved by the decision that per-signal breakdown applies to match-level predictions (Section 2), not championship odds. Data is already available from signal caches + calibration params. No extra MC runs required.

---

## the agent's Discretion

- Exact per-signal display order in expanded view
- Column width/alignment in expanded per-signal block
- Whether "available signals" count includes or excludes blended
- Threshold for "upcoming" vs "in-progress"
- --confidence CI format ([17.8-18.6] vs ±0.4 vs separate column)
- Empty state text for end of tournament

## Deferred Ideas

- **Terminal layout** — defer until data model locked (how to handle narrow terminals, wrapping, box-drawing vs plain text)
- **Delta presentation** — defer until data model locked (per-signal deltas, per-round deltas)
