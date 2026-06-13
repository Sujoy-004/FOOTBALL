# Phase 1: State & Elo Foundation — Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Delivers data persistence layer (JSON load/save), Elo rating engine, and bracket validation. By end of Phase 1, teams and bracket load from JSON on startup, bracket structure validates (match_ids unique, source_matches exist, no circular dependencies), Elo updates correctly after a match result, and all state persists across restarts.

Requirements: DATA-02, ELO-01, VAL-01

</domain>

<decisions>
## Implementation Decisions

### Repository Structure
- **D-01:** Top-level package: `worldcup_predictor/` — matches codebase maps and SOTs naming
- **D-02:** Module organization: `worldcup_predictor/src/` as Python package with `__init__.py` — scales through all 6 phases
- **D-03:** Data directory: `worldcup_predictor/data/` at project root, not inside `src/`
- **D-04:** All JSON state management in a single `state.py` — `load_teams()`, `save_teams()`, `load_bracket()`, `save_bracket()`, `load_played()`, `save_played()`. No separate bracket module — Phase 1 is too small to justify it.

### State Persistence Schemas
- **D-05:** `teams.json` — minimal schema: `{"Argentina": {"elo": 2100}}`. Extend with additional fields later.
- **D-06:** `bracket.json` — flat match list array (not nested rounds): `[{"match_id": "R16_1", "round": "R16", "team_a": "Argentina", "team_b": "Mexico", "source_matches": null, "winner": null}]`. Easier to validate, traverse, and look up.
- **D-07:** `played.json` — full match record: `{"R16_1": {"team_a": "Argentina", "team_b": "Mexico", "winner": "Argentina", "home_score": 2, "away_score": 1, "completed_at": "2026-06-15T22:05:01Z"}}`. Store facts, not just state — better debugging and future analytics.

### Bracket Representation
- **D-08:** API-to-bracket mapping strategy: dynamic team-name matching as primary, `api_id_mapping.json` as static fallback for ambiguous cases
- **D-09:** `api_id_mapping.json` is a Phase 3 concern — not created or implemented in Phase 1
- **D-10:** Phase 3 fallback flow: try dynamic matching → if ambiguous, consult `api_id_mapping.json` → if still unresolved, raise clear error

### Team Normalization
- **D-11:** Phase 1 uses canonical team names only — no normalization logic
- **D-12:** Create `data/team_aliases.json` as a reference file in Phase 1 with known aliases (file exists, logic deferred)
- **D-13:** Team name normalization belongs in Phase 3 — add DATA-04 requirement
- **D-14:** Known name ambiguities: USA/United States, Korea Republic/South Korea, IR Iran/Iran

### Testing Strategy
- **D-15:** Framework: `pytest` + `pytest-cov`
- **D-16:** No mandatory coverage percentage — focus on critical behavior coverage, not arbitrary targets
- **D-17:** Test files and cases:
  - `test_elo.py`: `expected_score()`, `update_ratings()`, equal ratings, large Elo gap, custom K-factor
  - `test_state.py`: load/save roundtrip, atomic write, bracket validation, corrupt JSON handling

### Phase 2 Performance Risk
- **D-18:** No benchmark code in Phase 1
- **D-19:** Document performance threshold: profile 50K simulations; if <5s target missed, evaluate NumPy optimization before proceeding
- **D-20:** Add Phase 2 success criterion: "Profile 50,000 simulations. If target (<5s) is missed, evaluate NumPy optimization before continuing."

### the agent's Discretion
- Atomic write implementation details (tempfile naming, retry count) — standard practices
- Error message formatting on validation failures
- Default Elo start value (1500 is standard baseline)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/PROJECT.md` — Project context, core value, constraints, key decisions
- `.planning/REQUIREMENTS.md` — v1 requirements (DATA-02, ELO-01, VAL-01 assigned to Phase 1)
- `.planning/ROADMAP.md` — Phase 1 goal, success criteria, mode (MVP)

### Codebase Architecture
- `.planning/codebase/STACK.md` — Technology stack (Python 3.10+, requests, pytest)
- `.planning/codebase/ARCHITECTURE.md` — System architecture, layers, data flow, abstractions
- `.planning/codebase/INTEGRATIONS.md` — Football-Data.org API details

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield project, no existing code

### Established Patterns
- No existing patterns — all patterns established in this phase

### Integration Points
- No integration code in Phase 1 — API integration deferred to Phase 3

</code_context>

<specifics>
## Specific Ideas

- "Store facts, not just state" — played.json should contain full match records for debugging, restart recovery, and future analytics
- Flat bracket list over nested rounds — validation and simulation traversal are simpler with flat data structures
- "Coverage targets often create useless tests" — focus on critical behavior coverage, not arbitrary percentages

</specifics>

<deferred>
## Deferred Ideas

- **DATA-04: Team Name Normalization** — Phase 3 concern. `data/team_aliases.json` created now as a placeholder, normalization logic implemented in Phase 3.
- **NumPy optimization** — Phase 2 performance gate. If 50K Monte Carlo simulations exceed 5s, evaluate NumPy acceleration before proceeding. Not a Phase 1 task.

</deferred>

---

*Phase: 1-State & Elo Foundation*
*Context gathered: 2026-06-13*
