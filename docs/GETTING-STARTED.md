<!-- generated-by: gsd-doc-writer -->
# Getting Started

This guide walks you through setting up and running the FOOTBALL Monte Carlo Prediction Engine — from cloning the repository to opening the web dashboard.

---

## Prerequisites

| Requirement | Version |
|---|---|
| **Python** | 3.10, 3.11, or 3.12 |
| **Git** | Any recent version |
| **pip** | Comes with Python 3.10+ |

No package manager (npm, yarn, cargo, etc.) is required — the engine runs directly from source.

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
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |

---

## API Key Setup (Optional)

The engine can run predictions using Elo ratings alone **without any API key**. To enable live match data, market odds, and CatBoost ML predictions, you need a free BSD (Bzzoiro Sports Data) API key.

### Get a key

1. Visit [https://sports.bzzoiro.com/register/](https://sports.bzzoiro.com/register/)
2. Register for a free account
3. Copy your API key from the dashboard

### Configure the key

```bash
cp competitions/worldcup/.env.example .env
# Edit .env and paste your key
# BSD_API_KEY=your_api_key_here
```

Without the API key, the engine falls back to Elo-only mode — predictions are still generated, but live data and signal blends are unavailable.

---

## Quick Start

### Web Dashboard (primary interface)

```bash
# Start the FastAPI web server (World Cup + UCL dashboards)
python -m web.server
```

Open **http://127.0.0.1:8080** in your browser. You'll see a competition selector — click **World Cup 2026** or **UCL 2025/26** to enter the dashboard.

**Routes:**

| URL | Content |
|---|---|
| `http://127.0.0.1:8080/` | Landing page — choose World Cup or UCL |
| `http://127.0.0.1:8080/worldcup` | World Cup dashboard — standings, bracket, odds, what-if |
| `http://127.0.0.1:8080/ucl` | UCL dashboard — Swiss standings, bracket, odds, signals |
| `http://127.0.0.1:8080/euro` | Euro placeholder (stub) |

---

## Web Dashboard Details

### World Cup 2026

Predicts 48 teams across 12 groups (A–L), 104 total matches (72 group + 32 knockout), with annex C routing for the 8 best third-placed teams. Runs 50,000 Monte Carlo iterations per cycle, blending 8 prediction signals with Brier-weighted calibration.

The dashboard shows:
- **Dashboard tab:** Top teams, champion probabilities, match results
- **Bracket tab:** Resolved R32 → R16 → QF → SF → FINAL with signal breakdowns
- **Standings tab:** Group tables with third-place bubble

**API endpoints:** `/worldcup/api/standings`, `/api/bracket`, `/api/evaluation`, `/api/signals`, `/api/blend`, `/api/governance`, `/api/refresh`, `/api/simulate`, `/api/what-if`, `/api/match/insight`, `/api/validation`, `/api/report`, `/api/calibrate`

### UCL 2025/26

Simulates a 36-team Swiss-system league phase (8 matchdays), followed by the playoff round, seeded R16 bracket, quarter-finals, semi-finals, and final. Uses a 5-signal ensemble (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays).

The dashboard shows:
- **Overview tab:** Top-4 teams, simulation stats
- **League Table tab:** Full 36-team standings with zone coloring
- **Bracket tab:** Playoff → R16 → QF → SF → FINAL
- **Odds tab:** Championship and qualification probabilities
- **Signals tab:** Signal blend breakdown

**API endpoints:** `/ucl/api/standings`, `/api/bracket`, `/api/odds`, `/api/signals`, `/api/simulate`, `/api/what-if`, `/api/match/insight`, `/api/validation`, `/api/report`, `/api/calibrate`, `/api/mode`

---

## Running Tests

### World Cup test suite

```bash
pytest competitions/worldcup/tests/
pytest competitions/worldcup/tests/ --cov=competitions.worldcup.src --cov-report=term-missing
```

### UCL test suite

```bash
pytest competitions/ucl/tests/ -x
```

### football_core test suite

```bash
pytest football_core/tests/ -v
pytest football_core/tests/ --cov=football_core --cov-report=term-missing
```

### All tests

```bash
python -m pytest football_core/tests/ competitions/worldcup/tests/ competitions/ucl/tests/
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'competitions'`

Make sure you are running commands from the project root (`FOOTBALL/`), not from inside a subdirectory.

### `connection refused` or timeout errors

The BSD API at `https://sports.bzzoiro.com/` must be reachable for live data. If you are behind a corporate firewall, the dashboard falls back to cached data or Elo-only mode.

### `ModuleNotFoundError: No module named 'fastapi'` / `No module named 'uvicorn'`

```bash
pip install fastapi uvicorn
```

### `Address already in use` when starting the web server

Port **8080** is already occupied. Either stop the process using that port or change the port in `web/server.py` (the `uvicorn.run()` call).

```bash
# Windows
netstat -ano | findstr :8080

# macOS / Linux
lsof -i :8080
```

---

## Next Steps

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Deep dive into system architecture, component relationships, and data flow.
- **[CONFIGURATION.md](CONFIGURATION.md)** — Environment variable reference.
- **[WEB_LAYER.md](WEB_LAYER.md)** — Web dashboard API endpoints and frontend details.
