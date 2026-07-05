<!-- generated-by: gsd-doc-writer -->
# System Architecture

## 1. Overview

This project is a **Monte Carlo football tournament prediction engine** — a collection of CLI tools that simulate football competitions (World Cup, UEFA Euro, UEFA Champions League) using Poisson-distributed match outcomes driven by Elo ratings. Each competition is a standalone CLI program (`wc-predict`, `euro-predict`, `ucl-predict`) that shares a common engine library (`football_core/`). The architecture follows a **hub-and-spoke** pattern: a flat shared library at the project root provides core math, data-fetching, and state-management primitives, while competition modules in `competitions/` add competition-specific simulation orchestration, display logic, and tournament format details.

The system has no API server, no database, and no web framework. All state is persisted as JSON files on disk. All user interaction is via `argparse` CLI.

---

## 2. Module Dependency Diagram

```
                    ┌─────────────────────────────────────┐
                    │         competitions/               │
                    │                                     │
                    │  ┌──────────┐  ┌────────┐  ┌─────┐ │
                    │  │ worldcup │  │  euro  │  │ ucl │ │
                    │  │          │  │        │  │     │ │
                    │  │ main.py  │  │main.py │  │main.│ │
                    │  │ src/     │  │simul.. │  │py   │ │
                    │  │  knockout│  │display │  │src/  │ │
                    │  │  output  │  │config  │  │ sim. │ │
                    │  │  eval.   │  └────────┘  │ kno. │ │
                    │  │  gov.    │              │ grps │ │
                    │  │  const.  │              │ val. │ │
                    │  │  form    │              │ live │ │
                    │  │  lineup  │              │provid.│ │
                    │  │  avail.  │              │replay│ │
                    │  │  mgr_sig │              │sig_reg│ │
                    │  └────┬─────┘              └─────┘ │
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
              └─────────────────────────────┘
```

### 2.1 Competition-to-Core Import Patterns

Each competition imports from `football_core` differently:

| Competition | Import style | Example |
|---|---|---|
| **worldcup** | Re-export wrappers in `competitions/worldcup/src/` | `from football_core.elo import *` via `src/elo.py` |
| **euro** | Direct imports from `football_core` + re-exports via `src` (World Cup `competitions/worldcup/src/`) | `from football_core import elo, state` + `from src.fetcher import ...` |
| **ucl** | Direct imports + selective `football_core.groups` + signal protocol types | `from football_core.constants import EXPECTED_GOALS_BASE_RATE` + `from football_core.signal import PredictionContext` |

World Cup uses re-export wrappers because its internal modules were written before `football_core` existed — the wrappers let existing `from src import X` statements continue working without touching every file.

---

## 3. Data Flow

The data flow differs between **live-polling** competitions (worldcup, euro) and the **single-run** competition (ucl).

### 3.1 Live-Polling Flow (World Cup, Euro)

