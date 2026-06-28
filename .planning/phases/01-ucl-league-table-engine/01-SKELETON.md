# Phase 1 Walking Skeleton — UCL League Table Engine

> Scaffold structure for `competitions/ucl/` module. Created as part of MVP Walking Skeleton.

## Module Structure

```
competitions/ucl/
├── __init__.py              # sys.path bootstrap (following WC pattern)
├── src/
│   ├── __init__.py          # exports: fetch_club_elo, simulate_swiss_match, compute_swiss_standings, validate_ucl_fixtures, run_league_mc
│   ├── validation.py        # validate_ucl_fixtures() — fixture schedule validation
│   ├── elo_fetcher.py       # fetch_club_elo(), ClubElo API integration
│   ├── groups.py            # simulate_swiss_match(), compute_swiss_standings() — 10-step tiebreaker chain
│   └── simulation.py        # run_league_mc() — Monte Carlo loop
├── data/
│   ├── fixtures.json        # UCL fixture schedule (36 teams, 8 matchdays)
│   ├── team_aliases.json    # ClubElo name → canonical name mappings
│   └── uefa_coefficients.json  # UEFA club coefficients for tiebreaker step 10
└── tests/
    ├── __init__.py
    ├── conftest.py          # shared fixtures: sample_36_teams, sample_fixture_schedule, etc.
    ├── test_fixture_validation.py
    ├── test_simulation.py
    ├── test_swiss_tiebreakers.py
    └── test_monte_carlo.py
```

## Key Interfaces

### Data Flow
```
fixtures.json ──► validation.py ──► groups.py ──► simulation.py ──► MC results
                    (validate)       (standings)     (aggregate)
                                          ▲
                                    elo_fetcher.py
                                    (ClubElo API)
```

### Function Contracts

| Function | File | Input | Output |
|----------|------|-------|--------|
| `validate_ucl_fixtures(schedule)` | `validation.py` | dict (parsed JSON) | list[str] (errors, empty = valid) |
| `fetch_club_elo(team_name, date)` | `elo_fetcher.py` | str, str | float (Elo rating) |
| `simulate_swiss_match(team_a, team_b, elo_a, elo_b, rng)` | `groups.py` | str, str, float, float, Random | dict (score_a, score_b, ...) |
| `compute_swiss_standings(results, elo_ratings, coeffs)` | `groups.py` | dict, dict, dict | list[dict] (ranked teams) |
| `run_league_mc(fixtures, elos, coeffs, iterations, rng)` | `simulation.py` | dict, dict, dict, int, Random | dict (probabilities + averages) |

## End-to-End Verification

The thinnest working slice:
1. Load fixtures from `data/fixtures.json`
2. Validate with `validate_ucl_fixtures()`
3. Fetch Elo ratings via `fetch_club_elo()` for all 36 teams
4. Simulate one match using `simulate_swiss_match()` with `football_core` Poisson
5. Compute standings via `compute_swiss_standings()`
6. Verify positions 1-8 = top 8, 9-24 = playoff, 25-36 = eliminated

Test: `python -m pytest competitions/ucl/tests/ -x --tb=short -q`
