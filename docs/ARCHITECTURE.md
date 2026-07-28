<!-- generated-by: gsd-doc-writer -->
# System Architecture

## 1. Overview

This project is a **Monte Carlo football tournament prediction engine** that simulates football competitions (World Cup, UEFA Champions League) using Poisson-distributed match outcomes driven by Elo ratings. The sole interface is a **FastAPI web dashboard** on port 8080. All competitions share a common engine library (`football_core/`). The architecture follows a **hub-and-spoke** pattern: a flat shared library at the project root provides core math, data-fetching, and state-management primitives, while competition modules in `competitions/` add competition-specific simulation orchestration and tournament format details.

The web dashboard serves a **SPA frontend** from `web/static/` via two competition sub-apps — `wc_app` for World Cup and `ucl_app` for UCL — mounted under a unified FastAPI server at `web/server.py` (port 8080, served by uvicorn). The dashboard provides standings, bracket trees, odds tables, signal evaluation panels, and match insight views. A **what-if engine** (`web/whatif_engine.py`) enables instant natural-language scenario analysis for any match. Match insight functions are served from competition-specific modules (`competitions/worldcup/src/insight.py` for World Cup and `competitions/ucl/src/pipeline.py` for UCL). All state is persisted as JSON files on disk.

---

## 2. Module Dependency Diagram

