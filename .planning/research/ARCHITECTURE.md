# Architecture Patterns: UCL & League Prediction Modules

**Domain:** UEFA Champions League (Swiss-system) + Domestic League prediction  
**Researched:** 2026-06-27

## Recommended Architecture

### UCL Module Structure

```
competitions/ucl/
├── __init__.py              # sys.path bootstrap
├── main.py                  # CLI entry point, polling loop
├── config.py                # Competition constants (COMPETITION_TYPE="swiss", etc.)
├── simulation.py            # Full tournament run (league → playoff → knockout)
├── display.py               # 36-row league table + knockout bracket output
├── data/                    # teams.json, bracket.json, played.json, etc.
└── src/
    ├── __init__.py
    ├── league_table.py      # 36-team table: standings computation, tiebreaker chain
    ├── playoffs.py          # Knockout playoff (9-24) two-legged simulation
    ├── bracket_setup.py     # Seeded bracket for R16 from league position
    ├── et_penalties.py      # Extra time + penalty shootout simulation
    └── constants.py         # UCL-specific constants (HOME_ADVANTAGE_MULTIPLIER, etc.)
```

### League Module Structure

```
competitions/league/
├── __init__.py
├── main.py                  # CLI entry point
├── config.py                # League-specific config (LEAGUE_SIZE, TIEBREAKER_RULES, etc.)
├── simulation.py            # Full season simulation (double round-robin MC)
├── display.py               # League table output
├── data/
└── src/
    ├── __init__.py
    ├── standings.py         # Table computation with configurable tiebreaker chain
    ├── promotion.py         # Promotion/relegation logic, play-offs
    └── euro_qual.py         # European qualification mapping
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `ucl/simulation.py` | Orchestrates 50K MC: league phase → playoff → knockout | `football_core.groups` (Poisson), `football_core.knockout`, `ucl/src/league_table`, `ucl/src/playoffs`, `ucl/src/bracket_setup` |
| `ucl/src/league_table.py` | Computes 36-team standings, applies UCL tiebreaker chain, determines qualification bands (1-8, 9-16, 17-24, 25-36) | `football_core.groups` (Poisson scores only) |
| `ucl/src/playoffs.py` | Pairs 9-16 vs 17-24, simulates two-legged ties, resolves aggregates → ET → pens, supplies 8 winners to R16 | `ucl/src/bracket_setup`, `ucl/src/et_penalties` |
| `ucl/src/bracket_setup.py` | Builds R16 pairings from league position + playoff winners; implements top-4 seeding protection | `football_core.knockout` |
| `ucl/src/et_penalties.py` | Simulates extra time (30min Poisson with reduced lambda) and penalty shootout (50/50 + skill factor) | None (utility) |
| `league/simulation.py` | Iterates over 38 matchdays, simulates each, accumulates standings; applies promotion/relegation at end | `football_core.groups` (Poisson), `league/src/standings`, `league/src/promotion` |
| `league/src/standings.py` | Per-matchday table computation with configurable tiebreaker chain | None |
| `league/src/promotion.py` | Determines auto-promotion, relegation, play-off participants; simulates play-off ties | `league/src/standings` |
| `league/src/euro_qual.py` | Maps final league position to European competition slots | None |

### Data Flow: UCL Simulation Loop

```
For each iteration (50,000):
  1. Generate 8 match results per team using Poisson (from football_core.groups)
  2. Compute league standings with UCL tiebreaker chain
  3. Determine qualification bands:
     - Top 8 → R16 bye
     - 9-24 → playoff
     - 25-36 → eliminated
  4. If playoff:
     a. Pair 9-16 (seeded) vs 17-24 (unseeded)
     b. Simulate two-legged ties (home/away)
     c. Resolve aggregate → ET → penalties if needed
     d. 8 winners advance to R16
  5. Build R16 bracket:
     a. Top-8 teams paired against playoff winners (1/2 vs 15/18 pair, etc.)
     b. Apply top-4 seeding protection
  6. Simulate knockout rounds (R16 → QF → SF → Final) using football_core.knockout
  7. Count advancement probabilities (R16, QF, SF, Final, Champion)
```

### Data Flow: League Simulation Loop

```
For each iteration (50,000):
  1. For each matchday (1-38):
     a. Simulate all fixtures using Poisson (from football_core.groups)
     b. Update league standings with per-league tiebreaker chain
  2. After final matchday:
     a. Determine champion, UCL/Europa/Conference spots
     b. Determine relegation positions (bottom N)
     c. If play-off promotion: simulate two-legged semis + final
  3. Count outcome probabilities:
     - Champion, top 4, European qualification
     - Automatic promotion, play-off promotion, relegation
     - Specific position probabilities
