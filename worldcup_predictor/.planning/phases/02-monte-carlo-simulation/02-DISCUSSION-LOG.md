# Phase 2: Monte Carlo Simulation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 2-Monte Carlo Simulation
**Areas discussed:** Bracket traversal, Simulation function interface, Probability aggregation detail, Random seed strategy, Performance profiling gate, Per-iteration state management

---

## Bracket Traversal

| Option | Description | Selected |
|--------|-------------|----------|
| Topological sort by round | Group matches by round (R16 → QF → SF → FINAL), simulate sequentially | ✓ |
| Recursive resolve from root | Start at FINAL, resolve source_matches recursively | |
| BFS from leaf matches | Start with R16, propagate winners forward through source_matches | |

**User's choice:** Topological sort by round
**Notes:** "R16 → QF → SF → FINAL is exactly how a knockout tournament progresses. Cleanest and most maintainable approach for 50,000+ iterations. No recursion complexity."

---

## Simulation Function Interface

| Option | Description | Selected |
|--------|-------------|----------|
| Single pure function with all data passed in | `run_simulation(teams, bracket, played, iterations, seed)` | ✓ |
| Function that loads state internally | Calls state.load_*() internally | |
| Simulation class with state | `class Simulator` with __init__ and run() | |

**User's choice:** Single pure function
**Notes:** "Pure function, easy unit testing, no hidden I/O, deterministic with seed, easy profiling, easy multiprocessing later. Keep simulation logic completely separate from state."

---

## Probability Aggregation Detail

| Option | Description | Selected |
|--------|-------------|----------|
| Championship probability only | `{"Argentina": 0.234, ...}` | |
| Championship + per-round advancement | `{"Argentina": {"qf": 0.88, "sf": 0.61, "final": 0.39, "champion": 0.24}}` | ✓ |

**User's choice:** Championship + per-round advancement
**Notes:** "Monte Carlo simulations are expensive. Run once, extract maximum information. +5% complexity now, very high future value. Users want to see: quarterfinal chance, semifinal chance, final chance, champion chance."

---

## Random Seed Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Per-call seed parameter | `seed=None` default, sets `random.seed()` internally | ✓ |
| Always seed + store in output | Return metadata with seed_used, iterations | |

**User's choice:** Per-call seed parameter
**Notes:** "Explicit, testable, reproducible when needed, non-deterministic by default. Maps directly to future --seed CLI flag. No output pollution. Return probabilities only."

---

## Performance Profiling Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Pytest benchmark test | Assert <5s in CI | |
| Separate benchmark script | `scripts/benchmark_simulation.py`, developer-run | ✓ |
| Start with performance awareness | No formal benchmark, just efficient code | |

**User's choice:** Separate benchmark script
**Notes:** "A performance test inside CI is usually a mistake — different machines, different CPUs, flaky CI. Use a developer-run benchmark script. 50K iterations <5s on developer machine. PASS/FAIL output."

---

## Per-iteration State Management

| Option | Description | Selected |
|--------|-------------|----------|
| Build progression dict from scratch | Fresh winner_progression dict each iteration | ✓ |
| Working copy mutation with reset | Copy bracket, mutate winner, reset | |

**User's choice:** Build progression dict from scratch
**Notes:** "No mutation. No reset logic. No state leakage risk. Each iteration builds its own winner_progression dict and leaves input data untouched."

---

## Agent's Discretion

- Seed data for `src/simulation.py` module structure
- Error handling for edge cases (all matches already played)
- `random.seed()` scope (module-level or local)
- Whether to use `random.random()` or `random.choice()` for match outcome

## Deferred Ideas

None — discussion stayed within phase scope.
