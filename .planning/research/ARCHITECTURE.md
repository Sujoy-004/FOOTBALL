# Architecture Research: 48-Team Format Integration (v1.1)

**Domain:** FIFA World Cup 2026 dynamic prediction — 48-team group stage + Annex C R32 routing
**Researched:** 2026-06-14
**Mode:** Ecosystem (architecture dimension — v1.1 migration)
**Overall confidence:** HIGH

## Executive Summary

This document addresses the specific architectural changes needed to migrate the existing v1.0 knockout-only predictor (32 teams, R16→FINAL) to the full v1.1 48-team FIFA 2026 format (12 groups of 4, R32→R16→QF→SF→FINAL). The investigation confirms earlier assumptions in RESPONSE.md with minor corrections, and surfaces one previously underappreciated complexity: **the group stage requires a score-producing match model (Poisson or equivalent) rather than the current binary win/loss Elo model**, because goal differential is the primary tiebreaker for both within-group standings and cross-group third-place ranking.

The v1.0 architecture's five-layer decomposition (Fetcher → State → Elo → Simulator → Output) remains valid, but the Simulator layer gains two new internal stages: (1) a round-robin group simulation engine with tiebreaker chains, and (2) an Annex C lookup resolver that maps advancing third-place teams to R32 slots. The existing knockout traversal code (`_simulate_r16`, `_simulate_knockout_round`) can be reused with minimal changes.

**Key architectural decision:** A new `src/groups.py` module is recommended (not extending `src/simulation.py` directly), because the group stage engine is self-contained, has different data inputs (groups.json, annex_c.json), and its complexity (72 matches, tiebreaker chains, cross-group ranking) warrants separation of concerns.

---

## 1. Data Model Changes

Three new data files, one modified file:

### 1.1 `data/groups.json` — NEW (12 groups × 4 teams)

```json
{
  "groups": {
    "A": {
      "teams": ["Mexico", "South Africa", "South Korea", "Czechia"],
      "matches": [
        {"match_id": "GS_A_01", "team_a": "Mexico", "team_b": "South Korea", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_02", "team_a": "South Africa", "team_b": "Czechia", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_03", "team_a": "Mexico", "team_b": "Czechia", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_04", "team_a": "South Korea", "team_b": "South Africa", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_05", "team_a": "Mexico", "team_b": "South Africa", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_06", "team_a": "South Korea", "team_b": "Czechia", "winner": null, "score_a": null, "score_b": null}
      ]
    },
    "B": { ... },
    ...
    "L": { ... }
  }
}
```

**Design rationale:**
- Groups are stored as an object keyed by letter (A–L), not an array — allows O(1) lookup by group letter during Annex C resolution
- Each group contains its full 6-match round-robin schedule (3 rounds, 2 matches per round)
- `score_a`/`score_b` capture actual scores for real matches; `null` indicates not yet played
- Team order in `teams` array is seeding order from FIFA draw, not ranking — affects which team is `team_a`/`team_b` in each match

**Validation rules (to add to `state.validate_groups()`):**
- Exactly 12 groups (A–L)
- Each group has exactly 4 teams (no duplicates across groups)
- Each group has exactly 6 matches with unique `match_id` within format `GS_{letter}_{NN}`
- All team names in matches reference valid team names in `teams.json`
- No circular match references (trivial — no source_matches in group stage)

**Confidence:** HIGH — structure aligns with RESPONSE.md and verified against FIFA 2026 regulations.

### 1.2 `data/bracket.json` — MODIFIED (40 matches vs current 23)

**Current v1.0 structure** (23 matches, R16→FINAL):
```json
{"match_id": "R16_1", "round": "R16", "team_a": "Argentina", "team_b": "Nigeria", "source_matches": null, "winner": null}
```

**Proposed v1.1 structure** (40 matches, R32→FINAL):

```json
[
  // ── Round of 32 (16 matches: M73–M88) ──
  // Three slot types coexist:
  // Type 1: Runner-up vs Runner-up (4 matches)
  {"match_id": "M73", "round": "R32",
   "home": {"kind": "group_position", "group": "A", "position": 2},
   "away": {"kind": "group_position", "group": "B", "position": 2},
   "winner": null},
  // Type 2: Group Winner vs Runner-up (4 matches)
  {"match_id": "M75", "round": "R32",
   "home": {"kind": "group_position", "group": "F", "position": 1},
   "away": {"kind": "group_position", "group": "C", "position": 2},
   "winner": null},
  // Type 3: Group Winner vs Annex C 3rd-place (8 matches)
  {"match_id": "M74", "round": "R32",
   "home": {"kind": "group_position", "group": "E", "position": 1},
   "away": {"kind": "annex_c_third", "group_winner": "E"},
   "winner": null},

  // ── Round of 16 (8 matches: M89–M96) ──
  {"match_id": "M89", "round": "R16",
   "source_matches": ["M74", "M77"],
   "winner": null},
  {"match_id": "M90", "round": "R16",
   "source_matches": ["M73", "M75"],
   "winner": null},

  // ── Quarterfinals (4 matches) ──
  {"match_id": "QF_1", "round": "QF",
   "source_matches": ["M89", "M90"],
   "winner": null},

  // ── Semifinals (2 matches) ──
  {"match_id": "SF_1", "round": "SF",
   "source_matches": ["QF_1", "QF_2"],
   "winner": null},

  // ── Third Place Match (1 match) ──
  {"match_id": "TPP", "round": "TPP",
   "source_matches": ["SF_1", "SF_2"],
   "winner": null},

  // ── Final (1 match) ──
  {"match_id": "FINAL", "round": "FINAL",
   "source_matches": ["SF_1", "SF_2"],
   "winner": null}
]
```

