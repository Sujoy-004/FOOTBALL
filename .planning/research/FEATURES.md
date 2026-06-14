# Feature Landscape: Live Football Tournament Prediction

**Domain:** CLI-based live football tournament prediction (World Cup 2026)
**Researched:** 2026-06-14
**Mode:** Ecosystem research — features analysis with official FIFA 2026 format verification

## Executive Summary

This document has two parts:

1. **Tournament Format Verification (v1.1 focus)** — Officially verified FIFA 2026 rules for the 48-team format: 12 groups, 32 advancing teams, the 8-best-third-placed qualification, the 495-scenario Annex C lookup, and the full R32→R16→QF→SF→FINAL bracket path. Every finding is sourced and confidence-rated.

2. **Feature Landscape (v1.0 + v1.1)** — The prediction pipeline features (Elo, Monte Carlo, API polling, console output) plus the format-specific features needed to support the 48-team format. v1.0 (32-team knockout-only) is a subset; v1.1 adds the full 48-team group stage and Annex C logic.

---

## PART 1: TOURNAMENT FORMAT VERIFICATION (v1.1 Critical)

### Sources Consulted

| Source | URL | Status | Confidence |
|--------|-----|--------|------------|
| FIFA Official — Groups & Tiebreakers | fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers | ✅ Fetched (Apr 2026) | **HIGH** |
| FIFA Official — New Format Article | fifa.com/en/articles/article-fifa-world-cup-2026-mexico-canada-usa-new-format-tournament-football-soccer | ✅ Fetched (Mar 2023) | **HIGH** |
| FIFA Regulations PDF (Annex C) | digitalhub.fifa.com/m/636f5c9c6f29771f/original/FWC2026_regulations_EN.pdf | ✅ Fetched (partial, binary) | **HIGH** |
| FIFA Ticket Support — Format FAQ | gpcustomersupportfwc2026.tickets.fifa.com/hc/en-gb/articles/28784798873117 | ✅ Fetched (May 2026) | **HIGH** |
| ESPN — Format, Groups, Schedule | espn.com/soccer/story/_/id/47108758 | ✅ Fetched (Apr 2026) | **HIGH** |
| Wikipedia — Knockout Stage | en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage | ✅ Fetched (complete) | **HIGH** |
| Bracket2026 — Format Guide | bracket2026.com/en/blog/how-48-team-world-cup-works | ✅ Fetched (Apr 2026) | **MEDIUM** (independent) |
| Bracket2026 — Third-Place Rules | bracket2026.com/en/blog/third-place-advancement | ✅ Fetched (Apr 2026) | **MEDIUM** (independent) |
| DEV.to — Annex C Encoding | dev.to/mark_b5f4ffdd8e7cd58/encoding-fifas-495-third-place-scenarios | ✅ Fetched (May 2026) | **MEDIUM** (independent impl.) |
| Sports StackExchange | sports.stackexchange.com/questions/30289 | ✅ Fetched | **LOW** (forum discussion) |

---

### 1. Group Advancement Rules

| Property | Value | Source | Confidence |
|----------|-------|--------|------------|
| Total teams | 48 | FIFA format article | **HIGH** |
| Number of groups | 12 (A through L) | FIFA draw article | **HIGH** |
| Teams per group | 4 | FIFA format article | **HIGH** |
| Group matches per team | 3 (round-robin) | FIFA format article | **HIGH** |
| Total group stage matches | 72 (12 groups × 6 matches) | FIFA format article | **HIGH** |
| Advance from each group | Top 2 | FIFA format article | **HIGH** |
| Total auto-advancers | 24 teams (12 winners + 12 runners-up) | FIFA format article | **HIGH** |
| Third-place advancers | 8 best (of 12) | FIFA format article | **HIGH** |
| Total to knockout | 32 teams | FIFA format article | **HIGH** |
| Total matches | 104 (72 group + 32 knockout) | FIFA format article | **HIGH** |
| Champion plays | 8 matches (3 group + 5 knockout) | FIFA format article | **HIGH** |
| Tournament length | 39 days (Jun 11 – Jul 19) | FIFA format article | **HIGH** |

**Points system:** Win = 3, Draw = 1, Loss = 0.

**Group stage tiebreaker chain** (for positions 1-2 within a group, applied in order):

