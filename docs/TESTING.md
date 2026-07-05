<!-- generated-by: gsd-doc-writer -->
# Testing

This document describes how the FOOTBALL Monte Carlo Prediction Engine is tested — the framework, test layout, run commands, patterns for adding new tests, coverage reporting, and CI configuration.

---

## Test Framework

The project uses **pytest >= 9.0** with **pytest-cov >= 7.1** for coverage reporting. There is no global `pytest.ini`, `tox.ini`, or `setup.cfg` — each competition's test suite is run independently from its own directory. Test dependencies are declared in `competitions/worldcup/requirements.txt`:

```
pytest>=9.0
pytest-cov>=7.1
python-dotenv>=1.0
```

Additional runtime dependencies (`requests`, `numpy`) are installed separately (see CI configuration).

---

## Test Structure and Organization

Tests are organized by layer, mirroring the project's three-tier architecture:

```
FOOTBALL/
├── football_core/tests/                  ← Shared engine library (6 test files, 109 tests)
│   ├── __init__.py
│   ├── test_availability_signal.py       Availability: team unavailability, match probability
│   ├── test_defensive_quality_signal.py  Defensive quality rating and probability
│   ├── test_evaluation.py                Brier score, log loss, calibration, ECE
│   ├── test_manager_effect_signal.py     Manager effect rating and probability
│   ├── test_manager_provider.py          Manager data parsing (providers.manager)
│   └── test_player_provider.py           Player data parsing (providers.player)
│
├── competitions/worldcup/tests/          ← World Cup 2026 (24 test files, 614 tests)
│   ├── __init__.py
│   ├── conftest.py                        Shared fixtures (sample_teams, sample_groups, etc.)
│   ├── fixtures/                          TSV data files
│   │   ├── eloratings_en_teams.tsv
│   │   └── eloratings_world.tsv
│   ├── test_blender.py
│   ├── test_catboost.py
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_elo.py
│   ├── test_elo_sync.py
│   ├── test_enrichment.py
│   ├── test_evaluation.py
│   ├── test_fetcher.py
│   ├── test_form.py
│   ├── test_governance.py
│   ├── test_group_integration.py
│   ├── test_groups.py
│   ├── test_integration.py
│   ├── test_knockout.py
│   ├── test_lineup.py
│   ├── test_live_smoke.py                Skipped without BSD_API_KEY
│   ├── test_main_loop.py
│   ├── test_migration.py
│   ├── test_odds.py
│   ├── test_output.py
│   ├── test_scaffold.py
│   ├── test_state.py
│   └── test_state_load.py
│
├── competitions/ucl/tests/               ← UCL 2025/26 (20 test files, 438 tests)
│   ├── __init__.py
│   ├── conftest.py                        Shared fixtures (36-team data, schedule, etc.)
│   ├── test_calibrate.py                  Calibration pipeline (fit, transform, save/load)
│   ├── test_cli.py
│   ├── test_counterfactual.py             Counterfactual analysis (what-if scenarios)
│   ├── test_display.py
│   ├── test_ensemble.py                   Ensemble signal blending
│   ├── test_explainability.py             Explainability metrics (SHAP, feature importance)
│   ├── test_fetcher.py
│   ├── test_fixture_validation.py
│   ├── test_knockout.py
│   ├── test_live.py                       Live mode: BSD fetch + played_matches injection
│   ├── test_monte_carlo.py
│   ├── test_orchestrator.py               Simulation mode orchestrator
│   ├── test_provider.py                   Fixture providers: Protocol conformance, schedule validation
│   ├── test_replay.py                     Replay mode: played_matches injection
│   ├── test_signal_registry.py            Signal Protocol, SignalOutput, SignalRegistry
│   ├── test_signals.py                    All signal implementations (RefinedElo, MarketOdds, etc.)
│   ├── test_simulation.py
│   ├── test_swiss_tiebreakers.py
│   ├── test_validation.py
│   └── test_validation_suite.py           Cross-season validation suite (Tier 1-4) with baseline comparison
│
├── tests/                                 ← Root-level shared tests (4 files, 132 tests)
│   ├── test_calibrated_pipeline.py        Calibrated validation pipeline integration
│   ├── test_calibration_pipeline.py       Temperature scaling, Brent's method, CalibrationPipeline
│   ├── test_confidence_intervals.py       Bootstrap CI, Wilson score, aggregate_mc_results
│   └── test_glicko.py                     Glicko-1 rating system (g(), expected_score, update, RatingSystem)
│
```

