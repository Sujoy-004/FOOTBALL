# HANDOVER.md — Football Prediction Engine

Single source of truth for continuing this project in a new session.

## Project Vision

A modular football prediction engine where competition-specific modules plug into a shared core (`football_core`). Adding a new competition requires only a new module — not changes to the core.

## Repository Architecture

```
football_core/              # Shared engine — 11 modules (elo, groups, knockout, state, fetcher, math_utils, predictors/, constants, elo_sync)
competitions/
  worldcup/                 # Mature — 613 tests, live BSD API, signal blending, CatBoost, governance, CLI
  euro/                     # Stable — simulation engine, display, config, CLI. Has legacy sys.path hack.
  ucl/                      # In progress — Phase 1 complete, Phase 2 starting
    src/                    # elo_fetcher.py, groups.py, simulation.py, validation.py
    tests/                  # 59 tests (1 skipped — ClubElo live)
    data/                   # fixtures.json (synthetic), team_aliases.json, uefa_coefficients.json
.planning/                  # GSD framework — phases, decisions, roadmaps, requirements, state
```

## Core Design Principles

1. **Rule of Two** — every `football_core` abstraction must be proven by ≥2 competitions before extraction
2. **No core modifications for a single competition** — competition-specific logic stays in `competitions/<name>/`
3. **Poisson-based match simulation** — `football_core.math_utils.simulate_match()` using precomputed goal distributions
4. **Competition boundary** — zero competition logic in `football_core`; all rules, data, display, config live in the module
5. **Synthetic schedules OK for dev, official required for validation** (ADR-002)

## External Data Providers

| Provider | Role | Used By |
|----------|------|---------|
| **ClubElo** (api.clubelo.com) | Team strength ratings | UCL module — single date-based fetch, `DEFAULT_ELO=1500` fallback with `logging.warning()` |
| **BSD API** (sports.bzzoiro.com) | Live match results + odds + CatBoost predictions | World Cup (mature), UCL Phase 4 planned |
| **eloratings.net** | Elo ratings sync | World Cup, football_core.elo_sync |

## Completed Milestones

- **World Cup module** — mature competition module with 613 tests, live polling loop, signal blending (Elo/market odds/CatBoost), governance, CLI
- **Euro module** — stable simulation engine, display, CLI entry point
- **football_core extraction** — 12 shared modules extracted from WC monolith
- **Phase 1 (UCL League Table Engine)** — 3/3 plans complete, 7/7 requirements satisfied, 59 UCL tests, WC regression clean (603 pass + 1 skip ignoring pre-existing path errors)

## Current Milestone and Phase

- **Milestone:** v1 (UCL module — 4 phases)
- **Phase:** 2 of 4 — UCL Knockout Phase (not started)
- **Phase 2 requirements:** UCLK-01 through UCLK-05 (two-legged tie sim, playoff, seeded R16 bracket, top-4 protection, full knockout tree)
- **Phase 2 plans:** 4 plans (02-01: two-legged tie sim, 02-02: playoff, 02-03: R16 bracket, 02-04: full knockout tree)

## Next Immediate Objective

Plan and execute Phase 2 — simulate the UCL knockout pipeline: two-legged playoff (positions 9–24), seeded R16 bracket with exact UEFA pairings, top-4 seed protection, full tree through the final.

## Stable Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| `football_core` at repo root (flat) | Minimize friction; defer subpackages until 3rd competition |
| No pip package (keep sys.path bootstrap) | Avoid packaging overhead until interfaces stabilize across 3+ competitions |
| Rule of Two for core changes | Prevents competition-specific abstractions in shared engine |
| Single-request date-based ClubElo fetch | 36× fewer network calls than per-team requests, same snapshot guarantee |
| Post-aggregation MC pattern | Collect per-iteration results in flat lists, aggregate once after loop |
| Matchup lambdas precomputed once per MC loop | ~2× performance gain vs computing inside iteration |
| Synthetic schedules for dev, official for validation (ADR-002) | Unblocks development; gates only validation/benchmarking/public reporting |
| No H2H tiebreaker | Inapplicable to Swiss system (36 teams × 8 matches ≠ full round-robin) |

## Outstanding Technical Debt

- **WC knockout test path error** — `test_knockout.py` references `worldcup_predictor/tests/test_knockout.py` data files via a stale path; 5 tests error with `FileNotFoundError`. Unrelated to UCL work.
- **Euro sys.path hack** — `competitions/euro/__init__.py` mutates sys.path to reach WC-specific `src.groups` functions; needs refactor into `football_core`
- **HOME_ADVANTAGE_MULTIPLIER** inflates UCL goals ~5% (neutral venue UCL); marginal impact on MC
- **HTTP (not HTTPS) for ClubElo API** — MITM risk (api.clubelo.com may not support HTTPS)
- **Single-proven modules in WC** — blender, evaluation, governance, form, enrichment live in `competitions/worldcup/src/` — extract only when a 2nd competition needs them

## Deferred Work

| Item | Reason | Target |
|------|--------|--------|
| La Liga / Premier League module | Requires stable core API + UCL proven first | v2 |
| pip-installable package | Deferred until 3 competitions proven stable | v2 |
| Web UI / dashboard | Engine-only project | Out of scope |
| What-if scenario analysis (UCLD-01) | Post-validation polish | v2 |
| Path visualization (UCLD-02) | Post-validation polish | v2 |
| Strength-of-schedule reporting (UCLD-03) | Post-validation polish | v2 |

## Known Limitations

- **Synthetic fixture schedule** — current `fixtures.json` is randomly generated (greedy + BFS, seed 737), not the official UEFA draw. Valid for engine dev, must be replaced before Phase 4 validation/benchmarking.
- **ClubElo API availability** — requires internet access; transient failures fall back to `DEFAULT_ELO=1500` with warning
- **Shakhtar Donetsk unresolved** — maps to ClubElo `Shakhtar Donetsk` (not `Shakhtar`) at fallback 1500 Elo
- **Single-date Elo snapshot** — all teams rated on same day (2026-06-27); no accounting for mid-season form changes
- **No injury/suspension/transfer modeling** — too dynamic for Monte Carlo forecasting

## Testing Status

| Suite | Count | Status |
|-------|-------|--------|
| UCL unit tests | 59 pass, 1 skip | ✓ Green (1 skip = ClubElo live test, requires network) |
| World Cup tests (core) | 603 pass, 1 skip | ✓ Green |
| World Cup tests (knockout) | 5 errors | ⚠ Pre-existing: stale data path in `test_knockout.py`, unrelated to UCL |
| Euro | Manual verification | Stable; no automated test suite |
| WC regression | 613 pass, 1 skip | ✓ Baseline verified after Phase 1 |

## Current Repository Status

- **Branch:** `main`
- **Latest commit:** `3bfde39` — `docs(01-ucl-league-table-engine-03): update SUMMARY.md with plan metadata hashes`
- **Tag:** `v1.2.0-refactor-31-g3bfde39` (ancestor)
- **Working tree:** Clean (ignoring cache files and planning/doc updates)

## Read Order

1. `.planning/PROJECT.md` — project overview, constraints, key decisions
2. `.planning/REQUIREMENTS.md` — all requirements traceable to phases
3. `.planning/ROADMAP.md` — phase breakdown, plans, progress
4. **`HANDOVER.md`** — this file: concise state for session handoff
