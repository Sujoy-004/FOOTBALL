# Migration Plan: Repository Restructuring

## Overview

```
BEFORE:                              AFTER:
FOOTBALL/                            FOOTBALL/
├── .gitignore                        ├── .gitignore
├── COMMONALITY_REPORT.md             ├── COMMONALITY_REPORT.md
├── FOOTBALL_ENGINE_ARCHITECTURE.md   ├── FOOTBALL_ENGINE_ARCHITECTURE.md
├── docs/                             ├── docs/
├── competitions/                     ├── football_core/        ← PROMOTED
│   └── euro/                         ├── competitions/
│       ├── __init__.py               │   ├── worldcup/         ← MOVED
│       ├── main.py                   │   │   ├── main.py
│       ├── simulation.py             │   │   ├── src/
│       ├── config.py                 │   │   ├── tests/
│       ├── display.py                │   │   ├── data/
│       └── data/                     │   │   ├── .github/
├── euro_predictor/                   │   │   ├── scripts/
│   └── README.md                     │   │   ├── benchmarks/
├── ucl_predictor/                    │   │   ├── requirements.txt
│   └── README.md                     │   │   └── config.json
├── worldcup_predictor/               │   ├── euro/             ← STAYS
│   ├── main.py                       │   │   ├── __init__.py (SYSPATH UPDATED)
│   ├── src/                          │   │   ├── main.py
│   │   ├── __init__.py               │   │   ├── simulation.py
│   │   ├── constants.py              │   │   └── ...
│   │   ├── [15 more files]           │   └── ucl/              ← MOVED
│   ├── tests/                        │       └── README.md
│   ├── football_core/                └── (empty euro_predictor/ deleted)
│   │   ├── __init__.py
│   │   ├── [10 modules]
│   ├── data/
│   ├── .github/
│   ├── scripts/
│   ├── benchmarks/
│   ├── requirements.txt
│   └── config.json
```

## File Moves (git operations)

| Action | Source | Destination |
|--------|--------|-------------|
| `git mv` | `worldcup_predictor/football_core/` | `football_core/` |
| `git mv` | `worldcup_predictor/` | `competitions/worldcup/` |
| `git rm -r` | `euro_predictor/` | *(deleted — placeholder README, actual code already at `competitions/euro/`)* |
| `git mv` | `ucl_predictor/` | `competitions/ucl/` |

## Content Changes

### 1. CREATE: `competitions/worldcup/__init__.py`

```python
"""World Cup 2026 competition package."""
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)
```

Purpose: puts repo root on `sys.path` (so `football_core` resolves) and the worldcup package dir (so `from src import ...` and `import main` resolve when running from other CWDs).

### 2. EDIT: `competitions/worldcup/main.py`

Insert after line 21 (`from dotenv import load_dotenv`):

```python
import competitions.worldcup  # noqa: F401 — sets up sys.path
```

### 3. EDIT: `competitions/euro/__init__.py`

Replace current content with:

```python
"""Euro 2024 Predictor — uses football_core for generic tournament primitives."""
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_wc_pkg = str(Path(__file__).resolve().parent.parent / "worldcup")
if _wc_pkg not in sys.path:
    sys.path.insert(0, _wc_pkg)
```

Purpose: adds repo root (for `football_core`) and `competitions/worldcup/` (for `from src.groups import ...`).

### 4. EDIT: `competitions/worldcup/.github/workflows/ci.yml`

Add at top level (after `jobs:`):

```yaml
defaults:
  run:
    working-directory: competitions/worldcup
```

Or update the test step to:

```yaml
      - name: Test with pytest
        working-directory: competitions/worldcup
        run: |
          python -m pytest -v --cov=src --cov-report=term-missing
```

## Files With Zero Import Changes

| Path | Reason |
|------|--------|
| `competitions/worldcup/src/*.py` (12 files, 41 intra-package `from src import ...` stmts) | `competitions/worldcup/` on sys.path via `__init__.py` |
| `competitions/worldcup/tests/*.py` (48 `from src` / 44 `import main` stmts) | Same + CWD when running pytest from `competitions/worldcup/` |
| `competitions/euro/main.py` | Already uses `from football_core import ...` |
| `competitions/euro/simulation.py` | Uses `football_core.*` (resolves via repo root) and `src.groups` (resolves via `competitions/worldcup/`) |

## Verification Commands

```bash
# World Cup tests (from competitions/worldcup/)
cd competitions/worldcup && python -m pytest tests/ -x --tb=short -q

# football_core import check (anywhere in repo)
python -c "import football_core; print(football_core.__file__)"

# Euro import check
python -c "from competitions.euro.simulation import run_full_simulation; print('ok')"

# Git status — should show clean moves, no unexpected changes
git status --short
```
