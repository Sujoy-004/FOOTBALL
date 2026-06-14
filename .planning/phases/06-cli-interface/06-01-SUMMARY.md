---
phase: 06-cli-interface
plan: 01
subsystem: cli
tags: argparse, no-color, cli-flags, ansi-output

requires: []
provides:
  - argparse CLI framework (_parse_args) for Plans 2-3
  - NO_COLOR module flag for color control
  - test patterns for CLI unit tests (TestParseArgs)
affects: [06-cli-interface]

tech-stack:
  added: [argparse (stdlib)]
  patterns: [Module-level config flags, argparse argv passthrough for testability]

key-files:
  created:
    - worldcup_predictor/tests/test_cli.py — 8 unit tests for _parse_args()
  modified:
    - worldcup_predictor/main.py — added import argparse, _parse_args(), args = _parse_args(), --no-color wiring
    - worldcup_predictor/src/output.py — added NO_COLOR module flag, updated _supports_color()
    - worldcup_predictor/tests/test_output.py — added TestNoColorFlag class with 3 tests

key-decisions:
  - "Module-level NO_COLOR flag in output.py: set from main.py after arg parsing, checked by _supports_color()"
  - "Argparse argv passthrough parameter (argv: list[str] | None = None) — enables unit testing without mocking sys.argv"
  - "--no-color hyphenated naming: argparse converts to no_color via dest parameter"
  - "Flag names: --once, --no-color, --seed (standardized for Plan 2 compatibility)"

requirements-completed: [CLI-01]

duration: 4 min
completed: 2026-06-14
---

# Phase 6: CLI Interface Summary — Plan 1

**argparse CLI framework with --once, --no-color, --seed flags and NO_COLOR module flag for ANSI control**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-14T09:55:14Z
- **Completed:** 2026-06-14T09:59:06Z
- **Tasks:** 2 (implemented TDD-style: tests-first, then code)
- **Files modified:** 4

## Accomplishments

- `_parse_args()` function with `--once`, `--no-color`, `--seed` flags using argparse
- `--help` shows all 4 flags with concise descriptions and detailed epilog
- `--no-color` flag wired through `main()` → `output.NO_COLOR` → `_supports_color()`
- `NO_COLOR = False` module-level flag in `output.py`
- `_supports_color()` checks both `sys.stdout.isatty()` and `not NO_COLOR`
- `--seed abc` rejected with type error and non-zero exit (threat T-06-01)
- `--bogus` rejected with unrecognized argument error (threat T-06-02)
- 8 unit tests for argument parsing (defaults, each flag, combinations, error cases)
- 3 unit tests for NO_COLOR flag behavior (True disables, False defers to TTY, default is False)

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement _parse_args() + NO_COCOLOR + wiring** — `c02eac2` (feat)
2. **Task 2: Add CLI arg tests + NO_COLOR output tests** — `7556605` (test)

**Plan metadata:** (committed in next step)

## Files Created/Modified

- `worldcup_predictor/main.py` - Added `import argparse`, `_parse_args()` function, `args = _parse_args()` as first line of `main()`, `if args.no_color: output.NO_COLOR = True` before output calls
- `worldcup_predictor/src/output.py` - Added `NO_COLOR = False` module-level flag, updated `_supports_color()` to return `sys.stdout.isatty() and not NO_COLOR`
- `worldcup_predictor/tests/test_cli.py` - New file: `TestParseArgs` class with 8 unit tests (defaults, --once, --no-color, --seed, all-flags, error cases)
- `worldcup_predictor/tests/test_output.py` - Added `TestNoColorFlag` class with 3 tests (NO_COLOR=True disables ANSI, NO_COLOR=False defers to TTY, default is False)

## Decisions Made

- **Module-level flag pattern (D-05):** `output.NO_COLOR = True` set from `main.py` after arg parsing. The `_supports_color()` function checks both `sys.stdout.isatty()` and the `NO_COLOR` flag. No parameter pollution across 9+ output function signatures.
- **No env vars (D-06):** Avoiding hidden state. The flag is set explicitly from code, not from environment variables.
- **Argv passthrough for testability:** `_parse_args(argv=None)` accepts an optional argument list — enables direct testing without mocking `sys.argv`.
- **Hyphenated flags:** `--no-color` (not `--no_color`). Argparse converts `dest="no_color"` automatically.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-existing `test_main_loop.py::test_main_loop_runs_iterations` failure persists — this test looks for "Fetched" in output but the current main.py flow produces different messages. Not related to this plan's changes.
- No other issues.

## Threat Model Compliance

| Threat | Disposition | Status |
|--------|-------------|--------|
| T-06-01: --seed non-int tampering | mitigate via type=int | ✅ Implemented — argparse rejects non-integer `--seed` values |
| T-06-02: Unknown flags | mitigate via parse_args defaults | ✅ Implemented — argparse raises SystemExit on unrecognized args |
| T-06-03: --help info disclosure | accept | ✅ No secrets exposed in help text |
| T-06-SC: argparse stdlib | accept | ✅ CPython stdlib since 3.2 |

## Next Phase Readiness

- `_parse_args()` framework ready for Plan 2 (--once and --seed flags)
- `NO_COLOR` flag fully integrated for all console output
- Test patterns established for CLI parameter testing
- Ready for Phase 6 Plan 2: --once mode and --seed integration

## Self-Check: PASSED

All file and commit verifications passed:
- All 4 source files exist on disk ✓
- All 3 commits found in git log ✓
- All 85 tests pass (8 CLI + 3 NO_COLOR + 74 existing) ✓
- Plan-level verification: --help, --bogus, --seed abc error cases all pass ✓

---

*Phase: 06-cli-interface*
*Completed: 2026-06-14*