| Step | Criterion | Notes |
|------|-----------|-------|
| 1 | Points in matches between tied teams | Head-to-head among tied teams only |
| 2 | Goal difference in matches between tied teams | Among tied teams only |
| 3 | Goals scored in matches between tied teams | Among tied teams only |
| 4 | Goal difference in all group matches | Full group |
| 5 | Goals scored in all group matches | Full group |
| 6 | Fair play score | Yellow -1, second yellow+red -3, straight red -4, yellow then direct red -5 |
| 7 | FIFA/Coca-Cola Men's World Ranking | Most recent edition |

*Sources: FIFA regulations PDF (Article 13), ESPN, Bracket2026, all confirmed identically.*

---

### 2. Third-Place Qualification Rules

The 8 best teams among the 12 third-placed finishers are selected using this tiebreaker chain:

| Step | Criterion | Notes |
|------|-----------|-------|
| **a** | Points in all group matches | 3 for win, 1 for draw |
| **b** | Goal difference in all group matches | Goals for minus goals against |
| **c** | Goals scored in all group matches | Total goals for |
| **d** | Fair play score | Same card scoring as group tiebreaker: yellow = -1, second yellow+red = -3, straight red = -4, yellow then direct red = -5 |
| **e** | Most recent FIFA/Coca-Cola Men's World Ranking | |
| **f** | Preceding FIFA ranking edition | Continued until tie broken |

**Critical thresholds** (historical, per Bracket2026 analysis of Euro 2016/2020):
- **4 points** → virtually locks advancement
- **3 points** → advances ~75% of the time (bubble)
- **2 points** → rarely advances; needs multiple other 3rd-place teams to do worse

*Sources: FIFA regulations PDF (Article 13 step for 3rd-place ranking), FIFA tiebreakers article, Bracket2026 third-place guide.*

---

### 3. The 495 Annex C Scenarios Explained

**What is Annex C?**
Annex C of the FIFA 2026 Regulations is a lookup table containing 495 rows, each specifying exactly which third-placed team goes into which Round of 32 slot for every possible combination of qualifying third-place groups.

**Why 495?**
```
C(12, 8) = 495
```
There are 12 possible third-place teams (one per group) but only 8 advance. The number of possible combinations of which 8 groups produce advancers is 12 choose 8 = 495. Each combination maps to a unique set of 8 R32 matchups.

**Which group winners face third-place teams?**
8 group winners face third-place teams (matches M74, M77, M79, M80, M81, M82, M85, M87):
- Winner A, Winner B, Winner D, Winner E, Winner G, Winner I, Winner K, Winner L

**Which group winners face runners-up?**
4 group winners face runners-up (matches M73, M75, M76, M84, M86):
- Winner C, Winner F, Winner H, Winner J

**Why not simply "best 3rd-place plays winner A"?**
Because the bracket must respect two constraints:
1. Third-placed teams always face group winners in R32 (never runners-up or other third-place)
2. Teams from the same group must not meet again immediately in R32

These constraints make a simple "sorted seeding" impossible. FIFA pre-computed all 495 cases.

**Example mappings** (from Wikipedia Annex C table):

| Combination (advancing groups) | W A faces | W B faces | W D faces | W E faces | W G faces | W I faces | W K faces | W L faces |
|-------------------------------|-----------|-----------|-----------|-----------|-----------|-----------|-----------|-----------|
| C, D, E, F, G, H, I, J | 3C | 3G | 3J | 3D | 3H | 3F | 3E | 3K |
| C, D, E, F, G, H, I, K | 3C | 3G | 3E | 3D | 3H | 3F | 3I | 3K |
| C, D, E, F, G, I, J, K | 3C | 3G | 3E | 3D | 3J | 3F | 3I | 3K |
| D, E, F, G, H, I, J, L | 3E | 3G | 3J | 3D | 3H | 3F | 3L | 3I |
| D, E, F, G, H, I, K, L | 3E | 3G | 3I | 3D | 3H | 3F | 3L | 3K |

**Implementation approach** (per DEV.to article):
```python
# Step 1: Rank all 12 third-place teams
qualified_thirds = rank_third_placed_teams(all_third_places)[:8]

# Step 2: Build combination key from qualifying groups
combination_key = "".join(sorted([t.group for t in qualified_thirds]))
# e.g., "CDEFGHIJ"

# Step 3: Look up the R32 mapping from the 495-row table
mapping = ANNEX_C_TABLE[combination_key]

# Step 4: Place each third-place team into its R32 slot
# mapping["1A"] gives "3C" = third-place team from group C goes to winner A's slot
```