**Slot type design:**

| Slot Kind | Meaning | Example | Resolved By |
|-----------|---------|---------|-------------|
| `group_position` | Known finishing position from a group | `{"group": "F", "position": 1}` → Group F winner | Group standings directly |
| `annex_c_third` | Third-place team routed via Annex C | `{"group_winner": "E"}` → the 3rd-placed team assigned to face Group E's winner | Annex C lookup table |

**Key insight:** The `group_position` and `annex_c_third` slots are **pre-MC-resolved** — they are resolved to actual team names once per MC iteration after group simulation. The existing `source_matches` wiring (R16 onward) is **unchanged** from v1.0.

**Bracket validation additions** (to `state.py`):
- Every R32 match must have exactly `home`/`away` slots (not `team_a`/`team_b`)
- Every R16+ match must have exactly `source_matches` (not `home`/`away`)
- R32 slots with `kind: "group_position"` must reference valid groups (A–L) and valid positions (1 or 2)
- R32 slots with `kind: "annex_c_third"` must reference a group winner group (one of: A, B, D, E, G, I, K, L — the 8 groups whose winners host third-place teams)
- All M-match references are reachable (no orphans)
- `source_matches` list length matches expected: 2 for all knockout rounds (R16→FINAL), 2 for TPP
- Total count: 40 matches

**R32 structure** (verified against tournamental repo and Wikipedia):

```
M73: A2 vs B2       M81: D1 vs 3rd(D)
M74: E1 vs 3rd(E)   M82: G1 vs 3rd(G)
M75: F1 vs C2       M83: H1 vs J2
M76: C1 vs F2       M84: K2 vs L2
M77: I1 vs 3rd(I)   M85: B1 vs 3rd(B)
M78: E2 vs I2       M86: J1 vs H2
M79: A1 vs 3rd(A)   M87: K1 vs 3rd(K)
M80: L1 vs 3rd(L)   M88: D2 vs G2
```

**R16 wiring** (FIFA Article 12.7, fixed):

```
M89: W74 vs W77     M93: W83 vs W84
M90: W73 vs W75     M94: W81 vs W82
M91: W76 vs W78     M95: W86 vs W88
M92: W79 vs W80     M96: W85 vs W87
```

**Confidence:** HIGH — structure verified against tournamental `rewrite-r32-fixtures.mjs`, tournamental `fifa-wc-2026-fixtures.json`, Wikipedia 2026 knockout stage, and RESPONSE.md.

### 1.3 `data/annex_c.json` — NEW (495 entries)

```json
{
  "_meta": {
    "source": "FIFA 2026 Competition Regulations Annex C",
    "verified_against": "tournamental packages/bracket-engine/data/fifa-2026-annex-c-assignments.json",
    "combinations": 495
  },
  "A,B,C,D,E,F,G,H": {
    "1A": "3H", "1B": "3G", "1D": "3B", "1E": "3C",
    "1G": "3A", "1I": "3F", "1K": "3D", "1L": "3E"
  },
  ...
}
```

**Key semantics:**
- Key is **sorted, comma-separated group letters** of the 8 groups whose third-placed teams advance
- Example: `"C,D,E,F,G,I,K,L"` means third-place teams from groups C, D, E, F, G, I, K, L advance
- Value is a map of group winner keys to third-place group letters
- `"1E": "3D"` means: the Group E winner (1E) faces the third-place team from Group D (3D) in R32
- The 8 keys in each value correspond to the 8 matches where a group winner hosts a third-place team (M74, M77, M79, M80, M81, M82, M85, M87)

**Lookup algorithm (pseudocode):**
```python
def lookup_annex_c(advancing_groups: set[str], table: dict) -> dict[str, str]:
    """Return {group_winner: third_place_group} mapping."""
    key = ",".join(sorted(advancing_groups))
    return table[key]  # e.g., {"1A": "3H", "1B": "3G", ...}
```

**Verification:** The tournamental repo data shows all 495 entries. File size estimate: ~120KB.

**Confidence:** HIGH — sourced from tournamental repo which captured from cup-predictor.com API; RESPONSE.md independently confirms the 495-entry approach.

### 1.4 `data/teams.json` — EXTENDED (32 → 48 teams)

Add 16 teams with Elo ratings. Same structure as current:
```json
{
  "Mexico": {"elo": 1850},
  "South Africa": {"elo": 1700},
  ...
}
```

---