```
  ┌───────────────────────────────────────────────────────────┐
  │                    web/  (FastAPI Dashboard)              │
  │                                                          │
  │  ┌─────────────────┐  ┌────────────────────────┐        │
  │  │   server.py      │  │   static/ (SPA)       │        │
  │  │   (uvicorn :8080)│  │   index.html          │        │
  │  │                  │  │   shared.css          │        │
  │  │   mounts:        │  │   shared.js           │        │
  │  │   /worldcup →    │  │   wc.js / ucl.js      │        │
  │  │   /ucl      →    │  └────────────────────────┘        │
  │  │   /static   →    │                                     │
  │  │   /euro (stub)   │  ┌────────────────────────┐        │
  │  └────────┬─────────┘  │  whatif_engine.py      │        │
  │           │            │  • parse_scenario      │        │
  │  ┌────────▼─────────┐  │  • handle_instant_     │        │
  │  │  wc_app.py       │  │    scenario            │        │
  │  │  (FastAPI sub)   │  │  • apply_adjustments   │        │
  │  │                  │  │  • generate_instant_   │        │
  │  │  /api/standings  │  │    insight             │        │
  │  │  /api/bracket    │  │  • generate_simulate_  │        │
  │  │  /api/evaluation │  │    insight             │        │
  │  │  /api/signals    │  └────────────────────────┘        │
  │  │  /api/blend      │  ┌────────────────────────┐        │
  │  │  /api/refresh    │  │  common.py             │        │
  │  │  /api/what-if    │  │  • boot_step           │        │
  │  │  /api/match/     │  │  • load_json           │        │
  │  │    insight       │  │  • ts                  │        │
  │  └────────┬─────────┘  └────────────────────────┘        │
  │           │                                               │
  │  ┌────────▼─────────┐                                     │
  │  │  ucl_app.py      │                                     │
  │  │  (FastAPI sub)   │                                     │
  │  │                  │                                     │
  │  │  /api/data       │                                     │
  │  │  /api/standings  │                                     │
  │  │  /api/bracket    │                                     │
  │  │  /api/odds       │                                     │
  │  │  /api/signals    │                                     │
  │  │  /api/simulate   │                                     │
  │  │  /api/what-if    │                                     │
  │  │  /api/match/     │                                     │
  │  │    insight       │                                     │
  │  └────────┬─────────┘                                     │
  └───────────┼───────────────────────────────────────────────┘
              │ imports competition modules & football_core
              ▼
┌─────────────────────────────────────┐
│         competitions/               │
│                                     │
│  ┌──────────┐  ┌────────┐  ┌─────┐ │
│  │ worldcup │  │  euro  │  │ ucl │ │
│  │          │  │        │  │     │ │
│  │ src/     │  │simul.. │  │src/  │ │
│  │  engine  │  │config  │  │ sim. │ │
│  │  analysis│  └────────┘  │ kno. │ │
│  │  knockout│              │ grps │ │
│  │  groups  │              │ orch.│ │
│  │  eval.   │              │ val. │ │
│  │  insight │              │provid│ │
│  │  gov.    │              │replay│ │
│  │  blender │              │ pip. │ │
│  │  pipeline│              └─────┘ │
│  └────┬─────┘                      │
└───────┼───────────────────────────┘
        │ imports all via football_core.*
        ▼
┌──────────────────────────────────────────┐
│              football_core/              │  ← SHARED ENGINE
│                                          │
│  ┌──────┐ ┌──────┐ ┌─────┐ ┌──────────┐ │
│  │ elo  │ │groups│ │kno. │ │ blender  │ │
│  └──┬───┘ └──┬───┘ └──┬──┘ └──────────┘ │
│     │        │        │      ┌──────────┐│
│  ┌──▼───┐ ┌──▼───┐ ┌──▼───┐ │enrichment││
│  │ state│ │fetcher│ │math  │ └──────────┘│
│  └──────┘ └──────┘ └──────┘ ┌──────────┐│
│  ┌──────────┐ ┌──────────┐  │provider  ││
│  │elo_sync  │ │elo_fetch │  │(protocol)││
│  └──────────┘ └──────────┘  └──────────┘│
│  ┌──────────┐ ┌────────────┐ ┌────────┐ │
│  │evaluation│ │ result_    │ │ signal │ │
│  │          │ │ provider   │ │(proto.)│ │
│  └──────────┘ └────────────┘ └────────┘ │
│  ┌──────┐ ┌──────────┐ ┌────────────┐   │
│  │glicko│ │predictors│ │ constants  │   │
│  └──────┘ │ /odds    │ │            │   │
│           │ /catboost│ │            │   │
│           └──────────┘ └────────────┘   │
│                                          │
│  ┌────────────────────────┐             │
│  │  providers/            │             │
│  │   manager.py           │             │
│  │   player.py            │             │
│  │   team.py              │             │
│  └────────────────────────┘             │
│  ┌────────────────────────┐             │
│  │  signals/              │             │
│  │   availability.py      │             │
│  │   defensive_quality.py │             │
│  │   manager_effect.py    │             │
│  │   market_odds.py       │             │
│  │   refined_elo.py       │             │
│  │   rest_days.py         │             │
│  │   rolling_form.py      │             │
│  │   squad_value.py       │             │
│  │   player_form.py       │             │
│  │   team_synergy.py      │             │
│  │   catboost.py          │             │
│  │   lineup.py            │             │
│  └────────────────────────┘             │
│  ┌────────────────────────┐             │
│  │  data_providers/       │             │
│  │   bsd_provider.py      │             │
│  │   football_data_org_   │             │
│  │   provider.py          │             │
│  └────────────────────────┘             │
└──────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────┐
│      External Services      │
│                             │
│  BSD API ── live match data │
│  eloratings.net ── Elo sync │
│  api.clubelo.com ── Club Elo│
│  football-data.org ── alt.  │
└─────────────────────────────┘
```

### 2.1 Competition-to-Core Import Patterns

Each competition imports from `football_core` differently:

| Competition | Import style | Example |
|---|---|---|
| **worldcup** | Re-export wrappers in `competitions/worldcup/src/` | `from football_core.elo import *` via `src/elo.py` |
| **euro** | Direct imports from `football_core` + re-exports via worldcup `src/` | `from football_core import elo, state` + `from competitions.worldcup.src.groups import ...` |
| **ucl** | Direct imports + selective `football_core.groups` + signal protocol types | `from football_core.constants import EXPECTED_GOALS_BASE_RATE` + `from football_core.signal import PredictionContext` |

World Cup uses re-export wrappers because its internal modules were written before `football_core` existed — the wrappers let existing `from src import X` statements continue working without touching every file.

---

## 3. Data Flow

The data flow differs between **live-polling** competitions (worldcup) and **on-demand** competitions (ucl).

### 3.1 Live-Polling Flow (World Cup)

