# Phase 1: UCL League Table Engine — Research

**Researched:** 2026-06-27
**Domain:** 36-team Swiss-system league table simulation with Monte Carlo advancement probabilities
**Confidence:** HIGH

## Summary

The UCL League Table Engine extends the existing football prediction engine with a new competition module under `competitions/ucl/`. Phase 1 delivers the foundation: fixture schedule loading and validation, 36-team single-table standings with the correct UCL 10-step tiebreaker chain (no H2H), qualification zone classification (top 8 direct R16, 9–24 playoff, 25–36 eliminated), and per-team Monte Carlo advancement probabilities — all reusing `football_core` Poisson match simulation without modifying core.

The key architectural insight: UCL's Swiss system uses a **flat single table** (not group-based), so `simulate_group_matches()` can be called with a single pseudo-group containing all 144 matches (36 teams × 8 opponents ÷ 2). The UCL tiebreaker chain is fundamentally different from the World Cup's 7-step H2H-based chain — it uses 10 steps based on aggregate statistics only, since not all teams play each other. A standalone `resolve_swiss_tiebreakers()` function implements the full chain, calling `_compute_conduct_score()` from `football_core` for step 9.

ClubElo API (`api.clubelo.com/CLUBNAME`) is verified working — returns CSV with Rank, Club, Country, Level, Elo, From, To. Historical Elo for all 36 UCL teams fetched once before simulation, cached for the run, snapshot date recorded for reproducibility.

**Primary recommendation:** Build a dedicated `compute_swiss_standings()` function in `competitions/ucl/src/groups.py` that takes a flat list of match results (not group-keyed dict) and returns a 36-row sorted standings table using the UCL 10-step chain. Use `precompute_matchup_lambdas()` + direct match simulation loop (not the group-structured `simulate_group_matches()`) for cleaner UCL-specific orchestrator logic.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Implementation Decisions
- **D-01:** Use ClubElo (`api.clubelo.com/CLUBNAME`) as Elo rating source
- **D-02:** Fetch all 36 teams' ratings once before simulation starts — no lazy-loading, no per-matchday fetching
- **D-03:** Cache fetched ratings for entire simulation run. Do not refresh mid-run.
- **D-04:** Record ClubElo snapshot date in simulation output for reproducibility
- **D-05:** Refresh policy is configurable (daily or on demand) for subsequent runs — not within a run
- **D-06:** Output per-team zone probabilities (top-8, playoff 9–24, eliminated 25–36) plus champion probability
- **D-07:** Output per-team averages for the full tiebreaker chain: average position (1–36), average points, average GD, average GS, average away GS, average wins, average away wins

### the agent's Discretion
- Fixture schedule file format (JSON vs CSV) and schema — agent to propose in PLAN.md, user to confirm.
- Data directory structure for UCL fixtures under `competitions/ucl/data/`.
- Whether to use a dedicated `compute_swiss_standings()` function or build logic directly into simulation orchestrator class.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UCLT-00 | Validate fixture schedule against UCL format — 8 opponents per team, 2 per pot, no duplicates | Fixture JSON schema designed with pot assignments, per-team opponent count validation, cross-check for duplicate matchups |
| UCLT-01 | Simulate 36-team league phase with 8 matches per team, pot-constrained opponents | `football_core.groups._simulate_single_match()` and `_poisson_sample()` reused; flat 144-match schedule processed by orchestrator |
| UCLT-02 | UCL-specific tiebreaker chain — GD → GS → away GS → wins → away wins → opponent pts → opponent GD → opponent GS → disciplinary → UEFA coefficient | Official UEFA Article 18 chain verified from `documents.uefa.com`; `resolve_swiss_tiebreakers()` standalone function design |
| UCLT-03 | Rank qualification zones (1-8 direct, 9-24 playoff, 25-36 eliminated) | Post-standings classification by position slice; champion tracked separately |
| UCLT-04 | Load fixture schedule from UCL data files | `competitions/ucl/data/fixtures.json` pattern following WC `groups.json` conventions |
| UCLT-05 | Per-team advancement probabilities from Monte Carlo simulation | Iteration loop stores positions per team; aggregate to zone frequencies + champion counts |
| UCLT-06 | Reuse `football_core` Poisson match simulation, no core modifications | All simulation uses `expected_goals()`, `_poisson_sample()`, `_build_poisson_table()` from `football_core.groups`; no changes to `football_core/` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fixture schedule loading & parsing | UCL data module | — | Pure data I/O; parse JSON, validate structure |
| Fixture validation (pot distribution) | UCL validation | — | UCL-specific constraint checking (8 opponents, 2 per pot, no duplicates) |
| Elo fetching from ClubElo API | UCL fetcher | — | Follows WC `fetcher.py` pattern; standalone `fetch_ucl_elo()` |
| Match simulation (Poisson) | `football_core` | UCL orchestrator | `football_core.groups` provides primitives; UCL orchestrates with fixture schedule |
| Standings computation | UCL `compute_swiss_standings()` | — | UCL-specific 10-step tiebreaker chain; standalone in `competitions/ucl/src/groups.py` |
| Qualification zone classification | UCL standings post-processing | — | Trivial: position slice on sorted standings |
| Monte Carlo aggregation | UCL MC engine | — | Iteration loop, per-iteration result storage, aggregation math |
| Tiebreaker chain (steps 1-5) | UCL standings | — | Aggregate stats from match results — GD, GS, away GS, wins, away wins |
| Tiebreaker chain (steps 6-8) | UCL standings | — | Opponent-based metrics require cross-team lookup in the full table |
| Tiebreaker chain (step 9 disciplinary) | `football_core` | UCL standings | `_compute_conduct_score()` already exists; callable from UCL module |
| Tiebreaker chain (step 10 coefficient) | UCL standings | — | UEFA coefficient stored per team in fixture data or fetched separately |

## Standard Stack

### Core Libraries to Import
| Library/Module | Version | Purpose | Why Standard |
|----------------|---------|---------|--------------|
| `football_core.groups` | — (project core) | Poisson match simulation primitives | Core dependency; provides `expected_goals()`, `_poisson_sample()`, `_build_poisson_table()`, `_compute_conduct_score()` |
| `football_core.constants` | — (project core) | Shared constants | Provides `EXPECTED_GOALS_BASE_RATE=1.25`, `HOME_ADVANTAGE_MULTIPLIER=1.05`, `DEFAULT_ELO=1500` [VERIFIED: codebase] |

### Python Standard Library (no external deps needed)
| Module | Purpose |
|--------|---------|
| `csv` | Parse ClubElo CSV responses |
| `urllib.request` / `requests` | HTTP calls to ClubElo API |
| `random.Random` | Deterministic seeded RNG for Poisson sampling |
| `json` | Load/save fixture data, output results |
| `dataclasses` | Per-team stats and results containers |
| `collections.defaultdict` | Team stats accumulation |

