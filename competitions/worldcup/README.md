<!-- generated-by: gsd-doc-writer -->
# World Cup Dynamic Predictor

Live tournament odds for FIFA World Cup 2026 — served via the unified web dashboard at `/worldcup`. Polls the BSD live match API, updates Elo ratings, ingests market odds and CatBoost ML predictions, runs 50K Monte Carlo simulations, and displays championship probabilities with deltas in a retro terminal interface.

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
         ┌──────────────┐   │  engine.py       │     │
         │  simulation   │   │ merge_signals_   │     │
         │  pipeline     │   │ into_history()   │     │
         └──────┬───────┘   └────────┬─────────┘     │
                │                    │                │
                ▼                    ▼                │
         ┌──────────────┐            │                │
         │  evaluation   │◀─── prediction_history.json│
         │ .py          │     (Brier, log loss,       │
         └──────┬───────┘      calibration, ECE)      │
                │                                     │
                ▼                                     │
         ┌──────────────┐                             │
         │  web server  │──▶ JSON over REST API       │
         │  (wc_app.py) │    → terminal UI / charts   │
         └──────────────┘                             │
   ┌──────────────────┐                                │
   │  BSD Events      │── odds extracted ──────────────┘
   │  endpoint        │   (odds_home/draw/away)
   └──────────────────┘
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key
cp .env.example .env
# Edit .env: add your BSD API key
```

Get a **free BSD API key** at `https://sports.bzzoiro.com/register/`.

## Running

Start the web dashboard from the project root:

```bash
python -m web.server
```

Then open **http://127.0.0.1:8080/worldcup**.

## Tournament Structure

- 48 teams — 12 groups (A–L), 4 teams per group
- 104 matches — 72 group + 32 knockout over 6 rounds
- Annex C routing — 8 best third-placed teams advance to R32
- 7-step FIFA tiebreaker — group standings resolution

## Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src --cov-report=term-missing
```