```
                            ┌───────────┐
                            │  Startup  │
                            │  (--once  │
                            │   or loop)│
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
                    │     - Historical catch-up   │
                    │       fetch from BSD API    │
                    └─────────────┬───────────────┘
                                  │
                                  ▼  ┌──────────────────┐
                    ┌──────────────────────┐ │  Loop interval   │
                    │  2. POLL LOOP        │ │  (default 60s)   │
                    │                      │◄┘                  │
                    │  ┌─────────────────┐ │                    │
                    │  │ a) Fetch matches│ │──→ BSD API         │
                    │  │    from BSD API │ │    (football_core  │
                    │  │                 │ │     .fetcher)      │
                    │  └────────┬────────┘ │                    │
                    │           ▼          │                    │
                    │  ┌─────────────────┐ │                    │
                    │  │ b) Process new  │ │                    │
                    │  │    matches      │ │                    │
                    │  │    - Update Elo │ │                    │
                    │  │      ratings    │ │                    │
                    │  │    - Persist    │ │                    │
                    │  │      state JSON │ │                    │
                    │  └────────┬────────┘ │                    │
                    │           ▼          │                    │
                    │  ┌─────────────────┐ │                    │
                    │  │ c) Refresh      │ │                    │
                    │  │    signal caches │ │                    │
                    │  │    - Market odds │ │                    │
                    │  │    - CatBoost    │ │                    │
                    │  │    - Form/lineup │ │                    │
                    │  │    - Availability│ │                    │
                    │  │    - Defensive   │ │                    │
                    │  │      quality     │ │                    │
                    │  │    - Manager     │ │                    │
                    │  │      effect      │ │                    │
                    │  └────────┬────────┘ │                    │
                    │           ▼          │                    │
                    │  ┌─────────────────┐ │                    │
                    │  │ d) Calibrate &  │ │  (worldcup only)   │
                    │  │    blend 8      │ │  8-signal Brier-   │
                    │  │    prediction   │ │  weighted fusion   │
                    │  │    signals      │ │                    │
                    │  └────────┬────────┘ │                    │
                    │           ▼          │                    │
                    │  ┌─────────────────┐ │  50000 iterations  │
                    │  │ e) Run Monte    │ │                    │
                    │  │    Carlo sim    │ │                    │
                    │  │    (groups →    │ │                    │
                    │  │     knockout)   │ │                    │
                    │  └────────┬────────┘ │                    │
                    │           ▼          │                    │
                    │  ┌─────────────────┐ │                    │
                    │  │ f) Display      │ │                    │
                    │  │    results      │ │                    │
                    │  │    - Probability│ │                    │
                    │  │      table      │ │                    │
                    │  │    - Group      │ │                    │
                    │  │      standings  │ │                    │
                    │  │    - Delta/trend│ │                    │
                    │  └─────────────────┘ │                    │
                    └──────────────────────┘                    │
                                  │                             │
                                  ▼  (on Ctrl+C or --once)      │
                    ┌─────────────────────────────┐             │
                    │  3. Shutdown                │             │
                    │     - Final sim run         │             │
                    │     - Print final table     │             │
                    │     - Save state            │             │
                    └─────────────────────────────┘             │
```

### 3.2 Single-Run Flow (UCL)

```
  ┌────────────┐
  │   CLI      │  ucl-predict --iterations 10000 --seed 42
  │   parse    │
  └─────┬──────┘
        │
        ▼
  ┌──────────────────────┐
  │  1. Load fixtures    │
  │     from data/       │
  └─────┬────────────────┘
        │
        ▼
  ┌──────────────────────┐
  │  2. Fetch Elo        │
  │     ratings from     │
  │     ClubElo API      │
  └─────┬────────────────┘
        │
        ▼
  ┌──────────────────────┐
  │  3. Set up signal    │
  │     EnsembleEngine   │
  │     (5 signals:      │
  │     RefinedElo,      │
  │     MarketOdds,      │
  │     RollingForm,     │
  │     SquadValue,      │
  │     RestDays)        │
  └─────┬────────────────┘
        │
        ▼
  ┌───────────────────────────────────────────────┐
  │  4. Monte Carlo loop (N iterations)           │
  │                                               │
  │  ┌───────────────────────────────────────┐    │
  │  │ Per iteration:                        │    │
  │  │    a) Simulate Swiss league phase     │    │
  │  │       (36 teams, 144 matches)         │    │
  │  │    b) Resolve playoff round (9-24)    │    │
  │  │    c) Build R16 bracket from standings│    │
  │  │    d) Simulate knockout tree           │    │
  │  │       (R16 → QF → SF → Final)         │    │
  │  │    e) Track stage reached for all     │    │
  │  └───────────────────────────────────────┘    │
  └─────┬─────────────────────────────────────────┘
        │
        ▼
  ┌──────────────────────┐
  │  5. Aggregate        │
  │     results across   │
  │     N iterations     │
  └─────┬────────────────┘
        │
        ▼
  ┌──────────────────────┐
  │  6. Display          │
  │     - Summary        │
  │     - League table   │
  │     - Playoff rounds │
  │     - Bracket        │
  │     - Odds table     │
  │     - JSON export    │
  └──────────────────────┘
```