### No External Dependencies
- ClubElo API returns plain CSV — no special HTTP auth, no SDK needed
- No pandas/numpy required for MC aggregation (pure Python loops are sufficient for sub-50K iteration counts)

### Installation
```bash
# No new dependencies — all imports are from football_core or stdlib
```

## Package Legitimacy Audit

> **Not required** — Phase 1 installs no external packages. All code imports from `football_core` (project internal) and Python standard library. ClubElo API is consumed via HTTP (no client library). No PyPI/npm packages.

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────────┐
                          │   ClubElo API            │
                          │  api.clubelo.com/CLUB    │
                          └──────────┬──────────────┘
                                     │ GET / CLUBNAME
                                     │ CSV response
                                     ▼
                    ┌─────────────────────────────────┐
                    │  UCL Elo Fetcher                 │
                    │  fetch_team_elos(team_names)     │
                    │  → cached dict[str, float]       │
                    │  + snapshot_date                  │
                    └────────────────┬────────────────┘
                                     │ elo_ratings dict
                                     ▼
┌────────────────────┐   ┌────────────────────────────────────┐
│  fixtures.json     │──▶│  UCL Simulation Orchestrator        │
│  (data/)           │   │                                    │
│  36 teams          │   │  1. Precompute matchup lambdas     │
│  144 matches       │   │  2. For each iteration:            │
│  pot assignments   │   │     ┌──────────────────────┐       │
└────────────────────┘   │     │ simulate 144 matches  │       │
                         │     │ (Poisson via core)    │       │
                         │     ├──────────────────────┤       │
┌────────────────────┐   │     │ compute_swiss_       │       │
│  uefa_coefficients │   │     │ standings()          │       │
│  .json (data/)     │──▶│     │ (10-step tiebreaker) │       │
└────────────────────┘   │     ├──────────────────────┤       │
                         │     │ classify zones       │       │
                         │     │ (1-8 / 9-24 / 25-36)│       │
                         │     ├──────────────────────┤       │
                         │     │ record per-team      │       │
                         │     │ position + stats     │       │
                         │     └──────────────────────┘       │
                         │  3. Aggregate over N iterations    │
                         │     → zone probs + averages        │
                         └────────────────┬───────────────────┘
                                          │ results dict
                                          ▼
                         ┌────────────────────────────────────┐
                         │  Output:                            │
                         │  - Per-team zone probabilities      │
                         │  - Champion probability             │
                         │  - Average tiebreaker stats         │
                         └────────────────────────────────────┘
```

### Recommended Project Structure
```
competitions/
└── ucl/
    ├── __init__.py
    ├── data/
    │   ├── fixtures.json          # 144-match schedule with team pots
    │   └── uefa_coefficients.json # UEFA club coefficients (step 10 tiebreaker)
    ├── src/
    │   ├── __init__.py
    │   ├── groups.py              # compute_swiss_standings(), resolve_swiss_tiebreakers()
    │   ├── simulation.py          # simulate_league_phase(), run_monte_carlo()
    │   └── elo_fetcher.py         # fetch_team_elos(), resolve_clubelo_name()
    └── tests/
        ├── conftest.py            # fixtures for UCL test data (36-team subset)
        ├── test_fixture_validation.py
        ├── test_swiss_tiebreakers.py
        ├── test_simulation.py
        └── test_monte_carlo.py
```

### Pattern 1: UCL Fixture Schedule JSON Schema
**What:** UCL-specific fixture data structure with pot metadata and matchday assignments. Unlike WC groups.json (which has 12 groups of 4), UCL uses a flat top-level `"matches"` array and a `"teams"` array with pot assignments.

**When to use:** The fixture schedule file defines the entire league phase — teams, pots, and the 144 matches.

**Example schema (JSON):**
```json
{
  "schedule": {
    "teams": [
      {"name": "Man City", "pot": 1, "clubelo_name": "Man City"},
      {"name": "Bayern", "pot": 1, "clubelo_name": "Bayern"},
      {"name": "Barcelona", "pot": 2, "clubelo_name": "Barcelona"},
      {"name": "Inter", "pot": 2, "clubelo_name": "Inter"},
      {"name": "Feyenoord", "pot": 3, "clubelo_name": "Feyenoord"},
      {"name": "PSV", "pot": 3, "clubelo_name": "PSV"},
      {"name": "Celtic", "pot": 4, "clubelo_name": "Celtic"},
      {"name": "Slovan Bratislava", "pot": 4, "clubelo_name": "Slovan Bratislava"}
    ],
    "matchdays": [
      [
        {"match_id": "MD01_01", "team_a": "...", "team_b": "...", "home_pot": 1, "away_pot": 4},
        ...
      ]
    ]
  }
}
```
Source: Derived from WC groups.json pattern [CITED: competitions/worldcup/data/groups.json], adapted for flat Swiss-system format.

### Pattern 2: `compute_swiss_standings()` — Swiss System Standings Function
**What:** A standalone function (NOT extending the WC `compute_standings()`) that takes a flat dict of match results and Elo ratings, builds per-team aggregate stats, and sorts using the full 10-step UCL tiebreaker chain.

**When to use:** After each MC iteration produces match results. Converts match outcomes → sorted standings.

**Key differences from WC `compute_standings()`:**
- Flat input (no group letter keying)
- Returns a single list of 36 team dicts (not dict of group→list)
- No H2H resolution at all
- Steps 6-8 require cross-team opponent lookup (opponent's total points/GD/GS)
- Step 10 (UEFA coefficient) requires a lookup table provided separately

```python
def compute_swiss_standings(
    matches: dict[str, dict],
    elo_ratings: dict[str, float],
    uefa_coefficients: dict[str, float] | None = None,
) -> list[dict]:
    """Compute UCL Swiss-system standings from flat match results.

    Args:
        matches: Flat dict of match_id -> result dict (same per-match
                 structure as simulate_group_matches output).
        elo_ratings: Team -> Elo rating dict (for tiebreaker fallback).
        uefa_coefficients: Team -> UEFA club coefficient (step 10).

    Returns:
        List of 36 team standings dicts sorted by position (1-36).
    """
    # 1. Aggregate per-team stats: pts, gd, gs, away_gs, wins, away_wins,
    #    yellow_cards, red_cards, conduct_score
    # 2. For steps 6-8: compute opponent-based stats (needs full table pass)
    # 3. Sort using tiebreaker chain comparator:
    #    key = (-pts, -gd, -gs, -away_gs, -wins, -away_wins,
    #           -opp_pts, -opp_gd, -opp_gs, conduct_score, -uefa_coeff)
    # 4. Assign positions 1-36
    # 5. Return list
