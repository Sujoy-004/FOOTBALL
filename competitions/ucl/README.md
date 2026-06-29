# UCL Predictor

Monte Carlo simulation engine for the UEFA Champions League 2025/26 season (36-team Swiss system format).

## Overview

The UCL Predictor simulates the complete UCL tournament — league phase (8 matches per team, pot-constrained opponents), playoff round (positions 9–24), seeded R16 bracket with top-4 protection, quarter-finals, semi-finals, and final — using Poisson-based match simulation driven by ClubElo ratings.

**Key capabilities:**

- 36-team Swiss-system league table with correct UCL tiebreaker chain
- Two-legged knockout ties with extra time and penalty shootouts
- Seeded R16 bracket with exact UEFA pairing rules
- Monte Carlo simulation for per-team advancement/elimination probabilities
- Live validation against BSD API match results
- JSON export for downstream analysis

## Architecture

The UCL module follows the competition module pattern: standalone, importable, with zero modifications to `football_core`. All data files live in `competitions/ucl/data/`. The display layer reads exclusively from the `SimulationResult` contract (no simulation imports in display code).

```
ucl-predict CLI (main.py)
  ├── Simulation orchestration (build_simulation_result)
  │   ├── run_monte_carlo()          — N-iteration simulation
  │   ├── simulate_league_phase()    — Single league phase snapshot
  │   └── simulate_knockout_tree()   — Full knockout pipeline
  ├── Display (display.py)
  │   ├── print_summary()
  │   ├── print_league_table()       — ANSI-colored zone highlighting
  │   ├── print_playoff_rounds()
  │   ├── print_knockout_bracket()   — Round-by-round match list
  │   ├── print_odds()               — Champion/qualification probabilities
  │   └── print_validation_summary() — Accuracy metrics (--validate)
  └── Validation (src/fetcher.py)
      └── fetch_ucl_matches()        — BSD API live match results
```

**Module structure:**

| Directory / File | Role |
|------------------|------|
| `main.py` | CLI entry point (`ucl-predict`), orchestration |
| `result.py` | `SimulationResult` frozen dataclass — contract between simulation and display |
| `display.py` | Formatted output — imports only `result.py` (D-17) |
| `src/simulation.py` | Monte Carlo simulation core — `run_monte_carlo()`, `simulate_league_phase()` |
| `src/groups.py` | Swiss system standings + 10-step UCL tiebreaker chain |
| `src/knockout.py` | Two-legged ties, playoff round, seeded R16 bracket, full knockout tree |
| `src/elo_fetcher.py` | ClubElo rating fetch (single request, cached per run) |
| `src/fetcher.py` | BSD API live match data for validation |
| `src/validation.py` | Fixture schedule validation (pot constraints, duplicates) |
| `data/` | JSON data files: fixtures, pairings, bracket rules, aliases, coefficients |
| `benchmarks/` | Performance benchmark script + results |
| `tests/` | pytest test suite |

## Usage

### Basic simulation

```
python -m competitions.ucl.main -n 10000
```

### Reproducible run with seed

```
python -m competitions.ucl.main -n 10000 -s 42
```

### JSON export

```
python -m competitions.ucl.main -n 10000 -o results.json
```

### Validate predictions against real results

```
export BSD_API_KEY=your_key_here
python -m competitions.ucl.main -n 10000 --validate
```

### Validate with JSON enrichment

```
python -m competitions.ucl.main -n 10000 --validate -o results_with_validation.json
```

**CLI flags:**

| Flag | Description | Default |
|------|-------------|---------|
| `-n, --iterations` | Monte Carlo iterations | 10000 |
| `-s, --seed` | Random seed for reproducibility | random |
| `-o, --output` | JSON output file path | (none) |
| `--validate` | Cross-check predictions against BSD match results | off |
| `--api-key` | BSD API key (overrides BSD_API_KEY env var) | env var |

### Benchmark

```
python competitions/ucl/benchmarks/benchmark_simulation.py
```

## Data Sources

- **ClubElo ratings** (footballclubelo.com) — Team strength ratings fetched once per run, cached for reproducibility.
- **BSD API** (sports.bzzoiro.com) — Live match results for validation against real outcomes. League ID: 7 (UCL 25/26). API key required.
- **Fixture schedule** — `data/fixtures.json` contains the synthetic 36-team fixture schedule.

## Validation

The `--validate` flag fetches completed UCL match results from the BSD API, computes home-win probability for each match using `expected_score()` from Elo ratings, and compares against actual outcomes. Metrics:

- **Brier Score** — Mean squared error between predicted probability and actual outcome (0.0 = perfect)
- **Log Loss** — Logarithmic loss, penalizes confident wrong predictions heavily
- **Accuracy** — Binary correctness thresholded at 50%
- **Calibration ECE** — Expected Calibration Error, measures how well predicted probabilities match observed frequencies
- **Market Odds Comparison** — Same metrics computed for BSD pre-match odds (after vig removal)

Validation output appears as a summary table on stdout and, if `--output` is used, enriches the JSON export with a `"validation"` section.

## Benchmarks

Latest performance measurements for the full UCL Monte Carlo simulation pipeline (see `benchmarks/BENCHMARK_RESULTS.md`):

| Iterations | Time (s) |
|------------|----------|
| 1,000 | 0.815 |
| 10,000 | 8.029 |
| 50,000 | 40.346 |

Benchmarks run with fixed seed (42) and measure wall-clock time only.

## Tests

```
# UCL module test suite
pytest competitions/ucl/tests/ -x --timeout=60

# WC regression test suite (must remain green)
pytest competitions/worldcup/tests/ -x --timeout=120
```

## Known Limitations

- **Synthetic fixture schedule** — Validation performed with a synthetic fixture schedule. The 36-team Swiss-system draw for 2025/26 UCL had not been conducted at the time of development. Re-run validation with the official schedule when available.
- **BSD API dependency** — Validation requires internet connectivity and a valid BSD API key. Without either, `--validate` prints a clear error and exits.
- **Single Elo signal** — Predictions are based solely on ClubElo ratings. Multi-signal blending (CatBoost, market odds, etc.) is a Phase 5 differentiator.
- **No injury/suspension modeling** — Squad composition is not modeled; Elo reflects team strength only.
- **No pyproject.toml/pip package** — The engine is run from source. Packaging is deferred until 3+ competition modules are stable.

## Release Notes

### v1.0 (current)
- Phase 1: 36-team Swiss-system league phase with correct tiebreaker chain
- Phase 2: Two-legged knockout playoff, seeded R16 bracket, full knockout tree
- Phase 3: `ucl-predict` CLI with formatted output and JSON export
- Phase 4: BSD API validation, accuracy metrics, performance benchmarks, full documentation

### v2 (planned)
- What-if scenario analysis
- Competition differentiators (player form, signal blending)
- Additional competition support (La Liga, Premier League)