### 3.3 Key Pipeline Differences

| Aspect | World Cup / Euro | UCL |
|---|---|---|
| **Mode** | Continuous poll loop (default 60s) | Single run, exits after display |
| **Data source** | BSD API (live matches) | Pre-loaded fixtures JSON |
| **Elo source** | eloratings.net (sync on startup + periodic) | ClubElo API (fetched once) |
| **Signal fusion** | Multi-signal (8 signals: Elo, odds, CatBoost, form, lineup, availability, defensive quality, manager effect) | 5-signal ensemble (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays) via EnsembleEngine |
| **State persistence** | JSON files updated after each poll cycle | No runtime persistence |
| **Group format** | Round-robin groups (4 teams × groups) | Swiss-system (36-team single table) |
| **Knockout structure** | Two-legged or single matches, bracket resolution | Two-legged ties (playoff + R16), single final |

---

## 4. Shared Library Design (`football_core/`)

### 4.1 Principles

The shared library follows the **Rule of Two**: a module graduates to `football_core/` only when at least two competitions use it identically. This prevents premature abstraction. See [FOOTBALL_ENGINE_ARCHITECTURE.md](./FOOTBALL_ENGINE_ARCHITECTURE.md) §2.1 for the full dual-proven module list.

### 4.2 Module Responsibilities

| Module | Responsibility | Proven By |
|---|---|---|
| `elo.py` | Pure Elo math: `expected_score`, `update_ratings`, `compute_k_factor` | WC, Euro, UCL |
| `groups.py` | Poisson score model, 7-step FIFA tiebreaker chain, round-robin simulation | WC, Euro |
| `knockout.py` | Generic round simulation, two-legged tie, and penalty shootout primitives: `_simulate_knockout_round`, `_build_round_map`, `simulate_two_legged_tie`, `_simulate_penalty_shootout` | WC, Euro, UCL |
| `fetcher.py` | BSD API fetch pipeline: `fetch_raw_matches`, `process_matches`, `process_group_matches` | WC, Euro, UCL |
| `state.py` | JSON persistence with atomic writes: load/save for all state files | WC, Euro, UCL |
| `elo_sync.py` | Elo sync from eloratings.net with drift detection | WC, Euro |
| `elo_fetcher.py` | ClubElo API fetcher for UCL with team-alias resolution | UCL |
| `glicko.py` | Glicko-1 Bayesian rating system: `update_glicko`, `RatingSystem`, `expected_score_bayesian`, `compute_glicko_k_factor` | UCL |
| `evaluation.py` | Shared metric computation: Brier score, log loss, calibration curve | UCL, WC |
| `math_utils.py` | Sigmoid utility | WC |
| `constants.py` | Generic constants only (K_FACTOR, Poisson params, timeouts) | WC, Euro, UCL |
| `predictors/odds.py` | Market odds fetch and vig removal | WC, Euro, UCL |
| `predictors/catboost.py` | CatBoost prediction fetch | WC, Euro |
| `provider.py` | Base provider protocol & dataclasses: `FixtureProvider`, `MatchResultProvider`, `FixtureSchedule` | UCL |
| `signal.py` | Base signal protocol & registry: `Signal`, `SignalRegistry`, `SignalOutput`, `PredictionContext` | UCL, WC |
| `blender.py` | Signal calibration & blending primitives (Platt scaling, Brier weighting, log-loss weighting) | WC, UCL |
| `enrichment.py` | Match enrichment: `extract_stats`, `extract_context` from BSD event dicts | WC |
| `result_provider.py` | `MatchResultProvider` protocol for rolling-form signal data sources | UCL |
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

### 4.3 Design Constraints

- **Evolving structure**: The original design mandated a fully flat `football_core/` package. With the addition of 8 signal modules and 3 provider modules, the package now has two subpackages — `providers/` and `signals/` — while core primitives (`elo`, `groups`, `state`, etc.) remain at top level. This hybrid layout keeps import paths short for frequently-used modules while organizing the growing signal/provider surface area.
- **Data-directory parameterization**: Every `state.py` function accepts a `data_dir` parameter — no hardcoded paths.
- **League-ID parameterization**: `fetcher.py` accepts `league_id` parameters. The BSD API URL template and most competition-specific constants live in competition modules, not the core.
- **No pip-installable package**: The project runs from source. There is no `setup.py` or `pyproject.toml`. Import discovery relies on `sys.path` manipulation in each competition's `__init__.py`.

