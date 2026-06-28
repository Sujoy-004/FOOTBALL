# Plan 02-02: Playoff Round Simulation

**Completed:** 2026-06-28
**Status:** ✓ Complete

## Summary

Built the playoff round orchestrator that consumes the playoff pairings data file and `simulate_two_legged_tie()` to resolve all 8 ties between positions 9-24.

## Completed Tasks

| Task | Name | Commit |
|------|------|--------|
| 1a (RED) | Add failing tests for `simulate_playoff_round()` | `f6bdc20` |
| 1b (GREEN) | Implement `simulate_playoff_round()` | `49244eb` |
| 2 | Verify playoff round produces plausible results (checkpoint) | Approved |

## Files Created

| File | Purpose |
|------|---------|
| — | Extended existing files only |

## Files Modified

| File | Change |
|------|--------|
| `competitions/ucl/src/knockout.py` | Added `simulate_playoff_round()`, `import json`, `import os` |
| `competitions/ucl/src/__init__.py` | Added `simulate_playoff_round` export |
| `competitions/ucl/tests/conftest.py` | Added `sample_playoff_standings` fixture |
| `competitions/ucl/tests/test_knockout.py` | Added `TestPlayoffRound` (9 tests) |

## Key Implementation Decisions

- **Seeded team = team_b:** Seeded team (position_a, 9-16) is passed as `team_b` to `simulate_two_legged_tie()` so it gets second-leg home advantage (D-05)
- **Input validation:** Raises `ValueError` if a team at a required position (9-24) is missing from standings (T-02-05) or if pairings reference invalid positions (T-02-06)
- **Data file loading:** Uses `*playoff*` glob to discover the playoff pairings file, falling back to conventional name
- **Elo merge:** Blends `elo` field from standings entries with provided `elo_ratings` dict for maximum compatibility

## Test Results

- 9/9 TestPlayoffRound tests pass
- 23/23 knockout tests pass (14 from 02-01 + 9 new)
- 82/82 UCL tests pass (1 skipped = live ClubElo API)
- WC regression: all World Cup tests pass
- Deterministic: same seed → identical results
- Manual integration with real fixtures: 8 ties resolved plausibly (seeded teams won 7/8)

## Dependencies Satisfied

- UCLK-04: ✅ Playoff round simulation (positions 9-24)
- D-04: ✅ Playoff pairings loaded from dedicated data file
- D-05: ✅ Seeded teams (9-16) get second-leg home advantage
- D-07: ✅ Knockout pipeline extends MC loop (interface ready)
- D-11: ✅ No football_core modifications
