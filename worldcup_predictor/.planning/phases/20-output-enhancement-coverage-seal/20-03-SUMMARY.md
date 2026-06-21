# 20-03: Match Detail & Focus Card

## Goal
Add per-match signal table (`--match-detail`) and match focus card (`--match-detail MATCH_ID`) outputs with Wilson score CI, signal helpers, and display dispatch.

## Implementation

### Wilson Score CI Functions (V2-28)
- `wilson_score_ci(k, n, z=1.96)` → `(lower, upper)` — closed-form using `math.sqrt` only
- `format_ci(k, n)` → formatted string `"[0.496 — 0.504]"`
- `wilson_ci_from_prob(p, n=50000)` → CI string from probability or None
- All in `src/output.py` before coverage auditor section
- 5 tests in `TestWilsonCI`

### Per-Match Signal Table (V2-27)
- `print_match_detail_table(matches_data, prev_matches_data=None)` — 7-column table (Elo, Odds, CB, Form, Line, xG, Δ)
  - `_fmt_prob()` / `_fmt_xg()` / `_format_delta_cell()` helpers
  - Δ column compares blended to previous iteration
  - 85-col width per D-01 constraint
- Backward compatible: works with empty/None data
- 3 tests in `TestMatchDetailTable`

### Match Focus Card (Mockup 3 layout per D-20)
- `print_focus_card(match_data, match_entry=None)` — 3 sections:
  - **Signals**: 7 rows (Blended, Elo, Odds, CatBoost, Form, Lineup, xG) with Prob, Δ, CI columns
  - **Context**: venue, referee, city, coaches (conditional on match_entry)
  - **Stats**: fouls, corners, shots, possession, cards (conditional on match_entry having stats)
- Backward compatible: shows "available after match completion" for upcoming matches
- 5 tests in `TestFocusCard`

### CLI Flag & Signal Helpers (3a)
- `--match-detail` optional arg: `--match-detail` → table, `--match-detail M73` → focus card, absent → disabled
- `_match_detail_enabled` module state variable (parallel to `_ai_preview_enabled`)
- `_collect_matches_from_groups()` / `_collect_matches_from_bracket()` helpers
- `_expected_score_for_match()` Elo helper
- `_gather_signal_data()` — builds per-match signal dicts from all caches
- `_prev_signal_data` module state for per-signal Δ tracking across iterations

### Display Dispatch (3b)
- Wired in `_run_iteration()` after probability log snapshot
- Table mode: calls `print_match_detail_table(matches_data, _prev_signal_data)`
- Focus mode: finds match by ID, builds prev_signals + blended_delta, calls `print_focus_card()`
- Saves `_prev_signal_data` for next iteration's Δ
- Exception-safe wrapper

## Files Changed
| File | Change |
|------|--------|
| `src/output.py` | +284 lines (CI functions, signal helpers, match table, focus card) |
| `tests/test_output.py` | +100 lines (13 new tests across 3 classes) |
| `main.py` | +116 lines (CLI flag, signal data helpers, display dispatch wiring) |

## Test Results
- 601 passed, 1 skipped, 0 regressions
- 13 new tests: 5 Wilson CI + 3 MatchDetailTable + 5 FocusCard
