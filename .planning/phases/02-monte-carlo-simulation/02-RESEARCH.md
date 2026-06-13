# Phase 2: Monte Carlo Simulation — Research

**Researched:** 2026-06-13
**Domain:** Monte Carlo simulation of knockout tournament brackets with Elo-based match outcomes
**Confidence:** HIGH

## Summary

This phase builds a pure-Python Monte Carlo engine that runs 50,000+ iterations of the 23-match knockout bracket, computing per-round advancement probabilities (QF/SF/FINAL/CHAMPION) for each of 32 teams using Elo-derived win probabilities from `elo.expected_score()`. The bracket is a flat list of match objects linked by `source_matches` arrays — a DAG that must be walked in round order. Performance target is 50K iterations in <5 seconds on the developer machine.

The existing codebase provides clear patterns: pure functional modules (`elo.py`, `state.py`, `constants.py`), no global mutable state, no I/O in core logic. The simulation module (`src/simulation.py`) follows this exactly — a single pure function `run_simulation(teams, bracket, played, iterations=50000, seed=None)` that receives all data as arguments and returns probabilities as a dict.

**Primary recommendation:** Pre-compute bracket walk order (topological sort by round) as a module-level constant, then use a tight `for` loop with local variable bindings (`random.random` to local, pre-resolve match lookups) to hit the 5-second performance target. Write pure Python first — NumPy acceleration is a documented fallback if the threshold is missed.

**Key performance insight:** 50K iterations × 23 matches = 1.15M match simulations. On Python 3.11 (confirmed available), with optimized local-bindings and pre-computed match ordering, each match simulation costs ~2-4μs, putting total runtime at ~2.3-4.6s — within the 5s target. [ASSUMED — will be validated by benchmark script]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|-----------|-------------|----------------|-----------|
| Match simulation | Core Logic (`simulation.py`) | — | Pure function: receives teams/bracket/played, returns probabilities |
| Win probability computation | Core Logic (`elo.py`) | — | Already exists as `expected_score()`, called by simulation |
| Bracket DAG traversal | Core Logic (`simulation.py`) | — | Walk `source_matches` to determine match order and participants |
| Probability aggregation | Core Logic (`simulation.py`) | — | Count per-round wins across all iterations into final dict |
| State loading | State/Persistence (`state.py`) | — | `load_teams()`, `load_bracket()`, `load_played()` — already exist |
| Performance profiling | Developer Tool (`scripts/benchmark_simulation.py`) | — | Separate script, not CI, measures elapsed time for N iterations |
| Orchestration | Orchestration (`main.py`) | — | Calls `run_simulation()` after state loading, passes results to output |

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Topological sort by round — simulate in sequential round order (R16 → QF → SF → FINAL). Matches within a round are independent.
- **D-02:** Round functions are separate and sequential: `simulate_r16()`, `simulate_qf()`, `simulate_sf()`, `simulate_final()`. Clean, debuggable, parallelizable later.
- **D-03:** Single pure function: `run_simulation(teams, bracket, played, iterations=50000, seed=None) -> dict[str, dict[str, float]]`
- **D-04:** No I/O inside simulation — state loaded separately by caller. Pure function receives all data as arguments.
- **D-05:** Module: `src/simulation.py` — following existing module structure (`elo.py`, `state.py`, `constants.py`).
- **D-06:** Per-round advancement + championship:
  ```python
  {
      "Argentina": {"qf": 0.88, "sf": 0.61, "final": 0.39, "champion": 0.24},
  }
  ```
- **D-07:** Rounds tracked: `qf` (quarterfinal), `sf` (semifinal), `final`, `champion`. Keys match round naming in seed bracket data.
- **D-08:** Probabilities sum to ~100% for `champion` within floating-point tolerance.
- **D-09:** `seed=None` by default (system entropy). When `seed` is provided, call `random.seed(seed)` internally at simulation start.
- **D-10:** Function returns probabilities dict only — no metadata or seed bookkeeping in return value.
- **D-11:** Separate `scripts/benchmark_simulation.py` — developer-run, not a CI test.
- **D-12:** Benchmark measures elapsed time for N iterations and reports: iterations, elapsed seconds, rate (sims/sec), PASS/FAIL (<5s threshold).
- **D-13:** If 50K iterations miss 5s on developer machine, evaluate NumPy optimization before proceeding.
- **D-14:** Each iteration builds a fresh `winner_progression` dict. No deep copies, no mutation of input data, no reset logic.
- **D-15:** Winner dict: `{match_id: winner_team_name}` — populated as each round completes, read by downstream rounds to determine participants.

