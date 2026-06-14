# Pitfalls Research

**Domain:** CLI tournament predictor — adding group stage + R32 knockout to existing Monte Carlo simulator
**Researched:** 2026-06-14
**Confidence:** MEDIUM (code-verified for existing project; FIFA rules verified via official sources)

## Critical Pitfalls

### Pitfall 1: Tiebreaker Step Reversal — H2H vs. Overall GD

**What goes wrong:**
The simulation produces incorrect group standings because tiebreaker steps are applied in wrong order. A team that scored heavily against a weaker opponent leapfrogs a team that won the head-to-head match between them.

**Why it happens:**
FIFA **reversed** the tiebreaker order for 2026. In every prior World Cup (2018, 2022), tiebreakers started with overall goal difference. For 2026, head-to-head points come **first**. Any developer copying from a pre-2026 codebase or online example will get the order wrong. The Sporting News published the *old* order as late as June 2026. Many reference sources are contradictory.

**Official 7-step order (2026):**
1. Points in matches between tied teams (H2H)
2. Goal difference in matches between tied teams (H2H GD)
3. Goals scored in matches between tied teams (H2H GS)
4. Goal difference in all group matches (Overall GD)
5. Goals scored in all group matches (Overall GS)
6. Highest team conduct score (Fair play: −1 yellow, −3 2nd yellow/indirect red, −4 straight red, −5 yellow→red)
7. Most recent published FIFA/Coca-Cola Men's World Ranking

**Most common wrong order found in code:**
```
Overall GD → Overall GS → H2H → Fair play → FIFA rank
```
(This was the pre-2026 order. Five of the seven steps are wrong.)

**Multi-team tie edge case (critical):**
When 3+ teams tie on points, the tiebreaker is applied in rounds:
1. Apply all 7 steps to the entire tied group.
2. If step N separates one team from the others (e.g., H2H points: Team A has 4 pts, Teams B and C have 1 pt each), the separated team is ranked and **removed**.
3. Restart the tiebreaker from **step 1** for the remaining teams (B and C are now a 2-team tie — re-evaluate H2H between just them).
4. Repeat until all positions are resolved.

**Failing to restart from step 1** is the #1 bug in multi-team tiebreaker code. Example: Three teams on 5 points. A beats B, B beats C, C beats A. All H2H steps fail (circular). You proceed to Overall GD. One team gets separated. Now you *must* re-enter H2H for the remaining two — even though H2H already failed for the full group.

**How to avoid:**
- Write tiebreaker as a `resolve_standings(teams_in_group: list[TeamResult])` function that:
  1. Sorts by points descending.
  2. If ties exist, extracts tied subset.
  3. Applies `_break_tie(tied_teams)` = apply step sequence, if any step produces a strict ranking, assign positions and recurse with `_resolve_subgroup()` on any remaining ties.
  4. Do NOT flatten — recursion is required.
- Unit-test with:
  - 2-team tie (simple H2H)
  - 3-team circle (each beats one, loses to one)
  - 4-team tie (all draw with each other)
  - Fair play tiebreak scenario (Japan vs Senegal 2018 style)
  - Step 7 scenario (FIFA ranking tiebreak)

**Warning signs:**
- Group standings show "impossible" results (team with worse H2H ranked above team that beat them)
- Running 50K iterations produces NaN or non-sensical third-place selections
- Tests pass for 2-team ties but fail for 3-team ties

**Phase to address:**
Phase 8 (Group Stage Simulation Engine)

---

### Pitfall 2: Annex C Lookup Table — Missing, Wrong, or Silent Failure

**What goes wrong:**
The Annex C lookup returns the wrong third-placed team for a R32 slot, or silently fails to find a matching combination, causing the simulation to produce an illegal bracket or silently skip matches.

**Why it happens:**
The combination key is deceptively simple: `sorted(group_letters_of_advancing_thirds).join("")`. Four common failure modes:

1. **Key sorting error:** If the key is built from high-to-low instead of alphabetical (`"LKIGFEDC"` instead of `"CDEFGIKL"`), the lookup _silently_ returns `None` or an entry for a different combination. The response from `fifa-2026-annex-c-assignments.json` uses the sorted order, so any key mismatch fails.

2. **Missing entries:** 495 combinations must all be present. If even one is omitted (e.g., `"ABCDEFGH"` is missing because someone assumed it was impossible), the sim hits a KeyError or fallback path. The `tournamental` project (0800tim/tournamental) explicitly checks `if (!lookup)` and emits a warning with code `annex_c_lookup_missing` — the Python project needs the same guard.

