<!-- generated-by: gsd-doc-writer -->
# Getting Started

This guide walks you through setting up and running the FOOTBALL Monte Carlo Prediction Engine — from cloning the repository to running your first tournament prediction.

---

## Prerequisites

| Requirement | Version |
|---|---|
| **Python** | 3.10, 3.11, or 3.12 |
| **Git** | Any recent version |
| **pip** | Comes with Python 3.10+ |

No package manager (npm, yarn, cargo, etc.) is required — the engine runs directly from source.

Additional Python packages will be installed in the next step (see [Installation](#installation)).

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Sujoy-004/FOOTBALL.git
cd FOOTBALL
```

### 2. Create and activate a virtual environment (recommended)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python -m venv venv
source venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r competitions/worldcup/requirements.txt
pip install requests numpy fastapi uvicorn
```

The core dependencies are:

| Package | Purpose |
|---|---|
| `pytest>=9.0` | Test runner |
| `pytest-cov>=7.1` | Test coverage reporting |
| `python-dotenv>=1.0` | Load `.env` for API keys |
| `requests` | HTTP client for the BSD sports data API |

---

## API Key Setup (Optional)

The engine can run predictions using Elo ratings alone **without any API key**. To enable live match data, market odds, and CatBoost ML predictions, you need a free BSD (Bzzoiro Sports Data) API key.

### Get a key

1. Visit [https://sports.bzzoiro.com/register/](https://sports.bzzoiro.com/register/)
2. Register for a free account
3. Copy your API key from the dashboard

### Configure the key

```bash
# Navigate to the worldcup competition directory
cd competitions/worldcup

# Copy the example file
cp .env.example .env

# Edit .env and paste your key
# BSD_API_KEY=your_api_key_here
```

Without the API key, the engine falls back to Elo-only mode — predictions are still generated, but live data and the full 8-signal blend pipeline are unavailable.

The eight prediction signals are:

| Signal | Source | Description |
|---|---|---|
| **Elo** | Built-in (always available) | Head-to-head Elo rating differential |
| **Market odds** | BSD API | Bookmaker-implied probabilities |
| **CatBoost** | BSD API | ML model prediction from team-level features |
| **Rolling form** | Computed locally | Recent performance trend (last N matches) |
| **Lineup strength** | Computed locally | Squad quality based on market value / lineup data |
| **Defensive quality** | BSD API | Expected goals conceded — defensive solidity metric |
| **Manager effect** | BSD API | Historical manager performance vs. opponent levels |
| **Availability / injury** | BSD API | Key player absences and squad depth impact |

Each signal is independently calibrated and blended via inverse-Brier weighting — signals with lower historical Brier scores (more accurate) carry more weight in the final prediction.

---

## Quick Start Examples

### World Cup 2026 (`wc-predict`)

```bash
# Single prediction cycle — fetch, simulate, print, then exit
python -m competitions.worldcup.main --once

# Continuous polling mode (polls BSD API every 60 seconds)
python -m competitions.worldcup.main

# Reproducible simulation with a fixed seed
python -m competitions.worldcup.main --once --seed 42

# Full list of flags: --once, --no-color, --seed N, --ai-preview, --match-detail, --league ID, --list-leagues
```

The World Cup predictor simulates 48 teams across 12 groups (A–L), 104 total matches (72 group + 32 knockout), with annex C routing for the 8 best third-placed teams. It runs 50,000 Monte Carlo iterations per cycle.

### UEFA Champions League (`ucl-predict`)

```bash
# Run with 10,000 iterations
python -m competitions.ucl.main -n 10000

# Reproducible run with a fixed seed
python -m competitions.ucl.main -n 10000 -s 42

# Export results to JSON
python -m competitions.ucl.main -n 10000 -s 42 -o results.json

# Validate predictions against real BSD match results (requires API key)
python -m competitions.ucl.main -n 10000 --validate --api-key YOUR_KEY

# Key flags: -n N, -s N, -o FILE, --validate, --api-key KEY, --fixture-source {auto,repo,bsd}, --mode {simulate,replay,live}, --replay-data FILE, --use-glicko, --weights, --show-breakdown, --verbose, --what-if, --report, --calibrate, --calibrate-temp, --validate-calibrated, --tier, --calibrated, --show-ci
```

The UCL predictor simulates a 36-team Swiss-system league phase (8 matchdays), followed by the playoff round, seeded R16 bracket, quarter-finals, semi-finals, and final.

Three simulation modes are available:

- **`--mode simulate`** (default) — Full synthetic simulation with no real-world match data.
- **`--mode replay`** — Replay a known schedule from a JSON file (requires `--replay-data FILE`).
- **`--mode live`** — Fetch real match results from the BSD API to seed the simulation (requires API key).

The `--fixture-source` flag controls where fixtures are loaded from: `auto` (try BSD, fall back to local repo), `repo` (local fixtures only), or `bsd` (BSD API only, fails if unavailable).

### Web Dashboard

```bash
# Start the FastAPI web server (World Cup + UCL dashboards)
python -m web.server
```

The server starts on **http://127.0.0.1:8080** and serves:

| URL | Content |
|---|---|
| `http://127.0.0.1:8080/` | Landing page (SPA shell) — choose World Cup or UCL |
| `http://127.0.0.1:8080/worldcup` | World Cup dashboard — standings, bracket, odds, evaluation, what-if |
| `http://127.0.0.1:8080/ucl` | UCL dashboard — Swiss standings, playoff bracket, signal breakdowns |
| `http://127.0.0.1:8080/euro` | Euro placeholder (stub) |

On first startup, the server pre-computes all prediction data and caches it in memory — this may take 10–30 seconds. The World Cup sub-app writes a persistent `web/cache.json` file so subsequent restarts are faster.

To stop the server, press **Ctrl+C** in the terminal.

> **Note:** The web server uses the same BSD API key (`BSD_API_KEY` in your `.env`) for live data refresh. Without the key, the dashboard falls back to cached prediction data and Elo-only mode.

### UEFA Euro 2024 (`euro-predict` — dormant)

```bash
# Single cycle
python -m competitions.euro.main --once

# Continuous polling
python -m competitions.euro.main
```

The Euro predictor is currently dormant. It shares its architecture with the World Cup predictor.

---

## Running Tests

### World Cup test suite (614 tests)

```bash
# Run all tests from the project root
pytest competitions/worldcup/tests/

# Run with coverage
pytest competitions/worldcup/tests/ --cov=competitions.worldcup.src --cov-report=term-missing
```

### UCL test suite (438 tests)

```bash
pytest competitions/ucl/tests/ -x
```

### football_core test suite (109 tests)

```bash
pytest football_core/tests/ -v
pytest football_core/tests/ --cov=football_core --cov-report=term-missing
```

The football_core library contains the shared signal computation, Elo engine, and enrichment pipeline used by both competition predictors.

---

## Troubleshooting

### `BSD_API_KEY not set` error

The API key is **optional** — the engine works in Elo-only mode without it. If you see this error, one of the following applies:

- You ran a command that explicitly requires the API key (e.g., `--validate` for UCL without providing `--api-key`). Pass the key via the flag or set the environment variable.
- You have a stale `.env` file with an empty or invalid key. Either set a valid key or remove/rename the `.env` file.

### `Python 3.13 not supported`

The engine is tested against Python 3.10, 3.11, and 3.12. If you are on Python 3.13, create a virtual environment with an older version:

```bash
# Windows (adjust path to your Python 3.12 installation)
C:\Python312\python -m venv venv

# macOS / Linux (using pyenv)
pyenv install 3.12
pyenv local 3.12
python -m venv venv
```

### `ModuleNotFoundError: No module named 'competitions'`

Make sure you are running commands from the project root (`FOOTBALL/`), not from inside a subdirectory. The engine uses relative imports that require the root as the working directory.

### `connection refused` or timeout errors

The BSD API at `https://sports.bzzoiro.com/` must be reachable for live data. If you are behind a corporate firewall or have no internet connection, the engine will fall back to cached data or Elo-only mode.

### `ModuleNotFoundError: No module named 'fastapi'` / `No module named 'uvicorn'`

The web server requires `fastapi` and `uvicorn`. Install them:

```bash
pip install fastapi uvicorn
```

If you already installed dependencies, you may need to re-run the full install command:

```bash
pip install -r competitions/worldcup/requirements.txt
pip install requests numpy fastapi uvicorn
```

### `Address already in use` when starting the web server

Port **8080** is already occupied. Either stop the process using that port or change the port in `web/server.py` (the `uvicorn.run()` call on line 80).

To find the process using port 8080:

```bash
# Windows
netstat -ano | findstr :8080

# macOS / Linux
lsof -i :8080
```

---

## Next Steps

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Deep dive into system architecture, component relationships, data flow, and web dashboard layout.
- **[CONFIGURATION.md](CONFIGURATION.md)** — Full environment variable reference and configuration options.
- **[README.md](../README.md)** — Project overview, usage examples for all three competitions, and directory structure.