## 2. Simulation Pipeline Changes

### 2.1 Current v1.0 Pipeline

```
run_simulation(teams, bracket, played, iterations=50000)
  │
  ├── _build_round_map(bracket) → round_map (R16/QF/SF/FINAL)
  ├── elo_ratings = {team: elo}
  │
  └── for _ in range(iterations):
        ├── _simulate_r16()      → winner_progression[R16_1..R16_8]
        ├── _simulate_round(QF)  → winner_progression[QF_1..QF_4]
        ├── _simulate_round(SF)  → winner_progression[SF_1..SF_2]
        └── _simulate_round(FINAL) → winner_progression[FINAL]
              │
              └── count champion
```

### 2.2 Proposed v1.1 Pipeline

```
run_full_simulation(teams, groups, bracket, annex_c, played, iterations)
  │
  ├── elo_ratings = {team: elo}
  │
  └── for _ in range(iterations):
        │
        ├── 1. SIMULATE GROUPS (72 matches)
        │      simulate_group_matches(groups, elos, played, rng)
        │      → results: {group: {match_id: {team_a, team_b, score_a, score_b}}}
        │
        ├── 2. COMPUTE STANDINGS (12 groups)
        │      compute_standings(results)
        │      → standings: {group: [{team, pts, gd, gs}, ...]} (sorted by position)
        │
        ├── 3. SELECT ADVANCERS (24 + 8 = 32 teams)
        │      select_advancers(standings)
        │      → advancing: {group: {1: team, 2: team, 3: team|null}}
        │      → third_place_rankings: [{group, team, pts, gd, gs, conduct}, ...]
        │      (top 8 third-placed teams identified via 5-tier tiebreaker)
        │
        ├── 4. RESOLVE ANNEX C (R32 matchups)
        │      resolve_r32_matchups(advancing, annex_c)
        │      → resolved_r32: [(M73, team_a, team_b), ...] (16 resolved matches)
        │
        ├── 5. SIMULATE KNOCKOUT (40 matches)
        │      simulate_r32(resolved_r32, ...)  → winner_progression[M73..M88]
        │      simulate_r16(round_map, ...)     → winner_progression[M89..M96]
        │      simulate_knockout_round(QF, ...)  → winner_progression[QF_1..QF_4]
        │      simulate_knockout_round(SF, ...)  → winner_progression[SF_1..SF_2]
        │      simulate_knockout_round(TPP, ...) → winner_progression[TPP]
        │      simulate_knockout_round(FINAL, ...) → winner_progression[FINAL]
        │
        └── 6. RECORD CHAMPION (and stage counts)
```

### 2.3 Key Pipeline Differences

| Aspect | v1.0 | v1.1 |
|--------|------|------|
| **Entry point** | `run_simulation(teams, bracket, played)` | `run_full_simulation(teams, groups, bracket, annex_c, played)` |
| **Group stage** | Not simulated | 72 round-robin matches per iteration |
| **Match model** | Binary win/loss (Elo prob) | Score-producing (draws, GD) |
| **Knockout entry** | Hardcoded R16 team names | R32 resolved from group standings |
| **Rounds simulated** | 15 matches | 103 matches |
| **Knockout traversal** | `_simulate_r16` + rounds loop | `_simulate_r32` (new) + existing rounds |
| **Champion tracking** | Same | Same (counts FINAL winner) |

### 2.4 Integrating with the Existing Main Loop

The current `main.py` calls:
```python
probs = run_simulation(teams, bracket, played, iterations=50000, seed=seed)
```

For v1.1, this becomes:
```python
probs = run_full_simulation(
    teams, groups, bracket, annex_c, played,
    iterations=50000, seed=seed,
)
```

The `_run_iteration()` function in `main.py` needs new load calls:
```python
groups = state.load_groups()
annex_c = state.load_annex_c()
```

And the output header updates to show the 104-match total.

---

## 3. Annex C Routing — Architecture

### 3.1 Algorithm

```
Input:  standings (12 groups, positions 1-4 determined)
Output: resolved_r32 (list of 16 (match_id, team_a, team_b) tuples)

Step 1: Extract third-placed teams
  third_placed = []
  for group in A..L:
      team_data = standings[group].third_place  # position 3
      third_placed.append((group, team_data))

Step 2: Rank third-placed teams (5-tier tiebreaker)
  sort third_placed by:
      primary:   points (desc)
      secondary: goal_difference (desc)
      tertiary:  goals_scored (desc)
      quaternary: conduct_score (desc, fair play)
      quinary:   FIFA ranking (desc = higher rank = better)

Step 3: Select top 8
  advancing_third = third_placed[:8]
  advancing_groups = {group for (group, _) in advancing_third}

Step 4: Build Annex C key
  key = ",".join(sorted(advancing_groups))
  annex_assignment = annex_c_table[key]
  # annex_assignment is {"1A": "3H", "1B": "3G", ...}

Step 5: Resolve 8 third-place R32 matches
  For each (winner_group, third_group) in annex_assignment:
      winner_team = standings[winner_group].first_place
      third_team = standings[third_group].third_place
      find corresponding R32 match in bracket where
        home.kind == "annex_c_third" AND home.group_winner == winner_group
      resolved = (match_id, winner_team, third_team)

Step 6: Resolve 8 non-third-place R32 matches
  For each R32 match with group_position slots:
      home_team = standings[match.home.group][match.home.position]
      away_team = standings[match.away.group][match.away.position]
      resolved = (match_id, home_team, away_team)
```