```
                            ┌───────────┐
                            │  Startup  │
                            │  (lifespan│
                            │   hook)   │
                            └─────┬─────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │  1. Bootstrap data loading  │
                    │     - Load teams, groups,   │
                    │       bracket, aliases from │
                    │       JSON files in data/   │
                    │     - Initial Elo sync from │
                    │       eloratings.net        │
                    │     - Live fetch from data  │
                    │       provider (BSD/fd-org) │
                    └─────────────┬───────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────────────┐
                    │  2. Compute overview (determin.) │
                    │     - Real standings from played │
                    │     - Bracket resolution (slots) │
                    │     - Signal cache metadata      │
                    │     - Governance (drift, vers.)  │
                    └─────────────┬────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────────────┐
                    │  3. On-demand simulation         │
                    │     (triggered by POST /api/     │
                    │      simulate)                   │
                    │  ┌──────────────────────────┐    │
                    │  │ a) Fetch latest data      │    │
                    │  │    from data provider     │    │
                    │  │ b) Refresh signal caches  │    │
                    │  │ c) Build prediction eng.  │    │
                    │  │ d) Run Monte Carlo        │    │
                    │  │    (groups → knockout)    │    │
                    │  │ e) Compute eval metrics   │    │
                    │  │ f) Build full bracket     │    │
                    │  │ g) Write snapshot.json    │    │
                    │  └──────────────────────────┘    │
                    └──────────────────────────────────┘
```

### 3.2 On-Demand Flow (UCL)

UCL runs as a FastAPI sub-app under `/ucl`. On startup, its lifespan hook fetches live data and computes a deterministic result set (standings, bracket, odds). An optional simulation can be triggered on demand via `POST /api/simulate`.

```
  ┌────────────┐
  │  Startup   │  lifespan hook in ucl_app
  │  (serve)   │
  └─────┬──────┘
        │
        ▼
  ┌────────────────────────────────┐
  │  1. Fetch live data from      │
  │     data provider (BSD or     │
  │     football-data.org)        │
  │     - League results (LEAGUE) │
  │     - Knockout results        │
  │     - Manager data from BSD   │
  └─────┬──────────────────────────┘
        │
        ▼
  ┌────────────────────────────────┐
  │  2. Deterministic compute     │
  │     - Load fixtures JSON      │
  │     - Build league standings  │
  │       from results            │
  │     - Build bracket tree      │
  │       (playoff + KO rounds)   │
  │     - Fetch Elo ratings from  │
  │       ClubElo API             │
  │     - Evaluate signal engine  │
  │       (5 signals, calibrated) │
  │     - Compute odds table      │
  └─────┬──────────────────────────┘
        │
        ▼
  ┌────────────────────────────────┐
  │  3. Optional on-demand        │
  │     Monte Carlo simulation    │
  │     (POST /api/simulate)      │
  │                                │
  │  ┌───────────────────────┐    │
  │  │ Per iteration:        │    │
  │  │  a) Simulate league   │    │
  │  │     phase (Swiss)     │    │
  │  │  b) Resolve playoff   │    │
  │  │     (positions 9-24)  │    │
  │  │  c) Build R16 bracket │    │
  │  │  d) Simulate KO tree  │    │
  │  │     (R16→QF→SF→FINAL) │    │
  │  │  e) Track stage per   │    │
  │  │     team              │    │
  │  └───────────────────────┘    │
  └────────────────────────────────┘
```

### 3.3 Key Pipeline Differences

| Aspect | World Cup | UCL |
|---|---|---|
| **Mode** | Live data fetch on startup + on-demand simulation | Deterministic compute on startup + on-demand simulation |
| **Data source** | BSD API or football-data.org (live matches) | BSD API or football-data.org (live results) + pre-loaded fixtures JSON |
| **Elo source** | eloratings.net (sync on startup) | ClubElo API (fetched once per boot) |
| **Signal fusion** | Multi-signal (8+ signals: Elo, odds, CatBoost, form, lineup, availability, defensive quality, manager effect, team synergy, rolling form, squad value, rest days) via pipeline cache | 5-signal ensemble (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays) via EnsembleEngine + calibration |
| **State persistence** | JSON files updated after each live fetch | JSON files updated after live fetch; snapshot written on simulation |
| **Group format** | Round-robin groups (4 teams × groups) | Swiss-system (36-team single table, 8 matchdays) |
| **Knockout structure** | Single matches, bracket resolution with Annex C (R32 routing) | Two-legged ties (playoff + R16 through SF), single final |

