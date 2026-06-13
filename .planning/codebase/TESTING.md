# Testing Patterns

**Analysis Date:** 2026-06-13

## Test Framework

**Runner:**
- `pytest` — added to `requirements.txt` after initial setup (Phase 0 / Phase 2)
- Config: No `pytest.ini` or `conftest.py` planned for MVP. Use default pytest discovery.
- Use `pip install pytest` alongside `requests` in the project's virtual environment.

**Run Commands:**
```bash
pytest                    # Run all tests
pytest -v                 # Run all tests with verbose output
pytest tests/             # Run all tests in tests/ directory
pytest tests/test_elo.py  # Run specific test file
pytest -x                 # Stop on first failure (useful during development)
pytest --tb=short         # Shorter traceback output
```

**Python version requirement:** 3.10+ (tested targets: Windows, macOS, Linux).

## Test File Organization

**Location:**
- All tests in a dedicated `tests/` directory at project root (co-location with `src/` and `data/`).
- No `__init__.py` necessary in `tests/` for pytest discovery.

**Naming:**
- Unit test files: `test_<module_name>.py` (e.g., `test_elo.py`, `test_state.py`)
- Integration test file: `integration_test.py` (following `Implementation_plan.md` convention)
- Test functions: `test_<function_name>_<scenario>()` (e.g., `test_update_ratings_higher_elo_wins`, `test_simulate_match_expected_distribution`)

**Structure:**
```
worldcup_predictor/
├── src/
│   ├── state.py
│   ├── elo.py
│   ├── simulator.py
│   ├── fetcher.py
│   ├── output.py
│   └── constants.py
├── tests/
│   ├── test_state.py          # Phase 1: JSON load/save roundtrip
│   ├── test_elo.py            # Phase 2: Elo update formulas
│   ├── test_simulator.py      # Phase 2: Match & tournament sim
│   └── integration_test.py    # Phase 6: End-to-end with mock API
├── main.py
└── requirements.txt
```

## Test Structure

**Suite Organization:**

Each test module follows a consistent pattern. Example from planned `test_elo.py`:

```python
"""Tests for elo.py — Elo rating update formulas."""

from src.elo import expected_score, update_ratings


def test_expected_score_equal_ratings():
    """Equal ratings should give 0.5 expected score."""
    assert expected_score(2000, 2000) == 0.5


def test_expected_score_higher_rating_favored():
    """Team with higher rating should have >0.5 expected score."""
    exp = expected_score(2100, 1850)
    assert exp > 0.5
    assert exp < 1.0
```

**Patterns:**
- **Setup:** Create input data inline within each test. No shared fixtures for MVP (data is small and simple).
- **No conftest.py fixtures** for MVP — tests are self-contained functions using explicit dict/data creation.
- **Teardown:** Not needed — tests don't modify real data files. Test state module uses temp files.
- **Assertion pattern:** Use plain `assert` statements. No `assertAlmostEqual` from unittest — use `assert abs(val - expected) < 0.001` for float tolerance.

## Mocking

**Framework:** `unittest.mock` (stdlib) — no `pytest-mock` or `mocker` fixture required. Use `from unittest.mock import patch, MagicMock`.

**Patterns:**

For `fetcher.py` integration tests (from `Implementation_plan.md` Phase 3), mock the external API:

```python
"""Tests for fetcher.py — API polling with mock responses."""

from unittest.mock import patch
from src.fetcher import fetch_new_results

MOCK_API_RESPONSE = {
    "matches": [
        {
            "id": 123456,
            "status": "FINISHED",
            "homeTeam": {"name": "Argentina"},
            "awayTeam": {"name": "Nigeria"},
            "score": {"fullTime": {"home": 2, "away": 1}},
            "winner": "HOME_TEAM"
        }
    ]
}


@patch("src.fetcher.requests.get")
def test_fetch_new_results_returns_new_matches(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = MOCK_API_RESPONSE

    results = fetch_new_results(last_known_ids=set())

    assert len(results) == 1
    assert results[0]["winner"] == "Argentina"


@patch("src.fetcher.requests.get")
def test_fetch_new_results_skips_known_matches(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = MOCK_API_RESPONSE

    results = fetch_new_results(last_known_ids={"R16_1"})

    assert len(results) == 0


@patch("src.fetcher.requests.get")
def test_fetch_new_results_handles_api_error(mock_get):
    mock_get.side_effect = ConnectionError("API unreachable")

    # Should not crash, return empty list
    results = fetch_new_results(last_known_ids=set())
    assert results == []
```