---

## 5. Competition Module Design Patterns

### 5.1 Similarities

All three competitions follow the same logical pipeline:

```
Load data → Fetch live info (or skip) → Simulate Monte Carlo → Display results
```

The simulation kernel is always Poisson-distributed match outcomes computed from Elo ratings via `football_core.elo.expected_score()`. All competitions use `football_core.state` for JSON file persistence. All use `argparse` for CLI argument parsing.

### 5.2 Differences

| Aspect | World Cup | Euro | UCL |
|---|---|---|---|
| **Maturity** | Most mature (614 tests, 24 test files) | Mature (dormant) | Mature (438 tests, 20 test files) |
| **CLI name** | `wc-predict` | `euro-predict` | `ucl-predict` |
| **Poll mode** | Continuous (60s interval) | Continuous (60s interval) | Single-run |
| **Group format** | 12 groups (A-L), 4 teams each | 6 groups (A-F), 4 teams each | Swiss-system, 36 teams, 8 matchdays |
| **Third-place advancers** | Top 8 of 12 | Top 4 of 6 | N/A (positions 9-24 → playoff) |
| **Knockout entry** | R32 → R16 → QF → SF → FINAL + TPP | R16 → QF → SF → FINAL | Playoff → R16 → QF → SF → FINAL |
| **R32 resolution** | Annex C (495-entry table, WC-specific) | Precomputed bracket JSON | Playoff round (positions 9-24, two-legged) |
| **Match format** | Single match per round | Single match per round | Two-legged aggregate + ET + penalties |
| **Signals used** | Elo, odds, CatBoost, form, lineup, availability, defensive quality, manager effect | Elo, odds, CatBoost | 5-signal ensemble (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays) |
| **Blending** | Brier-weighted 8-signal fusion | None | Log-loss-weighted uniform blend via EnsembleEngine |
| **Governance** | Drift detection, version tracking, backtest | None | None |
| **Display** | Rich: standings table, trend arrows, delta, signal detail, AI previews | Simple: probability table only | Structured: standings, playoff, bracket, odds table |
| **Validation** | History-based evaluation | None | `--validate` flag cross-checks vs BSD results |
| **BSD integration** | Full: group + knockout fetch, alias resolution | Full: group + knockout fetch | Partial: validation-only fetch |

### 5.3 World Cup-Specific Modules

These remain in `competitions/worldcup/src/` because no other competition needs them yet:

- `blender.py` — thin WC-specific orchestration layer; calibration/blending primitives imported from `football_core.blender`
- `evaluation.py` — WC-specific `evaluate_all_matches` (historical match evaluation)
- `governance.py` — model governance with drift detection
- `predictors/form.py` — form signal computation
- `predictors/lineup.py` — lineup strength signal
- `predictors/manager_signals.py` — manager-based signal orchestration (uses `football_core.providers.manager`, `football_core.signals.defensive_quality`, `football_core.signals.manager_effect`)
- `predictors/availability.py` — availability signal orchestration (uses `football_core.providers.player`, `football_core.signals.availability`)
- `output.py` — WC-specific display with 12-group standings, trend arrows, signal detail
- `knockout.py` — full simulation orchestrator with R32 Annex C routing

### 5.4 Sys.Path Bootstrap

Each competition module manipulates `sys.path` at import time:

- **`competitions/worldcup/__init__.py`**: Adds repo root (for `football_core`) and `competitions/worldcup/` (for `src`).
- **`competitions/euro/__init__.py`**: Adds repo root and `competitions/worldcup/` (needed because Euro imports `compute_standings` from `src.groups` for historical catch-up).
- **`competitions/ucl/__init__.py`**: Minimal bootstrap for `competitions.ucl.*` package imports.

