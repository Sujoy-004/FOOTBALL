# Codebase Structure

**Analysis Date:** 2026-06-27

## Directory Layout

```
FOOTBALL/
├── football_core/          # Shared tournament engine (generic, competition-agnostic)
├── competitions/           # Competition-specific packages
│   ├── worldcup/           # World Cup 2026 Dynamic Predictor (full implementation)
│   ├── euro/               # UEFA Euro 2024 Dynamic Predictor (simpler, standalone)
│   └── ucl/                # UCL Predictor (placeholder — README.md only)
├── docs/                   # Architecture and commonality reports
│   ├── FOOTBALL_ENGINE_ARCHITECTURE.md
│   └── COMMONALITY_REPORT.md
├── .planning/              # GSD planning artifacts (gitignored)
│   └── codebase/           # Codebase mapping documents (this file + ARCHITECTURE.md)
├── .gitignore
└── RESPONSE.md             # Git-committed operational artifact
```

## Directory Purposes

**`football_core/`** — Shared Engine Layer:
- Purpose: Generic tournament simulation primitives usable by any competition
- Contains: Python modules for Elo ratings, group simulation, knockout bracket processing, state persistence, API data fetcher, Elo synchronization, math utilities, shared constants, and predictor signal ingestion (odds, CatBoost)
- Key files:
  - `__init__.py` — Empty (namespace package marker)
  - `constants.py` — Shared numeric constants (K_FACTOR=60, DEFAULT_ELO=1500, Poisson table sizing, API timeout, Elo sync params)
  - `elo.py` — Elo rating engine: `expected_score()`, `update_ratings()`, `apply_elo_update()`
  - `groups.py` — Generic group simulation: Poisson scoring, tiebreaker chain, match simulation
  - `knockout.py` — Generic knockout round processing: round map building, match simulation, blended probabilities
  - `state.py` — Generic state persistence: JSON load/save with atomic writes, bracket DAG validation, cache helpers
  - `fetcher.py` — Generic BSD API fetcher: `fetch_raw_matches()`, `process_matches()`, `process_group_matches()`
  - `elo_sync.py` — Generic Elo sync from eloratings.net: fetch TSV, parse, validate, graduated correction
  - `math_utils.py` — `sigmoid()` utility
  - `predictors/` — Generic predictor signal ingestion
    - `__init__.py` — Empty
    - `odds.py` — Market odds ingestion (`remove_vig()`, `fetch_and_cache_odds()`)
    - `catboost.py` — CatBoost ML prediction ingestion (`fetch_and_cache_catboost()`)

**`competitions/worldcup/`** — World Cup 2026 Predictor:
- Purpose: Full-featured live tournament predictor with multi-signal blending, governance, and evaluation
- Contains: Entry point, src/ package with all logic, test suite, benchmarks, scripts, JSON data files
- State files at top level: `config.json`, `form_cache.json`, `lineup_cache.json`, `predictions_ledger.json`, `probability_log.json`
- Key subdirectories:
  - `src/` — All WC-specific logic (see below)
  - `tests/` — Comprehensive pytest test suite (27 test files + conftest.py)
  - `scripts/` — Utility scripts (`benchmark_simulation.py`)
  - `benchmarks/` — Performance benchmarks (`benchmark_groups.py`)
  - `data/` — Competition data and persistent state
    - `teams.json`, `groups.json`, `bracket.json`, `annex_c.json` — Static tournament structure
    - `team_aliases.json`, `team_values.json` — Supporting static data
    - `played.json`, `played_groups.json` — Ingested match results
    - `prediction_history.json`, `predictions_ledger.json` — Prediction records
    - `calibration_params.json`, `versions.json` — Model state
    - `odds_cache.json`, `catboost_cache.json`, `form_cache.json`, `lineup_cache.json` — Signal caches
    - `eloratings_cache.json`, `elo_update_log.json`, `elo_applied.json` — Elo tracking
    - `eval_baseline_report.json`, `eval_backtest_report.json` — Evaluation reports
    - `probability_log.json` — Rolling probability snapshot log
    - `historical/` — Historical tournament data for backtesting (`2018.json`, `2022.json`)
  - `docs/archive/refactor/` — Architecture summary docs from past refactoring milestones

