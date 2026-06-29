# Architecture: UCL Predictor Module

## Overview

The UCL Predictor is a competition module for the football prediction engine, implementing the 2025+ UEFA Champions League format (36-team Swiss system). It follows the established competition module pattern: self-contained, zero modifications to `football_core`, data-driven configuration.

This document describes the architecture for developers extending the UCL module or building new competition modules on the same pattern.

## Module Layout

All UCL code lives under `competitions/ucl/`:

- `main.py` — CLI entry point (`ucl-predict`), orchestration, validation dispatch
- `result.py` — `SimulationResult` frozen dataclass (contract between simulation and display)
- `display.py` — Formatted output (imports only `result.py`, per D-17)
- `src/simulation.py` — Monte Carlo simulation core (`run_monte_carlo`, `simulate_league_phase`)
- `src/groups.py` — Swiss system standings computation + 10-step UCL tiebreaker chain
- `src/knockout.py` — Two-legged ties, playoff round, seeded R16 bracket, full knockout tree
- `src/elo_fetcher.py` — ClubElo rating fetch (single request, cached snapshot)
- `src/fetcher.py` — BSD API live match data for validation (Phase 4)
- `src/validation.py` — Fixture schedule validation (pot constraints, duplicate detection)
- `data/` — JSON data files (fixtures, pairings, bracket rules, aliases, coefficients)
- `benchmarks/` — Performance benchmark script + results (Phase 4)
- `tests/` — pytest test suite (129+ tests)
- `README.md` — Module documentation

## Data Flow

1. **CLI** (`main.py`) parses flags, loads fixture data from `data/fixtures.json`, fetches Elo ratings from ClubElo.
2. **Simulation** (`build_simulation_result`) runs Monte Carlo (`run_monte_carlo`) for aggregated probabilities plus one representative iteration for bracket display.
3. **Display** (`display.py`) reads `SimulationResult` and prints formatted output — summary, league table, playoff rounds, bracket, and odds.
4. **Validation** (optional, `--validate` flag): BSD API fetcher fetches real match results, `run_validation` cross-checks predictions using Elo-based `expected_score()`, metrics computed by `football_core/evaluation.py`.
5. **Export** (optional, `-o` flag): `dataclasses.asdict()` serialises the full result to JSON, enriched with validation data when `--validate` is active.

```
┌──────────┐    ┌──────────────┐    ┌────────────────┐
│  CLI     │───>│  Simulation  │───>│  Display       │
│ (main.py)│    │ (simulation) │    │ (display.py)   │
└──────────┘    └──────┬───────┘    └────────────────┘
                       │
                  ┌────▼───────┐    ┌──────────────────┐
                  │ Validation  │───>│ football_core/   │
                  │ (--validate)│    │ evaluation.py    │
                  └────────────┘    └──────────────────┘
```

## Key Contracts

### SimulationResult (result.py)

Frozen dataclass with JSON-native types throughout. Serves as the API boundary between simulation internals and display/export. Key fields:

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_date` | `str` | ISO date of Elo snapshot |
| `n_iterations` | `int` | Number of MC iterations |
| `seed` | `int` | Random seed used |
| `standings` | `list[dict]` | 36 team standings (position-ordered) |
| `teams` | `dict[str, dict]` | Per-team probabilities (zone, champion, stage) |
| `playoff_ties` | `dict[int, dict]` | Playoff tie results |
| `playoff_winners` | `dict[int, str]` | Playoff advancing teams |
| `bracket_rounds` | `dict[str, list[dict]]` | Round-by-round bracket matches |
| `bracket_champion` | `str \| None` | Tournament champion |
| `stages` | `dict[str, str]` | Final stage per team |
| `validation` | `dict \| None` | Validation results (Phase 4, D-09) |

### evaluation.py (football_core/)

Shared accuracy metrics extracted from WC evaluation.py (D-04, D-05). Five functions: `brier_score()`, `log_loss()`, `compute_metrics()`, `calibration_curve()`, `expected_calibration_error()`. Consumed by both WC and UCL validation pipelines.

## Simulation Pipeline

1. **Swiss-system league phase** — 8 matches per team, pot constraints, 10-step UCL tiebreaker
2. **Playoff round** — Positions 9–24, 8 two-legged ties (D-04 pairings, D-05 seeding)
3. **R16 bracket construction** — Seeded: 1/2 → 15/18, 3/4 → 13/20, etc. (D-06 data-driven)
4. **Knockout tree** — R16 → QF → SF → Final (two-legged except final, single-match neutral venue)
5. **Stage tracking** — All 36 teams mapped to stages: eliminated → playoff → r16 → qf → sf → final → champion (D-09)

## Validation Pipeline

1. **BSD API fetch** — `fetch_ucl_matches()` retrieves finished events (league_id=7)
2. **Team name normalization** — BSD names → canonical names via alias lookup
3. **Fixture matching** — BSD events matched to fixture schedule by (team_a, team_b) pair
4. **Prediction computation** — `expected_score(home_elo, away_elo)` for each matched match
5. **Metric computation** — Brier score, Log Loss, accuracy, calibration ECE (via `football_core/evaluation.py`)
6. **Market odds comparison** — Vig-removed BSD odds compared alongside model predictions (D-03)

## Dependencies

- **Python 3.11+** stdlib (no external ML dependencies)
- **`requests`** — BSD API and ClubElo HTTP calls
- **`football_core`** — fetcher (`fetch_raw_matches`), Elo (`expected_score`), evaluation metrics, odds (`remove_vig`)

## Design Decisions

- **D-01:** `--validate` flag on `ucl-predict` — not a standalone script
- **D-03:** BSD data is read-only reference for validation; never overwrites simulation outputs
- **D-04/D-05:** Accuracy metrics extracted to `football_core/evaluation.py` (Rule of Two: WC + UCL)
- **D-06/D-07:** Benchmark script at `competitions/ucl/benchmarks/benchmark_simulation.py`
- **D-08:** Synthetic fixture schedule — documented limitation
- **D-09:** Validation section appended to `SimulationResult` is backward-compatible public schema
- **D-17:** Display layer imports only `result.py` — no simulation internals
