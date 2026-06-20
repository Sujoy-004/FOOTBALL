# Requirements: World Cup Dynamic Prediction

**Defined:** 2026-06-14
**Core Value:** A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.

## v1.1 Requirements

Requirements for the 48-team FIFA World Cup 2026 format migration. Each maps to roadmap phases.

### Dataset & Data Structures

- [x] **DATA2-01**: 48 teams exist in `data/teams.json` with researched Elo ratings and group assignments
- [x] **DATA2-02**: 12 group definitions exist in `data/groups.json` (groups A–L, 4 teams each) matching the official FIFA 2026 draw
- [x] **DATA2-03**: 495-entry Annex C lookup table exists in `data/annex_c.json` matching FIFA's official mappings
- [x] **DATA2-04**: `data/team_aliases.json` covers all 48 teams with BSD API name variations
- [x] **DATA2-05**: `validate_groups()` verifies 12 groups, 4 teams each, valid team references
- [x] **DATA2-06**: `validate_annex_c()` verifies exactly 495 keys, correct structure, sorted-letter key invariant

### Group Stage Simulation

- [x] **GROUPS-01**: Group standings computed per FIFA rules — points, goal difference, goals for/against
- [x] **GROUPS-02**: 7-step within-group tiebreaker chain applied correctly (H2H pts → H2H GD → H2H GS → overall GD → overall GS → fair play → FIFA ranking) with recursive narrowing for 3+ team ties
- [x] **GROUPS-03**: 5-step cross-group third-place ranking applied correctly (points → GD → GS → fair play → FIFA ranking)
- [x] **GROUPS-04**: 72 round-robin group matches simulated per Monte Carlo iteration using Poisson score model
- [x] **GROUPS-05**: Advancement selection: top 2 per group (24 teams) + 8 best third-placed teams
- [x] **GROUPS-06**: R32 matchup resolution via Annex C lookup (combination key → mapped third-place opponents)
- [x] **GROUPS-07**: Performance benchmark: 50K full simulation iterations complete in < 15s (12.66s)

### Knockout Bracket & Full Simulation

- [x] **BRKT-01**: `data/bracket.json` defines all 40 knockout matches (R32→R16→QF→SF→TPP→FINAL) using `group_position` and `annex_c_third` slot types (never hardcoded team names for R32)
- [x] **BRKT-02**: R32 simulation resolves `group_position` slots to actual teams from group standings
- [x] **BRKT-03**: R32 simulation resolves `annex_c_third` slots via Annex C lookup table
- [x] **BRKT-04**: R16–FINAL simulation uses existing `source_matches` pattern (unchanged from v1.0)
- [x] **BRKT-05**: Third-place match simulated from SF losers
- [x] **BRKT-06**: `run_full_simulation()` runs complete 48-team pipeline (group stage → Annex C → knockout)
- [x] **BRKT-07**: Bracket validation checks round counts, slot types, R16 wiring per FIFA Article 12.7
- [x] **BRKT-08**: All existing v1.0 knockout tests continue to pass

### Integration & Live Data

- [x] **INTG-01**: BSD API polling detects and ingests group match results (matched against `groups.json`)
- [x] **INTG-02**: Group match results stored in separate `played_groups.json` (no knockout bracket contamination)
- [x] **INTG-03**: Console output displays 12 group standings tables (position, points, GD, GS)
- [x] **INTG-04**: Console output shows third-place bubble indicator (8th vs 9th ranked teams)
- [x] **INTG-05**: Console header updated for 48-team format
- [x] **INTG-06**: All test fixtures updated for 48-team bracket with group-position and Annex C slots
- [x] **INTG-07**: E2E test with mock data through full 104-match pipeline
- [x] **INTG-08**: Live BSD smoke test with `--once` flag returning valid 48-team predictions
- [x] **INTG-09**: Pre-existing `test_main_loop_runs_iterations` failure fixed
- [x] **INTG-10**: All 7 SOTs batch-updated (PRD, TRD, MVP, Appflow, Backend Schema, UI/UX, Implementation Plan)

> **Phase 10 complete: 2026-06-14**

## v2 Requirements

### Prediction Engine Modernization (Phases 11+)