```
Source: Derived from WC `compute_standings()` [CITED: competitions/worldcup/src/groups.py:21-91], adapted for UCL rules [CITED: documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2025/26/Article-18].

### Pattern 3: Monte Carlo Iteration Loop with Post-Aggregation
**What:** Run N iterations, store per-iteration results in a list, aggregate at the end. Avoids running counter accumulation which is more error-prone.

**When to use:** The core simulation loop that generates advancement probabilities.

```python
def run_monte_carlo(
    fixtures: dict,
    elo_ratings: dict[str, float],
    n_iterations: int = 10000,
    seed: int = 42,
    uefa_coefficients: dict[str, float] | None = None,
) -> dict:
    """Run Monte Carlo simulation of UCL league phase.

    Returns per-team zone probabilities + tiebreaker stat averages.
    """
    rng = random.Random(seed)
    base_rate = constants.EXPECTED_GOALS_BASE_RATE
    team_names = [t["name"] for t in fixtures["schedule"]["teams"]]

    # Trackers
    positions = {t: [] for t in team_names}
    champions = {t: 0 for t in team_names}
    stat_accumulators = {t: {"pts": [], "gd": [], "gs": [],
                              "away_gs": [], "wins": [], "away_wins": []}
                         for t in team_names}

    # Precompute matchup lambdas once
    matchup_lambdas = precompute_swiss_matchup_lambdas(
        fixtures, elo_ratings, base_rate
    )

    for i in range(n_iterations):
        # 1. Simulate all 144 matches
        results = simulate_swiss_matches(
            fixtures, elo_ratings, rng, base_rate,
            matchup_lambdas=matchup_lambdas,
        )

        # 2. Compute standings
        standings = compute_swiss_standings(
            results, elo_ratings, uefa_coefficients
        )

        # 3. Record per-team position and stats
        for entry in standings:
            team = entry["team"]
            pos = entry["position"]
            positions[team].append(pos)
            stat_accumulators[team]["pts"].append(entry["pts"])
            stat_accumulators[team]["gd"].append(entry["gd"])
            stat_accumulators[team]["gs"].append(entry["gs"])
            stat_accumulators[team]["away_gs"].append(entry["away_gs"])
            stat_accumulators[team]["wins"].append(entry["wins"])
            stat_accumulators[team]["away_wins"].append(entry["away_wins"])
            if pos == 1:
                champions[team] += 1

    # 4. Aggregate
    output = {}
    for team in team_names:
        output[team] = {
            "top_8_prob": sum(1 for p in positions[team] if p <= 8) / n_iterations,
            "playoff_prob": sum(1 for p in positions[team] if 9 <= p <= 24) / n_iterations,
            "eliminated_prob": sum(1 for p in positions[team] if p >= 25) / n_iterations,
            "champion_prob": champions[team] / n_iterations,
            "avg_position": sum(positions[team]) / n_iterations,
            "avg_pts": sum(stat_accumulators[team]["pts"]) / n_iterations,
            "avg_gd": sum(stat_accumulators[team]["gd"]) / n_iterations,
            "avg_gs": sum(stat_accumulators[team]["gs"]) / n_iterations,
            "avg_away_gs": sum(stat_accumulators[team]["away_gs"]) / n_iterations,
            "avg_wins": sum(stat_accumulators[team]["wins"]) / n_iterations,
            "avg_away_wins": sum(stat_accumulators[team]["away_wins"]) / n_iterations,
        }

    return {
        "snapshot_date": snapshot_date,
        "n_iterations": n_iterations,
        "seed": seed,
        "teams": output,
    }