### Test file naming convention

All test files follow the `test_<module_name>.py` pattern. This is the standard pytest convention — no special configuration is needed.

### Test organization within files

Tests are grouped into classes for logical organization:

- `class TestExpectedGoals:` — unit tests for the `expected_goals()` function
- `class TestSimulateGroupMatches:` — tests for full group stage simulation
- `class TestComputeStandings:` — tests for standings computation and tiebreakers

Each test method has a descriptive name (e.g., `test_expected_goals_home_advantage`) and a docstring explaining the scenario and expected behavior.

### Conftest fixtures

Shared fixtures live in `conftest.py` files at each test directory level:

**`competitions/worldcup/tests/conftest.py`** provides:
- `sample_teams` — 5 test teams with Elo ratings
- `sample_bracket` — 7-match R16→QF→SF DAG structure (4 R16 + 2 QF + 1 SF)
- `sample_group_matches_results` — pre-built simulated Group A results
- `sample_groups` — minimal `groups.json`-like dict with Group A
- `sample_elo` — Elo ratings for the sample group teams

**`competitions/ucl/tests/conftest.py`** provides:
- `sample_36_teams` — all 36 UCL teams with realistic Elo ratings, pot assignments, and UEFA coefficients
- `sample_fixture_schedule` — the real 36-team, 8-matchday fixture schedule
- `sample_fixture_path` — real fixture schedule written to a temp JSON file path
- `sample_invalid_fixtures` — 3 fixture schedules with known validation failures
- `sample_elo_dict` — flat `{team_name: elo}` dict for all 36 teams
- `sample_elo_ratings` — Elo ratings for 4 sample teams
- `sample_match_results` — pre-built match results for 2 sample matches
- `sample_rng` — seeded `random.Random(42)` for deterministic tests
- `sample_uefa_coefficients` — UEFA club coefficients for 4 sample teams
- `sample_standings_results` — 36-team standings list sorted by Elo
- `sample_full_fixture_path` — real fixtures.json copied to a temp path for disk-based tests
- `sample_mc_output` — pre-formatted Monte Carlo output dict
- `sample_playoff_pairings`, `sample_bracket_rules` — playoff and bracket data loaded from competition data files
- `sample_knockout_elos`, `sample_tie_standings`, `sample_playoff_standings` — standings and Elo data for knockout and playoff tests
- `sample_playoff_winners`, `sample_stage_collectors`, `sample_knockout_stage_result`, `sample_result` — knockout and bracket fixtures including full `SimulationResult`
- `bsd_response_data` — BSD API snapshot response loaded from `tests/fixtures/bsd_response.json`
- `sample_36_teams_data`, `sample_cached_fixtures` — team dataclass structures and cache file for BSD provider tests
- `sample_match_data`, `sample_prediction_context`, `sample_match_with_odds_data` — match schema and prediction context for signal tests
- `sample_match_result_provider`, `empty_result_provider` — mock match result providers with pre-built or empty results
- `seasons_data`, `replay_matchdays` — multi-season synthetic data for validation suite and replay tests

Supports a `--live` CLI flag (registered via `pytest_addoption`) to optionally run live ClubElo API integration tests.

### Fixtures directories

**`competitions/worldcup/tests/fixtures/`** contains TSV data files for Elo rating testing:
- `eloratings_en_teams.tsv`
- `eloratings_world.tsv`

**`competitions/ucl/tests/fixtures/`** contains BSD API response data for offline provider tests:
- `bsd_response.json`

---

## Running Tests

### Run all tests (World Cup)

```bash
cd competitions/worldcup
pip install -r requirements.txt
pip install requests numpy
python -m pytest -v
```

### Run all tests (UCL)

```bash
cd competitions/ucl
pip install pytest pytest-cov requests numpy
python -m pytest -v
```

### Run all tests (football_core)

```bash
cd football_core
pip install pytest pytest-cov
python -m pytest -v
```

### Run all tests (root-level shared tests)

```bash
cd <project_root>
pip install pytest pytest-cov
python -m pytest tests/ -v
```

