# Phase 2: UCL Knockout Phase — Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the complete UCL knockout pipeline: two-legged playoff round (positions 9–24), seeded R16 bracket construction with exact UEFA pairings and top-4 protection, full knockout tree (R16 → QF → SF → Final) with per-team stage probabilities — all reusing `football_core` Poisson match simulation without modifying core.

This phase extends the Phase 1 Monte Carlo loop so each iteration simulates both the league phase standings and then the knockout pipeline from those standings.

</domain>

<decisions>
### Governance

- **D-13:** Phase 2 public interfaces are frozen as of 2026-06-28. Any proposal to change a signature, return schema, or stage model (D-09) requires an architecture review before implementation. No downstream phase or caller may modify Phase 2 contracts without review.

## Implementation Decisions

### Extra Time and Penalties
- **D-01:** ET is simulated locally using reduced Poisson lambda (lower base rate than normal time) because BSD API does not expose ET scores — `extra_time_score` is always null in live API data.
- **D-02:** Penalty shootouts are simulated locally. The exact calibration method and conversion rate will be determined during planning using available evidence (including BSD historical data if appropriate). BSD remains a validation/calibration source, not a runtime input.
- **D-03:** ET home advantage belongs to the second-leg home team (matches real UCL rules: ET is played at the second leg's venue).

### Playoff Draw
- **D-04:** Playoff pairings are stored in a dedicated playoff draw data file, not computed or randomized. This represents the actual draw outcome as a competition artifact, separate from the league-phase fixture schedule.
- **D-05:** Deterministic position-based pairing (9v24, 10v23, etc.) is the fallback if no official draw data is available.

### R16 Bracket Structure
- **D-06:** The R16 pairing table and full bracket structure (which rounds feed into which) is stored in a dedicated bracket structure data file, not hardcoded in Python. Competition configuration belongs in data files, not code.

### Monte Carlo Integration
- **D-07:** The knockout pipeline extends the existing Phase 1 `run_monte_carlo()` loop — each iteration simulates league phase → standings → playoff → R16 bracket → full knockout tree. Single loop, single output. Not a separate simulation pass.
- **D-08:** Stage probabilities use the same post-aggregation pattern as Phase 1: track which round each team reaches per iteration, aggregate at end.

### Stage Tracking Granularity
- **D-09:** Per-team probabilities tracked for: Eliminated in League Phase (25–36), Reached Playoff (9–24), Reached Round of 16, Quarterfinal, Semifinal, Final, Champion.

### BSD API Role
- **D-10:** Live BSD API is authoritative for validation (Phase 4), not simulation (Phase 2). BSD validates final outcomes (`winner` field, `penalty_shootout` data, `home_score`/`away_score`) but does not provide a model to replicate for simulation.

### Architectural Invariants
- **D-11:** No modifications to `football_core`. All UCL-specific knockout logic (two-legged ties, playoff, bracket construction, stage tracking) lives under `competitions/ucl/`.
- **D-12:** Official competition structure (playoff draw, bracket layout, pairing tables) must be represented as replaceable data rather than executable logic, allowing future UEFA format updates without code changes.

### agent's Discretion
- Precision of the reduced Poisson lambda for ET (e.g., 0.3× vs 0.4× normal base rate) — planner to propose with evidence, user to confirm.
- Penalty conversion rate implementation details (fixed probability vs per-team adjustment).
- Data file schema for the playoff draw and bracket structure data files — agent to propose in PLAN.md.
- Function signature and file organization for knockout modules under `competitions/ucl/src/`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — UCLK-01 through UCLK-05 (knockout requirements)
- `.planning/ROADMAP.md` — Phase 2 section with success criteria

### Phase 1 (existing UCL code)
- `competitions/ucl/src/groups.py` — Swiss match simulation and standings (consumed by knockout pipeline as input)
- `competitions/ucl/src/simulation.py` — Existing MC loop to extend (`simulate_league_phase`, `run_monte_carlo`, `aggregate_mc_results`)
- `competitions/ucl/src/elo_fetcher.py` — ClubElo fetcher for Elo ratings
- `competitions/ucl/tests/conftest.py` — Test fixtures (36 teams, sample fixture schedule, Elo ratings)

### Shared Core
- `football_core/groups.py` — `expected_goals()` and Poisson primitives (reused for ET simulation)
- `football_core/knockout.py` — Reference pattern for WC knockout (UCL uses different two-legged approach)
- `football_core/fetcher.py` — BSD API fetch pattern (for Phase 4 reference)

### BSD API (verified capabilities)
The live BSD API (league_id=7 for UEFA Champions League) exposes the following fields relevant to knockout validation:
- `penalty_shootout` — home/away penalty scores (populated for matches resolved by shootout)
- `winner` — resolving team when aggregate score is level
- `home_score` / `away_score` — final scores (includes ET if applicable)
- `round_name` — "Round of 16", "Quarterfinals", "Semifinals", "Final"
- `home_score_ht` / `away_score_ht` — half-time scores
- `extra_time_score` — always null (BSD does not distinguish FT vs ET scoring)
- No official playoff pairings or bracket structure is exposed by the API

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `competitions.ucl.src.groups.compute_swiss_standings()` — Produces the standings list that feeds into playoff qualification (positions 9–24).
- `competitions.ucl.src.groups.precompute_swiss_matchup_lambdas()` — Precomputed Poisson lambdas pattern, reusable for knockout matchups.
- `competitions.ucl.src.simulation.run_monte_carlo()` — The N-iteration loop to extend with knockout stages.
- `competitions.ucl.src.simulation.aggregate_mc_results()` — The aggregation function to extend with new stage probability fields.
- `football_core.groups.expected_goals()` — Poisson expected goals computation, reusable for ET with reduced base rate.

### Established Patterns
- **Post-aggregation MC**: Collect per-iteration results in flat lists, aggregate once after loop (Phase 1 pattern, proven in `simulation.py`).
- **Precomputed lambdas**: Compute matchup lambdas once before the iteration loop for performance (Phase 1 pattern).
- **Data files for competition structure**: `fixtures.json`, `uefa_coefficients.json`, `team_aliases.json` in `competitions/ucl/data/` — extend with dedicated data files for playoff draw and bracket structure.
- **TDD pattern**: RED → GREEN → REFACTOR commits, consistent with Phase 1 plans.
- **No `football_core` modifications**: All UCL logic in `competitions/ucl/`.

### Integration Points
- `competitions/ucl/src/simulation.py` — Extend `run_monte_carlo()` and `simulate_league_phase()` to accept knockout data and call knockout pipeline after league phase.
- `competitions/ucl/src/__init__.py` — Export new knockout module functions.
- `competitions/ucl/tests/conftest.py` — Add knockout-specific test fixtures (playoff pairings, bracket rules, sample standings).
- `competitions/ucl/data/` — Add dedicated data files for playoff draw and bracket structure.

</code_context>

<specifics>
- Two-legged ties: each leg simulated using normal Poisson (home/away advantage per leg), then aggregate scored. If aggregate level after 180 min, ET uses reduced Poisson, then penalties if still level.
- No away goals rule (UCL abolished it for 2025+ format).
- R16 bracket uses the official UEFA pairing table: seeds 1/2 vs 15/18, 3/4 vs 13/20, 5/6 vs 11/16, 7/8 vs 9/24 (with winner playoff bracket positions).
- Top-4 seeding protection: seeds 1–4 placed in separate bracket quarters so they cannot meet until semifinals.

</specifics>

<deferred>
- **What-if scenario analysis** (UCLD-01) — deferred to v2 Differentiators phase.
- **Path visualization** (UCLD-02) — deferred to v2 Differentiators phase.
- **Strength-of-schedule impact reporting** (UCLD-03) — deferred to v2 Differentiators phase.

</deferred>

---

*Phase: 2-UCL Knockout Phase*
*Context gathered: 2026-06-28*