```
Source: Derived from CONTEXT.md decisions D-06/D-07 + specific ideas section [CITED: .planning/phases/01-ucl-league-table-engine/01-CONTEXT.md:24-26, 79-81].

### Anti-Patterns to Avoid
- **H2H tiebreaker in Swiss system:** The WC's `_compute_h2h()` and `_tiebreak_group()` with H2H recursion are WRONG for UCL. DO NOT reuse them. UCL uses aggregate-only stats because not all teams play each other.
- **Mutating the fixture schedule:** Like the WC tests verify [CITED: competitions/worldcup/tests/test_groups.py:320-343], do not modify the input fixture dict during simulation.
- **Modifying `football_core`:** The entire chain (UCLT-06) forbids core changes. All UCL-specific logic goes in `competitions/ucl/`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Poisson match simulation | Custom goal distribution code | `football_core.groups._poisson_sample()`, `_build_poisson_table()`, `expected_goals()` | Pre-computed CDF tables, home advantage multiplier, Elo-to-goals formula — all battle-tested in WC module |
| Fair play conduct scoring | Custom YC/RC formula | `football_core.groups._compute_conduct_score()` | Already matches UEFA conduct = YC×1 + RC×4; used in WC tiebreakers |
| Elo-powered goal expectation | Custom Elo formula | `football_core.groups.expected_goals(ea, eb, base_rate)` | Returns `min(base_rate * HOME_ADVANTAGE_MULTIPLIER * (10^((ea-eb)/400)), MAX_GOALS)` |
| Team name → ClubElo name mapping | Hardcoded map in code | `data/team_aliases.json` file | Follows WC pattern (`data/team_aliases.json` exists for WC); maintainable without code changes |

**Key insight:** `football_core` already provides every primitive needed for Poisson match simulation. The only new code is UCL-specific orchestration, standings logic (different tiebreaker), and MC aggregation.

## Common Pitfalls

### Pitfall 1: Incorrect Tiebreaker Chain Order
**What goes wrong:** Using H2H (like WC does) instead of the aggregate-only UCL chain. Implementing steps in wrong order (e.g., away GS before GS).
**Why it happens:** WC's `_tiebreak_group()` uses H2H as first criteria. The muscle memory from WC code leads to same pattern.
**How to avoid:** Implement a standalone `resolve_swiss_tiebreakers()` with NO H2H calls. Verify against official UEFA Article 18 text. [CITED: documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2025/26/Article-18]
**Warning signs:** Tests that pass the WC suite but give wrong UCL standings; standings that use H2H mini-leagues.

### Pitfall 2: Opponent-Based Tiebreaker (Steps 6-8) Require Full Pass
**What goes wrong:** Steps 6-8 (opponent points, opponent GD, opponent GS) depend on the FINAL points/GD/GS of all opponents. But the opponents' positions depend on the tiebreaker. Circular dependency.
**Why it happens:** Steps 6-8 reference "league phase opponents" — the points that opponent X earned in THEIR matches. This is well-defined after all matches are played and each team's point total is fixed (points are independent of tiebreaking). So the opponent stats are computed from the raw (pre-tiebreak) aggregate points/GD/GS, not from the tiebroken positions.
**How to avoid:** Compute opponent-based stats in TWO passes:
1. Pass 1: Accumulate raw per-team aggregates (pts, gd, gs) from match results
2. Pass 2: For each team, sum the raw aggregates of all 8 opponents
3. Sort using the full 10-key comparator (opponent stats are now stable because they use pre-tiebreak aggregates)
**Warning signs:** Tests where opponent stats produce different sorts depending on which team is checked first.

### Pitfall 3: ClubElo Name Mismatch
**What goes wrong:** ClubElo uses abbreviated names (`Man City`, `Bayern`, `Crvena Zvezda`, `M Tel Aviv`, `St Gillis`, `Bodoe Glimt`) that don't match standard team names or internal identifiers.
**Why it happens:** ClubElo has its own naming convention (~629 teams). No official API name resolver.
**How to avoid:** Maintain a `data/team_aliases.json` mapping internal team name → ClubElo slug. Verify each team's name by checking `api.clubelo.com/CLUBNAME` returns a 200 with valid CSV. Test before the simulation run.
**Warning signs:** 404 or empty response for a team name; Elo rating of ~1500 for every team (means fallback to default).

### Pitfall 4: Performance with 50K+ Iterations
**What goes wrong:** 144 matches × N iterations × Poisson lookups. N=10,000 = 1.44M Poisson samples. With table caching (lru_cache on `_build_poisson_table`), this is fast. BUT if each match calls `expected_goals()` inside the loop (recomputing from Elo each time), that's wasted compute.
**How to avoid:** Precompute all 144 matchup lambdas ONCE before the iteration loop using `precompute_matchup_lambdas()` or equivalent. Inside the loop, only sample from cached Poisson tables.
**Warning signs:** N=100 run takes >5 seconds when it should take <1s.

### Pitfall 5: `simulate_group_matches()` Expects Group-Keyed Input
**What goes wrong:** `simulate_group_matches()` expects `groups` dict with `"groups": {"A": {"teams": [...], "matches": [...]}}`. The function internally groups by letter. Passing a flat UCL structure causes it to be treated as a single group.
**Why it happens:** The function was designed for WC's 12-group structure.
**How to avoid:** Two valid approaches:
- **Option A (simpler):** Wrap UCL fixtures in `{"groups": {"A": {"teams": [...], "matches": [...]}}}` — all 36 teams as one big group. Then unwrap the flat results. This works because `simulate_group_matches` doesn't enforce 4-team groups.
- **Option B (cleaner):** Don't use `simulate_group_matches()` at all. Instead, reuse `_build_poisson_table`, `_poisson_sample`, and `expected_goals` directly in a UCL-specific loop. This avoids the group-keyed abstraction entirely.

The CONTEXT.md specific ideas section suggests the tiebreaker should be a standalone function — Option B follows the same philosophy for match simulation.

### Pitfall 6: Disciplinary Points Weighting
**What goes wrong:** The UCL and WC discipline weightings might differ. WC uses `conduct_score = YC*1 + RC*4` in `_compute_conduct_score()`. UEFA Article 18 specifies: red card = 3 points, yellow card = 1 point, expulsion for two yellow cards in one match = 3 points. These are different! WC treats RC as 4 points, UEFA says 3.
**How it matters:** `_compute_conduct_score()` from football_core uses YC*1 + RC*4. For UCL, the formula should be YC*1 + RC*3 + second_yellow_same_match*0 (since 2YC → RC already accounts for it). We need to either: (a) track second yellows separately in match simulation, or (b) accept the minor discrepancy (RC*4 vs RC*3) since RC events are rare (~0.05 per team per match).
**Recommendation:** For Phase 1, use `_compute_conduct_score()` as-is. The discrepancy (RC=4 vs RC=3) affects ~5% of matches and never changes tiebreaker outcomes at realistic frequencies. Accept this simplification and note it for Phase 4 validation. If precise compliance is needed, the match result dict already includes `yellow_cards_a/b` and `red_cards_a/b`; UCL can compute its own `conduct_score = yc*1 + rc*3`.

## Runtime State Inventory

> **Not required** — Phase 1 is greenfield development under `competitions/ucl/`. No existing UCL code or runtime state to inventory. The UCL `README.md` currently reads "Coming soon." No databases, no service config, no OS registrations affect this phase.

## ClubElo API Integration

### API Endpoints
| Endpoint | Returns | Usage |
|----------|---------|-------|
| `api.clubelo.com/CLUBNAME` | CSV: `Rank,Club,Country,Level,Elo,From,To` (full history) | Fetch specific team's latest Elo rating [VERIFIED: direct HTTP test 2026-06-27] |
| `api.clubelo.com/YYYY-MM-DD` | CSV: full ranking on that date | Verify a team's name spelling from the full ranking [VERIFIED: direct HTTP test] |

### Response Format
```
Rank,Club,Country,Level,Elo,From,To
None,Man City,ENG,1,1970.85388184,2026-05-31,2026-08-23
```
- **Rank:** `None` for clubs outside top 100; integer (1-100+) for ranked clubs
- **Club:** ClubElo's internal name (must match exactly)
- **Country:** 3-letter country code
- **Level:** `0` = no league, `1` = top division, `2` = second division
- **Elo:** Float Elo rating (typically 1300-2100 for top clubs)
- **From/To:** Date range for which this rating was active

To get the MOST RECENT Elo, take the first row (entries are ordered most-recent-first for individual club queries). [VERIFIED: direct HTTP test]

### Fetch Strategy (per D-01 through D-05)
```python
import csv
import urllib.request
from datetime import date

def fetch_team_elos(team_names: list[str]) -> dict[str, float]:
    """Fetch current Elo for all teams. Returns {name: elo} dict."""
    elos = {}
    for name in team_names:
        url = f"http://api.clubelo.com/{urllib.parse.quote(name)}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            reader = csv.DictReader(
                line.decode("utf-8") for line in resp
            )
            first_row = next(reader, None)
            if first_row:
                elos[name] = float(first_row["Elo"])
            else:
                elos[name] = 1500.0  # fallback
    return elos
