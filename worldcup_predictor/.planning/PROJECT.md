# World Cup Dynamic Prediction

## What This Is

- Self-updating tournament predictor for football fans and B.Tech students
- Polls BSD live match API → updates Elo ratings after every result → re-runs Monte Carlo simulations → prints championship probabilities to console
- Targets the full 48-team FIFA World Cup 2026 format: 12 groups, Annex C R32 routing, 104-match tournament tree

```
         ┌──────────────┐     ┌────────────┐     ┌─────────────┐
 BSD API ─►  fetcher.py  ───►  state.py    ───► simulation.py  ─┐
         │  (live data) │     │  (JSON)     │     │  (Monte Carlo) │
         └──────────────┘     └──────┬──────┘     └───────────────┘
                                     │                            │
         ┌──────────────┐           │                            │
 eloratings.net ─► elo_sync.py       │                            │
         │  (auto-sync)  │           │                            │
         └──────────────┘           │                            │
                                     ▼                            ▼
                              evaluation.py ─────► prediction_history.json
                              (Brier, log loss)
                                                                    │
                                                                    ▼
                                                            output.py ──► Console
                                                            (colored tables,
                                                             deltas, standings)
```

## Core Value

A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.

## Current State (v2.0 — Active)

| Milestone | Status | Shipped |
|-----------|--------|---------|
| v1.0 MVP | ✅ Complete | 2026-06-14 |
| v1.1 World Cup 2026 Support | ✅ Complete | 2026-06-14 |
| v2.0 Prediction Engine Modernization | 🚧 Phases 11–15 complete, Phases 16–20 planned | — |

**v1.0 core capabilities:**
1. Load state from JSON (32 teams, 23 bracket matches)
2. Compute Elo ratings (standard formula, configurable K-factor)
3. Simulate remaining knockout 50,000+ times in ~1.3s
4. Fetch live results from BSD API (automatic retry + cached fallback)
5. Poll continuously every 60s, auto-detect new matches, re-simulate
6. Display color-coded probability tables with delta tracking (▲/▼)
7. Run one-off (`--once`), control color (`--no-color`), reproduce (`--seed`)

**v1.1 48-team expansion (Phases 7–10):**
- 48-team dataset with researched Elo, group assignments, BSD aliases
- 12 group definitions (A–L) + 495-entry Annex C lookup table
- Group stage engine (round-robin, 7-step tiebreaker, 5-step third-place ranking, Poisson scoring)
- Full knockout bracket (R32 → R16 → QF → SF → TPP → FINAL)
- BSD live-data ingestion for group matches
- Console display: group standings + third-place bubble indicator

**v2.0 completed (Phases 11–15):**
- **Phase 11:** Elo auto-sync from eloratings.net (48 teams, graduated correction, drift detection)
- **Phase 12:** Draw pipeline fixed, K-multiplier implemented, historical backfill applied
- **Phase 12b:** Evaluation framework — Brier score, log loss, calibration curves, prediction history
- **Phase 13:** Market odds + CatBoost signal ingestion with TTL caching and graceful degradation
- **Phase 14:** Signal blending — Platt calibration, Brier-weighted ensemble, Poisson base rate
- **Phase 14a:** Permanent prediction ledger for pre-match signal archival
- **Phase 15:** Context signals — team form (Elo residuals) and lineup strength (market value proxy)

**Test coverage:** 477+ passing tests, 1 skipped (live smoke needs BSD_API_KEY) across **16 test modules**
**Codebase:** ~4,200 LOC Python across **14 source modules**

## Canonical Docs

| Doc | Path | Covers |
|-----|------|--------|
| README | [README.md](../README.md) | Install, quick start, usage examples, license |
| Architecture | [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) | System overview, component diagram, data flow, key abstractions |
| Getting Started | [docs/GETTING-STARTED.md](../docs/GETTING-STARTED.md) | Prerequisites, install steps, first run, common issues |
| Development | [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md) | Build commands, code style, branch conventions, PR process |
| Testing | [docs/TESTING.md](../docs/TESTING.md) | Test framework, running tests, writing tests, coverage, CI |
| Configuration | [docs/CONFIGURATION.md](../docs/CONFIGURATION.md) | Environment variables, config files, defaults, per-env overrides |

## Current Milestone: v2.0 Prediction Engine Modernization

**Goal:** Fix the Elo foundation (63% wrong ratings, missing draws, missing K-multiplier), add multi-signal blending (market odds + CatBoost), establish model governance, and expand BSD API coverage to 85%. See [`MODERNIZATION-PROPOSAL.md`](../MODERNIZATION-PROPOSAL.md) for full architecture.

**Phase progress:**