3. **Group winner <-> third mapping reverse:** The lookup maps `"1A" → "3E"` meaning "Group A winner faces Group E's third-placed team." It's easy to read this as "Group E's third goes to slot 1A" but the _implementation direction_ matters: when resolving, you iterate the R32 slots that need thirds and look them up in the mapping, you don't reverse the map.

4. **Only 8 of 12 groups map:** Only group winners from A, B, D, E, G, I, K, L face third-place teams. Groups C, F, H, J winners face runners-up instead. If someone adds third-place slots for ALL 12 group winners, the bracket structure is wrong.

**How to avoid:**
- Include explicit validation in `state.py` (or a new `validate_annex_c()` function) that checks:
  - The JSON object has exactly 495 keys.
  - Every key is length-8, contains only letters A–L, and letters are sorted ascending.
  - Every key's value object has exactly 8 entries.
  - The 8 entry keys are `1A`, `1B`, `1D`, `1E`, `1G`, `1I`, `1K`, `1L` (not C, F, H, J).
  - No value references a group letter that isn't in the key.
  - No self-references (e.g., `"1A": "3A"` — a team cannot face its own group's third).
- In simulation, after lookup: verify the advancing third's group is actually in the key. Log a warning if not.
- Store `annex_c.json` as the authoritative source, not as generated code. The 495 entries are official FIFA data, not an algorithm.
- Source the table from the FIFA regulations PDF or a verified mirror (the `tournamental` project's `fifa-2026-annex-c-assignments.json` is one verified source; the dev.to article is a readable reference but not authoritative).

**Warning signs:**
- Simulation completes but R32 matchups have teams from the same group facing each other
- R32 has fewer than 8 third-place slots or more than 8
- KeyError during simulation for specific third-place combinations (unlikely combinations fail but common ones work)
- Third-place team appears in TWO different R32 matches

**Phase to address:**
Phase 7 (48-Team Dataset & Group Definitions) — the `annex_c.json` validation belongs here so Phase 9 (Knockout Bracket) trusts the data.

---

### Pitfall 3: Performance Regression — 4.5× More Matches, 12× Standings Computations

**What goes wrong:**
The simulation time per iteration jumps from 1–2 seconds to 15+ seconds, breaking the 60-second polling loop. The tool becomes sluggish, and users see stale probabilities between updates.

**Why it happens:**
The current v1.0 simulation (from `simulation.py`) runs:
- 1 iteration = simulate up to 23 knockout matches (16 R16 + 4 QF + 2 SF + 1 FINAL)
- Cost per iteration: 23 × Elo `expected_score()` calls + random draws + dict updates
- 50K iterations ≈ 1.15M match simulations in ~1-2 seconds

The v1.1 simulation requires:
- 1 iteration = simulate 72 group matches + compute 12 standings tables + rank 12 third-placed teams + resolve 16 R32 matches + 8 R16 + 4 QF + 2 SF + 1 3rd-place + 1 FINAL
- Cost per iteration: **104 match simulations** + 12 group standings sorts + 1 third-place ranking + Annex C lookup
- 50K iterations ≈ **5.2M match simulations** + standings overhead

The standings computation is the hidden cost: sorting 4 teams is cheap, but tiebreaker resolution involves O(n²) comparisons of head-to-head match results, which requires scanning 6 group matches per standings call. That's 72 match scans × 50K = 3.6M group match scans.

**Specific bottlenecks:**
1. **`expected_score()` called per match** — pure Python `math.pow(10, ...)` per call. 5.2M calls × pow ≈ measurable overhead.
2. **Standings recomputation from scratch** — every iteration recomputes all 12 standings by replaying scores from simulated matches. If standings are computed by summing group match results that are generated on the fly, the repeated summing adds up.
3. **Tiebreaker recursion** — multi-team ties trigger recursive H2H lookups that rescore matches within the tied subset. In the worst case (3+ teams tied), this adds 30-50% more work per iteration.
4. **Annex C lookup** — string key building + dict lookup per iteration (negligible in isolation, but multiplied by 50K).

**How to avoid:**
- **Profile first:** Before optimizing, run 1K iterations of the new simulation and time it. If < 1s, skip optimization. If > 3s, proceed.
- **Precompute `expected_score` lookup table:** Elo ratings change slowly. Cache `expected_score(elo_a, elo_b)` results in a dict keyed by `(rating_a, rating_b)` for ratings that repeat.
- **Vectorize group standings computation:** Instead of re-scanning match results per team, maintain running totals as matches are simulated:
  ```python
  # Bad: sum after all matches
  standings = {g: compute_standings(results[g]) for g in groups}
  
  # Good: accumulate during simulation
  # (points, gd, gs are updated per match, standings is a simple sort)
  ```
- **Avoid `random.random()` per match:** Draw a batch of random floats in one NumPy call (or `random.choices()`) and consume them sequentially. This cuts Python function call overhead.
- **Consider reducing iterations for group stage:** The group stage has fewer degrees of freedom than knockout (only 3 matches per team). 50K iterations may be overkill. Run a sensitivity analysis at 10K, 25K, 50K and check if probabilities stabilize (±0.5% for top teams).
- **Use `functools.lru_cache` on tiebreaker comparisons:** If the same two teams tie repeatedly across iterations, cache the H2H resolution.

**Scale threshold:**
- 10K iterations: ~1-2 seconds (still responsive)
- 50K iterations: ~5-10 seconds (acceptable for 60s polling)
- 100K iterations: ~10-20 seconds (too slow — breaks user experience)

**Warning signs:**
- Average poll cycle exceeds 30 seconds
- `print_simulation_duration()` consistently shows > 10s
- CPU usage at 100% for the full poll interval
- Rapid polling causes time-of-check/time-of-use issues with API data

**Phase to address:**
Phase 8 (Group Stage Simulation Engine) — must include performance benchmarks as acceptance criteria.

---

### Pitfall 4: Third-Place Ranking — Confusing Cross-Group vs. Within-Group Tiebreakers

**What goes wrong:**
The 8 best third-placed teams are selected incorrectly because the cross-group ranking uses within-group tiebreaker logic (applying H2H when the tied teams never played each other).

**Why it happens:**
The third-place ranking across all 12 groups uses a **different** tiebreaker chain than the within-group standings:

| Step | Within-Group (7 steps) | Third-Place Ranking (5 steps) |
|------|----------------------|------------------------------|
| 1 | H2H points | Overall points |
| 2 | H2H GD | Overall GD |
| 3 | H2H GS | Overall GS |
| 4 | Overall GD | Fair play |
| 5 | Overall GS | FIFA ranking |
| 6 | Fair play | — |
| 7 | FIFA ranking | — |

**Common mistakes:**
1. **Using H2H for cross-group ranking:** Developers reuse the within-group tiebreaker function for cross-group ranking. Since third-placed teams from different groups **never played each other**, H2H comparison is meaningless (zero points for both, doesn't separate). The tiebreaker must skip directly to step 4 (overall GD).
2. **Forgetting fair play in third-place ranking:** The cross-group ranking has fair play at step 4. Many simplified implementations omit it, making step 5 (FIFA ranking) more determinative than it should be.
3. **Not slicing to exactly 8:** The code must select EXACTLY 8 of 12 third-placed teams. The 9th–12th are eliminated. This is a rank-then-slice operation, not a rank-then-apply-threshold. A team with 4 points that ranks 9th on tiebreakers is out, while a team with 3 points that ranks 8th on GD advances.
4. **Sorting order reversal:** The third-place ranking sorts **descending** for points/GD/GS (higher is better) but **ascending** for fair play (lower card count = higher = better). FIFA ranking also sorts ascending (lower rank number = higher = better). Getting one comparator backward silently flips the selection.

**How to avoid:**
- Write two separate functions: `resolve_group_standings(group_matches)` and `rank_third_placed(groups_standings)`.
- The third-place ranker must accept the 12 third-placed teams and:
  1. Sort by points desc → GD desc → GS desc → fair play asc → FIFA rank asc.
  2. Return indices [0:8] as advancing, [8:12] as eliminated.
- Unit-test with:
  - All 12 thirds have different points (simple sort).
  - Two thirds tied on points and GD, resolved by GS.
  - Three thirds tied on all of points, GD, GS — falls to fair play.
  - Exact tie on fair play falls to FIFA ranking.
  - 9th/10th/11th/12th have same points as 8th but lose on tiebreaker (this matters for probability accuracy).

**Warning signs:**
- Simulation shows a team with 2 points advancing while a team with 4 points is eliminated
- Third-place ranking changes drastically between iterations with the same group results
- More or fewer than 8 third-place teams selected (should always be exactly 8)
- Cross-group ranking using H2H scoring (all zeros never separates)

**Phase to address:**
Phase 8 (Group Stage Simulation Engine)

---

### Pitfall 5: Group Match Result Persistence — Bracket Matching Breaks with Same Teams Across Stages

**What goes wrong:**
Live group match results fetched from BSD are not correctly matched to group stage match slots, or group results contaminate knockout bracket data, or partial group results corrupt standings computation.

**Why it happens:**
The current `played.json` stores results keyed by `match_id` from `bracket.json`. The current `bracket.json` uses match_ids like `R16_1`, `QF_1`, etc. The `fetcher._find_bracket_match()` function matches by `{team_a, team_b}` set equality.

**Three specific failure modes:**

1. **Same team pair in group AND knockout:** If Argentina vs. Nigeria occurs in both a group match AND the Round of 32, `_find_bracket_match()` returns the first match it finds. It might map the group result to the R32 bracket slot and vice versa.

2. **Match ID collision:** If group match IDs follow the same naming convention (e.g., `GRP_A_1`) but IDFormat collides with knockout match IDs (e.g., "R16_1" vs "GRP_1"), `played.json` becomes ambiguous.

3. **BSD data doesn't include group context:** The BSD API returns fixtures with home/away team names but no explicit "this is group A" annotation. Without group-specific match_ids, the fetcher cannot distinguish which group match a result belongs to.

**How to avoid:**
- Use a distinct match_id scheme for group matches: `GRP_<GROUP>_<MATCHNUM>` (e.g., `GRP_A_M1`, `GRP_A_M2`, ..., `GRP_L_M6`).
- Store group match results in a separate `played_groups.json` that maps `match_id → {team_a, team_b, home_score, away_score, winner, completed_at}`. Do NOT mix group results into the knockout `played.json`.
- The `_find_bracket_match()` function must scope its search: for knockout matches, search `bracket.json` only; for group matches, search `groups.json` only. Add a `scope` parameter to prevent cross-contamination.
- The standings computation reads from `played_groups.json` for completed group matches + simulated results for unplayed ones. The knockout simulation reads from `played.json`.
- When the tournament is over (all group matches completed), the standings are deterministic — no simulation needed for group outcomes. The simulation should detect this and only simulate knockout rounds.

**Data structure recommendation:**
```json
// groups.json
{
  "groups": {
    "A": { "teams": ["Mexico", "South Korea", "South Africa", "Czech Republic"], "matches": ["GRP_A_M1", "GRP_A_M2", "GRP_A_M3", "GRP_A_M4", "GRP_A_M5", "GRP_A_M6"] }
  },
  "match_details": {
    "GRP_A_M1": { "team_a": "Mexico", "team_b": "South Korea", "matchday": 1 },
    "GRP_A_M2": { "team_a": "South Africa", "team_b": "Czech Republic", "matchday": 1 }
  }
}
```

**Warning signs:**
- A group match result is reported but the simulation doesn't reflect it in standings
- A knockout match shows a scoreline that is actually a group match
- `played.json` contains match_ids that don't exist in `bracket.json`
- The same team appears as both "team_a" and "winner" but the opponent doesn't match

**Phase to address:**
Phase 7 (48-Team Dataset & Group Definitions) — the data structure must be designed for separation before any code is written.

---

### Pitfall 6: BSD Live Data Integration — Partial Group Results Create Invalid Bracket States

**What goes wrong:**
When the FIFA tournament is in progress (e.g., matchday 2 of 3 in group stage), BSD returns partial group results. The simulation tries to resolve R32 matchups from incomplete group standings, producing wild probability swings that don't reflect reality.

**Why it happens:**
After matchday 2, some groups have 4/6 matches completed, others have 3/6 (because matches are staggered across days). The standings computation must handle:

1. **Incomplete groups:** A team with 4 points after 2 matches might be leading, but two more matches remain. The simulation should NOT project them as group winner with certainty — the remaining unplayed matches must be simulated.
2. **Unresolvable third-place slots:** If some groups have only 2/3 matches played, the third-place is provisional. The cross-group third-place ranking must treat unplayed groups as having uncertainty.
3. **Annex C routing with partial data:** The combination key is built from which groups' third-placed teams are projected to advance. With partial results, this changes every iteration. That's correct for Monte Carlo, but the probability variance will be high — users may see "50% chance of advancing" swing to "10%" after a single match.

**Specific complexity:**
The current code handles "played matches are fixed, unplayed are simulated" cleanly for knockouts. For groups, the same model works: completed matches in `played_groups.json` are fixed, unplayed group matches are simulated. But the standings computation must correctly **merge** fixed results and simulated results per iteration.

**How to avoid:**
- Treat group matches exactly like knockout matches: completed matches are read from `played_groups.json` and never re-simulated; unplayed matches are simulated each iteration using Elo probabilities.
- The standings for each iteration = run completed match results + simulated results through the tiebreaker → get positions 1-4.
- Use a `StandingsResult` namedtuple that can represent "group winner is locked" vs. "group winner is projected." The Annex C routing and R32 resolution should work identically either way — the Monte Carlo handles the uncertainty.
- Add a stability metric: track how many third-place slots change across iterations. High variance = many groups still undecided.
- The BSD API returns `event_date` for each match — use this to filter matches. Only matches with `status: "finished"` go into `played_groups.json`.

**Warning signs:**
- Pre-tournament simulation shows 100% for a group winner (should be ~25-40% for balanced groups)
- Third-place rankings fluctuate between 8th and 9th across consecutive iterations with high variance
- The combination key fails (KeyError in annex_c.json) because too few groups have complete data
- Simulation crashes when a group has 0 completed matches (first iteration before any games)

**Phase to address:**
Phase 8 (Group Stage Simulation Engine) + Phase 10 (Integration, Tests & BSD Verification)

---

### Pitfall 7: Bracket Validation — 103-Match DAG Needs Structural, Slot, and Count Checks

**What goes wrong:**
The bracket JSON passes validation but produces an illegal tournament structure — wrong number of third-place slots, circular dependencies, or teams from the same group meeting in R32.

**Why it happens:**
The current `validate_bracket()` (in `state.py`) checks three things:
1. Unique match_ids (passes fine)
2. `source_matches` references exist (passes fine for well-formed data)
3. No cycles via DFS (passes fine for a DAG)

For the 2026 bracket (M73–M112, 40 knockout matches + 72 group matches), this is **insufficient**. The following are **NOT** validated:

1. **Round counts:** Must have exactly 72 group matches (6 per group × 12), 16 R32, 8 R16, 4 QF, 2 SF, 1 3rd-place, 1 FINAL = 104 total.
2. **Third-place slot count:** Exactly 8 of the 16 R32 matches must have `{kind: "annex_c_third"}` or equivalent. The other 8 must have fixed group positions.
3. **Group winners vs. runners-up vs. thirds:** The 8 third-place slots must pair with group winners (1A, 1B, 1D, 1E, 1G, 1I, 1K, 1L). Groups C, F, H, J winners must face runners-up. No group winner faces another group winner.
4. **No same-group rematch in R32:** Teams from the same group cannot meet in R32. This is enforced by Annex C's design, but the validation should verify it for any R32 matchup that isn't Annex C routed.
5. **R16 wiring matches FIFA Article 12.7:** The 8 R16 matches (M89–M96) must follow the specific pairing: M89 = W74 vs W77, M90 = W73 vs W75, etc. If the wiring is off by even one match, the bracket flow is wrong.
6. **Source matches fan out correctly:** Each R32 match should be referenced as a source by exactly one R16 match. No R16 match should skip an R32 match.
7. **Third-place match:** M103 (bronze final) must pair the two SF losers — verify its source_matches = [SF_1, SF_2] with the correct loser resolution logic.

**How to avoid:**
Write a comprehensive `validate_2026_bracket()` function with per-stage validators:

```python
def validate_2026_bracket(groups: dict, bracket: list[dict], annex_c: dict) -> None:
    """Validate full 104-match tournament structure."""
    checks = [
        _check_match_count(bracket, expected=104),
        _check_group_match_count(groups, expected=72),
        _check_round_structure(bracket),
        _check_source_integrity(bracket),
        _check_cycle_free(bracket),
        _check_third_place_slots(bracket, expected_count=8),
        _check_no_same_group_r32(bracket, groups),
        _check_r16_wiring(bracket),  # FIFA Article 12.7
        _check_annex_c_coverage(annex_c, expected_entries=495),
        _check_bronze_final(bracket),
    ]
    for check in checks:
        check()  # raise ValueError on failure
```

- Add a `--validate` CLI flag that runs all validation checks and reports results in a table format.
- Integrate into the startup sequence (`main.py` line 199) so invalid data stops the tool immediately with a clear error.
- For the annex_c.json file specifically: validate that every possible C(12,8) combination key exists (495/495), not just that the file loads.

**Warning signs:**
- Simulation produces probabilities for 31 teams instead of 48 (one team never appears)
- R16 probabilities exist for teams that shouldn't be there
- Probabilities don't sum to 100% for "advance from group" across all teams in a group
- A team's path to the final goes through an opponent from its own group

**Phase to address:**
Phase 9 (Knockout Bracket with Annex C Routing) — the validation must be in place before the bracket is used.

---

### Pitfall 8: Fair Play Tiebreaker — Card Points Scoring is Subtly Wrong

**What goes wrong:**
The fair play tiebreaker produces incorrect rankings because card deductions are calculated with wrong point values or wrong accumulation logic.

**Why it happens:**
The fair play scoring system has four distinct card events with different point deductions:

| Event | Deduction | Example |
|-------|-----------|---------|
| Yellow card (YC) | −1 | Standard caution |
| Indirect red (2YC) | −3 | Two yellows in one match → red |
| Straight red (RC) | −4 | Direct red card |
| Yellow then straight red (YC+RC) | −5 | Yellow followed by straight red |

**Common bugs:**
1. **Double-counting indirect red:** If a player gets two yellows then a red, some implementations deduct −1 for each yellow AND −3 for the indirect red (total −5). The correct deduction is −3 total for the indirect red (which replaces the two yellows). This is subtle: the player's two yellows are NOT counted separately; they're replaced by the −3 indirect red.
2. **Per-player cap:** The deduction is per-match-per-player. A player who gets two yellows across two different matches accumulates −2 (two separate yellow cards), NOT −3 (those are not an indirect red).
3. **Squad total vs. match total:** The fair play score is the **sum** of all card deductions across all group matches for all players and team officials. Some implementations average it per match.
4. **Team officials included:** Yellow/red cards to coaching staff count toward the team's fair play score. Most implementations forget this.
5. **Cumulative across stages:** For group standings tiebreaker, fair play includes ONLY group stage matches. For third-place ranking, it also includes ONLY group stage matches. However, for the knockout stage tiebreaker (should a match go to penalties and need fair play), it includes ALL matches. Different scopes.

**How to avoid:**
- Model a `FairPlayTracker` class that accumulates deductions per-match:
  ```python
  class FairPlayTracker:
      def record_card(self, player_id: str, card_type: str, match_id: str):
          # If this player already has a YC in this match and gets another YC,
          # deduct -3 for indirect red (not -1-1).
          # If this player has YC then RC in this match, deduct -5.
  ```
- For Monte Carlo simulation: assign probabilistic card counts per team based on historical averages (e.g., Brazil averages 2.1 YC per match, 0.05 RC per match). Draw from Poisson distribution per match for realism.
- Store fair play data in a clean structure: `{"team": {"yellow_cards": int, "indirect_reds": int, "straight_reds": int, "yellows_then_reds": int}}`.
- Validate fair play scores against historical World Cup data: most teams range from −5 to −15 across the group stage.

**Warning signs:**
- A team advances on fair play but its card count seems wrong (e.g., 0 deductions for a team with 10 yellows)
- Fair play tiebreaker never triggers in 50K iterations (should trigger occasionally in realistic simulations)
- Negative fair play scores exceed −30 (impossibly bad) or equal 0 for all teams (not implemented)

**Phase to address:**
Phase 8 (Group Stage Simulation Engine)

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Combine group + knockout in single `bracket.json` | One file, one loader | Can't distinguish group vs. knockout matches; fetcher scoping bugs; validation complexity explodes | NEVER — the RESPONSE.md already mandates separate `groups.json` and `bracket.json` |
| Skip fair play tiebreaker ("it never matters") | Simpler code | Produces wrong probabilities for heavily penalized teams that are bubble third-place candidates; Japan 2018 proved it matters | Only if running Monte Carlo for demonstration, not accuracy |
| Hardcode Annex C as a Python dict in simulation.py | No JSON loading overhead | Can't update table independently; validation code is mixed with simulation logic; violates separation of concerns | NEVER — must be `data/annex_c.json` loaded at startup |
| Use `random.random()` per match call | Simple to write | 5M+ function calls per iteration dominates runtime when group stage added | Acceptable only for MVP if runtime < 3s; optimize before Phase 9 ships |
| Derive R32 wiring algorithmically instead of using Annex C | No 120KB data file | Algorithm would need to replicate FIFA's pre-computed 495 scenarios — almost certainly wrong | NEVER — FIFA published the table because no simple algorithm exists |
| Skip third-place match (M103) | One less match to model | Probabilities for "reach final" vs "win final" are wrong; user-facing output doesn't match real tournament structure | Only if output never shows bronze probabilities |

---

## Integration Gotchas

Common mistakes when connecting to BSD live data and external sources.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| BSD API — match identification | Using `_find_bracket_match()` across both group and knockout matches | Scope search to `groups.json` for group matches, `bracket.json` for knockout matches. Add `scope` parameter. |
| BSD API — group assignment | Assuming BSD's `league_id=27` includes group letter metadata | BSD may not annotate which group a match belongs to. Match team names against `groups.json` team lists to infer group. |
| BSD API — match completeness | Marking group match as "played" before all 90 minutes (status not "finished") | Check `status` field — only accept `"finished"`. Ignore `"live"`, `"halftime"`, `"fulltime"` (full time is not finished if extra time possible, though group matches don't have ET). |
| Annex C data source | Extracting the 495-entry table from memory or AI knowledge | The table MUST come from the official FIFA regulations PDF (Section 12, Annex C) or a verified mirror. The `tournamental` project's `fifa-2026-annex-c-assignments.json` is a verified cross-reference. |
| Team aliases for 48 teams | Only 32-team aliases loaded (current `team_aliases.json` has only 11 entries) | All 48 teams need aliases. BSD may use different naming for new teams. Expand `team_aliases.json` before Phase 7. |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `random.random()` per match | Simulation time > 10s for 50K iterations | Batch random draws: `rands = [random.random() for _ in range(total_matches)]`, then `rands.pop()` per match | 50K × 104 = 5.2M function calls |
| Standings recomputation from scratch | Group match simulation is fast but standings compute is slow | Maintain running totals during match simulation; standings becomes a sort, not a sum | 50K × 12 groups × O(n²) H2H lookups |
| `expected_score()` called on hot path | Elo math dominates simulation time | Precompute lookup table for common Elo matchups; cache results | 5.2M `math.pow(10, ...)` calls |
| Tiebreaker recursion on identical standings | Worst-case multi-team ties cause 10x more comparisons per iteration | Cache tiebreaker results for identical point distributions across iterations (rare but possible) | Groups with 3-4 teams finishing on same points |
| Loading annex_c.json on every iteration | 120KB JSON file parsed 50K times | Load once at startup, pass as reference through simulation | 50K JSON parses = unnecessary GC pressure |
| Deep copying standings dict per iteration | High memory allocation | Mutate a pre-allocated standings structure, reset per iteration | 50K dict allocations × 12 groups |

---

## Security Mistakes

Domain-specific security issues for a CLI tool that fetches live data.

| Mistake | Risk | Prevention |
|---------|------|------------|
| BSD API key in git history | API key leaked to public repos | `.env` file, `load_dotenv()`, add `.env` to `.gitignore`. Already done correctly. |
| Malformed Annex C JSON | `json.load()` with malicious payload → `eval()` equivalent | Use `json.load()` with no custom decoder. Already safe. |
| Simulated data served as real predictions | Users make decisions based on inaccurate probabilities | Clear disclaimer in output: "Simulated probabilities — not betting advice." |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Showing winning probability for group stage (unlike knockout) | Confusion about what's being predicted | Use "advance probability" for groups, "champion probability" for knockout. Label clearly. |
| Third-place advancement shown without context | User sees "8 of 12 third-placed teams advance" but doesn't know which bubble teams are close | Show bubble indicator: 8th and 9th third-place teams with their tiebreaker difference. Highlight "on the bubble" scenarios. |
| Polling timer shows stale data during group play | User checks at matchday 2 but sees probabilities from matchday 1 | Display "last updated" timestamp and "matches remaining" count per group. |
| Massive probability swings during group stage | User sees 60% → 20% after one match and assumes bug | Add delta column (already exists in output.py) but include explanation: "Probability changed because [team] lost to [team]." |
| 48 teams shown in top-5 table | Most teams have <1% champion probability; top-5 only shows ~5 teams | Keep top-5 for champion, but show full table on shutdown. Add "advance probability" secondary sort. |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [x] **Groups JSON created:** But does it include match_id references? Each match needs a stable ID for `played_groups.json` persistence.
- [ ] **Annex C JSON loaded:** But not validated for all 495 entries. A missing combination crashes the simulation silently (KeyError) or produces wrong bracket.
- [ ] **Group stage simulated:** But tiebreaker only tested for 2-team ties. 3-team and 4-team ties will produce wrong positions.
- [ ] **Third-place teams selected:** But not checked for exact count = 8. If the slice accidentally takes 9 or 7, the R32 bracket is invalid.
- [ ] **BSD live data flowing:** But group match team names don't match new 48-team alias entries. BSD may use "Korea Republic" while teams.json uses "South Korea".
- [ ] **Bracket validated:** But only the old 23-match checks run. The 104-match structure has 4x more failure modes.
- [ ] **Probabilities displayed:** But only QF/SF/FINAL/champion, no "advance from group" or "R32"/"R16" probability columns.
- [ ] **Simulation fast enough:** But only tested with a 32-team bracket. 48-team + group stage hits 5M+ match simulations per run.
- [ ] **Third-place match (M103) modeled:** But who advances from the semifinal losers? The bronze final winner should not count as "champion probability."

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Tiebreaker order wrong | LOW | Fix function order in `resolve_group_standings()`, re-run all tests |
| Annex C missing entry | MEDIUM | Add the missing combination key to `annex_c.json`. Re-run both validation and simulation. |
| Performance > 10s | MEDIUM | Profile with `cProfile`, identify top 3 bottlenecks (likely: random draws, expected_score, standings compute), optimize each |
| Third-place rank bug produces wrong 8 | LOW | Fix comparator order in `rank_third_placed()`. Add test for bubble scenario. |
| BSD fetcher maps group match to knockout slot | LOW | Add scope parameter to `_find_bracket_match()`. Clear `played.json` to flush mismatched entries. |
| Fair play scoring bug | LOW | Fix `FairPlayTracker.record_card()` logic for 2YC→RC conversion. Re-simulate. |
| Bracket validation misses structural error | HIGH | Add per-stage validators. The root cause is structural data error (wrong R16 wiring). Requires data fix. |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Tiebreaker step reversal | Phase 8 — include 7-step chain with correct order + recursion | Unit tests: 2, 3, 4-team ties; known FIFA scenarios (Japan 2018 fair play) |
| Annex C lookup failures | Phase 7 — validate 495 entries on load; Phase 9 — guard against missing keys | Validation prints "495/495 entries OK" or fails with specific missing combinations |
| Performance regression | Phase 8 — benchmark at 10K/25K/50K iterations; opt if > 5s | `python -m cProfile` shows < 3s for 50K iterations |
| Third-place selection order | Phase 8 — separate function from within-group tiebreaker | Test: 12 thirds with ties at bubble 8th/9th boundary |
| Group match persistence | Phase 7 — separate `played_groups.json` schema; Phase 10 — integration test | E2E: simulate group match, verify standings update, verify R32 resolution unchanged |
| BSD integration with partial data | Phase 10 — mock API returns partial matchday results | E2E: load 4/6 group matches, verify simulation handles incomplete groups |
| Bracket validation | Phase 9 — `validate_2026_bracket()` with 10 sub-checks | All sub-checks pass; known-bad bracket fixtures fail with specific error messages |
| Fair play scoring | Phase 8 — include `FairPlayTracker` in standings model | Test: 2YC→RC = −3, YC+RC = −5, two YC across matches = −2 |

---

## Sources

- **FIFA Official 2026 Regulations:** https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers — tiebreaker order and fair play rules (HIGH confidence)
- **FIFA Match Schedule (PDF):** https://digitalhub.fifa.com/m/1be9ce37eb98fcc5/original/FWC26-Match-Schedule/_English.pdf — official 104-match schedule (HIGH confidence)
- **DEV.to (Mark):** https://dev.to/mark_b5f4ffdd8e7cd58/encoding-fifas-495-third-place-scenarios-for-the-2026-world-cup-4814 — Annex C implementation patterns and pitfalls (MEDIUM confidence — community consensus, cross-checked against official data)
- **tournamental project (0800tim):** https://github.com/0800tim/tournamental — Annex C validation code and R32 fixture verification (MEDIUM confidence — cross-referenced with Wikipedia and FIFA PDF)
- **Bracket2026.com:** https://bracket2026.com/en/blog/how-48-team-world-cup-works — format overview and third-place rules (MEDIUM confidence — commercial predictor, verified against FIFA)
- **Sporting News:** https://www.sportingnews.com/us/soccer/news/world-cup-group-tiebreakers-2026-teams-tied-points-goal-differential/606ca25a20c6167ef229d31c — fair play deduction values (MEDIUM confidence — major publisher, consistent with FIFA)
- **myteamkickoff.com:** https://myteamkickoff.com/articles/world-cup-2026-tiebreaker-rules-explained/ — identified the H2H vs Overall GD reversal as a common misconception (MEDIUM confidence)
- **FOX Sports:** https://www.foxsports.com/stories/soccer/fifa-world-cup-group-stage-third-place-tiebreakers — third-place ranking criteria (MEDIUM confidence)
- **steodose/world-cup-2026 (GitHub):** https://github.com/steodose/world-cup-2026 — reference implementation with vectorized Monte Carlo (LOW confidence — single source, but code structure is visible)
- **Sportmonks:** https://www.sportmonks.com/blogs/world-cup-2026-round-of-32-and-knockouts-how-to-build-world-cup-brackets/ — bracket API integration patterns (LOW confidence — vendor blog, but practical API integration insight)
- **Codebase analysis** — `simulation.py`, `state.py`, `fetcher.py`, `main.py`, `elo.py`, `output.py`, `constants.py`, `teams.json`, `bracket.json`, `played.json`, `team_aliases.json` (HIGH confidence — verified against actual project code)
- **RESPONSE.md** — project architecture decisions (HIGH confidence — internal planning document)

---

*Pitfalls research for: FIFA-WC World Cup Dynamic Predictor — v1.0 (32-team knockout) → v1.1 (48-team, group stage, Annex C routing)*
*Researched: 2026-06-14*
