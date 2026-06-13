# Phase 5: Console Output & Formatting — Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

System displays beautiful, colored, delta-tracking championship probabilities in the terminal — readable at a glance with rich formatting and plain-text fallback. Creates a dedicated `src/output.py` module that extracts all display logic from `main.py`, implements probability deltas between simulation cycles, and formats tables with ANSI color support.

Requirements: UI-01, UI-02, UI-03

**Already decided (carried forward from prior phases):**
- Elo ratings in memory as `dict[str, dict]` with `{"elo": int}` (Phase 1)
- Bracket structure with match_ids, rounds, team_a/team_b, winner fields (Phase 1)
- Simulation returns `dict[str, dict[str, float]]` with qf/sf/final/champion keys (Phase 2)
- Continuous main loop with `_run_iteration()` in main.py (Phase 4)
- `_print_probability_table` currently lives in main.py — will be extracted to output.py

</domain>

<decisions>
## Implementation Decisions

### Output Module Structure
- **D-01:** Single `src/output.py` module containing all display functions. No splits. Will include:
  - `print_header()` — startup banner
  - `print_probability_table(probs, prev_probs)` — top-5 table with deltas + remaining summary
  - `print_match_alert(match)` — NEW MATCH DETECTED block with score and winner
  - `print_elo_changes(updates)` — Elo change summary per team
  - `print_heartbeat()` — "Polling... no new matches" line
  - `print_delta_summary(risers, fallers)` — biggest risers/fallers block
  - `print_shutdown_banner(probs)` — final probabilities on Ctrl+C
  - Color/style helpers (ANSI wrappers)
- **Function style:** Pure functions that take data and print to stdout. No classes (matching MVP pattern).

### Delta Tracking
- **D-02:** In-memory only. Store previous probabilities dict in main.py's iteration state. Not persisted to JSON. Only tracks changes within a session — which is the primary use case (live monitoring).

### Table Format & Content
- **D-03:** Top 5 teams by championship probability, showing QF/SF/FINAL/CHAMPION columns with deltas. Followed by a one-liner summarizing remaining teams:
  ```
   1. Argentina    0.838 0.531 0.316 0.178  ▲ +0.003
   2. Brazil       0.801 0.491 0.257 0.135  ▼ -0.002
   ...
   5. England      0.728 0.371 0.177 0.083  ▲ +0.001
   ─── 27 other teams — best: Nigeria (0.002)
  ```
- Timestamps on each table block per UI_UX_Design.md §3.4

### Probability Change Visibility
- **D-04:** Show biggest risers and biggest fallers (top 3 each) with their champion% deltas. Not all 32 teams and not threshold-based:
  ```
  Biggest Risers
    ▲ Argentina   +3.2%
    ▲ Brazil      +1.8%
    ▲ Spain       +1.1%

  Biggest Fallers
    ▼ France      -2.9%
    ▼ England     -1.7%
    ▼ Germany     -1.0%
  ```
- This replaces the inline delta column in the table (avoids visual clutter per row).

### ANSI Strategy
- **D-05:** Raw ANSI escape codes. No `colorama` dependency. Color scheme follows `SOTs/UI_UX_Design.md` §4 and `CONVENTIONS.md` color table:
  - Timestamps: dim gray
  - Headers/separators: bold cyan
  - Match alerts: bold yellow
  - Probability increase (▲): green
  - Probability decrease (▼): red
  - Errors: bold red
  - Success/simulation done: bold green
- **Fallback:** Check `sys.stdout.isatty()` before applying colors. If piped or redirected, plain text with symbols only (▲, ▼, ⚠).
- **Explicit override:** `--no-color` flag checks are Phase 6 scope (CLI Interface), not Phase 5.

### Autoscroll Behavior
- **D-06:** Append new tables below previous output (keep scrollback history). Do NOT clear screen or redraw in-place. Each table has a timestamp line above it so the scrollback forms a timeline:
  ```
  [2026-06-13 22:00:00] Probabilities:
   1. Argentina  0.178  ▲
   ...

  [2026-06-13 22:01:00] Probabilities:
   1. Argentina  0.175  ▼
   ...
  ```

