# Architecture Patterns: Real-Time Tournament Simulation Systems

**Domain:** Live football tournament prediction (World Cup knockout stage)
**Researched:** 2026-06-13
**Mode:** Ecosystem (architecture dimension)
**Overall confidence:** HIGH

## Executive Summary

Real-time tournament simulation systems follow a **pipelines-with-aggregation** architecture: data flows linearly through five core stages — *Data Ingestion → Rating Engine → Match Model → Simulation Engine → Output Layer* — with a **State/Persistence Layer** providing durability and a **Main Loop** orchestrating the cycle. The ecosystem splits into two clusters: (1) **production-scale streaming systems** built on Kafka/Flink/Druid (overkill for a CLI tool), and (2) **modular Python CLI systems** that use flat JSON-file state, pure-function modules, and a synchronous poll-process-simulate loop. The latter is the correct pattern for this project.

Every similar project studied (goal-analytics, world-cup-2026-forecast, hrzn/soccer-predictions, mundial-monte, boxing-montecarlo, chessswissprediction) converges on the same five-layer decomposition. Key variations appear in *bracket data structure* (flat list vs. nested tree), *simulation approach* (vectorized numpy vs. iterative Python), and *match model sophistication* (thin Elo formula vs. Poisson/Dixon-Coles). For a knockout-only MVP with 50,000 simulations, iterative Python is sufficient and avoids the numpy dependency.

---

## Key Architecture Patterns

### Pattern 1: Poll-Detect-Update-Simulate-Output Loop (Dominant)

Every real-time sports predictor follows this cycle:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MAIN LOOP (Orchestrator)                     │
│                                                                     │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐   │
│   │  POLL    │ → │ DETECT   │ → │ UPDATE   │ → │ SIMULATE     │   │
│   │  API     │   │ new      │   │ Elo      │   │ Monte Carlo  │   │
│   │          │   │ matches  │   │ ratings  │   │ 50,000x      │   │
│   └──────────┘   └──────────┘   └──────────┘   └──────┬───────┘   │
│                                                        │           │
│                                                        ▼           │
│                                                  ┌──────────────┐  │
│                                                  │  OUTPUT      │  │
│                                                  │  formatted   │  │
│                                                  │  console     │  │
│                                                  └──────────────┘  │
│                                                                     │
│                                              ┌──────────────────┐   │
│                                              │  SLEEP 60s       │   │
│                                              └──────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

**Found in:** goal-analytics, mundial-monte, world-cup-2026-forecast, the Super Bowl Elo model, all NCAA March Madness simulators.

**Key insight:** The loop is *event-triggered* — it does nothing until the API returns a new finished match. Between matches, the system idles (sleeping). This is the correct pattern for a low-rate API (10 req/min).

---

### Pattern 2: Pure-Function Module Decomposition (Standard for Python CLI)

All studied Python CLI projects decompose into leaf modules with **no circular dependencies**:

```
main.py (orchestrator)  ──────┬──────┬──────┬──────┬──────┐
                              │      │      │      │      │
                             ┌▼┐  ┌──▼──┐ ┌▼──┐ ┌▼──┐ ┌──▼───┐
                             │S│  │ Elo │ │Si-│ │Fe-│ │Out-  │
                             │t│  │ Ra- │ │mu-│ │tc-│ │put   │
                             │a│  │ ting│ │la-│ │her│ │For-  │
                             │t│  │ En- │ │tor│ │   │ │mat-  │
                             │e│  │ gine│ │   │ │   │ │ter   │
                             └─┘  └─────┘ └───┘ └───┘ └──────┘
```

Dependency direction: **main.py → every other module**. Leaf modules have zero inter-dependencies.

**Found in:** goal-analytics, chessswissprediction, world-cup-2026-forecast, hrzn/soccer-predictions, boxing-montecarlo, jordydavelaar/MarchMadSim.

---

### Pattern 3: File-Based State as "Database" (Standard for MVP)

The ecosystem overwhelmingly uses flat files for state in non-production systems:

| Data | Storage | Frequency |
|------|---------|-----------|
| Team Elo ratings | Single JSON/CSV file | Rewritten on each Elo update |
| Played match records | Append-only JSON/CSV | Grows over tournament |
| Bracket structure | Static JSON/CSV | Read-only at startup |
| Simulation results | JSON/CSV (per cycle) | Overwritten each cycle |

