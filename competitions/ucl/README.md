# UCL Predictor

Monte Carlo simulation engine for the UEFA Champions League 2025/26 season (36-team Swiss system format) — served via the unified web dashboard at `/ucl`.

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

The UCL module follows the competition module pattern: standalone, importable, with zero modifications to `football_core`. All data files live in `competitions/ucl/data/`.

```
web dashboard (web/ucl_app.py)
  ├── Simulation orchestration (src/orchestrator.py)
  │   ├── build_simulation_result()
  │   │   ├── run_monte_carlo()          — N-iteration simulation
  │   │   ├── simulate_league_phase()    — Single league phase snapshot
  │   │   └── simulate_knockout_tree()   — Full knockout pipeline
  │   ├── run_validation_suite()         — Multi-tier validation
  │   └── run_calibrated_validation()    — Temperature-calibrated validation
  └── REST API
      ├── GET /api/data, /api/standings, /api/bracket, /api/odds, /api/signals
      ├── POST /api/simulate, /api/calibrate, /api/mode, /api/what-if
      └── GET /api/validation, /api/report, /api/simulation/progress/{task_id}
```

**Module structure:**

| Directory / File | Role |
|------------------|------|
| `result.py` | `SimulationResult` frozen dataclass — contract between simulation and web layer |
| `src/simulation.py` | Monte Carlo simulation core — `run_monte_carlo()`, `simulate_league_phase()` |
| `src/groups.py` | Swiss system standings + 10-step UCL tiebreaker chain |
| `src/knockout.py` | Two-legged ties, playoff round, seeded R16 bracket, full knockout tree |
| `src/orchestrator.py` | Replay/live simulation orchestrator |
| `src/analysis.py` | Counterfactual analysis and validation suite |
| `src/elo_fetcher.py` | ClubElo rating fetch (single request, cached per run) |
| `src/fetcher.py` | BSD API live match data for validation |
| `src/validation.py` | Fixture schedule validation |
| `data/` | JSON data files: fixtures, pairings, bracket rules, aliases, coefficients |
| `benchmarks/` | Performance benchmark script + results |
| `tests/` | pytest test suite |

## Running

Start the web dashboard from the project root:

```bash
python -m web.server
```

Then open **http://127.0.0.1:8080/ucl**.

## Data Sources

- **ClubElo ratings** (footballclubelo.com) — Team strength ratings fetched once per run, cached for reproducibility.
- **BSD API** (sports.bzzoiro.com) — Live match results for validation against real outcomes. League ID: 7 (UCL 25/26). API key required.
- **Fixture schedule** — `data/fixtures.json` contains the synthetic 36-team fixture schedule.

## Tests

```
pytest competitions/ucl/tests/ -x --timeout=60
```

## Known Limitations

- **Single Elo signal** — Predictions are based on ClubElo ratings as primary signal with 4 additional blended signals.
- **No injury/suspension modeling** — Squad composition is not modeled; Elo reflects team strength only.
- **No pip install** — The engine is run from source.