```
 v1.0 MVP     v1.1 48-team          v2.0 Modernization
 ─────────────────────────────────────────────────────────►
 [████████]  [████████████]  [███████████████████░░░░░░░░░]
   Phases 1-6    Phases 7-10  11 12 12b 13 14 15 16 17 18 19 20
                                ▲       ▲
                          Complete    Planned
```

| Phase | Status | Plans | Key Outputs |
|-------|--------|-------|-------------|
| ✅ 11. Data Integrity & Elo Foundation | Complete | 3/3 | elo_sync.py, auto-sync from eloratings.net, drift detection |
| ✅ 12. Draw Handling & Elo Math | Complete | 3/3 | K-multiplier, draw pipeline fix, historical backfill |
| ✅ 12b. Evaluation Infrastructure | Complete | 1/1 | evaluation.py, Brier/log-loss, prediction history |
| ✅ 13. Signal Ingestion | Complete | 3/3 | Market odds + CatBoost API integration |
| ✅ 14. Signal Blending | Complete | 2/2 | Platt scaling, Brier-weighted ensemble |
| ✅ 14a. Prediction Retention Fix | Complete | 1/1 | Permanent prediction ledger |
| ✅ 15. Context Signals | Complete | 3/3 | Team form, lineup strength |
| 🔲 16. Model Governance | In Progress | 1/3 | Version tracking complete, drift + backtesting pending |
| 🔲 17. Enriched Match Context | Defined | — | Live event fields, coach/venue/ref/weather |
| 🔲 18. xG & AI Prediction Signals | Defined | — | xG predictions, AI preview ingestion |
| 🔲 19. Multi-League Framework | Defined | — | All 65 BSD leagues, --league flag |
| 🔲 20. Output Enhancement & Coverage Seal | Defined | — | Signal breakdown, CI, probability log, 85% API coverage |

## Requirements

### Validated (v1.0 & v1.1)

- ✓ **DATA-01**: Fetch live match results from Football-Data.org API
- ✓ **DATA-02**: Persist played matches and Elo ratings via JSON
- ✓ **DATA-03**: Graceful API failure handling (retry + cached fallback)
- ✓ **ELO-01**: Update Elo after each match using standard formula
- ✓ **SIM-01**: Monte Carlo simulation of remaining bracket (50K+ iterations)
- ✓ **UI-01/02/03**: Championship probabilities table, deltas (▲/▼), colored output with fallback
- ✓ **LOOP-01**: Continuous polling every N seconds + hourly auto-resim
- ✓ **VAL-01**: Bracket structure validation on startup
- ✓ **SHUT-01**: Save state + print final probabilities on Ctrl+C
- ✓ **CLI-01**: CLI flags —once, --no-color, --help, --seed

### Completed (v2.0 — Phases 11–12b)

- ✓ **V2-01**: All 48 Elo ratings match eloratings.net within 5 points
- ✓ **V2-02**: Elo auto-sync from eloratings.net on configurable interval
- ✓ **V2-03**: Draw results ingested and Elo-updated correctly
- ✓ **V2-04**: Goal-difference K-multiplier per eloratings.net step-function
- ✓ **V2-18**: Prediction evaluation framework (Brier, log loss, calibration)
- ✓ **V2-19**: Match-level prediction history stored persistently

### Active (v2.0 — Phases 13+)

- [x] **V2-05**: Market odds fetched and converted to vig-removed probabilities
- [x] **V2-06**: CatBoost predictions fetched for every match
- [x] **V2-07**: Signal calibration layer (Platt scaling) per signal
- [x] **V2-08**: Dynamic signal blender (Brier-weighted) into simulation
- [x] **V2-09**: Calibrated Poisson base rate from historical data
- [x] **V2-10**: Team form signal (last 5 matches)
- [x] **V2-11**: Lineup strength factor (market value proxy)
- [ ] **V2-12**: Model/data/run version tracking
- [ ] **V2-13**: Per-signal Brier with drift detection
- [ ] **V2-14**: Backtesting framework against historical World Cups
- [ ] **V2-21**: Live match event fields (goals, cards, subs, possession, shots, corners, fouls) ingested from BSD
- [ ] **V2-22**: Coach, venue, referee, and weather data ingested and accessible
- [ ] **V2-23**: BSD xG predictions ingested as independent prediction signal
- [ ] **V2-24**: BSD AI preview / pre-match analysis ingested and displayed
- [ ] **V2-25**: League selection via CLI flag (--league) and config, supporting all 65 BSD leagues
- [ ] **V2-26**: Multi-league data isolation (separate state files per league)
- [ ] **V2-27**: Per-match signal breakdown display (blended + per-signal) in console
- [ ] **V2-28**: Confidence intervals (Clopper-Pearson) alongside probabilities
- [ ] **V2-29**: Historical probability log with trend tracking
- [ ] **V2-30**: 85% BSD API field coverage (monitored and reported)