**Atomic write pattern** (used by every project): Write to temp file, then `os.rename()` to target path. Prevents corruption on crash mid-write.

---

## Five-Layer Architecture (Detailed)

### Layer 1: Data Ingestion (Fetcher)

**Responsibility:** Poll external API, parse responses, filter new matches, map external IDs to internal IDs.

**Ecosystem patterns:**
- **Polling** — synchronous HTTP GET with retry/backoff (retry 3×, exponential: 1s, 2s, 4s)
- **Rate limiting** — free tier typically 10 req/min; poll every 60s stays safe
- **Response filtering** — filter by `status == "FINISHED"`; track last-known match IDs in memory
- **ID mapping** — external API numeric IDs → internal bracket match IDs via static mapping file
- **Team name normalisation** — API may return "USA" while internal uses "United States"; mapping table needed

**Used by:** Football-Data.org API consumers, eloratings.net scrapers, Sportradar API consumers.

**Build order note:** Can be built after State layer (needs played.json to filter new matches).

---

### Layer 2: Rating Engine (Elo)

**Responsibility:** Maintain numeric team strength ratings; update after every real match.

**Ecosystem patterns:**
- **Standard Elo formula** (`E = 1 / (1 + 10^((Rb - Ra) / 400))`) — universal across all studied projects
- **K-factor** — typically 32 for knockouts; some projects scale by margin of victory
- **Rating range** — World Cup teams typically cluster 1500–2100
- **No home advantage** in neutral-site knockout matches (unlike league models that add +55–100 Elo)
- **Pure function** — `update_ratings(team_a, team_b, winner, elos_dict) → new_elos_dict` — no side effects

**Variants observed:**
- Some projects use composite ratings (Elo + FIFA rank weighted)
- Some use surface-specific or confederation-adjusted Elo
- Some add margin-of-victory scaling (`K × G(goal_diff)`)
- For World Cup knockouts, draws don't exist (penalties) → simplifies to binary outcome

**Build order note:** Pure math, no dependencies. Can be built first or second.

---

### Layer 3: Match Model (Win Probability)

**Responsibility:** Convert rating difference into win probability for a single match.

**Ecosystem patterns:**
- **Elo win probability** — `P(A) = 1 / (1 + 10^((EloB - EloA) / 400))` — the simplest and most common
- **Poisson goal model** — `λ_home = avg_goals × 10^(Δelo/800)`, then sample from Poisson — used for scoreline distributions (needed for group stage GD tiebreakers)
- **Bivariate Poisson/Dixon-Coles** — for group stage with scoreline correlation — *overkill for knockout-only MVP*
- **Calibrated logistic** — some projects fit historical data to calibrate Elo diff → win prob

**For knockout-only MVP:** The thin Elo formula is sufficient. Poisson models add complexity without benefit when draws don't exist.

---

### Layer 4: Simulation Engine (Monte Carlo)

**Responsibility:** Traverse the tournament bracket thousands of times, aggregating results into a probability distribution.

#### Bracket Data Structures

The ecosystem uses three strategies:

**Strategy A: Flat ordered list** (simplest, most common for CLI projects)
```python
# Array-of-rounds: each round is a list of matches
bracket = [
    # Round of 16
    [{"team_a": "Arg", "team_b": "Den", "winner": None}, ...],
    # Quarterfinals
    [{"team_a": None, "team_b": None, "winner": None, "source": [0, 1]}, ...],
    # Semifinals
    [{"team_a": None, "team_b": None, "winner": None, "source": [0, 1]}, ...],
    # Final
    [{"team_a": None, "team_b": None, "winner": None, "source": [0, 1]}],
]
```
**Used by:** tournament_bracketool, several NCAA simulators.
**Pros:** Simple traversal (for round → for match), easy to serialize.
**Cons:** Needs source-match resolution for later rounds.

**Strategy B: Nested dict tree** (more explicit, used by several projects)
```json
{
  "round_of_16": [
    {"match_id": "R16_1", "team_a": "Arg", "team_b": "Den", "winner": null},
    ...
  ],
  "quarterfinals": [
    {"match_id": "QF_1", "team_a": null, "team_b": null, "winner": null,
     "source_matches": ["R16_1", "R16_2"]},
    ...
  ]
}
```
**Used by:** The project's existing design docs (SOTs).
**Pros:** Self-documenting structure, explicit source links.
**Cons:** Slightly more complex resolution logic.

