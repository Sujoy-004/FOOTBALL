<!-- generated-by: gsd-doc-writer -->
# World Cup Dynamic Predictor

Live tournament odds for FIFA World Cup 2026 — in your terminal. Polls the BSD live match API, updates Elo ratings, ingests market odds and CatBoost ML predictions, runs 50K Monte Carlo simulations, and prints championship probabilities with deltas.

## How It Works

```
         ┌──────────────┐
         │  BSD API     │
         │ (live match  │◀──── BSD Predictions API
         │  data)       │      (/api/predictions/)
         └──────┬───────┘
                │ poll every 60s
                ▼
         ┌──────────────┐          ┌──────────────────┐
         │  fetcher.py  │──▶ played.json,             │
         └──────┬───────┘    played_groups.json       │
                │ new match?                          │
                ▼                                     │
         ┌──────────────┐    ┌──────────────────┐     │
         │  elo.py      │──▶│ Signal Cache      │     │
         │  elo_sync.py │   │  odds_cache.json  │◀────┤
         └──────┬───────┘   │  catboost_cache   │     │
                │           │  .json            │◀────┤
                ▼           └────────┬─────────┘     │
         ┌──────────────┐           │                │
         │  groups.py   │──▶ Group  │                │
         │  knockout.py │   standings               │
         └──────┬───────┘           │                │
                │                   ▼                │
                ▼           ┌──────────────────┐     │
         ┌──────────────┐   │_merge_signals_   │     │
         │ simulation   │   │ into_history()   │     │
         │ .py          │   │ → prediction_   │     │
         └──────┬───────┘   │   history.json   │     │
                │           └────────┬─────────┘     │
                ▼                    │                │
         ┌──────────────┐            ▼                │
         │  evaluation   │◀─── prediction_history.json │
         │ .py          │     (Brier, log loss,       │
         └──────┬───────┘      calibration, ECE)      │
                │                                     │
                ▼                                     │
         ┌──────────────┐                             │
         │  output.py   │──▶ ANSI console table       │
         └──────────────┘                             │
                                                       │
   ┌──────────────────┐                                │
   │  BSD Events      │── odds extracted ──────────────┘
   │  endpoint        │   (odds_home/draw/away)
   └──────────────────┘
```

**3-Signal Architecture:**

- **Elo**: eloratings.net + live match results (Per match + 24h sync, N/A cache TTL)
- **Market odds**: BSD events endpoint (odds_home/draw/away) (On poll, cache expiry, 12h TTL)
- **CatBoost**: BSD /api/predictions/ endpoint (On poll, cache expiry, 24h TTL)

All signals merge into `prediction_history.json` for per-signal evaluation and blended analysis.

**Tournament Structure:**
- 48 teams — 12 groups (A–L), 4 teams per group
- 104 matches — 72 group + 32 knockout over 6 rounds
- Annex C routing — 8 best third-placed teams advance to R32
- 7-step FIFA tiebreaker — group standings resolution

## Installation

```bash
# 1. Clone
git clone <repo-url>
cd worldcup_predictor

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set API key
cp .env.example .env
# Edit .env: add your BSD API key
```

Get a **free BSD API key** at `https://sports.bzzoiro.com/register/`.

## Quick Start

```bash
# Single fetch → simulate → print cycle
python main.py --once

# Continuous polling (60s interval, Ctrl+C to stop)
python main.py

# Reproducible results
python main.py --once --seed 42
```

## Usage

**Available Flags:**
- `--once`: Single cycle, then exit
- `--no-color`: Disable ANSI output
- `--seed N`: Reproducible simulation

**Continuous Mode:** Polls every 60s. New matches trigger:
1. Match result alert
2. Elo rating update (goal-difference K-multiplier, PK mode 0.75/0.25 split)
3. Signal cache refresh (market odds + CatBoost)
4. Merge signals into `prediction_history.json`
5. Full re-simulation (50K iterations)
6. Probability table with deltas from previous run
7. Evaluation metrics (Brier score, log loss, calibration)

No new matches? Prints a heartbeat. Hourly auto-refresh re-simulates anyway.

## Project Structure

```
worldcup_predictor/
├── main.py           # Entry point, CLI, polling loop, signal merge
├── src/
│   ├── elo.py        # Elo rating engine (K-multiplier, PK mode)
│   ├── elo_sync.py   # Sync from eloratings.net (24h)
│   ├── knockout.py   # Monte Carlo knockout + full tournament simulation
│   ├── fetcher.py    # BSD API fetch/match processing
│   ├── groups.py     # Group stage simulation & standings
│   ├── state.py      # JSON persistence, bracket validation, signal cache
│   ├── output.py     # ANSI console display
│   ├── evaluation.py # Brier, log loss, calibration, ECE
│   ├── constants.py  # All config constants
│   └── predictors/   # Signal ingestion pipeline (Phase 13)
│       ├── odds.py    # Market odds from BSD events endpoint
│       └── catboost.py# CatBoost from BSD predictions API
├── data/             # JSON state files (teams, groups, bracket,
│                     # odds_cache, catboost_cache, prediction_history, etc.)
├── tests/            # 26 modules, 611 tests
└── requirements.txt  # pytest, pytest-cov, python-dotenv (requests is transitive)
```

## Evaluation Framework

Phase 12b added comprehensive evaluation:

- **Brier score**: Mean squared probability error
- **Log loss**: Cross-entropy for probability predictions
- **Calibration curves**: 10-bin reliability diagram with ECE
- **Per-signal metrics**: Evaluate Elo, market odds, and CatBoost independently
- **Prediction history**: `data/prediction_history.json` persists match-level signals for longitudinal analysis

Evaluation runs automatically at startup, recording a baseline report to `data/eval_baseline_report.json`.

## Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src --cov-report=term-missing
```

611 passed across 26 test modules covering Elo, groups, knockout, fetcher, state, output, CLI, evaluation, odds, catboost, blender, enrichment, governance, and integration scenarios.