### Run a single test file

```bash
cd competitions/worldcup
python -m pytest tests/test_groups.py -v
```

### Run a single test class or method

```bash
python -m pytest tests/test_groups.py::TestExpectedGoals -v
python -m pytest tests/test_groups.py::TestExpectedGoals::test_expected_goals_home_advantage -v
```

### Run tests matching a keyword

```bash
python -m pytest -v -k "tiebreaker"
```

### Run with verbose output and stop on first failure

```bash
python -m pytest -x -v
```

### Run with live API tests

The live smoke test requires a `BSD_API_KEY` environment variable. See [Dealing with skipped tests](#dealing-with-skipped-tests-bsd_api_key) below.

```bash
$env:BSD_API_KEY = "your_api_key"
cd competitions/worldcup
python -m pytest tests/test_live_smoke.py -x -v
```

---

## Coverage Reporting

Code coverage is provided by **pytest-cov**. No minimum coverage thresholds are currently configured in CI or in any config file.

### Run with coverage (all tests)

```bash
cd competitions/worldcup
python -m pytest --cov=src --cov-report=term-missing
```

### Run with coverage (specific module)

```bash
cd competitions/worldcup
python -m pytest --cov=src.groups --cov-report=term-missing
```

### Generate HTML coverage report

```bash
cd competitions/worldcup
python -m pytest --cov=src --cov-report=html
# Open htmlcov/index.html in a browser
```

### Coverage scope

| Directory | Coverage scope |
|---|---|
| `competitions/worldcup/` | `--cov=src` (the competition's `src/` package) |
| `competitions/ucl/` | No CI coverage configured — run manually with `--cov=src` |
| `football_core/` | No CI coverage configured — run manually with `--cov=football_core` |
| `tests/` (root level) | No CI coverage configured — run manually with `--cov=football_core --cov=competitions.ucl.src` |

---

## CI Test Configuration

Only the **World Cup** competition has a CI pipeline. It is defined in:

`competitions/worldcup/.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: competitions/worldcup
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install requests numpy

      - name: Test with pytest
        run: |
          python -m pytest -v --cov=src --cov-report=term-missing
        env:
          BSD_API_KEY: ${{ secrets.BSD_API_KEY }}
```

Key points:
- **Trigger:** Push or pull request to `main`.
- **Matrix:** Python 3.10, 3.11, and 3.12 on `ubuntu-latest`.
- **Install:** Requirements + `requests` + `numpy` (runtime dependencies not in `requirements.txt`).
- **Command:** `python -m pytest -v --cov=src --cov-report=term-missing`.
- **BSD_API_KEY:** Pulled from GitHub Actions secrets. This means tests that require the key (like `test_live_smoke.py`) run in CI, not just locally.

No CI pipeline exists at the repository root level or for the UCL/football_core test suites.

---

## Dealing with Skipped Tests (BSD_API_KEY)

One test file requires a live API key:

**`competitions/worldcup/tests/test_live_smoke.py`**

This file makes real API calls to the BSD sports data API and verifies the full `--once` prediction pipeline. It is automatically skipped when `BSD_API_KEY` is not set:

```python
_LIVE_SKIP = pytest.mark.skipif(
    not os.environ.get("BSD_API_KEY"),
    reason="BSD_API_KEY not set — requires live API key",
)

@_LIVE_SKIP
def test_live_smoke_once():
    """Smoke test: --once fetches, simulates, prints valid 48-team predictions."""
    ...
```

When running locally without the key, the test suite reports **613 passed, 1 skipped** (614 collected, of which 1 is skipped and the remaining 613 execute). When running in CI (where `BSD_API_KEY` is available via secrets), the live smoke test executes as part of the full suite.

To run the live smoke test locally:

```bash
# PowerShell
$env:BSD_API_KEY = "your_api_key"
cd competitions/worldcup
python -m pytest tests/test_live_smoke.py -x -v

# Or inline
$env:BSD_API_KEY = "your_api_key" ; python -m pytest tests/test_live_smoke.py -x -v
```

You can obtain a free API key at `https://sports.bzzoiro.com/register/`.

---

## Adding New Tests

### Where to place new tests

| Code being tested | Test location |
|---|---|
| Cross-competition integration code (Glicko, calibration, CIs) | `<project_root>/tests/test_<module>.py` |
| Shared engine code in `football_core/` | `football_core/tests/test_<module>.py` |
| World Cup competition code in `competitions/worldcup/src/` | `competitions/worldcup/tests/test_<module>.py` |
| UCL competition code in `competitions/ucl/src/` | `competitions/ucl/tests/test_<module>.py` |

### Test file template

```python
"""Tests for the <module_name> module.

<Optional: one-line description of what's covered.>
"""

import pytest
from src.<module> import <function_to_test>


class TestFeatureName:
    """Tests for <function_or_feature>."""

    def test_normal_case(self):
        """<Scenario description — what this test verifies and why.>"""
        result = <function_to_test>(<args>)
        assert result == <expected_value>

    def test_edge_case(self):
        """<Edge case description.>"""
        result = <function_to_test>(<edge_args>)
        assert result is None  # or other appropriate assertion

    def test_reproducible_with_seed(self):
        """Random operations produce the same output with the same seed."""
        import random
        r1 = <function_to_test>(random.Random(42))
        r2 = <function_to_test>(random.Random(42))
        assert r1 == r2
```

### Guidelines

1. **Use descriptive test method names** that explain the scenario, e.g., `test_expected_goals_stronger_team` rather than `test_expected_goals_3`.
2. **Write docstrings** on every test method explaining what is being tested and what the expected outcome is.
3. **Prefer class-based organization** — group related tests into classes (`class TestComputeStandings:`) for readability and targeted execution.
4. **Use conftest fixtures** for shared data — define fixtures in `conftest.py` when data is reused across multiple test files. For file-local data, define helper methods on the test class.
5. **Seed random state** — any test that uses `random.Random` must pass a seeded instance for reproducibility. Never call module-level `random.random()` without a seed.
6. **Mock external APIs** — use `monkeypatch` to replace `requests.get` (or other HTTP calls) rather than making live requests. See `test_catboost.py` for examples.
7. **Use `tmp_path` for file I/O** — tests that read or write files should use pytest's built-in `tmp_path` fixture to avoid polluting real data directories. See `test_catboost.py` for patterns.
8. **Mark live API tests with `skipif`** — if a test requires a network call or an API key, guard it with `@pytest.mark.skipif(not os.environ.get("VARIABLE"), …)` so the suite still passes without the key.

### Existing test patterns to follow

- **Unit tests with injected RNG:** `test_groups.py` passes `random.Random(seed)` to functions instead of relying on global state.
- **API mocking:** `test_catboost.py` uses `monkeypatch.setattr("requests.get", mock_get)` to test HTTP error handling without real calls.
- **Integration tests:** `test_group_integration.py` runs the full groups pipeline (simulate → standings → third-place ranking → R32 resolution) with real data files.
- **Calibration pipeline tests:** `tests/test_calibration_pipeline.py` demonstrates temperature scaling, Brent's method, and `CalibrationPipeline` lifecycle testing.
- **Bootstrap CI tests:** `tests/test_confidence_intervals.py` shows how to test Monte Carlo aggregation with `compute_ci=True` and Wilson score intervals.
- **Glicko-1 rating system tests:** `tests/test_glicko.py` tests the full `RatingSystem` lifecycle with seeded determinism and symmetry checks.
- **Deterministic fixtures:** `conftest.py` provides pre-built data structures so tests don't recompute expensive simulation results.

---

## Known Test Issues

| Issue | File | Status |
|---|---|---|
| `test_live_smoke_once` requires `BSD_API_KEY` | `competitions/worldcup/tests/test_live_smoke.py` | Skipped by default |
| One flaky test in World Cup suite (nondeterministic) | World Cup tests | Intermittent |
| No tests for Euro 2024 | `competitions/euro/tests/` | Dormant — no test coverage when the competition is reactivated |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: src.xxx` | Tests are being run from the wrong directory | `cd competitions/worldcup` before running pytest |
| `pytest: command not found` | pytest not installed | `pip install -r requirements.txt` |
| `BSD_API_KEY` tests skipped unexpectedly | Environment variable not set | Set `BSD_API_KEY` or accept the skip |
| Flaky test failure in random-dependent tests | Unseeded `random` module | Ensure every test passes `random.Random(seed)` explicitly |
