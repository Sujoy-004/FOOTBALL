# Requirements: World Cup Dynamic Prediction

**Defined:** 2026-06-14
**Core Value:** A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.

## v1.1 Requirements

Requirements for the 48-team FIFA World Cup 2026 format migration. Each maps to roadmap phases.

### Dataset & Data Structures

- [ ] **DATA2-01**: 48 teams exist in `data/teams.json` with researched Elo ratings and group assignments
- [ ] **DATA2-02**: 12 group definitions exist in `data/groups.json` (groups A–L, 4 teams each) matching the official FIFA 2026 draw
- [ ] **DATA2-03**: 495-entry Annex C lookup table exists in `data/annex_c.json` matching FIFA's official mappings
- [ ] **DATA2-04**: `data/team_aliases.json` covers all 48 teams with BSD API name variations
- [ ] **DATA2-05**: `validate_groups()` verifies 12 groups, 4 teams each, valid team references
- [ ] **DATA2-06**: `validate_annex_c()` verifies exactly 495 keys, correct structure, sorted-letter key invariant

### Group Stage Simulation

- [ ] **GROUPS-01**: Group standings computed per FIFA rules — points, goal difference, goals for/against
- [ ] **GROUPS-02**: 7-step within-group tiebreaker chain applied correctly (H2H pts → H2H GD → H2H GS → overall GD → overall GS → fair play → FIFA ranking) with recursive narrowing for 3+ team ties
- [ ] **GROUPS-03**: 5-step cross-group third-place ranking applied correctly (points → GD → GS → fair play → FIFA ranking)
- [ ] **GROUPS-04**: 72 round-robin group matches simulated per Monte Carlo iteration using Poisson score model
- [ ] **GROUPS-05**: Advancement selection: top 2 per group (24 teams) + 8 best third-placed teams
- [ ] **GROUPS-06**: R32 matchup resolution via Annex C lookup (combination key → mapped third-place opponents)
- [ ] **GROUPS-07**: Performance benchmark: 50K full simulation iterations complete in < 15s

### Knockout Bracket & Full Simulation

- [ ] **BRKT-01**: `data/bracket.json` defines all 40 knockout matches (R32→R16→QF→SF→TPP→FINAL) using `group_position` and `annex_c_third` slot types (never hardcoded team names for R32)
- [ ] **BRKT-02**: R32 simulation resolves `group_position` slots to actual teams from group standings
- [ ] **BRKT-03**: R32 simulation resolves `annex_c_third` slots via Annex C lookup table
- [ ] **BRKT-04**: R16–FINAL simulation uses existing `source_matches` pattern (unchanged from v1.0)
- [ ] **BRKT-05**: Third-place match simulated from SF losers
- [ ] **BRKT-06**: `run_full_simulation()` runs complete 48-team pipeline (group stage → Annex C → knockout)
- [ ] **BRKT-07**: Bracket validation checks round counts, slot types, R16 wiring per FIFA Article 12.7
- [ ] **BRKT-08**: All existing v1.0 knockout tests continue to pass

### Integration & Live Data

- [ ] **INTG-01**: BSD API polling detects and ingests group match results (matched against `groups.json`)
- [ ] **INTG-02**: Group match results stored in separate `played_groups.json` (no knockout bracket contamination)
- [ ] **INTG-03**: Console output displays 12 group standings tables (position, points, GD, GS)
- [ ] **INTG-04**: Console output shows third-place bubble indicator (8th vs 9th ranked teams)
- [ ] **INTG-05**: Console header updated for 48-team format
- [ ] **INTG-06**: All test fixtures updated for 48-team bracket with group-position and Annex C slots
- [ ] **INTG-07**: E2E test with mock data through full 104-match pipeline
- [ ] **INTG-08**: Live BSD smoke test with `--once` flag returning valid 48-team predictions
- [ ] **INTG-09**: Pre-existing `test_main_loop_runs_iterations` failure fixed
- [ ] **INTG-10**: All 7 SOTs batch-updated (PRD, TRD, MVP, Appflow, Backend Schema, UI/UX, Implementation Plan)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Analytics & Advanced

- **V2-01**: Most-likely full bracket visualization
- **V2-02**: Dark horse detection (gap between Elo and probability)
- **V2-03**: Historical probability log (track odds over time)
- **V2-04**: Simple web dashboard (Flask + Chart.js)
- **V2-05**: What-if mode (simulate hypothetical match results)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Player-level modeling | Massive data pipeline for marginal gain; team-level only |
| Multi-tournament / historical archive | Only current World Cup |
| Mobile app | CLI is the product |
| Real-time WebSocket / live ticker | Overengineering for polling-based tool |
| Betting advice / "value bet" alerts | Legal gray area |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA2-01 | Phase 7 | Pending |
| DATA2-02 | Phase 7 | Pending |
| DATA2-03 | Phase 7 | Pending |
| DATA2-04 | Phase 7 | Pending |
| DATA2-05 | Phase 7 | Pending |
| DATA2-06 | Phase 7 | Pending |
| GROUPS-01 | Phase 8 | Pending |
| GROUPS-02 | Phase 8 | Pending |
| GROUPS-03 | Phase 8 | Pending |
| GROUPS-04 | Phase 8 | Pending |
| GROUPS-05 | Phase 8 | Pending |
| GROUPS-06 | Phase 8 | Pending |
| GROUPS-07 | Phase 8 | Pending |
| BRKT-01 | Phase 9 | Pending |
| BRKT-02 | Phase 9 | Pending |
| BRKT-03 | Phase 9 | Pending |
| BRKT-04 | Phase 9 | Pending |
| BRKT-05 | Phase 9 | Pending |
| BRKT-06 | Phase 9 | Pending |
| BRKT-07 | Phase 9 | Pending |
| BRKT-08 | Phase 9 | Pending |
| INTG-01 | Phase 10 | Pending |
| INTG-02 | Phase 10 | Pending |
| INTG-03 | Phase 10 | Pending |
| INTG-04 | Phase 10 | Pending |
| INTG-05 | Phase 10 | Pending |
| INTG-06 | Phase 10 | Pending |
| INTG-07 | Phase 10 | Pending |
| INTG-08 | Phase 10 | Pending |
| INTG-09 | Phase 10 | Pending |
| INTG-10 | Phase 10 | Pending |

**Coverage:**
- v1.1 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0 ✅

---

*Requirements defined: 2026-06-14*
*Last updated: 2026-06-14 after initial definition*
