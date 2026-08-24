# FOOTBALL — Probabilistic Tournament Prediction Engine

A modular Monte Carlo football tournament prediction engine. Team-strength
ratings (Elo) plus a small refinement ensemble feed a Poisson match model;
match probabilities are propagated through seeded Monte Carlo simulation of
two competition formats:

| Competition | Format | Route |
|---|---|---|
| **World Cup 2026** | 48 teams · 12 groups · Annex-C knockout routing | `/worldcup` |
| **UCL 2025/26** | 36-team Swiss league · playoff round · two-legged knockouts | `/ucl` |

The sole interface is a FastAPI web dashboard (`python -m web.server`).

## How predictions are made

```text
Elo ratings (ClubElo fetch + eloratings.net sync)
        ↓
5-signal ensemble   refined_elo · market_odds · rolling_form · squad_value · rest_days
        ↓           blended by EnsembleEngine (weighted average per outcome)
Match probabilities
        ↓
Poisson score model (per-match expected goals from rating difference)
        ↓
Seeded Monte Carlo tournament simulation (reproducible: seed=42 by default)
        ↓
Standings · knockout bracket · championship odds (+ bootstrap confidence intervals)
```

**Weights:** the runtime currently uses **uniform ensemble weights** (the
documented fallback). A single inverse-log-loss weight fitter exists in-repo
(`POST /worldcup/api/calibrate`, `POST /ucl/api/calibrate`), but there is not
yet enough labeled match history to produce *validated* learned weights — so
none are claimed.

## What this project does NOT claim

- No accuracy/"validated model" claims — evaluation metrics exist
  (Brier score, log-loss, ECE, TRPS) but labeled history is still accumulating.
- No machine-learned signals: every signal is a transparent formula over
  public data (ratings, results, schedule, market odds, squad values).
- No player/manager modelling, no third-party ML predictions.

## Quick start

```bash
pip install -r requirements.txt

cp .env.example .env          # optional: add API keys for live results
python -m web.server          # http://127.0.0.1:8080

python -m pytest              # run the test suite
```

Live results require a free football-data.org key (`FOOTBALL_DATA_ORG_KEY`)
or a BSD key (`BSD_API_KEY`). Without keys the dashboard runs on committed
seed data and simulated fixtures.

## Repository layout

```text
football_core/            shared kernel: Elo, Poisson sim, EnsembleEngine,
                          weight fitting, evaluation metrics, persistence
competitions/worldcup/    WC format logic + signal caches + tests + benchmark
competitions/ucl/         UCL Swiss/knockout logic + calibration + tests
web/                      FastAPI apps + vanilla-JS dashboard
tests/                    cross-cutting regression tests
docs/                     ARCHITECTURE · GETTING-STARTED · TESTING
```

See `docs/ARCHITECTURE.md` for the design, `docs/GETTING-STARTED.md` for a
walkthrough, `docs/TESTING.md` for how to verify everything.

No license — this project is not open source.