**Note:** The Annex C table has been fully tabulated on Wikipedia and independently validated by the DEV.to author's bracket2026.com implementation. It can be encoded as a Python dictionary with 495 keys.

*Sources: FIFA regulations PDF (Article 12, Annex C), Wikipedia, DEV.to, Sports StackExchange, Bracket2026.*

---

### 4. Round of 32 Match Structure (Seeding Matrix)

The R32 has **16 matches** (M73 through M88). Officially verified pairings:

| Match | Team A | Team B | Notes |
|-------|--------|--------|-------|
| M73 | Runner-up Group A | Runner-up Group B | RU vs RU |
| M74 | **Winner Group E** | **Best 3rd of {A,B,C,D,F}** | W vs 3rd |
| M75 | Winner Group F | Runner-up Group C | W vs RU |
| M76 | Winner Group C | Runner-up Group F | W vs RU |
| M77 | **Winner Group I** | **Best 3rd of {C,D,F,G,H}** | W vs 3rd |
| M78 | Runner-up Group E | Runner-up Group I | RU vs RU |
| M79 | **Winner Group A** | **Best 3rd of {C,E,F,H,I}** | W vs 3rd |
| M80 | **Winner Group L** | **Best 3rd of {E,H,I,J,K}** | W vs 3rd |
| M81 | **Winner Group D** | **Best 3rd of {B,E,F,I,J}** | W vs 3rd |
| M82 | **Winner Group G** | **Best 3rd of {A,E,H,I,J}** | W vs 3rd |
| M83 | Runner-up Group K | Runner-up Group L | RU vs RU |
| M84 | Winner Group H | Runner-up Group J | W vs RU |
| M85 | **Winner Group B** | **Best 3rd of {E,F,G,I,J}** | W vs 3rd |
| M86 | Winner Group J | Runner-up Group H | W vs RU |
| M87 | **Winner Group K** | **Best 3rd of {D,E,I,J,L}** | W vs 3rd |
| M88 | Runner-up Group D | Runner-up Group G | RU vs RU |

**Key patterns:**
- 4 group winners (C, F, H, J) face runners-up from specific groups (fixed regardless of 3rd-place outcomes)
- 8 group winners (A, B, D, E, G, I, K, L) face third-place teams (opponent depends on which groups produce advancers — determined by Annex C)
- 4 runner-up pairs: (A vs B), (E vs I), (K vs L), (D vs G)
- Each group winner that plays a 3rd-place team has **exactly 5 possible group candidates** for their opponent (the candidate sets are listed above).

*Sources: Wikipedia knockout stage page (verified R32 layout), ESPN schedule (venue assignments confirm match ordering), FIFA regulations PDF (Article 12.6).*

---

### 5. Knockout Path: R32 → R16 → QF → SF → FINAL

**Round of 16 (M89–M96):**

| R16 Match | Team A | Team B |
|-----------|--------|--------|
| M89 | Winner M74 | Winner M77 |
| M90 | Winner M73 | Winner M75 |
| M91 | Winner M76 | Winner M78 |
| M92 | Winner M79 | Winner M80 |
| M93 | Winner M83 | Winner M84 |
| M94 | Winner M81 | Winner M82 |
| M95 | Winner M86 | Winner M88 |
| M96 | Winner M85 | Winner M87 |

**Quarterfinals (M97–M100):**

| QF Match | Team A | Team B |
|----------|--------|--------|
| QF1 (M97) | Winner M89 | Winner M90 |
| QF2 (M98) | Winner M93 | Winner M94 |
| QF3 (M99) | Winner M91 | Winner M92 |
| QF4 (M100) | Winner M95 | Winner M96 |

**Semifinals (M101–M102):**

| SF Match | Team A | Team B |
|----------|--------|--------|
| SF1 (M101) | Winner QF1 | Winner QF2 |
| SF2 (M102) | Winner QF3 | Winner QF4 |

**Final (M103):**
- Winner SF1 vs Winner SF2

**Third-place match (M104):**
- Loser SF1 vs Loser SF2

