# Plan 18-03 Summary — CLI Wiring + Integration Tests

## Goal
Wire `--ai-preview` CLI flag, build `xg_overrides` dict, connect `print_ai_previews()` call, and add integration tests.

## Changes

### `main.py`
- **Module-level flag**: Added `_ai_preview_enabled: bool` after `_last_gov_time` — set in `main()` after `_parse_args()`
- **CLI flag**: Added `--ai-preview` argparse flag with `dest="ai_preview"` before the return in `_parse_args()`
- **Global set**: `_ai_preview_enabled = args.ai_preview` right after `args = _parse_args()` in `main()`
- **xG overrides dict**: Built from `cb_cache["matches"]` after the catboost cache block — maps `match_id → (expected_home_goals, expected_away_goals)` for entries where both xG values exist
- **Simulation wiring**: Added `xg_overrides=xg_overrides` to the `run_full_simulation()` call at line 876
- **AI preview display**: Added `if _ai_preview_enabled: output.print_ai_previews(played, played_groups)` after `print_probability_table()` at line 887

### `tests/test_cli.py`
- `test_ai_preview_flag` — `--ai-preview` sets `ai_preview=True`
- `test_ai_preview_default` — no flag means `ai_preview=False`
- Updated `test_all_flags_together` — includes `--ai-preview` in combined flag test

### `tests/test_main_loop.py`
- `test_ai_preview_flag_disabled` — `--once` alone: "No AI previews available." NOT in stdout
- `test_ai_preview_flag_enabled` — `--ai-preview --once`: "No AI previews available." appears in stdout

## Verification
- `python -m pytest tests/test_cli.py -v` — 10/10 passed
- `python -m pytest tests/test_main_loop.py::test_ai_preview_flag_disabled -v` — passed
- `python -m pytest tests/test_main_loop.py::test_ai_preview_flag_enabled -v` — passed
- Full suite: 555 passed, 1 skipped (live smoke), 0 failed

## Key Decisions
- `print_ai_previews()` correctly called with `played` and `played_groups` (not `groups, bracket, cb_cache`) as confirmed by reading actual function signature
- Hourly re-sim path intentionally does NOT pass xg_overrides (D-04 — would be stale)
- Shutdown path intentionally does NOT pass xg_overrides (final display only)
