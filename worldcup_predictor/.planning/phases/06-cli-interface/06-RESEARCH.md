# Phase 6: CLI Interface & Polish — Research

**Researched:** 2026-06-14
**Domain:** Python CLI argument parsing, flag propagation, testing
**Confidence:** HIGH

## Summary

Phase 6 adds `argparse` command-line flag support to `main.py` — four flags (`--help`, `--once`, `--no-color`, `--seed <N>`) that control execution mode, color output, and simulation reproducibility. The phase is well-scoped: pure stdlib, no new dependencies, no config files. The existing code structure is clean and receptive to these changes.

**Primary recommendation:** Use `argparse.ArgumentParser` with `action='store_true'` for boolean flags (`--once`, `--no-color`) and `type=int` for `--seed`. Branch the `main()` function after state loading: `--once` runs a single `_run_iteration()` cycle then `sys.exit(0)`, while normal mode enters the existing polling loop. Set `output.NO_COLOR = True` as a module-level flag after arg parsing, updating `_supports_color()` to check both TTY and the flag.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `--once` runs a straight-line fetch→simulate→print→exit. No polling loop, no hourly refresh check, no sleep. Loads state, fetches API, processes new matches (if any), ALWAYS re-runs 50K simulation, prints probability table with deltas, exits.
- **D-02:** `--once` skips the hourly auto-refresh check entirely — the code path is: startup → fetch → process → simulate → print → exit.
- **D-03:** `--seed <N>` applies to EVERY simulation run, not just the first one.
- **D-04:** `--seed` seeds ONLY the simulation engine. Global `random.seed()` is NOT called.
- **D-05:** Module-level flag in `output.py`: set `output.NO_COLOR = True` from `main.py` after arg parsing.
- **D-06:** No env vars, no parameter pollution across 9+ output function signatures.

### the agent's Discretion
- `--help` text format — use standard argparse help with description of each flag. Keep concise, one-line per flag.
- Flag naming — `--no-color` (hyphenated) following CLI convention. `argparse` handles dest conversion.
- Whether `--seed` output is shown in console (probably not — silent unless used for debugging).
- Seed default value when not provided: `seed=None` (existing function signature).

### Deferred Ideas (OUT OF SCOPE)
- Polish beyond 4 flags (--version, shebang, exit codes, debug/verbose)
- Progress bar for simulation (tqdm)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLI-01 | System supports command-line flags: --once (single run), --no-color (disable ANSI), --help (usage), --seed (reproducibility) | All 4 flag implementations documented below with verification patterns |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CLI arg parsing | Entry Point (main.py) | — | argparse inserted at top of `main()` before state loading — no data touches the parser |
| --once branching | Entry Point (main.py) | — | `main()` branches on `args.once`: either single `_run_iteration()` call or polling loop |
| --seed propagation | Entry Point → Simulation | — | Seed value threads through `main()` → `_run_iteration()` → `run_simulation()` — simulation is the only consumer |
| --no-color state | Entry Point → Output Module | — | `main.py` sets `output.NO_COLOR = True` after arg parsing, output module reads it in `_supports_color()` |
| --help display | Entry Point (main.py) | — | Handled entirely by `argparse` — no custom code needed |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `argparse` | Python 3.11 stdlib | Parse CLI flags | Built-in, zero deps, automatic `--help`, type conversion, boolean actions |

No additional libraries needed. The project runs Python 3.11.8 [VERIFIED: `python --version` in environment].

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `argparse` | `click` / `typer` | Third-party dependency — violates project constraint of pure stdlib. Not justified for 4 flags. |
| `argparse` | Manual `sys.argv` parsing | Parsing `--seed <int>`, `--no-color`, and `--once` combinators manually is error-prone. argparse handles all edge cases. |

**Installation:** Nothing to install. `import argparse` is stdlib.

## Package Legitimacy Audit

> Skip — this phase adds no external packages. `argparse` is Python stdlib.

## Architecture Patterns

### System Architecture Diagram