### 3.2 The Sorted-Key Property

The Annex C key is **sorted** group letters (comma-separated). This is why `"CDEFGIKL"` (not `"DEFGCIKL"`). The canonical form is always ascending alphabetical order. The lookup table's keys are pre-sorted — the resolver must also sort before lookup.

**Critical correctness property:** The sort is **lexicographic** (string sort by single letter), which for single-letter group codes A–L is the same as alphabetical order. This is stable across any 8-group combination.

### 3.3 Group Winner → Third-Place Mapping Pattern

From the tournamental data, the 8 group winners that host third-place teams are: **A, B, D, E, G, I, K, L**. These are the same groups every time — the Annex C table only varies *which* third-placed group each faces.

Groups C, F, H, J never host third-place teams in R32. Their group winners face runners-up from paired groups: C1↔F2, F1↔C2, H1↔J2, J1↔H2.

**Architectural implication:** The R32 bracket structure is itself fixed in *which* matches involve third-place teams vs. group_position vs. runner-up pairings. Only the team identities change. This means `bracket.json` can be fully defined at build time — no dynamic generation needed.

---

## 4. R16 Bracket Wiring (FIFA Article 12.7)

### 4.1 Fixed Wiring

The R16 bracket path is **immutable** — only the team identities flowing from R32 change:

```
M89 ← W(M74) vs W(M77)
M90 ← W(M73) vs W(M75)
M91 ← W(M76) vs W(M78)
M92 ← W(M79) vs W(M80)
M93 ← W(M83) vs W(M84)
M94 ← W(M81) vs W(M82)
M95 ← W(M86) vs W(M88)
M96 ← W(M85) vs W(M87)
```

### 4.2 How This Maps to source_matches

In `bracket.json`, the R16 matches use `source_matches` as follows:

| R16 Match | source_matches | Origin Type |
|-----------|----------------|-------------|
| M89 | ["M74", "M77"] | Both: winner vs 3rd (Annex C) |
| M90 | ["M73", "M75"] | M73: runner-up vs runner-up, M75: winner vs runner-up |
| M91 | ["M76", "M78"] | M76: winner vs runner-up, M78: runner-up vs runner-up |
| M92 | ["M79", "M80"] | Both: winner vs 3rd (Annex C) |
| M93 | ["M83", "M84"] | M83: winner vs runner-up, M84: runner-up vs runner-up |
| M94 | ["M81", "M82"] | Both: winner vs 3rd (Annex C) |
| M95 | ["M86", "M88"] | M86: winner vs runner-up, M88: runner-up vs runner-up |
| M96 | ["M85", "M87"] | Both: winner vs 3rd (Annex C) |

**Design implication:** The existing `_simulate_knockout_round()` function (which reads `source_matches` and resolves teams from `winner_progression`) works **unchanged** for R16 onward. The resolution chain is:

```
R32 match winners → winner_progression[M73..M88]
R16 source_matches → pulls from winner_progression[M73..M88]
R16 match winners → winner_progression[M89..M96]
(QF/SF/FINAL continue the same pattern)
```

### 4.3 Third-Place Match

The third-place match (TPP) is a new addition vs v1.0. It takes `source_matches` from both SF losers. Since the existing `_simulate_knockout_round` resolves `source_matches` by looking up `winner_progression[src]`, and the SF loser's entry in `winner_progression` is the winner of *that specific match*, we need to handle TPP differently.

**Approach:** Track not just winners but also the runner-up (loser of the SF). Modify `winner_progression` to store `{"winner": team, "runner_up": team}` for semifinal matches. The TPP reads `source_matches` → extracts `runner_up` from each.

Simpler alternative: **Track semifinal losers explicitly.** After each semifinal simulation, store the loser in a separate dict `semifinal_losers`. TPP uses `semifinal_losers[src]`.

```
Semifinal: SF_1 → TeamA beats TeamB → winner_progression[SF_1] = TeamA, sf_losers[SF_1] = TeamB
TPP: source_matches = ["SF_1", "SF_2"] → teams = [sf_losers["SF_1"], sf_losers["SF_2"]]
```

This is the simplest integration with the existing code.

---

## 5. Module Boundaries

### 5.1 Proposed Module Map

```
src/
├── __init__.py
├── constants.py       # DATA_DIR updated; GROUP_COUNT, etc.
├── elo.py             # Unchanged (pure math)
├── state.py           # EXTENDED: load_groups(), load_annex_c(), validate_groups()
├── groups.py          # NEW: group simulation + standings + Annex C resolver
├── simulation.py      # MODIFIED: run_full_simulation(), simulate_r32(), simulate_knockout_round()
├── fetcher.py         # MODIFIED: process_matches handles groups.json matches too
├── output.py          # MODIFIED: group standings display, updated header counts
```

