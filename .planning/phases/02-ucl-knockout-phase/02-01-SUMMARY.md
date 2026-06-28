# Plan 02-01: Two-Legged Tie Simulation + Data Files

**Completed:** 2026-06-28
**Status:** ✓ Complete

## Summary

Built the core two-legged knockout tie primitive and the dedicated competition data files for playoff pairings and bracket structure.

## Completed Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Create playoff draw and bracket structure data files + conftest fixtures | `5095e82` |
| 2a (RED) | Add failing tests for two-legged tie simulation | `3794bbc` |
| 2b (GREEN) | Implement `simulate_two_legged_tie()` with aggregate scoring, ET, and penalties | `7636a64` |
| 2c (REFACTOR) | Apply ET home advantage boost and improve test robustness | `05077fa` |
| 3 | Verify two-legged tie simulation produces plausible results | Approved (checkpoint) |

## Files Created

| File | Purpose |
|------|---------|
| `competitions/ucl/data/playoff_pairings.json` | 8 playoff ties mapping positions 9-24 |
| `competitions/ucl/data/bracket_rules.json` | 15-match R16/QF/SF/Final bracket structure |
| `competitions/ucl/src/knockout.py` | `simulate_two_legged_tie()`, `_simulate_penalty_shootout()` |
| `competitions/ucl/tests/test_knockout.py` | 14 tests: tie simulation + penalty shootout |

## Files Modified

| File | Change |
|------|--------|
| `competitions/ucl/tests/conftest.py` | Added `sample_playoff_pairings`, `sample_bracket_rules`, `sample_knockout_elos`, `sample_tie_standings` fixtures |
| `competitions/ucl/src/__init__.py` | Added `simulate_two_legged_tie` export |

## Key Implementation Decisions

- **File naming:** Used `playoff_pairings.json` and `bracket_rules.json` as conventional data file names
- **ET lambda factor:** Configurable parameter defaulting to 0.25 (30-min ET / 90-min normal time)
- **Penalty conversion:** Configurable parameter defaulting to 0.76 (historical UCL average)
- **No away goals rule:** Per 2025+ format, aggregate level always goes to ET regardless of away goals
- **Second-leg home advantage:** Applied in ET only (D-03), not normal time
- **Penalty shootout:** 5 rounds + sudden death; early termination if one team cannot be caught

## Test Results

- 14/14 knockout tests pass
- 73/73 UCL tests pass (1 skipped = live ClubElo API)
- WC regression: all World Cup tests pass
- `football_core` unchanged
- Deterministic: same seed produces identical results
- 1000-trial plausibility: ~49.2% A wins (equal Elo), ~15.7% ET rate, ~9.4% penalty rate

## Dependencies Satisfied

- UCLK-01: ✅ Two-legged tie with aggregate scoring, ET, and penalties
- D-01: ✅ ET simulated locally with configurable reduced Poisson factor
- D-02: ✅ Penalties simulated locally with configurable conversion model
- D-03: ✅ ET home advantage to second-leg home team
- D-04: ✅ Playoff pairings from dedicated data file
- D-05: ✅ Deterministic fallback (9v24, etc.) encoded in data file
- D-06: ✅ Bracket structure from dedicated data file
- D-11: ✅ No football_core modifications
- D-12: ✅ Competition structure as replaceable data
