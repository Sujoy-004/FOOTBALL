# World Cup Dynamic Prediction

## What This Is

A self-updating tournament predictor for football fans and B.Tech students. It polls the BSD live match API, updates team Elo ratings after every real result, re-runs thousands of Monte Carlo simulations, and prints updated championship probabilities to the console — all in real time. Now targeting the full 48-team FIFA World Cup 2026 format with group stage, Annex C R32 routing, and 104-match tournament tree.

## Core Value

A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.

## Current State (v1.1)

**Shipped:** 2026-06-14 — v1.1 complete

The v1.0 MVP is complete. The tool can:

1. **Load state** from JSON files (32 teams, 23 bracket matches)
2. **Compute Elo ratings** using standard Elo formula with configurable K-factor
3. **Simulate** the remaining knockout tournament 50,000+ times in ~1.3s
4. **Fetch live results** from BSD API with automatic retry and cached fallback
5. **Poll continuously** every 60 seconds, auto-detecting new matches and re-simulating
6. **Display** color-coded probability tables with delta tracking (▲/▼)
7. **Run one-off** with `--once`, control color with `--no-color`, reproduce with `--seed`

**Test coverage:** 212 passing tests, 1 skipped across 14 test modules
**Codebase:** ~3,200 LOC Python

## Current Milestone: v1.1 World Cup 2026 Support — Complete 2026-06-14

**Goal:** Migrate from 32-team knockout-only format to the full 48-team FIFA World Cup 2026 with group stage, Annex C R32 routing, and verified BSD live-data integration.

**Shipped features:**
- ✅ 48-team dataset with researched Elo ratings, group assignments, and BSD aliases
- ✅ 12 group definitions (A–L) with validated structure
- ✅ 495-entry Annex C lookup table for R32 third-place routing
- ✅ Group stage simulation engine (round-robin, 7-step tiebreaker, 5-step third-place ranking, Poisson scoring)
- ✅ Full knockout bracket (R32 → R16 → QF → SF → TPP → FINAL) with Annex C resolution
- ✅ BSD live-data ingestion for group stage matches
- ✅ Console display of group standings + third-place bubble indicator
- ✅ All test fixtures updated; E2E test with live BSD smoke test scaffolding
- ✅ All 7 SOTs batch-updated for 48-team format

**Test suite:** 212 passed, 1 skipped (live smoke test requires BSD_API_KEY), 0 failures

## Requirements

### Validated (v1.0)

- ✓ **DATA-01**: Fetch live match results from Football-Data.org API — v1.0
- ✓ **DATA-02**: Persist played matches and Elo ratings across restarts via JSON — v1.0
- ✓ **DATA-03**: Graceful API failure handling with retry and cached fallback — v1.0
- ✓ **ELO-01**: Update Elo ratings after each match using standard formula — v1.0
- ✓ **SIM-01**: Monte Carlo simulation of remaining bracket (50K+ iterations) — v1.0
- ✓ **UI-01**: Championship probabilities as formatted table with timestamps — v1.0
- ✓ **UI-02**: Probability deltas (▲ increase, ▼ decrease) — v1.0
- ✓ **UI-03**: Colored console output with plain-text fallback — v1.0
- ✓ **LOOP-01**: Continuous polling every N seconds with hourly auto-resim — v1.0
- ✓ **VAL-01**: Bracket structure validation on startup — v1.0
- ✓ **SHUT-01**: Save state and print final probabilities on Ctrl+C — v1.0
- ✓ **CLI-01**: CLI flags: --once, --no-color, --help, --seed — v1.0

### Active (v1.1)

- [x] **DATA2-01**: 48 teams with Elo ratings and group assignments
- [x] **DATA2-02**: 12 group definitions (groups A–L, 4 teams each)
- [x] **DATA2-03**: 495-entry Annex C lookup table
- [x] **DATA2-04**: BSD team aliases for all 48 teams
- [x] **DATA2-05**: validate_groups() — structure validation
- [x] **DATA2-06**: validate_annex_c() — 495-entry validation
- [x] **GROUPS-01**: Group standings computation
- [x] **GROUPS-02**: 7-step within-group tiebreaker chain
- [x] **GROUPS-03**: 5-step cross-group third-place ranking
- [x] **GROUPS-04**: 72 round-robin group match simulation
- [x] **GROUPS-05**: Advancement selection (24 auto + 8 best third)
- [x] **GROUPS-06**: Annex C R32 matchup resolution
- [x] **GROUPS-07**: Performance benchmark (< 15s for 50K) — 12.66s [PASS]
- [x] **BRKT-01**: 40-match bracket.json with slot types
- [x] **BRKT-02**: R32 group_position slot resolution
- [x] **BRKT-03**: R32 annex_c_third slot resolution
- [x] **BRKT-04**: R16–FINAL source_matches pattern
- [x] **BRKT-05**: Third-place match simulation
- [x] **BRKT-06**: run_full_simulation() 48-team pipeline
- [x] **BRKT-07**: Bracket validation (10+ sub-checks)
- [x] **BRKT-08**: v1.0 knockout tests still pass
- [x] **INTG-01**: BSD API ingests group match results
- [x] **INTG-02**: played_groups.json persistence
- [x] **INTG-03**: Group standings console display
- [x] **INTG-04**: Third-place bubble indicator
- [x] **INTG-05**: Console header for 48-team format
- [x] **INTG-06**: All test fixtures updated
- [x] **INTG-07**: E2E mock test through full pipeline
- [x] **INTG-08**: Live BSD smoke test with --once
- [x] **INTG-09**: test_main_loop fix
- [x] **INTG-10**: All 7 SOTs batch-updated