### 5.2 `src/groups.py` — New Module

**Responsibility:** Group stage simulation, standings computation, tiebreaker enforcement, advancement selection, Annex C resolution.

**Functions:**

```python
def simulate_group_matches(
    groups: dict,
    teams: dict[str, dict],
    played: dict[str, dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
) -> dict[str, dict[str, dict]]:
    """Simulate unplayed group matches. Returns results per group.
    
    For each group, for each unplayed match (winner is None):
      1. Draw match score using goal model (Poisson from Elo)
      2. Record winner, score_a, score_b
      3. Add to played dict for this iteration
    For played matches (winner is not None), use actual result.
    
    Returns: {group_letter: {match_id: {team_a, team_b, score_a, score_b, winner}}}
    """
    ...

def compute_standings(
    results: dict[str, dict[str, dict]]
) -> dict[str, list[dict]]:
    """Compute sorted standings for each group.
    
    For each group:
      1. Accumulate points, GD, GS from results
      2. Sort by: points, H2H (if tied), H2H_GD, H2H_GS, GD, GS, conduct, FIFA rank
      3. Position 1-4
    
    Returns: {group_letter: [{team, pts, gd, gs, position}, ...]}
    """
    ...

def rank_third_placed(
    standings: dict[str, list[dict]]
) -> list[dict]:
    """Rank third-placed teams across all 12 groups.
    
    5-tier tiebreaker:
      1. Points
      2. Goal difference
      3. Goals scored
      4. Fair play conduct score
      5. FIFA ranking
    
    Returns: [{group, team, pts, gd, gs, conduct}, ...] sorted desc
    """
    ...

def select_advancers(
    standings: dict[str, list[dict]],
    third_ranked: list[dict],
) -> dict[str, dict[int, str]]:
    """Select top 2 per group + top 8 third-placed.
    
    Returns: {group_letter: {1: winner_team, 2: runner_up_team, 3: third_team_or_null}}
    """
    ...

def resolve_r32_matchups(
    bracket: list[dict],
    standings: dict[str, list[dict]],
    advancers: dict[str, dict[int, str]],
    annex_c: dict,
) -> list[dict]:
    """Resolve all 16 R32 matches to actual team names.
    
    For each R32 match in bracket:
      - If slot.kind == "group_position": look up from advancers
      - If slot.kind == "annex_c_third": look up via Annex C → advancers
      - Return match dict with team_a, team_b filled
    
    Returns: list of match dicts with {match_id, team_a, team_b, winner=None}
    """
    ...
```

### 5.3 `src/simulation.py` — Modifications

**New function: `simulate_r32()`**
```python
def _simulate_r32(resolved_r32, played, winner_progression, _rand, _exp, elo_ratings):
    """Simulate R32 matches from resolved matchups.
    
    Identical logic to current _simulate_r16() — the resolved matchups
    have team_a and team_b filled. Just iterate and simulate.
    """
```

**Modified: `run_simulation()` → `run_full_simulation()`**
```python
def run_full_simulation(
    teams: dict[str, dict],
    groups: dict,
    bracket: list[dict],
    annex_c: dict,
    played: dict[str, dict],
    iterations: int = 50000,
    seed: int | None = None,
) -> dict[str, dict[str, float]]:
    """Full 48-team tournament simulation.
    
    Per iteration:
      1. simulate_group_matches() → results
      2. compute_standings() → standings
      3. rank_third_placed() → third_ranked
      4. select_advancers() → advancers
      5. resolve_r32_matchups() → resolved_r32
      6. _simulate_r32(resolved_r32, ...)
      7. _simulate_r16(round_map, ...)  # unchanged
      8. _simulate_knockout_round(QF, ...)  # unchanged
      9. _simulate_knockout_round(SF, ...)  # unchanged
     10. _simulate_tpp()  # new — third place match
     11. _simulate_knockout_round(FINAL, ...)  # unchanged
    
    Returns: {team: {qf: float, sf: float, final: float, champion: float}}
    """
```

### 5.4 Existing Code Reuse Summary

| Component | v1.0 Code | v1.1 Status | Changes Needed |
|-----------|-----------|-------------|----------------|
| `_simulate_r16()` | 10 lines | Replaced by `_simulate_r32()` | New function; R16 now uses source_matches like QF |
| `_simulate_knockout_round()` | 14 lines | Reused for QF/SF/FINAL | Add TPP handling; runner-up tracking |
| `run_simulation()` | 42 lines | Extended to `run_full_simulation()` | Add group pre-stage before knockout loop |
| `_build_round_map()` | 10 lines | Extended | Handle R32 round in round_map |
| `elo.py` | 89 lines | Unchanged | Pure math; no changes needed |
| `state.py` | 240 lines | Extended | Add load_groups, load_annex_c, validators |
| `fetcher.py` | 156 lines | Extended | Match detection must handle group match_ids too |
| `output.py` | 204 lines | Extended | Group standings display; updated match counts |
| `main.py` | 267 lines | Extended | Load groups.json, annex_c.json on startup |

