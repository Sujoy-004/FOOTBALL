# Testing Patterns

**Analysis Date:** 2026-06-27

## Test Framework

**Runner:**
- **pytest** (>=9.0)
- Config: No `pytest.ini`, `pyproject.toml`, `setup.cfg`, or `conftest.py` at project root — all config and fixtures are test-directory-local
- Requirements: `pytest>=9.0`, `pytest-cov>=7.1` in `competitions/worldcup/requirements.txt`
- Python: No `.python-version` file detected

**Assertion Library:**
- Python built-in `assert` statements
- `pytest.raises` for exception testing
- No third-party assertion library (no `hamcrest`, `assertpy`, etc.)

**Run Commands:**
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov-report=term

# Run specific test file
pytest tests/test_elo.py

# Run specific test class
pytest tests/test_groups.py::TestTiebreaker2Team

# Run specific test
pytest tests/test_elo.py::TestUpdateRatings::test_standard_update

# Watch mode (if pytest-watch or pytest-xdist installed separately)
# No watch-mode configuration detected
```

## Test File Organization

**Location:**
- All tests co-located in `competitions/worldcup/tests/` — not co-located with source
- Source lives in `competitions/worldcup/src/` and `football_core/`
- One shared conftest at `competitions/worldcup/tests/conftest.py`

**File count:** 29 test files in `competitions/worldcup/tests/`

**Naming:**
- Files named `test_<module>.py` matching the module under test:
  - `src/elo.py` → `test_elo.py`
  - `src/groups.py` → `test_groups.py`
  - `src/state.py` → `test_state.py`
  - `src/fetcher.py` → `test_fetcher.py`
  - `src/knockout.py` → `test_knockout.py`

**Structure:**
```
competitions/worldcup/tests/
├── conftest.py               # 5 shared fixtures
├── test_blender.py           # 43 tests — Platt calibration, blending, Brier
├── test_catboost.py          # 28 tests — CatBoost prediction parsing
├── test_cli.py               # 17 tests — CLI arg parsing
├── test_config.py            # 6 tests — league ID config
├── test_elo.py               # 27 tests — Elo rating engine
├── test_elo_sync.py          # 47 tests — Elo sync pipeline
├── test_enrichment.py        # 13 tests — match enrichment
├── test_evaluation.py        # 44 tests — Brier, log-loss, calibration
├── test_fetcher.py           # 20 tests — BSD API fetching
├── test_form.py              # 23 tests — form residual signal
├── test_governance.py        # 47 tests — governance, drift, backtesting
├── test_group_integration.py # 17 tests — group match pipeline
├── test_groups.py            # 45 tests — group simulation + tiebreakers
├── test_integration.py       # 1 test — E2E roundtrip
├── test_knockout.py          # 11 tests — knockout simulation
├── test_lineup.py            # 23 tests — lineup strength signal
├── test_live_smoke.py        # 3 tests — live smoke (2 skipped by default)
├── test_main_loop.py         # 36 tests — main loop iterations
├── test_migration.py         # 13 tests — data migration
├── test_odds.py              # 20 tests — market odds pipeline
├── test_output.py            # 63 tests — terminal output formatting
├── test_scaffold.py          # 8 tests — project scaffold verification
└── test_state.py             # 58 tests — state persistence + validation
```

**Test count:** 614 tests collected, 4 skipped (under conditional `skipif` markers), 610 active

## Test Structure

**Suite Organization:**
- Classes group related tests: `class TestExpectedScore`, `class TestUpdateRatings`, `class TestDrawBackfill`
- Module-level functions used for simpler standalone tests: `test_valid_bracket_passes()`, `test_duplicate_match_id()`
- Mix of methods inside classes and standalone functions — both patterns used

```python
# Class-based grouping (preferred for complex modules)
class TestUpdateRatings:
    """Tests for the update_ratings function."""

    def test_standard_update(self):
        """Argentina(2100) beats Nigeria(1800) → Arg ~2109, Nig ~1791."""
        elos = {"Argentina": 2100, "Nigeria": 1800, "France": 2050}
        result = update_ratings("Argentina", "Nigeria", "Argentina", elos, K=60)
        assert round(result["Argentina"], 0) == 2109
        assert round(result["Nigeria"], 0) == 1791
        assert "France" not in result
```

**Patterns:**
- **Setup pattern:** Fixtures via `conftest.py` (global) or `@pytest.fixture` methods inside test classes (local)
- **Teardown:** Not explicitly used — filesystem isolation via `tmp_path` replaces cleanup
- **Assertion pattern:** `assert <condition>` with optional error message string
- **Exception testing:** `with pytest.raises(ValueError, match="..."):`
- **Docstrings:** Every test method has a docstring describing what is tested and expected

```python
def test_compute_standings_basic(self, sample_group_matches_results, sample_elo):
    """Basic standings: Mexico (7pts,+4) > South Korea (7pts,+3) on GD."""
    s = compute_standings(sample_group_matches_results, sample_elo)["A"]
    assert len(s) == 4
    assert [t["team"] for t in s] == [
        "Mexico", "South Korea", "South Africa", "Czech Republic"
    ]
