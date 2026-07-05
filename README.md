<!-- generated-by: gsd-doc-writer -->
# FOOTBALL Monte Carlo Prediction Engine

A Python Monte Carlo simulation engine that predicts football tournament outcomes — knockout probabilities, group standings, and championship odds — across three major competitions. Each competition is a standalone CLI tool sharing a common library (`football_core/`) for Elo ratings, Poisson-based match simulation, and prediction evaluation.

| Competition | Status | CLI Tool | Run Command | Tests |
|---|---|---|---|---|
| **World Cup 2026** | Active — continuous polling (60s) | `wc-predict` | `python -m competitions.worldcup.main` | 614 |
| **UCL 2025/26** | Active — single-run Monte Carlo | `ucl-predict` | `python -m competitions.ucl.main` | 438 |
| **Euro 2024** | Dormant — continuous polling | `euro-predict` | `python -m competitions.euro.main` | — |
| **football_core** | Shared library | — | — | 109 |

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

## Usage

### World Cup 2026 (continuous polling)

Fetches live match data from the BSD API every 60 seconds, updates Elo ratings, refreshes signal caches (market odds, CatBoost ML predictions, and 6 additional signals), runs 50,000 Monte Carlo iterations, and prints championship probability tables with deltas.

```bash
# Single fetch → simulate → print cycle, then exit
python -m competitions.worldcup.main --once

# Continuous polling mode (Ctrl+C for graceful shutdown)
python -m competitions.worldcup.main

# Reproducible simulation with a fixed seed
python -m competitions.worldcup.main --once --seed 42

# List all available BSD league IDs and names
python -m competitions.worldcup.main --list-leagues

# Simulate a different league by ID
python -m competitions.worldcup.main --once --league 27

# Available flags: --once, --no-color, --seed N, --ai-preview, --match-detail [TABLE|MATCH_ID], --league ID, --list-leagues
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

# Run in replay mode with historical match data
python -m competitions.ucl.main --mode replay --replay-data matches.json

# Available flags: -n N (iterations), -s N (seed), --use-glicko (Bayesian uncertainty),
#   -o FILE (output), --validate, --api-key KEY, --tier {cross-tournament,walk-forward,replay,all},
#   --fixture-source {auto,repo,bsd}, --mode {simulate,replay,live}, --replay-data FILE,
#   --what-if TEAM.PARAM=VALUE, --report FILE, --calibrate, --calibrate-temp FILE,
#   --validate-calibrated, --weights K=V,K=V, --show-breakdown, --calibrated, --show-ci,
#   --verbose
```

The UCL competition uses a Swiss-system league phase (36 teams, 8 matchdays) followed by a playoff round and a 16-team knockout bracket.

### Euro 2024 (dormant)

Continuous polling predictor for UEFA Euro 2024. Shares architecture with the World Cup predictor but is currently in a dormant state.

```bash
# Single cycle with reproducible seed
python -m competitions.euro.main --once --seed 42

# Continuous polling
python -m competitions.euro.main
```

## Project Structure