**Strategy C: Array-of-rounds with null slots** (compact)
```python
# n_teams slots per round; null = not yet determined
rounds = [
    ["Arg", "Den", "Fra", "Pol", ...],  # R16
    [None, None, None, None],            # QF
    [None, None],                        # SF
    [None],                              # Final
]
```
**Used by:** Several academic/notebook implementations.
**Pros:** Extremely fast traversal, no dict lookups.
**Cons:** Loses match metadata (scores, etc.).

#### Simulation Approaches

**Approach 1: Iterative (Python loop)** — *Recommended for MVP*
```python
def run_monte_carlo(elos, bracket, played_set, n=50000):
    wins = Counter()
    for _ in range(n):
        # Copy bracket template (deep copy or rebuild)
        b = deepcopy(bracket)  # or rebuild_flat()

        # Play each round bottom-up
        for round_idx, round_matches in enumerate(b):
            for match in round_matches:
                if match["match_id"] in played_set:
                    continue  # use real result
                p = elo_win_prob(elos[match["team_a"]], elos[match["team_b"]])
                match["winner"] = match["team_a"] if random() < p else match["team_b"]

        # Propagate winners through bracket...
        champion = resolve_bracket(b)
        wins[champion] += 1

    return {team: count/n for team, count in wins.items()}
```
**Performance:** ~750k match simulations (15 matches × 50k sims) in ~2-5s in CPython. Acceptable.

**Approach 2: Vectorized (numpy)** — *Optimization option*
```python
# Pre-compute all match probability matrices
# Run all simulations as array operations
```
**Used by:** steodose/world-cup-2026 (50k sims in <1s).
**Tradeoff:** Adds numpy dependency; more complex code. **Not needed for 15-match knockout.**

**Approach 3: Pre-computed tree (Phylourny algorithm)** — *Academic*
- Computes exact win probabilities via bottom-up tree traversal using matrix multiplication
- O(n²) vs O(n × sims) for Monte Carlo
- **Overkill for 15-match tree with 50k sims**

#### Performance Characteristics (from ecosystem data)

| Approach | 50k sims (15 matches) | Dependency | Complexity |
|----------|----------------------|------------|------------|
| Iterative Python | ~2-5s | None | Low |
| Vectorized numpy | ~0.1-0.5s | numpy | Medium |
| Parallel (multiprocessing) | ~0.5-1s | multiprocessing | Medium |
| Pre-computed tree | ~0.01s | numpy/scipy | High |

**Verdict:** Iterative Python is correct for MVP. The bottleneck is API polling (60s), not simulation speed. Optimization can wait.

---

### Layer 5: Output Layer

**Responsibility:** Format and display results. Console-only for this project.

**Ecosystem patterns:**
- **Timestamped header** — `[2026-06-13 18:30:00]`
- **Probability table** — top 5-10 teams with formatted percentages
- **Delta indicators** — ▲/▼ arrows showing change from previous cycle
- **ANSI colors** — green for increases, red for decreases, yellow for new
- **Match detection log** — "New match: Argentina 2-1 Denmark → Elo updated"
- **Minimalist vs. detailed** — some projects print full table, some print only deltas

**Found in:** goal-analytics (CLI mode), world-cup-2026-forecast, hrzn/soccer-predictions.

---

## Data Flow

### Primary Path (Match Detection → Probability Update)

