# Domain Pitfalls: UCL & League Football Prediction

**Domain:** UEFA Champions League (Swiss-system) + Domestic League prediction modules  
**Researched:** 2026-06-27

---

## Critical Pitfalls

Mistakes that cause incorrect results, wasted implementation effort, or architectural debt.

### Pitfall 1: Reusing H2H tiebreaker in UCL league phase

**What goes wrong:** Using `football_core.groups._tiebreak_group()` (which applies head-to-head comparison) for UCL's 36-team league table.

**Why it happens:** The existing `football_core.groups._tiebreak_group()` and `_compute_h2h()` are readily available, well-tested, and logically similar to what's needed. A developer reaching for the easiest path will import them.

**Consequences:** Incorrect standings. In UCL's Swiss system, not every team plays every other team, so head-to-head records are meaningless for ranking. This produces demonstrably wrong tiebreaker resolution — the exact order depends on which teams happen to share opponents.

**Prevention:** Implement a separate `compute_swiss_standings()` that uses GD → GS → away GS → wins → away wins → opponent strength chain. Add an explicit assertion or test that prevents importing the old `_tiebreak_group` for Swiss standings.

**Detection:** Unit test comparing Swiss standings: create a scenario where two teams have equal points but different opponent pools and verify tiebreaker uses opponent strength, not H2H.

**Source:** UEFA.com, Sporting News tiebreaker analysis — MEDIUM confidence

### Pitfall 2: Simulating UCL playoff as single-leg knockout

**What goes wrong:** The knockout playoff (9-24) is a TWO-LEGGED tie, but existing `football_core.knockout._simulate_knockout_round()` handles single-match resolution.

**Why it happens:** Existing knockout simulation assumes single matches (WC/Euro format). UCL playoff requires home-and-away aggregate scoring.

**Consequences:** Loses home/away advantage effects. Misses the strategy difference: in two-legged ties, the higher seed (9-16) gets second leg at home, which is a significant advantage.

**Prevention:** Build a dedicated `simulate_two_legged_tie()` function. Handle aggregate → extra time → penalties explicitly.

**Source:** UEFA knockout playoff rules — HIGH confidence

### Pitfall 3: Applying away goals rule in knockout

**What goes wrong:** Using away goals as an aggregate tiebreaker in UCL knockout rounds.

**Why it happens:** Away goals was the standard UEFA tiebreaker for decades (1965-2021). Training data or older sources still reference it.

**Consequences:** Incorrect simulation results. UEFA abolished away goals for ALL competitions from 2021-22 season onward.

**Prevention:** Verify no away goals logic exists in new code. If extracting `football_core.knockout` for two-legged ties, explicitly reject away goals.

**Source:** UEFA announcement, Sporting News analysis — HIGH confidence

### Pitfall 4: Adding country protection to UCL knockout draw

**What goes wrong:** Preventing same-nation clubs from meeting in R16.

**Why it happens:** WC/Euro group-to-knockout advancement prevents same-group meetings early. Champions League historically had country protection in R16 draws (until Swiss system).

**Consequences:** Incorrect bracket simulation. The new UCL format has NO country protection from R16 onward. Same-nation clubs CAN meet at any stage.

**Prevention:** Do not implement any country-pairing restrictions in UCL bracket construction.

**Source:** UEFA R16 draw procedure — MEDIUM confidence (multiple confirmations)

### Pitfall 5: Not handling the "knockout playoff winner seed inheritance" rule

**What goes wrong:** Assuming a higher-seeded playoff winner (e.g., 9th place) gets matched against a lower R16 seed (8th) rather than the top seed (1st).

**Why it happens:** The seeded bracket pairings look intuitive but are non-obvious. The pairing is: 1st/2nd vs playoff winner from the 15-18 bracket position, not 1st vs lowest-ranked survivor.

**Consequences:** Wrong R16 matchups. The pairing logic is: teams 1-8 are paired against specific playoff bracket positions, and the pairing depends on the predetermined bracket, not on which specific teams win.

**Prevention:** Implement the exact seeded pairings table:
- 1st/2nd → winner of [15th/16th vs 17th/18th] bracket
- 3rd/4th → winner of [13th/14th vs 19th/20th] bracket  
- 5th/6th → winner of [11th/12th vs 21st/22nd] bracket
- 7th/8th → winner of [9th/10th vs 23rd/24th] bracket

**Source:** Sporting News knockout bracket analysis — MEDIUM confidence

### Pitfall 6: League simulation performance blowup

**What goes wrong:** League simulation (38 matchdays × 10 matches) being 3-10× slower than tournament simulation, making 50K iterations impractical.

**Why it happens:** Naively nesting matchday iteration inside the MC loop: `for _ in range(50000): for md in range(38): simulate_matches(md)`. More matches × more iterations = quadratic-like growth.

**Consequences:** Unacceptably slow runtimes (30+ seconds per pass). Users wait minutes for results.

**Prevention:** Optimize order: precompute lambdas, then for each iteration simulate ALL matches in a flat pass, not per-matchday. Consider:
- Precomputing a 380-element list of (team_a, team_b, lambda_a, lambda_b) tuples
- Generating scores for all matches before computing standings
- Using the same `simulate_group_matches` approach but treating the whole season as one "group"
- For high iterations, investigate vectorized Poisson sampling (numpy)

**Source:** Existing performance patterns — WC uses 48 teams × 3 matches = 72 matchups; league uses 380