**`competitions/worldcup/src/`** — World Cup logic modules:

| File | Purpose | Lines | Depends on |
|------|---------|-------|------------|
| `__init__.py` | Package marker (empty) | 0 | — |
| `main.py` | Entry point, CLI, polling loop, orchestration | ~1350 | All src/* modules + football_core |
| `constants.py` | WC-specific constants + league mapping | 254 | `football_core.constants` |
| `state.py` | Extended state persistence (prediction ledger, calibration, versions) | 384 | `football_core.state` |
| `elo.py` | WC-specific Elo wrappers (standalone `expected_score`) | ~30 | None (stdlib only) |
| `elo_sync.py` | WC Elo sync with team code mapping | 94 | `football_core.elo_sync` |
| `groups.py` | WC group standings: 48-team, 12 groups, Annex C third-place advancement | 224 | `football_core.groups` |
| `knockout.py` | WC knockout: R32→R16→QF→SF→TPP→FINAL, 50K Monte Carlo simulation | 232 | `football_core.groups`, `football_core.knockout`, `src.groups` |
| `fetcher.py` | WC fetcher with historic URL, AI preview extraction, enriched processing | 219 | `football_core.fetcher`, `src.enrichment` |
| `output.py` | Terminal display: probability tables, match alerts, group standings, ANSI colors | 952 | `src.constants`, `src.elo_sync` |
| `blender.py` | Signal calibration & blending: Platt scaling, Brier weighting, LOO-CV | 456 | `src.constants`, `src.elo` |
| `evaluation.py` | Brier score, log loss, calibration curves, ECE computation | 427 | `src.elo` |
| `governance.py` | Version tracking, drift detection, model oversight | 573 | `src.evaluation` |
| `enrichment.py` | Match stats & context extraction from BSD event dicts | 93 | None (stdlib + logging) |
| `math_utils.py` | Empty/placeholder | — | — |
| `predictors/` | WC prediction signal computation | | |
| `predictors/__init__.py` | Package docstring | 6 | — |
| `predictors/odds.py` | Market odds ingestion (WC-specific overrides) | ~120+ | `football_core.predictors.odds` |
| `predictors/catboost.py` | CatBoost ingestion (WC-specific overrides) | ~180+ | `football_core.predictors.catboost` |
| `predictors/form.py` | Form residual signal computation | — | `src.state`, `src.elo` |
| `predictors/lineup.py` | Lineup strength signal computation | — | `src.constants` |

**`competitions/euro/`** — Euro 2024 Predictor:
- Purpose: Standalone simpler predictor (no multi-signal blending, no governance)
- Contains: Entry point, competition config, simulation, display — does NOT have a separate `src/` package
- Key files:
  - `__init__.py` — sys.path bootstrap (imports repo root + worldcup path)
  - `main.py` — Entry point (`~260 lines`), polling loop, basic orchestration
  - `config.py` — Competition constants (SIMULATION_ITERATIONS=50000, 6 groups, ROUND_ORDER, DEFAULT_LEAGUE_ID=3)
  - `simulation.py` — Full tournament simulation (6 groups → R16 → QF → SF → FINAL), imports `football_core.*` and `src.groups` (from worldcup)
  - `display.py` — Terminal display (header, probability table, match alerts, heartbeat)
  - `data/` — Competition data
    - `teams.json`, `groups.json`, `bracket.json`

**`competitions/ucl/`** — UCL Predictor (placeholder):
- Contains: `README.md` with "Coming soon."

**`tests/`** — Test suites:
- Located at `competitions/worldcup/tests/` (27 test files + conftest.py + __init__.py)
- No root-level test directory — all tests are competition-scoped
- 26 test modules covering: elo, groups, knockout, state, CLI, fetcher, odds, catboost, blender, governance, evaluation, enrichment, form, lineup, live smoke, migration, integration, group integration, main loop, config, scaffold, output, state load, elo sync

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` — e.g., `elo_sync.py`, `math_utils.py`, `test_elo.py`
- Package init: `__init__.py`
- JSON data: `snake_case.json` — e.g., `teams.json`, `played_groups.json`, `prediction_history.json`
- Test files: `test_<module>.py` — e.g., `test_elo.py`, `test_knockout.py`, `test_blender.py`
- Script files: `snake_case_name.py` — e.g., `benchmark_simulation.py`

**Functions:**
- `snake_case` — e.g., `expected_score()`, `process_matches()`, `resolve_knockout_slot_teams()`, `_run_iteration()`
- Private/helper functions prefixed with `_` — e.g., `_build_round_map()`, `_simulate_knockout_round()`, `_atomic_write_json()`
- Descriptive verb-noun patterns — e.g., `load_teams()`, `save_played()`, `validate_bracket()`, `fetch_raw_matches()`

**Variables:**
- `snake_case` — e.g., `elo_ratings`, `played_groups`, `winner_progression`, `matchup_lambdas`
- Constants in `UPPER_SNAKE_CASE` — e.g., `K_FACTOR`, `DEFAULT_ELO`, `POLL_INTERVAL`, `ELO_SYNC_INTERVAL_HOURS`
- Module-level state instances prefixed with `_` — e.g., `_state = RunState()`

**Types:**
- Type hints used throughout with standard Python syntax — e.g., `dict[str, dict]`, `list[dict[str, Any]]`, `tuple[str, float]`
- `dataclass` used for structured state containers — e.g., `class RunState` in `worldcup/main.py`
- No custom type aliases or `TypedDict` definitions detected

**Directories:**
- `snake_case` — e.g., `football_core/`, `competitions/`, `predictors/`, `benchmarks/`, `scripts/`
- Single competition directories use short names — `worldcup/`, `euro/`, `ucl/`

**Test Fixtures:**
- `snake_case` prefixed with `sample_` in fixtures — e.g., `sample_teams`, `sample_bracket`, `sample_played`, `sample_group_matches_results`

## Where to Add New Code

**New Competition:**
- Create `competitions/<name>/` with `__init__.py` (sys.path bootstrap), `main.py`, `config.py`, `simulation.py`, `display.py`
- Import primitives from `football_core/` for generic features; override as needed
- Tests go in `competitions/<name>/tests/`

**New Feature (World Cup):**
- Business logic: `competitions/worldcup/src/<feature>.py`
- Display output: extend `competitions/worldcup/src/output.py`
- Constants: `competitions/worldcup/src/constants.py`
- State persistence: `competitions/worldcup/src/state.py`
- Tests: `competitions/worldcup/tests/test_<feature>.py`

**New Shared Primitive:**
- `football_core/<primitive>.py` — Must have zero competition-specific imports
- `football_core/predictors/<signal>.py` — For prediction signal computation

**New Signal (predictor):**
- Implementation: `competitions/worldcup/src/predictors/<name>.py`
- Tests: `competitions/worldcup/tests/test_<name>.py`
- Constants: `competitions/worldcup/src/constants.py` (add cache file, TTL, tuning parameters)
- Integration: wire into `_run_iteration()` in `competitions/worldcup/main.py`

**New Data File:**
- Static tournament data: `competitions/<name>/data/<file>.json`
- Persistent runtime state: `competitions/worldcup/data/<league_id>/<file>.json`

## Special Directories

**`.planning/`:**
- Purpose: GSD planning artifacts — codebase maps, phase plans, milestone documents
- Generated: Yes (by GSD workflow tools like `/gsd-map-codebase`, `/gsd-plan-phase`)
- Committed: No (listed in `.gitignore`)

**`competitions/worldcup/__pycache__/` and `competitions/worldcup/tests/__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes (by Python interpreter)
- Committed: No (listed in `.gitignore` via `__pycache__/` pattern)

**`competitions/worldcup/data/runs/`:**
- Purpose: Governance run snapshots directory
- Generated: Yes (by governance module at runtime)
- Committed: No (runtime artifacts)

**`competitions/worldcup/docs/`:**
- Purpose: Architecture documentation from past refactoring milestones
- Generated: No (hand-written)
- Committed: Yes

---

*Structure analysis: 2026-06-27*
