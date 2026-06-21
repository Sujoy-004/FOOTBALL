<!-- generated-by: gsd-doc-writer -->
# Architecture — World Cup Dynamic Predictor

Live tournament odds in your terminal. Single-process CLI, polling loop, Elo-based Monte Carlo simulation with multi-signal evaluation (Elo, market odds, CatBoost ML).

## System Overview

```
         ┌──────────────────┐
         │   BSD API        │◄── polls every 60s
         │  (football-data) │
         └──────┬───────────┘
                │ match results
                ▼
   ┌─────────────────────────────────────┐
   │              main.py                │
   │  ┌───────┐ ┌────────────┐           │
   │  │catch- │ │draw back-  │           │
   │  │up     │ │fill        │           │
   │  └───┬───┘ └─────┬──────┘           │
   │      │            │                 │
   │      ▼            ▼                 │
   │  ┌─────────────────────┐            │
   │  │    Elo sync          │            │
   │  │ (eloratings.net,     │            │
   │  │  24h interval)       │            │
   │  └──────────┬──────────┘            │
   │             ▼                       │
   │  ┌──────────────────────────────┐   │
   │  │  Signal Ingestion            │   │
   │  │  ┌──────────┐ ┌───────────┐ │   │
   │  │  │odds_cache│ │catboost_  │ │   │
   │  │  │.json     │ │cache.json │ │   │
   │  │  └─────┬────┘ └─────┬─────┘ │   │
   │  │        │             │       │   │
   │  │        ▼             ▼       │   │
   │  │  _merge_signals_into_history │   │
   │  │         │                   │   │
   │  │         ▼                   │   │
   │  │  prediction_history.json    │   │
   │  │         │                   │   │
   │  │         ▼                   │   │
   │  │  evaluation.py              │   │
   │  └──────────┬──────────────────┘   │
   │             ▼                      │
   │  ┌─────────────────────┐           │
   │  │  Monte Carlo sim    │           │
   │  │  (50K iterations)   │           │
   │  └──────────┬──────────┘           │
   │             ▼                      │
   │  ┌─────────────────────┐           │
   │  │   output.py         │           │
   │  │ (ANSI terminal)     │           │
   │  └─────────────────────┘           │
   └─────────────────────────────────────┘
```

## Module Map

```
main.py
  ├── constants.py          — config values, URLs, group sizes, TTLs
  ├── elo.py                — expected_score, update_ratings, apply_elo_update, compute_k_factor
  ├── elo_sync.py           — fetch → parse → validate → correct (eloratings.net)
  ├── state.py              — all JSON I/O (atomic writes), signal cache helpers
  ├── fetcher.py            — BSD API calls, match processing
  ├── groups.py             — Poisson sim, standings, tiebreakers, Annex C
  ├── knockout.py           — run_full_simulation (groups → R32 → ... → FINAL)
  ├── simulation.py         — lightweight knockout-only sim (legacy)
  ├── output.py             — ANSI terminal display
  ├── evaluation.py         — Brier, log loss, calibration, multi-signal evaluation
  └── predictors/
      ├── __init__.py       — prediction signal ingestion package
      ├── odds.py           — market odds vig removal, fetch → parse → cache pipeline
      └── catboost.py       — CatBoost ML prediction fetch from BSD API, cache pipeline
```

## Data Flow (startup → loop)

1. **Load state** — `data/*.json` (teams, groups, bracket, annex_c, played, played_groups)
2. **Historical catch-up** — fetch all finished matches from WC_START (2026-06-11) to today via BSD API
3. **Draw backfill** — replay historical draws through Elo pipeline (one-shot)
4. **Eval baseline** — Brier/log-loss/ECE metrics against past matches
5. **Prediction history migration** — migrate flat entries to compound `signals` dict format (one-shot)
6. **Signal ingestion** — fetch CatBoost predictions from BSD API, merge into `prediction_history.json`
7. **Elo sync** — fetch eloratings.net World.tsv, compare, apply graduated corrections (24h interval)
8. **Continuous loop:**
   ```
   ┌─ sleep 60s ──► poll BSD API ──► new match? ──► Elo update ──►
   │                                                               │
   │   refresh signal caches (odds+catboost if TTL expired)        │
   │        │                                                      │
   │        ▼                                                      │
   │   _merge_signals_into_history()                               │
   │        │                                                      │
   │        ▼                                                      │
   │   re-simulate (50K) ──► print ──┐                            │
   │                                                               │
   └───────────────────────────────────────────────────────────────┘
   ```

## Tournament Simulation (run_full_simulation)

```
Groups (12 × 4 teams)
    │
    ▼  72 matches via Poisson scoring
Group stage
    │
    ▼  7-step tiebreaker per group
Standings (positions 1-4)
    │
    ▼  5-step cross-group tiebreaker
Third-place ranking (12 teams)
    │
    ▼  top 2 per group (24) + top 8 third-place
Advancers (32 teams)
    │
    ▼ Annex C lookup → R32 matchups
Round of 32 (16 matches, Elo win probability)
    │
    ▼ via source_matches
Round of 16 → QF → SF
    │
    ▼ SF losers → TPP
Third-place playoff
    │
    ▼
FINAL
    │
    ▼ aggregate counts → probabilities per team
50,000 Monte Carlo iterations
```