### Future (v2.x+)

| Requirement | Priority |
|-------------|----------|
| Most-likely full bracket visualization | Low |
| NumPy-accelerated simulation | Low |
| Simple web dashboard (Flask + Chart.js) | Post-MVP |
| What-if mode (hypothetical match results) | Low |
| Backtesting against historical tournaments | Post-MVP |

### Out of Scope

| Feature | Reason |
|---------|--------|
| User accounts or login | Not needed for single-user CLI tool |
| Web dashboard | Console-only; v2.x candidate |
| ML models (XGBoost, neural nets) | Beyond scope; Elo + CatBoost sufficient |
| Multi-tournament support | Only current World Cup |
| Player-level modeling | Massive data pipeline for marginal gain |
| Betting odds comparison | Post-MVP enhancement |
| Mobile notifications | Post-MVP enhancement |

## Context

- **Runtime:** Python 3.10+ CLI, no graphical interface — runs on Windows/macOS/Linux
- **Data source:** BSD sports API (`sports.bzzoiro.com`) with token authentication
- **Persistence:** All state as JSON files (teams.json, groups.json, bracket.json, annex_c.json, played.json, played_groups.json, elo_update_log.json, prediction_history.json)
- **Tournament:** 48 teams, 12 groups (A–L) → R32 → R16 → QF → SF → TPP → FINAL = 104 matches
- **Elo system:** Standard formula, K=60 default, K-multiplier per goal difference (eloratings.net formula)
- **Group simulation:** Poisson scoring model (goal difference needed for tiebreakers)
- **Knockout simulation:** Binary Elo win/loss (including PK resolution for draws)
- **R32 routing:** 495-entry Annex C lookup table
- **Codebase:** ~4,200 LOC Python, 14 source modules, 16 test modules
- **Test suite:** 475 passing, 1 skipped (live smoke), 2 pre-existing regressions

## Constraints

- **Language:** Python 3.10+ — must run on Windows, macOS, Linux
- **Dependencies:** Minimal (requests, random, python-dotenv)
- **Storage:** JSON files only — no database
- **API:** BSD sports API — token auth, 200-result pagination
- **UI:** Console-only — no web framework, no frontend
- **Scope:** 48-team FIFA World Cup 2026 format
- **Persistence:** State must survive script restarts via JSON
- **Performance:** 50K iterations within 60s poll interval (12.66s current)

## Key Decisions

| Decision | Rationale | Outcome | Phase |
|----------|-----------|---------|-------|
| Python 3.10+ | Fast prototyping, rich ecosystem, cross-platform | ✓ | 1 |
| BSD sports API | Free tier, reliable, well-documented | ✓ | 1 |
| Elo rating system | Simple, transparent, well-understood | ✓ | 1 |
| Monte Carlo simulation | Straightforward probability estimation | ✓ | 1 |
| JSON file persistence | No DB setup, human-readable, easy to debug | ✓ | 1 |
| Console-only output | Simpler than web UI, immediate feedback | ✓ | 1 |
| Pure stdlib ANSI | No colorama dependency, cross-platform | ✓ | 1 |
| `--once` skips state save | Single-cycle mode doesn't change state | ✓ | 1 |
| `--seed` on every sim | Reproducibility, no global random pollution | ✓ | 1 |
| Group-position slot types | R32 teams unresolved until runtime | ✓ | 9 |
| Annex C lookup table | 495-entry JSON, validated at startup | ✓ | 8 |
| Separate group/knockout persistence | Prevents bracket contamination | ✓ | 10 |
| Poisson scoring for groups | Required for goal-difference tiebreakers | ⚠️ Revisit | 8 |
| Elo auto-sync from eloratings.net | Self-healing ratings, never manual | ✓ | 11 |
| Startup + daily sync interval | Never per-poll (unnecessary traffic) | ✓ | 11 |
| Graduated correction thresholds | <10pt ignore, 10-30 blend, >30 flag | ✓ | 11 |
| K-multiplier G=1/1.5/(11+N)/8 | Per eloratings.net step-function | ✓ | 12 |
| Draw : no PK winner split | Group = true draw, knockout = PK resolution | ✓ | 12 |
| Evaluation as separate module | Reusable by all subsequent phases | ✓ | 12b |
| Append-only prediction history | Never overwritten, audit trail | ✓ | 12b |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---

*Last updated: 2026-06-18 — v2.0: Phases 11–15 complete, Phase 16 planned, Phases 17–20 defined*
