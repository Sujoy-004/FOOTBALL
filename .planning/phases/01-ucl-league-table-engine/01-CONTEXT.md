# Phase 1: UCL League Table Engine — Context

**Gathered:** 2026-06-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the UCL league table engine: 36-team Swiss-system regular season with fixture schedule loading and validation, correct UCL-specific tiebreaker chain (no H2H), qualification zone determination (top 8 direct, 9–24 playoff, 25–36 eliminated), Monte Carlo simulation for per-team advancement probabilities — all reusing `football_core` Poisson match simulation without modifying core.

</domain>

<decisions>
## Implementation Decisions

### Elo Initialization for UCL Teams
- **D-01:** Use **ClubElo** (`api.clubelo.com/CLUBNAME`) as the Elo rating source for UCL club teams. BSD API was investigated first but has no club strength metric.
- **D-02:** Fetch all 36 teams' ratings **once before simulation starts** — no lazy-loading, no per-matchday fetching.
- **D-03:** Cache the fetched ratings for the entire simulation run. Do not refresh mid-run.
- **D-04:** Record the ClubElo snapshot date in the simulation output for reproducibility.
- **D-05:** Refresh policy is configurable (daily or on demand) for subsequent simulation runs — not within a run.

### Monte Carlo Output Granularity
- **D-06:** Output per-team **zone probabilities** (top-8, playoff 9–24, eliminated 25–36) plus **champion probability**.
- **D-07:** Output per-team **averages for the full tiebreaker chain**: average position (1–36), average points, average GD, average GS, average away GS, average wins, average away wins.

### the agent's Discretion
- Fixture schedule file format (JSON vs CSV) and schema — agent to propose in PLAN.md, user to confirm.
- Data directory structure for UCL fixtures under `competitions/ucl/data/`.
- Whether to use a dedicated `compute_swiss_standings()` function or build the logic directly into a simulation orchestrator class — agent to design and propose.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — UCLT-00 through UCLT-06
- `.planning/ROADMAP.md` — Phase 1 section with success criteria

### Shared Core
- `football_core/groups.py` — `simulate_group_matches()` and `expected_goals()` patterns to reuse
- `football_core/groups.py` § `_build_poisson_table`, `_poisson_sample` — Poisson simulation primitives
- `football_core/constants.py` — shared constants, base_rate for goal expectation

### Competition Patterns
- `competitions/worldcup/src/groups.py` — `compute_standings()` as reference for competition-specific standings logic (UCL uses different tiebreaker chain)
- `competitions/worldcup/tests/test_groups.py` — tiebreaker test patterns to follow

### External API
- `http://api.clubelo.com/CLUBNAME` — ClubElo API, returns per-team Elo history as CSV. No auth required.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `football_core.groups.simulate_group_matches()` — can simulate matches using Poisson given groups dict and Elo ratings. UCL will need to call this with 36-team fixture schedule.
- `football_core.groups.expected_goals(ea, eb, base_rate)` — computes expected goals from Elo ratings. ClubElo ratings feed directly into this.
- `football_core.groups._compute_conduct_score()` — shared discipline tiebreaker helper, reusable for UCL's disciplinary tiebreaker step.

### Established Patterns
- World Cup `compute_standings()` uses per-group 7-step recursive H2H tiebreaker. UCL needs completely different: 10-step single-table chain with **no H2H** (not applicable in Swiss system). UCL standings function should be standalone in `competitions/ucl/` — do not modify or extend the WC version.
- WC uses group-based data structure (`{"Group A": {"matches": [...]}}`). UCL uses single flat table — data model will differ.
- All competition-specific logic lives in `competitions/<name>/`. Zero competition logic in `football_core`.

### Integration Points
- `competitions/ucl/` — new module directory. Initial structure matches the pattern: `src/`, `data/`, `tests/`.
- Existing BSD integration (`competitions/worldcup/src/fetcher.py`) is a pattern reference for live API data, but UCL Phase 4 (Validation) handles BSD live validation. Phase 1 uses static fixture data files + ClubElo API only.

</code_context>

<specifics>
## Specific Ideas
- Fixture schedule should be a JSON file under `competitions/ucl/data/fixtures.json` with the official UCL draw format: each entry specifies home team, away team, pot assignments, and matchday.
- The tiebreaker chain implementation should be a single function (`resolve_swiss_tiebreakers()`) that takes two tied teams and the full standings context, returning the winner — testable in isolation.
- Monte Carlo should store per-iteration results (final positions) and aggregate at the end, rather than maintaining running counters.

</specifics>

<deferred>
## Deferred Ideas
None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-UCL League Table Engine*
*Context gathered: 2026-06-27*
