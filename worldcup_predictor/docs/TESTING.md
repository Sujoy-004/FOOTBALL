<!-- generated-by: gsd-doc-writer -->

# Testing — World Cup Dynamic Prediction

## Framework

```
pytest >= 9.0
pytest-cov >= 7.1
```

## Quick Commands

**Available Commands:**
- `pytest -v` — All tests
- `pytest --cov=src --cov-report=term-missing` — With coverage
- `pytest tests/test_elo.py -v` — Single file
- `pytest tests/test_elo.py::TestExpectedScore -v` — Single test
- `$env:BSD_API_KEY="key" ; pytest tests/test_live_smoke.py -x -v` — Live smoke

## Test Modules (18 total, 387 passing, 1 skipped)

```
┌──────────────────────┬─────────────────────────────────────────┐
│ Module               │ Coverage                                │
├──────────────────────┼─────────────────────────────────────────┤
│ test_elo.py          │ expected_score, update_ratings,         │
│                      │ apply_elo_update, K-factor              │
│ test_elo_sync.py     │ sync_elo_from_eloratings, staleness     │
│ test_state.py        │ load/save, _atomic_write_json,          │
│                      │ state_meta                              │
│ test_state_load.py   │ FileNotFoundError, JSONDecodeError      │
│ test_groups.py       │ group stage simulation, standings,      │
│                      │ tiebreakers                             │
│ test_group_integration.py │ group → knockout pipeline          │
│ test_knockout.py     │ resolve_knockout_slot_teams,            │
│                      │ run_full_simulation                     │
│ test_simulation.py   │ run_simulation, R16→FINAL               │
│ test_fetcher.py      │ fetch_raw_matches, process_matches,     │
│                      │ process_group_matches                   │
│ test_output.py       │ probability table, group standings,     │
│                      │ delta display                           │
│ test_cli.py          │ --once, --no-color, --seed, --help      │
│ test_main_loop.py    │ main loop, iteration cycle, shutdown    │
│ test_evaluation.py   │ brier_score, log_loss, calibration      │
│                      │ curve, compare_baselines                │
│ test_integration.py  │ E2E pipeline mock                       │
│ test_live_smoke.py   │ Live BSD API (skipped w/o BSD_API_KEY)  │
│ test_scaffold.py     │ Scaffold structure validation            │
│ test_odds.py         │ Vig removal, missing odds, cache         │
│                      │ schema, persistence, fetch+cache (17)    │
│ test_catboost.py     │ Parse predictions, missing predictions,  │
│                      │ cache schema, fetch integration,         │
│                      │ edge cases (20)                          │
└──────────────────────┴─────────────────────────────────────────┘
```

**Note:** `test_live_smoke.py` is marked `@pytest.mark.skipif` — auto-skipped when `BSD_API_KEY` is not set.

## Fixtures (`tests/conftest.py`)

**Available Fixtures:**
- `sample_teams` — 5 teams (`Argentina`, `France`, etc.) with Elo ratings
- `sample_bracket` — R16→QF→SF tournament DAG (7 matches)
- `sample_groups` — Group A with 4 teams, 6 unplayed matches
- `sample_played` — Empty played dict
- `sample_group_matches_results` — Pre-built Group A results (6 matches, deterministic scores)
- `sample_elo` — Elo ratings for 4 group teams

**Odds & CatBoost tests** (`test_odds.py`, `test_catboost.py`) use `tmp_path` for isolated file I/O and `monkeypatch` for HTTP mocking instead of conftest fixtures. No shared fixtures needed — each test class defines its own factory methods.

## Coverage Targets

- **Goal:** >90% on `src/` modules
- **Report:** `pytest --cov=src --cov-report=term-missing`
- No formal `.coveragerc` or `setup.cfg` — thresholds not enforced in CI

## CI Integration

- No CI workflow detected (`.github/workflows/` empty)
- Tests run locally only

## Writing New Tests

- Place in `tests/` directory
- Name: `test_*.py` — mirrors the module name under `src/` (e.g., `src/predictors/odds.py` → `tests/test_odds.py`)
- Use fixtures from `conftest.py` when possible
- For signal ingestion tests (`src/predictors/`), use `tmp_path` for file I/O isolation and `monkeypatch` for HTTP mocking instead of adding shared fixtures to `conftest.py`
- Update coverage goals: add new tests under `src/` modules