---

## 4. Shared Library Design (`football_core/`)

### 4.1 Principles

The shared library follows the **Rule of Two**: a module graduates to `football_core/` only when at least two competitions use it identically. This prevents premature abstraction. See [FOOTBALL_ENGINE_ARCHITECTURE.md](./FOOTBALL_ENGINE_ARCHITECTURE.md) §2.1 for the full dual-proven module list.

### 4.2 Module Responsibilities

| Module | Responsibility | Proven By |
|---|---|---|
| `elo.py` | Pure Elo math: `expected_score`, `update_ratings`, `compute_k_factor` | WC, Euro, UCL |
| `groups.py` | Poisson score model, 7-step FIFA tiebreaker chain, round-robin simulation, precomputed matchup lambdas | WC, Euro |
| `knockout.py` | Generic round simulation, two-legged tie, and penalty shootout primitives: `_simulate_knockout_round`, `_build_round_map`, `simulate_two_legged_tie`, `_simulate_penalty_shootout` | WC, Euro, UCL |
| `fetcher.py` | BSD/football-data.org fetch pipeline: `fetch_raw_matches`, `process_matches`, `process_group_matches`, `_build_alias_lookup` | WC, Euro, UCL |
| `state.py` | JSON persistence with atomic writes: load/save for all state files | WC, Euro, UCL |
| `elo_sync.py` | Elo sync from eloratings.net with drift detection | WC, Euro |
| `elo_fetcher.py` | ClubElo API fetcher for UCL with team-alias resolution | UCL |
| `glicko.py` | Glicko-1 Bayesian rating system: `update_glicko`, `RatingSystem`, `expected_score_bayesian`, `compute_glicko_k_factor` | UCL |
| `evaluation.py` | Shared metric computation: Brier score, log loss, calibration curve, `compute_metrics` | UCL, WC |
| `math_utils.py` | Sigmoid utility | WC |
| `constants.py` | Generic constants only (K_FACTOR, Poisson params, timeouts, Elo sync params) | WC, Euro, UCL |
| `predictors/odds.py` | Market odds fetch and vig removal | WC, Euro, UCL |
| `predictors/catboost.py` | CatBoost prediction fetch | WC, Euro |
| `provider.py` | Base provider protocol & dataclasses: `FixtureProvider`, `MatchResultProvider`, `FixtureSchedule` | UCL |
| `signal.py` | Base signal protocol & registry: `Signal`, `SignalRegistry`, `SignalOutput`, `PredictionContext` | UCL, WC |
| `blender.py` | Signal calibration & blending primitives (Platt scaling, Brier weighting, log-loss weighting), `EnsembleEngine` | WC, UCL |
| `enrichment.py` | Match enrichment: `extract_stats`, `extract_context` from BSD event dicts | WC |
| `result_provider.py` | `MatchResultProvider` protocol for rolling-form signal data sources | UCL |
| `data_providers/bsd_provider.py` | BSD API provider: fetches matches, managers, signals | WC, UCL |
| `data_providers/football_data_org_provider.py` | football-data.org API provider: fetches matches | WC, UCL |
| `providers/manager.py` | Manager data fetch and caching from BSD API | WC |
| `providers/player.py` | Player data fetch and caching from BSD API | WC |
| `providers/team.py` | Team data structures and providers | UCL |
| `signals/availability.py` | Availability/injury impact signal from player data | WC |
| `signals/defensive_quality.py` | Defensive quality signal from manager stats | WC |
| `signals/manager_effect.py` | Manager effect signal (win rate, formation, style) | WC |
| `signals/market_odds.py` | Market odds prediction signal (Signal protocol wrapper) | UCL |
| `signals/refined_elo.py` | Refined Elo signal with configurable K-factor & home advantage | UCL |
| `signals/rest_days.py` | Rest days advantage signal | UCL |
| `signals/rolling_form.py` | Rolling form signal from recent match results | UCL |
| `signals/squad_value.py` | Squad market value signal | UCL |
| `signals/player_form.py` | Player-level form signal | UCL |
| `signals/team_synergy.py` | Team synergy / chemistry signal | WC |
| `signals/catboost.py` | CatBoost prediction signal (Signal protocol) | WC |
| `signals/lineup.py` | Lineup strength signal (Signal protocol) | WC |