| ID | Requirement | Phase |
|----|------------|-------|
| V2-01 | All 48 Elo ratings match eloratings.net within 5 points | 11 ✅ |
| V2-02 | Elo values auto-sync from eloratings.net every N minutes | 11 ✅ |
| V2-03 | Draw results are ingested and Elo-updated correctly | 12 |
| V2-04 | Goal-difference K multiplier implemented per eloratings.net formula | 12 |
| V2-05 | Market odds fetched and converted to vig-removed probabilities | 13 ✅ |
| V2-06 | CatBoost predictions fetched for every match | 13 ✅ |
| V2-07 | Signal calibration layer (Platt scaling) implemented per signal | 14 ✅ |
| V2-08 | Dynamic signal blender (Brier-weighted) integrated into simulation | 14 ✅ |
| V2-09 | Calibrated Poisson base rate from historical World Cup data | 14 ✅ |
| V2-20 | Pre-match predictions retained permanently for historical Brier computation | 14a ✅ |
| V2-10 | Team form signal (last 5 matches) computed and integrated | 15 ✅ |
| V2-11 | Lineup strength factor (market value proxy) computed | 15 ✅ |
| V2-12 | Model version, data version, and run version tracked | 16 ✅ |
| V2-13 | Per-signal Brier scoring with drift detection | 16 ✅ |
| V2-14 | Backtesting framework against historical World Cups | 16 ✅ |
| V2-15 | Probability delta since last run displayed with signal breakdown | 20 |
| V2-16 | Historical probability log across tournament duration | 20 |
| V2-17 | Dark horse detection (highest Δ between average probability and champion probability) | 20 |
| V2-18 | Baseline prediction evaluation framework (Brier, log loss, calibration) computed per match | 12b |
| V2-19 | Match-level prediction history stored persistently for analysis | 12b |
| V2-21 | Live match event fields (goals, cards, subs, possession, shots, corners, fouls) ingested from BSD | 17 |
| V2-22 | Coach, venue, referee, and weather data ingested and accessible | 17 |
| V2-23 | BSD xG predictions (`expected_home_goals`, `expected_away_goals`) ingested as optional Poisson simulation lambda overrides | 18 |
| V2-24 | BSD AI preview / pre-match analysis ingested and displayed | 18 |
| V2-25 | League selection via CLI flag (--league) and config (single-league, World Cup scope) | 19 |
| V2-26 | Per-league state isolation (World Cup scope: league 27 only) | 19 |
| V2-27 | Per-match signal breakdown display (blended + per-signal) in console | 20 |
| V2-28 | Confidence intervals (Clopper-Pearson) alongside probabilities | 20 |
| V2-29 | Historical probability log with trend tracking | 20 |
| V2-30 | ≥60% BSD API meaningful field coverage (counts Prediction + Display + Operational fields only; excludes No-Value noise) with automated auditor script | 20 |

## Out of Scope

| Feature | Reason |
|---------|--------|
| Player-level modeling | Massive data pipeline for marginal gain; team-level only |
| Multi-tournament / historical archive | Only current World Cup |
| Non-World-Cup BSD leagues (64 others) | Project is World Cup only |
| Mobile app | CLI is the product |
| Real-time WebSocket / live ticker | Overengineering for polling-based tool |
| Betting advice / "value bet" alerts | Legal gray area |

## Traceability

### v1.1

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA2-01 | 7 | Complete |
| DATA2-02 | 7 | Complete |
| DATA2-03 | 7 | Complete |
| DATA2-04 | 7 | Complete |
| DATA2-05 | 7 | Complete |
| DATA2-06 | 7 | Complete |
| GROUPS-01 | 8 | Complete |
| GROUPS-02 | 8 | Complete |
| GROUPS-03 | 8 | Complete |
| GROUPS-04 | 8 | Complete |
| GROUPS-05 | 8 | Complete |
| GROUPS-06 | 8 | Complete |
| GROUPS-07 | 8 | Complete |
| BRKT-01 | 9 | Complete |
| BRKT-02 | 9 | Complete |
| BRKT-03 | 9 | Complete |
| BRKT-04 | 9 | Complete |
| BRKT-05 | 9 | Complete |
| BRKT-06 | 9 | Complete |
| BRKT-07 | 9 | Complete |
| BRKT-08 | 9 | Complete |
| INTG-01 | 10 | Complete |
| INTG-02 | 10 | Complete |
| INTG-03 | 10 | Complete |
| INTG-04 | 10 | Complete |
| INTG-05 | 10 | Complete |
| INTG-06 | 10 | Complete |
| INTG-07 | 10 | Complete |
| INTG-08 | 10 | Complete |
| INTG-09 | 10 | Complete |
| INTG-10 | 10 | Complete |

### v2.0

| Requirement | Phase | Status |
|-------------|-------|--------|
| V2-01 | 11 | Complete |
| V2-02 | 11 | Complete |
| V2-03 | 12 | Complete |
| V2-04 | 12 | Complete |
| V2-05 | 13 | Complete |
| V2-06 | 13 | Complete |
| V2-07 | 14 | Complete |
| V2-08 | 14 | Complete |
| V2-09 | 14 | Complete |
| V2-20 | 14a | Complete |
| V2-10 | 15 | Complete |
| V2-11 | 15 | Complete |
| V2-12 | 16 | Complete |
| V2-13 | 16 | Complete |
| V2-14 | 16 | Complete |
| V2-15 | 20 | Planned |
| V2-16 | 20 | Planned |
| V2-17 | 20 | Planned |
| V2-18 | 12b | Complete |
| V2-19 | 12b | Complete |
| V2-21 | 17 | Defined |
| V2-22 | 17 | Defined |
| V2-23 | 18 | Defined |
| V2-24 | 18 | Defined |
| V2-25 | 19 | Defined |
| V2-26 | 19 | Defined |
| V2-27 | 20 | Defined |
| V2-28 | 20 | Defined |
| V2-29 | 20 | Defined |
| V2-30 | 20 | Defined |

**Coverage:**
- v1.1 requirements: 31 total, 31 mapped ✅
- v2.0 requirements: 30 total, 30 mapped ✅
- Unmapped (any): 0 ✅

---

*Requirements defined: 2026-06-14*
*Last updated: 2026-06-21 — V2-30 re-scoped to meaningful-field coverage with value-based classification*