This is a deliberate trade-off: it avoids rewriting all module-level import paths but creates implicit cross-competition dependencies (notably Euro → World Cup `src.groups`). See [FOOTBALL_ENGINE_ARCHITECTURE.md](./FOOTBALL_ENGINE_ARCHITECTURE.md) §7 for the eventual migration plan.

---

## 6. Key Design Decisions

### 6.1 Flat Package over Subpackages (Relaxed)

`football_core/` was originally designed as a fully flat package — all modules at top level rather than organized into `compute/`, `signals/`, `bsd/`, `state/` subpackages. As the signal and provider surface area grew, two subpackages were introduced: `providers/` (3 modules) and `signals/` (8 modules). Core primitives (`elo`, `groups`, `state`, `knockout`, `fetcher`) remain at top level. This hybrid preserves short import paths for the most frequently-used modules while keeping the growing signal/provider surface organized.

### 6.2 Sys.Path over pip Install

The project runs from source without a build step. This avoids tooling overhead (no `pyproject.toml`, no `setup.py`, no virtualenv requirement) and keeps the development loop fast: edit → run. The downside is that other projects cannot `pip install football_core`.

### 6.3 Rule-of-Two Extraction

Modules graduate to `football_core/` only when two competitions use them with identical call signatures. This prevents speculative abstraction. As the project has matured, `blender.py` and `evaluation.py` have become dual-proven (WC + UCL), while some modules (WC-specific governance, form, lineup) remain single-proven in the World Cup while they could theoretically be shared.

### 6.4 Two-Legged Tie Simulation in Core

The core `football_core/knockout.py` provides `simulate_single_match`, `simulate_two_legged_tie`, and `_simulate_penalty_shootout` — all three are shared primitives used by UCL. UCL's `competitions/ucl/src/knockout.py` imports `simulate_two_legged_tie` from the core and wraps it with UCL-specific orchestration (playoff round pairings for positions 9–24, seeded team home-advantage assignment, and specific ET/penalty calibration constants). This means the two-legged aggregate logic lives in the shared core, while the UCL-specific bracket resolution, playoff format, and seeding logic stay in the competition module.

### 6.5 JSON File Persistence over Database

All state is stored as human-readable JSON files. This was chosen for simplicity — no database setup, no schema migrations, and files can be inspected and hand-edited for debugging. The trade-off is no concurrent write safety (writes use atomic file swaps) and no query capability.

### 6.6 Signal Fusion Architecture

The World Cup blends up to **eight** independent prediction signals using Brier-weighted calibration. This is the most architecturally complex part of the system. The blender's pure-computation primitives (Platt scaling, rolling Brier, blend weighting) live in `football_core/blender.py`, while WC-specific orchestration (`calibrate_and_blend`) remains in `competitions/worldcup/src/blender.py`:

UCL also performs signal fusion, but with a simpler approach: up to **five** signals (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays) combined via a log-loss-weighted uniform blend implemented in `football_core.blender.EnsembleEngine`. Unlike the World Cup's online Brier-weighted calibration, UCL's weights are fitted offline from historical replay data via `competitions/ucl/src/calibrate.py` and stored in a static `signal_weights.json` file.

```
        ┌──────┐ ┌──────┐ ┌──────┐ ┌────┐ ┌─────┐
        │ Elo  │ │ Odds │ │CBoo. │ │Form│ │Line │
        └──┬───┘ └──┬───┘ └──┬───┘ └──┬─┘ └──┬──┘
           │        │        │        │      │
           │   ┌────▼──┐ ┌──▼───┐ ┌───▼────┐ │
           │   │Avail. │ │Def.  │ │Manager │ │
           │   │       │ │Qual. │ │Effect  │ │
           │   └──┬────┘ └──┬───┘ └───┬────┘ │
           └──────┴─────────┴─────────┴───────┘
                            │
                            ▼
                    ┌──────────────────┐
                    │  calibrate_and_  │  ← competitions/worldcup/src/blender.py
                    │  blend()         │     (orchestration)
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
