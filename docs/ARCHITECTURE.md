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
                    │  │  blender │  └────────┘  │ kno. │ │
                    │  │  eval.   │              │ grps │ │
                    │  │  gov.    │              │ val. │ │
                    │  │  enrich. │              └─────┘ │
                    │  │  const.  │                      │
                    │  └────┬─────┘                      │
                    └───────┼───────────────────────────┘
                            │ imports all via football_core.*
                            ▼
              ┌─────────────────────────────┐
              │       football_core/        │  ← SHARED ENGINE
              │                             │
              │  ┌──────┐ ┌──────┐ ┌─────┐  │
              │  │ elo  │ │groups│ │kno. │  │
              │  └──┬───┘ └──┬───┘ └──┬──┘  │
              │     │        │        │      │
              │  ┌──▼───┐ ┌──▼───┐ ┌──▼───┐ │
              │  │ state│ │fetcher│ │math  │ │
              │  └──────┘ └──────┘ └──────┘ │
              │                             │
              │  ┌──────────┐ ┌────────────┐│
              │  │predictors│ │evaluation  ││
              │  │ /odds    │ │ /constants ││
              │  │ /catboost│ │ /elo_sync  ││
              │  └──────────┘ └────────────┘│
              └─────────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │      External Services      │
              │                             │
              │  BSD API ── live match data │
              │  eloratings.net ── Elo sync │
              └─────────────────────────────┘
