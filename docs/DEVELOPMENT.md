<!-- generated-by: gsd-doc-writer -->
# Development Guide

This guide covers developer workflows, environment setup, coding conventions, architectural boundaries, and CI quality gates for the FOOTBALL platform.

---

## Local Setup

### 1. Prerequisites
- **Python**: 3.11 (3.10–3.12 compatible; 3.11 is target runtime and CI standard)
- **Node.js**: 20+ (required for frontend unit tests: `node --test`)
- **Git**

### 2. Environment Setup

Clone the repository and set up a virtual environment:

```bash
git clone <repository-url>
cd FOOTBALL
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

Install the pinned dependencies matching the CI test battery:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment configuration:

```bash
cp .env.example .env
```

Key environment toggles during development:
- `FOOTBALL_SNAPSHOT=1`: Forces offline mode. All network fetch wrappers self-gate, making zero external API calls and serving stored snapshots.
- `FOOTBALL_PRELOAD_ALL=1`: Eagerly refreshes/preloads all registered competition caches at boot (defaults to lazy acquisition per competition).
- Optional API keys (for live data updates): `FOOTBALL_DATA_ORG_KEY`, `BSD_API_KEY`, `THE_ODDS_API_KEY`. The server runs fully offline without these keys using committed snapshot datasets.

### 5. Running the Local Server

Run the unified FastAPI server via Python module execution or Uvicorn:

```bash
# Standard local run (eagerly warms cache by default, listens on 127.0.0.1:8080)
python -m web.server

# Explicit offline mode (zero network calls)
python -m web.server --offline

# Skip cache preload on startup
python -m web.server --no-preload

# Custom host and port
python -m web.server --host 0.0.0.0 --port 8080
```

Once running, access:
- Landing Page & SPA Dashboard: `http://localhost:8080/`
- Static Assets: `http://localhost:8080/static/`
- World Cup Sub-App: `http://localhost:8080/worldcup/`
- UCL Sub-App: `http://localhost:8080/ucl/`
- LaLiga Sub-App: `http://localhost:8080/laliga/`

---

## Build & Quality Commands

The project uses standalone Python modules, Ruff, mypy, pytest, and Node.js rather than npm build scripts.

| Command | Description |
|---------|-------------|
| `python -m web.server` | Start local ASGI server on port 8080 |
| `python -m web.server --offline` | Start local server in strict offline mode (`FOOTBALL_SNAPSHOT=1`) |
| `ruff check .` | Run lint checks across the codebase using `pyproject.toml` configuration |
| `mypy football_core` | Type-check the core prediction kernel |
| `pytest -v tests/test_quality_gates.py tests/test_layering_architecture.py tests/test_atomic_store_writes.py tests/test_hard02_swallow_sites.py` | Verify architectural layering, quality gates, and atomic store invariants |
| `pytest` | Execute the full Python test suite |
| `pytest --cov=football_core --cov-report=term-missing` | Run test suite with kernel coverage report (enforces `>= 70%` coverage floor) |
| `node --test web/static/refresh.test.mjs` | Run frontend JavaScript unit tests |

---

## Code Style & Architectural Invariants

### Linter & Formatter: Ruff
- **Configuration**: Defined in `pyproject.toml` (`[tool.ruff]`).
- **Target**: Python 3.11 (`target-version = "py311"`).
- **Rule Set**: Pyflakes rules (`select = ["F"]`).
- **Ignored**: `F401` (intentional facade re-exports and module aliases), `F841` (unused variables), `F811` (redefinition), `F541` (f-string missing placeholder), `F601` (tuple unpacking).
- **Enforcement**: Run `ruff check .` before pushing.

### Static Typing: mypy
- **Configuration**: Defined in `pyproject.toml` (`[tool.mypy]`).
- **Scope**: Primary target is `football_core`.
- **Options**: `python_version = "3.11"`, `explicit_package_bases = true`, `ignore_missing_imports = true`.
- **Enforcement**: Run `mypy football_core`.

### Layer Separation Boundaries
The architecture enforces strict unidirectional dependency boundaries:
1. **`football_core/` (Shared Kernel)**:
   - Contains core mathematical models (Poisson, Monte Carlo, Elo), truth domain types, blender, and signal interfaces.
   - **Hard Rule**: `football_core` **never** imports from `competitions/*` or `web/*`. Verified automatically by `tests/test_layering_architecture.py`.
2. **`competitions/<id>/src/` (Competition Brains)**:
   - Owns competition-specific tournament logic, tiebreakers, table progression, and pipelines.
   - Depends only on `football_core`. Never imports from `web/*` or sibling competitions.
3. **`web/` (HTTP & Presentation Layer)**:
   - FastAPI server, competition adapter registry, task services, and static browser client.
   - Mounts competition apps and orchestrates background simulations.

### Provenance & Truthfulness Invariants
- **Immutable Facts vs Simulated Values**: Played matches are immutable facts (`MatchStatus.PLAYED`). Any simulated match or state must carry `ResultProvenance.SIMULATED`.
- **No Fabricated Data**: Missing data must never be reported as zeroes or empty tables; use explicit `DataAvailability` semantics (`LIVE`, `SNAPSHOT`, `FALLBACK`, `EMPTY`, `MISSING`).
- **Boot Safety**: The web server must make **zero** external network calls during lifespan startup. Ingestion is strictly lazy on first request or explicit via `/api/refresh`.

---

## Branch Conventions

- **Default Branch**: `main`
- **Feature Branches**: `feat/<feature-name>` or `feature/<feature-name>`
- **Bug Fixes**: `fix/<bug-description>`
- **WIP / Experiments**: `wip/<topic>`
- **Pull Request Flow**: All pull requests target `main`.

---

## PR Process & CI Pipeline

Every pull request and push to `main` must pass the automated GitHub Actions CI Quality Gate (`.github/workflows/ci.yml`).

### CI Steps Executed
1. **Linting**:
   ```bash
   ruff check .
   ```
2. **Type Checking**:
   ```bash
   mypy football_core
   ```
3. **Architecture & Invariants**:
   ```bash
   pytest -v tests/test_quality_gates.py tests/test_layering_architecture.py tests/test_atomic_store_writes.py tests/test_hard02_swallow_sites.py
   ```
4. **Test Suite & Coverage Floor**:
   ```bash
   pytest --cov=football_core --cov-report=term-missing
   ```
   *Note: Fails if coverage for `football_core` drops below 70%.*
5. **Frontend Unit Tests**:
   ```bash
   node --test web/static/refresh.test.mjs
   ```

### Pre-PR Checklist
Before opening a pull request:
- [ ] Ensure virtual environment matches `requirements.txt`.
- [ ] Run `ruff check .` with zero errors.
- [ ] Run `mypy football_core` with zero errors.
- [ ] Execute `pytest` and verify architectural invariant tests pass.
- [ ] Verify coverage meets the kernel floor (`pytest --cov=football_core`).
- [ ] Verify frontend tests pass (`node --test web/static/refresh.test.mjs`).
- [ ] Ensure no secret keys, credentials, or `.env` files are tracked.