### 5.5 Dependency Graph (v1.1)

```
main.py
  ├── groups.py → elo.py, state.py (for data loading)
  ├── simulation.py → elo.py, groups.py (for R32 resolution)
  ├── state.py → json, os
  ├── fetcher.py → state.py, constants.py
  ├── elo.py → (none, pure math)
  └── output.py → constants.py

Dependency direction: main.py → groups.py → simulation.py → elo.py
                                        ↕ (circular avoided: groups.py doesn't import simulation.py)
```

No circular dependencies. `groups.py` is consumed by `simulation.py` but does not import `simulation.py`.

---

## 6. Goal Model for Group Stage (Complexity Flag)

The v1.0 Elo model produces a **binary outcome** (win/loss) — sufficient for knockout where draws resolve to penalties. But the group stage requires **actual scores** to compute goal difference, which is the primary tiebreaker in both within-group standings (step 4) and third-place ranking (step 2).

### 6.1 Options

| Approach | Complexity | Scorelines | GD Accuracy | Dependencies |
|----------|-----------|------------|-------------|--------------|
| **Null model**: random score | Very Low | Random 0-0 to 4-4 | Poor (no team skill signal) | None |
| **Elo→Poisson**: `λ = base_rate × 10^(Δelo/400)` | Medium | Realistic distributions | Good | None (custom math) |
| **Dixon-Coles** (full bivariate) | High | Correlated scorelines | Best | numpy/scipy |
| **Elo→scorebands**: discretized distribution | Low-Medium | Binned score outcomes | Fair (limited to bins) | None |

### 6.2 Recommendation: Elo→Poisson (Medium Complexity)

```python
def expected_goals(rating_a: float, rating_b: float, base_rate: float = 1.2) -> float:
    """Expected goals for team A against team B."""
    return base_rate * (10 ** ((rating_a - rating_b) / 400))

def simulate_match_score(rating_a: float, rating_b: float, rng) -> tuple[int, int]:
    lambda_a = expected_goals(rating_a, rating_b)
    lambda_b = expected_goals(rating_b, rating_a)
    score_a = rng.poisson(lambda_a)  # Using random.poisson? No — need custom Poisson
    score_b = rng.poisson(lambda_b)
    return score_a, score_b
```

**Note:** Python's `random` module does **not** have a Poisson sampler. Options:
1. **Implement a Poisson CDF table** (pre-compute, ~10KB) and invert — no dependency
2. **Use `numpy.random.poisson`** — adds numpy dependency
3. **Approximate with binomial** — sacrifices accuracy

**Recommendation for MVP:** Implement a Poisson sampler using the Knuth algorithm on `random.random()` — about 15 lines of code. No dependency needed. Accuracy is sufficient for Monte Carlo.

### 6.3 Draw Handling

In the group stage, draws occur. The current Elo model doesn't produce a draw probability. Options:
1. **Elo→draw threshold:** if `|expected_a - 0.5| < T`, treat as draw (crude)
2. **Poisson→draw:** match is a draw if both teams score the same (natural — falls out of Poisson scorelines)
3. **Separate draw probability:** estimate draw probability from Elo difference using historical calibration

**Recommendation:** Use Poisson scorelines (option 2). Draws fall out naturally when `score_a == score_b`. This is the cleanest approach and matches how real tournaments work.

---

## 7. Performance Projection

### 7.1 Current Baseline

| Metric | v1.0 (15 matches, 50K iterations) |
|--------|-----------------------------------|
| Match simulations | 750,000 |
| Time | ~1.3s |
| Operations per second | ~577K matches/s |

### 7.2 v1.1 Projection

| Stage | Matches/Iter | Operations |
|-------|-------------|------------|
| Group stage | 72 | 72 score simulations |
| Standings | — | 12× sorting (4 teams) |
| Third-place ranking | — | 1× sorting (12 teams) |
| Annex C lookup | — | 1× dict lookup |
| R32 | 16 | 16 binary sims |
| R16 | 8 | 8 binary sims |
| QF | 4 | 4 binary sims |
| SF | 2 | 2 binary sims |
| TPP | 1 | 1 binary sim |
| FINAL | 1 | 1 binary sim |
| **Total** | **104** | **~110 ops** |

**Projected time at 50K iterations:**
- Match simulation (104 × 50K = 5.2M): ~9s (linear extrapolation from 1.3s × 7×)
- Standings + tiebreaker (~6K sort ops): ~0.5s
- Total: **~10-15s**

**Implication:** At 10-15s per simulation cycle, the 60s poll interval leaves 45-50s headroom. Acceptable for MVP. If profiling shows >20s, consider:
1. Pre-computing Poisson CDF tables (avoids per-call Poisson generation)
2. Moving group simulation to numpy vectorization

### 7.3 Memory

- Group simulation results: ~1,200 objects per iteration (72 matches × ~16 fields) → garbage collected each iteration
- Annex C table: ~120KB JSON → ~1MB in Python memory → negligible
- Total per-iteration heap: ~50KB → well within Python limits