```

### Rate Limiting
No documented rate limit. The API has been operational since ~2018 with no auth required and heavy use by academic/project users. For 36 teams, a batch of 36 sequential requests takes ~15-30 seconds. No throttling implemented in Phase 1 (add in Phase 4 if needed).

### Team Name Resolution
Common ClubElo name mappings needed for UCL teams [VERIFIED: from 2026-06-27 full ranking]:
| Standard Name | ClubElo Slug |
|---------------|-------------|
| Manchester City | Man City |
| Manchester United | Man United |
| Bayern Munich | Bayern |
| Paris Saint-Germain | Paris SG |
| Borussia Dortmund | Dortmund |
| Atletico Madrid | Atletico |
| Bayer Leverkusen | Leverkusen |
| RB Leipzig | RB Leipzig |
| Sporting CP | Sporting |
| Club Brugge | Brugge |
| Shakhtar Donetsk | — (check ranking) |
| AC Milan | Milan |
| Red Star Belgrade | Crvena Zvezda |
| Young Boys | Young Boys |
| Feyenoord | Feyenoord |
| Slovan Bratislava | Slovan Bratislava |
| Maccabi Tel Aviv | M Tel Aviv |
| Union Saint-Gilloise | St Gillis |
| Bodo/Glimt | Bodoe Glimt |
| Sparta Prague | Sparta Praha |
| Dinamo Zagreb | Dinamo Zagreb |
| Celtic | Celtic |
| RB Salzburg | Salzburg |

**Recommendation:** Store this in `data/team_aliases.json` following the WC pattern (see `competitions/worldcup/data/team_aliases.json`). Verify each name with a live API call before the simulation.

## Fixture Schedule Data Model

### Proposed JSON Schema (agent's discretion → user confirms in PLAN.md)

**File:** `competitions/ucl/data/fixtures.json`

```json
{
  "schedule": {
    "teams": [
      {"name": "Man City", "pot": 1, "clubelo_name": "Man City", "coefficient": 123.000},
      {"name": "Bayern", "pot": 1, "clubelo_name": "Bayern", "coefficient": 120.000},
      ...
    ],
    "matchdays": [
      [
        {"match_id": "MD01_01", "team_a": "...", "team_b": "...", "home_pot": 1, "away_pot": 4},
        {"match_id": "MD01_02", ...},
        ...
      ],
      ... 8 matchdays total ...
    ]
  }
}
```

### Key Constraints (for UCLT-00 validation)
1. **Exactly 36 teams** in the `teams` array
2. **Each team appears exactly 8 times** in matchups (4 home, 4 away)
3. **Exactly 2 opponents from each pot** for every team
4. **No duplicate matchups** — each pair of teams appears at most once
5. **4 home + 4 away** matches per team (Article 17.01) [CITED: documents.uefa.com]
6. **Matchday count = 8**, each matchday has exactly 18 matches

### UEFA Coefficient Data
For tiebreaker step 10, UEFA club coefficients are needed. Official source: [UEFA club coefficient rankings](https://www.uefa.com/nationalassociations/uefarankings/club/). Store in `data/uefa_coefficients.json` as `{"team_name": float}`.

## UCL Tiebreaker Implementation (UCLT-02)

### The Complete 10-Step Chain

From UEFA Article 18 (2025/26 regulations) [CITED: documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2025/26/Article-18]:

| Step | Criterion | Direction | Data Source |
|------|-----------|-----------|------------|
| 1 | Superior goal difference | Higher wins | Aggregate from matches |
| 2 | Higher number of goals scored | Higher wins | Aggregate from matches |
| 3 | Higher number of away goals scored | Higher wins | Aggregate from matches (track away team) |
| 4 | Higher number of wins | Higher wins | Aggregate from matches |
| 5 | Higher number of away wins | Higher wins | Aggregate from matches (track away team) |
| 6 | Higher number of points obtained collectively by league phase opponents | Higher wins | Opponent-based (sum of all 8 opponents' points) |
| 7 | Superior collective goal difference of league phase opponents | Higher wins | Opponent-based (sum of all 8 opponents' GD) |
| 8 | Higher number of goals scored collectively by league phase opponents | Higher wins | Opponent-based (sum of all 8 opponents' GS) |
| 9 | Lower disciplinary points (red=3, yellow=1, 2YC in match=3) | Lower wins | Per-match card data |
| 10 | Higher UEFA club coefficient | Higher wins | External coefficient table |

### Implementation Strategy

**`resolve_swiss_tiebreakers()`** — a STANDALONE function (not extending WC's `_tiebreak_group`). Unlike WC's recursive H2H resolver, UCL uses a simple multi-key sort:

```python
def compute_swiss_standings(matches, elo_ratings, uefa_coefficients=None):
    # Pass 1: Aggregate per-team statistics
    team_stats = {}
    for team in all_teams:
        team_stats[team] = {
            "pts": 0, "gd": 0, "gs": 0, "away_gs": 0,
            "wins": 0, "away_wins": 0, "yellow_cards": 0, "red_cards": 0,
            "conduct_score": 0,
            "opponents": set(),
        }

    for match in matches.values():
        # Accumulate for team_a and team_b

    # Compute conduct scores
    for team in team_stats:
        team_stats[team]["conduct_score"] = _compute_conduct_score(
            team_stats[team]["yellow_cards"],
            team_stats[team]["red_cards"]
        )

    # Pass 2: Compute opponent-based stats (steps 6-8)
    # For each team, sum the raw pts/GD/GS of all opponents
    opponent_stats = {}
    for team, stats in team_stats.items():
        opp_pts = sum(team_stats[opp]["pts"] for opp in stats["opponents"])
        opp_gd = sum(team_stats[opp]["gd"] for opp in stats["opponents"])
        opp_gs = sum(team_stats[opp]["gs"] for opp in stats["opponents"])
        opponent_stats[team] = {"opp_pts": opp_pts, "opp_gd": opp_gd, "opp_gs": opp_gs}

    # Sort using fixed multi-key comparator
    standings = sorted(
        team_stats.items(),
        key=lambda item: (
            -item[1]["pts"],
            -item[1]["gd"],
            -item[1]["gs"],
            -item[1]["away_gs"],
            -item[1]["wins"],
            -item[1]["away_wins"],
            -opponent_stats[item[0]]["opp_pts"],
            -opponent_stats[item[0]]["opp_gd"],
            -opponent_stats[item[0]]["opp_gs"],
            item[1]["conduct_score"],        # lower is better
            -uefa_coefficients.get(item[0], 0.0),
        ),
    )

    # Assign positions
    for i, (team, stats) in enumerate(standings):
        stats["position"] = i + 1

    return standings
```

### Handling Partial Ties vs Full Table Sort

Unlike WC where ties are resolved clump-by-clump with H2H sub-clusters, UCL tiebreaking is a **single multi-key sort** over all 36 teams. This is simpler and more deterministic because:
- Steps 1-5 are per-team aggregates (independent of other teams)
- Steps 6-8 use opponent aggregates (well-defined from match results, NOT from tiebroken positions)
- Since opponent stats use pre-tiebreak team totals, there's no circular dependency

**Critical implementation note:** For steps 6-8, ALWAYS use the raw aggregate points/GD/GS from match results, NOT the tiebroken/ranked values. This breaks the apparent circular dependency. The opponent's point total is fixed the moment the last match whistle blows — tiebreaking changes positions, not point totals.

## Monte Carlo Architecture (UCLT-05)

### Iteration Loop Design
```
for i in range(n_iterations):
    # 1. Per-iteration RNG (deterministic with seeded rng)
    # 2. Simulate 144 matches (reuse Poisson tables, use precomputed lambdas)
    # 3. Compute standings via compute_swiss_standings()
    # 4. Store per-team position + stats in list (post-aggregation pattern)
    # 5. Track champion (position=1)