## Key Abstractions

| Abstraction | File | Role |
|---|---|---|
| `expected_score(rating_a, rating_b)` | `elo.py:19` | Elo win probability formula |
| `apply_elo_update(match, teams)` | `elo.py:140` | K-factor adjusted rating update |
| `compute_k_factor(goal_diff, base_K)` | `elo.py:39` | Goal-difference Elo K-multiplier (eloratings.net formula) |
| `sync_elo_from_eloratings(teams)` | `elo_sync.py:277` | Graduated correction pipeline |
| `simulate_group_matches(...)` | `groups.py:187` | Poisson score generation |
| `compute_standings(results, elo)` | `groups.py:556` | 7-step tiebreaker + standings |
| `rank_third_placed(standings)` | `groups.py:664` | 5-step cross-group ranking |
| `resolve_r32_matchups(...)` | `groups.py:770` | Annex C routing |
| `run_full_simulation(...)` | `knockout.py:224` | Full tournament Monte Carlo |
| `process_matches(raw, ...)` | `fetcher.py:86` | BSD → bracket match resolution |
| `validate_api_key()` | `main.py:624` | BSD_API_KEY check + HTTP 401 |
| `remove_vig(odds_home, odds_draw, odds_away)` | `predictors/odds.py:22` | Bookmaker vig removal via 1/odds normalization |
| `fetch_and_cache_odds(...)` | `predictors/odds.py:165` | Market odds fetch → parse → cache pipeline (12h TTL) |
| `fetch_and_cache_catboost(...)` | `predictors/catboost.py:209` | CatBoost ML fetch → parse → cache (24h TTL, 3-retry backoff) |
| `load_signal_cache(filename)` | `state.py:699` | Load signal cache dict (graceful bootstrap) |
| `save_signal_cache(cache, filename)` | `state.py:720` | Atomic save of signal cache |
| `is_cache_valid(cache, ttl_hours)` | `state.py:734` | TTL-based cache expiry check |
| `migrate_prediction_history()` | `state.py:775` | Flat→compound schema migration (idempotent) |
| `_merge_signals_into_history()` | `main.py:37` | Inject odds/catboost signals into prediction_history entries |
| `evaluate_all_matches(...)` | `evaluation.py:72` | Multi-signal evaluation (elo, market_odds, catboost, blended) |

## Data Persistence

| File | Purpose |
|---|---|
| `data/teams.json` | Team names + Elo ratings (static input, mutated at runtime) |
| `data/groups.json` | Group definitions (A-L, teams, match slots) |
| `data/bracket.json` | Knockout bracket (match_ids, source_matches) |
| `data/annex_c.json` | 495-entry third-place routing table |
| `data/played.json` | Knockout match results (runtime) |
| `data/played_groups.json` | Group match results (runtime) |
| `data/elo_applied.json` | Dedup guard — match_ids with applied Elo |
| `data/eloratings_cache.json` | Last-known-good Elo values (sync fallback) |
| `data/elo_update_log.json` | Audit trail — all Elo corrections |
| `data/team_aliases.json` | Team name → BSD API alias mappings |
| `data/eval_baseline_report.json` | Brier/log-loss/ECE metrics |
| `data/prediction_history.json` | Per-match prediction + actual + signals (compound format) |
| `data/odds_cache.json` | Market odds cache with TTL (12h) |
| `data/catboost_cache.json` | CatBoost ML prediction cache with TTL (24h) |

## Directory Layout

```
.
├── main.py              — entry point, CLI, polling loop
├── requirements.txt     — pytest, pytest-cov, python-dotenv, requests
├── data/                — all JSON state (static + runtime)
├── src/
│   ├── __init__.py
│   ├── constants.py     — K_FACTOR, API_URL, WC_START_DATE, group sizes, signal TTLs
│   ├── elo.py           — Elo engine (expected_score, compute_k_factor, apply_elo_update)
│   ├── elo_sync.py      — eloratings.net sync pipeline
│   ├── state.py         — JSON load/save (atomic writes), signal cache helpers, schema migration
│   ├── fetcher.py       — BSD API client
│   ├── groups.py        — group sim, standings, tiebreakers, Annex C
│   ├── knockout.py      — full tournament sim (groups + knockout)
│   ├── simulation.py    — legacy knockout-only sim
│   ├── output.py        — ANSI display (probabilities, standings)
│   ├── evaluation.py    — Brier, log loss, calibration, multi-signal evaluation
│   └── predictors/
│       ├── __init__.py  — signal ingestion package
│       ├── odds.py      — market odds vig removal, fetch → parse → cache
│       └── catboost.py  — CatBoost ML prediction fetch from BSD API
├── tests/               — 20 test files (pytest, 387 passed, 1 skipped)
├── scripts/             — benchmark_simulation.py
└── benchmarks/          — benchmark_groups.py
```