```

### 2.1 Competition-to-Core Import Patterns

Each competition imports from `football_core` differently:

| Competition | Import style | Example |
|---|---|---|
| **worldcup** | Re-export wrappers in `competitions/worldcup/src/` | `from football_core.elo import *` via `src/elo.py` |
| **euro** | Direct imports from `football_core` | `from football_core import elo, state` |
| **ucl** | Direct imports + selective `football_core.groups` | `from football_core.constants import EXPECTED_GOALS_BASE_RATE` |

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
                    │  │ a) Fetch matches │ │──→ BSD API        │
                    │  │    from BSD API  │ │    (football_core │
                    │  │                  │ │     .fetcher)     │
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
                    │  └────────┬────────┘ │                    │
                    │           ▼          │                    │
                    │  ┌─────────────────┐ │                    │
                    │  │ d) Calibrate &  │ │                    │
                    │  │    blend signals│ │  (worldcup only)   │
                    │  └────────┬────────┘ │                    │
                    │           ▼          │                    │
                    │  ┌─────────────────┐ │                    │
                    │  │ e) Run Monte    │ │  50000 iterations  │
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
  ┌───────────────────────────────────────────────┐
  │  3. Monte Carlo loop (N iterations)           │
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
  │  4. Aggregate        │
  │     results across   │
  │     N iterations     │
  └─────┬────────────────┘
        │
        ▼
  ┌──────────────────────┐
  │  5. Display          │
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
| **Signal fusion** | Multi-signal (ElO + odds + CatBoost + form + lineup) | Elo-only |
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
| `knockout.py` | Generic round simulation primitive: `_simulate_knockout_round`, `_build_round_map` | WC, Euro |
| `fetcher.py` | BSD API fetch pipeline: `fetch_raw_matches`, `process_matches`, `process_group_matches` | WC, Euro |
| `state.py` | JSON persistence with atomic writes: load/save for all state files | WC, Euro, UCL |
| `elo_sync.py` | Elo sync from eloratings.net with drift detection | WC, Euro |
| `evaluation.py` | Shared metric computation: Brier score, log loss, calibration curve | UCL |
| `math_utils.py` | Sigmoid utility | WC |
| `constants.py` | Generic constants only (K_FACTOR, Poisson params, timeouts) | WC, Euro, UCL |
| `predictors/odds.py` | Market odds fetch and vig removal | WC, Euro |
| `predictors/catboost.py` | CatBoost prediction fetch | WC, Euro |

### 4.3 Design Constraints

- **Flat package**: All modules live at the top level of `football_core/`. Subpackage reorganization into `compute/`, `signals/`, `bsd/`, `state/` is deferred until a third competition justifies it (see [FOOTBALL_ENGINE_ARCHITECTURE.md](./FOOTBALL_ENGINE_ARCHITECTURE.md) §2.4).
- **Data-directory parameterization**: Every `state.py` function accepts a `data_dir` parameter — no hardcoded paths.
- **League-ID parameterization**: `fetcher.py` and `constants.py` accept `league_id` parameters. The BSD API URL template and most competition-specific constants live in competition modules, not the core.
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
| **Maturity** | Most mature (613 tests) | Mature (dormant) | Mature (149 tests) |
| **CLI name** | `wc-predict` | `euro-predict` | `ucl-predict` |
| **Poll mode** | Continuous (60s interval) | Continuous (60s interval) | Single-run |
| **Group format** | 12 groups (A-L), 4 teams each | 6 groups (A-F), 4 teams each | Swiss-system, 36 teams, 8 matchdays |
| **Third-place advancers** | Top 8 of 12 | Top 4 of 6 | N/A (positions 9-24 → playoff) |
| **Knockout entry** | R32 → R16 → QF → SF → FINAL + TPP | R16 → QF → SF → FINAL | Playoff → R16 → QF → SF → FINAL |
| **R32 resolution** | Annex C (495-entry table, WC-specific) | Precomputed bracket JSON | Playoff round (positions 9-24, two-legged) |
| **Match format** | Single match per round | Single match per round | Two-legged aggregate + ET + penalties |
| **Signals used** | Elo, odds, CatBoost, form, lineup | Elo, odds, CatBoost | Elo only |
| **Blending** | Brier-weighted signal fusion | None | None |
| **Governance** | Drift detection, version tracking, backtest | None | None |
| **Display** | Rich: standings table, trend arrows, delta, signal detail, AI previews | Simple: probability table only | Structured: standings, playoff, bracket, odds table |
| **Validation** | History-based evaluation | None | `--validate` flag cross-checks vs BSD results |
| **BSD integration** | Full: group + knockout fetch, alias resolution | Full: group + knockout fetch | Partial: validation-only fetch |

### 5.3 World Cup-Specific Modules

These remain in `competitions/worldcup/src/` because no other competition needs them yet:

- `blender.py` — signal calibration and blending
- `evaluation.py` — WC-specific `evaluate_all_matches` (historical match evaluation)
- `governance.py` — model governance with drift detection
- `predictors/form.py` — form signal computation
- `predictors/lineup.py` — lineup strength signal
- `enrichment.py` — BSD stats/context field extraction
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

### 6.1 Flat Package over Subpackages

`football_core/` is deliberately flat (all modules at top level) rather than organized into `compute/`, `signals/`, `bsd/`, `state/` subpackages. The flat layout minimizes friction during the extraction phase and keeps import paths short. Reorganization is deferred until a third competition provides sufficient justification.

### 6.2 Sys.Path over pip Install

The project runs from source without a build step. This avoids tooling overhead (no `pyproject.toml`, no `setup.py`, no virtualenv requirement) and keeps the development loop fast: edit → run. The downside is that other projects cannot `pip install football_core`.

### 6.3 Rule-of-Two Extraction

Modules graduate to `football_core/` only when two competitions use them with identical call signatures. This prevents speculative abstraction. The cost is that some modules (blender, evaluation, governance, form, lineup) remain single-proven in the World Cup while they could theoretically be shared.

### 6.4 Single-Match vs Two-Legged Tie Simulation

The core `football_core/knockout.py` only simulates single matches (one Poisson draw per match). UCL's two-legged aggregate format with extra time and penalties is entirely UCL-specific (`competitions/ucl/src/knockout.py`). This keeps the core simple and lets UCL handle its unique format without leaking complexity into the shared library.

### 6.5 JSON File Persistence over Database

All state is stored as human-readable JSON files. This was chosen for simplicity — no database setup, no schema migrations, and files can be inspected and hand-edited for debugging. The trade-off is no concurrent write safety (writes use atomic file swaps) and no query capability.

### 6.6 Signal Fusion Architecture (World Cup Only)

The World Cup blends up to five independent prediction signals (Elo, market odds, CatBoost, form, lineup) using Brier-weighted calibration. This is the most architecturally complex part of the system:

```
        ┌──────┐ ┌──────┐ ┌──────┐ ┌────┐ ┌─────┐
        │ Elo  │ │ Odds │ │CBoo. │ │Form│ │Line │
        └──┬───┘ └──┬───┘ └──┬───┘ └──┬─┘ └──┬──┘
           └────┬───┴────────┴────────┴──────┘
                │
                ▼
        ┌──────────────────┐
        │  calibrate_and_  │  ← blender.py
        │  blend()         │     (calibrate each signal against
        │                  │      history, then Brier-weighted blend)
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

This architecture keeps the simulation engine clean — it consumes `blend_params` as a dict and does not need to know how signals are combined. Signal fusion remains entirely in the World Cup domain because no other competition performs blending.

---

## 7. References

For detailed information on specific architectural areas, see these sibling documents:

- **[FOOTBALL_ENGINE_ARCHITECTURE.md](./FOOTBALL_ENGINE_ARCHITECTURE.md)** — Complete module inventory, stable abstraction schemas, public API signatures, aspirational destination architecture, migration execution summary, and remaining work items.
- **[COMMONALITY_REPORT.md](./COMMONALITY_REPORT.md)** — Empirical dual-proven audit showing exactly which modules are shared, which are competition-specific, and why.
