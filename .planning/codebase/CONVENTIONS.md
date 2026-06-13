# Coding Conventions

**Analysis Date:** 2026-06-13

## Naming Patterns

**Files:**
- All Python source files: `snake_case.py` (e.g., `elo.py`, `fetcher.py`, `state.py`, `simulator.py`, `output.py`, `constants.py`)
- Test files: `test_<module_name>.py` (e.g., `test_state.py`, `test_elo.py`, `integration_test.py`)
- JSON data files: `snake_case.json` (e.g., `teams.json`, `bracket.json`, `played.json`, `api_id_mapping.json`)

**Functions:**
- `snake_case` with descriptive action-prefixed names (e.g., `update_ratings()`, `fetch_new_results()`, `run_monte_carlo()`, `simulate_match()`, `print_probabilities()`)
- Verbs first, then nouns: `load_teams()` not `teams_load()`

**Variables:**
- `snake_case` throughout (e.g., `current_elos`, `played_set`, `last_known_ids`, `new_results`)
- Boolean variables use positive phrasing: `eliminated` not `not_eliminated`
- Constants: `UPPER_SNAKE_CASE` defined in `constants.py` (e.g., `K_FACTOR = 60`, `POLL_INTERVAL_SECONDS = 60`, `SIMULATION_COUNT = 50000`, `API_URL = "..."`, `API_KEY_ENV_VAR = "FOOTBALL_API_KEY"`)

**Types:**
- Python standard type hints throughout all function signatures (e.g., `def update_ratings(team_a: str, team_b: str, winner: str, current_elos: dict[str, float], K: int = 60) -> dict[str, float]:`)
- Custom types: None for MVP. Use built-in generics: `dict[str, float]`, `list[dict]`, `set[str]`, `tuple[set[str], dict]`
- Return type annotations required on every function. Parameter types required on every public function.

## Code Style

**Formatting:**
- Standard Python PEP 8 enforced. No auto-formatter config detected — use standard Python style (4-space indentation, 88-100 char line limit recommended)
- Blank lines: 2 between top-level definitions, 1 between methods in a class (though MVP has no classes)
- Imports order: standard library → third-party (`requests`) → local modules, separated by blank lines

**Linting:**
- No linter config detected yet. Plan to add `pytest` to `requirements.txt` in Phase 0. `flake8` or `pylint` not specified but recommended before Phase 2.
- No pre-commit hooks detected. Plan to use environment variable for API key security (`.gitignore` for `.env`).

## Import Organization

**Order:**
1. Standard library: `os`, `json`, `time`, `random`, `sys`, `logging`, `functools`, `datetime`
2. Third-party: `requests`
3. Local modules: `from src import state, elo, simulator, fetcher, output`, `from src.constants import K_FACTOR, SIMULATION_COUNT`

**Path Aliases:**
- No aliases or path rewriting detected. Imports use relative package structure via `src/__init__.py`.
- Run from project root: `python main.py` uses `from src.state import ...` style.

**Example import block:**
```python
import json
import os
import random
from datetime import datetime
from typing import Any

import requests

from src.constants import (
    API_KEY_ENV_VAR,
    API_URL,
    K_FACTOR,
    POLL_INTERVAL_SECONDS,
    SIMULATION_COUNT,
)
from src.state import load_bracket, load_played_matches, load_teams
```

## Error Handling

**Patterns:**
- **Global catch-all:** Main loop wrapped in `try/except Exception as e` — prints error, sleeps, continues loop. Never exits on transient failure (`main.py`, line 208 of `TRD.md`).
- **Retry with exponential backoff:** API fetch retries up to 3 times with 1s, 2s, 4s backoff (defined in `fetcher.py`, line 122 of `TRD.md`). On final failure, log and return empty results — never crash.
- **API key validation at startup:** Check `os.environ.get("FOOTBALL_API_KEY")` raises `ValueError` if unset (`main.py` startup, `Backend_Schema.md` section 9).
- **Graceful shutdown:** `KeyboardInterrupt` caught in `main.py` — saves state, prints final probabilities, exits with code 0 (`Appflow.md` section 11).
- **File write safety:** Atomic writes — write to temp file then rename to avoid corruption (`state.py`, `TRD.md` section 5.4 line 183).
- **JSON decode errors:** Catch `json.JSONDecodeError` from API responses, treat as API failure (`Implementation_plan.md` Phase 5).
- **Team name mismatches:** Log warning, skip the match via mapping dictionary fallback (`Appflow.md` section 6, `Implementation_plan.md` Phase 5).

**Anti-patterns to avoid:**
- Do NOT use bare `except:` — always specify `except Exception as e:`.
- Do NOT exit or crash on API failure — the system must survive transient network issues.
- Do NOT catch `KeyboardInterrupt` in sub-modules — only `main.py` handles shutdown.

## Logging

**Framework:** `print()` statements with ISO 8601 timestamps. No `logging` module for MVP (console-only output).

**Patterns:**
```python
# Standard heartbeat
print(f"[{datetime.utcnow().isoformat()}] Polling... no new matches.")

# Match detection
print(f"[{datetime.utcnow().isoformat()}] NEW MATCH DETECTED!")

# Elo update
print(f"[{datetime.utcnow().isoformat()}] Updating Elo: {team_a} {old_elo_a} -> {new_elo_a}")

# Error
print(f"[{datetime.utcnow().isoformat()}] API error: timeout. Retry in 60s.")

# Probabilities
print(f"[{datetime.utcnow().isoformat()}] Updated probabilities:")
```