```

## Fixtures and Test Data

**conftest.py** (`competitions/worldcup/tests/conftest.py`):
- 5 reusable fixtures shared across test files:
  - `sample_teams` — 5 teams with Elo ratings
  - `sample_bracket` — 7-match R16→QF→SF DAG structure
  - `sample_played` — empty played matches dict
  - `sample_group_matches_results` — 6-match Group A with deterministic scores
  - `sample_groups` — minimal groups.json with Group A (4 teams, 6 matches)
  - `sample_elo` — Elo ratings for the 4 group teams

**Per-test-file fixtures:**
- Test files define their own additional fixtures when needed:
  - `test_knockout.py`: `full_data` (loads production JSON), `small_teams`
  - `test_fetcher.py`: Module-level constants `SAMPLE_MATCHES`, `SAMPLE_ALIASES`, `ENRICHED_MATCH`
  - `test_groups.py`: Helper methods like `_make_group()`, `_make_valid_groups()`

**Test data location:**
- Production data: `competitions/worldcup/data/` (teams.json, groups.json, bracket.json, annex_c.json, played.json, team_aliases.json)
- Test fixtures: `competitions/worldcup/tests/fixtures/` (eloratings_world.tsv)

**tmp_path usage:**
- All file I/O tests use pytest's built-in `tmp_path` fixture to avoid modifying real data:
  ```python
  def test_teams_roundtrip(tmp_path):
      data = {"Argentina": {"elo": 2100}, "France": {"elo": 2050}}
      save_teams(data, data_dir=tmp_path)
      loaded = load_teams(data_dir=tmp_path)
      assert loaded == data
  ```

## Mocking

**Framework:** Two patterns used interchangeably:

1. **`monkeypatch`** (pytest built-in) — preferred for simpler cases:
   ```python
   def test_fetch_success(monkeypatch):
       def mock_get(url, **kwargs):
           return MockResponse(200, {"results": SAMPLE_MATCHES})
       monkeypatch.setattr(requests, "get", mock_get)
   ```
   (`competitions/worldcup/tests/test_fetcher.py:77-83`)

2. **`unittest.mock.patch`** — used for more complex scenarios with multiple mocks:
   ```python
   @patch("src.elo_sync.state.save_teams")
   @patch("src.elo_sync.state.save_eloratings_cache")
   @patch("src.elo_sync.state.save_elo_update_log")
   @patch("src.elo_sync.state.load_elo_update_log")
   @patch("src.elo_sync.fetch_eloratings_tsv")
   def test_sync_with_mocked_fetch(
       self, mock_fetch, mock_load_log, mock_save_log,
       mock_save_cache, mock_save_teams,
   ):
   ```
   (`competitions/worldcup/tests/test_elo_sync.py:445-449`)

**Custom Mock Classes:**
- `MockResponse` in `test_fetcher.py` — full mock with `.json()`, `.ok`, `.raise_for_status()`
- `BadJSONResponse` in `test_fetcher.py` — subclass that raises `json.JSONDecodeError`
- Anonymous lambda mocks for simple cases: `monkeypatch.setattr("main.state.save_teams", lambda *a, **kw: None)`

**What to Mock:**
- **External network calls** (requests.get to BSD API, eloratings.net)
- **State persistence** that would write to production data files
- **File I/O** via tmp_path and monkeypatch on save functions
- **Random number generators** with seeded `random.Random` instances

**What NOT to Mock:**
- **Core computation functions** (elo rating math, group simulation, tiebreaker logic) are tested directly without mocking
- **Data validation** functions tested against real data structures
- **Fixtures use real data** where possible (production JSON files for integration tests)

## Fixtures and Factories

**Test Data:**
```python
# Helper factory pattern (test_groups.py)
def _make_group(self, teams, scores, card_data=None):
    matchups = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    results = {}
    for i, (m, (sa, sb)) in enumerate(zip(matchups, scores)):
        ta, tb = teams[m[0]], teams[m[1]]
        cards = card_data.get((ta, tb), (0, 0, 0, 0)) if card_data else (0, 0, 0, 0)
        results[f"M{i+1}"] = {
            "team_a": ta, "team_b": tb,
            "score_a": sa, "score_b": sb,
            "winner": ta if sa > sb else (tb if sb > sa else None),
            "yellow_cards_a": cards[0], "red_cards_a": cards[1],
            "yellow_cards_b": cards[2], "red_cards_b": cards[3],
        }
    return results
```

**TSV fixture builder (test_elo_sync.py):**
```python
def _make_tsv_row(code: str, rating: float, cols: int = 33) -> str:
    parts = [f"VAL{i}" if i not in (2, 3) else (code if i == 2 else str(rating))
             for i in range(cols)]
    return "\t".join(parts)

def _make_tsv(rows: list[tuple[str, float]]) -> str:
    return "\n".join(_make_tsv_row(code, rating) for code, rating in rows)
