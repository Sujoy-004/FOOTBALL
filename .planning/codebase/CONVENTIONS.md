# Coding Conventions

**Analysis Date:** 2026-06-27

## Naming Patterns

**Files:**
- All lowercase with underscores (`snake_case.py`): `elo.py`, `math_utils.py`, `elo_sync.py`, `knockout.py`
- Test files prefixed with `test_`: `test_elo.py`, `test_groups.py`, `test_state.py`
- Package `__init__.py` files present for all packages

**Functions:**
- `snake_case` exclusively for all function and method names
- Module-private functions prefixed with underscore: `_poisson_sample`, `_tiebreak_group`, `_atomic_write_json`, `_dfs`, `_resolve_data_dir`, `_build_round_map`, `_compute_h2h`, `_get_blended_prob`
- Public functions exposed as module-level: `expected_score()`, `update_ratings()`, `simulate_group_matches()`, `load_teams()`, `validate_bracket()`

**Variables:**
- `snake_case` for all local and module-level variables: `goal_diff`, `elo_a`, `expected_a`, `matchup_lambdas`, `winner_progression`
- Constants in `UPPER_SNAKE_CASE`: `K_FACTOR`, `DEFAULT_ELO`, `MAX_EXPECTED_GOALS`, `API_TIMEOUT`, `ROUND_ORDER`, `ROUND_KEYS`
- Single-letter variable names for generic parameters: `_` (loop discard), `r` (round), `k` (loop counter in `_build_poisson_table`)
- Type-annotated local variables: `result: list[dict] = []`, `teams_seen: set[str] = set()`

**Types:**
- `PascalCase` for all classes: `TestExpectedScore`, `TestUpdateRatings`, `TestComputeKFactor`, `TestDrawBackfill`, `TestMigratePredictionHistory`, `MockResponse`
- Type aliases and union types use standard library notation: `str | None`, `dict[str, float]`, `Path | str | None`

## Code Style

**Formatting:**
- No auto-formatter configuration detected (no `.prettierrc`, `.editorconfig`, `pyproject.toml`, or `setup.cfg` for Python)
- Code consistently follows PEP 8 with 4-space indentation
- Line lengths appear to be within reasonable limits (~100 chars max)
- Two blank lines between top-level definitions (classes, functions)
- Single blank line between method definitions inside classes

**Linting:**
- No linting configuration detected (no `.flake8`, `pyproject.toml` with flake8/ruff, or `setup.cfg`)
- Code quality is self-enforced through consistent style

**Imports:**
```python
# Standard library first (alphabetically grouped)
import functools
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Third-party second
import pytest
import requests

# Internal imports third
from football_core import constants
from football_core.elo import expected_score
from src import constants as wc_constants   # when importing from competition-level src
```

## Import Organization

**Order:**
1. Standard library imports (alphabetical)
2. Third-party imports (pytest, requests)
3. Internal project imports:
   - `football_core.*` core library imports
   - `src.*` competition-level imports
   - Relative imports within same package

**Re-export Pattern:**
The competition-level package (`competitions/worldcup/src/`) re-exports from `football_core/` and adds competition-specific wrappers:

```python
# In competitions/worldcup/src/predictors/catboost.py
from football_core.predictors.catboost import (
    _normalize_prediction,
    _extract_probability,
    _extract_xg,
    _find_match_id,
    parse_catboost_response,
    predictions_url_for_league,
    fetch_and_cache_catboost as _core_fetch_and_cache_catboost,
)
```

```python
# In competitions/worldcup/src/knockout.py — mixing core and src
from src.groups import (
    compute_standings,
    rank_third_placed,
    select_advancers,
    resolve_r32_matchups,
)
from football_core.groups import (
    precompute_matchup_lambdas,
    simulate_group_matches,
)
from football_core.knockout import (
    _build_round_map,
    _simulate_knockout_round,
    _get_blended_prob,
)
```

**Path Aliases:**
- No path aliases (e.g., `@/`) are used. All imports are relative to the project structure using sys.path manipulation at entry points (`main.py`).

## Error Handling

**Patterns:**
- **Raise `ValueError`** for validation failures with descriptive messages:
  ```python
  raise ValueError(f"pk_winner '{pk_winner}' must be '{team_a}' or '{team_b}'")
  ```
  (`football_core/elo.py:44-45`)

- **Use `assert` rarely** — only in test files for test assertions, not in production code
- **Exception cleanup** pattern for atomic operations — clean up temp files on failure:
  ```python
  try:
      with os.fdopen(fd, "w", encoding="utf-8") as f:
          json.dump(data, f, indent=2)
          f.flush()
          os.fsync(f.fileno())
      os.replace(tmp_path, str(path))
  except Exception:
      try:
          os.unlink(tmp_path)
      except OSError:
          pass
      raise
  ```
  (`football_core/state.py:26-36`)