**Color conventions (ANSI codes, in `output.py`):**
| Element | Color | Purpose |
|---------|-------|---------|
| Timestamps | Dim gray | Background info |
| Match alerts | Bold yellow | Attract attention |
| Elo increase | Green | Positive change |
| Elo decrease | Red | Negative change |
| Probability delta ▲ | Green | Positive movement |
| Probability delta ▼ | Red | Negative movement |
| Errors | Bold red | Alert user |
| Success | Bold green | Confirm completion |

**Fallback:** When `--no-color` flag provided or terminal doesn't support ANSI, use symbols alone: `▲`, `▼`, `⚠`.
- ANSI color logic must be wrapped in a helper in `output.py` — never inline escape codes in `main.py`.

## Comments

**When to Comment:**
- Every file: module-level docstring explaining the module's purpose.
- Every function: docstring with `"""` describing parameters, return value, and any side effects (as shown in `Backend_Schema.md` section 5).
- Complex formulas: inline comments explaining the math (especially Elo formula in `elo.py`).
- Bracket traversal logic: comment explaining the recursive/match-ID lookup pattern in `simulator.py`.
- Constants and magic numbers: explain why the value was chosen (e.g., `# K=60 for high-volatility knockout matches`).

**JSDoc/TSDoc:**
- Not applicable (Python). Use PEP 257 docstring convention.
- Example docstring style from `Backend_Schema.md`:
  ```python
  def update_ratings(team_a: str, team_b: str, winner: str,
                     current_elos: dict[str, float],
                     K: int = 60) -> dict[str, float]:
      """
      Returns new elo dict (only for the two teams changed).
      """
  ```

## Function Design

**Size:**
- Each function has a single responsibility (one job, well-named).
- `run_monte_carlo()` and `run_single_tournament()` are the largest — but kept under ~50 lines by delegating `simulate_match()`.
- `main.py` loop body kept concise by delegating to module functions.

**Parameters:**
- Primitive types preferred: `str`, `int`, `float`, `dict`, `set`, `list`.
- Named parameters over positional for clarity (especially booleans).
- Sensible defaults for configurable parameters: `K: int = 60`, `n: int = 50000`.

**Return Values:**
- Functions return simple types: `str`, `dict`, `list`, `tuple`, `None`.
- No exception-based flow control. Return empty structures (empty `list`, empty `dict`) for no-data cases.
- `fetch_new_results()` returns `list[dict]` — empty list when no new matches.
- `update_ratings()` returns a dict with only the two changed teams.

## Module Design

**Exports:**
- Modules expose public functions only. No private helper functions are expected to be named with `_` prefix for MVP.
- All public function signatures explicitly typed.

**Package structure** (`Implementation_plan.md` Phase 0):
```
worldcup_predictor/
├── src/
│   ├── __init__.py
│   ├── state.py        # JSON persistence
│   ├── elo.py          # Elo rating math
│   ├── simulator.py    # Match & tournament simulation
│   ├── fetcher.py      # External API polling
│   ├── output.py       # Console formatting
│   └── constants.py    # All configurable constants
├── tests/
│   ├── test_state.py
│   ├── test_elo.py
│   └── integration_test.py
├── data/
│   ├── teams.json
│   ├── bracket.json
│   ├── played.json
│   └── api_id_mapping.json
├── main.py
└── requirements.txt
```

**No classes for MVP** — all logic is pure functions using dicts and sets. The design explicitly avoids OOP overhead (`MVP.md` section 4: "No web framework, no database, no frontend – keep it a single script").

**Barrel Files:**
- Not applicable. `src/__init__.py` exists but is expected to be empty or contain only a version string.

## Data Conventions

**JSON file format:**
- keys: uppercase team names (e.g., `"Argentina"`, `"France"`)
- match IDs: `"{Round}_{number}"` format (e.g., `"R16_1"`, `"QF_3"`, `"SF_2"`, `"FINAL"`)
- winner field: `null` when match not yet played, team name string when played
- All JSON files remain human-readable with indentation (no minification)

**In-memory structures:**
- `teams: dict[str, dict]` — team name → `{"elo": int, "eliminated": bool}`
- `played_set: set[str]` — match IDs for O(1) lookup
- `played_details: dict[str, dict]` — match ID → full match result details
- `probabilities: dict[str, float]` — team name → probability (sum ≈ 1.0)

**Constants in `constants.py` (all example defaults, override as needed):**
```python
K_FACTOR = 60
POLL_INTERVAL_SECONDS = 60
SIMULATION_COUNT = 50000
API_URL = "https://api.football-data.org/v4/matches?competition=WC&status=FINISHED"
API_KEY_ENV_VAR = "FOOTBALL_API_KEY"
DEFAULT_ELO_START = 2000
```

**State persistence rules:**
- State saved after EVERY Elo update (not batched).
- Atomic writes: write to `.tmp` file → `os.replace()` to target.
- No database — JSON files only.

---

*Convention analysis: 2026-06-13*
