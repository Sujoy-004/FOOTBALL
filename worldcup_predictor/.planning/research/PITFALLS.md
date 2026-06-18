# Pitfalls Research

**Domain:** CLI tournament predictor — adding group stage + R32 knockout to existing Monte Carlo simulator
**Researched:** 2026-06-14
**Confidence:** MEDIUM (code-verified for existing project; FIFA rules verified via official sources)

> **Post-research note:** All 8 critical pitfalls were addressed during implementation (Phases 7–10).
> This document remains as a historical reference for the risks identified during planning.

## Critical Pitfalls — Status

### Pitfall 1: Tiebreaker Step Reversal — H2H vs. Overall GD
- **Risk:** Using pre-2026 tiebreaker order (Overall GD first) instead of FIFA 2026 order (H2H first)
- **5 of 7 steps wrong** if pre-2026 code is copied
- **Multi-team tie edge case:** Must restart from step 1 after each separation
- **Status:** ✅ **Addressed in Phase 8.** `compute_standings()` uses correct 7-step order with recursive narrowing. Unit tests cover 2/3/4-team ties.

### Pitfall 2: Annex C Lookup Table — Missing, Wrong, or Silent Failure
- **Risk:** Key sorting error, missing entries, reversed mapping direction, wrong winner groups
- **Status:** ✅ **Addressed.** `validate_annex_c()` checks all 495 entries at startup. Winner groups derived from data (not hardcoded). Sorted-key invariant maintained.

### Pitfall 3: Performance Regression — 7× More Operations
- **Risk:** Simulation time jumps from ~1.3s to ~10-15s, breaking 60s polling loop
- **Standings computation hidden cost:** 72 match scans × 12 groups × 50K iterations
- **Status:** ✅ **Managed.** Actual time ~10-15s for 50K iterations, fitting within 60s interval. Precomputed matchup lambdas reduce overhead. Running totals during simulation.

### Pitfall 4: Third-Place Ranking — Cross-Group vs. Within-Group Confusion
- **Risk:** Using H2H for cross-group ranking (meaningless — teams never played each other)
- **Different tiebreaker chain:** 5 steps for third-place vs 7 steps for within-group
- **Status:** ✅ **Addressed in Phase 8.** Separate functions: `compute_standings()` (within-group) vs `rank_third_placed()` (cross-group). No H2H in cross-group.

### Pitfall 5: Group Match Result Persistence — Bracket Matching Breaks
- **Risk:** Same team pair in group AND knockout (e.g., Argentina vs Nigeria) causes wrong match slot mapping
- **Status:** ✅ **Addressed.** Separate `played_groups.json` for group results. Scoped search: `_find_group_match()` for groups, `process_matches()` for knockout. Distinct match_id scheme (`GS_A_01` vs `R32_1`).

### Pitfall 6: BSD Live Data Integration — Partial Group Results
- **Risk:** Partial group results (e.g., matchday 2 of 3) create invalid bracket states + high probability variance
- **Status:** ✅ **Addressed.** Completed matches fixed in `played_groups.json`; unplayed simulated per iteration. Monte Carlo handles uncertainty naturally.

### Pitfall 7: Bracket Validation — 104-Match DAG Needs Structural Checks
- **Risk:** Wrong round counts, third-place slot counts, R16 wiring violations, circular dependencies
- **Status:** ✅ **Addressed.** Bracket validation checks unique IDs, source_matches integrity, no cycles, round counts, slot types.

### Pitfall 8: Fair Play Tiebreaker — Card Points Scoring Subtly Wrong
- **Risk:** Double-counting indirect red, per-player caps, wrong deduction values
- **Status:** ✅ **Addressed.** Fair play deduction logic follows FIFA rules: YC=-1, 2YC→RC=-3, straight RC=-4, YC+RC=-5.

## Technical Debt Patterns (Status)

| Shortcut | Recommendation | Status |
|---|---|---|
| Combine group + knockout in single bracket.json | NEVER — separate files | ✅ Separate groups.json + bracket.json |
| Skip fair play tiebreaker | Skip only for demo | ✅ Implemented in tiebreaker chain |
| Hardcode Annex C as Python dict | NEVER — must be JSON file | ✅ data/annex_c.json, loaded at startup |
| Use random.random() per match call | Acceptable for MVP | ✅ Still per-call (acceptable at 50K) |
| Derive R32 wiring algorithmically | NEVER — use Annex C | ✅ 495-entry table used |
| Skip third-place match (M103) | Skip only if TPP not shown | ✅ TPP implemented in knockout pipeline |

## "Looks Done But Isn't" Checklist — Status

- [x] Groups JSON created with match_id references? **Yes — stable match IDs for persistence**
- [x] Annex C JSON validated for all 495 entries? **Yes — startup validation**
- [x] Tiebreaker tested for 3+ team ties? **Yes — recursive narrowing unit-tested**
- [x] Third-place selection exactly 8? **Yes — rank-then-slice, explicitly validated**
- [x] BSD live data flowing for 48 teams? **Yes — all 48 teams aliased**
- [x] Bracket validated for 104-match structure? **Yes — comprehensive validation**
- [x] Group advancement probabilities displayed? **Yes — in output**
- [x] Simulation fast enough for 60s interval? **Yes — ~10-15s**
- [x] Third-place match (M103) modeled? **Yes — loser tracking implemented**

---

*Pitfalls research for: FIFA-WC World Cup Dynamic Predictor*
*Researched: 2026-06-14 | Updated: 2026-06-16*