```
                         ┌──────────────────┐
                         │ External API      │
                         │ Football-Data.org │
                         └────────┬─────────┘
                                  │ HTTP GET (every 60s)
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ FETCHER                                                         │
│ 1. GET /v4/matches?competition=WC                               │
│ 2. Parse JSON response                                          │
│ 3. Filter: status == "FINISHED" + id ∉ last_known_ids          │
│ 4. Map external IDs → internal match_ids via api_id_mapping     │
│ 5. Return: list of new MatchResult dicts                        │
└────────────────────────────────┬────────────────────────────────┘
                                 │ new matches list
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ STATE (read)                                                    │
│ - Load played.json → played_set, played_details                  │
│ - Load teams.json → elos_dict                                   │
└────────────────────────────────┬────────────────────────────────┘
                                 │ elos + played_set
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ ELO ENGINE                                                      │
│ For each new match:                                             │
│ 1. Compute expected_scores from current Elo ratings             │
│ 2. Calculate K-factor × (actual - expected) for winner/loser    │
│ 3. Return: updated elos_dict                                    │
└────────────────────────────────┬────────────────────────────────┘
                                 │ updated elos
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ STATE (write)                                                   │
│ - Save teams.json (atomic write)                                │
│ - Append to played.json (atomic write)                          │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ SIMULATION ENGINE                                               │
│ 1. Copy bracket template                                        │
│ 2. For 50,000 iterations:                                       │
│    a. For each unplayed match, sample winner via Elo prob       │
│    b. Propagate winners through bracket                         │
│    c. Record champion                                           │
│ 3. Aggregate → {team: win_count / 50000}                        │
│ 4. Return: probabilities dict                                   │
└────────────────────────────────┬────────────────────────────────┘
                                 │ probabilities
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ OUTPUT FORMATTER                                                │
│ 1. Compare with previous probabilities → compute deltas         │
│ 2. Format table: rank | team | prob% | Δ | bar chart            │
│ 3. Print to stdout with ANSI colors                             │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                          ╔══════════════╗
                          ║   CONSOLE    ║
                          ╚══════════════╝
                                 │
                                 ▼
                       time.sleep(60)
                                 │
                                 ▼
                       ┌──────────────────┐
                       │ Loop back to POLL │
                       └──────────────────┘
```

### Startup Flow

```
1. STATE.load_teams() → elos_dict
2. STATE.load_bracket() → bracket_structure
3. STATE.load_played_matches() → played_set, played_details
4. Build last_known_match_ids from played_set keys
5. SIMULATOR.run_monte_carlo(elos, bracket, played_set, 50000) → probs
6. OUTPUT.print_header() + OUTPUT.print_probabilities(probs)
7. Enter main loop (POLL → ...)
```

### Shutdown Flow

```
1. KeyboardInterrupt caught
2. STATE.save_teams(elos)    # ensure latest state on disk
3. STATE.save_played_matches(played_details)
4. SIMULATOR.run_monte_carlo(elos, bracket, played_set, 50000) → final_probs
5. OUTPUT.print_probabilities(final_probs) with "FINAL" header
6. sys.exit(0)
```

---

## Component Boundaries

| Component | Responsibility | Input | Output | Depends On |
|-----------|----------------|-------|--------|------------|
| **Main Loop** (`main.py`) | Infinite poll-detect-update-simulate-output cycle; graceful shutdown | CLI args, env vars | Console output | All modules |
| **Fetcher** (`fetcher.py`) | HTTP GET, parse, filter new matches, ID mapping | API response, last_known_ids | List[MatchResult] | `requests`, `state` (mapping) |
| **State Manager** (`state.py`) | Load/save all JSON files; atomic writes | File paths, data dicts | Data dicts | `json`, `os` |
| **Elo Engine** (`elo.py`) | Compute expected scores; update ratings | Teams dict, MatchResult | Updated teams dict | None (pure math) |
| **Simulator** (`simulator.py`) | Match simulation, bracket traversal, Monte Carlo aggregation | Elos dict, bracket, played_set, n | {team: probability} | `random` |
| **Output** (`output.py`) | Console formatting, ANSI colors, delta computation | Probabilities, deltas, timestamp | stdout | `sys` |
| **Constants** (`constants.py`) | Tunable parameters | None (module-level) | Constants | None |

### Dependency Graph

```
main.py
  ├── fetcher.py → requests, state.py (for mapping)
  ├── state.py → json, os
  ├── elo.py → (none)
  ├── simulator.py → random
  └── output.py → sys

No circular dependencies. All leaf modules are independent.
```

---

## Architectural Decisions (from Ecosystem Evidence)

### Decision 1: JSON File Persistence (not database)

**Evidence:** Every studied CLI project uses JSON or CSV files. goal-analytics uses JSON. world-cup-2026 uses CSV. hrzn/soccer-predictions uses CSV snapshots. chessswissprediction uses CSV.

**Why it works:** 32 teams × 15 matches = tiny data volume. JSON is human-readable, debuggable, and requires zero infrastructure.

**Atomic write recommendation:** Write to `data/teams.json.tmp`, then `os.rename()` to `data/teams.json`. This prevents corruption if the process crashes mid-write.