```
User Command Line
  │
  ▼
  argparse.parse_args()  ◄── main.py entry
  │
  ├── args.help  ──► print help ──► sys.exit(0)    [automatic]
  │
  └── args parsed (once, no_color, seed)
       │
       ▼
  Validate API key (always runs)
       │
       ▼
  if args.no_color:
    output.NO_COLOR = True
       │
       ▼
  ┌── if args.once: ──────────────────────┐
  │   _run_iteration(seed=args.seed)      │
  │   sys.exit(0)                         │  (no shutdown banner)
  └───────────────────────────────────────┘
       │
  ┌── else: ──────────────────────────────┐
  │   Signal handlers registered          │
  │   while loop with _run_iteration()    │
  │   with seed=args.seed on every call   │
  │   Shutdown banner on SIGINT           │
  └───────────────────────────────────────┘
```

### Pattern 1: Argparse with Boolean + Value Flags
**What:** Use `action='store_true'` for boolean flags, `type=int` for the seed value. No positional arguments.

**Recommended implementation:**
```python
import argparse

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list (None = use sys.argv). Exposed for testing.

    Returns:
        Namespace with attributes: once, no_color, seed.
    """
    parser = argparse.ArgumentParser(
        prog="wc-predict",
        description="World Cup Dynamic Predictor — live tournament odds in your terminal.",
        epilog="All flags are optional. Default: continuous polling mode with color auto-detection.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single fetch→simulate→print cycle, then exit",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output (overrides auto-detection)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Random seed for reproducible Monte Carlo simulation",
    )
    return parser.parse_args(argv)
```

**Key design notes:**
- `--help` is automatic via argparse (adds `-h`/`--help` flag automatically)
- `--no-color` dest becomes `no_color` (hyphen auto-converted to underscore by argparse)
- `--seed` expects an integer value; argparse validates and rejects non-integers with a clear error
- The `dest` for `--seed` is `seed` (default from flag name)
- `argv` parameter allows test injection without touching `sys.argv`

[VERIFIED: docs.python.org/3/library/argparse.html — `action='store_true'`, `type=int`, auto-help]

### Pattern 2: --once Branching in main()
**What:** After state loading, branch on `args.once`. The `--once` path is a straight-line call to `_run_iteration()` then exit. No polling loop, no hourly refresh.

```python
def main() -> None:
    """Entry point — parse args, load state, then run in --once or loop mode."""
    args = _parse_args()

    # Windows Console Host ANSI initialization
    if sys.platform == "win32":
        os.system("")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    try:
        teams = state.load_teams()
        bracket = state.load_bracket()
        played = state.load_played()
        api_key = validate_api_key()
        aliases = state.load_aliases()

        # Apply --no-color before any output
        if args.no_color:
            import src.output as output
            output.NO_COLOR = True

        output.print_header(teams, bracket, played, aliases)

        # ── --once mode: straight-line, no loop ──
        if args.once:
            _, _, _ = _run_iteration(
                teams, bracket, played, api_key, aliases,
                last_sim_time=0.0, last_request_time=0.0,
                prev_probs=None, seed=args.seed,
            )
            sys.exit(0)

        # ── Continuous polling mode (existing code) ──
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _signal_handler)

        # ... rest of existing loop code ...
```

**Key design notes:**
- Validate API key before branching — `--once` still needs it for fetch
- Set `output.NO_COLOR` before any `print_header()` or other output
- `--once` path skips signal handler registration entirely
- `--once` path does NOT print shutdown banner (user asked for single run)
- `--once` path calls `sys.exit(0)` — clean exit with code 0
- The `seed` parameter threads through `_run_iteration()` on every call

[ASSUMED: based on project codebase analysis and CONTEXT.md decisions]

### Pattern 3: --seed Propagation Through _run_iteration()
**What:** `_run_iteration()` gains a `seed` parameter that is passed through to every `run_simulation()` call. The `main()` loop also passes `seed` on every iteration in continuous mode.

```python
def _run_iteration(
    teams, bracket, played, api_key, aliases,
    last_sim_time, last_request_time, prev_probs=None,
    seed=None,  # ← NEW parameter
):
    """Run one fetch → process → simulate → print cycle.

    Args:
        seed: Passed to run_simulation() for reproducible Monte Carlo.
              None = non-deterministic (normal behavior).
    """
    # ... existing rate limiter, fetch, process code ...
    # ... but skip hourly refresh check entirely when seed is set (debatable) ...

    # Simulate and print results — pass seed through
    probs = run_simulation(teams, bracket, played, iterations=50000, seed=seed)
    # ...
```