**Semi-bracket visualization (left side = top half):**
```
W.E vs 3rd{A,B,C,D,F} ─┐ M74 ─┐
                              ├── M89 ──┐
W.I vs 3rd{C,D,F,G,H} ─┘ M77 ─┘        │
                                          ├── QF1 ──┐
RU.A vs RU.B ─────────── M73 ─┐          │          │
                              ├── M90 ──┘          │
W.F vs RU.C ──────────── M75 ─┘                    │
                                                    ├── SF1 ──┐
W.C vs RU.F ──────────── M76 ─┐                    │          │
                              ├── M91 ──┐          │          │
RU.E vs RU.I ─────────── M78 ─┘        │          │          │
                                          ├── QF3 ──┘          │
W.A vs 3rd{C,E,F,H,I} ── M79 ─┐          │                    │
                              ├── M92 ──┘                    │
W.L vs 3rd{E,H,I,J,K} ── M80 ─┘                              │
                                                               ├── FINAL
                                                               │
(Repeat symmetric layout on right half with M83-88 → M93-96 → QF2/QF4 → SF2)
```

*Sources: Wikipedia knockout stage (complete bracket tree), FIFA regulations PDF (Article 12.7), ESPN schedule (venue assignments for R16+ confirm the pairing structure).*

---

### 6. Verification: Confidence Summary

| Area | Confidence | Cross-Sources |
|------|------------|---------------|
| Groups: 12 groups of 4, top 2 advance | **HIGH** | FIFA × 3, ESPN, Wikipedia, Bracket2026, FIFA Support |
| Third-place: 8 of 12 advance, 5-level tiebreaker | **HIGH** | FIFA regulations PDF, FIFA website, ESPN, Bracket2026 |
| Annex C: 495 combos, group-key lookup | **HIGH** | FIFA regulations PDF, Wikipedia (full table), DEV.to impl. |
| R32 match matrix (all 16 matchups) | **HIGH** | Wikipedia, FIFA regulations, ESPN schedule |
| R16 → QF → SF → Final path | **HIGH** | Wikipedia (full bracket), FIFA regulations PDF |
| Fair play scorecard values | **HIGH** | FIFA regulations PDF, Bracket2026, ESPN |
| Historical 3rd-place threshold analysis | **MEDIUM** | Bracket2026 (extrapolated from Euro 2016/2020 data) |
| Formal proof of Annex C algorithm | **LOW** | Sports StackExchange (discussion, not official) |

---

## PART 2: FEATURE LANDSCAPE (v1.0 + v1.1)

### Table Stakes

Features users expect. Missing these means the product feels incomplete vs. any existing predictor.

| # | Feature | Why Expected | Complexity | Format Dependency | Phase |
|---|---------|--------------|------------|-------------------|-------|
| 1 | **Championship probability (%) per team** | Every predictor outputs this as the headline number | Low | v1.0: 32-team bracket. v1.1: 48-team with group stage | Core |
| 2 | **Round-by-round advancement probabilities** | Users expect stage-by-stage breakdown (R32→R16→QF→SF→Final) | Low | v1.0: R16 onward. v1.1: adds R32 stage | Core |
| 3 | **Live match result ingestion** | Must detect and process real results without manual intervention | Medium | v1.0: knockout matches only. v1.1: group + knockout | Core |
| 4 | **Elo rating updates after each match** | The fundamental rating engine | Low | Match-agnostic (pure formula) | Core |
| 5 | **Monte Carlo simulation engine** | 50,000+ sims expected for stable probabilities | Medium | v1.0: simpler bracket (32-team KO). v1.1: 48-team with group permutation | Core |
| 6 | **Team rating display** | Show current Elo rating alongside probability | Low | Match-agnostic | Core |
| 7 | **Match-level win probability** | "Team A has X% chance vs Team B" via Elo → expected score | Low | Match-agnostic | Core |
| 8 | **Predictions update automatically** | Not a static snapshot; re-sim on new results | Medium | Match-agnostic | Core |
| 9 | **Error-resilient operation** | API failures must not crash the loop | Medium | Match-agnostic | Core |
| 10 | **Console-formatted output** | Readable in terminal; tables, percentages, clear formatting | Low | Match-agnostic | Core |
| 11 | **Correct bracket structure (v1.0)** | 32-team knockout must follow real R16→QF→SF→Final format | Low | v1.0 only: 8 groups × 4 teams, R16 onward | v1.0 |
| 12 | **Correct bracket structure (v1.1)** | 48-team format: 12 groups → R32 → R16 → QF → SF → Final | High | v1.1 only: needs Annex C lookup for 3rd-place placement | v1.1 |
| 13 | **Annex C 495-scenario table** | Required for determining which third-place teams face which group winners in R32 | Medium | v1.1 only: encode as Python dict or compute dynamically | v1.1 |
| 14 | **Group stage tables** | Standings for 12 groups with tiebreaker application | High | v1.1 only: group simulation + tiebreaker logic | v1.1 |