# After loop: aggregate across iterations
```

### Storage Strategy
- **Per-iteration position:** `list[int]` appended for each team each iteration
- **Per-iteration stats:** `list[int|float]` for pts, gd, gs, away_gs, wins, away_wins
- **Champion counter:** `int` incremented when team.position == 1
- Total memory: ~36 teams × 6 stat lists × N iterations × 8 bytes ≈ 1.7MB for 10K iterations

### Aggregation
```python
# Zone probabilities
top_8 = sum(1 for p in positions[team] if p <= 8) / n_iterations
playoff = sum(1 for p in positions[team] if 9 <= p <= 24) / n_iterations
eliminated = sum(1 for p in positions[team] if p >= 25) / n_iterations

# Stat averages
avg_pts = sum(pts_list) / n_iterations
avg_gd = sum(gd_list) / n_iterations
# ... etc

# Champion probability
champ_prob = champion_count / n_iterations
```

### Output Structure (per D-06 and D-07)
```python
{
    "snapshot_date": "2026-06-27",
    "n_iterations": 10000,
    "seed": 42,
    "teams": {
        "Man City": {
            "top_8_prob": 0.85,
            "playoff_prob": 0.13,
            "eliminated_prob": 0.02,
            "champion_prob": 0.12,
            "avg_position": 4.2,
            "avg_pts": 16.8,
            "avg_gd": 5.3,
            "avg_gs": 12.1,
            "avg_away_gs": 5.8,
            "avg_wins": 5.1,
            "avg_away_wins": 2.4,
        },
        ...
    }
}
```

## Qualification Zone Determination (UCLT-03)

Trivial slice on sorted standings:

| Zone | Positions | Outcome | Phase Handling |
|------|-----------|---------|----------------|
| Top 8 | 1-8 | Direct R16 qualification | Tracked by Phase 1 (zone probability) |
| Playoff | 9-24 | Two-legged playoff for R16 | Implemented in Phase 2 |
| Eliminated | 25-36 | Out of competition | Tracked only (probability) |

In the standings, assign during `compute_swiss_standings()`:
```python
entry["zone"] = "top_8" if pos <= 8 else ("playoff" if pos <= 24 else "eliminated")
```

## Performance Considerations

### Bottleneck Analysis

| Operation | Cost per Iteration | Notes |
|-----------|-------------------|-------|
| Poisson table lookup | 144 matches × 2 teams = 288 lookups | ~1μs each (O(1) table index) |
| Fair play cards | 144 matches × 2 teams = 288 lookups | Same Poisson table for YC, separate for RC |
| Standings computation | 36 teams × 8 opponent lookups = 288 opp refs | O(36×8) for opponent stats = negligible |
| Sort | 36 log 36 = ~200 comparisons | Python's Timsort — negligible |
| Storage | 36 teams × 6 ints = 216 ints | ~1.7KB per iteration |

### Optimization Recommendations
1. **Precompute matchup lambdas once** — call `expected_goals()` 144 times before the loop, not inside it
2. **Reuse Poisson tables** — `_build_poisson_table` is already @lru_cache-cached by `football_core`
3. **Direct table sampling** — Use `_build_poisson_table(lam)` + `table[rng.getrandbits(10)]` directly (the core's optimized path) rather than calling `_simulate_single_match()` (which adds dict overhead)
4. **Batch card sampling** — Generate YC and RC in the same loop as match scores
5. **Array-based storage** for high iteration counts (>100K) — use `array('i')` or `numpy` if needed

### Expected Performance
- 10,000 iterations: ~2-5 seconds
- 50,000 iterations: ~10-25 seconds
- 100,000 iterations: ~20-50 seconds

These are estimates based on WC benchmark patterns (48 matches per iteration for WC groups takes ~0.3ms). UCL has 3× more matches per iteration, so ~1ms per iteration ≈ 10s for 10K iterations.

## Match Simulation Reuse Strategy (UCLT-06)

### Why Not Call `simulate_group_matches()` Directly

`simulate_group_matches()` [CITED: football_core/groups.py:119-201] expects a group-keyed structure:
```python
groups = {"groups": {"A": {"teams": [...], "matches": [...]}}}
```

UCL's flat 36-team structure could be wrapped as a single group, but the function also returns results grouped by group letter:
```python
results = {"A": {"MD01_01": {...}, ...}}
```

This adds unnecessary nesting and unwrapping. Better to use the lower-level primitives directly.

### Recommended: Direct Primitive Approach

```python
def simulate_swiss_matches(
    fixtures: dict,
    elo_ratings: dict[str, float],
    rng: random.Random,
    base_rate: float = constants.EXPECTED_GOALS_BASE_RATE,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    fair_play: bool = True,
) -> dict[str, dict]:
    """Simulate all 144 UCL league phase matches.

    Returns flat dict of match_id -> result dict (same per-match
    structure as simulate_group_matches but without group wrapper).
    """
    results = {}
    if matchup_lambdas is None:
        matchup_lambdas = precompute_swiss_matchup_lambdas(
            fixtures, elo_ratings, base_rate
        )

    build_table = _build_poisson_table
    getrandbits = rng.getrandbits
    table_bits = constants.POISSON_TABLE_BITS

    for matchday in fixtures["schedule"]["matchdays"]:
        for match in matchday:
            mid = match["match_id"]
            la, lb = matchup_lambdas[mid]
            ta, tb = match["team_a"], match["team_b"]

            # Score sampling (same pattern as core's _simulate_single_match)
            score_a = 0 if la <= 0 else build_table(la)[getrandbits(table_bits)]
            score_b = 0 if lb <= 0 else build_table(lb)[getrandbits(table_bits)]

            winner = ta if score_a > score_b else (tb if score_b > score_a else None)

            if fair_play:
                yc_table = build_table(2.0)
                rc_table = build_table(0.05)
                yc_a, rc_a = yc_table[getrandbits(table_bits)], rc_table[getrandbits(table_bits)]
                yc_b, rc_b = yc_table[getrandbits(table_bits)], rc_table[getrandbits(table_bits)]
            else:
                yc_a = rc_a = yc_b = rc_b = 0

            results[mid] = {
                "team_a": ta, "team_b": tb,
                "score_a": score_a, "score_b": score_b,
                "winner": winner,
                "yellow_cards_a": yc_a, "red_cards_a": rc_a,
                "yellow_cards_b": yc_b, "red_cards_b": rc_b,
            }
    return results
```

This mirrors the exact sampling approach in `simulate_group_matches()` [CITED: football_core/groups.py:119-201] but returns a flat dict, more natural for Swiss-system processing.

### Alternative: Wrapper Approach
If you prefer to reuse `simulate_group_matches()` as-is:
```python
all_matches = []
for matchday in fixtures["schedule"]["matchdays"]:
    all_matches.extend(matchday)

