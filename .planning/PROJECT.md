# Football Prediction Engine

## What This Is

A modular football prediction engine where competition-specific modules plug into a shared core. Instead of forking the codebase for each tournament or league, every competition implements its rules on top of `football_core` — a stable, well-tested library of prediction, simulation, calibration, and evaluation primitives.

## Core Value

Adding a new competition requires only a new competition module — not changes to `football_core`. Every architectural decision is evaluated against: *Does this make the next competition easier to add?*

## Requirements

### Validated

- ✓ **Shared engine (`football_core/`)** — elo, groups, knockout, state, fetcher, constants, math_utils, predictors/odds, predictors/catboost — all dual-proven by World Cup and Euro
- ✓ **World Cup competition** (`competitions/worldcup/`) — 613 tests, live polling loop, signal blending, governance, CLI entry point
- ✓ **Euro competition** (`competitions/euro/`) — simulation engine, display, config, CLI entry point
- ✓ **Sys.path bootstrap** — import mechanism allowing `from football_core import *` and cross-competition imports
- ✓ **BSD API integration** — live match results, odds, CatBoost predictions via sports.bzzoiro.com
- ✓ **Elo ratings sync** — fetch and apply from eloratings.net
- ✓ **Poisson simulation** — match-level goal distribution model
- ✓ **Monte Carlo tournament simulation** — 50K iteration competition forecasting
- ✓ **Signal blending** — Platt-scaled calibration + weighted blend of Elo, market odds, CatBoost
- ✓ **Evaluation framework** — Brier score, log loss, calibration curves, backtesting
- ✓ **Governance** — data/model versioning, drift detection, run snapshots
- ✓ **CLI architecture** — long-running polling loop, cross-platform (Windows SIGBREAK handler)
- ✓ **Codebase map** — `.planning/codebase/` with 7 documents covering stack, architecture, conventions, testing, integrations, concerns

### Active

- [ ] **ENG-01**: UCL competition module — full Swiss-system group stage + knockout, plugging into `football_core` without core modifications
- [ ] **ENG-02**: Euro's `sys.path` hack removed — shared group/advancement logic refactored into `football_core` so Euro no longer depends on worldcup directory
- [ ] **ENG-03**: `football_core` public API stabilized — documented, consistent interface for competition modules
- [ ] **ENG-04**: `football_core` proven by 3+ competitions — World Cup, Euro, UCL, and at least one domestic league
- [ ] **ENG-05**: La Liga / Premier League competition module — proving the core handles league-style (double round-robin) competitions

### Out of Scope

- **pip-installable package** — deferred until 3 competitions (WC, UCL, 1 league) are proven stable and interfaces stop changing
- **Web UI / dashboard** — the engine is CLI-only; web layer is a separate project
- **Real-time live betting** — predictions are tournament-forecast, not in-play
- **Mobile app** — not relevant to the engine architecture
- **ML model training pipeline** — CatBoost models are consumed, not trained, by this engine

## Context

The codebase started as a monolith (`worldcup_predictor/`) for the 2026 World Cup. A Euro 2024 module was added by importing generic modules from the WC package — proving the Rule of Two: modules used by both competitions are candidates for extraction.

This extraction produced `football_core/` at the repo root with 12 shared modules. The WC and Euro modules now depend on `football_core` through a sys.path bootstrap mechanism (no package install).

Remaining legacy:
- Euro's `__init__.py` still mutates `sys.path` to reach WC-specific `src.groups` functions — these need to be refactored into `football_core`
- `competitions/worldcup/src/` still holds single-proven modules (blender, evaluation, governance, form, lineup, enrichment) — extract only when a second competition needs them
- `competitions/ucl/` is a placeholder README — the next competition to build

## Constraints

- **Python 3.11+** — all code and CI targets 3.10–3.12
- **No new runtime dependencies** — stick to stdlib + requests + catboost (already in requirements.txt)
- **No modifying `football_core` for a single competition** — every change must be justified by evidence from multiple competitions
- **Sys.path bootstrap** — keep until 3 competitions are proven; no pyproject.toml yet
- **WC regression suite** — must remain green (613 passed, 1 skipped) after every change
- **Euro simulation** — must produce identical results after every change
- **Competition boundary** — competition-specific rules, data, display, config live in `competitions/<name>/`; zero competition logic in `football_core`

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| `football_core` at repo root (flat) | Minimize friction; subpackages deferred until third competition justifies reorganization | ✓ Good |
| UCL next (not La Liga) | Swiss-system + knockout is closer to existing tournament pattern; lower risk for proving architecture | — Pending |
| Keep sys.path bootstrap | Avoid packaging overhead until interfaces stabilize across 3+ competitions | ✓ Good |
| Rule of Two for core changes | Prevents competition-specific abstractions from leaking into shared engine | ✓ Good |
| No UI layer | Engine-first — web/mobile is a separate concern | — Pending |
| Synthetic schedules for dev, official for validation | Unblocks competition dev without official fixtures; gates validation/benchmarking/public reporting | ✓ ADR-002 |

---

*Last updated: 2026-06-27 after initialization*