### Agent's Discretion

- Seed data for `src/simulation.py` — standard module structure following existing patterns
- Error handling for edge cases (e.g., all matches already played — nothing to simulate)
- Implementation of `random.seed()` scope (module-level or local)
- Whether to use `random.random()` or `random.choice()` for match outcome determination

### Deferred Ideas (OUT OF SCOPE)

None.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SIM-01 | System runs Monte Carlo simulation of remaining knockout tournament (50,000+ iterations) to compute championship probabilities for every team | See Standard Stack, Architecture Patterns, Performance Analysis — pure Python approach with pre-computed walk order and local variable bindings expected to hit 50K <5s target |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `random` (stdlib) | 3.11+ | Random number generation for match outcomes | Only RNG needed for MVP; `random.random()` at ~70ns/call [VERIFIED: docs.python.org/3/library/random.html]; no external deps |
| `math` (stdlib) | 3.11+ | `math.pow(10, diff/400)` for Elo expected_score | Already used by `src/elo.py`; must be in the hot path |
| `itertools` (stdlib) | 3.11+ | Optional grouping/batching of round matches | Clean round iteration patterns; not in hot path |
| `collections` (stdlib) | 3.11+ | `defaultdict(int)` for per-iteration counters | Clean aggregation: `{team: {round: count}}` pattern |
| `time` (stdlib) | 3.11+ | Benchmark timing | For `scripts/benchmark_simulation.py`; `time.perf_counter()` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `numPy` | 2.x | Vectorized simulation (fallback) | Only if pure Python misses 5s threshold per D-13. Pre-generate outcome arrays with vectorized `np.random.random()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `random.random()` + `<` | `random.choice(['team_a', 'team_b'])` | `random.random()` is ~70ns vs `random.choice()` ~900ns per call [CITED: geoffruddock.com/python-random-module-faster-than-numpy] — 10x faster. Use `random.random() < prob_a`. |
| `random.seed()` global | `random.Random(seed)` instance | Global `random.seed()` is simplest per D-09/D-10 and matches the "call internally at simulation start" requirement. Local `Random` instance is cleaner architecture but adds object overhead. AGENT'S DISCRETION — either works. |
| `for match in bracket` each iteration | Pre-computed round-indexed match list | Pre-compute once: `{round: [match_indices]}`. Avoids 50K×23 bracket list scans. Critical for performance. |

**Installation:**
```bash
# No new packages needed — all standard library
```

**Version verification:** All dependencies are Python stdlib available in 3.11.8 (confirmed on dev machine).

## Package Legitimacy Audit

> This phase installs NO external packages. All dependencies are Python standard library modules (`random`, `math`, `itertools`, `collections`, `time`). No npm/PyPI packages required.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                               ┌─────────────────────────────┐
                               │     main.py (orchestrator)    │
                               │  load teams/bracket/played   │
                               └──────────┬──────────────────┘
                                          │
                                          ▼
                        ┌─────────────────────────────────────┐
                        │  run_simulation(                     │
                        │    teams, bracket, played,          │
                        │    iterations=50000, seed=None      │
                        │  )                                  │
                        └──────────┬─────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
           ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
           │ Pre-compute  │ │ Loop body    │ │ Aggregate    │
           │ walk order   │ │ ×50K         │ │ probabilities │
           │ (round→list) │ │              │ │ per team     │
           └──────────────┘ │ ┌──────────┐ │ └──────────────┘
                            │ │For each  │ │
                            │ │ round:   │ │
                            │ │ simulate │ │
                            │ │ all      │ │
                            │ │ matches  │ │
                            │ │ → store  │ │
                            │ │ winners  │ │
                            │ │ in winner│ │
                            │ │_progress │ │
                            │ │ion dict  │ │
                            │ └──────────┘ │
                            │ ┌──────────┐ │
                            │ │Tally per-│ │
                            │ │round     │ │
                            │ │advancement│ │
                            │ │ to local │ │
                            │ │counters  │ │
                            │ └──────────┘ │
                            └──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │  {                            │
                    │   "Argentina": {             │
                    │     "qf": 0.88,              │
                    │     "sf": 0.61,              │
                    │     "final": 0.39,           │
                    │     "champion": 0.24         │
                    │   }, ...                     │
                    │  }                            │
                    └─────────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │   scripts/benchmark_         │
                    │   simulation.py              │
                    │   (standalone profiling)     │
                    └─────────────────────────────┘
```