### Decision 2: Single-Threaded Synchronous (not asyncio/multiprocessing)

**Evidence:** The poll interval is 60s (API rate limit). Even with 50k sims taking ~2-5s, the CPU is idle ~90% of the time. No project in the "simple CLI" cluster uses asyncio or multiprocessing for the core loop.

**Performance ceiling:** 50k simulations of a 15-match knockout bracket in pure Python: ~2-5s. This leaves ~55s of idle time per cycle. The bottleneck is the API, not the CPU.

### Decision 3: Separated Match Model from Simulation Engine

**Evidence:** Projects that separate the match probability model from the simulation engine are more maintainable and testable. The match model is a pure function (`f(elo_a, elo_b) → probability`). The simulation engine is a pure function (`f(elos, bracket, model_fn, n) → {team: prob}`).

**Why it matters:** You can swap the match model (Elo → Poisson → ML) without touching the simulation engine. This is the single most important architectural decision for future extensibility.

### Decision 4: Bracket as Data, Not Code

**Evidence:** The bracket structure should be a data file (JSON), not embedded in Python code. This allows updating the bracket without code changes and makes the bracket inspectable/debuggable.

**How it works in ecosystem:** `data/bracket.json` is loaded at startup. The simulator reads it as a structure and traverses it programmatically. No hardcoded matchups in Python code.

---

## Bracket Traversal Algorithm (Ecosystem Consensus)

The standard algorithm for simulating a single knockout tournament:

```
function simulate_single_tournament(elos, bracket, played_set, model_fn):
    # Work bottom-up through rounds
    for round_matches in bracket.rounds:
        for match in round_matches:
            if match.id in played_set:
                # Use real result
                continue  # winner already set
            else:
                # Simulate based on Elo
                p = model_fn(elos[match.team_a], elos[match.team_b])
                if random() < p:
                    match.winner = match.team_a
                else:
                    match.winner = match.team_b

    # Champion is the winner of the final
    return bracket.rounds[-1][0].winner
```

**Key insight:** Later round matches get their participants from earlier round winners. The bracket structure must encode this linkage (e.g., `source_matches` array or positional ordering).

**Flat list approach** (alternative):
```python
def simulate_single_tournament_flat(teams_in_order, elos, model_fn):
    """teams_in_order: ordered list of R16 match participants"""
    round_teams = teams_in_order[:]  # copy
    while len(round_teams) > 1:
        next_round = []
        for i in range(0, len(round_teams), 2):
            a, b = round_teams[i], round_teams[i+1]
            p = model_fn(elos[a], elos[b])
            next_round.append(a if random() < p else b)
        round_teams = next_round
    return round_teams[0]
```

**Speed comparison:** The flat approach is ~2× faster (no dict lookups for match metadata). For 50k sims × 15 matches, the difference is ~1-2 seconds — negligible.

---

## Anti-Patterns Observed in Ecosystem

### Anti-Pattern 1: Deep Copy in Inner Simulation Loop

**What:** `b = deepcopy(bracket)` inside the `for _ in range(50000)` loop.
**Why bad:** `deepcopy` is ~10-100× slower than rebuilding a flat list.
**Instead:** Either (a) rebuild a flat team list each iteration, or (b) shallow-copy the bracket template and only overwrite winner fields.

### Anti-Pattern 2: Hardcoded Bracket in Simulation Code

**What:** `round_1 = [("Arg", "Den"), ("Fra", "Pol"), ...]` written in Python code.
**Why bad:** Any bracket change requires code modification. Cannot inspect bracket structure without running code.
**Instead:** Load bracket from `data/bracket.json`.

### Anti-Pattern 3: Global Mutable State

**What:** Module-level dicts that get mutated by functions.
**Why bad:** Testing becomes order-dependent; difficult to reason about state.
**Instead:** All state lives in `main.py` and is passed explicitly to pure functions.

### Anti-Pattern 4: Not Handling "Played Match" Shortcut

**What:** Re-simulating matches that already have real results.
**Why bad:** Wastes CPU; simulation results won't match reality for past matches.
**Instead:** Check `played_set` before each match simulation; skip and use real winner.

### Anti-Pattern 5: Single-Round Bracket Representation

