# Phase 1: State & Elo Foundation — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 1-State & Elo Foundation
**Areas discussed:** Repository Structure, State Persistence Design, Bracket Representation, Team Normalization, Testing Strategy, Phase 2 Performance Risk

---

## Repository Structure Freeze

| Option | Description | Selected |
|--------|-------------|----------|
| src/ package | `worldcup_predictor/src/` (state.py, elo.py) — modular, import-friendly | ✓ |
| Flat structure | state.py and elo.py directly in worldcup_predictor/ | |
| Single file per phase | phase1_state_elo.py — one file per phase | |

**User's choice:** src/ package
**Notes:** Top-level dir `worldcup_predictor/`, data dir at `worldcup_predictor/data/`, all state in combined `state.py` (not split). Confirmed: too small for separate bracket module.

---

## State Persistence Design

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal teams | `{"team_name": {"elo": int}}` — elo only | ✓ |
| Extended teams | Add group, eliminated, fifa_rank upfront | |

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal played | `{match_id: {"winner": "Argentina"}}` | |
| Full record | Full match record with team_a, team_b, winner, scores, timestamp | ✓ |

**User's choice:** Minimal teams, full played record
**Notes:** "Store facts, not just state" — full played.json for debugging, restart recovery, future analytics. Negligible storage cost.

---

## Bracket Representation

| Option | Description | Selected |
|--------|-------------|----------|
| Flat match list | `[match_id, round, team_a, team_b, source_matches, winner]` | ✓ |
| Nested rounds | `{round_of_16: [...], quarterfinals: [...], ...}` | |

| Option | Description | Selected |
|--------|-------------|----------|
| Dynamic resolution | Match by team names at runtime — no mapping file | |
| Static mapping file | `data/api_id_mapping.json` hardcoded | |
| Both | Dynamic primary + static fallback | ✓ |

**User's choice:** Flat bracket list, dynamic primary + static fallback
**Notes:** Phase 3 logic: try dynamic → if ambiguous → consult api_id_mapping.json → if unresolved → raise error. Known pitfalls: USA/United States, Korea Republic/South Korea, IR Iran/Iran.

---

## Team Normalization

| Option | Description | Selected |
|--------|-------------|----------|
| Canonical names only | Single canonical name per team, normalization in Phase 3 | ✓ |
| Include alias mapping | Store aliases in teams.json upfront | |

**User's choice:** Canonical names in Phase 1
**Notes:** Create `data/team_aliases.json` as placeholder in Phase 1. Add DATA-04 requirement for Phase 3. Normalization logic deferred.

---

## Testing Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Elo + bracket validation | test_elo.py + test_state.py for critical paths | ✓ |
| Elo engine only | Core math only | |
| All + property-based | Hypothesis tests for invariants | |

| Option | Description | Selected |
|--------|-------------|----------|
| pytest + pytest-cov | Industry standard with coverage | ✓ |
| unittest (stdlib) | Built-in, zero dependencies | |
| pytest only | No coverage metrics | |

**User's choice:** pytest + pytest-cov, elo + state tests
**Notes:** No mandatory coverage percentage. "Coverage targets often create useless tests. Focus on critical behavior coverage, not percentages." Specific test cases in CONTEXT.md D-17.

---

## Phase 2 Performance Risk

| Option | Description | Selected |
|--------|-------------|----------|
| No benchmark in Phase 1 | Phase 2 handles its own benchmark | |
| Add micro-benchmark skeleton | Create `tests/bench_simulator.py` scaffold | |
| Define profiling criteria | Document 5s threshold and numpy fallback plan | ✓ |

**User's choice:** Document risk in CONTEXT.md
**Notes:** Add Phase 2 success criterion: profile 50K simulations; if <5s missed, evaluate NumPy. No code changes in Phase 1. Do not modify roadmap structure.

---

## the agent's Discretion

- Atomic write implementation details (tempfile naming, retry count)
- Error message formatting on validation failures
- Default Elo start value (1500 is standard baseline)

## Deferred Ideas

- **DATA-04: Team Name Normalization** — Phase 3
- **NumPy optimization** — Phase 2 performance gate