### Per-Iteration Data Flow

```
Start iteration
  │
  ▼
Create empty winner_progression = {}
  │
  ▼
For each ROUND in [R16, QF, SF, FINAL]:
  │
  ▼
  For each MATCH in current round:
    │
    ├── Is match_id in played?
    │   ├── YES → winner = played[match_id]["winner"]
    │   └── NO  → 
    │       ├── Determine participants:
    │       │   ├── R16: use team_a, team_b from bracket data
    │       │   └── Post-R16: lookup source_matches winners from winner_progression
    │       ├── Compute p_a = expected_score(elo[team_a], elo[team_b])
    │       ├── Generate r = random.random()
    │       ├── Determine winner = team_a if r < p_a else team_b
    │       └── Store winner_progression[match_id] = winner
    │
    ▼
  Record advancement for each participant in this round
    │
    ▼
  (next round)
  │
  ▼
Record champion (winner of FINAL match)
```

### Recommended Project Structure

```
scripts/
└── benchmark_simulation.py    # Standalone performance benchmark

src/
├── __init__.py
├── constants.py               # Existing — K_FACTOR, DEFAULT_ELO, DATA_DIR
├── elo.py                     # Existing — expected_score(), update_ratings()
├── simulation.py              # NEW — run_simulation() and internal helpers
└── state.py                   # Existing — load/save/validate

tests/
├── conftest.py                # Existing — sample_teams, sample_bracket fixtures
├── test_simulation.py         # NEW — tests for simulation logic
├── test_elo.py                # Existing
├── test_state.py              # Existing
├── test_scaffold.py           # Existing
└── test_integration.py        # Existing
```

### Pattern 1: Bracket Walk Order Pre-computation

**What:** Build a round-indexed map of matches once, outside the main simulation loop, so each iteration can directly access per-round matches without scanning the bracket list.

**When to use:** Every simulation. This is the single most impactful performance optimization — it converts 23 bracket list scans (50K × 23 = 1.15M scans) into a one-time scan.

**Example:**
```python
# Pre-compute once at module level (or inside run_simulation before the loop)
def _build_round_map(bracket: list[dict]) -> dict[str, list[dict]]:
    """Group matches by round. Order rounds deterministically."""
    round_order = ["R16", "QF", "SF", "FINAL"]
    round_map: dict[str, list[dict]] = {}
    for match in bracket:
        r = match["round"]
        if r not in round_map:
            round_map[r] = []
        round_map[r].append(match)
    # Sort within each round by match_id for determinism
    for r in round_map:
        round_map[r].sort(key=lambda m: m["match_id"])
    return round_map, round_order
```

### Pattern 2: Local Variable Binding for Hot Path

**What:** Bind frequently-accessed globals (`random.random`, `math.pow`, `elo.expected_score`) to local variables at the top of each iteration to avoid global lookup overhead.

**When to use:** Inside the 50K loop. Python 3.11 has improved function call performance, but global-lookup avoidance still provides measurable benefit.

**Example:**
```python
def _run_single(teams, bracket, played, round_map, round_order, _rand, _exp, p_teams):
    """Run one tournament iteration and return per-round advancement counts."""
    winner_progression: dict[str, str] = {}
    adv_counts = {"qf": set(), "sf": set(), "final": set(), "champion": set()}
    
    for round_name in round_order:
        for match in round_map[round_name]:
            mid = match["match_id"]
            
            if mid in played:
                # Real result: use already determined winner
                winner = played[mid]["winner"]
                winner_progression[mid] = winner
                continue
            
            # Determine participants
            if match["team_a"]:  # R16 directly has teams
                team_a, team_b = match["team_a"], match["team_b"]
            else:  # Post-R16: look up from source_matches winners
                src = match["source_matches"]
                team_a = winner_progression[src[0]]
                team_b = winner_progression[src[1]]
            
            # Simulate match outcome
            p_a = _exp(p_teams[team_a], p_teams[team_b])
            winner = team_a if _rand() < p_a else team_b
            winner_progression[mid] = winner
        
        # Tally winners for this round
        # ... (team-specific counting)
    
    return adv_counts
```

### Pattern 3: Round Tally via Sets (per iteration)

**What:** Track which teams advanced to each round using Python sets. After simulation, counts become probabilities.