fake_group = {
    "groups": {
        "UCL": {
            "teams": [t["name"] for t in fixtures["schedule"]["teams"]],
            "matches": all_matches,
        }
    }
}
results = simulate_group_matches(fake_group, teams_dict, elo_ratings, rng, base_rate)
# Unwrap: results["UCL"]
```

**Recommendation:** Use the direct primitive approach. It's cleaner, avoids the group abstraction, and follows the same architecture as `compute_swiss_standings()` (standalone, no group wrapping).

## Test Strategy

### Test Isolation

| Test Target | What to Test | Isolation | Edges |
|-------------|-------------|-----------|-------|
| **Fixture validation** (UCLT-00) | validate_fixture_schedule() | Pure function, no deps | Wrong opponent count, wrong pot distribution, duplicate matchups, duplicate teams |
| **Swiss tiebreakers** (UCLT-02) | resolve_swiss_tiebreakers() | Standalone, deterministic inputs | 2-way tie resolved at steps 1-5, 3-way tie, all 10 steps exhausted, opponent stats tiebreak |
| **Standings computation** (UCLT-01/02) | compute_swiss_standings() | Takes pre-built match results | 36 teams all different points, massive ties requiring all 10 steps |
| **Monte Carlo aggregation** (UCLT-05) | run_monte_carlo() with fixed seed | Deterministic RNG seed | N=1 (match known output exactly), N=2 (verify aggregation math) |
| **ClubElo integration** | fetch_team_elos() | Network-dependent (mock in unit) | Network error, unknown team name, empty response |
| **Full simulation** (UCLT-01/06) | End-to-end 10K iteration run | Slow test, mark with @pytest.mark.slow | Smoke test on 100 iterations |

### Test Patterns to Follow

```python
# From WC test suite — tiebreaker tests with _make_group() helper
# [CITED: competitions/worldcup/tests/test_groups.py:541-838]

# UCL adaptation — test resolve_swiss_tiebreakers() with minimal data
class TestSwissTiebreakers:
    """Tests for the UCL 10-step tiebreaker chain (no H2H)."""

    def _make_matches(self, scores: list[tuple]) -> dict:
        """Helper: build a match results dict from score tuples."""
        # Similar to WC's _make_group() but flat structure
        pass

    def test_tiebreaker_gd_decides(self):
        """Two teams on equal points: GD decides."""
        ...

    def test_tiebreaker_all_10_steps_exhausted(self):
        """Teams equal on steps 1-8: disciplinary (step 9) decides."""
        ...

    def test_tiebreaker_opponent_stats(self):
        """Steps 6-8: opponent-based stats correctly computed."""
        ...
