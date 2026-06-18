# Phase 8: Group Stage Simulation Engine - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 8 delivers the group stage simulation engine as a new `src/groups.py` module. This module handles: 72 round-robin group match simulation per Monte Carlo iteration (Poisson score model), 12-group standings computation with 7-step within-group tiebreaker chain, 5-step cross-group third-place ranking, advancement selection (24 auto-advancers + 8 best third-placed), and Annex C lookup for R32 matchup resolution. The third-place match (TPP) is explicitly deferred to Phase 9.

Phase 8 does NOT modify `simulation.py`, `main.py`, `fetcher.py`, or `output.py`. It produces a consumable module that Phase 9 will integrate into the full simulation pipeline.
</domain>

<decisions>
## Implementation Decisions

### Poisson Model Calibration
- **D-01:** Use the Knuth algorithm for Poisson sampling (no numpy dependency — ~15 lines pure Python using `random.random()`).
- **D-02:** Add `EXPECTED_GOALS_BASE_RATE: float = 1.25` to `constants.py` (configurable, defaults to historical WC group average of 1.25 goals/team/match).
- **D-03:** The `expected_goals()` function signature: `expected_goals(rating_a, rating_b, base_rate=None) -> float` — defaults to `constants.EXPECTED_GOALS_BASE_RATE`.

### Fair Play Tiebreaker
- **D-04:** Implement probabilistic card distribution per team per match during group simulation:
  - Yellow cards: `Poisson(2.0)` per team per match
  - Red cards: `Poisson(0.05)` per team per match
- **D-05:** Card counting follows official FIFA deduction values: YC = -1, 2YC→RC = -3, straight RC = -4, YC→RC = -5.
- **D-06:** Fair play score is the sum across all simulated group matches (not averaged).
- **D-07:** Do NOT overbuild — simple Poisson draws suffice. No per-player tracking needed for MC.

### Third-Place Match
- **D-08:** TPP (third-place match) is explicitly deferred to Phase 9. Phase 8's `groups.py` produces `standings` and `advancers` dicts only. No TPP tracking in Phase 8.

### Module Architecture
- **D-09:** New `src/groups.py` module (no circular dependencies — consumed by `simulation.py`, does not import it).
- **D-10:** Functions follow the signatures specified in `ARCHITECTURE.md` §5.2.
- **D-11:** Standings computed from per-iteration simulated match results (not replayed from persisted data).
- **D-12:** `winner_progression` is NOT used for group matches — group results stored in separate `group_results` dict. `winner_progression` starts at R32 (handled in Phase 9).