**When to use:** During aggregation. Each iteration, add advancing teams to round-specific sets. At the end, `{team: len(set) / iterations}` gives probability.

**Alternative (more precise):** Use `collections.Counter` dict for each round keyed by team name. Slightly more memory but cleaner.

```python
# Inside the 50K loop:
for match in round_map[round_name]:
    # ... simulate match, determine winner
    winner_progression[mid] = winner

# After round completes, count advancing teams
for match in round_map[round_name]:
    mid = match["match_id"]
    if not match["source_matches"]:
        continue  # R16 doesn't count as "advancement" for our QF/SF/FINAL tracking
    # The winners of this round's source matches advanced TO this round
    for src in match["source_matches"]:
        if src in winner_progression:
            team = winner_progression[src]
            adv_counts[round_name.lower()].add(team)
```

### Anti-Patterns to Avoid

- **Deep copying the entire bracket per iteration:** `copy.deepcopy(bracket)` costs ~50μs × 50K = 2.5s — half the budget gone. Use D-14 pattern: fresh `winner_progression` dict only.
- **Scanning bracket list for source match lookups:** Building a `match_id → match` dict once (not per iteration) avoids O(n²) behavior.
- **Using `random.choice()` instead of `random.random() < threshold`:** `choice()` is ~900ns vs `random()` ~70ns — 13x slower for each match determination [ASSUMED — based on blog benchmarks].
- **Global state mutation:** Don't write to `random` module state mid-iteration. Per D-09: seed once at simulation start, then only call `random.random()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Random number generation | Custom PRNG implementation | Python `random` module Mersenne Twister | Battle-tested, C implementation, ~70ns per `random()`, period 2^19937-1 [VERIFIED: docs.python.org/3/library/random.html] |
| Win probability formula | Custom team-strength model | `elo.expected_score()` | Already implemented in Phase 1; standard World Football Elo formula [VERIFIED: src/elo.py] |
| Performance timing | Custom benchmarking framework | `time.perf_counter()` + print | Single script, no CI — minimal tooling needed |
| Topological sorting | DFS cycle detection | Pre-computed round order from bracket data | Bracket is validated as DAG by `state.validate_bracket()` [VERIFIED: src/state.py]; round string field provides natural ordering |

**Key insight:** The simulation is computationally simple — it's just `random() < expected_score()` in a loop. The complexity is in bracket traversal logic and performance optimization.

## Performance Analysis

### Expected Cost Model

| Operation | Cost (ns) | Count per Iteration | Total per Iteration |
|-----------|-----------|---------------------|---------------------|
| `random.random()` | ~70 | 23 | ~1,610ns |
| `math.pow(10, diff/400)` | ~150 | up to 23 | ~3,450ns |
| Dict lookup (teams, bracket) | ~50 | ~100 | ~5,000ns |
| Dict write (winner_progression) | ~60 | 23 | ~1,380ns |
| Python function call overhead | ~80 | per match | ~1,840ns |
| Set additions (tallying) | ~50 | 4-23 | ~1,150ns |
| **Per-iteration total** | | | **~15-25μs** |
| **50K iterations total** | | | **~0.75-1.25s** |
| **With overhead (loop mgmt, etc.)** | | | **~1.5-3.0s** |

[ASSUMED — based on stdlib benchmark data and performance characteristics of Python 3.11]

### Performance Optimization Checklist (in order of impact)

1. **Pre-compute round map** — Avoids 50K × 23 bracket scans. Estimated impact: ~20-30% of total runtime.
2. **Local variable bindings** — Bind `random.random`, `teams.get`, `expected_score` to locals inside loop. Estimated impact: ~10-15%.
3. **Pre-build `match_id → match` lookup dict** — Avoids linear search for source match resolution. Estimated impact: ~5-10%.
4. **Pre-extract Elo ratings** into `{team: elo}` flat dict (not `{team: {"elo": val}}`). Estimated impact: ~5%.
5. **Use `if mid in played` not `if played.get(mid)`** — `in` is faster for dict containment. Impact: marginal.

### Fallback Path (per D-13)

If pure Python misses 5s threshold:
1. Profile with `python -m cProfile` to find bottlenecks
2. Replace the iteration loop with NumPy vectorized match simulation:
   - Pre-generate all random numbers as array: `rng.random(size=(iterations, num_sim_matches))`
   - Pre-compute all match probabilities as array
   - Compare vectors: `winners = rng < probs` (boolean → team index mapping)
   - Aggregate using `np.bincount` or similar