### 4.3 Design Constraints

- **Evolving structure**: The original design mandated a fully flat `football_core/` package. With the addition of signal modules, provider modules, and data provider modules, the package now has four subpackages — `providers/`, `signals/`, `data_providers/`, and `predictors/` — while core primitives (`elo`, `groups`, `state`, etc.) remain at top level. This hybrid layout keeps import paths short for frequently-used modules while organizing the growing signal/provider surface area.
- **Data-directory parameterization**: Every `state.py` function accepts a `data_dir` parameter — no hardcoded paths.
- **Data-provider abstraction**: The `data_providers/` subpackage defines a common interface (`BSDDataProvider`, `FootballDataOrgProvider`) behind a `DATA_PROVIDER` env-var switch. This allows competitions to fetch live match data from either provider without code changes.
- **No pip-installable package**: The project runs from source. There is no `setup.py` or `pyproject.toml`. Import discovery relies on `sys.path` manipulation in each competition's `__init__.py`.

---

## 5. Competition Module Design Patterns

### 5.1 Similarities

All three competitions follow the same logical pipeline:

```
Load data → Fetch live info (or skip) → Simulate Monte Carlo → Display results
```

The simulation kernel is always Poisson-distributed match outcomes computed from Elo ratings via `football_core.elo.expected_score()`. All competitions use `football_core.state` for JSON file persistence. Data is served through the web dashboard's REST API.

### 5.2 Differences

| Aspect | World Cup | Euro | UCL |
|---|---|---|---|
| **Maturity** | Most mature (24+ test files, 600+ tests) | Mature (dormant) | Mature (20+ test files, 430+ tests) |
| **Web route** | `/worldcup` | `/euro` (stub — returns `coming_soon`) | `/ucl` |
| **Poll mode** | Live data fetch on startup + on-demand simulation | Disconnected from web — standalone simulation module | Deterministic compute on startup + on-demand simulation |
| **Group format** | 12+ groups (A-L), 4 teams each | 6 groups (A-F), 4 teams each | Swiss-system, 36 teams, 8 matchdays |
| **Third-place advancers** | Top 8 of 12 | Top 4 of 6 | N/A (positions 9-24 → playoff) |
| **Knockout entry** | R32 → R16 → QF → SF → FINAL + TPP | R16 → QF → SF → FINAL | Playoff → R16 → QF → SF → FINAL |
| **R32 resolution** | Annex C (495-entry table, WC-specific) | Precomputed bracket JSON | Playoff round (positions 9-24, two-legged) |
| **Match format** | Single match per round | Single match per round | Two-legged aggregate + ET + penalties |
| **Signals used** | Elo, odds, CatBoost, form, lineup, availability, defensive quality, manager effect, team synergy, rolling form, squad value, rest days | None | 5-signal ensemble (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays) |
| **Blending** | Brier-weighted multi-signal fusion | None | Log-loss-weighted uniform blend via EnsembleEngine |
| **Governance** | Drift detection, version tracking, backtest, signal cache metadata | None | Calibration tracking, validation suite |
| **Display** | Web dashboard: standings, bracket, odds, signal eval, what-if, match insight, calibration, validation | Stub | Web dashboard: standings, bracket, odds, signal eval, what-if, match insight, calibration, validation |
| **Validation** | History-based evaluation, calibrated validation | None | Validation suite (Brier, log-loss, accuracy vs BSD/ClubElo) |
| **Data provider** | BSD API or football-data.org (env-var selectable) | Pre-loaded data only | BSD API or football-data.org (env-var selectable) |

### 5.3 World Cup-Specific Modules

These remain in `competitions/worldcup/src/` because no other competition needs them yet:

- `blender.py` — thin WC-specific orchestration layer; calibration/blending primitives imported from `football_core.blender`
- `evaluation.py` — WC-specific `evaluate_all_matches` (historical match evaluation), per-signal Brier/log-loss computation
- `governance.py` — model governance with drift detection, version tracking, match counting
- `insight.py` — WC-specific match insight: `compute_team_signal_strengths`, `compute_ko_signal_probs`, `compute_match_insight`, `compute_form_trend`, `compute_head_to_head`, `compute_match_outcome`
- `pipeline.py` — extracted compute pipeline: `fetch_live_data`, `build_chronological_matches`, `build_knockout_tree`, `run_simulation_compute`, `run_calibration_compute`
- `engine.py` — WC prediction engine builder: `build_engine_from_caches`
- `predictors/form.py` — form signal computation
- `predictors/lineup.py` — lineup strength signal
- `predictors/manager_signals.py` — manager-based signal orchestration (uses `football_core.providers.manager`, `football_core.signals.defensive_quality`, `football_core.signals.manager_effect`)
- `predictors/availability.py` — availability signal orchestration (uses `football_core.providers.player`, `football_core.signals.availability`)
- `predictors/elo_odds.py` — Elo odds signal computation
- `predictors/rest_days.py` — rest days signal computation
- `predictors/rolling_form.py` — rolling form signal computation
- `predictors/squad_value.py` — squad value signal computation
- `predictors/team_synergy.py` — team synergy signal computation
- `knockout.py` — full simulation orchestrator with R32 Annex C routing

### 5.4 UCL-Specific Modules

These remain in `competitions/ucl/src/` because they are UCL-specific:

- `orchestrator.py` — top-level compute orchestration: `build_simulation_result`, `build_signal_engine`, `run_deterministic_compute`, `run_compute_all`
- `pipeline.py` — UCL fetch and compute pipeline functions (match insight, calibration, MC simulation)
- `simulation.py` — UCL Monte Carlo simulation with Swiss league + two-legged knockout
- `groups.py` — UCL Swiss-system standings computation
- `knockout.py` — UCL knockout bracket resolution and simulation
- `calibrate.py` — offline signal calibration from historical replay data
- `validation.py` — validation suite for UCL predictions
- `validation_suite.py` — comprehensive validation against BSD/ClubElo results
- `elo_fetcher.py` — ClubElo API fetcher
- `elo_updater.py` — Elo rating update pipeline
- `provider.py` — `RepoFixtureProvider` for loading UCL fixtures from JSON
- `result_provider.py` — UCL result provider
- `live_state.py` — UCL live state management
- `constants.py` — UCL-specific constants (league ID, knockout stage mapping)
- `fetcher.py` — UCL-specific data fetch helpers
- `wikipedia_scraper.py` — Wikipedia-based data scraping for historical fixtures

### 5.5 Sys.Path Bootstrap

Each competition module manipulates `sys.path` at import time for `football_core` resolution:

- **`competitions/worldcup/__init__.py`**: Adds repo root (for `football_core`) and `competitions/worldcup/src/` directory.
- **`competitions/ucl/__init__.py`**: Adds repo root and `competitions/ucl/` directory.
- **`competitions/euro/__init__.py`**: Minimal bootstrap — imports `football_core` and `competitions.worldcup.src.groups` via absolute paths.

This is a deliberate trade-off: it avoids a `pyproject.toml` / pip-installable package while keeping import resolution working from source. Euro's previous sys.path manipulation for `worldcup/` was removed when its import was migrated to an absolute path.

---

## 6. Key Design Decisions

### 6.1 Flat Package over Subpackages (Relaxed)

`football_core/` was originally designed as a fully flat package — all modules at top level rather than organized into `compute/`, `signals/`, `bsd/`, `state/` subpackages. As the signal, provider, and data-provider surface area grew, four subpackages were introduced: `providers/` (3 modules), `signals/` (10+ modules), `data_providers/` (2 modules), and `predictors/` (2 modules). Core primitives (`elo`, `groups`, `state`, `knockout`, `fetcher`) remain at top level. This hybrid preserves short import paths for the most frequently-used modules while keeping the growing surface organized.

### 6.2 Sys.Path over pip Install

The project runs from source without a build step. This avoids tooling overhead (no `pyproject.toml`, no `setup.py`) and keeps the development loop fast: edit → run (with hot reload via `uvicorn --reload`). The downside is that other projects cannot `pip install football_core`.

### 6.3 Rule-of-Two Extraction

Modules graduate to `football_core/` only when two competitions use them with identical call signatures. This prevents speculative abstraction. As the project has matured, `blender.py` and `evaluation.py` have become dual-proven (WC + UCL), while some modules (WC-specific governance, form, lineup) remain single-proven despite potential for sharing.