---

## 8. State Validation — Additional Checks

### 8.1 `validate_groups(groups: dict) -> None`

```python
def validate_groups(groups: dict) -> None:
    """Validate groups.json structure.
    
    Raises ValueError if:
    - Not exactly 12 groups (A–L)
    - Any group missing 'teams' or 'matches' keys
    - Group doesn't have exactly 4 teams
    - Group doesn't have exactly 6 matches
    - Match IDs not unique within group
    - Any team name not in teams.json
    """
```

### 8.2 `validate_annex_c(annex_c: dict) -> None`

```python
def validate_annex_c(annex_c: dict) -> None:
    """Validate annex_c.json structure.
    
    Raises ValueError if:
    - Not exactly 495 entries
    - Any key has wrong number of groups (not 8)
    - Any key contains invalid group letters (not A–L)
    - Any value doesn't have exactly 8 assignments
    - Any assignment references unknown group
    """
```

### 8.3 `validate_bracket()` — Extended

Add checks for v1.1 bracket structure:
- R32 matches have `home`/`away` slot descriptors (not raw team names)
- R16+ matches have `source_matches`
- All `group_position` slots reference valid groups (A–L) and positions (1 or 2)
- All `annex_c_third` slots reference valid group winners (A, B, D, E, G, I, K, L)
- Exactly 8 R32 matches with `annex_c_third` slots
- Exactly 40 total matches

---

## 9. Tiebreaker Implementation Detail

### 9.1 Within-Group Tiebreaker (7-step)

For teams tied on points within a group:

```python
def _sort_group_standings(teams: list[dict]) -> list[dict]:
    """Sort 4 teams in a group using FIFA 7-step tiebreaker.
    
    1. Points in matches between tied teams (H2H)
    2. Goal difference in H2H matches
    3. Goals scored in H2H matches
    4. Goal difference in ALL group matches
    5. Goals scored in ALL group matches
    6. Fair play conduct score (lower is better)
    7. FIFA/Coca-Cola ranking (higher is better)
    
    Implemented as iterative narrowing: start with all 4, apply 
    tiebreaker chain, narrow tied clusters at each step.
    """
```

**Implementation pattern:** For tiebreaker steps 1–3 (H2H), we need to identify *which* teams are tied and then consider *only matches among those tied teams*. Steps 4–7 apply to all group matches.

**Key edge case:** If a 3-way tie is partially resolved (e.g., step 1 leaves 2 still tied), continue to step 2 for those 2 only. Do not reset to all tied teams.

### 9.2 Third-Place Ranking (5-step)

Simpler — all 12 teams ranked together:

```python
def _sort_third_placed(teams: list[dict]) -> list[dict]:
    """Sort 12 third-placed teams.
    
    1. Points in all group matches
    2. Goal difference in all group matches
    3. Goals scored in all group matches
    4. Fair play conduct score
    5. FIFA ranking
    """
```