### Tiebreaker Implementation
- **D-13:** 7-step within-group tiebreaker: H2H points → H2H GD → H2H GS → overall GD → overall GS → fair play → FIFA ranking.
  - **Verified:** FIFA 2026 regulations explicitly reversed the order from pre-2026. Confirmed by `FEATURES.md` §1 (FIFA Regulations Article 13, ESPN, Bracket2026 — all identical), `PITFALLS.md` §Pitfall 1 (flags this as the #1 implementation trap), and `ARCHITECTURE.md` §5.x.
  - **Not a mistake:** H2H-first is unusual but correct for 2026. The *wrong* order (overall-first) is what most tutorials and legacy code use.
- **D-14:** Recursive narrowing for multi-team ties — restart from step 1 when a subset is isolated.
- **D-15:** 5-step cross-group third-place ranking: overall points → overall GD → overall GS → fair play → FIFA ranking (no H2H — teams from different groups never played each other).
- **D-16:** Sort descending for points/GD/GS.
  - **Fair play (conduct_score):** stored as **positive penalty points** (YC=+1, 2YC→RC=+3, RC=+4, YC→RC=+5). Sort **ascending** (lower penalty points = better discipline = wins tiebreak).
  - **FIFA ranking:** Sort ascending (lower rank number = better team = wins tiebreak). Phase 8 uses Elo as a proxy (higher Elo = better) with descending sort; Phase 10 expected to replace with real FIFA ranking data.

### Performance
- **D-17:** Target: 50K full simulation iterations in < 15s (as measured in Phase 9 when bracket is connected).
- **D-18:** Phase 8 standalone benchmark: simulate 72 group matches + compute standings for 50K iterations, measure time.
- **D-19:** Accept 10-15s range. The 60s poll interval provides sufficient headroom.

### the agent's Discretion
- Choice of which random generator API (`random.Random()` instance vs module-level). Standard approach is preferred.
- Whether to use `functools.lru_cache` on expected_goals for identical Elo pairs at this stage (defer if < 5s benchmark).
- Fair play edge case handling for 2YC→RC conversion within a single match (per-player tracking per match, reset across matches).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Design
- `.planning/research/ARCHITECTURE.md` — Full architecture for groups.py module, pipeline changes, performance projections, tiebreaker implementation detail
- `.planning/research/PITFALLS.md` — 8 critical pitfalls with prevention strategies (especially Pitfall 1: tiebreaker step reversal, Pitfall 4: third-place ranking confusion, Pitfall 8: fair play scoring)
- `.planning/research/FEATURES.md` — FIFA 2026 format verification, 495 Annex C scenarios, R32 seeding matrix
- `.planning/research/SUMMARY.md` — Synthesized research findings for all areas
- `.planning/REQUIREMENTS.md` — GROUPS-01 through GROUPS-07 requirements

### Data Files (created in Phase 7)
- `worldcup_predictor/data/groups.json` — 12 groups (A-L), 4 teams each, 72 match definitions
- `worldcup_predictor/data/annex_c.json` — 495-entry Annex C lookup table
- `worldcup_predictor/data/teams.json` — 48 teams with Elo ratings
- `worldcup_predictor/data/team_aliases.json` — 48 entries, 1:1 coverage with teams.json

### Code to Reference
- `worldcup_predictor/src/state.py` — `validate_groups()`, `load_groups()`, `validate_annex_c()`, `load_annex_c()` — the data loading patterns
- `worldcup_predictor/src/constants.py` — `GROUP_COUNT`, `TEAMS_PER_GROUP`, `MATCHES_PER_GROUP`, `ANNEX_C_ENTRIES`, `ANNEX_C_WINNER_GROUPS`, `K_FACTOR`, `DEFAULT_ELO`
- `worldcup_predictor/src/simulation.py` — Current knockout simulation patterns (for reference — groups.py is independent)
- `worldcup_predictor/src/elo.py` — `expected_score()` function for Elo probability computation
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Poisson generator** — phase already suggests Knuth algorithm; no existing asset, but `expected_goals()` uses the same `10^(Δelo/400)` factor from `elo.py`
- **`random.Random`** — used throughout `simulation.py` with seeded instance; Phase 8 should follow the same pattern for reproducibility

### Established Patterns
- **Load→Validate→Return** — All state loaders follow this pattern. Phase 8 functions will consume already-validated data.
- **Sequential validation checks** — `validate_bracket()` raises `ValueError` with descriptive messages on first failure. Group validators follow this.
- **Per-iteration fresh state** — `simulation.py` resets `winner_progression` each iteration. Phase 8 should follow the same pattern with `group_results`.

### Integration Points
- `src/groups.py` → consumed by `src/simulation.py` in Phase 9 (no circular deps — groups.py does NOT import simulation.py)
- `src/groups.py` → imports: `random`, `math` (for Poisson), `src.constants`, `src.elo` (for expected_score)
- Output dict shape: `standings` dict keyed by group letter, each value list of team result dicts sorted by position (1-4)
</code_context>

<specifics>
## Specific Ideas

- The expected_goals function must handle the home/away distinction. By default, `team_a` is treated as home (receives a small multiplier ~1.05 on base_rate to reflect HFA). This is built into the Poisson model by adjusting the base_rate per team rather than having a separate HFA parameter.
- The Annex C resolver function should raise a descriptive `ValueError` if the combination key is not found (missing Annex C entry), not silently fail.
- Standings data structure: `{group_letter: [{team, pts, gd, gs, yellow_cards, red_cards, conduct_score, position}, ...]}` — the 4 teams in position order (1-4).
</specifics>

<deferred>
## Deferred Ideas

- **Third-place match (TPP) tracking** — moved from Phase 8 to Phase 9. Phase 9 will implement `sf_losers` dict tracking as part of the full bracket integration.
- **Historical fair play calibration per confederation** — not needed for MVP. The Poisson(2.0)/Poisson(0.05) defaults provide sufficient realism for tiebreaker edge case generation.
- **NumPy-accelerated simulation** — not needed. Phase 8 benchmark will confirm < 15s target. Revisit only if profiling shows > 20s.

None — discussion stayed within phase scope.
</deferred>

---

*Phase: 8-Group Stage Simulation Engine*
*Context gathered: 2026-06-14*