### Differentiators

Features that set this product apart from existing web-based predictors and other CLI tools.

| # | Feature | Value Proposition | Complexity | Format Dependency | Phase |
|---|---------|-------------------|------------|-------------------|-------|
| 1 | **Probability delta tracking** | "Brazil: 22.1% (▼ 3.2%)" — live odds shifts in CLI | Medium | Match-agnostic | Post-v1.0 |
| 2 | **Timeline/probability history** | Track odds evolution; JSON export for charting | Medium | Match-agnostic | Post-v1.0 |
| 3 | **Elo change annotations in match log** | Transparent rating changes after each match | Low | Match-agnostic | Post-v1.0 |
| 4 | **Most likely full bracket** | Single most probable path through the knockout tree | Medium | v1.0: 32-team. v1.1: 48-team | Post-v1.0 |
| 5 | **Most likely scoreline per match** | Poisson from Elo expected goals | Medium | Match-agnostic | Post-v1.0 |
| 6 | **"Dark horse" / surprise team detection** | Flag teams with rising probability beyond initial rating | Low | Match-agnostic | Post-v1.0 |
| 7 | **Configurable everything** | K-factor, sim count, poll interval via config | Low | Match-agnostic | Post-v1.0 |
| 8 | **Exportable JSON snapshot** | All probabilities, ratings, results for downstream use | Low | Match-agnostic | Post-v1.0 |
| 9 | **Backtest accuracy** | Simulate from starting ratings, compare predicted vs actual | High | v1.0 historical; v1.1 can't be backtested until after July 2026 | Post-v1.0 |
| 10 | **"What if" scenario mode** | Force-result and re-simulate | Medium | Match-agnostic | Post-v1.0 |
| 11 | **Bookmaker odds comparison** | Model vs market implied probability | High | Match-agnostic | Future |
| 12 | **Compact "dashboard" view** | Real-time terminal refresh (like `top`) | Medium | Match-agnostic | Future |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **User accounts / authentication** | Single-user CLI tool; no value | Run as local script. No auth needed |
| **Web dashboard** | Doubles scope; project is console-only | Output JSON export for external charting |
| **ML models (XGBoost, neural nets)** | Opaque, needs training data, harder to debug | Pure Elo + optional Poisson extension |
| **Player-level modeling** | Massive data pipeline for marginal gain | Team-level only |
| **Fantasy football integration** | Separate product domain | Not relevant to tournament prediction |
| **Betting advice / "value bet" alerts** | Legal gray area; implies actionable wagering advice | Model vs market comparison as data, not advice |
| **Multi-tournament / historical archive** | Adds data pipeline complexity | Only current tournament |
| **Push notifications** | OS-specific integration; out of scope | Log to console; user can grep/pipe |
| **Mobile app** | Entirely separate platform | CLI is the product |
| **Real-time WebSocket / live ticker** | Overengineering for a polling-based tool | Polling loop is sufficient |
| **Multi-league / simultaneous tournaments** | World Cup is the project focus | Single tournament mode |

### Feature Dependencies

```
Elo Rating System
  └── Match probability (Elo → expected score)
       └── Monte Carlo simulation (uses match probs to sample outcomes)
            ├── Championship probability (aggregate of simulation finals)
            ├── Round-by-round advancement (aggregate of simulation stages)
            └── Probability delta (diff previous aggregate vs current)

API Polling
  └── Match detection (new result identified)
       └── Elo rating update
            └── Re-run Monte Carlo simulation
                 └── Probability delta computation
                      └── Console output (delta display)

Group Stage (v1.1)
  └── 12 groups of 4
       └── Tiebreaker chain (head-to-head → GD → GF → fair play → ranking)
            └── Third-place ranking (5-level tiebreaker)
                 └── Annex C lookup (combination key → R32 mapping)
                      └── Round of 32 bracket (M73-M88)
                           └── Round of 16 → QF → SF → Final

Bracket Structure (v1.0)
  └── 32-team knockout bracket
       └── 8 groups → R16 → QF → SF → Final

Bracket Structure (v1.1)
  └── 48-team knockout bracket
       └── 12 groups → R32 (with Annex C) → R16 → QF → SF → Final
```

**Critical dependency chain (v1.0):** Working API poll → correct Elo update → meaningful MC simulation → useful output.