For `simulator.py`, use `random.seed()` for deterministic tests:

```python
def test_run_single_tournament_seeded():
    """With a fixed seed, tournament outcome is deterministic."""
    import random
    random.seed(42)

    champion = run_single_tournament(test_elos, test_bracket, played_set=set())
    assert isinstance(champion, str)
    assert champion in test_elos
```

**What to Mock:**
- External HTTP requests (`requests.get`) — never call the real API in unit tests.
- The `random` module may be controlled via `random.seed()` rather than mocked (simpler and more reliable).
- File I/O in `state.py` tests — use `tempfile` for real I/O (integration-style) or mock `json.load`/`json.dump` for unit-isolated tests.

**What NOT to Mock:**
- Elo computation — test the real math against known examples.
- Match simulation logic — test real randomness distribution with seed control.
- Bracket traversal — test with real nested bracket dicts.

## Fixtures and Factories

**Test Data:**

Test data is defined inline in each test file as module-level constants or helper functions. No separate `tests/fixtures/` directory for MVP.

```python
# In test_simulator.py — module-level test fixtures
TEST_ELOS: dict[str, float] = {
    "Argentina": 2100.0,
    "Nigeria": 1850.0,
    "France": 2075.0,
    "Denmark": 1900.0,
}

TEST_BRACKET: dict = {
    "round_of_16": [
        {"match_id": "R16_1", "team_a": "Argentina", "team_b": "Nigeria", "winner": None},
        {"match_id": "R16_2", "team_a": "France", "team_b": "Denmark", "winner": None},
    ],
    "quarterfinals": [
        {"match_id": "QF_1", "source_matches": ["R16_1", "R16_2"], "winner": None},
    ],
    "semifinals": [],
    "final": {"match_id": "FINAL", "source_matches": ["QF_1"], "winner": None},
}
```

For state persistence tests, use `tempfile.TemporaryDirectory`:

```python
import json
import os
import tempfile
from src.state import save_teams, load_teams


def test_teams_save_and_load_roundtrip():
    """Loading saved data returns identical structure."""
    data = {"Argentina": {"elo": 2112, "eliminated": False}}
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "teams.json")
        save_teams(data, filepath)  # may need to inject path
        loaded = load_teams(filepath)
        assert loaded == data
```

**Location:**
- Test data lives inside each `tests/test_*.py` file as module-level constants.
- No shared fixture files.

## Coverage

**Requirements:** None enforced for MVP. The plan focuses on targeted high-value tests rather than coverage percentages.

**Planned test coverage targets by module (derived from `TRD.md` section 8 and `Implementation_plan.md` section 6):**

| Module | Coverage Target | Key Scenarios |
|--------|----------------|---------------|
| `elo.py` | ~95%+ | Expected score, update ratings (higher wins, lower wins, equal), draw (future), K-factor variations |
| `simulator.py` | ~85%+ | Match simulation (seed control, distribution), single tournament, Monte Carlo sum ≈ 1.0, played-match skipping |
| `state.py` | ~90%+ | Load/save roundtrip, atomic writes, missing file handling, corrupt JSON handling |
| `fetcher.py` | ~80%+ | New matches returned, known matches filtered, API error handling, retry logic, malformed JSON |
| `output.py` | Not covered | Manual visual inspection per `Implementation_plan.md` Phase 6 |
| `main.py` | Integration only | End-to-end flow via `integration_test.py` |

**View Coverage:**
```bash
pip install pytest-cov
pytest --cov=src
```

(Adding `pytest-cov` is a Phase 6/post-MVP addition — not in the MVP requirements.)

## Test Types

**Unit Tests:**
- **Scope:** Individual functions in isolation. Test the Elo formula, match simulation randomness, bracket traversal logic.
- **Approach:** Pure function tests. Input → expected output.
- **Coverage by phase:**
  - Phase 1 — `test_state.py`: verify JSON load/save roundtrips (`Implementation_plan.md` Phase 1 checklist: "Load, modify, save, reload – values match")
  - Phase 2 — `test_elo.py`: compute expected scores and rating changes by hand, compare to code output (`Implementation_plan.md` Phase 2 checklist)
  - Phase 2 — `test_simulator.py`: verify Monte Carlo probabilities sum to 1.0 (within 0.001), verify played matches are never re-simulated