### Pitfall 7: Breaking WC regression suite during UCL module development

**What goes wrong:** Adding ET/penalties or other shared utilities to `football_core` that accidentally affect WC/Euro simulation behavior.

**Why it happens:** A shared utility change in `football_core.knockout` or `football_core.groups` could alter Poisson tables, tiebreaker logic, or knockout resolution paths.

**Consequences:** WC regression test failures (613 tests must remain green). Waste debugging time.

**Prevention:** 
- Prefer adding new functions over modifying existing ones
- Add ET/penalties as a NEW module (`football_core.et_penalties`) rather than modifying `football_core.knockout`
- Run WC full test suite before every commit during UCL development
- Keep all UCL-specific logic in `competitions/ucl/` until Rule of Two satisfied

**Source:** PROJECT.md constraints — HIGH confidence

---

## Moderate Pitfalls

### Pitfall: Ignoring UEFA coefficient in tiebreakers
UCL tiebreaker chain ends with UEFA club coefficient. This is rare but affects teams like Real Madrid/AC Milan vs smaller clubs. **Prevention:** Implement the full 10-step chain. Coefficient data can be hardcoded from the latest UEFA rankings.

### Pitfall: Assuming all leagues use 3-up/3-down
Some leagues have different promotion/relegation counts. La Liga uses 3 up/3 down; Championship uses 2 up + play-off; Bundesliga has 2.5 spots (2 direct, 1 play-off). **Prevention:** Make promotion/relegation counts configurable in the league module.

### Pitfall: Forgetting play-off format differences
Championship play-off is 4 teams (semi + final). New Championship expansion (2026-27) goes to 6 teams. La Liga Segunda play-off is also 4 teams. National League has 6 teams with a different format. **Prevention:** Parameterize play-off structure (number of teams, round structure) in configuration.

### Pitfall: Home advantage coefficient mismatch
UCL has a strong home advantage (familiar stadium, travel for opposition) but WC is neutral/Euro is weaker host advantage. Reusing the same HOME_ADVANTAGE_MULTIPLIER across all competitions is wrong. **Prevention:** Each competition configures its own `HOME_ADVANTAGE_MULTIPLIER` in config.py.

### Pitfall: Not accounting for summer-break Elo drift
In league simulation across a season (Aug-May), Elo ratings from the previous season should have an initial uncertainty or regression. **Prevention:** Add optional pre-season Elo decay factor for league modules.

---

## Minor Pitfalls

### Pitfall: Betting odds display in CLI
Users may request odds display alongside probabilities. This is out of scope per PROJECT.md. **Prevention:** Clearly document in README and CLI help that this is a tournament-forecast engine, not a betting tool.

### Pitfall: Mid-season transfer adjustments
Asking "how do we model when a star player leaves in January?" The simple answer is: use the existing Elo update mechanism — when results reflect the team's new strength, Elo adjusts automatically. **Prevention:** Don't add player-specific models. Elo captures strength changes through results.

### Pitfall: Winter break / fixture postponement handling
Leagues have winter breaks, FA Cup weekends, postponements. The schedule is not a fixed uniform grid. **Prevention:** Use a flexible matchday model where each matchday is a set of fixtures, not a calendar week. The simulation schedules matches when they occur.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| **ENG-01: UCL league table** | Using H2H tiebreaker (Pitfall #1) | Dedicated UCL tiebreaker function; test against HC scenarios |
| **ENG-01: UCL bracket** | Incorrect seed pairing (Pitfall #5) | Implement exact UEFA pairing table; validate with test cases |
| **ENG-01: UCL playoff** | Single-leg vs two-leg (Pitfall #2) | Dedicated two-leg simulation function |
| **ENG-01: football_core changes** | Breaking WC tests (Pitfall #7) | New modules > modifying existing; run full test suite |
| **ENG-05: League simulation** | Performance blowup (Pitfall #6) | Flat simulation pass; investigate numpy optimization |
| **ENG-05: Promotion/relegation** | Hardcoded counts (moderate #1) | Configurable N-up/M-down parameters |
| **ENG-05: Play-offs** | Wrong format (moderate #2) | Parameterized play-off structure |

## Sources

- UEFA.com — format regulations: https://www.uefa.com/uefachampionsleague/news/0296-1d21e9bdf7e4-808a7511165c-1000--2025-26-champions-league-format-dates-draws-final/ (MEDIUM)
- Sporting News — UCL tiebreaker rules: https://www.sportingnews.com/uk/football/news/champions-league-tiebreaker-level-points-league-phase-uefa/54f8a7396551932b2a87fe87 (MEDIUM)
- Sporting News — UCL bracket structure: https://www.sportingnews.com/uk/football/news/champions-league-bracket-explained-knockout-round-16-playoffs/09410346dd5c2cad44e6058f (MEDIUM)
- NBC Sports — PL tiebreakers: https://www.nbcsports.com/soccer/news/premier-league-tiebreaker-rules-2026-goal-difference-head-to-head-record-how-it-works (MEDIUM)
- Premier League — relegation FAQ: https://www.premierleague.com/en/news/4657245/202526-premier-league-relegation-faq (HIGH)
- Sky Sports — Championship play-off expansion: https://www.skysports.com/football/news/11688/13515549/championship-play-offs-efl-confirms-expansion-from-four-to-six-teams-from-2026-27-season-onwards (HIGH)
- PROJECT.md — competition boundary contract (HIGH)
- Codebase — existing WC/Euro patterns (HIGH)