### the agent's Discretion
- Exact ANSI escape code wrappers in output.py (helper functions like `_green(text)`, `_bold_yellow(text)`)
- Whether risers/fallers print inline in the table or as a separate block below it
- Exact format of the remaining-teams one-liner
- Heartbeat format and frequency of heartbeat lines
- Whether to include simulation duration in output (e.g., "Re-simulating (50000 runs)... done in 0.8s")

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Output Spec
- `SOTs/UI_UX_Design.md` — Full console output format spec with examples for every block type (startup, heartbeat, match detection, probability updates, errors). Also defines color scheme §4 and interaction patterns §5. **This is the primary reference.**
- `SOTs/PRD.md` §6 — UI-01 (top-5 formatted percentages), UI-02 (probability deltas), UI-03 (colored output with fallback)
- `SOTs/TRD.md` §5.3 — Output specification (probability table format, ANSI codes)
- `SOTs/Backend_Schema.md` §7 — Probability data format (return type of run_simulation)

### Existing Display Code
- `worldcup_predictor/main.py` — `_print_probability_table()` to be extracted, `_run_iteration()` where deltas hook in
- `worldcup_predictor/src/constants.py` — Constants for display (if any needed)

### Design References
- `.planning/codebase/CONVENTIONS.md` — Color table (ANSI codes), module conventions, function design patterns
- `.planning/ROADMAP.md` — Phase 5 goal: "System displays beautiful, colored, delta-tracking championship probabilities"
- `.planning/REQUIREMENTS.md` — UI-01, UI-02, UI-03 definitions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_print_probability_table` in `main.py` (Phase 4) — move to `output.py`, enhance with delta columns and top-5 filtering
- `run_simulation()` result format `dict[str, dict[str, float]]` with qf/sf/final/champion — already provides all data needed for display
- `_print_probability_table` currently prints all 32 teams with QF/SF/FINAL/CHAMPION columns — extraction preserves this for the full-table use case while adding top-5 variant

### Established Patterns
- Pure functional style with typed return values — output.py follows the same pattern
- `print()` statements for all output (no logging module for MVP)
- `_private` naming for helper functions (e.g., `_ansi_wrap(code, text)`)
- ISO 8601 timestamps on all output lines (`time.strftime('%Y-%m-%d %H:%M:%S')`)

### Integration Points
- `main.py` — `_run_iteration()` stores previous `probs` dict, passes it to `output.print_probability_table(probs, prev_probs)`, calls `output.print_delta_summary()` after simulation
- `main.py` — startup calls `output.print_header()`, shutdown calls `output.print_shutdown_banner()`
- `main.py` — match detection code calls `output.print_match_alert(match)` and `output.print_elo_changes(updates)`
- `main.py` — heartbeat line calls `output.print_heartbeat()`

</code_context>

<specifics>
## Specific Ideas

- "Top 5 with deltas + remaining teams one-liner" — keeps output scannable without losing total-picture awareness
- "Biggest risers/fallers" — inspired by stock market movers display; most informative pattern for probability changes
- "Append, don't redraw" — odds evolution timeline in scrollback is valuable; simpler implementation
- "Raw ANSI, no colorama" — Python 3.10+ on Windows 10+ supports ANSI natively; colorama adds unnecessary dependency for MVP
- In-memory deltas — previous probabilities are naturally available in the loop iteration scope

</specifics>

<deferred>
## Deferred Ideas

- **Phase 6 concern:** `--no-color` flag to explicitly disable ANSI (belongs in CLI Interface & Polish phase)
- **Phase 6 concern:** `--once` flag for single run (belongs in CLI Interface & Polish phase)
- **v1.1 concern:** Progress bar during Monte Carlo simulation using `tqdm` (post-MVP per UI_UX_Design.md §11)
- **v1.2 concern:** Log output to file via `--log` flag (post-MVP)

</deferred>

---

*Phase: 5-Console Output & Formatting*
*Context gathered: 2026-06-13*