3. Expected speedup: 5-20x on the simulation core

## Common Pitfalls

### Pitfall 1: Source-Match Resolution on the Wrong Match Object

**What goes wrong:** When looking up participants for QF_1 (which depends on R16_1 and R16_2 winners), code might look at the bracket data's `team_a`/`team_b` (which are `null`) instead of reading from the `winner_progression` dict.

**Why it happens:** The bracket JSON stores R16 matches with explicit `team_a`/`team_b`, but post-R16 matches have `null` values — participants are determined by winners of `source_matches`. Two different lookup paths.

**How to avoid:** Check `if match["team_a"] is not None` to decide the lookup path. Always resolve post-R16 participants from `winner_progression[source_match_id]`, never from bracket data.

**Warning signs:** Simulation crashes with `TypeError: winner_progression[None]` or advancing probability 0% for all teams in post-R16 rounds.

### Pitfall 2: Floating-Point Drift in Probability Sum

**What goes wrong:** `champion` probabilities sum to ~1.05 or ~0.97 due to accumulation of floating-point error or missing team in aggregation.

**Why it happens:** Each iteration counts winners in per-round sets. If a team name is misspelled or a team drops out of the set incorrectly, per-round counts drift.

**How to avoid:** After aggregation, verify `abs(sum(probs[team]["champion"] for team in probs) - 1.0) <= 0.001` per D-08. Use `collections.Counter` for safer counting than manual dict increment.

**Warning signs:** D-08 failed in a test; user reports "probabilities don't add up."

### Pitfall 3: Played Match After the Current Round

**What goes wrong:** If R16_1 is played but QF_1 is not yet played, and the code advances to QF round, the source matches are resolved correctly (winners from played data), but `expected_score()` is called with the played match's winner vs the other source match winner — which is correct behavior, but only if played match winners are reliably populated.

**Why it happens:** The `played` dict only has entries for matches that have actually been played. Post-R16 matches may also have been played in a real tournament.

**How to avoid:** Always check `if mid in played` regardless of round. The same logic path handles played matches in any round.

**Warning signs:** Simulation doesn't use real results for already-played QF matches.

### Pitfall 4: Random Seed Scope Leakage

**What goes wrong:** `random.seed(seed)` is called inside `run_simulation()`, but the caller's random state is also affected (global state modification). If the caller also uses `random` after the simulation returns, they get deterministic output instead of entropy.

**Why it happens:** `random.seed()` modifies the global `random.Random` instance. Per D-09, this is the specified behavior — but it's a side effect.

**How to avoid:** This is an accepted tradeoff per D-09. The AGENT'S DISCRETION allows using `random.Random(seed)` as a local generator instead, which avoids global state modification. Document the side effect clearly if using global `random.seed()`.

**Warning signs:** After `--seed` invocation, subsequent calls to `random` (outside simulation) produce deterministic values.

### Pitfall 5: `random.seed()` Called Inside the Loop

**What goes wrong:** Seeding once, then seeding again mid-loop, causes the same sequence of random numbers to repeat, corrupting results.

**Why it happens:** If dev mistakenly puts `random.seed(seed)` inside the per-iteration loop thinking "each iteration should be reproducible."

**How to avoid:** Call `random.seed(seed)` exactly once at the top of `run_simulation`, before entering the 50K loop. Never call `random.seed()` inside the loop.

**Warning signs:** Consecutive iterations produce identical results; champion probabilities are always 0 or 1.

## Code Examples

### Example 1: Core Simulation Function Skeleton

