# Phase 2: Monte Carlo Simulation — Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

System runs 50,000+ Monte Carlo simulations of the remaining knockout bracket, computes per-round advancement probabilities and championship probabilities for every team, and returns results as a pure dict — no I/O, no side effects. Performance gate: 50K iterations <5s on developer machine, measured by a standalone benchmark script (not CI).

Requirement: SIM-01

</domain>

<decisions>
## Implementation Decisions

### Bracket Traversal
- **D-01:** Topological sort by round — simulate in sequential round order (R16 → QF → SF → FINAL). Matches within a round are independent.
- **D-02:** Round functions are separate and sequential: `simulate_r16()`, `simulate_qf()`, `simulate_sf()`, `simulate_final()`. Clean, debuggable, parallelizable later.

### Simulation Function Interface
- **D-03:** Single pure function: `run_simulation(teams, bracket, played, iterations=50000, seed=None) -> dict[str, dict[str, float]]`
- **D-04:** No I/O inside simulation — state loaded separately by caller. Pure function receives all data as arguments.
- **D-05:** Module: `src/simulation.py` — following existing module structure (`elo.py`, `state.py`, `constants.py`).

### Probability Aggregation Detail
- **D-06:** Per-round advancement + championship:
  ```python
  {
      "Argentina": {"qf": 0.88, "sf": 0.61, "final": 0.39, "champion": 0.24},
      "Brazil": {"qf": 0.85, "sf": 0.55, "final": 0.30, "champion": 0.18},
      ...
  }
  ```
- **D-07:** Rounds tracked: `qf` (quarterfinal), `sf` (semifinal), `final`, `champion`. Keys match round naming in seed bracket data.
- **D-08:** Probabilities sum to ~100% for `champion` within floating-point tolerance.

### Random Seed Strategy
- **D-09:** `seed=None` by default (system entropy). When `seed` is provided, call `random.seed(seed)` internally at simulation start.
- **D-10:** Function returns probabilities dict only — no metadata or seed bookkeeping in return value.

### Performance Profiling Gate
- **D-11:** Separate `scripts/benchmark_simulation.py` — developer-run, not a CI test (performance varies across machines).
- **D-12:** Benchmark measures elapsed time for N iterations and reports: iterations, elapsed seconds, rate (sims/sec), PASS/FAIL (<5s threshold).
- **D-13:** If 50K iterations miss 5s on developer machine, evaluate NumPy optimization before proceeding (per D-18/D-19 from Phase 1).

### Per-Iteration State Management
- **D-14:** Each iteration builds a fresh `winner_progression` dict. No deep copies, no mutation of input data, no reset logic.
- **D-15:** Winner dict: `{match_id: winner_team_name}` — populated as each round completes, read by downstream rounds to determine participants.

### Agent's Discretion
- Seed data for `src/simulation.py` — standard module structure following existing patterns
- Error handling for edge cases (e.g., all matches already played — nothing to simulate)
- Implementation of `random.seed()` scope (module-level or local)
- Whether to use `random.random()` or `random.choice()` for match outcome determination

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/ROADMAP.md` — Phase 2 goal: "System can simulate remaining knockout tournament 50,000+ times and compute accurate championship probabilities from current Elo ratings"
- `.planning/REQUIREMENTS.md` — SIM-01 assigned to Phase 2

### Architecture & Phase 1 Decisions
- `.planning/phases/01-state-elo-foundation/01-CONTEXT.md` — Phase 1 decisions (D-07 flat bracket, D-18/D-19 NumPy gate, D-04 state.py patterns)
- `.planning/codebase/ARCHITECTURE.md` — System architecture, layers, data flow

### Codebase Implementation
- `worldcup_predictor/src/elo.py` — `expected_score()` computes match win probability from Elo ratings
- `worldcup_predictor/src/state.py` — `load_teams()`, `load_bracket()`, `load_played()` — data access patterns
- `worldcup_predictor/data/bracket.json` — 23-match flat bracket with `source_matches` linking rounds
- `worldcup_predictor/data/teams.json` — 32 teams with Elo ratings

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `elo.expected_score(rating_a, rating_b)` — directly computes match win probability; simulation core
- `state.load_bracket()` + `state.validate_bracket()` — bracket already validated on load; simulation can assume valid structure
- `state.load_played()` — played matches dict; simulation uses to skip already-completed matches

### Established Patterns
- Pure functional style — no classes, dict/list data structures, explicit dependencies
- Module pattern: single-purpose modules (`elo.py`, `state.py`, `constants.py`)
- All state loading/saving in `state.py` — simulation does NOT do I/O

### Integration Points
- `main.py` — Phase 2 adds simulation call after state loading in startup
- `data/bracket.json` — flat list, `source_matches` field links rounds; simulation walks this DAG
- `data/played.json` — already-played matches keyed by match_id; simulation skips these

</code_context>

<specifics>
## Specific Ideas

- "Run once, extract maximum information" — per-round probabilities cost ~5% extra complexity now, save full re-design later
- "No mutation of input data" — each iteration builds fresh state; no reset, no leakage between iterations
- "Benchmark script, not CI test" — performance varies by machine; developer measures on their own hardware
- Sequential round functions (R16 → QF → SF → FINAL) mirror how a knockout tournament actually progresses

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-Monte Carlo Simulation*
*Context gathered: 2026-06-13*
