<!-- generated-by: gsd-doc-writer -->
# FOOTBALL Monte Carlo Prediction Engine

A Python Monte Carlo simulation engine that predicts football tournament outcomes — knockout probabilities, group standings, and championship odds — across three major competitions. Each competition is a standalone CLI tool sharing a common library (`football_core/`) for Elo ratings, Poisson-based match simulation, and prediction evaluation.

| Competition | Status | CLI Tool | Run Command | Tests |
|---|---|---|---|---|
| **World Cup 2026** | Active — continuous polling (60s) | `wc-predict` | `python -m competitions.worldcup.main` | 613 |
| **UCL 2025/26** | Active — single-run Monte Carlo | `ucl-predict` | `python -m competitions.ucl.main` | 149 |
| **Euro 2024** | Dormant — continuous polling | `euro-predict` | `python -m competitions.euro.main` | — |

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd FOOTBALL

# 2. Install Python dependencies
pip install -r competitions/worldcup/requirements.txt
pip install requests numpy

# 3. Set your BSD API key (required for live match data and market odds)
cp competitions/worldcup/.env.example competitions/worldcup/.env
# Edit .env and set BSD_API_KEY=your_key_here
# Get a free key at https://sports.bzzoiro.com/register/

# 4. Run a single World Cup prediction cycle
python -m competitions.worldcup.main --once
```

---

## Usage

### World Cup 2026 (continuous polling)

Fetches live match data from the BSD API every 60 seconds, updates Elo ratings, refreshes signal caches (market odds, CatBoost ML predictions), runs 50,000 Monte Carlo iterations, and prints championship probability tables with deltas.

```bash
# Single fetch → simulate → print cycle, then exit
python -m competitions.worldcup.main --once

# Continuous polling mode (Ctrl+C for graceful shutdown)
python -m competitions.worldcup.main

# Reproducible simulation with a fixed seed
python -m competitions.worldcup.main --once --seed 42

# Available flags: --once, --no-color, --seed N, --ai-preview, --match-detail [TABLE|MATCH_ID]
```

The World Cup competition supports 48 teams across 12 groups (A–L), 104 total matches (72 group + 32 knockout), and annex C routing for third-placed teams.

### UCL 2025/26 (single-run)

Runs a Monte Carlo simulation of the Champions League league phase and knockout tree, then prints a full result summary including the league table, playoff rounds, knockout bracket, and championship odds.

```bash
# Run with 10,000 iterations and a fixed seed
python -m competitions.ucl.main -n 10000 -s 42

# Run and export results to JSON
python -m competitions.ucl.main -n 10000 -s 42 -o results.json

# Cross-check predictions against real BSD match results
python -m competitions.ucl.main --validate --api-key KEY

# Available flags: -n N (iterations), -s N (seed), -o FILE (output), --validate, --api-key KEY
```

The UCL competition uses a Swiss-system league phase (36 teams, 8 matchdays) followed by a playoff round and a 16-team knockout bracket.

### Euro 2024 (dormant)

Continuous polling predictor for UEFA Euro 2024. Shares architecture with the World Cup predictor but is currently in a dormant state.

```bash
# Single cycle
python -m competitions.euro.main --once

# Continuous polling
python -m competitions.euro.main
```

---

## Project Structure

```
FOOTBALL/
├── football_core/              ← Shared engine library
│   ├── elo.py                  Elo rating math (expected_score, update_ratings, K-factor)
│   ├── elo_sync.py             Elo sync from eloratings.net
│   ├── fetcher.py              BSD API fetch + match dedup
│   ├── groups.py               Poisson simulation + FIFA tiebreaker chain
│   ├── knockout.py             Generic round simulation primitive
│   ├── evaluation.py           Brier score, log loss, calibration, ECE
│   ├── state.py                JSON persistence layer
│   ├── math_utils.py           Sigmoid and other math helpers
│   ├── display.py              Terminal output helpers
│   ├── constants.py            Shared configuration constants
│   └── predictors/             Signal ingestion pipeline
│       ├── odds.py             Market odds fetcher
│       └── catboost.py         CatBoost prediction fetcher
│
├── competitions/
│   ├── worldcup/               ← World Cup 2026 (active)
│   │   ├── main.py             CLI entry point, polling loop, governance, blending
│   │   ├── requirements.txt    pytest, pytest-cov, python-dotenv
│   │   ├── .env.example        BSD_API_KEY template
│   │   ├── config.json         League ID (27)
│   │   ├── src/                WC-specific modules (blender, governance, output, etc.)
│   │   ├── tests/              26 modules, 613 tests
│   │   ├── data/               JSON state files (generated at runtime)
│   │   └── .github/workflows/  CI pipeline (Python 3.10–3.12, pytest --cov)
│   │
│   ├── ucl/                    ← UCL 2025/26 (active)
│   │   ├── main.py             CLI entry point, single-run Monte Carlo
│   │   ├── src/                UCL-specific simulation + knockout modules
│   │   ├── tests/              10 modules, 149 tests
│   │   └── data/               Fixture, bracket rules, Elo data
│   │
│   └── euro/                   ← Euro 2024 (dormant)
│       ├── main.py             CLI entry point, continuous polling
│       ├── config.py           Euro-specific configuration
│       └── data/               Teams, groups, bracket data
│
└── docs/
    ├── FOOTBALL_ENGINE_ARCHITECTURE.md   Detailed architecture and design decisions
    └── COMMONALITY_REPORT.md             Cross-competition commonality analysis
```

---

## Detailed Documentation

See the `docs/` directory for in-depth technical documentation:

- **[FOOTBALL_ENGINE_ARCHITECTURE.md](docs/FOOTBALL_ENGINE_ARCHITECTURE.md)** — System architecture, component relationships, data flow, and design rationale for all three competitions.
- **[COMMONALITY_REPORT.md](docs/COMMONALITY_REPORT.md)** — Analysis of shared vs. competition-specific code across the World Cup, UCL, and Euro implementations.

---

## Requirements

- **Python:** 3.10, 3.11, or 3.12
- **Dependencies:** pytest, pytest-cov, python-dotenv, requests, numpy
- **API key:** A free [BSD API key](https://sports.bzzoiro.com/register/) for live match data, market odds, and CatBoost predictions. The engine can run in Elo-only mode without an API key, but will not fetch live data or signals.

---

## License

No license — this project is not open source.