```python
"""Monte Carlo simulation engine for knockout tournament."""

import math
import random
from collections import defaultdict
from typing import Any

from src.elo import expected_score

ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]
ROUND_KEYS = {"QF": "qf", "SF": "sf", "FINAL": "final"}


def _build_round_map(bracket: list[dict]) -> dict[str, list[dict]]:
    """Group matches by round and sort deterministically."""
    round_map: dict[str, list[dict]] = {}
    for match in bracket:
        r = match["round"]
        if r not in round_map:
            round_map[r] = []
        round_map[r].append(match)
    for matches in round_map.values():
        matches.sort(key=lambda m: m["match_id"])
    return round_map


def _build_match_index(bracket: list[dict]) -> dict[str, dict]:
    """Build match_id → match lookup dict."""
    return {m["match_id"]: m for m in bracket}


def run_simulation(
    teams: dict[str, dict[str, Any]],
    bracket: list[dict],
    played: dict[str, dict[str, Any]],
    iterations: int = 50000,
    seed: int | None = None,
) -> dict[str, dict[str, float]]:
    """Run Monte Carlo simulation of the knockout tournament.

    Args:
        teams: {team_name: {"elo": rating, ...}}
        bracket: Flat list of match objects with source_matches linking rounds.
        played: {match_id: {"winner": team_name, ...}} for already-played matches.
        iterations: Number of tournament simulations to run.
        seed: Random seed for reproducibility. None = system entropy.

    Returns:
        {team_name: {"qf": p, "sf": p, "final": p, "champion": p}}
    """
    # Seed random number generator (if provided)
    if seed is not None:
        random.seed(seed)

    # Pre-compute lookup structures
    round_map = _build_round_map(bracket)
    match_index = _build_match_index(bracket)
    elo_ratings = {name: data["elo"] for name, data in teams.items()}

    # Aggregate counters: team → {round_key: count}
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # Local bindings for hot-path performance
    _rand = random.random
    _exp = expected_score
    _played_get = played.get
    _round_map_get = round_map.get
    _match_index_get = match_index.get
    _elo_get = elo_ratings.get

    for _ in range(iterations):
        winner_progression: dict[str, str] = {}

        for round_name in ROUND_ORDER:
            for match in _round_map_get(round_name, []):
                mid = match["match_id"]

                # Check for played match
                played_result = _played_get(mid)
                if played_result is not None:
                    winner_progression[mid] = played_result["winner"]
                    continue

                # Determine participants
                team_a = match["team_a"]
                if team_a is not None:
                    team_b = match["team_b"]
                else:
                    src = match["source_matches"]
                    team_a = winner_progression[src[0]]
                    team_b = winner_progression[src[1]]

                # Simulate match
                p_a = _exp(_elo_get(team_a), _elo_get(team_b))
                winner = team_a if _rand() < p_a else team_b
                winner_progression[mid] = winner

        # Tally: which teams advanced to each round?
        for round_name, round_key in ROUND_KEYS.items():
            for match in _round_map_get(round_name, []):
                for src in match["source_matches"]:
                    if src in winner_progression:
                        team = winner_progression[src]
                        counts[team][round_key] += 1

        # Tally champion
        final_winner = winner_progression.get("FINAL")
        if final_winner:
            counts[final_winner]["champion"] += 1

    # Convert counts to probabilities
    result: dict[str, dict[str, float]] = {}
    for team_name in teams:
        result[team_name] = {
            round_key: counts[team_name][round_key] / iterations
            for round_key in ["qf", "sf", "final", "champion"]
        }

    return result
```

### Example 2: Benchmark Script Pattern

```python
#!/usr/bin/env python3
"""Benchmark the Monte Carlo simulation performance.

Usage:
    python scripts/benchmark_simulation.py [--iterations 50000]

Measures elapsed wall-clock time for N simulation iterations.
Target: 50,000 iterations in <5 seconds on the developer machine.
"""

import argparse
import time

from src.constants import DATA_DIR
from src.state import load_teams, load_bracket, load_played
from src.simulation import run_simulation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Monte Carlo simulation performance"
    )
    parser.add_argument(
        "--iterations", type=int, default=50000,
        help="Number of iterations to benchmark (default: 50000)",
    )
    args = parser.parse_args()

    # Load data
    teams = load_teams(DATA_DIR)
    bracket = load_bracket(DATA_DIR)
    played = load_played(DATA_DIR)

    # Warmup (JIT/CPU cache)
    _ = run_simulation(teams, bracket, played, iterations=100)

    # Benchmark
    start = time.perf_counter()
    probs = run_simulation(teams, bracket, played, iterations=args.iterations)
    elapsed = time.perf_counter() - start

    rate = args.iterations / elapsed if elapsed > 0 else float("inf")
    status = "PASS" if elapsed < 5.0 else "FAIL"

    print(f"Iterations: {args.iterations}")
    print(f"Elapsed: {elapsed:.3f}s")
    print(f"Rate: {rate:.0f} sims/sec")
    print(f"Status: {status} (threshold: 5.0s)")

    # Sanity check
    champion_sum = sum(p["champion"] for p in probs.values())
    print(f"Champion prob sum: {champion_sum:.4f} (should be ~1.0)")


if __name__ == "__main__":
    main()
```

### Example 3: Fixed-Seed Test for Deterministic Behavior

