<!-- refreshed: 2026-06-27 -->
# Architecture

**Analysis Date:** 2026-06-27

## System Overview

The codebase is a **modular monolith** for football tournament prediction. A shared engine library (`football_core`) provides generic tournament primitives while competition-specific packages (`competitions/worldcup/`, `competitions/euro/`, `competitions/ucl/`) layer on top with competition-specific logic, data, and entry points.

```text
┌────────────────────────────────────────────────────────────────┐
│                     ENTRY POINTS                                │
│  competitions/worldcup/main.py    competitions/euro/main.py     │
├──────────────────┬────────────────┬────────────────────────────┤
│                  │                │                             │
│  World Cup src/  │  Euro src/     │  UCL (placeholder)         │
│  ─────────────   │  ─────────     │  ─────────────────         │
│  main.py         │  simulation.py │  README.md only            │
│  src/*.py        │  config.py     │                             │
│  src/predictors/ │  display.py    │                             │
│  tests/          │  data/         │                             │
└────────┬─────────┴────────┬───────┴────────┬────────────────────┘
         │                  │                │
         ▼                  ▼                ▼
┌────────────────────────────────────────────────────────────────┐
│                   SHARED ENGINE (football_core/)                │
│                                                                │
│  ┌──────────┬───────────┬──────────┬──────────┬─────────┐     │
│  │  elo.py  │ groups.py │knockout.py│state.py │fetcher.py│     │
│  ├──────────┼───────────┼──────────┼──────────┼─────────┤     │
│  │elo_sync  │ math_utils│constants │predictors│         │     │
│  │.py       │ .py       │ .py      │ /        │         │     │
│  └──────────┴───────────┴──────────┴──────────┴─────────┘     │
└──────────────────────────────┬─────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────┐
│                  EXTERNAL SERVICES                              │
│                                                                │
│  BSD API (sports.bzzoiro.com) — live match results + odds      │
│  eloratings.net — Elo rating TSV sync                          │
│  Local JSON files — team data, bracket, groups, caches         │
└────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | Files |
|-----------|---------------|-------|
| **football_core/** | Shared tournament engine — generic, competition-agnostic | `football_core/*.py`, `football_core/predictors/*.py` |
| **competitions/worldcup/** | World Cup 2026 full predictor (48-team, 12 groups) | `main.py`, `src/*.py`, `src/predictors/*.py` |
| **competitions/euro/** | UEFA Euro 2024 predictor (24-team, 6 groups) | `main.py`, `config.py`, `simulation.py`, `display.py` |
| **competitions/ucl/** | Placeholder for future UCL predictor | `README.md` only |

## Pattern Overview

**Overall:** Layer-based modular monolith with functional core.

**Key Characteristics:**
- **Layered isolation** — `football_core/` has zero awareness of any competition; competitions import from it
- **Functional purity** — Core simulation logic uses pure functions (no classes, no mutation); state I/O is separated into `state.py` modules
- **Extend-via-import** — Competition modules extend `football_core` by importing primitives and wrapping them with competition-specific logic (e.g., `src/groups.py` imports `football_core.groups.*` and adds WC-specific standings)
- **Polling loop** — Both `main.py` entry points implement a continuous poll→fetch→simulate→display cycle
- **Monte Carlo simulation** — 50,000-iteration loop over group + knockout stages produces probability distributions

## Layers

**Shared Engine Layer (`football_core/`):**
- Purpose: Generic tournament primitives usable by any competition
- Location: `football_core/`
- Contains: Elo engine (`elo.py`), group simulation (`groups.py`), knockout round robin (`knockout.py`), state persistence (`state.py`), BSD API fetcher (`fetcher.py`), Elo sync w/ eloratings.net (`elo_sync.py`), math helpers (`math_utils.py`), constants (`constants.py`), predictor signal ingestion (`predictors/odds.py`, `predictors/catboost.py`)
- Depends on: `requests` HTTP library, Python stdlib
- Used by: `competitions/worldcup/`, `competitions/euro/`

**Competition Layer (`competitions/{worldcup,euro}/`):**
- Purpose: Competition-specific orchestration, simulation, display
- Location: `competitions/worldcup/`, `competitions/euro/`
- Contains: Entry point `main.py`, competition `config.py`, `simulation.py`, `display.py` (euro); full `src/` package with groups, knockout, evaluation, governance, blender, enrichment, predictors, output (worldcup)
- Depends on: `football_core/`, competition data JSON files
- Used by: End users (entry points)

**Data Layer:**
- Purpose: Persistent state (team data, results, caches)
- Location: `competitions/worldcup/data/`, `competitions/euro/data/`, `competitions/worldcup/*.json`
- Contains: `teams.json`, `groups.json`, `bracket.json`, `played.json`, `played_groups.json`, `prediction_history.json`, cache files, calibration params, version data
- Persistence: JSON files on local filesystem, read/written via `football_core.state` and `src.state` modules

## Data Flow

### Primary Request Path (World Cup)

1. **Startup** — `competitions/worldcup/main.py:main()` parses args, loads `.env`, validates API key, loads all state (`teams.json`, `groups.json`, `bracket.json`, `annex_c.json`, `played.json`, `played_groups.json`), runs initial Elo sync
2. **Historical catch-up** — `_run_historical_catch_up()` (`main.py:328`) fetches BSD API from tournament start to today, ingests unplayed group + knockout matches, applies Elo updates chronologically
3. **Polling loop** — `_run_iteration()` (`main.py:743`) runs continuously:
   a. **Fetch** — `fetch_raw_matches()` from BSD events API (`src/fetcher.py` → `football_core/fetcher.py:15`)
   b. **Process** — `process_matches()` and `process_group_matches()` match API results to bracket/group structure using team aliases
   c. **Elo update** — `elo.apply_elo_update()` (`football_core/elo.py:66`) updates team ratings on new results
   d. **Signal ingestion** — odds (`predictors/odds.py`), CatBoost ML (`predictors/catboost.py`), form (`predictors/form.py`), lineup strength (`predictors/lineup.py`)
   e. **Calibrate & Blend** — `_run_calibrate_and_blend()` (`main.py:119`) delegates to `src/blender.py:calibrate_and_blend()` for Platt scaling + Brier-weighted blending
   f. **Governance** — `_run_governance()` (`src/governance.py`) checks drift, updates version tracking
   g. **Simulate** — `run_full_simulation()` (`src/knockout.py:160`) runs 50K Monte Carlo iterations through group stage → R32 → R16 → QF → SF → TPP → FINAL
   h. **Display** — `output.print_probability_table()` (`src/output.py`) shows team probabilities with deltas
4. **Shutdown** — Signal handler sets `_state.running = False`, final simulation runs, state is persisted

### Euro Data Flow

Mirrors World Cup but simplified: no CatBoost/form/lineup signals, no blender, no governance. Uses `football_core` directly for Elo, state, fetchers. Competition-specific simulation in `competitions/euro/simulation.py` (6 groups → R16 → QF → SF → FINAL).

### State Management

- **JSON persistence** — All state is stored as JSON files on the local filesystem
- **Atomic writes** — `football_core/state.py:_atomic_write_json()` uses tempfile + os.replace for crash-safe writes
- **Per-league scoping** — State is stored under `data/<league_id>/` subdirectory (Phase 19 migration)
- **Cache layers** — Signal data (odds, CatBoost, form, lineup) uses TTL-based caching with `is_cache_valid()` checking expiry timestamps

## Key Abstractions

**Elo Engine:**
- Purpose: Rating system for team strength; used for match prediction probabilities and Monte Carlo simulation
- Files: `football_core/elo.py`, `competitions/worldcup/src/elo.py`, `competitions/worldcup/src/elo_sync.py`
- Pattern: Pure functions (`expected_score()`, `update_ratings()`, `apply_elo_update()`)
- External sync: `football_core/elo_sync.py` fetches from eloratings.net TSV, parses, validates, applies graduated correction

**Group Simulation:**
- Purpose: Round-robin group match simulation with Poisson scoring model and FIFA-standard tiebreaker chain
- Files: `football_core/groups.py` (generic), `competitions/worldcup/src/groups.py` (WC-specific standings), `competitions/euro/simulation.py` (Euro-specific)
- Pattern: Precomputed Poisson CDF tables → fast table-lookup sampling; tiebreaker chain: H2H points → H2H GD → H2H GS → overall GD → overall GS → conduct score → Elo → alphabetical

**Knockout Tournament:**
- Purpose: Bracket-based elimination rounds with winner progression
- Files: `football_core/knockout.py` (generic), `competitions/worldcup/src/knockout.py` (WC: R32→R16→QF→SF→TPP→FINAL), `competitions/euro/simulation.py` (Euro: R16→QF→SF→FINAL)
- Pattern: `_build_round_map()` creates round→matches mapping; `_simulate_knockout_round()` advances winners; World Cup includes third-place playoff (TPP) and SF loser tracking

**Signal Blending:**
- Purpose: Combine multiple prediction signals (Elo, market odds, CatBoost, form, lineup) into calibrated blended probabilities
- Files: `competitions/worldcup/src/blender.py`
- Pattern: Platt scaling for calibration, Brier-weighted rolling average for blend weights, LOO-CV for evaluation — all pure Python stdlib

**State Persistence:**
- Purpose: JSON load/save with atomic writes, bracket validation, cache helpers
- Files: `football_core/state.py` (generic), `competitions/worldcup/src/state.py` (extended with WC-specific features: prediction ledger, calibration params, version tracking, migration)
- Pattern: Functions only — `load_*()` / `save_*()` pairs per data type

## Entry Points

**World Cup Predictor:**
- Location: `competitions/worldcup/main.py` (function `main()`)
- Triggers: CLI invocation (`python main.py`), supports `--once`, `--seed`, `--no-color`, `--ai-preview`, `--match-detail`, `--league`, `--list-leagues`
- Responsibilities: Full lifecycle — startup validation, data loading, historical catch-up, continuous polling, signal ingestion, calibration/blending, Monte Carlo simulation, probability display, governance, graceful shutdown
- CLI: `wc-predict`

**Euro 2024 Predictor:**
- Location: `competitions/euro/main.py` (function `main()`)
- Triggers: CLI invocation (`python main.py`), supports `--once`, `--seed`
- Responsibilities: Simplified lifecycle — data loading, Elo sync, polling loop, basic simulation, probability display
- CLI: `euro-predict`

## Architectural Constraints

- **Threading:** Single-threaded event loop with synchronous I/O. Polling uses `time.sleep()` with 0.5s granularity for responsive shutdown.
- **Global state:** `competitions/worldcup/main.py` uses a module-level `RunState` dataclass instance `_state` for polling loop state. `competitions/euro/main.py` uses a lightweight `_RunState` class instance.
- **Circular imports:** None detected — dependency direction is strictly `football_core` ← competitions.
- **sys.path bootstrap:** Each competition `__init__.py` inserts the repo root and package dir into `sys.path` at import time (`competitions/worldcup/__init__.py`, `competitions/euro/__init__.py`).
- **No config/ini/yaml:** Configuration is entirely through Python constants and CLI args.

## Anti-Patterns

### Long module-level orchestration

**What happens:** `competitions/worldcup/main.py` is ~1350 lines with numerous private functions, complex data flow, and deep nesting.
**Why it's wrong:** Hard to isolate for testing; most logic is exercised only via integration tests or not at all.
**Do this instead:** Extract orchestration into smaller dedicated modules (similar to how `blender.py` and `governance.py` handle their concerns).

### sys.path bootstrap via __init__.py

**What happens:** `competitions/worldcup/__init__.py` and `competitions/euro/__init__.py` mutate `sys.path` at import time.
**Why it's wrong:** Side effects at import time can cause issues in testing environments. Requires the competition module to be imported before its submodules.
**Do this instead:** Use a proper Python package structure with setup.py/pyproject.toml, or use PYTHONPATH in the CI/run script.

## Error Handling

**Strategy:** Graceful degradation — most failures print warnings and continue rather than crashing.

**Patterns:**
- Fetch failures return `[]` (empty list) instead of raising
- Signal ingestion failures fall back to cached data or Elo-only
- Each step in `_run_iteration()` is wrapped in try/except with `print(f"Warning: ... {e}")`
- API key validation exits with code 1 on missing/invalid key
- Deep nested error handling in main loop (many empty `except: pass` blocks in euro version)

## Cross-Cutting Concerns

**Logging:** `logging.getLogger(__name__)` in each module; imported in `main.py` with `logging.basicConfig(level=logging.INFO)`

**Validation:** Bracket DAG validation (`football_core/state.py:validate_bracket()`) — detects cycles and duplicate match IDs; Eloratings data validation (`football_core/elo_sync.py:validate_eloratings_data()`)

**Authentication:** BSD API key from `BSD_API_KEY` env var (loaded via `python-dotenv`); validated at startup with HTTP 401 check

---

*Architecture analysis: 2026-06-27*