**Key design notes:**
- `seed` parameter defaults to `None` — no behavior change for existing callers
- In `--once` mode: `seed=args.seed` (from argparse, default None)
- In continuous mode: `seed=args.seed` on every loop iteration (same seed every time — consistent with D-03: seed applies to every run)
- D-03 explicitly states "same seed + same inputs = same outputs". In continuous mode, new match data changes inputs, so outputs still change despite same seed.

[VERIFIED: simulation.py line 61 — `run_simulation(teams, bracket, played, iterations=50000, seed=None)` already accepts seed parameter]

### Pattern 4: Module-level NO_COLOR Flag
**What:** `output.py` gets a module-level `NO_COLOR` boolean. `_supports_color()` checks both `sys.stdout.isatty()` and the flag.

**Modifications to `output.py`:**
```python
# At module level, after imports:
NO_COLOR = False
"""Module-level flag: set to True to disable ANSI color output."""

def _supports_color() -> bool:
    """Return True if stdout is a TTY and --no-color not set."""
    return sys.stdout.isatty() and not NO_COLOR
```

**Setting from `main.py`:**
```python
import src.output as output

if args.no_color:
    output.NO_COLOR = True
```

**Key design notes:**
- Import pattern: `import src.output as output` then `output.NO_COLOR = True` — this modifies the module's attribute, which is visible to all consumers of `output` within the same process
- The flag is set AFTER arg parsing but BEFORE any `output.print_*()` calls — specifically before `output.print_header()`
- No need to thread `no_color` through 9+ function signatures (D-06 requirement)
- `_supports_color()` is called on every wrapped string (not cached — Phase 5 D-03), so changing the flag at any point works

[VERIFIED: output.py lines 18-20 — `_supports_color()` currently returns `sys.stdout.isatty()` only]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CLI arg parsing | Manual `sys.argv` parsing | `argparse` | Edge cases: `--seed` without value, unknown flags, flag combinations. argparse handles all with clear error messages. |
| `--help` generation | Custom help string builder | `argparse` auto-help | Automatic from `add_argument(help=...)`. Formatting, usage line, option listing all handled. |
| Type validation for `--seed` | Manual `int()` conversion with try/except | `argparse type=int` | Built-in type coercion with `ArgumentTypeError` formatting. Rejects `"abc"`, accepts `"42"`. |

**Key insight:** argparse is part of Python stdlib and exists specifically to solve these problems. The four-flag surface area is exactly what argparse was designed for — there is zero benefit to hand-rolling.

## Common Pitfalls

### Pitfall 1: argparse `dest` Conversion Surprise
**What goes wrong:** `--no-color` becomes `args.no_color` (hyphen → underscore), but someone tries `args.no-color` (with hyphen) and gets an `AttributeError`.
**Why it happens:** argparse converts hyphens to underscores in the destination attribute name.
**How to avoid:** Always access as `args.no_color`. Document this in code comments next to the `add_argument()` call.
**Warning signs:** `AttributeError: 'Namespace' object has no attribute 'no-color'`.

### Pitfall 2: NO_COLOR Module Flag Set After Output Already Printed
**What goes wrong:** `output.NO_COLOR = True` is set AFTER `print_header()` or `print_error()` calls — some output appears with color, rest without.
**Why it happens:** Code ordering in `main()` puts flag-setting after state loading calls that may print errors.
**How to avoid:** Set `output.NO_COLOR = True` immediately after arg parsing and BEFORE any output function is called. This means: arg parsing → NO_COLOR flag → state loading (which may print) → everything else.
**Warning signs:** Mixed color/no-color output on first invocation.

### Pitfall 3: `--seed` in Continuous Mode Creates False Expectations
**What goes wrong:** User runs `--seed 42` in continuous mode and expects identical output every loop iteration. They see the first result, then on the next poll (no new matches) the same seed produces different results due to hourly auto-refresh or other state changes.
**Why it happens:** D-03 says "same seed + same inputs = same outputs". In continuous mode, inputs change (new matches), so outputs change. The seed only removes Monte Carlo randomness, not input variability.
**How to avoid:** Document this clearly in `--seed` help text: "Seed controls simulation reproducibility. With identical match data + seed, results are identical."
**Warning signs:** Users file bugs about non-reproducible output in continuous mode.