```

## Coverage

**Requirements:**
- `pytest-cov>=7.1` listed in `requirements.txt`
- No coverage configuration file (`.coveragerc`, `coverage.ini`, or `pyproject.toml` section)
- No coverage threshold enforced in CI

**View Coverage:**
```bash
pytest --cov=src --cov-report=term
pytest --cov=src --cov-report=html
```

## Subprocess Testing

**Pattern for testing main.py entry point:**
- Tests invoke `main.py` in a subprocess with overridden `DATA_DIR` and mocked `requests.get`:
  ```python
  def test_main_runs_successfully(tmp_path):
      runner_code = (
          f"import os, sys\n"
          f"os.environ['POLL_INTERVAL'] = '1'\n"
          f"os.environ['BSD_API_KEY'] = 'test_dummy_key'\n"
          f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
          # ... sys.path and DATA_DIR overrides ...
          f"import main\n"
          f"main.main()\n"
      )
      result = subprocess.run(
          [sys.executable, "-u", "-c", runner_code],
          capture_output=True, text=True, timeout=10,
      )
  ```
  (`competitions/worldcup/tests/test_state.py:171-215`)

- Subprocess tests validate stdout/stderr output and exit codes

## CI Configuration

- **No CI pipeline detected** — no `.github/workflows/`, no `Jenkinsfile`, no `.circleci/config.yml`
- Tests are designed to be run locally with `pytest`

## Test Types

**Unit Tests:**
- Scope: Individual functions in isolation — Elo math, group standings computation, tiebreaker logic, CLI parsing, mock responses
- Approach: Direct function calls with controlled inputs, assert on exact return values
- Proportion: ~80% of test suite

**Integration Tests:**
- Scope: Multi-step flows — Elo persistence roundtrip (`test_integration.py`), full simulation with production data (`test_knockout.py::TestRunFullSimulation`), group match pipeline with played groups persistence
- Approach: Use real production data + `tmp_path` for file isolation
- Proportion: ~15% of test suite

**E2E / Smoke Tests:**
- Scope: Main entry point (`main.main()`) invoked via subprocess
- `test_live_smoke.py`: 3 tests (2 conditionally skipped when `BSD_API_KEY` is not set)
- `test_state.py::test_main_runs_successfully`: Checks "Loaded", "bracket matches", "played matches" in stdout

**Benchmark Tests:**
- `competitions/worldcup/benchmarks/benchmark_groups.py` — standalone benchmark (not pytest)
- `competitions/worldcup/scripts/benchmark_simulation.py` — simulation benchmark script

## Skipped Tests

4 tests conditionally skipped using `@pytest.mark.skipif`:
- `test_form.py::TestFormSignal::test_unresolved_bracket_slot_skipped`
- `test_group_integration.py::TestProcessGroupMatches::test_process_group_matches_null_group_name_skipped`
- `test_lineup.py::TestLineupComputeSignal::test_unresolved_bracket_slot_skipped`
- `test_main_loop.py::TestHistoricalCatchUp::test_unmatchable_team_skipped`

Live smoke tests are conditionally skipped when `BSD_API_KEY` environment variable is not set.

## Common Patterns

**Error Testing:**
```python
# Standard exception testing with match regex
def test_duplicate_match_id():
    bad = [ ... ]
    with pytest.raises(ValueError, match="Duplicate match_id"):
        validate_bracket(bad)

# SystemExit for argparse tests
def test_seed_rejects_non_int(self):
    try:
        _parse_args(["--seed", "abc"])
        assert False, "Should have raised SystemExit"
    except SystemExit:
        pass
```

**Immutability Testing:**
```python
def test_does_not_mutate_input(self):
    elos = {"A": 2000, "B": 1900}
    before_a = elos["A"]
    update_ratings("A", "B", "A", elos, K=60)
    assert elos["A"] == before_a  # unchanged
```

**Determinism Testing:**
```python
def test_simulate_group_matches_reproducible(self):
    r1 = simulate_group_matches(groups, teams, elo, random.Random(42), ...)
    r2 = simulate_group_matches(groups, teams, elo, random.Random(42), ...)
    assert r1 == r2, "Same seed should produce identical results"
```

**Edge Case Testing (boundary values):**
```python
def test_edge_tolerance_boundary(self):
    """Drift exactly 10 → NOT ignored (tolerance is <10, so ==10 triggers blend)."""
    teams = {"TestTeam": {"elo": 1800.0}}
    corrections = apply_graduated_correction(teams, {"TestTeam": 1810.0})
    assert len(corrections) == 1
```

**Round-trip Persistence Testing:**
```python
def test_teams_roundtrip(tmp_path):
    data = {"Argentina": {"elo": 2100}, "France": {"elo": 2050}}
    save_teams(data, data_dir=tmp_path)
    loaded = load_teams(data_dir=tmp_path)
    assert loaded == data
```

**Idempotency Testing:**
```python
def test_migrate_idempotent(self, tmp_path):
    save_prediction_history([entry], data_dir=tmp_path)
    n = migrate_prediction_history(data_dir=tmp_path)
    assert n == 0, "Should not migrate already-compound entries"
```

---

*Testing analysis: 2026-06-27*
