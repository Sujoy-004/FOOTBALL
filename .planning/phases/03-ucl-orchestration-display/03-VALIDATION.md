---
phase: 03-ucl-orchestration-display
validated: 2026-06-28
source: RESEARCH.md Validation Architecture (lines 540-571)
status: pending
---

# Phase 3: UCL Simulation Orchestration + Display — Validation Strategy

## Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | None — project-wide defaults |
| Quick run command | `python -m pytest competitions/ucl/tests/test_cli.py competitions/ucl/tests/test_display.py -x` |
| Full suite command | `python -m pytest competitions/ucl/tests/ -x` |

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File |
|--------|----------|-----------|-------------------|------|
| UCLO-01 | CLI parses -n/--iterations, -s/--seed, -o/--output | unit | `test_cli.py::test_defaults` etc. | `test_cli.py` |
| UCLO-02 | League table displays 36 rows with 6 columns, zone coloring | unit | `test_display.py::test_league_table_*` | `test_display.py` |
| UCLO-03 | Bracket displays round-by-round match list | unit | `test_display.py::test_knockout_bracket_*` | `test_display.py` |
| UCLO-04 | Odds table shows all 36 teams, sorted by champion prob descending | unit | `test_display.py::test_odds_*` | `test_display.py` |
| D-10/D-11 | ANSI codes present when stdout is TTY, absent when piped | unit | `test_display.py::test_ansi_*` | `test_display.py` |
| D-13/D-14 | JSON export has correct schema, stdout still prints text | unit | `test_cli.py::test_output_flag` | `test_cli.py` |
| D-17 | display.py does not import from simulation.py/knockout.py | static | `grep -c "from competitions.ucl.src" display.py` | static check |

## Sampling Rate

- **Per task commit:** `python -m pytest competitions/ucl/tests/test_cli.py competitions/ucl/tests/test_display.py -x`
- **Per wave merge:** `python -m pytest competitions/ucl/tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

## Wave 0 Gaps

- [ ] `tests/test_cli.py` — covers UCLO-01 (argparse tests)
- [ ] `tests/test_display.py` — covers UCLO-02, UCLO-03, UCLO-04 (display output tests)
- [ ] `tests/conftest.py` — add `sample_result: SimulationResult` fixture for display tests
- [ ] Display import audit — add a static check that `display.py` has zero imports from `competitions.ucl.src` (except `.result`)
