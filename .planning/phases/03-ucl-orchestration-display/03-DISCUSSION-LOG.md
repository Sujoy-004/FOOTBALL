# Phase 3: UCL Simulation Orchestration + Display — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-28
**Phase:** 3-UCL Simulation Orchestration + Display
**Areas discussed:** CLI scope and flags, Output contents and order, Display formatting style, Data export (JSON/CSV), Display layer abstraction

---

## CLI Scope and Flags

| Option | Description | Selected |
|--------|-------------|----------|
| Single-run (Recommended) | Run simulation once with given params, print results, exit | ✓ |
| Interactive/watch mode | Keep running, periodically refresh probabilities | |

**User's choice:** Single-run (Recommended)
**Notes:** No polling loop needed — UCL has no live matches to react to.

| Option | Description | Selected |
|--------|-------------|----------|
| `--iterations / -n` | Number of MC iterations (default 10000) | ✓ |
| `--seed / -s` | Random seed for reproducibility | ✓ |
| `--output / -o` | Output file path for JSON export | ✓ |
| `--quiet / -q` | Suppress formatted table output | |
| `--color / --no-color` | Explicitly enable/disable ANSI color | |

**User's choice:** `--iterations`, `--seed`, `--output`
**Notes:** After initially selecting underscores, user reconsidered and confirmed hyphens for flag names. Short forms: `-n`, `-s`, `-o`.

---

## Output Contents and Order

| Option | Description | Selected |
|--------|-------------|----------|
| Simulation Summary first | iterations, seed, snapshot date | ✓ |
| League Table second | 36 rows, positions 1-36 | ✓ |
| Playoff Results third | 8 ties, aggregate scores | ✓ |
| Knockout Bracket fourth | R16 → QF → SF → Final | ✓ |
| Odds / Stage Probs last | champion %, final %, SF %, QF % | ✓ |

**User's choice:** Chronological order following tournament progression.
**Notes:** User proposed the exact order and rationale: "output follows tournament chronology, each section builds on the previous one, odds become easier to interpret after seeing the simulated path."

### League Table Columns

| Option | Description | Selected |
|--------|-------------|----------|
| Pos / Team / Pts / GD / GS / Zone | 6 columns, clean default | ✓ |
| Full 9-column tiebreaker | All tiebreaker stats visible | |
| With opponent stats | Full context including strength-of-schedule | |

**User's choice:** Two-tier: default shows 6 columns. Full tiebreaker chain available via `--verbose` (future).

### Bracket Display

| Option | Description | Selected |
|--------|-------------|----------|
| Round-by-round match list | R16 (8), QF (4), SF (2), Final (1) | ✓ |
| ASCII tree diagram | Visual progression structure | |
| Stage probabilities only | Just per-team stage probs | |

**User's choice:** Round-by-round match list as default. ASCII tree is a future enhancement.

### Playoff Display

| Option | Description | Selected |
|--------|-------------|----------|
| Show individual ties | Each of 8 ties with aggregate score | ✓ |
| Summary only | "8 ties resolved" | |

**User's choice:** Show each tie individually. Format: `9th Team A 3-2 agg 24th Team B → Team A advances`. Show ET/Pens only when triggered.

### Odds Display

| Option | Description | Selected |
|--------|-------------|----------|
| Full 36-team table | All teams, sorted by champion prob | ✓ |
| Top N + summary | Top 8 most-likely champions | |
| Full 7-column stage table | All stage probabilities in terminal | |

**User's choice:** All 36 teams. Columns: Rank, Team, Champion %, Final %, SF %, QF %. Full stage probabilities in JSON only.

---

## Display Formatting Style

| Option | Description | Selected |
|--------|-------------|----------|
| Plain text | No ANSI, no Unicode. Like Euro. | |
| ANSI color only | Zone highlighting (green/yellow/red), bold headings | ✓ |
| Full color + Unicode | Like WC output.py | |

**User's choice:** ANSI color only. Auto-detect support, fall back to plain text. No Unicode box-drawing.

| Option | Description | Selected |
|--------|-------------|----------|
| Headers + separators | `==== Section Name ====`, blank lines | ✓ |
| No separators | Minimal, no extra formatting | |
| Collapsible (--verbose) | Headings only by default | |

**User's choice:** Headers with separator lines.

---

## Data Export (JSON/CSV)

| Option | Description | Selected |
|--------|-------------|----------|
| JSON | Full simulation structure, machine-parseable | ✓ |
| CSV | Spreadsheet-friendly, flat format | |
| Both JSON and CSV | Two files | |

**User's choice:** JSON only. CSV can be generated from JSON.

| Option | Description | Selected |
|--------|-------------|----------|
| Both stdout + file | Formatted text to stdout, JSON to --output file | ✓ |
| File only, suppress stdout | Quiet mode behavior | |

**User's choice:** Both destinations simultaneously. Stdout never suppressed by output flag.

---

## Display Layer Abstraction

| Option | Description | Selected |
|--------|-------------|----------|
| Abstract result schema | Display consumes contract, not simulation directly | ✓ |
| Direct coupling, refactor later | Display calls run_monte_carlo() directly | |
| Separate display per phase | Phase 3 and Phase 4 have independent display | |

**User's choice:** Abstract result schema owned by orchestration layer. Phase 4 normalizes BSD data into same contract. Display unchanged between phases.

---

## agent's Discretion

- File/function naming for CLI entry point
- `SimulationResult` dataclass field names and types
- Column widths, ANSI color codes, separator line format
- Whether to use `argparse.FileType` for `--output`
- Table printing implementation (string-format based, no external libs)

## Deferred Ideas

- ASCII tree bracket visualization — future display enhancement
- CSV export — can be generated from JSON
- `--quiet` flag — not needed; stdout can be redirected
- `--verbose` flag for full tiebreaker chain — may add later

---

*Phase: 3-UCL Simulation Orchestration + Display*
*Date: 2026-06-28*