### Future (v2.0+)

- [ ] **V2-01**: Most-likely full bracket visualization
- [ ] **V2-02**: Dark horse detection (gap between Elo and probability)
- [ ] **V2-03**: Historical probability log (track odds over time)
- [ ] **V2-04**: Simple web dashboard (Flask + Chart.js)
- [ ] **V2-05**: What-if mode (simulate hypothetical match results)
- [ ] **V2-06**: Backtesting against historical tournaments
- [ ] **V2-07**: NumPy-accelerated simulation for larger iterations

### Out of Scope

| Feature | Reason |
|---------|--------|
| User accounts or login | Not needed for single-user CLI tool |
| Web dashboard | Console-only; v2.0 candidate |
| ML models (XGBoost, neural nets) | Beyond scope; Elo is sufficient |
| Multi-tournament support | Only current World Cup |
| Historical data analysis | Beyond current tournament scope |
| Mobile notifications | Post-MVP enhancement |
| Betting odds comparison | Post-MVP enhancement |
| Player-level modeling | Massive data pipeline for marginal gain |
| NumPy acceleration | Not needed at current simulation scale |

## Context

- Python 3.10+ CLI application, no graphical interface
- Uses BSD sports API (`sports.bzzoiro.com`) with token authentication
- All state persisted as JSON files (teams.json, groups.json, bracket.json, annex_c.json, played.json, played_groups.json)
- Full 48-team tournament: 12 groups (A–L) → R32 → R16 → QF → SF → TPP → FINAL (104 matches)
- Standard Elo rating system with configurable K-factor (default 60)
- Group stage uses Poisson score model for goal difference (required for tiebreakers); knockout uses binary Elo win/loss
- R32 third-place routing via 495-entry Annex C lookup table
- Codebase: ~3,200 LOC Python across 9 modules + 14 test files
- Full test suite: 212 passed, 1 skipped (live BSD smoke test requires BSD_API_KEY)

## Constraints

- **Language**: Python 3.10+ — must run on Windows, macOS, Linux
- **Dependencies**: Minimal (requests library for HTTP, random for simulation, python-dotenv for .env)
- **Storage**: JSON files only — no database
- **API**: BSD sports API — token auth, 200-result pagination
- **UI**: Console-only — no web framework, no frontend
- **Scope**: 48-team FIFA World Cup 2026 format with full group stage and knockout
- **Persistence**: State must survive script restarts via JSON files
- **Performance**: 50K iterations must complete within 60s poll interval

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python 3.10+ | Fast prototyping, rich ecosystem, cross-platform | ✓ Good |
| BSD sports API | Free tier, reliable match data, well-documented | ✓ Good |
| Elo rating system | Simple, transparent, well-understood formula | ✓ Good |
| Monte Carlo simulation | Straightforward probability estimation | ✓ Good |
| JSON file persistence | No database setup, human-readable, easy to debug | ✓ Good |
| Console-only output | Simpler than web UI, immediate feedback | ✓ Good |
| Pure stdlib ANSI | No colorama dependency, works cross-platform | ✓ Good |
| `--once` skips state save | Single-cycle mode doesn't change state, no save needed | ✓ Good |
| `--seed` on every sim | Reproducibility without global random state pollution | ✓ Good |
| Group-position slot types | R32 teams unresolved until runtime; avoids hardcoding team names | ✓ Good |
| Annex C lookup table | 495-entry JSON file, validated at startup | ✓ Good |
| Separate group/knockout persistence | Played_groups.json prevents bracket contamination | ✓ Good |
| Poisson scoring for group matches | Required for goal-difference tiebreakers | ⚠️ Revisit (needs calibration) |

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

*Last updated: 2026-06-14 — v1.1 milestone complete*
