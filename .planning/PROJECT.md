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
- ✓ **UCL competition module** (`competitions/ucl/`) — full Swiss-system group stage + knockout + CLI + validation, reusing `football_core` with zero modifications — v1.0

### Active

- [ ] **ENG-02**: Euro's `sys.path` hack removed — shared group/advancement logic refactored into `football_core` so Euro no longer depends on worldcup directory
- [ ] **ENG-03**: `football_core` public API stabilized — documented, consistent interface for competition modules
- [ ] **ENG-04**: `football_core` proven by 3+ competitions — World Cup, Euro, UCL (3 proven ✓), need at least one domestic league
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

**Shipped v1.0** (2026-06-29): UCL competition module with full Swiss-system league phase, knockout bracket, Monte Carlo simulation, BSD API validation, and documentation. 22,244 LOC Python across 94 files. `football_core` proven by 3 competitions (WC, Euro, UCL).

Remaining legacy:
- Euro's `__init__.py` still mutates `sys.path` to reach WC-specific `src.groups` functions — these need to be refactored into `football_core`
- `competitions/worldcup/src/` still holds single-proven modules (blender, governance, form, lineup, enrichment) — some now shared (evaluation extracted to football_core)
- `competitions/ucl/` is a full competition module — Swiss-system + knockout + CLI + validation

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
| UCL next (not La Liga) | Swiss-system + knockout is closer to existing tournament pattern; lower risk for proving architecture | ✓ Good — UCL shipped v1.0 |
| Keep sys.path bootstrap | Avoid packaging overhead until interfaces stabilize across 3+ competitions | ✓ Good — 3 competitions proven |
| Rule of Two for core changes | Prevents competition-specific abstractions from leaking into shared engine | ✓ Good — evaluation metrics extraction proved the rule |
| No UI layer | Engine-first; web/mobile is a separate concern | — Pending (not relevant yet) |
| Synthetic schedules for dev, official for validation | Unblocks competition dev without official fixtures; gates validation/benchmarking/public reporting | ✓ ADR-002 — honored |
| Elo-based expected_score for validation | Same foundation as simulation engine, no MC loop modification | ✓ Good — used in `run_validation()` |
| Evaluation extraction: verbatim copy to football_core | Preserves WC 613-test regression compatibility | ✓ Good — 38 WC evaluation tests pass |

## Next Milestone Goals

Potential directions for v1.1+ (subject to `/gsd:new-milestone` questioning):

1. **Domestic league module** (La Liga / Premier League) — prove football_core handles double round-robin format
2. **Euro refactoring** — remove sys.path hack, extract shared group/advancement logic into football_core
3. **Package & publish** — pyproject.toml for pip-installable football_core
4. **UCL differentiators** — what-if scenarios, path visualization, strength-of-schedule reporting

---

*Last updated: 2026-06-29 after v1.0 milestone*