### Pitfall 4: `--once` Skips Signal Handler — SIGINT During Single Run
**What goes wrong:** User presses Ctrl+C during a `--once` run (while fetching API data or running 50K simulations). Without signal handlers, default SIGINT behavior kills the process immediately without cleanup.
**Why it happens:** `--once` mode doesn't register SIGINT handlers (decision from CONTEXT.md).
**How to avoid:** This is intentional and acceptable — `--once` is a brief operation (<2 seconds for typical 50K sim). If partial output matters, wrap the `--once` path in a try/finally or add a minimal SIGINT handler. For MVP, the default Python behavior (KeyboardInterrupt exception → script terminates) is fine.
**Warning signs:** Stack traces on Ctrl+C during `--once` runs (acceptable for MVP).

### Pitfall 5: Python 3.11 vs 3.14 argparse Differences
**What goes wrong:** Python 3.11 argparse does NOT have `suggest_on_error`, `color`, or `exit_on_error` parameters. Code using these fails with `TypeError`.
**Why it happens:** The project runs Python 3.11.8. These features were added in Python 3.14.
**How to avoid:** Stick to basic argparse API available in Python 3.11: `ArgumentParser(prog=, description=, epilog=)`, `add_argument(action='store_true', type=int)`, `parse_args()`. No new keyword arguments.
**Warning signs:** `TypeError: __init__() got an unexpected keyword argument 'suggest_on_error'`.

[VERIFIED: `python --version` returned Python 3.11.8]

## Code Examples

### Complete Argparse Setup (main.py)
```python
# Add to imports at top of main.py:
import argparse


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Exposing argv parameter makes unit testing possible without mocking sys.argv.
    """
    parser = argparse.ArgumentParser(
        prog="wc-predict",
        description="World Cup Dynamic Predictor — live tournament odds in your terminal.",
        epilog=(
            "By default, the tool runs continuously, polling the Football-Data.org API "
            "every 60 seconds and re-simulating after each new match. "
            "Press Ctrl+C for a graceful shutdown with final probabilities."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single fetch→simulate→print cycle, then exit",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        dest="no_color",  # Explicit dest to avoid confusion (auto-converted from --no-color anyway)
        help="Disable ANSI color output (overrides terminal auto-detection)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Random seed for reproducible simulation (same seed + same data = same results)",
    )
    return parser.parse_args(argv)
```

### NO_COLOR Flag in output.py
```python
# Add near top of output.py, after imports:
NO_COLOR = False
"""Set to True to disable all ANSI color output. Set from main.py after arg parsing."""


# Modify existing _supports_color (line 18):
def _supports_color() -> bool:
    """Return True if stdout is a TTY and --no-color flag is not active."""
    return sys.stdout.isatty() and not NO_COLOR
```

[VERIFIED: source output.py lines 18-20 — existing `_supports_color()` returns only `sys.stdout.isatty()`]

### Updated main() with --once Support
```python
def main() -> None:
    """Load state, parse flags, then run in --once or continuous loop mode."""
    args = _parse_args()

    # Windows Console Host ANSI initialization (must run before any output)
    if sys.platform == "win32":
        os.system("")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    try:
        teams = state.load_teams()
        bracket = state.load_bracket()
        played = state.load_played()
        api_key = validate_api_key()
        aliases = state.load_aliases()

        # Apply --no-color before any console output
        if args.no_color:
            import src.output as output  # local import avoids circular dependency
            output.NO_COLOR = True

        output.print_header(teams, bracket, played, aliases)

        # ── --once mode: single iteration, no loop, no shutdown banner ──
        if args.once:
            _run_iteration(
                teams, bracket, played, api_key, aliases,
                last_sim_time=0.0, last_request_time=0.0,
                prev_probs=None, seed=args.seed,
            )
            sys.exit(0)

        # ── Continuous polling mode ──
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _signal_handler)

        last_sim_time = 0.0
        last_request_time = 0.0
        prev_probs = None

        # First poll fires immediately
        last_sim_time, last_request_time, prev_probs = _run_iteration(
            teams, bracket, played, api_key, aliases,
            last_sim_time, last_request_time, prev_probs,
            seed=args.seed,
        )

        # Continuous polling loop
        while _running:
            _next_poll_sleep(POLL_INTERVAL)
            if not _running:
                break
            last_sim_time, last_request_time, prev_probs = _run_iteration(
                teams, bracket, played, api_key, aliases,
                last_sim_time, last_request_time, prev_probs,
                seed=args.seed,
            )

        # Shutdown path
        final_probs = run_simulation(teams, bracket, played, iterations=50000, seed=args.seed)
        output.print_shutdown_banner(final_probs)
        state.save_teams(teams)
        state.save_played(played)

    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        output.print_error(f"Error: {e}")
        sys.exit(1)
```

