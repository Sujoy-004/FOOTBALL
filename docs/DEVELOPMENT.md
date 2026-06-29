<!-- generated-by: gsd-doc-writer -->
# Development Guide

This document covers how to set up a development environment, navigate the project
structure, run tests, add a new competition, and understand the shared library for
the FOOTBALL Monte Carlo Prediction Engine.

---

## Table of Contents

- [Development Environment Setup](#development-environment-setup)
- [Project Structure](#project-structure)
- [Understanding the Shared Library](#understanding-the-shared-library)
- [Running Tests](#running-tests)
- [Adding a New Competition](#adding-a-new-competition)
- [Code Style Guidelines](#code-style-guidelines)
- [CI Pipeline](#ci-pipeline)

---

## Development Environment Setup

### Prerequisites

- **Python:** 3.10, 3.11, or 3.12
- **Git**

### Clone and Install

The project is source-based — there is no `pyproject.toml` or `setup.py`. Python
modules are resolved at runtime via `sys.path` manipulation in each competition's
`__init__.py`. To get started:

```bash
git clone <repo-url>
cd FOOTBALL
```

For **World Cup development**, install the required dependencies:

```bash
pip install -r competitions/worldcup/requirements.txt
pip install requests numpy
```

For **UCL development**, install the same base dependencies (there is no separate
requirements file for UCL):

```bash
pip install requests numpy pytest pytest-cov
```

For **Euro development**, same dependencies as World Cup.

### API Key (optional for development)

Live match data, market odds, and CatBoost predictions require a BSD API key.
The engine runs in Elo-only mode without one.

```bash
cp competitions/worldcup/.env.example competitions/worldcup/.env
# Edit .env and set BSD_API_KEY=your_key_here
```

Get a free key at <https://sports.bzzoiro.com/register/>.

### sys.path Mechanism

Each competition package adds the repository root to `sys.path` on import,
which makes `football_core` importable. This is done in the package's
`__init__.py`:

```python
"""Example from competitions/worldcup/__init__.py"""
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
```

> **Note:** All competition code imports `football_core` directly (e.g.,
> `from football_core import elo`). There is no editable install or pip
> package for the shared library.

---

## Project Structure

```
FOOTBALL/
├── football_core/                   ← Shared engine library (imported by all competitions)
│   ├── __init__.py
│   ├── constants.py                 K-factor, Elo defaults, Poisson config, timeouts
│   ├── elo.py                       Expected score, K-factor, rating updates
│   ├── elo_sync.py                  Fetch/parse Elo ratings from eloratings.net
│   ├── fetcher.py                   BSD API match fetching, dedup, normalization
│   ├── groups.py                    Poisson match simulation, tiebreaker chain, round-robin
│   ├── knockout.py                  Generic round-map building, match simulation, blended probs
│   ├── evaluation.py                Brier score, log loss, calibration, ECE
│   ├── state.py                     JSON persistence with atomic writes, caching helpers
│   ├── math_utils.py                Sigmoid and other small math helpers
│   ├── predictors/
│   │   ├── odds.py                  Market odds ingestion and vig removal
│   │   └── catboost.py              CatBoost ML prediction ingestion from BSD API
│   └── tests/
│       └── test_evaluation.py       Core evaluation metric tests
│
├── competitions/
│   ├── worldcup/                    ← World Cup 2026 predictor (active — continuous polling)
│   │   ├── __init__.py              sys.path setup
│   │   ├── main.py                  CLI entry point, 60s polling loop, orchestration (1568 lines)
│   │   ├── config.json              League ID: 27
│   │   ├── .env.example             BSD_API_KEY template
│   │   ├── requirements.txt         pytest, pytest-cov, python-dotenv
│   │   ├── src/                     World Cup-specific modules
│   │   │   ├── __init__.py
│   │   │   ├── constants.py         WC-specific constants
│   │   │   ├── elo.py, elo_sync.py  Extends football_core Elo for WC
│   │   │   ├── groups.py            WC group stage (48 teams, 12 groups, annex C)
│   │   │   ├── knockout.py          WC knockout bracket resolution
│   │   │   ├── fetcher.py           WC-specific BSD API fetching
│   │   │   ├── state.py             WC-specific state persistence + versioning
│   │   │   ├── evaluation.py        WC-specific evaluation/calibration
│   │   │   ├── output.py            ANSI terminal display (952 lines)
│   │   │   ├── blender.py           Platt scaling, Brier-weighted blending
│   │   │   ├── governance.py        Version tracking, drift detection (573 lines)
│   │   │   ├── enrichment.py        Match enrichment pipeline
│   │   │   ├── math_utils.py        Sigmoid helper
│   │   │   └── predictors/          Competition-specific predictor wrappers
│   │   │       ├── odds.py
│   │   │       ├── catboost.py
│   │   │       ├── form.py          Form signal computation
│   │   │       └── lineup.py        Lineup signal computation
│   │   ├── tests/                   26 test files, 613 tests
│   │   │   ├── conftest.py          Shared fixtures (sample_teams, sample_bracket, etc.)
│   │   │   └── test_*.py            Unit + integration tests
│   │   ├── scripts/                 Benchmark scripts
│   │   ├── benchmarks/              Performance benchmarks
│   │   ├── data/                    Runtime state (gitignored) + team/group config
│   │   └── .github/workflows/       CI pipeline
│   │
│   ├── ucl/                         ← UEFA Champions League 2025/26 predictor (active — single-run)
│   │   ├── __init__.py              sys.path setup, exports SimulationResult + main
│   │   ├── main.py                  CLI entry point, Monte Carlo orchestration (313 lines)
│   │   ├── result.py                SimulationResult dataclass (display contract)
│   │   ├── display.py               Formatted terminal output (309 lines)
│   │   ├── src/                     UCL-specific simulation modules
│   │   │   ├── __init__.py          Public API: simulation, knockout, groups, elo_fetcher
│   │   │   ├── simulation.py        Monte Carlo engine, league phase simulation
│   │   │   ├── knockout.py          Swiss playoff + knockout bracket simulation
│   │   │   ├── groups.py            Swiss-system standings, matchup lambdas
│   │   │   ├── fetcher.py           Match fetching for UCL
│   │   │   ├── elo_fetcher.py       ClubElo data fetching
│   │   │   └── validation.py        Cross-check predictions vs real results
│   │   ├── tests/                   10 test files, 149 tests
│   │   │   ├── conftest.py          Team pots, Elo ratings, fixture data (908 lines)
│   │   │   └── test_*.py            Unit + integration tests
│   │   ├── benchmarks/              Performance benchmarks + results
│   │   └── data/                    Fixture data, bracket rules, team aliases, coefficients
│   │
│   └── euro/                        ← Euro 2024 predictor (dormant — continuous polling)
│       ├── __init__.py              sys.path setup (also adds worldcup/src to path)
│       ├── main.py                  CLI entry point, polling loop (262 lines)
│       ├── config.py                Euro-specific configuration
│       ├── display.py               Terminal display
│       ├── simulation.py            Match + knockout simulation
│       └── data/                    Teams, groups, bracket data
│
└── docs/                            Project documentation
```

### Key Architectural Patterns

- **Continuous polling (World Cup, Euro):** CLI enters a 60-second loop that
  fetches live matches → updates Elo → refreshes signal caches → runs Monte Carlo
  simulation → prints probability tables. Supports `--once` for single-cycle mode.
- **Single-run Monte Carlo (UCL):** Fetches all data upfront, runs N iterations of
  league-phase + knockout simulation, prints a full result summary, optionally
  exports to JSON. Uses `-n` for iteration count and `-s` for seed.
- **Simpson's paradox avoidance:** The `result.py` / `display.py` separation in UCL
  ensures the display layer never imports simulation internals — only the result
  contract dataclass.

---

## Understanding the Shared Library

`football_core/` is a flat Python package that all three competitions import via
`sys.path`. It contains no competition-specific logic. Modules are thin wrappers
around pure math and data pipeline functions — avoid adding competition-specific
logic here.

| Module | File | Purpose | Key Functions |
|---|---|---|---|
| **constants** | `constants.py` | Shared configuration constants | `K_FACTOR`, `DEFAULT_ELO`, `MAX_EXPECTED_GOALS`, `HOME_ADVANTAGE_MULTIPLIER`, `POISSON_TABLE_BITS`, `API_TIMEOUT`, `ELORATINGS_TSV_URL` |
| **elo** | `elo.py` | Elo rating engine | `expected_score()`, `update_ratings()`, `compute_k_factor()` |
| **elo_sync** | `elo_sync.py` | Sync ratings from eloratings.net | `fetch_eloratings_tsv()`, `parse_eloratings_tsv()`, `validate_ratings()`, `correct_ratings()` |
| **fetcher** | `fetcher.py` | BSD API match fetch + processing | `fetch_raw_matches()`, `process_group_matches()`, `process_matches()`, `find_bracket_match()`, `find_group_match()`, `normalize_team()` |
| **groups** | `groups.py` | Poisson group simulation | `expected_goals()`, `simulate_group()`, `simulate_group_stage()`, `resolve_group_standings()` |
| **knockout** | `knockout.py` | Generic knockout primitives | `_build_round_map()`, `_get_blended_prob()`, `simulate_knockout_match()` |
| **evaluation** | `evaluation.py` | Prediction accuracy metrics | `brier_score()`, `log_loss()`, `compute_metrics()`, `calibration_curve()`, `expected_calibration_error()` |
| **state** | `state.py` | JSON persistence layer | `_atomic_write_json()`, `load_json()`, `save_json()`, bracket validation, cache helpers |
| **math_utils** | `math_utils.py` | Small math helpers | `sigmoid()` |
| **predictors.odds** | `predictors/odds.py` | Market odds ingestion | `remove_vig()`, TTL-based cache read/write |
| **predictors.catboost** | `predictors/catboost.py` | ML prediction ingestion | BSD API CatBoost probability fetching, TTL caching |

### When to Add to `football_core` vs a Competition

Add to `football_core/` when:
- The logic is generic across all tournament formats (group stage round-robin,
  knockout bracket, Elo math, persistence).
- It is a pure function with no competition-specific configuration.

Add to `competitions/<name>/src/` when:
- The logic is specific to a competition format (Swiss-system for UCL, annex C
  routing for World Cup, WC-specific display layout).
- It imports competition-specific constants or data files.

---

## Running Tests

Each competition has its own test suite under `competitions/<name>/tests/`.
The core library has a small test suite under `football_core/tests/`.

### Core Library Tests

```bash
# From the repository root
python -m pytest football_core/tests/ -v
```

### World Cup Tests (613 tests)

```bash
# From the repository root
python -m pytest competitions/worldcup/tests/ -v

# Run with coverage
python -m pytest competitions/worldcup/tests/ --cov=competitions/worldcup/src --cov-report=term-missing

# Run a specific test file
python -m pytest competitions/worldcup/tests/test_elo.py -v

# Run a specific test by name
python -m pytest competitions/worldcup/tests/ -k "test_expected_score"

# World Cup CI is the only fully configured CI pipeline (see CI Pipeline section)
```

### UCL Tests (149 tests)

```bash
# From the repository root
python -m pytest competitions/ucl/tests/ -v

# Run with coverage
python -m pytest competitions/ucl/tests/ --cov=competitions/ucl/src --cov-report=term-missing

# Run a specific test file
python -m pytest competitions/ucl/tests/test_simulation.py -v
```

### Euro Tests

Euro currently has **no test suite** (`competitions/euro/tests/` does not exist).

### Running All Tests

```bash
python -m pytest football_core/tests/ competitions/worldcup/tests/ competitions/ucl/tests/ -v
```

### Test Conventions

- **Test framework:** pytest
- **Fixtures:** Shared fixtures live in `tests/conftest.py` per competition.
  World Cup fixtures include `sample_teams`, `sample_bracket`, `sample_played`,
  and `sample_group_matches_results`. UCL fixtures include 36-team pot data,
  realistic ClubElo ratings, and fixture lists.
- **Naming:** Test files are named `test_<module>.py` and test functions use
  descriptive snake_case names like `test_perfect`, `test_worst`, `test_half`.

---

## Adding a New Competition

Each competition follows a consistent structural pattern. To add a new one:

### 1. Create the Package Structure

```
competitions/<name>/
├── __init__.py          # sys.path setup (see template below)
├── main.py              # CLI entry point
├── src/                 # Competition-specific modules
│   └── __init__.py
├── tests/               # Test suite
│   ├── __init__.py
│   └── conftest.py
└── data/                # Competition data files
```

### 2. `__init__.py` Template

Every competition needs `sys.path` setup so it can import `football_core`:

```python
"""<Name> competition package."""
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)
```

If the new competition reuses World Cup modules (like Euro does), also add
the worldcup `src/` path:

```python
_wc_pkg = str(Path(__file__).resolve().parent.parent / "worldcup")
if _wc_pkg not in sys.path:
    sys.path.insert(0, _wc_pkg)
```

### 3. `main.py` Entry Point

The entry point should use `argparse` for CLI argument parsing and follow one
of two patterns:

**Continuous polling pattern** (like World Cup / Euro):

```python
import argparse
from <package> import <package>  # noqa: F401 — sys.path setup

def _parse_args(argv=None):
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args(argv)

def main():
    args = _parse_args()
    # Load state → polling loop → simulate → print

if __name__ == "__main__":
    main()
```

**Single-run Monte Carlo pattern** (like UCL):

```python
import argparse
from <package> import <package>  # noqa: F401 — sys.path setup

def _parse_args(argv=None):
    parser = argparse.ArgumentParser(...)
    parser.add_argument("-n", type=int, default=10000, help="Iterations")
    parser.add_argument("-s", type=int, default=None, help="Seed")
    parser.add_argument("-o", type=str, default=None, help="JSON output path")
    return parser.parse_args(argv)

def main():
    args = _parse_args()
    # Fetch data → run Monte Carlo → print results

if __name__ == "__main__":
    main()
```

### 4. Testing Setup

Create a `tests/conftest.py` with shared fixtures, then add `test_*.py` files
following the naming convention. The Euro competition currently has no tests —
a new competition should include at minimum:

- Smoke test (`test_main_loop.py` or `test_cli.py`) — verifies the CLI parses
  arguments without error.
- Core logic tests — test group simulation, knockout resolution, etc.

### 5. Data Files

Place competition data (teams, groups, bracket rules, fixtures) in `data/`.
The World Cup uses JSON files like `teams.json`, `groups.json`, `bracket.json`,
and `annex_c.json`. The UCL uses `fixtures.json`, `bracket_rules.json`,
`playoff_pairings.json`, `team_aliases.json`, and `uefa_coefficients.json`.

### 6. Dependencies

If the competition needs additional Python packages, create a
`requirements.txt`. Otherwise, the `requests` and `numpy` dependencies shared
across all competitions are sufficient.

---

## Code Style Guidelines

The project does not use an automated linter or formatter. The following
conventions have emerged organically:

- **Descriptive variable names.** Use full words (`expected_goals` not `xg`,
  `team_a` not `ta`). Abbreviations are acceptable only when they are universal
  (e.g., `elo`, `std`, `max`).
- **Type annotations.** Early modules (`football_core/elo.py`,
  `football_core/groups.py`, `football_core/knockout.py`) use no type hints.
  Newer modules (UCL's `result.py`, `display.py`) use `from __future__ import annotations`
  and full type annotations. Follow the convention of the module you are editing.
- **Docstrings.** Top-level modules have a module-level docstring. Public
  functions and classes have docstrings describing purpose, arguments, and
  return values. Internal/private functions (prefixed with `_`) may omit
  docstrings or use a brief comment.
- **Imports order.** Standard library → third-party → local imports, grouped
  and alphabetized within each group.
- **Maximum line length.** No formal rule, but most files stay under 100
  characters. Long function signatures use trailing-comma multi-line
  formatting.
- **f-strings over `%` or `.format()`.** New code should use f-strings.
- **Pure functions.** Simulation and math functions prefer pure computation
  with no I/O or mutation of global state. I/O (fetching, file persistence,
  terminal output) is isolated in dedicated modules.
- **Edge cases.** Goal difference of 0 or 1 should use `G=1.0`, 2 uses
  `G=1.5`, and 3+ uses `(11+GD)/8` in K-factor computation. Poisson
  distribution uses precomputed tables via `lru_cache` for performance.

### Before Committing

```bash
# Verify tests pass for the competition you modified
python -m pytest competitions/<name>/tests/ -v

# If you modified the core library
python -m pytest football_core/tests/ -v
```

---

## CI Pipeline

Only the **World Cup** competition has a CI pipeline configured.

### Workflow File

`.github/workflows/ci.yml` (located inside `competitions/worldcup/`)

### Triggers

- **Push** to the `main` branch
- **Pull request** targeting the `main` branch

### Matrix

Python 3.10, 3.11, and 3.12 on `ubuntu-latest`.

### Steps

1. `actions/checkout@v4`
2. `actions/setup-python@v5` with the matrix version
3. Install dependencies: `pip install -r requirements.txt && pip install requests numpy`
4. Run tests with coverage: `python -m pytest -v --cov=src --cov-report=term-missing`
5. The `BSD_API_KEY` secret is injected as an environment variable for tests
   that require API access.

### Coverage

The CI runs `pytest-cov` on `src/` (World Cup's `competitions/worldcup/src/`)
with `--cov-report=term-missing`. There is **no configured coverage threshold**
— coverage is informational only.

### UCL and Euro CI

The UCL and Euro competitions do **not** have CI workflows. If adding CI for
one of these, follow the World Cup pattern: create
`competitions/<name>/.github/workflows/ci.yml` with the same Python version
matrix and test invocation.

---

## Additional Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — System architecture, component
  relationships, and data flow.
- **[CONFIGURATION.md](CONFIGURATION.md)** — Environment variables and
  configuration reference.
- **[COMMONALITY_REPORT.md](COMMONALITY_REPORT.md)** — Analysis of shared
  vs. competition-specific code.
- **[FOOTBALL_ENGINE_ARCHITECTURE.md](FOOTBALL_ENGINE_ARCHITECTURE.md)** —
  Detailed architecture and design decisions.
