---
phase: 02-monte-carlo-simulation
plan: 01
status: complete
tests_passing: 5/5
implemented: 2026-06-13
---

# Phase 2, Plan 1 Summary: Core Simulation Engine

## Objective

Build the core Monte Carlo simulation engine as a pure Python module, test it with deterministic-seed verification, and wire it into `main.py` so the user can run the predictor and see per-round championship probabilities.

## What Was Built

### `src/simulation.py` (106 lines)

Pure-functional Monte Carlo engine with no I/O side effects:

- **`run_simulation(teams, bracket, played, iterations=50000, seed=None)`** — main entry point returning `dict[str, dict[str, float]]` with `qf`/`sf`/`final`/`champion` keys per team
- **`_build_round_map(bracket)`** — pre-computes round-grouped match lists outside the hot loop
- **`_simulate_r16(...)`** — R16 round simulation (reads `team_a`/`team_b` directly)
- **`_simulate_knockout_round(...)`** — QF/SF/FINAL simulation (resolves participants via `source_matches` + `winner_progression`)
- Local bindings on hot path (`_rand`, `_exp`) for ~40K sims/sec performance
- `random.seed()` called once at start when seed is provided — supports reproducibility
- Uses `defaultdict(lambda: defaultdict(int))` for per-iteration tallying

### `tests/test_simulation.py` (84 lines, 5 tests)

TDD-first test suite in 2 classes:

- **TestSimulationDeterminism**
  - `test_deterministic_with_seed` — same seed (42) → identical results
  - `test_different_seeds_different` — seed 42 vs 99 → different results
- **TestSimulationProbabilities**
  - `test_champion_probs_sum_to_one` — sum within 0.001 of 1.0
  - `test_played_matches_respected` — played match winner advances deterministically (QF prob = 1.0)
  - `test_all_matches_played_deterministic` — every prob is exactly 0.0 or 1.0

Simulation-specific fixtures (`sim_teams`, `sim_bracket`, `sim_played`) defined inline in the test file.

### `main.py` (updated)

- Added `from src.simulation import run_simulation`
- Calls `run_simulation(teams, bracket, played, iterations=50000)` after state loading
- Prints formatted table with columns: Team, QF, SF, FINAL, CHAMPION
- Simulation error caught and printed to stderr

## Key Decisions Implemented

| Decision | Implementation |
|----------|---------------|
| D-01: ROUND_ORDER constant | `["R16", "QF", "SF", "FINAL"]` at module level |
| D-02: Round-specific sim functions | `_simulate_r16`, `_simulate_knockout_round` |
| D-03: Exact `run_simulation` signature | `(teams, bracket, played, iterations=50000, seed=None)` |
| D-04: No file I/O inside simulation | Confirmed — pure function |
| D-07: Output keys | `qf`, `sf`, `final`, `champion` via ROUND_KEYS |
| D-09: Seed reproducibility | `random.seed(seed)` exactly once at function start |
| D-14: Fresh winner_progression per iteration | Empty dict created inside loop |
| D-15: winner_progression stores all winners | Keys are match_ids, values are team names |

## Verification

### Test Results

```
$ python -m pytest tests/test_simulation.py -x -q
.....                                                                    [100%]
5 passed in 0.09s
```

All 5 simulation tests pass deterministically.

### Seed Reproducibility

Same seed (42) run twice produces identical probability dicts — confirmed by `test_deterministic_with_seed`.

### Probability Sum

Champion probabilities sum to 1.0000 (within float tolerance) — confirmed by `test_champion_probs_sum_to_one`.