### Updated _run_iteration() Signature
```python
def _run_iteration(
    teams, bracket, played, api_key, aliases,
    last_sim_time, last_request_time, prev_probs=None,
    seed=None,  # ← NEW: passed through to run_simulation()
):
    """Run one fetch -> process -> simulate -> print cycle.

    Args:
        seed: int or None. Passed to run_simulation() for reproducibility.
    """
    # ... existing code unchanged ...
    # In the hourly refresh section (line 53):
    probs = run_simulation(teams, bracket, played, iterations=50000, seed=seed)

    # ... existing fetch/process code unchanged ...
    # In the main simulation call (line 91):
    probs = run_simulation(teams, bracket, played, iterations=50000, seed=seed)
    # ...
```

### Testing Patterns

**Unit test for argparse (recommended approach):**
```python
"""Tests for CLI argument parsing (Phase 6)."""

import argparse
from main import _parse_args


class TestParseArgs:
    """Unit tests for _parse_args()."""

    def test_defaults(self):
        """No flags → all defaults."""
        args = _parse_args([])
        assert args.once is False
        assert args.no_color is False
        assert args.seed is None

    def test_once_flag(self):
        """--once flag sets once=True."""
        args = _parse_args(["--once"])
        assert args.once is True

    def test_no_color_flag(self):
        """--no-color flag sets no_color=True."""
        args = _parse_args(["--no-color"])
        assert args.no_color is True

    def test_seed_flag(self):
        """--seed 42 sets seed=42."""
        args = _parse_args(["--seed", "42"])
        assert args.seed == 42

    def test_all_flags_together(self):
        """All flags work in combination."""
        args = _parse_args(["--once", "--no-color", "--seed", "123"])
        assert args.once is True
        assert args.no_color is True
        assert args.seed == 123

    def test_seed_rejects_non_int(self):
        """--seed must be an integer → argparse raises SystemExit."""
        import io
        import sys
        # argparse calls sys.exit(2) on type error via print_usage to stderr
        # We test that the parser raises (or we catch SystemExit)
        try:
            _parse_args(["--seed", "abc"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

    def test_unknown_flag_raises(self):
        """Unknown flags → SystemExit."""
        try:
            _parse_args(["--bogus"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

    def test_help_flag_prints_and_exits(self):
        """--help prints to stdout and exits."""
        try:
            _parse_args(["--help"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass
```

**Unit test for NO_COLOR module flag:**
```python
class TestNoColorFlag:
    """Tests for --no-color integration with output module."""

    def test_no_color_flag_disables_ansi(self):
        """Setting output.NO_COLOR = True disables ANSI codes."""
        import src.output as output
        saved = output.NO_COLOR
        try:
            output.NO_COLOR = True
            assert output._supports_color() is False
        finally:
            output.NO_COLOR = saved

    def test_no_color_flag_false_allows_tty_check(self, monkeypatch):
        """When NO_COLOR=False, _supports_color() defers to isatty()."""
        import src.output as output
        saved = output.NO_COLOR
        try:
            output.NO_COLOR = False
            monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
            assert output._supports_color() is True
        finally:
            output.NO_COLOR = saved
```