**Integration Tests:**
- **Scope:** Module interactions — fetcher + state + elo + simulator working together.
- **Approach:** Mock the external API to return a sequence of fake finished matches, then verify Elo changes and probability updates.
- **Key file:** `tests/integration_test.py` — runs a controlled scenario (e.g., R16 matches one by one) and checks:
  - Elo ratings change correctly after each mock match
  - Probabilities evolve in the expected direction (winner's chances increase)
  - Already-processed matches are never re-processed after script restart
  - State persists across simulated restarts (`Implementation_plan.md` Phase 5 crash recovery test)

**E2E Tests:**
- **Framework:** Manual / script-based. No automated E2E framework.
- **Approach:**
  - Run `python main.py` for 1–2 hours with real API (using historical/friendly matches).
  - Verify live output shows correct timestamps, match detection, and probability updates.
  - Test graceful shutdown with Ctrl+C — verify `played.json` has correct state afterward.
  - Test API outage by disconnecting internet — script must not crash (`Implementation_plan.md` Phase 5: "Script survives simulated API outages").

**Persistence Tests:**
- Approach: Kill script mid-run, restart, verify `played.json` contains last recorded match and Elo ratings are persisted. (`TRD.md` section 8 table row 4).

## Common Patterns

**Async Testing:**
- Not applicable. The MVP is fully synchronous and single-threaded (`Appflow.md` section 8). No `asyncio`, no threading.

**Error Testing:**

```python
import pytest
from src.elo import update_ratings


def test_update_ratings_winner_not_in_elos():
    """Should raise KeyError or handle gracefully when winner team not in elos dict."""
    elos = {"TeamA": 2000.0, "TeamB": 1800.0}
    with pytest.raises(KeyError):
        update_ratings("TeamA", "TeamB", "TeamC", elos)
```

```python
from unittest.mock import patch
from src.fetcher import fetch_new_results


@patch("src.fetcher.requests.get")
def test_fetch_retry_on_timeout(mock_get):
    """Should retry up to 3 times on timeout, then return empty."""
    from requests.exceptions import Timeout
    mock_get.side_effect = Timeout()

    results = fetch_new_results(last_known_ids=set())

    assert results == []          # Graceful failure
    assert mock_get.call_count <= 3  # Retry limit respected
```

**Seed Control for Reproducibility:**

```python
def test_monte_carlo_deterministic_with_seed():
    """Same seed produces identical probabilities."""
    import random
    random.seed(42)
    probs_a = run_monte_carlo(TEST_ELOS, TEST_BRACKET, set(), n=10000)

    random.seed(42)
    probs_b = run_monte_carlo(TEST_ELOS, TEST_BRACKET, set(), n=10000)

    assert probs_a == probs_b
```

**Float Tolerance:**

```python
def test_monte_carlo_probabilities_sum_to_one():
    """Probabilities should sum to 1.0 within floating-point tolerance."""
    probs = run_monte_carlo(TEST_ELOS, TEST_BRACKET, set(), n=50000)
    total = sum(probs.values())
    assert abs(total - 1.0) < 0.001  # Tolerance per TRD section 6
```

## Testing Checklist Per Phase (from `Implementation_plan.md` section 6)

| Phase | Test | Verification |
|-------|------|--------------|
| 1 | JSON load/save preserves data | Load, modify, save, reload — values match |
| 2 | Elo update matches known examples (e.g., from chess) | Compute by hand, compare code output |
| 2 | Monte Carlo probabilities sum to 1.0 (within 0.001) | Run `sum(probs.values())` |
| 3 | API returns at least one finished match (or mock) | Print response; check parsing |
| 3 | New match filtering (no duplicates after restart) | Run, stop, re-run — same match not reprocessed |
| 4 | Colored output appears (or fallback plain text) | Visual inspection |
| 4 | Ctrl+C shutdown saves state | Compare `played.json` before and after kill |
| 5 | API failure does not crash script | Disconnect internet, script continues |
| 6 | End-to-end: simulate R16 matches one by one, probabilities evolve | Mock API returns sequential results, check deltas |

## Risk Mitigation — Testing

| Risk | Mitigation in Tests |
|------|---------------------|
| Elo formula incorrect | Unit tests with hand-computed examples (chess-known cases) |
| Simulation too slow (>5s target) | `test_simulator_performance` — measure and fail if exceeds threshold |
| API data format changes | Tests with mocked responses exercise parsing; fails early if format breaks |
| State file corruption on crash | Atomic write tests + crash-recovery integration test |
| Windows ANSI color issues | Test with `--no-color` flag; verify fallback symbols work (`▲`, `▼`, `⚠`) |

---

*Testing analysis: 2026-06-13*
