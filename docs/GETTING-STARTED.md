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
pip install requests numpy
```

The core dependencies are:

| Package | Purpose |
|---|---|
| `pytest>=9.0` | Test runner |
| `pytest-cov>=7.1` | Test coverage reporting |
| `python-dotenv>=1.0` | Load `.env` for API keys |
| `requests` | HTTP client for the BSD sports data API |
| `numpy` | Numerical operations in the simulation engine |

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

Without the API key, the engine falls back to Elo-only mode — predictions are still generated, but live data and advanced signals (market odds, CatBoost) are unavailable.

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

# Full list of flags: --once, --no-color, --seed N, --ai-preview, --match-detail
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

# Full list of flags: -n N, -s N, -o FILE, --validate, --api-key KEY
```

The UCL predictor simulates a 36-team Swiss-system league phase (8 matchdays), followed by the playoff round, seeded R16 bracket, quarter-finals, semi-finals, and final.

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

### World Cup test suite (613 tests)

```bash
# Run all tests from the project root
pytest competitions/worldcup/tests/

# Run with coverage
pytest competitions/worldcup/tests/ --cov=competitions.worldcup.src --cov-report=term-missing
```

### UCL test suite (149 tests)

```bash
pytest competitions/ucl/tests/ -x --timeout=60
```

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

---

## Next Steps

- **[ARCHITECTURE.md](FOOTBALL_ENGINE_ARCHITECTURE.md)** — Deep dive into system architecture, component relationships, and data flow.
- **[CONFIGURATION.md](CONFIGURATION.md)** — Full environment variable reference and configuration options.
- **[README.md](../README.md)** — Project overview, usage examples for all three competitions, and directory structure.
