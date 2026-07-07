# Phase 12: UCL Live Monitor + WC Batch Research - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-07
**Phase:** 12-UCL Live Monitor + WC Batch Research
**Areas discussed:** State persistence format, Live display style, Historical catch-up scope, Signal cache configuration, Counterfactual parameter scope, Signal breakdown format, Calibrated validation approach

---

## State Persistence Format

| # | Question | Option | Selected |
|---|----------|--------|----------|
| 1 | Single consolidated vs multiple files | Multiple files (WC pattern) | ✓ |
|  |  | Single consolidated file |  |
| 2 | File naming convention | Match WC naming |  |
|  |  | UCL-prefixed names | ✓ |
| 3 | Directory location | competitions/ucl/data/ |  |
|  |  | competitions/ucl/data/live/ | ✓ |
| 4 | Write strategy | Atomic write every cycle | ✓ |
|  |  | Periodic flush every N cycles |  |
|  |  | User configurable interval |  |

**User's choice:** Multiple files, UCL-prefixed, in data/live/, atomic write every cycle.
**Notes:** Consistent with WC's per-file pattern but uses ucl_ prefix to avoid ambiguity.

---

## Live Display Style

| # | Question | Option | Selected |
|---|----------|--------|----------|
| 1 | Display mechanism | Streaming lines per poll |  |
|  |  | In-place re-render | ✓ |
|  |  | Compact heartbeat |  |
| 2 | Windows terminal strategy | Use ANSI cursor-up | ✓ |
|  |  | Adaptive: detect terminal |  |
|  |  | Streaming only, no re-render |  |
| 3 | Display sections | Summary only |  |
|  |  | Full display | ✓ |
|  |  | Match alert mode |  |
| 4 | Delta display format | Per-team delta arrows |  |
|  |  | Compact delta column | ✓ |
|  |  | Delta-only display |  |

**User's choice:** In-place re-render, ANSI cursor-up on Windows (acceptable), full display with compact delta column.
**Notes:** ANSI escape sequences are ASCII-compatible and work on modern Windows Terminal. Phase 11's constraint was about Unicode glyphs, not control sequences.

---

## Historical Catch-Up Scope

| # | Question | Option | Selected |
|---|----------|--------|----------|
| 1 | How far back? | Current season 2025/26 only | ✓ |
|  |  | All available BSD history |  |
| 2 | Process method | Sequential per-match | ✓ |
|  |  | Bulk load |  |
| 3 | Catch-up detection | File-based flag |  |
|  |  | Compare against latest played | ✓ |
| 4 | Error handling | Abort and warn |  |
|  |  | Retry with backoff | ✓ |
|  |  | Skip and continue |  |

**User's choice:** Current season only, sequential per-match processing, compare-against-latest detection, retry with backoff then abort.
**Notes:** User typed "1+2" for error handling — interprets as retry with backoff up to 3 times, then abort with clear error message.

---

## Signal Cache Configuration

| # | Question | Option | Selected |
|---|----------|--------|----------|
| 1 | TTL approach | Hardcoded TTLs like WC |  |
|  |  | Configurable per signal | ✓ |
| 2 | Cache refresh | TTL-only |  |
|  |  | TTL + match event trigger | ✓ |
| 3 | Cache location | Alongside state files | ✓ |
|  |  | Separate cache directory |  |
| 4 | Cache naming | Prefix-based (ucl_odds_cache) | ✓ |
|  |  | Simple names (odds_cache) |  |

**User's choice:** Configurable per-signal TTLs, TTL + match event trigger, alongside state files, prefix-based naming.

---

## Counterfactual Parameter Scope

| # | Question | Option | Selected |
|---|----------|--------|----------|
| 1 | Mutable parameters | Elo only |  |
|  |  | Elo + blend weights |  |
|  |  | Everything | ✓ |
|  |  | Let the agent decide |  |
| 2 | CLI syntax | Namespace syntax (TEAM.elo=) |  |
|  |  | Separate flags per type |  |
|  |  | JSON config file | ✓ |
| 3 | Comparison view | Combined only |  |
|  |  | Per-override breakdown |  |
|  |  | Side-by-side table | ✓ |
| 4 | File export | CLI-only display | ✓ |
|  |  | JSON export alongside CLI |  |

**User's choice:** Everything mutable (Elo, blend weights, xG, calibration), JSON config file syntax, side-by-side table, CLI-only display.

---

## Signal Breakdown Format

| # | Question | Option | Selected |
|---|----------|--------|----------|
| 1 | Format reuse | Reuse UCL format exactly |  |
|  |  | Custom format per signal type |  |
|  |  | Let the agent decide | ✓ |
| 2 | Detail level | Summary mode only |  |
|  |  | Summary + context | ✓ |
| 3 | Breakdown scope | Tournament-level only |  |
|  |  | Per-match breakdown | ✓ |
|  |  | Both via --show-breakdown flag |  |
| 4 | When to show | Always-on (like UCL) | ✓ |
|  |  | On-demand only |  |

**User's choice:** Agent discretion on format (start with UCL template, customize per signal), summary + context detail, per-match breakdown, always-on display.

---

## Calibrated Validation Approach

| # | Question | Option | Selected |
|---|----------|--------|----------|
| 1 | Baseline strategy | Dynamic both-side compute |  |
|  |  | Store baseline on first run |  |
|  |  | Always both + cache | ✓ |
| 2 | Report metrics | Brier + Log Loss only |  |
|  |  | Full metrics suite | ✓ |
| 3 | Display format | Side-by-side table | ✓ |
|  |  | Inline summary |  |
| 4 | Export | CLI-only | ✓ |
|  |  | Append to --report output |  |

**User's choice:** Always both + cache (cache baseline, compute dynamically), full metrics suite, side-by-side table, CLI-only.

---

## the agent's Discretion

- **Signal breakdown display format (D-06):** User chose "Let the agent decide" on whether to reuse UCL format exactly or customize per signal type. Start with UCL's format template, adapt per signal where practical (e.g., Odds shows implied probability, Form shows WDL record). The detail level and always-on behavior are locked.

## Deferred Ideas

None — discussion stayed within phase scope.
