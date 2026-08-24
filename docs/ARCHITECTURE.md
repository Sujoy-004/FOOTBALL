# ARCHITECTURE

## Overview

```text
Elo ratings (ClubElo API + eloratings.net sync)
        ↓
5-signal refinement ensemble          refined_elo · market_odds ·
(EnsembleEngine, weighted blend)      rolling_form · squad_value · rest_days
        ↓
Match probabilities  (Poisson score model driven by rating difference)
        ↓
Seeded Monte Carlo tournament simulation
        ↙                          ↘
World Cup 2026                 UCL 2025/26
12 groups + Annex-C + TPP     Swiss league + playoff + seeded R16
        ↘                          ↙
        FastAPI dashboard (standings · bracket · odds · signals · what-if)
```

## football_core (shared kernel)

| Module | Responsibility |
|---|---|
| `elo.py` | Elo math (goal-diff-weighted K, shootout results) |
| `elo_fetcher.py` / `elo_sync.py` | ClubElo fetch; eloratings.net TSV sync with graduated correction |
| `groups.py` | Poisson match model: expected goals from rating diff, cached CDF sampling, tiebreaker chains |
| `knockout.py` | Knockout primitives: single match (+ET/pens), two-legged ties |
| `signal.py` | `Signal` protocol, registry, `PredictionContext` |
| `blender.py` | **The** ensemble: `EnsembleEngine`, `compute_log_loss_weights`, `compute_signal_contributions`. Nothing else. |
| `signals/` | The five signal implementations |
| `predictors/odds.py` | Market-odds ingestion from BSD event payloads (vig removal) |
| `data_providers/` | BSD + football-data.org result/event providers (`fetch_matches` only) |
| `evaluation.py` | Brier, log-loss, ECE, calibration curve, TRPS (numpy only here) |
| `state.py` | Atomic JSON persistence helpers |
| `provider.py` | Protocols: `DataProvider`, `FixtureProvider`, `MatchResultProvider`, `ResultHistoryProvider` |

## Signals

| Signal | Data source | Degradation |
|---|---|---|
| `refined_elo` | context Elo ratings (ClubElo) | defaults to 1500 |
| `market_odds` | odds on BSD event payloads, devigged | uniform ⅓⅓⅓ |
| `rolling_form` | recent results via a result-history provider | neutral form |
| `squad_value` | committed squad-value JSON (log-ratio sigmoid) | median imputation → uniform |
| `rest_days` | fixture schedule gaps | assumes 7 days rest |

World Cup additionally carries its own live-synced `elo` signal as base;
UCL's base rating enters through `refined_elo`.

## Weight resolution & calibration

Precedence everywhere: explicit weights dict → committed
`config/signal_weights.json` → **uniform fallback** (logged).

Fitting uses one method only: inverse multiclass log-loss
(`compute_log_loss_weights`, floored at 0.05, normalized). Entry points:
`POST /worldcup/api/calibrate` (fits on recorded prediction history) and
`POST /ucl/api/calibrate` (fits on replay/results data). Both write provenance
(`method`, `source`, `n_matches`) and refuse to fit below the per-signal
sample threshold.

**Current status:** insufficient labeled history exists, so the runtime runs
on the uniform fallback. No validated-weight claims are made.

## Reproducibility

Every simulation takes an explicit seed (default 42). Same code + same data +
same seed ⇒ identical probabilities. Bootstrap confidence intervals quantify
Monte-Carlo noise on championship odds.