- **Graduated error logging** in network operations — log warnings at each retry:
  ```python
  except requests.exceptions.Timeout:
      logger.warning("Request timed out (attempt %d/3)", attempt + 1)
      if attempt < 2:
          time.sleep(backoff_seconds[attempt])
          continue
      return []
  ```
  (`football_core/fetcher.py:49-54`)

- **Return empty/None** on non-fatal errors in fetchers rather than raising:
  ```python
  except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
      logger.warning("Malformed JSON response, returning []")
      return []
  ```
  (`football_core/fetcher.py:70-72`)

## Logging

**Framework:** Python standard library `logging` module

**Patterns:**
- Logger at module level: `logger = logging.getLogger(__name__)`
- Using %-formatting in log messages (not f-strings): `logger.warning("HTTP 401 (invalid API key), returning []")`
- Log levels used: `warning` for recoverable issues, `debug` for verbose info
- No `info` level usage detected — only `warning` and `debug`

## Comments

**When to Comment:**
- Module docstrings explaining purpose of the file
- Class docstrings describing test class coverage
- Inline comments for non-obvious logic (tiebreaker steps, boundary values)
- Section markers using comment dashes: `# ─── Section name ────────────────────────────────────────────`

**Python Docstrings:**
- Triple-quoted `""" ... """` for modules, classes, functions
- Google/informational style — brief description on the first line, then Args/Returns sections where helpful:
  ```python
  def update_ratings(
      team_a: str,
      team_b: str,
      winner: str | None,
      current_elos: dict[str, float],
      K: int = 60,
      pk_winner: str | None = None,
  ) -> dict[str, float]:
      ...
  ```
  (`football_core/elo.py:23-30`)

- Test classes and methods always include docstrings describing what is tested:
  ```python
  class TestExpectedScore:
      """Tests for the expected_score function."""

      def test_equal_ratings(self):
          """Equal ratings should return 0.5 exactly."""
  ```
  (`competitions/worldcup/tests/test_elo.py:17-21`)

## Function Design

**Size:**
- Core logic functions are compact (10-30 lines)
- Larger pipeline functions can be 50-80 lines (`simulate_group_matches`, `run_full_simulation`, `validate_groups`)
- Private helper functions extracted from complex logic: `_build_round_map`, `_simulate_knockout_round`, `_tiebreak_group`, `_resolve_by_values`

**Parameters:**
- Named parameters with defaults for configuration values: `home_advantage: int = 0`, `base_rate: float = constants.EXPECTED_GOALS_BASE_RATE`, `fair_play: bool = True`
- Union types for optional parameters: `data_dir: Path | str | None = None`
- Complex parameter combinations in domain functions (e.g., `run_full_simulation` takes 11 parameters)

**Return Values:**
- Single-type returns with type annotations always present
- Sentinel value pattern: `return None` for "not found" cases, `return []` for empty results
- Validation functions return `tuple[bool, list[str]]`: `validate_eloratings_data`

## Module Design

**Exports:**
- Public functions are documented at module level (no `__all__` declarations)
- Explicit import paths used by consumers: `from src.elo import expected_score, update_ratings`
- Dual-layer architecture: `football_core/` holds generic logic, `competitions/worldcup/src/` holds WC-specific wrappers

**Barrel Files:**
- `__init__.py` used for:
  - Package marking (empty for `football_core/__init__.py`)
  - Documentation: `competitions/worldcup/src/predictors/__init__.py` describes package contents in docstring
  - Re-exports are NOT done through `__init__.py` — direct imports from modules preferred

**Competition Structure:**
```
football_core/                  # Generic library — no competition logic
├── elo.py                      # Elo rating engine
├── groups.py                   # Group simulation
├── knockout.py                 # Knockout primitives
├── state.py                    # State persistence
├── fetcher.py                  # API fetch pipeline
├── elo_sync.py                 # Elo sync pipeline
├── math_utils.py               # Shared utilities
├── constants.py                # Shared constants
└── predictors/                 # Prediction signal computation
    ├── __init__.py
    ├── catboost.py
    └── odds.py

competitions/worldcup/          # World Cup competition — concrete
├── main.py                     # Entry point
├── src/                        # WC-specific implementations
│   ├── knockout.py             # WC knockout simulation
│   ├── groups.py               # WC group extensions
│   ├── state.py                # WC persistence with validation
│   ├── constants.py            # WC constants
│   ├── predictors/             # WC prediction wrappers
│   └── ...
└── tests/                      # All tests
    ├── conftest.py             # Shared fixtures
    ├── test_elo.py
    ├── test_groups.py
    └── ...
```

**Dependency Direction:**
- `competitions/worldcup/src/` imports from `football_core/` and `src/` (same package), never the reverse
- `football_core/` has no knowledge of any competition

---

*Convention analysis: 2026-06-27*