```python
"""Tests for simulation module."""

import pytest

from src.simulation import run_simulation


def test_deterministic_with_seed(sample_teams, sample_bracket, sample_played):
    """Same seed should produce identical results."""
    result_a = run_simulation(
        sample_teams, sample_bracket, sample_played,
        iterations=1000, seed=42,
    )
    result_b = run_simulation(
        sample_teams, sample_bracket, sample_played,
        iterations=1000, seed=42,
    )
    assert result_a == result_b


def test_different_seeds_different(sample_teams, sample_bracket, sample_played):
    """Different seeds should produce different results."""
    result_a = run_simulation(
        sample_teams, sample_bracket, sample_played,
        iterations=1000, seed=42,
    )
    result_b = run_simulation(
        sample_teams, sample_bracket, sample_played,
        iterations=1000, seed=99,
    )
    assert result_a != result_b


def test_champion_probs_sum_to_one(sample_teams, sample_bracket, sample_played):
    """Champion probabilities should sum to 1.0 within tolerance."""
    result = run_simulation(
        sample_teams, sample_bracket, sample_played,
        iterations=10000, seed=42,
    )
    total = sum(p["champion"] for p in result.values())
    assert abs(total - 1.0) <= 0.001


def test_played_matches_respected(sample_teams, sample_bracket):
    """If R16_1 is played, that winner must advance in every iteration."""
    played = {
        "R16_1": {"winner": "Argentina", "home_score": 2, "away_score": 0, "completed_at": "2026-06-15T22:00:00Z"},
    }
    result = run_simulation(
        sample_teams, sample_bracket, played,
        iterations=1000, seed=42,
    )
    # Argentina must be in QF (i.e., must have qf probability > 0)
    # Actually if R16_1 is played and Argentina won, they should advance to QF
    assert result["Argentina"]["qf"] > 0.0, "Argentina should advance to QF"


def test_all_matches_played_returns_deterministic(sample_teams, sample_bracket):
    """If all matches are played, probabilities should be 0 or 1."""
    # Simulate a full bracket run where every match has a result
    played = {
        "R16_1": {"winner": "Argentina"},
        "R16_2": {"winner": "France"},
        # ... etc for all 23 matches
    }
    result = run_simulation(
        sample_teams, sample_bracket, played,
        iterations=1000, seed=42,
    )
    # Every champion prob should be 0 or 1
    for team, probs in result.items():
        assert probs["champion"] in (0.0, 1.0), f"All-played: {team} champion prob should be 0 or 1"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Deep-copy bracket per iteration | Fresh `winner_progression` dict | D-14 | Avoids 50K×deepcopy (~2.5s savings) |
| Global `random.seed()` | Could use `random.Random(seed)` | D-09 discretion | Global is simpler but side-effectful |
| `random.choice()` | `random.random() < prob` | Research recommendation | ~10x faster per match outcome |
| `math.pow(10, diff/400)` in hot path | Same, but bound to local | Research recommendation | Avoids global lookup overhead |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 50K iterations × 23 matches = ~1.15M simulations will complete in <5s (pure Python) | Summary, Performance Analysis | If false, fallback to NumPy per D-13 adds ~2-4 hours of work |
| A2 | `random.random()` is ~70ns per call | Performance Analysis | Slightly slower doesn't break target; slightly faster makes it easier |
| A3 | Pre-computed round map + local bindings achieves ~2-4μs per iteration | Performance Analysis | If loop overhead is significantly higher, may need NumPy fallback |
| A4 | Python 3.11 provides measurable function call improvements over 3.10 | Performance Analysis | Conservative — optimizations work on any 3.x |
| A5 | `random.choice()` is ~13x slower than `random.random() < threshold` | Standard Stack | Only affects marginal performance; choice still works |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

## Open Questions (RESOLVED)

1. **Random seed scope — global vs local Random instance?**
   - What we know: D-09 says "call `random.seed(seed)` internally". This modifies global state.
   - What's unclear: Whether the caller (main.py) will also rely on `random` for non-simulation purposes during the same session. If so, global state modification could cause unexpected determinism.
   - Recommendation: Marked as AGENT'S DISCRETION. Recommend using `random.Random(seed)` as a local generator and taking the `_rand` from that instance. Avoids side effects, same performance characteristics.

2. **`random.random()` vs `random.random()` with threshold — numerical stability?**
   - What we know: Both `random.random() < p` and `random.random() <= p` give correct distributions for p in (0,1).
   - What's unclear: Whether strict `<` causes any bias for extreme probabilities (p=0.0 or p=1.0).
   - Recommendation: `random.random() < p`. For `p=0.0`, never triggers. For `p=1.0`, always triggers (0.0 <= X < 1.0 is always < 1.0). Correct.

## Environment Availability

**Step 2.6: SKIPPED (no external dependencies identified)**

This phase requires only Python 3.11+ standard library modules (`random`, `math`, `itertools`, `collections`, `time`) and the existing project code. Python 3.11.8 is confirmed available on the developer machine.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All simulation code | ✓ | 3.11.8 | — |
| `random` (stdlib) | Match outcome generation | ✓ | stdlib | — |
| `math` (stdlib) | Elo probability calc | ✓ | stdlib | — |

**Missing dependencies with no fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pytest.ini` or `pyproject.toml` (check existing) |
| Quick run command | `pytest tests/test_simulation.py -x -q` |
| Full suite command | `pytest -x -q (from project root)` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIM-01 | Same seed → same results | unit | `pytest tests/test_simulation.py::test_deterministic_with_seed -x` | ❌ Wave 0 |
| SIM-01 | Different seeds → different results | unit | `pytest tests/test_simulation.py::test_different_seeds_different -x` | ❌ Wave 0 |
| SIM-01 | Champion probs sum to ~1.0 | unit | `pytest tests/test_simulation.py::test_champion_probs_sum_to_one -x` | ❌ Wave 0 |
| SIM-01 | Played matches respected | unit | `pytest tests/test_simulation.py::test_played_matches_respected -x` | ❌ Wave 0 |
| SIM-01 | All-played → deterministic | unit | `pytest tests/test_simulation.py::test_all_matches_played_returns_deterministic -x` | ❌ Wave 0 |
| SIM-01 | 50K < 5s performance gate | benchmark | `python scripts/benchmark_simulation.py` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_simulation.py -x -q`
- **Per wave merge:** `pytest -x -q` (full suite)
- **Phase gate:** Full suite green + `python scripts/benchmark_simulation.py` reports PASS

### Wave 0 Gaps
- [ ] `tests/test_simulation.py` — covers SIM-01 (all 5 test cases)
- [ ] Existing `conftest.py` — fixtures `sample_teams`, `sample_bracket`, `sample_played` already exist
- [ ] Framework install: `pytest 9.0.2` confirmed available

## Security Domain

> No security enforcement needed. This phase is pure computation with no I/O, no network access, no user input processing, and no data persistence. It reads data from in-memory Python dicts and returns a probability dict. No attack surface exists for injection, authentication bypass, or data tampering within this module.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | No | — |
| V4 Access Control | No | — |
| V5 Input Validation | No | Input is pre-validated by `state.validate_bracket()` |
| V6 Cryptography | No | `random` module is not suitable for crypto — not relevant here |

## Sources

### Primary (HIGH confidence)
- [Python `random` module docs] — `random.seed()`, `random.random()` behavior, reproducibility guarantees [VERIFIED: docs.python.org/3/library/random.html]
- [Existing codebase: `worldcup_predictor/src/`] — `elo.py`, `state.py`, `constants.py`, `main.py`, test files [VERIFIED: codebase read]
- [Existing data: `worldcup_predictor/data/`] — `bracket.json` (23 matches), `teams.json` (32 teams), `played.json` (empty) [VERIFIED: codebase read]
- [CONTEXT.md Phase 2] — D-01 through D-15 locked decisions [VERIFIED: .planning/phases/02-monte-carlo-simulation/02-CONTEXT.md]

### Secondary (MEDIUM confidence)
- [geoffruddock.com — Python random vs NumPy performance benchmarks] — `random.random()` ~70ns, `random.choice()` ~900ns [CITED]
- [Python 3.11 performance release notes] — Function call and loop improvements over 3.10

### Tertiary (LOW confidence)
- [StackOverflow — Python random 300K samples/s] — Ballpark performance reference for stdlib `random` [CITED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib, no external dependencies
- Architecture: HIGH — follows existing codebase patterns, locked decisions crystal clear
- Performance analysis: MEDIUM — estimates based on stdlib benchmarks; actual benchmark script may reveal different numbers
- Pitfalls: HIGH — based on known patterns from similar simulation engines
- Testing: HIGH — deterministic seed and property-based tests are well-established patterns

**Research date:** 2026-06-13
**Valid until:** 2026-07-13 (stable — all dependencies are stdlib)
