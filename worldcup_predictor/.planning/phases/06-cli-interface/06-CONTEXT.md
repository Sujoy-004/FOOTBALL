# Phase 6: CLI Interface & Polish — Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

User controls the tool via command-line flags with full usage documentation. Add `argparse` to `main.py` to parse `--help`, `--once`, `--no-color`, and `--seed <N>`. Flags integrate with existing loop and output module. No web frontend, no config files, no new external dependencies.

Requirements: CLI-01 (5 success criteria from ROADMAP.md)

**Already decided (carried forward from prior phases):**
- Continuous polling loop with SIGINT handler — `_run_iteration()` returns 3-tuple (Phase 4)
- Output module with `_supports_color()` reading `sys.stdout.isatty()` (Phase 5 D-03)
- `run_simulation(teams, bracket, played, iterations=50000, seed=None)` signature (Phase 2 D-03)
- Raw ANSI codes, no colorama, pure stdlib only (Phase 5 D-01, Project constraint)
- Already decided: polish scope stays limited to the 4 flags — no --version, no shebang, no exit code changes

</domain>

<decisions>
## Implementation Decisions

### --once Behavior
- **D-01:** `--once` runs a straight-line fetch→simulate→print→exit. No polling loop, no hourly refresh check, no sleep. Loads state, fetches API, processes new matches (if any), ALWAYS re-runs 50K simulation, prints probability table with deltas, exits. User expects a fresh snapshot on every `--once` invocation.
- **D-02:** `--once` skips the hourly auto-refresh check entirely — the code path is: startup → fetch → process → simulate → print → exit.

### --seed Scope
- **D-03:** `--seed <N>` applies to EVERY simulation run, not just the first one. Consistent: same seed + same inputs = same outputs. In live mode, new match data changes inputs so outputs still change. Seed only removes Monte Carlo randomness, it does not freeze the system.
- **D-04:** `--seed` seeds ONLY the simulation engine. The value is passed as the `seed` parameter to `run_simulation()`. Global `random.seed()` is NOT called — avoids side effects on other code (backoff, sampling, future features). Narrow, explicit contract.

### --no-color Hookup
- **D-05:** Module-level flag in `output.py`: set `output.NO_COLOR = True` from `main.py` after arg parsing. The `_supports_color()` function checks both `sys.stdout.isatty()` and the `NO_COLOR` flag.
- **D-06:** No env vars (hidden state), no parameter pollution across 9+ output function signatures.

### the agent's Discretion
- `--help` text format — use standard argparse help with description of each flag. Keep concise, one-line per flag.
- Flag naming — `--no-color` (hyphenated) following CLI convention. `argparse` handles dest conversion.
- Whether `--seed` output is shown in console (probably not — silent unless used for debugging).
- Seed default value when not provided: `seed=None` (existing function signature).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Phase Scope
- `.planning/ROADMAP.md` §103-114 — Phase 6 goal and 5 success criteria
- `.planning/REQUIREMENTS.md` §39 — CLI-01 definition

### Phase 4 Context (Loop Structure)
- `.planning/phases/04-main-loop-shutdown/04-CONTEXT.md` — D-01 (SIGINT handler), D-06 (shutdown sequence), D-08 (hourly re-sim)

### Phase 5 Context (Output Module)
- `.planning/phases/05-console-output-formatting/05-CONTEXT.md` — D-05 (ANSI strategy, --no-color flagged for Phase 6), D-03 (table format), current `_supports_color()` implementation

### Codebase Architecture
- `.planning/codebase/ARCHITECTURE.md` — Main entry point, module boundaries, data flow
- `.planning/codebase/CONVENTIONS.md` — CLI flags listed in entry points section, naming conventions

### Existing Source
- `worldcup_predictor/main.py` — Entry point where argparse will be added; loop structure to be modified for --once
- `worldcup_predictor/src/output.py` — `_supports_color()` to be updated with NO_COLOR flag support
- `worldcup_predictor/src/simulation.py` — `run_simulation()` already accepts `seed=None` parameter

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `argparse` — Python stdlib, no new dependency. Handles `--help` generation automatically.
- `run_simulation(..., seed=None)` — Already has the seed parameter ready (Phase 2 D-03).
- `_supports_color()` in `output.py` — Currently checks `sys.stdout.isatty()`; adding `NO_COLOR` flag is a 1-line change.

### Established Patterns
- Pure functional style, no classes for MVP
- All orchestration in `main.py` (Phase 4 D-02)
- Constants in `constants.py` for configurable values
- `print()` statements for all output (no logging module)

### Integration Points
- `main.py:main()` — argparse parsing inserted at the top, before state loading. Flags branch between `--once` path and continuous loop path.
- `main.py:validate_api_key()` — Should still run for `--once` mode (API fetch needs the key).
- `output.py` — `NO_COLOR` flag set after arg parsing, before any output is printed.
- `simulation.py:run_simulation()` — Seed passed on every call when `--seed` is set.

</code_context>

<specifics>
## Specific Ideas

- "`--once` means: Load state, fetch API, process new matches, run simulation, print probabilities, exit. Every time." — direct quote from discussion
- "`--seed` controls simulation reproducibility only. Keep scope narrow and explicit." — no global `random.seed()`
- "Module-level flag for --no-color: minimal code change, explicit, easy to test." — `output.NO_COLOR = True`
- Phase 6 stays limited to the 4 flags — no scope creep into --version, exit codes, or shebang

</specifics>

<deferred>
## Deferred Ideas

- **Polish beyond 4 flags** (--version, shebang, exit codes, debug/verbose) — user elected to keep Phase 6 focused on the originally planned flags. Could be its own cleanup phase or rolled into documentation.
- **Progress bar for simulation** (tqdm) — tracked in Phase 5 deferred, still post-MVP.

</deferred>

---

*Phase: 6-CLI Interface & Polish*
*Context gathered: 2026-06-14*