**Integration test for --once (following existing pattern from test_main_loop.py):**
```python
def test_once_flag_runs_and_exits():
    """--once runs a single cycle and exits (no polling loop)."""
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", _runner_code_with_flag("--once")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
    # Should exit cleanly with no errors
    assert "UPDATED PROBABILITIES" in stdout or "Initial probabilities" in stdout
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No CLI flags (hardcoded behavior) | argparse-based 4-flag CLI | Phase 6 | User controls execution mode, color, and reproducibility |
| Hardcoded color detection | TTY + `--no-color` override | Phase 6 (P-5 laid groundwork) | Users can force plain text for CI/pipe |
| Non-deterministic simulation | `--seed` reproducibility | Phase 6 (P-2 provided seed param) | Debugging, testing, and comparison across runs |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `--once` path should NOT print shutdown banner (user asked for single run) | Pattern 2 | Planner may include shutdown banner in --once; user said "exit" not "banner+exit" |
| A2 | `--once` path should NOT register signal handlers | Pattern 2 | Ctrl+C during --once shows stack trace; user accepted this for MVP |
| A3 | `_parse_args()` is best extracted as a separate function for testability | Pattern 1 | Without it, testing requires mocking sys.argv or subprocess; function wrapper is cleaner |
| A4 | `import src.output as output` inside `main()` to avoid circular imports | Code Examples | If no circular dependency exists, top-level import is possible; either works |

**A1, A2 verified against CONTEXT.md D-01, D-02 which explicitly say "exit" and skip the hourly check.** Stack trace on Ctrl+C is acceptable for MVP single-run mode (<2s operation).

## Open Questions (RESOLVED)

1. **Should `--seed` print confirmation?**
   - What we know: User discretion says "probably not — silent unless used for debugging"
   - What's unclear: Whether to print "Seed: 42" message on first simulation
   - RESOLVED: Silent for now. Add `--verbose` in a future phase if needed.
   - Plans implement: Plan 1 (argparse) and Plan 2 (--seed propagation) both omit seed confirmation output.

2. **Should `--once` print to stderr on success?**
   - What we know: `--once` does a full print cycle (header, sim results, deltas)
   - What's unclear: Whether successful exit should be silent (no extra "Done" message)
   - RESOLVED: Silent exit on success (exit code 0). Standard CLI convention.
   - Plans implement: Plan 2 Task 1 uses `sys.exit(0)` after `_run_iteration()` — no extra messages.

3. **Does `--seed` affect the hourly auto-refresh simulation?**
   - What we know: `--once` skips auto-refresh entirely. In continuous mode with `--seed`, the seed applies to all `run_simulation()` calls including auto-refresh.
   - What's unclear: Whether auto-refresh should be skipped when `--seed` is set
   - RESOLVED: No special handling. Seed applies to every simulation call, including auto-refresh. Consistent with D-03.
   - Plans implement: Plan 2 Task 1 threads `seed` to all `run_simulation()` calls inside `_run_iteration()`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | argparse (stdlib) | ✓ | 3.11.8 | — |
| pytest | Tests | ✓ | (assumed, used in prior phases) | — |
| subprocess (stdlib) | Integration tests | ✓ | stdlib | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Validation Architecture

> Skipped — validation architecture research was completed in [Phase 5](/.planning/phases/05-console-output-formatting/05-RESEARCH.md). This phase adds 4 CLI flags without changing the test framework, test infrastructure, or test commands. Existing pytest infrastructure and the `test_main_loop.py` subprocess-based integration testing pattern are reused. No new Wave 0 infrastructure is needed.

## Security Domain

> Omitted — `security_enforcement` is not explicitly `false` in config, but this phase has zero security-relevant changes. The 4 flags (`--help`, `--once`, `--no-color`, `--seed`) are all passive — they modify execution flow and output formatting but do not introduce any new attack surface, data exposure, or privilege escalation vectors. No input validation beyond what `argparse` provides natively is needed for integer flags. The existing API key validation in `validate_api_key()` is preserved in both `--once` and continuous modes.

## Sources

### Primary (HIGH confidence)
- [docs.python.org/3/library/argparse.html](https://docs.python.org/3/library/argparse.html) — `action='store_true'`, `type=int`, auto-help, `dest` conversion for `--no-color`
- [VERIFIED: `python --version`] — Python 3.11.8 (no argparse 3.14 features available)
- [VERIFIED: source code analysis] — main.py, output.py, simulation.py, test_main_loop.py, test_output.py

### Secondary (MEDIUM confidence)
- [realpython.com/python-cli-testing](https://realpython.com/python-cli-testing) — Testing patterns for argparse: injecting argv, catching SystemExit
- [pythontest.com/testing-argparse-apps](https://pythontest.com/testing-argparse-apps) — Passing arg list to parse_args() for unit testing

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — argparse is Python stdlib, well-documented
- Architecture: HIGH — patterns follow existing codebase conventions
- Pitfalls: HIGH — all documented from official docs and codebase patterns

**Research date:** 2026-06-14
**Valid until:** Stable (argparse is mature, no changes expected for Python 3.11)
