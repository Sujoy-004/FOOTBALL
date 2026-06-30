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

### v2 (UCL Prediction Quality)

- [ ] **UCLF-01**: BSD fixtures as primary simulation source, repo as fallback (Phase 5)
- [ ] **UCLF-02**: FixtureProvider abstraction with two implementations (Phase 5)
- [ ] **UCLF-03**: Remove synthetic-only execution path (Phase 5)
- [ ] **UCLM-01**: Three simulation modes — simulate, replay, live (Phase 6)
- [ ] **UCLM-02**: PlayedMatches override in simulation engine (Phase 6)
- [ ] **UCLS-01**: Multi-signal architecture with SignalRegistry (Phase 7)
- [ ] **UCLS-02**: Refined Elo with configurable K-factor (Phase 7)
- [ ] **UCLS-03**: Market odds as simulation signal (Phase 7)
- [ ] **UCLS-04**: Rolling form features (Phase 7)
- [ ] **UCLS-05**: Squad value signal (Phase 7)
- [ ] **UCLS-06**: Rest days signal (Phase 7)
- [ ] **UCLB-01**: Weighted ensemble with inverse-log-loss weights (Phase 8)
- [ ] **UCLB-02**: Market integration — calibration baseline, blended signal, value detection (Phase 8)
- [ ] **UCLB-03**: EnsembleEngine with JSON config (Phase 8)
- [ ] **UCLV-07**: Three-tier validation — cross-tournament, walk-forward, replay (Phase 9)
- [ ] **UCLV-08**: TRPS tournament-level metric (Phase 9)
- [ ] **UCLV-09**: Automated validation suite (Phase 9)
- [ ] **UCLC-01**: Temperature scaling for calibration (Phase 10)
- [ ] **UCLC-02**: Bayesian/Glicko-style Elo with uncertainty (Phase 10)
- [ ] **UCLC-03**: Confidence intervals on champion probabilities (Phase 10)
- [ ] **UCLE-01**: Prediction breakdown / signal contribution display (Phase 11)
- [ ] **UCLE-02**: Counterfactual analysis (`--what-if`) (Phase 11)
- [ ] **UCLE-03**: Production config management and CLI cleanup (Phase 11)

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

**Planning v2.0** (2026-06-29): UCL prediction quality milestone — 7 phases addressing root causes identified in RESPONSE.md: real fixture ingestion, simulation modes, multi-signal architecture, signal blending, tournament validation (baseline), calibration/uncertainty (improvement), and explainability/production refinements. Driven by RESEARCH.md architectural study.

Remaining legacy:
- Euro's `__init__.py` still mutates `sys.path` to reach WC-specific `src.groups` functions — these need to be refactored into `football_core`
- `competitions/worldcup/src/` still holds single-proven modules (blender, governance, form, lineup, enrichment) — some now shared (evaluation extracted to football_core)
- `competitions/ucl/` is a full competition module — Swiss-system + knockout + CLI + validation

## Constraints

- **Python 3.11+** — all code and CI targets 3.10–3.12
- **No new runtime dependencies** — stick to stdlib + requests + catboost (already in requirements.txt)
- **Generic functionality belongs in `football_core`** — competition-agnostic primitives (fixture providers, signal interfaces, calibration pipelines, evaluation utilities) should live in `football_core` once proven by 2+ competitions. Competition-specific logic (UCL Swiss-system, WC group stage, league rules) stays in `competitions/<name>/`
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
| **v2 phases consolidated from 11 research topics to 7 phases** | Dependent topics grouped into coherent implementation phases; each phase independently executable | ✓ Planned — see ROADMAP.md |
| **Temperature scaling over isotonic regression** | Limited calibration data (1 UCL season ≈ 144 matches); single-parameter T is robust | ✓ Planned — Phase 10 |
| **Validation before calibration** | Establish uncalibrated baseline first, then measure calibration improvement — enables objective before/after comparison | ✓ Planned — Phase 9 (validation), Phase 10 (calibration) |
| **No artificial football_core restriction** | Generic, proven-reusable functionality (fixture providers, signal interfaces, calibration utilities) belongs in football_core | ✓ Planned — phases may contribute to football_core |
| **Weighted averaging over stacking** | Small-data regime; stacking deferred until 5+ tournament seasons of data exist | ✓ Planned — Phase 8 |

## Next Milestone Goals

**v2.0 — UCL Prediction Quality** (current planning):

1. **Fixture quality** — real BSD fixtures replace synthetic schedules (Phase 5)
2. **Simulation modes** — replay + live conditioning unlock validation (Phase 6)
3. **Signal diversity** — market odds, form, squad value, rest days (Phase 7)
4. **Signal blending** — weighted ensemble resolves contradictory probabilities (Phase 8)
5. **Tournament validation** — three-tier framework establishing uncalibrated baseline (Phase 9)
6. **Calibration & uncertainty** — temperature scaling + Bayesian Elo improving on baseline (Phase 10)
7. **Explainability & production** — understanding and maintainability (Phase 11)

---

*Last updated: 2026-06-29 after v2.0 planning*