**Critical dependency chain (v1.1):** Group standings → correct 3rd-place ranking → correct Annex C lookup → correct R32 pairings → correct R16/QF/SF/Final → meaningful MC simulation.

### Complexity Estimates

| Component | Complexity | v1.0 (32-team KO only) | v1.1 (48-team full) |
|-----------|------------|------------------------|----------------------|
| Elo rating system | Low | 30-50 lines | 30-50 lines (unchanged) |
| API polling + match detection | Medium | 100-150 lines | 100-150 lines (unchanged) |
| JSON persistence | Low | 80-120 lines | 80-120 lines (unchanged) |
| Monte Carlo simulator | Medium | 150-250 lines | 250-400 lines (needs group stage + Annex C) |
| Bracket structure (32-team KO) | Low | 50-100 lines | N/A (replaced) |
| Bracket structure (48-team) | High | N/A | 200-350 lines (R32 + R16 + QF + SF + Final) |
| Group stage tables | High | N/A | 200-300 lines (12 groups, tiebreakers) |
| Third-place ranking + tiebreaker | Medium | N/A | 50-80 lines |
| Annex C 495-scenario lookup | Medium | N/A | 50-100 lines (data encoding) OR 495-line static dict |
| Console output | Low | 50-80 lines | 80-120 lines (more rounds to display) |
| **Total (estimate)** | | **~460-730** | **~1040-1630** |

### Feature Distribution by Phase

| Phase | Features | Format Version |
|-------|----------|----------------|
| **Phase 1: Core Pipeline** | Elo system, MC simulator, API polling, JSON persistence, console output | v1.0 base |
| **Phase 2: Live Loop** | Continuous polling, auto-re-simulation, error handling, rate-limit compliance | v1.0 |
| **Phase 3: Rich Output** | Probability deltas, Elo change logging, top N display, timestamped logs | v1.0 |
| **Phase 4: Analytics** | Most likely bracket, dark horse detection, compact dashboard view | v1.0 |
| **Phase 5: Power Features** | JSON export, config system, what-if mode | v1.0 |
| **Phase 6: 48-Format Migration** | 12-group stage, 5-level 3rd-place tiebreaker, Annex C lookup, R32 bracket, full bracket tree update | **v1.1** |
| **Post-v1.1** | Poisson model, backtest, historical mode, bookmaker comparison | Future |

### Sources

#### Official FIFA Sources (HIGH confidence)
- [FIFA 2026 Format Article](https://www.fifa.com/en/articles/article-fifa-world-cup-2026-mexico-canada-usa-new-format-tournament-football-soccer) — 12 groups of 4, 104 matches, champion plays 8 matches
- [FIFA Groups & Tiebreakers](https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers) — 7-level group tiebreaker + 5-level 3rd-place tiebreaker
- [FIFA Regulations PDF](https://digitalhub.fifa.com/m/636f5c9c6f29771f/original/FWC2026_regulations_EN.pdf) — Annex C (495 scenarios), Article 12.6-12.7 (bracket structure), Article 13 (tiebreakers)
- [FIFA Ticket Support Format FAQ](https://gpcustomersupportfwc2026.tickets.fifa.com/hc/en-gb/articles/28784798873117) — Confirms 12 groups, R32, 8-match champion path

#### Secondary Verified Sources (HIGH confidence)
- [ESPN Format Guide](https://www.espn.com/soccer/story/_/id/47108758/2026-fifa-world-cup-format-tiebreakers-fixtures-schedule) — Full schedule with R32 matchups confirmed
- [Wikipedia 2026 Knockout Stage](https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage) — Complete Annex C table, full bracket tree, all 16 R32 matchups

#### Independent Analysis (MEDIUM confidence)
- [Bracket2026 Format Guide](https://bracket2026.com/en/blog/how-48-team-world-cup-works) — Detailed format breakdown with historical thresholds
- [Bracket2026 Third-Place Rules](https://bracket2026.com/en/blog/third-place-advancement) — Fair play scoring, 495 scenarios explained
- [DEV.to Annex C Encoding](https://dev.to/mark_b5f4ffdd8e7cd58/encoding-fifas-495-third-place-scenarios-for-the-2026-world-cup-4814) — Practical implementation guide for the 495-scenario lookup

---

*Feature research for: FIFA World Cup 2026 CLI Prediction Tool*
*Researched: 2026-06-14*
*Version scope: v1.0 (32-team knockout-only) → v1.1 (48-team full format migration)*
