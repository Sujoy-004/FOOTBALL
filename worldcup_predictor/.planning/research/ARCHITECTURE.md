# Architecture Research: 48-Team Format Integration (v1.1)

**Domain:** FIFA World Cup 2026 dynamic prediction — 48-team group stage + Annex C R32 routing
**Researched:** 2026-06-14
**Mode:** Ecosystem (architecture dimension — v1.1 migration)
**Overall confidence:** HIGH

> **Post-research note:** All phases covered in this research (7–10) have been completed as of v2.0. The proposed architecture was implemented with minor deviations:
> - `src/groups.py` was created as recommended (776 lines implemented vs 200-300 estimated)
> - `src/knockout.py` replaced `simulation.py` as the primary pipeline
> - `src/elo_sync.py` and `src/evaluation.py` were added beyond the original v1.1 scope
> - `api_id_mapping.json` was replaced with team-pair-based match identification
> - BSD API was integrated (not Football-Data.org)

## Executive Summary

- **What this covers:** Architectural changes needed to migrate v1.0 knockout-only predictor (32 teams, R16→FINAL) to v1.1 48-team format (12 groups of 4, R32→R16→QF→SF→FINAL)
- **Key finding:** Group stage requires a score-producing match model (Poisson) rather than binary win/loss Elo model, because goal differential is the primary tiebreaker
- **Key architectural decision:** New `src/groups.py` module recommended (not extending `simulation.py`) — group stage engine is self-contained with different data inputs and complexity
- **Status:** ⚠️ **Completed** — the architecture described here was implemented in Phases 7–10

## 1. Data Model Changes

- `data/groups.json` — NEW (12 groups × 4 teams, 72 round-robin match slots)
- `data/bracket.json` — MODIFIED (40 knockout matches vs 23 in v1.0)
- `data/annex_c.json` — NEW (495-entry third-place lookup table)
- `data/teams.json` — EXTENDED (32 → 48 teams)
- Design rationale: Groups keyed by letter (A–L) for O(1) lookup during Annex C resolution
- **R32 slot types:** `group_position` (fixed slots like A2 vs B2) + `annex_c_third` (third-place teams resolved via Annex C)
- **R16 wiring** fixed per FIFA Article 12.7 — 8 R16 matches with specific `source_matches` pairings
- Third-place match (TPP) — new addition vs v1.0, uses SF losers
- All implemented as described (except `api_id_mapping.json` was not used — team-pair matching instead)

## 2. Simulation Pipeline Changes

**v1.0 pipeline (original):**
```
run_simulation(teams, bracket, played, iterations=50000)
  → _build_round_map → _simulate_r16 → _simulate_round(QF/SF/FINAL)
```

**v1.1 pipeline (proposed and implemented):**
```
run_full_simulation(teams, groups, bracket, annex_c, played, iterations)
  → simulate_group_matches() (72 matches, Poisson score model)
  → compute_standings() (12 groups, 7-step tiebreaker)
  → rank_third_placed() (5-step cross-group ranking)
  → resolve_r32_matchups() (Annex C lookup)
  → simulate_r32() → simulate_r16() → simulate_knockout_round(QF/SF/TPP/FINAL)
```

- **Match model changed:** Binary win/loss → Poisson score model for group matches (no numpy)
- **Knockout entry:** Hardcoded R16 names → R32 resolved from group standings
- **Rounds simulated:** 15 matches → 104 matches
- **Knockout traversal:** Existing `_simulate_knockout_round()` reused for QF/SF/FINAL

## 3. Annex C Routing — Architecture

- **Algorithm:** Extract third-placed teams → rank via 5-tier tiebreaker → select top 8 → build sorted group key → lookup in 495-entry table → resolve 8 third-place R32 slots + 8 fixed slots
- **Key insight:** Group winners from A, B, D, E, G, I, K, L host third-place teams. C, F, H, J winners face runners-up — fixed, not dynamic
- **Sorted-key property:** Combination key is comma-separated, alphabetically sorted group letters
- **Critical correctness:** Derive winner groups from `annex_c.json` itself — no hardcoding
- **Implemented as described** in `src/groups.py`

## 4. Module Boundaries (Proposed vs Actual)

**Proposed:**
- `src/groups.py` — NEW: group simulation + standings + Annex C resolver
- `src/simulation.py` — MODIFIED: `run_full_simulation()`, `simulate_r32()`
- `src/state.py` — EXTENDED: `load_groups()`, `load_annex_c()`, validators
- `src/fetcher.py` — EXTENDED: group match processing
- `src/output.py` — EXTENDED: group standings display, updated counts

**Actual implementation (deviations):**
- `src/knockout.py` was created as the primary pipeline module (separate from `simulation.py`)
- `src/elo_sync.py` and `src/evaluation.py` added beyond original scope
- No classes used — remained pure function style (research recommended `dataclasses`)
- `enum` and `dataclasses` not used — kept dict-based approach
- Rest of module boundaries match the proposal

## 5. Goal Model for Group Stage

- **Elo→Poisson** model recommended and implemented
- `expected_goals(rating_a, rating_b, base_rate)` → Poisson sample for scorelines
- No numpy — Knuth algorithm for Poisson sampling (~15 lines pure Python)
- Draws fall out naturally when `score_a == score_b`
- Precomputed matchup lambdas added for performance (not in original research)

## 6. Performance Projection (Post-Implementation)

- **Projected:** 50K iterations at ~10-15s for 104 matches
- **Actual:** ~10-15s confirmed, within 60s poll interval
- Bottlenecks addressed: precomputed lambdas, running totals during match simulation
- Performance benchmarks in Phases 8 and 9

## 7. Tiebreaker Implementation

- 7-step within-group: H2H points → H2H GD → H2H GS → Overall GD → Overall GS → Fair play → FIFA ranking
- 5-step third-place: Overall points → Overall GD → Overall GS → Fair play → FIFA ranking
- Recursive narrowing for multi-team ties (as recommended)
- Separate functions: `compute_standings()` vs `rank_third_placed()` (avoided the H2H confusion pitfall)

## 8. Phase Ordering (Completed)

| Phase | Module | Status |
|---|---|---|
| 7: Dataset | Data files (groups.json, annex_c.json, 48 teams) | ✅ Complete |
| 8: Group Engine | `src/groups.py` — simulation, standings, tiebreakers | ✅ Complete |
| 9: Knockout Bracket | Full 104-match simulation loop | ✅ Complete |
| 10: Integration | main.py, fetcher, output, state integration | ✅ Complete |
| 11: Data Integrity | Elo sync, data validation | ✅ Complete |
| 12/12b: Evaluation | Prediction metrics, baseline runs | ✅ Complete |

---

*Architecture research for: 48-team World Cup simulation integration*
*Researched: 2026-06-14 | Updated: 2026-06-16*