**What:** Only storing current round matchups, discarding future round structure.
**Why bad:** Cannot simulate full tournament; only predicts next round.
**Instead:** Store full bracket tree at startup.

---

## Scalability Considerations

| Concern | At 16 teams (R16→Final) | At 48 teams (group + knockout) |
|---------|------------------------|--------------------------------|
| **State size** | 16 teams, 15 matches, ~5KB JSON | 48 teams, 104 matches, ~20KB JSON |
| **Simulation time** (50k, Python) | ~2-5s | ~30-60s (group + 32-team KO) |
| **State complexity** | Linear file reads | Group standings, tiebreakers, third-place qualifiers |
| **API polling** | 1 req/min (within free tier) | Same (free tier limit unchanged) |
| **Output complexity** | Simple probability table | Per-stage probabilities, group standings |

**Implication:** The current architecture scales to the full 2026 format (48 teams, 104 matches) but simulation time becomes noticeable. At 48 teams, vectorization with numpy or multiprocessing may be warranted.

---

## Build Order Recommendation

Based on dependency analysis across ecosystem projects:

| Phase | Component | Depends On | Why This Order |
|-------|-----------|------------|----------------|
| 1 | State/Persistence | None | Every other component reads/writes state |
| 2 | Elo Rating Engine | None (pure math) | Can test independently; core algorithm |
| 3 | Bracket data structure + Tournament logic | State | Needs bracket format defined; foundational for sim |
| 4 | Simulator (single tournament + Monte Carlo) | Elo, Bracket | Tests core loop before API integration |
| 5 | Fetcher / API integration | State (mapping + played) | Needs state to persist played matches |
| 6 | Main loop orchestration | All above | Ties everything together |
| 7 | Output formatting | None (pure formatting) | Can be developed/tested with mock data |
| 8 | Error handling, logging, CLI options | Main loop | Polish layer |

**Dependency constraint:** Bracket structure must be defined before State (Phase 1) or at least before the State's load/save functions are finalized. In practice, define the bracket JSON schema first, then implement State, then everything else.

---

## Sources

| Source | Type | Confidence | Key Contribution |
|--------|------|------------|-----------------|
| goal-analytics (nithinnarla/goal-analytics) | GitHub (2026-04) | HIGH | Elo → Poisson → MC pipeline; project structure |
| world-cup-2026 (steodose/world-cup-2026) | GitHub (2026-06) | HIGH | Vectorized numpy MC; bracket solver; 50k sims <1s |
| world-cup-2026-forecast (manuelpeba) | GitHub (2026-03) | HIGH | Production-style modular architecture |
| mundial-monte (MPG-Paradox) | GitHub (2026-05) | HIGH | Live update loop; 50k sims; weekly re-sim |
| hrzn/soccer-predictions | GitHub | HIGH | Elo → Poisson → MC; clean module decomposition |
| soccer-xg-simulator (arya-chak) | GitHub (2025-05) | MEDIUM | CLI architecture; Monte Carlo engine pattern |
| chessswissprediction (geckods) | GitHub (2025-09) | HIGH | Elo-based MC; module separation; tiebreak logic |
| Super Bowl Prediction Model (CodeFix Solution) | Blog | MEDIUM | NFL-tuned Elo; bracket traversal algorithm |
| BoxingMonteCarlo (stevenGGG23) | GitHub (2025-12) | MEDIUM | CLI + multiprocessing MC |
| MarchMadSim (jordydavelaar) | GitHub (2025-03) | HIGH | NCAA bracket simulator; MC + round-by-round modes |
| AWS Bundesliga Match Facts | AWS Blog (2024-01) | MEDIUM | Production real-time architecture (overkill reference) |
| BotStadium (DEV Community) | Article (2026-03) | MEDIUM | Real-time SSE-based sports prediction |
| UCL Monte Carlo Simulation (ethan.science) | Academic Paper | MEDIUM | Elo → MC → Kelly criterion |
| SlamPredictor (nickdatak) | GitHub (2026-01) | MEDIUM | Surface-specific Elo; calibrated win probability |
| FIDE Candidates 2026 MC (Recursing gist) | GitHub (2026-03) | HIGH | 1M sims in ~5s on PyPy; draw-margin model |
| rstt (Ematrion/rstt) | GitHub (2025-02) | MEDIUM | Elo/Glicko ranking; tournament bracket formats |
