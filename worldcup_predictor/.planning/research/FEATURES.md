# Feature Landscape: Live Football Tournament Prediction

**Domain:** CLI-based live football tournament prediction (World Cup 2026)
**Researched:** 2026-06-14
**Mode:** Ecosystem research — features analysis with official FIFA 2026 format verification

> **Post-research note:** The 48-team format features described here were implemented in Phases 7–10
> (completed v2.0). v1.0 (32-team knockout-only) was shipped before this research. All table-stakes
> features for v1.1 are now implemented. Some differentiators remain deferred.

## Part 1: Tournament Format Verification (v1.1 Critical)

### Sources Consulted
- FIFA Official — Groups & Tiebreakers: **HIGH** confidence, confirmed 7-step H2H-first order
- FIFA Regulations PDF (Annex C): **HIGH** confidence, 495-scenario table
- Wikipedia 2026 Knockout Stage: **HIGH** confidence, bracket tree + Annex C
- ESPN Format Guide: **HIGH** confidence, schedule + R32 matchups
- Bracket2026.com: **MEDIUM** confidence, third-place rules
- DEV.to Annex C Encoding: **MEDIUM** confidence, implementation patterns

### Group Advancement Rules (Verified)
- 48 teams, 12 groups (A–L), 4 teams per group
- Top 2 advance from each group = 24 auto-advancers
- 8 best third-placed teams advance (of 12)
- Total knockout: 32 teams, 104 total matches (72 group + 32 knockout)
- Points: Win=3, Draw=1, Loss=0

- **7-step group tiebreaker:** H2H Pts → H2H GD → H2H GS → Overall GD → Overall GS → Fair play → FIFA rank
- **5-step third-place ranking:** Overall Pts → Overall GD → Overall GS → Fair play → FIFA rank
- **Note:** 2026 order has H2H FIRST (reversed from pre-2026 tournaments) ✓ Implemented correctly

### The 495 Annex C Scenarios
- C(12, 8) = 495 combinations of which 8 third-place teams advance
- 8 group winners face third-place teams (A, B, D, E, G, I, K, L)
- 4 group winners face runners-up (C, F, H, J)
- Combination key: sorted, comma-separated group letters of advancing third-place teams
- Table sourced from FIFA regulations, stored as `data/annex_c.json`

### R32 Match Structure (Verified)
- 16 matches (M73–M88): 4 RU vs RU, 4 W vs RU, 8 W vs 3rd
- R16→QF→SF→TPP→FINAL fixed wiring per FIFA Article 12.7
- All confirmed correct in implementation

## Part 2: Feature Landscape (v1.0 + v1.1)

### Table Stakes — Status

| # | Feature | Phase | Status |
|---|---|---|---|
| 1 | Championship probability (%) per team | Core | ✅ Implemented |
| 2 | Round-by-round advancement probabilities | Core | ✅ Implemented (R32→FINAL) |
| 3 | Live match result ingestion | Phase 3/10 | ✅ Implemented (BSD API) |
| 4 | Elo rating updates after each match | Phase 1 | ✅ Implemented |
| 5 | Monte Carlo simulation engine | Phase 2 | ✅ Implemented (50K iterations) |
| 6 | Team rating display | Phase 5 | ✅ Implemented |
| 7 | Match-level win probability | Phase 2 | ✅ Implemented |
| 8 | Predictions update automatically | Phase 4 | ✅ Implemented |
| 9 | Error-resilient operation | Phase 3/4 | ✅ Implemented |
| 10 | Console-formatted output | Phase 5 | ✅ Implemented |
| 11 | 48-team bracket structure | Phase 7–9 | ✅ Implemented |
| 12 | Group stage tables | Phase 8/10 | ✅ Implemented |
| 13 | Annex C 495-scenario table | Phase 7 | ✅ Implemented |
| 14 | Third-place ranking | Phase 8 | ✅ Implemented |

### Differentiators — Status

| # | Feature | Status | Notes |
|---|---|---|---|
| 1 | Probability delta tracking | ✅ Implemented | ▲ green, ▼ red in output |
| 2 | Timeline/probability history | ✅ Implemented | `prediction_history.json` |
| 3 | Elo change annotations | ✅ Implemented | In match log |
| 4 | Most likely full bracket | 📋 Deferred | Post-v2.0 |
| 5 | Most likely scoreline per match | 📋 Deferred | Post-v2.0 |
| 6 | Dark horse / surprise detection | 📋 Deferred | Post-v2.0 |
| 7 | Configurable everything | ⚠️ Partial | POLL_INTERVAL env-overridable |
| 8 | Exportable JSON snapshot | ✅ Implemented | Multiple runtime JSON files |
| 9 | Backtest accuracy | ✅ Implemented | Evaluation metrics (Phase 12b) |
| 10 | What-if scenario mode | 📋 Deferred | Post-v2.0 |
| 11 | Bookmaker odds comparison | 📋 Deferred | Future |
| 12 | Compact dashboard view | 📋 Deferred | Future |

---

*Feature research for: FIFA World Cup 2026 CLI Prediction Tool*
*Researched: 2026-06-14 | Updated: 2026-06-16*
