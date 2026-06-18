---
phase: 05-console-output-formatting
created: 2026-06-13
source: Nyquist validation strategy
framework: pytest
---

# Phase 5 Validation Strategy: Console Output & Formatting

## Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | None (default pytest discovery) |
| Quick run command | `cd worldcup_predictor && python -m pytest tests/test_output.py -x` |
| Full suite command | `cd worldcup_predictor && python -m pytest tests/ -x` |

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File |
|--------|----------|-----------|-------------------|------|
| UI-01 | Top-5 table output sorted by champion% | snapshot/subprocess | `pytest tests/test_output.py::test_top5_table` | test_output.py (Wave 0) |
| UI-01 | Remaining teams one-liner summary | snapshot | `pytest tests/test_output.py::test_remaining_teams` | test_output.py (Wave 0) |
| UI-02 | Delta symbol direction (▲/▼/ ) matches sign | unit | `pytest tests/test_output.py::test_delta_symbol` | test_output.py (Wave 0) |
| UI-02 | Risers/fallers top-3 with percentage format | snapshot | `pytest tests/test_output.py::test_delta_summary` | test_output.py (Wave 0) |
| UI-02 | First call shows no deltas when prev_probs is None | unit | `pytest tests/test_output.py::test_first_call_no_deltas` | test_output.py (Wave 0) |
| UI-03 | ANSI codes stripped when stdout not a tty | unit | `pytest tests/test_output.py::test_no_ansi_when_piped` | test_output.py (Wave 0) |
| UI-03 | Plain text fallback preserves symbols (▲▼⚠) | unit | `pytest tests/test_output.py::test_symbols_preserved` | test_output.py (Wave 0) |
| (internal) | All output functions defined in output.py | import | `python -c "from src import output; print(hasattr(output, 'print_header'))"` | — |
| (internal) | test_main_loop.py tests still pass after return sig change | integration | `pytest tests/test_main_loop.py -x` | test_main_loop.py (update) |
| (internal) | Shutdown banner text matches new format | integration | `pytest tests/test_main_loop.py::test_main_loop_clean_shutdown -x` | test_main_loop.py (update) |

## Sampling Rate

- **Per task commit:** `cd worldcup_predictor && python -m pytest tests/test_output.py -x --tb=short`
- **Per wave merge:** `cd worldcup_predictor && python -m pytest tests/test_output.py tests/test_main_loop.py -x --tb=short`
- **Phase gate:** Full suite `cd worldcup_predictor && python -m pytest tests/ -x`

## Wave 0 Gaps

- [ ] `tests/test_output.py` — new file, create first in Wave 0
- [ ] `tests/test_main_loop.py` — update `test_hourly_resim_triggers` unpack to 3 values (Plan 05-01)
- [ ] `tests/test_main_loop.py` — update `test_main_loop_clean_shutdown` assertion to new banner text (Plan 05-02)

Existing `tests/conftest.py` fixtures (`sample_teams`, `sample_bracket`, `sample_played`) are reusable for output tests.
