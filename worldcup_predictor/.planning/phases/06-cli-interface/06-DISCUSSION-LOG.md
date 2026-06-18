# Phase 6: CLI Interface & Polish — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-14
**Phase:** 6-CLI Interface & Polish
**Areas discussed:** --once behavior, --seed scope, --no-color hookup

---

## --once behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Always sim + print (Recommended) | Load, fetch, always re-run 50K sim, print table with deltas, exit | ✓ |
| Sim only if new matches | If API returns no new matches, just print a brief status and exit | |
| You decide | Let the planner pick | |

**User's choice:** Always sim + print
**Notes:** A user running `python main.py --once` expects a fresh probability snapshot regardless of whether new matches arrived. "No new matches found. Exiting." is not useful. Also decided that --once skips the hourly auto-refresh check entirely — dead code path for single-run mode. --once should be: startup → fetch → process → simulate → print → exit. No polling loop, no waiting, no hourly refresh logic.

---

## --seed scope

| Option | Description | Selected |
|--------|-------------|----------|
| First sim only (Recommended) | Seeds the first/once simulation for reproducibility | |
| Every sim | Every re-simulation is seeded — deterministic outputs for same inputs | ✓ |

**User's choice:** Every sim
**Notes:** If a user provides --seed, they are explicitly asking for reproducibility. First-run-only is surprising behavior. Live mode + --seed is mainly a debugging/testing feature anyway — if new matches arrive, inputs change and outputs still change. The seed only removes Monte Carlo randomness. Also decided that --seed should seed ONLY the simulation engine (passed to `run_simulation()`), not the global `random.seed()`. Avoids side effects on other code.

---

## --no-color hookup

| Option | Description | Selected |
|--------|-------------|----------|
| Module-level flag (Recommended) | Set output.NO_COLOR = True in main.py | ✓ |
| Env variable | Set env var before importing output | |
| Parameter on every call | Pass color=True/False to every output function | |

**User's choice:** Module-level flag
**Notes:** Minimal code change, explicit, easy to test. `_supports_color()` returns `sys.stdout.isatty() and not NO_COLOR`. Avoid env vars (hidden state) and parameter pollution across 9+ function signatures.

---

## the agent's Disposition

- `--help` text format — standard argparse help with one-line-per-flag descriptions
- Flag naming — `--no-color` following CLI convention
- Whether seed value is displayed in console (probably silent)
- Seed default when not provided: `seed=None`

## Deferred Ideas

- **Polish beyond 4 flags** (--version, shebang, exit codes, debug/verbose) — user elected to keep Phase 6 focused on flags only
- **Progress bar for simulation** (tqdm) — post-MVP