```
FOOTBALL/
├── football_core/              ← Shared engine library
│   ├── elo.py                  Elo rating math
│   ├── elo_fetcher.py          Elo rating fetch from external sources
│   ├── elo_sync.py             Elo sync from eloratings.net
│   ├── fetcher.py              BSD API fetch + match dedup
│   ├── groups.py               Poisson simulation + FIFA tiebreaker chain
│   ├── knockout.py             Generic round simulation primitive
│   ├── blender.py              Signal blending and weighting
│   ├── enrichment.py           Match data enrichment pipeline
│   ├── evaluation.py           Brier score, log loss, calibration, ECE
│   ├── state.py                JSON persistence layer
│   ├── glicko.py               Glicko-1 Bayesian rating with uncertainty
│   ├── math_utils.py           Sigmoid and other math helpers
│   ├── constants.py            Shared configuration constants
│   ├── signal.py               Signal computation framework
│   ├── provider.py             Data provider framework
│   ├── result_provider.py      Result data provider
│   ├── providers/              BSD data providers
│   │   ├── manager.py          Manager profile fetcher & parser
│   │   ├── player.py           Player profile fetcher & parser
│   │   └── team.py             Team ID-to-name mapping
│   ├── signals/                8 prediction signal implementations
│   │   ├── availability.py     Availability/injury impact signal
│   │   ├── defensive_quality.py Defensive quality signal
│   │   ├── manager_effect.py   Manager effect signal
│   │   ├── market_odds.py      Market odds signal
│   │   ├── refined_elo.py      Refined Elo signal
│   │   ├── rest_days.py        Rest days signal
│   │   ├── rolling_form.py     Rolling form signal
│   │   └── squad_value.py      Squad value signal
│   ├── predictors/             Signal ingestion pipeline
│   │   ├── odds.py             Market odds fetcher
│   │   └── catboost.py         CatBoost prediction fetcher
│   └── tests/                  7 modules, 109 tests
│       ├── test_availability_signal.py
│       ├── test_defensive_quality_signal.py
│       ├── test_evaluation.py
│       ├── test_manager_effect_signal.py
│       ├── test_manager_provider.py
│       └── test_player_provider.py
│
├── competitions/
│   ├── worldcup/               ← World Cup 2026 (active)
│   │   ├── main.py             CLI entry point, polling loop, governance, blending
│   │   ├── requirements.txt    pytest, pytest-cov, python-dotenv
│   │   ├── .env.example        BSD_API_KEY template
│   │   ├── config.json         League ID (27)
│   │   ├── src/                WC-specific modules (blender, governance, output, etc.)
│   │   │   └── predictors/     Signal ingestion (odds, catboost, form, lineup, availability, manager_signals)
│   │   ├── tests/              26 modules, 614 tests
│   │   ├── data/               JSON state files (generated at runtime)
│   │   ├── docs/               Archive docs
│   │   └── .github/workflows/  CI pipeline (Python 3.10–3.12, pytest --cov)
│   │
│   ├── ucl/                    ← UCL 2025/26 (active)
│   │   ├── main.py             CLI entry point, single-run Monte Carlo
│   │   ├── display.py          Formatted terminal output
│   │   ├── result.py           SimulationResult contract (display-layer boundary)
│   │   ├── report.py           Structured JSON report builder
│   │   ├── config/             Signal weights and calibration JSON
│   │   ├── src/                UCL-specific simulation + knockout modules
│   │   ├── tests/              22 modules, 438 tests
│   │   └── data/               Fixture files, bracket rules, team aliases
│   │
│   └── euro/                   ← Euro 2024 (dormant)
│       ├── main.py             CLI entry point, continuous polling
│       ├── config.py           Competition configuration
│       ├── display.py          Formatted terminal output
│       ├── simulation.py       Euro-specific simulation logic
│       ├── __init__.py         Package init + sys.path bootstrap
│       └── data/               Teams, groups, bracket data
│
└── docs/
    ├── ARCHITECTURE.md            System architecture, data flow, design decisions
    ├── ARCHITECTURE_RESEARCH.md Architecture research notes
    ├── CONFIGURATION.md        Environment variables and CLI reference
    ├── DEVELOPMENT.md          Development setup and contribution guide
    ├── GETTING-STARTED.md      Installation and quick start
    ├── TESTING.md              Test framework, layout, and patterns
    ├── FOOTBALL_ENGINE_ARCHITECTURE.md   Detailed architecture document
    └── COMMONALITY_REPORT.md   Cross-competition commonality analysis
```

## Requirements

- **Python:** 3.10, 3.11, or 3.12
- **Dependencies:** pytest, pytest-cov, python-dotenv, requests, numpy
- **API key:** A free [BSD API key](https://sports.bzzoiro.com/register/) for live match data, market odds, and CatBoost predictions. The engine can run in Elo-only mode without an API key, but will not fetch live data or signals.

## License

No license — this project is not open source.
