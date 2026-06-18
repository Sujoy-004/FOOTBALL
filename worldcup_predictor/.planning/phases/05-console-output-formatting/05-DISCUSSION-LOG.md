# Phase 5: Console Output & Formatting — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 5-Console Output & Formatting
**Areas discussed:** Output module design, Delta tracking, Table format & content, ANSI strategy, Autoscroll behavior, Probability change visibility

---

## Output Module Design

| Option | Description | Selected |
|--------|-------------|----------|
| Single display module | One output.py with everything: print_probability_table, print_delta_summary, print_match_alert, print_header, print_heartbeat | ✓ |
| Split into display + formatters | output.py has format functions (build strings), a separate concern handles printing them | |

**User's choice:** Single display module
**Notes:** Keep it simple — one file, all display functions.

---

## Delta Tracking

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory only | Store previous probs dict in main.py iteration state. Lost on restart. | ✓ |
| Persist to JSON file | Write last probabilities to delta_cache.json. Survives restarts. | |

**User's choice:** In-memory only
**Notes:** Session-scoped changes only. No need for cross-session delta tracking.

---

## Table Format & Content

| Option | Description | Selected |
|--------|-------------|----------|
| Keep all 32 teams, full columns | Current format — all teams with QF/SF/FINAL/CHAMPION | |
| Top 5 only with all columns | As specified in UI-01 | |
| Top 5 with deltas + remaining summary | Top 5 with full columns + deltas, one-liner for remaining teams | ✓ |

**User's choice:** Top 5 with deltas, plus a note for remaining teams
**Notes:** Best balance of readability and completeness.

---

## ANSI Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Raw ANSI escape codes + isatty() | Python 3.10+ on Windows 10+ supports ANSI natively. No extra dep. | ✓ |
| Add colorama for Windows safety | Normalizes ANSI on older Windows. Adds dependency. | |

**User's choice:** Raw ANSI escape codes + isatty() check
**Notes:** Python 3.10+ requirement means Windows 10+ ANSI support is guaranteed. colorama deferred.

---

## Autoscroll Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Append — keep history | Each poll cycle adds a new table below the previous one | ✓ |
| Redraw in-place | Clear screen or cursor-up before each update | |

**User's choice:** Append
**Notes:** "Terminal app. Odds evolution is valuable. Users can scroll back. Simpler than cursor management. For a World Cup predictor, seeing 10:00 Argentina 23.4%, 11:00 Argentina 25.1%, 12:00 Argentina 27.8% is useful history. Redrawing loses that."

---

## Probability Change Visibility

| Option | Description | Selected |
|--------|-------------|----------|
| All teams with any change | Show every team's delta, no matter how small | |
| Threshold-based: ±0.1% | Only show meaningful changes | |
| Highlight biggest risers and fallers | Top 3-5 risers and fallers with deltas | ✓ |

**User's choice:** Biggest risers and fallers
**Notes:** "Most informative. Least noisy. Fits a live-monitoring terminal app. Showing 32 tiny deltas every minute becomes unreadable. A summary like 'Biggest Risers: +Argentina +3.2%, +Brazil +1.8%' is much more useful."

---

## the agent's Discretion

- Exact ANSI escape code wrappers (helper functions like `_green()`, `_bold_yellow()`)
- Whether risers/fallers print inline in the table or as a separate block below it
- Exact format of the remaining-teams one-liner
- Heartbeat format and frequency of heartbeat lines
- Whether to include simulation duration in output

## Deferred Ideas

- `--no-color` flag to explicitly disable ANSI — belongs in Phase 6 (CLI Interface)
- `--once` flag for single run — belongs in Phase 6
- `tqdm` progress bar for Monte Carlo simulation — post-MVP (v1.1)
- Log output to file — post-MVP (v1.2)
