# Technology Stack

**Analysis Date:** 2026-06-27

## Languages

**Primary:**
- Python 3.11+ — All application code, from CLI entry points to core engine to tests.
  Bytecode compilation reveals `cpython-311` across all `__pycache__/` directories.
  CI matrix validates against 3.10, 3.11, and 3.12 (`competitions/worldcup/.github/workflows/ci.yml`).

**Secondary:**
- JSON — Static tournament data (teams, groups, bracket, annex C), runtime persistence (played matches, prediction history, signal caches), and configuration (`config.json`).

## Runtime

**Environment:**
- CPython — No managed runtime (Docker, virtualenv) captured in repo; dependencies resolved at install time via `pip`.
- Cross-platform: tested on GitHub Actions `ubuntu-latest`; Windows `SIGBREAK` handler present in `competitions/worldcup/main.py:1517` and `competitions/euro/main.py:226`.

**Package Manager:**
- pip — Declared in `competitions/worldcup/requirements.txt`.
- Lockfile: Not detected. No `requirements-lock.txt`, `Pipfile.lock`, or `poetry.lock` present.

## Frameworks

**Core (none):**
- No web framework (Django, FastAPI, Flask). The application is a CLI-based long-running process with a polling loop — not a web service.

**Testing:**
- pytest >= 9.0 — Test runner. Config file not detected; relies on pytest defaults.
- pytest-cov >= 7.1 — Coverage reporting.
- Config: Not detected (no `pytest.ini`, `pyproject.toml`, or `setup.cfg` with pytest config).

**Build/Dev:**
- No build system (no `setup.py`, `pyproject.toml`, `Makefile`, `tox.ini`).
- Package bootstrap per competition uses dynamic `sys.path` insertion in `__init__.py`:
  - `competitions/worldcup/__init__.py` — adds repo root + package dir to `sys.path`
  - `competitions/euro/__init__.py` — adds repo root + worldcup package dir to `sys.path`

**CI:**
- GitHub Actions — workflow at `competitions/worldcup/.github/workflows/ci.yml`

## Key Dependencies

**Critical runtime dependencies (from `competitions/worldcup/requirements.txt` + CI):**

| Package | Version | Source | Purpose |
|---------|---------|--------|---------|
| `requests` | latest (not pinned) | CI `pip install requests` | HTTP client for BSD Sports API and eloratings.net |
| `python-dotenv` | >= 1.0 | `requirements.txt` | Load `.env` file with BSD_API_KEY |
| `numpy` | latest (not pinned) | CI `pip install numpy` | Numerical operations (used for Poisson table computations) |

**Standard library modules used (no separate package):**
- `json` — All state persistence (JSON files), API response parsing
- `csv` / `io` — TSV parsing for eloratings.net data (`football_core/elo_sync.py:55-56`)
- `argparse` — CLI argument parsing (`competitions/worldcup/main.py:214-278`)
- `logging` — Structured logging throughout all modules
- `dataclasses` — RunState data container (`competitions/worldcup/main.py:39-51`)
- `random` — Monte Carlo simulation (50K iterations per cycle)
- `signal` — Graceful shutdown (SIGINT/SIGTERM/SIGBREAK)
- `tempfile` / `os.replace` — Atomic file writes for JSON persistence
- `pathlib` — Cross-platform path handling
- `shutil` — Legacy data migration (`competitions/worldcup/main.py:1202`)
- `functools.lru_cache` — Poisson table caching (`football_core` groups/knockout modules, per commit history)
- `math` — Elo rating formulas, probability computations

**Dev dependencies:**
| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | >= 9.0 | Test runner |
| `pytest-cov` | >= 7.1 | Coverage reporting |

## Configuration

**Environment (loaded via python-dotenv from `.env`):**
- `BSD_API_KEY` — Required. API token for Bzzoiro Sports Data API. Validated at startup with HTTP 401 check (`competitions/worldcup/main.py:1160-1188`).
- `POLL_INTERVAL` — Optional. Polling interval in seconds (default: 60). Read at `competitions/worldcup/src/constants.py:53`.

**File-based config:**
- `competitions/worldcup/config.json` — Optional. Contains `{"league_id": 27}` to override default league ID. Auto-created on first run if missing.
- `competitions/worldcup/data/` — State directory with per-league subdirectories (`data/27/` for World Cup 2026).

**CLI flags:**
- `--once` — Single fetch→simulate→print cycle
- `--seed N` — Reproducible Monte Carlo simulation
- `--no-color` — Disable ANSI console output
- `--ai-preview` — Show BSD AI prediction previews
- `--match-detail [TABLE|MATCH_ID]` — Per-match signal breakdown
- `--league ID` — Override BSD league ID (default: 27)
- `--list-leagues` — Print available league IDs

## Platform Requirements

**Development:**
- Python 3.10+ (CI matrix: 3.10, 3.11, 3.12)
- `pip install -r requirements.txt` plus `pip install requests numpy`
- BSD API key (free at https://sports.bzzoiro.com/register/)
- .env file with `BSD_API_KEY=your_key_here`

**Production:**
- No deployment target captured. The tool is designed as a terminal-based CLI, not a hosted service. Runs as a long-lived process on any machine with Python 3.10+ and network access to `sports.bzzoiro.com` and `eloratings.net`.

---

*Stack analysis: 2026-06-27*