No H2H needed (teams didn't play each other). Pure multi-key sort.

---

## 10. Integration Points with Fetcher and Main Loop

### 10.1 `fetcher.py` Changes

The fetcher currently matches API results to `bracket.json` matches via `_find_bracket_match()`. With groups.json, it must also match to group matches:

```python
def _find_group_match(home_norm: str, away_norm: str, groups: dict) -> str | None:
    """Find a group match by team pairing.
    
    Searches all 72 group matches. Returns match_id like "GS_A_01".
    """
```

The `process_matches()` function signature changes to accept `groups` as an optional parameter. If a match isn't found in the bracket, check groups. Mark found matches with their type (`"group"` or `"knockout"`).

### 10.2 `main.py` Changes

```python
def main() -> None:
    groups = state.load_groups()
    annex_c = state.load_annex_c()
    # (existing loads unchanged)
    
    # Pass to simulation
    probs = run_full_simulation(
        teams, groups, bracket, annex_c, played,
        iterations=50000, seed=args.seed,
    )
```

The output header updates to show:
- "Loaded 48 teams, 12 groups, 40 bracket matches, 72 group matches, 495 Annex C scenarios"

---

## 11. Phase Ordering for Implementation

Following the RESPONSE.md phase plan:

| Phase | Module | Delivers | Depends On |
|-------|--------|----------|------------|
| **7: Dataset** | `data/groups.json`, `data/annex_c.json`, `data/teams.json` (48) | All data files | None |
| **8: Group Engine** | `src/groups.py` | Group simulation, standings, tiebreakers, R32 resolution | Phase 7 |
| **9: Knockout Bracket** | `bracket.json` (40 matches), `simulation.py` (extended) | Full 48-team simulation loop | Phase 8 |
| **10: Integration** | `main.py`, `fetcher.py`, `output.py`, `state.py` | End-to-end pipeline | Phase 9 |

**Critical dependency:** Phase 7 must complete before Phase 8 (needs data shapes). Phase 8 must complete before Phase 9 (needs group engine). Phase 9 must complete before Phase 10 (needs full simulation working).

---

## 12. Anti-Patterns in Group Stage Simulation

### Anti-Pattern 1: Re-computing standings from scratch per MC iteration

**What people do:** Deep-copy the full group results dict and re-process everything.
**Why it's not a problem here:** 72 match results is tiny. Deep copy is fine at this scale. But avoid deep-copying the full groups.json structure every iteration — only copy the results dict.

### Anti-Pattern 2: H2H tiebreaker computed on full group instead of tied cluster

**What people do:** Re-sort all 4 teams at each tiebreaker step without narrowing.
**Why it's wrong:** A 3-way tie on points should be resolved via H2H among those 3, not all 4. The 4th team might have more points against the 3 but that's irrelevant.
**Correct approach:** Iteratively narrow the tied set. If 3 of 4 are tied on points, compute H2H among those 3 only. Continue narrowing.

### Anti-Pattern 3: Winner/stage counts in simulation.py tracking 104+ match winners

**What people do:** Track `winner_progression` for ALL matches including group matches.
**Why it's wasteful:** Group match winners aren't needed for knockout simulation. Only the standings output matters.
**Correct approach:** Don't put group match results into `winner_progression`. Use a separate `group_results` dict. Only start `winner_progression` at R32.

### Anti-Pattern 4: Hardcoding the 8 Annex C "winner groups" (A, B, D, E, G, I, K, L)

**What people do:** Writing `ASSIGNED_WINNER_GROUPS = ["A", "B", "D", "E", "G", "I", "K", "L"]` in Python code.
**Why it's brittle:** FIFA could change the Annex C structure. The Annex C data might change which groups host third-place teams.
**Correct approach:** Derive the set of winner groups from `annex_c.json` itself — they're the keys in each entry (`"1A", "1B", ...`). No hardcoding.

### Anti-Pattern 5: Poisson goal model with numpy dependency for MVP

**What people do:** `import numpy; numpy.random.poisson()` for scoreline generation.
**Why it's premature:** Adds numpy as a dependency for a single function. The Knuth algorithm for Poisson sampling is ~5 lines of pure Python. Evaluate numpy if profiling shows the Poisson sampler as a bottleneck (>20% of simulation time).

---

## 13. Scaling Considerations

| Concern | v1.0 (15 KO matches) | v1.1 (72 group + 31 KO + 1 TPP) |
|---------|----------------------|----------------------------------|
| **State size** | ~5KB JSON | ~25KB JSON (groups + annex_c) |
| **Simulation time** (50K, Python) | ~1.3s | ~10-15s (projected) |
| **MC iterations for stability** | 50K | 50K (same — limited by poll interval) |
| **Tiebreaker complexity** | None | 7-step within group + 5-step cross-group |
| **Match model** | Binary (win/loss) | Score-producing (Poisson) |
| **Data validation** | bracket only + playable check | groups + annex_c + bracket |
| **Output complexity** | Probability table | Group standings + probability table |

**Bottleneck projection:** The Poisson score generation for 72 group matches will be the heaviest single operation. If `simulate_group_matches()` takes >5s per iteration, pre-generate all group match scorelines as an array before the MC loop (generate once, reuse) — but note this reduces variance because the same "surprising" scorelines repeat.

**Alternative:** Accept the ~10-15s time. The poll interval is 60s, so there's 45-50s of idle time. Simulation speed isn't the bottleneck.

---

## 14. Sources

| Source | Type | Confidence | What It Provided |
|--------|------|------------|-----------------|
| RESPONSE.md (project root) | Project doc | HIGH | Full 48-team architecture plan, Annex C structure, R16 wiring |
| tournamental `rewrite-r32-fixtures.mjs` | GitHub code | HIGH | R32 structure (M73–M88 slot types confirmed) |
| tournamental `fifa-2026-annex-c-assignments.json` | GitHub data | HIGH | All 495 Annex C entries; slot assignment pattern |
| tournamental `fifa-wc-2026-fixtures.json` | GitHub data | HIGH | Full 104-match bracket structure (knockout) |
| `worldcup_predictor/src/simulation.py` | Existing code | HIGH | Current simulation pipeline; _simulate_r16, _simulate_knockout_round |
| `worldcup_predictor/src/state.py` | Existing code | HIGH | State persistence patterns; atomic writes; validation |
| `worldcup_predictor/data/bracket.json` | Existing data | HIGH | Current 23-match v1.0 bracket structure |
| `worldcup_predictor/main.py` | Existing code | HIGH | Main loop orchestration pattern |
| FIFA 2026 Regulations (Article 12.7) | Official PDF | HIGH | R16 wiring (M89–M96) |
| FIFA 2026 Regulations (Annex C) | Official PDF | HIGH | 495-entry third-place routing table |
| Wikipedia "2026 FIFA World Cup knockout stage" | Web | MEDIUM | R32 strategy, third-place advancement rules |
| worldcupwiki.com 2026 R32 rules | Web | MEDIUM | Third-place ranking criteria details |

---

*Architecture research for: 48-team World Cup simulation integration*
*Researched: 2026-06-14*