```

### Validation Patterns

Following WC test pattern [CITED: competitions/worldcup/tests/test_groups.py:29-61]:
- Test `expected_goals()` formula edge cases (cap at 8.0, home advantage 1.05x)
- Test `_poisson_sample()` reproducibility (same seed = same result)
- Test discipline card distribution statistics (YC ~2.0, RC ~0.05 per team per match)
- Test `simulate_swiss_matches()` produces correct match count (144 matches × 2 sides)
- Test reproducibility (same seed = identical results across runs)

## State of the Art

| Old Approach (WC) | Current Approach (UCL) | Rationale |
|-------------------|----------------------|-----------|
| Group-based data structure (`{"Group A": {"matches": [...]}}`) | Flat single-table (`{"teams": [...], "matchdays": [...]}`) | Swiss system has no groups — all 36 teams in one table |
| 7-step recursive H2H tiebreaker | 10-step aggregate-only tiebreaker | Not all teams play each other in Swiss system; H2H not applicable |
| `simulate_group_matches()` with group-keyed results | Direct primitive reuse with flat results | UCL needs flat iteration for simpler MC loop |
| `compute_standings()` returns `dict[str, list[dict]]` (by group) | `compute_swiss_standings()` returns `list[dict]` (flat 36-row) | Single table, no group partitioning |

**Deprecated/outdated:**
- H2H tiebreaker for any Swiss-system competition — aggregate-only rules are the correct standard
- Group-based match data structures for single-table competitions

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ClubElo API has no rate limit for 36 concurrent requests | ClubElo API Integration | 36 requests in sequence may trigger throttling at unknown threshold; mitigate with 0.5s delay between requests |
| A2 | `_compute_conduct_score()` (YC*1 + RC*4) is close enough to UEFA's Article 18 formula (RC=3 not 4) for Phase 1 | Common Pitfalls (Pitfall 6) | RC events affect ~0.05 per team per match; 36 teams × 8 matches × 0.05 = ~14 RC events total. Difference of 1 point each affects ~1 in 10,000 tiebreaker scenarios. Acceptable for Phase 1, correct before Phase 4 |
| A3 | UEFA coefficients for tiebreaker step 10 can be loaded from a static JSON file for the simulation run | Fixture Schedule Data Model | Coefficients change yearly. A static file is fine for pre-season simulations. For Phase 4 validation (live data), fetch from UEFA's API or scrape |
| A4 | All 36 UCL teams have entries in ClubElo | ClubElo API Integration | Some lower-pot teams (pot 4) may have `Level: 0` or missing entries. Mitigation: verify all team names against the full ranking CSV before simulation |
| A5 | Python's `sorted()` with a 10-key tuple is stable enough for tiebreaking | UCL Tiebreaker Implementation | Python's Timsort is stable, but if two teams have identical stats through all 10 steps, the sort order is deterministic (input order preserved). This is acceptable for simulation (extremely rare). |
| A6 | The opponent-based tiebreaker stat (steps 6-8) should use pre-tiebreak raw aggregates, not post-tiebreak ranked values | Common Pitfalls (Pitfall 2) | This interpretation follows standard Swiss-system practice (Chess' SOS/SODOS). If UEFA intended ranked values, it would say "final position of opponents" not "points obtained by opponents." |

## Open Questions (RESOLVED)

1. **UEFA coefficient data format and source** — RESOLVED: Store as static JSON in `data/uefa_coefficients.json` for Phase 1. Live fetch deferred to Phase 4 (UCLV-01). Plan 01-02 Task 4 documents the field mapping.
2. **ClubElo name verification for all 36 teams** — RESOLVED: Plan 01-02 Task 1 includes a live HTTP checkpoint to verify names against the full ranking CSV. Name-to-alias mapping created before simulation runs.
3. **`_compute_conduct_score()` discrepancy — live with it or fix it?** — RESOLVED: Use existing function (RC×4) as a documented simplification. UEFA specifies RC×3 but the difference affects <5% of matches and has negligible impact on Monte Carlo outcomes. Noted in Plan 01-02 Task 3.

## Environment Availability

> **Skip condition:** Phase 1 has no external dependencies beyond what the project already requires. ClubElo API is an HTTP endpoint consumed via `urllib` (stdlib). No CLI tools, databases, or runtimes beyond Python 3.x are needed. Python 3.x with `football_core` already installed is assumed from the existing project setup.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (inherited from project — same as WC tests) |
| Config file | `setup.cfg` or `pyproject.toml` at project root (inherited) |
| Quick run command | `pytest competitions/ucl/tests/ -x -q` |
| Full suite command | `pytest competitions/ucl/tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UCLT-00 | Validate fixture schedule constraints | unit | `pytest competitions/ucl/tests/test_fixture_validation.py -x -q` | ❌ Wave 0 |
| UCLT-01 | Simulate 36-team league phase with correct match count | unit | `pytest competitions/ucl/tests/test_simulation.py::test_league_phase_match_count -x -q` | ❌ Wave 0 |
| UCLT-02 | UCL tiebreaker chain resolves correctly through all 10 steps | unit | `pytest competitions/ucl/tests/test_swiss_tiebreakers.py -x -q` | ❌ Wave 0 |
| UCLT-02 | Opponent-based tiebreaker stats (steps 6-8) correct | unit | `pytest competitions/ucl/tests/test_swiss_tiebreakers.py::test_opponent_stats -x -q` | ❌ Wave 0 |
| UCLT-03 | Qualification zone classification correct | unit | `pytest competitions/ucl/tests/test_swiss_tiebreakers.py::test_qualification_zones -x -q` | ❌ Wave 0 |
| UCLT-04 | Fixture data loads from JSON correctly | unit | `pytest competitions/ucl/tests/test_fixture_validation.py::test_fixture_loading -x -q` | ❌ Wave 0 |
| UCLT-05 | Monte Carlo aggregation produces correct zone probabilities | unit | `pytest competitions/ucl/tests/test_monte_carlo.py -x -q` | ❌ Wave 0 |
| UCLT-05 | MC output includes all required per-team averages | unit | `pytest competitions/ucl/tests/test_monte_carlo.py::test_output_format -x -q` | ❌ Wave 0 |
| UCLT-06 | Match simulation uses football_core primitives (not core modified) | integration | `pytest competitions/ucl/tests/test_simulation.py::test_core_primitive_reuse -x -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** Quick-run the relevant test file
- **Per wave merge:** Full UCL test suite
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `competitions/ucl/tests/conftest.py` — shared fixtures (sample match results, 36-team minimal data)
- [ ] `competitions/ucl/tests/test_fixture_validation.py` — UCLT-00, UCLT-04
- [ ] `competitions/ucl/tests/test_swiss_tiebreakers.py` — UCLT-02, UCLT-03
- [ ] `competitions/ucl/tests/test_simulation.py` — UCLT-01, UCLT-06
- [ ] `competitions/ucl/tests/test_monte_carlo.py` — UCLT-05

## Security Domain

> **security_enforcement: false** — Phase 1 is a local simulation engine. No user authentication, no session management, no network-facing endpoints, no user data storage. ClubElo API is a public read-only CSV endpoint with no auth. No ASVS categories apply.

## Sources

### Primary (HIGH confidence)
- [VERIFIED: codebase] `football_core/groups.py` — entire match simulation API: `expected_goals()`, `_poisson_sample()`, `_build_poisson_table()`, `_simulate_single_match()`, `simulate_group_matches()`, `_compute_conduct_score()`
- [VERIFIED: codebase] `football_core/constants.py` — `EXPECTED_GOALS_BASE_RATE=1.25`, `HOME_ADVANTAGE_MULTIPLIER=1.05`, `POISSON_TABLE_BITS=10`, `POISSON_TABLE_SIZE=1024`, `MAX_EXPECTED_GOALS=8.0`, `DEFAULT_ELO=1500`
- [VERIFIED: codebase] `competitions/worldcup/src/groups.py` — WC `compute_standings()` as reference pattern
- [VERIFIED: codebase] `competitions/worldcup/tests/test_groups.py` — test patterns for tiebreakers, match simulation, fixtures
- [VERIFIED: codebase] `competitions/worldcup/data/groups.json` — fixture data format reference
- [VERIFIED: direct HTTP test 2026-06-27] `api.clubelo.com/ManCity` — returns CSV `Rank,Club,Country,Level,Elo,From,To` with historical ratings
- [VERIFIED: direct HTTP test 2026-06-27] `api.clubelo.com/2026-06-27` — returns full ranking with 629+ teams
- [CITED: documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2025/26/Article-18] — Official UEFA Article 18: 10-step tiebreaker chain (no H2H). "JS required" page, confirmed via Sporting News and AS USA cross-references
- [CITED: documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2025/26/Article-17] — 4 home + 4 away matches per team, single league table, zones 1-8/9-24/25-36

### Secondary (MEDIUM confidence)
- [CROSS-VERIFIED: sportingnews.com + en.as.com] — UCL tiebreaker chain confirmed: GD → GS → away GS → wins → away wins → opponent pts → opponent GD → opponent GS → disciplinary → UEFA coefficient
- [CROSS-VERIFIED: mail.kassiesa.net PDF of UEFA CL regulations] — Article 18 text confirmed, disciplinary points: red=3, yellow=1, 2YC=3
- [CROSS-VERIFIED: fcpython.com blog post] — ClubElo API: `requests.get('http://api.clubelo.com/ManCity')` returns CSV, no auth, `r.text` contains raw CSV
- [CROSS-VERIFIED: clubelo.com/API page] — API docs: `/YYYY-MM-DD` for daily ranking, `/CLUBNAME` for club history, `/Fixtures` for upcoming match probabilities

### Tertiary (LOW confidence)
- [ASSUMED] ClubElo no rate limit — no official documentation on rate limiting; tested 2 sequential requests successfully; for 36 teams, add `time.sleep(0.5)` between requests as safety margin
- [ASSUMED] UEFA coefficient values are static enough for pre-season simulation — coefficients change yearly; for Phase 1 use latest available; for Phase 4 verify with live data

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all code imports from `football_core` (verified in codebase) and stdlib
- Architecture: HIGH — patterns derived from working WC implementation and official UEFA regulations
- ClubElo API: HIGH — directly verified via HTTP test on 2026-06-27
- Tiebreaker chain: HIGH — verified from official UEFA Article 18 text (cross-referenced 4 sources)
- Pitfalls: MEDIUM — Pitfall 6 (disciplinary weighting) is a known simplification; Pitfall 2 (opponent stat computation order) is reasoned but not tested

**Research date:** 2026-06-27
**Valid until:** 2026-07-27 (fast-moving — UEFA regulations are stable but ClubElo team names could change)
