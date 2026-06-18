# Coding Conventions

**Analysis Date:** 2026-06-16

## Naming Patterns

**Files:**
- Python source files: `snake_case.py` (e.g., `elo.py`, `fetcher.py`, `state.py`, `groups.py`, `knockout.py`, `output.py`, `constants.py`, `elo_sync.py`, `evaluation.py`, `simulation.py`)
- Test files: `test_<module_name>.py` (e.g., `test_state.py`, `test_elo.py`, `test_groups.py`)
- JSON data files: `snake_case.json` (e.g., `teams.json`, `bracket.json`, `played.json`, `groups.json`)

**Functions:**
- `snake_case` with action-prefixed names: `update_ratings()`, `fetch_new_results()`, `simulate_group_matches()`, `compute_standings()`, `rank_third_placed()`, `print_probabilities()`
- Verbs first, then nouns: `load_teams()` not `teams_load()`

**Variables:**
- `snake_case` throughout: `current_elos`, `played_set`, `last_known_ids`, `new_results`
- Boolean variables use positive phrasing: `eliminated` not `not_eliminated`
- Constants: `UPPER_SNAKE_CASE` in `constants.py`: `K_FACTOR`, `POLL_INTERVAL`, `DEFAULT_ELO`, `API_URL`

**Types:**
- Python standard type hints throughout all function signatures
- `dict[str, float]`, `list[dict]`, `set[str]`, `tuple[set[str], dict]` patterns
- Return type annotations required on every function. Parameter types required on every public function.

## Code Style

**Formatting:**
- PEP 8 standard: 4-space indentation, 88-100 char line limit
- 2 blank lines between top-level definitions, 1 between methods
- Import order: standard library → third-party (`requests`) → local modules, blank-line separated

**Linting:**
- No linter config (no flake8, pylint, or ruff config detected)
- CI enforces passing tests (pytest), not linting

## Import Organization

```
import json
import os
import random
from datetime import datetime
from typing import Any

import requests

from src.constants import (
    API_URL,
    K_FACTOR,
    POLL_INTERVAL,
)
from src.state import load_bracket, load_played_matches, load_teams
```

## Error Handling

- **Global catch-all:** Main loop wrapped in `try/except Exception as e` — prints error, sleeps, continues
- **Retry with exponential backoff:** API fetch retries up to 3 times with 1s, 2s, 4s backoff
- **API key validation at startup:** Check `os.environ.get("BSD_API_KEY")` raises `ValueError` if missing
- **Graceful shutdown:** `KeyboardInterrupt` — sets `_running=False`, finishes iteration, saves state, prints final probabilities, exits 0
- **File write safety:** Atomic writes — write to temp file then `os.replace()` to target path
- **JSON decode errors:** Catch `json.JSONDecodeError` from API responses, treat as API failure
- **Team name mismatches:** Log warning, skip match

**Anti-patterns avoided:**
- No bare `except:` — always `except Exception as e:`
- No exit/crash on API failure — survive transient network issues
- No catching `KeyboardInterrupt` in sub-modules — only `main.py` handles shutdown

## Logging

- `print()` statements with ISO 8601 timestamps. No `logging` module for MVP
- ANSI color codes in `output.py`: timestamps = dim gray, match alerts = bold yellow, Elo increase = green, decrease = red, probability ▲ = green, ▼ = red, errors = bold red
- Fallback: `--no-color` strips ANSI, uses symbols alone (▲, ▼, ⚠)

## Comments

- Module-level docstring in every file describing the module's purpose
- Every function: docstring with parameters, return value, side effects
- Complex formulas (Elo, Poisson): inline comments explaining math
- Constants and magic numbers: explanation of chosen value

## Function Design

- Single responsibility per function
- Largest functions under ~715 lines (`src/groups.py` — group simulation engine)
- Primitive types preferred: `str`, `int`, `float`, `dict`, `set`, `list`
- Named parameters over positional for clarity
- Sensible defaults: `K: int = 60`, `n: int = 50000`
- Functions return simple types: `str`, `dict`, `list`, `tuple`, `None`
- No exception-based flow control. Return empty structures for no-data cases

## Module Design

- Modules expose typed public functions only
- No classes — all logic is pure functions using dicts and sets
- `src/__init__.py` exists but is empty

**Package structure (current):**
```
worldcup_predictor/
├── src/
│   ├── __init__.py
│   ├── constants.py        # Configurable parameters
│   ├── state.py            # JSON persistence, validation
│   ├── elo.py              # Elo rating math
│   ├── groups.py           # Group stage simulation, standings, tiebreakers
│   ├── knockout.py         # Full tournament pipeline
│   ├── simulation.py       # Legacy v1.0 knockout-only simulation
│   ├── fetcher.py          # BSD API polling
│   ├── elo_sync.py         # Elo sync from eloratings.net
│   ├── evaluation.py       # Prediction quality metrics
│   └── output.py           # Console formatting
├── tests/
│   ├── test_state.py
│   ├── test_elo.py
│   ├── test_groups.py
│   ├── test_knockout.py
│   ├── test_simulation.py
│   ├── test_fetcher.py
│   ├── test_output.py
│   ├── test_elo_sync.py
│   ├── test_evaluation.py
│   ├── test_cli.py
│   ├── test_integration.py
│   ├── test_main_loop.py
│   ├── test_live_smoke.py
│   ├── test_scaffold.py
│   ├── test_state_load.py
│   └── test_group_integration.py
├── data/
│   ├── teams.json           # 48 teams with Elo ratings
│   ├── bracket.json         # 40-match knockout bracket
│   ├── groups.json          # 12 group definitions
│   ├── annex_c.json         # 495-entry Annex C table
│   ├── team_aliases.json    # BSD API name variations
│   ├── played.json          # Knockout match results
│   └── (6 more runtime files)
├── main.py
└── requirements.txt
```

## Data Conventions

- JSON keys: uppercase team names (e.g., `"Argentina"`, `"France"`)
- Match IDs: `"R32_1"`, `"QF_1"`, `"GS_A_01"` (group stage), `"FINAL"`
- Winner field: `null` for unplayed/drawn, team name string for played
- All JSON files human-readable with indentation

**In-memory structures:**
- `teams: dict[str, dict]` — team name → `{"elo": int, "group": str, "eliminated": bool, "fifa_rank": int}`
- `played_set: set[str]` — match IDs for O(1) lookup
- `played_details: dict[str, dict]` — match ID → full match result
- `probabilities: dict[str, float]` — team name → probability (sum ≈ 1.0)

**Constants in `constants.py`:**
```python
K_FACTOR = 60
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
API_URL = "https://sports.bzzoiro.com/api/events/?league_id=27&limit=200"
DEFAULT_ELO = 1500
GROUP_COUNT = 12
MATCHES_PER_GROUP = 6
ANNEX_C_ENTRIES = 495
```

---

*Convention analysis: 2026-06-16*