```

## Patterns to Follow

### Pattern 1: Extend-via-Import (existing pattern)
**What:** Competition modules import generic primitives from `football_core` and wrap them with competition-specific logic  
**When:** Always — this is the established pattern  
**Example:**
```python
# UCL simulation imports Poisson scoring, adds Swiss league table
from football_core.groups import simulate_group_matches  # for Poisson per-match
from competitions.ucl.src.league_table import compute_swiss_standings
```

### Pattern 2: Competition-Boundary Contract (existing pattern)
**What:** Zero competition-specific logic in `football_core`  
**When:** Always — enforced by the Rule of Two  
**Example:** Tiebreaker logic lives in `competitions/ucl/src/tiebreakers.py`, not in `football_core/groups.py`

### Pattern 3: Precomputed Matchup Parameters (existing pattern)
**What:** Compute match lambdas before MC loop for speed  
**When:** For UCL's 36 teams × 8 matches = 144 matchups per MC iteration  
**Example:** Precompute `matchup_lambdas` dict for all 144 fixtures before entering 50K loop

### Pattern 4: Aggregation-First, Detail-Second (new for UCL)
**What:** For two-legged ties, simulate aggregate score first, then check if decider needed  
**When:** Knockout playoff ties; reduces simulation cost  
**Example:**
```python
def simulate_two_legged(team_a, team_b, lambda_a, lambda_b, rng):
    # First leg: team_a at home
    score_a1, score_b1 = poisson(lambda_a_home), poisson(lambda_b_away)
    # Second leg: team_b at home  
    score_a2, score_b2 = poisson(lambda_a_away), poisson(lambda_b_home)
    aggregate_a = score_a1 + score_a2
    aggregate_b = score_b1 + score_b2
    if aggregate_a > aggregate_b: return team_a
    if aggregate_b > aggregate_b: return team_b
    return simulate_extra_time_and_pens(team_a, team_b, ...)  # decider
```

### Pattern 5: Configurable Tiebreaker Chain (new for league)
**What:** Represent tiebreakers as an ordered list of `(key, reverse)` tuples that can be configured per league  
**When:** League module needs to handle different tiebreaker systems  
**Example:**
```python
# Premier League tiebreaker chain
PL_TIEBREAKERS = [
    ("gd", True),   # goal difference, descending
    ("gs", True),   # goals scored, descending
    ("h2h_pts", True),  # head-to-head points
    ("h2h_away_gs", True),  # head-to-head away goals
]

# La Liga tiebreaker chain  
LALIGA_TIEBREAKERS = [
    ("h2h_pts", True),
    ("h2h_gd", True),
    ("h2h_gs", True),
    ("gd", True),
    ("gs", True),
]
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Reusing H2H tiebreaker for UCL
**What:** Calling `football_core.groups._tiebreak_group()` for UCL league standings  
**Why bad:** UCL league phase does NOT use head-to-head as a tiebreaker (not all teams play each other)  
**Instead:** Implement separate UCL tiebreaker chain: GD → GS → away GS → wins → away wins → opponent points → opponent GD → opponent GS → disciplinary → coefficient

### Anti-Pattern 2: Per-matchday iteration inside MC loop for league
**What:** Re-computing the full schedule 38 times per iteration inside a 50K loop  
**Why bad:** 50K × 38 × (matches per MD) = excessive computation  
**Instead:** For each iteration, simulate all 380 matches (38 MD × 10 matches) in a single pass, then compute final standings. Precompute lambdas before the loop.

### Anti-Pattern 3: Knocking out 25th-36th teams in MC
**What:** Continuing to track eliminated teams through the knockout phase  
**Why not needed:** UCL eliminates 25-36 outright (no Europa League drop-down)  
**Instead:** Stop tracking eliminated teams. Only track survivors through playoff + knockout.

### Anti-Pattern 4: Single generic tiebreaker module
**What:** Building one "universal" tiebreaker system that handles every competition  
**Why bad:** UCL uses completely different criteria (no H2H, uses opponent strength). Leagues vary. Violates competition boundary principle.  
**Instead:** Each competition implements its own tiebreakers; shared logic extracted only when Rule of Two satisfied.

## Scalability Considerations

| Concern | UCL (36 teams) | League (20-24 teams) | League (46-match season) |
|---------|---------------|----------------------|--------------------------|
| MC iterations | 50K (standard) | 50K | 50K |
| Matches per iteration | 144 (36×8÷2) | 380 (20×38÷2) | 552 (24×46÷2) |
| Standings computation | O(n log n) × 1 | O(n log n) × 38 | O(n log n) × 46 |
| Memory | ~10MB | ~25MB | ~35MB |
| Runtime estimate | 3-5s per MC pass | 8-15s per MC pass | 12-20s per MC pass |

**Note:** League simulation is 2-4× more expensive than UCL due to match density. Precomputation of expected goals and vectorized Poisson sampling should be investigated for league modules.

## Sources

- Existing codebase patterns: `football_core/{groups,knockout}.py`, `competitions/worldcup/src/{groups,knockout}.py` — HIGH confidence
- Architectural constraints: `.planning/intel/constraints.md` — HIGH confidence
- UCL bracket procedure: Sporting News analysis — MEDIUM confidence (multiple sources)
- UEFA format documentation: UEFA.com — MEDIUM confidence (official, but regulation text not fully accessible)