### 6.4 Two-Legged Tie Simulation in Core

The core `football_core/knockout.py` provides `simulate_single_match`, `simulate_two_legged_tie`, and `_simulate_penalty_shootout` — all three are shared primitives used by UCL. UCL's `competitions/ucl/src/knockout.py` imports `simulate_two_legged_tie` from the core and wraps it with UCL-specific orchestration (playoff round pairings for positions 9–24, seeded team home-advantage assignment, and specific ET/penalty calibration constants). This means the two-legged aggregate logic lives in the shared core, while the UCL-specific bracket resolution, playoff format, and seeding logic stay in the competition module.

### 6.5 JSON File Persistence over Database

All state is stored as human-readable JSON files. This was chosen for simplicity — no database setup, no schema migrations, and files can be inspected and hand-edited for debugging. The trade-off is no concurrent write safety (writes use atomic file swaps) and no query capability.

### 6.6 Signal Fusion Architecture

The World Cup blends up to **twelve** independent prediction signals using Brier-weighted calibration. This is the most architecturally complex part of the system. The blender's pure-computation primitives (Platt scaling, rolling Brier, blend weighting) live in `football_core/blender.py`, while WC-specific orchestration (calibrate and blend) is handled by the pipeline in `competitions/worldcup/src/pipeline.py` and `competitions/worldcup/src/engine.py`.

UCL also performs signal fusion, but with a simpler approach: up to **five** signals (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays) combined via a log-loss-weighted uniform blend implemented in `football_core.blender.EnsembleEngine`. Unlike the World Cup's online Brier-weighted calibration, UCL's weights are fitted offline from historical replay data via `competitions/ucl/src/calibrate.py` and stored in a static `signal_weights.json` file.

```
        ┌──────┐ ┌──────┐ ┌──────┐ ┌────┐ ┌─────┐ ┌─────┐
        │ Elo  │ │ Odds │ │CBoo. │ │Form│ │Line │ │Avail│
        └──┬───┘ └──┬───┘ └──┬───┘ └──┬─┘ └──┬──┘ └──┬──┘
           │        │        │        │      │       │
           │   ┌────▼──┐ ┌──▼───┐ ┌───▼────┐ │  ┌───▼───┐
           │   │Def.  │ │Mgr.  │ │Team    │ │  │Rolling │
           │   │Qual. │ │Eff.  │ │Synergy │ │  │Form    │
           │   └──┬───┘ └──┬───┘ └───┬────┘ │  └───┬───┘
           │      │        │         │      │      │
           │   ┌──▼────────▼─────────▼──────▼──┐   │
           │   │   rest_days, squad_value,     │   │
           │   │   elo_odds                    │   │
           │   └──────────────┬────────────────┘   │
           └──────────────────┼────────────────────┘
                              │
                              ▼
                      ┌──────────────────┐
                      │  pipeline.py     │  ← competitions/worldcup/src/pipeline.py
                      │  run_simulation_ │     (orchestration)
                      │  compute()       │
                      │                  │     primitives: football_core/blender.py
                      │  - Platt scaling │
                      │  - Rolling Brier │
                      │  - Brier-weighted│
                      │    blend         │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │  match_probs     │  → used by knockout simulation
                      │  blend_weights   │  → logged in governance
                      │  calibration_    │
                      │  params          │  → persisted for next run
                      └──────────────────┘
```

This architecture keeps the simulation engine clean — it consumes `blend_params` as a dict and does not need to know how signals are combined. The World Cup uses the more complex online Brier-weighted calibration, while UCL uses offline-fitted log-loss weighting — both share the same core blending primitives in `football_core/blender.py`.

---

## 7. References

For detailed information on specific architectural areas, see these sibling documents:

- **[FOOTBALL_ENGINE_ARCHITECTURE.md](./FOOTBALL_ENGINE_ARCHITECTURE.md)** — Complete module inventory, stable abstraction schemas, public API signatures, aspirational destination architecture, migration execution summary, and remaining work items.
- **[COMMONALITY_REPORT.md](./COMMONALITY_REPORT.md)** — Empirical dual-proven audit showing exactly which modules are shared, which are competition-specific, and why.