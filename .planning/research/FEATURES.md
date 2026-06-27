# Feature Landscape: UCL & League Football Prediction

**Domain:** UEFA Champions League (Swiss-system) + Domestic League (double round-robin) prediction modules  
**Researched:** 2026-06-27  
**Existing system:** World Cup (48-team, 12 groups) + Euro (24-team, 6 groups) — Poisson simulation, Elo ratings, signal blending, Monte Carlo 50K iterations

---

## What Makes UCL Unique vs WC/Euro

Before listing features, the key structural differences matter for every feature decision:

| Dimension | World Cup / Euro | UCL (2025+) | League (La Liga/PL) |
|-----------|-----------------|-------------|---------------------|
| **Stage 1 format** | Fixed round-robin groups (4 teams) | Single 36-team league table | Double round-robin (38-46 matches) |
| **Stage 1 fixture count** | 3 per team | 8 per team | 38-46 per team |
| **Stage 1 opponent selection** | All group opponents | 2 from each of 4 pots | Every other team ×2 |
| **Tiebreaker basis** | Head-to-head (all played each other) | No H2H (not all played each other) | Varies: H2H (La Liga) or GD (PL) |
| **Advancement cut** | Top 2 per group + best 3rds | Top 8 direct, 9-24 playoff | N/A (full season points) |
| **Knockout round-of-16** | Fixed bracket by group position | Seeded by league position + playoff | N/A (no knockout) |
| **Away goals rule** | Did not exist in WC/Euro (neutral venues) | Abolished in UCL (2021-) | N/A |
| **Home advantage** | Neutral for WC; low for Euro | Strong (club competition) | Significant (varies by league) |
| **Schedule type** | Tournament (weeks) | Mixed (Sep-Jan league + Feb-May knockout) | Season-long (Aug-May) |
| **Structural features** | Third-place ranking, Annex C | Seeding protection, bracket predetermination | Promotion, relegation, play-offs |

---

## TABLE STAKES — Must Have

Features that make a UCL or league prediction module functional. Without these, the module doesn't work.

### UCL Table Stakes

| # | Feature | Complexity | Why Required | Reuses `football_core`? |
|---|---------|------------|-------------|------------------------|
| 1 | **36-team league table simulation** — 8 matches per team, pot-constrained opponents (2 from each of 4 pots) | **High** | Central structural feature; entirely different from round-robin groups | Partial — Poisson scoring model from `groups.py` |
| 2 | **UCL-specific tiebreaker chain** — GD → GS → away GS → wins → away wins → opponent points → opponent GD → opponent GS → disciplinary → UEFA coefficient | **Medium** | No head-to-head possible (not all teams play each other); tiebreakers differ from WC/Euro group rules | New logic required (no equivalent in `football_core`) |
| 3 | **Knockout playoff simulation** — teams 9-24 compete in two-legged ties to reach R16 | **High** | Unique to UCL format; 8 winners join top 8 teams in R16 | Partial — `football_core.knockout` provides round simulation but needs two-legged aggregation |
| 4 | **Seeded knockout bracket** — top 8 vs playoff winners with position-based pairings (1/2 vs 15/18, 3/4 vs 13/20, etc.) | **Medium** | Bracket structure is predetermined by league position; entirely different from WC/Euro bracket rules | New logic required |
| 5 | **Top-4 seeding protection** — seeds 1-4 cannot meet each other until semifinals | **Low** | Explicit UEFA rule that affects bracket construction | New logic |
| 6 | **No away goals rule** — aggregate ties go to extra time → penalties | **Low** | UEFA abolished away goals in 2021; must not apply in UCL knockout | New logic for `knockout.py` (currently has no away goals concept, but ET/pens is new) |
| 7 | **Extra time + penalty shootout simulation** for knockout ties level on aggregate | **Medium** | Required for two-legged knockout realism | New logic required |
| 8 | **Simultaneous matchday scheduling** — all 18 matches kick off simultaneously on final matchday | **Low** | Key UCL rule — affects when results become available for simulation | Config flag only |
| 9 | **Second-leg home advantage for higher seed** — higher-seeded team always plays R16/playoff 2nd leg at home | **Low** | UEFA rule; affects match probability for second leg | New logic |
| 10 | **League phase standings display** — single 36-row table with positions, points, GD, GS, form | **Medium** | Primary output format; different from group-stage display | New display module |

### League (La Liga / Premier League) Table Stakes

| # | Feature | Complexity | Why Required | Reuses `football_core`? |
|---|---------|------------|-------------|------------------------|
| 1 | **Double round-robin table simulation** — 38 matchdays (20 teams) or 46 (24 teams) | **High** | Central structural feature; long season with complex schedule | Partial — Poisson model, but needs per-matchday iteration |
| 2 | **League-specific tiebreaker chain** — configurable per league (PL: GD→GS→H2H→H2H away→playoff; La Liga: H2H points→H2H GD→H2H GS→GD→GS) | **Medium** | Different league use different rules; La Liga uses H2H first, PL uses GD first | New logic required (generic configurable chain) |
| 3 | **Home/away form split tracking** — separate home and away record in standings | **Low** | Standard table feature; informs prediction adjustments | New logic |
| 4 | **Promotion / relegation logic** — bottom N relegated, top N promoted (configurable: 3 up/3 down standard) | **Medium** | Core league mechanic; affects what "advancement" means | New logic (generic: N promoted, M relegated) |
| 5 | **Automatic promotion positions** — top 2 (or N) teams promoted directly | **Low** | Standard league feature | Config parameter |
| 6 | **Play-off promotion** — positions 3-6 (or expanded 3-8) compete for final promotion spot | **Medium** | EFL Championship, La Liga Segunda, etc. | New logic (two-legged semis + final) |
| 7 | **European qualification logic** — top N qualify for UCL/Europa/Conference based on final position | **Medium** | Required for realistic league simulation (affects what "success" means) | New logic (position→tournament mapping) |
| 8 | **Recent form indicator** — last N matches (typically 5) with W/D/L streak | **Low** | Standard league display feature | Reuse pattern from existing form tracking |
| 9 | **Full league standings display** — 20/24-row table with P, W, D, L, GF, GA, GD, Pts, Form | **Medium** | Primary output format | New display module |

---

## DIFFERENTIATORS — Competitive Advantage

Features that set this prediction engine apart from basic prediction tools. Not strictly necessary for correctness, but provide analytical value.

| # | Feature | Complexity | Value Proposition | Target |
|---|---------|------------|-------------------|--------|
| 1 | **Post-Swiss knockout path visualization** — show each team's possible bracket path after league phase | **Medium** | Users can see "if Team X finishes 7th, they'll face Y in R16, then Z in QF..." | UCL |
| 2 | **Knockout playoff qualification probability** — P(finish 9-24) broken down by seed threshold | **Medium** | Finer granularity than just "advance"; does team finish 9-16 (seeded) or 17-24 (unseeded)? | UCL |
| 3 | **What-if scenarios for final MD** — recalculate probabilities given one specific match result changes | **High** | "What if Real Madrid beats Liverpool 2-0?" — live during simultaneous final matchday | UCL |
| 4 | **League schedule difficulty analysis** — strength of remaining opponents (SoS metric) | **Medium** | "Team X has easier run-in than Team Y" — valuable for mid-season league prediction | League |
| 5 | **Relegation probability with "points needed" projection** — P(relegation) + estimated survival threshold | **Medium** | More actionable than raw probability — "Team needs 8 points from 5 games" | League |
| 6 | **Promotion play-off probability breakdown** — P(automatic) vs P(play-off) vs P(none) | **Low** | Three-tier outcome distribution for promotion race | League |
| 7 | **Form trend overlay** — rolling 5-match points-per-game vs season average, plotted over season | **Low** | Shows which teams are improving/declining — predictive signal | League |
| 8 | **Home/away form divergence detector** — highlight teams with statistically significant home/away splits | **Low** | "Team A is strong at home but weak away" — actionable for match prediction | League |
| 9 | **Injury-impact simulation** — adjust Elo/probability when key player is missing (using lineup data) | **High** | More realistic short-term prediction during live season | Both |
| 10 | **Transfer window impact estimation** — model how squad changes affect team strength mid-season | **High** | Winter transfers can significantly alter league trajectories | League |
| 11 | **Derby/matchup-specific adjustments** — historical H2H bias for specific rivalries | **Low** | Some matchups defy form (e.g., El Clásico, North West Derby) | Both |
| 12 | **Confidence interval on league position** — show not just most likely position but ± range | **Medium** | "Team X is expected 4th but could finish anywhere from 2nd-7th" | League |
| 13 | **UCL pot simulation at season start** — which pot each team falls into, influencing draw difficulty | **Low** | Pre-season analysis; affects probability of easy/hard schedule | UCL |
| 14 | **Form-weighted Poisson lambda** — recent 5-match xG form weighted higher than season average | **Medium** | Short-term form beats long-term average in prediction accuracy | Both |

---

## ANTI-FEATURES — Explicitly NOT to Build

Features that seem attractive but should be rejected.

| # | Feature | Why Avoid | What to Do Instead |
|---|---------|-----------|-------------------|
| 1 | **Head-to-head tiebreaker for UCL league phase** | UCL's Swiss system does NOT use H2H (not all teams play each other); implementing it would be incorrect | Use GD → GS → away GS → wins → away wins → opponent strength chain |
| 2 | **Away goals rule for knockout** | UEFA abolished away goals in 2021; would produce inaccurate simulation | Aggregate → ET → penalties |
| 3 | **Country protection in UCL R16 draw** | UCL has NO country protection in R16 anymore; same-nation clubs CAN meet | Allow any pairing |
| 4 | **CLI betting odds display** | Expressly out of scope per PROJECT.md ("predictions are tournament-forecast, not in-play") | Keep output as probability tables only |
| 5 | **Live in-play adjustment** | Out of scope; engine updates between matchdays, not during live matches | Polling loop refreshes post-match only |
| 6 | **Web UI / dashboard** | Separate project per PROJECT.md; would add packaging/frontend dependency | Keep CLI-only |
| 7 | **pip-installable package** | Deferred until 3 competitions are proven stable | Keep sys.path bootstrap |
| 8 | **Real-time odds scraping** | Requires rate-limited API with no guarantee of availability; adds fragility | Use existing BSD API odds integration |
| 9 | **Squad depth / substitution modeling** | Too complex for simulation; requires per-player data unavailable via current API | Use team-level Elo rating as strength proxy |
| 10 | **Manager tactical style modeling** | Subjective, not data-available; would introduce false precision | Stick to statistical models (Poisson, Elo, signals) |

---

## UCL-Specific Feature Dependencies

```
UCL Module
├── League Phase (table stakes)
│   ├── 36-team league table engine  ← NEW (no existing equivalent)
│   ├── Pot-constrained schedule model ← NEW
│   ├── UCL tiebreaker chain        ← NEW
│   ├── League standings computation  ← NEW
│   └── Final MD simultaneous scheduling ← MINOR (config flag)
│
├── Knockout Phase
│   ├── Knockout playoff simulation  ← NEW (two-leg + seed pairing)
│   │   ├── Away goals rule (abolished) → ET → penalties ← NEW
│   │   └── Second-leg home advantage for seeded teams ← NEW
│   ├── Seeded R16 bracket setup     ← NEW (position-based)
│   │   ├── Top-4 seeding protection ← NEW
│   │   └── Pre-determined quarter paths ← NEW
│   ├── QF/SF/Final simulation       ← REUSE football_core.knockout (with ET/pens addition)
│   └── Bracket visualization         ← DIFFERENTIATOR
│
└── Shared with existing
    ├── Poisson scoring model        ← REUSE football_core.groups
    ├── Elo ratings                  ← REUSE football_core.elo
    ├── Signal blending (Elo/odds/CatBoost) ← REUSE football_core.predictors + blender pattern
    ├── Monte Carlo framework        ← REUSE pattern from WC/Euro
    ├── Evaluation framework         ← REUSE pattern from WC
    └── Governance                   ← REUSE pattern from WC
```

## League Feature Dependencies

```
League Module (La Liga / Premier League)
├── Season-long Simulation (table stakes)
│   ├── Double round-robin schedule    ← NEW (38-46 matches per team)
│   ├── Per-matchday iteration engine  ← NEW
│   ├── League-specific tiebreaker chain (configurable) ← NEW
│   │   ├── PL: GD → GS → H2H → H2H away → playoff ← config
│   │   └── La Liga: H2H → H2H GD → H2H GS → GD → GS ← config
│   ├── Home/away form split           ← NEW
│   └── Full standings display (P/W/D/L/GF/GA/GD/Pts/Form) ← NEW
│
├── Promotion/Relegation (table stakes)
│   ├── Auto-promotion positions (top N)  ← NEW (generic config)
│   ├── Relegation positions (bottom M)   ← NEW (generic config)
│   └── Play-off promotion (two-legged → final) ← NEW
│
├── European Qualification (table stakes)
│   ├── Position-to-tournament mapping ← NEW (configurable per league)
│   └── UCL/Europa/Conference slots   ← NEW
│
├── Differentiators
│   ├── Schedule difficulty (SoS)       ← DIFFERENTIATOR
│   ├── Relegation threshold projection ← DIFFERENTIATOR
│   ├── Play-off probability breakdown  ← DIFFERENTIATOR
│   ├── Form trend overlay              ← DIFFERENTIATOR
│   ├── H/A form divergence detector    ← DIFFERENTIATOR
│   └── Confidence interval on position ← DIFFERENTIATOR
│
└── Shared with existing
    ├── Poisson scoring model          ← REUSE football_core.groups
    ├── Elo ratings + updates          ← REUSE football_core.elo
    ├── Signal blending                ← REUSE football_core.predictors + blender pattern
    ├── Monte Carlo framework          ← REUSE pattern
    ├── Evaluation framework           ← REUSE pattern
    └── Governance                     ← REUSE pattern
```

---

## Complexity Assessment Legend

| Level | Effort | Test Count Estimate | Dependencies |
|-------|--------|-------------------|-------------|
| **Low** | < 50 LOC, 1-2 files | 10-20 tests | Trivial config/display changes |
| **Medium** | 50-200 LOC, 2-3 files | 30-60 tests | New logic that parallels existing patterns |
| **High** | 200-500+ LOC, 3-6+ files | 60-150+ tests | New algorithmic work, may need `football_core` additions |

---

## MVP Recommendation (UCL First, Then League)

Per PROJECT.md decision, UCL is next (not league). Recommended feature order:

### UCL MVP (Phase ENG-01)
1. **36-team league table simulation** — the core engine (HIGH)
2. **UCL tiebreaker chain** — required for correct standings (MEDIUM)
3. **League standings display** — 36-row table (MEDIUM)
4. **Knockout playoff simulation** — 9-24 seeded two-legged (HIGH)
5. **Seeded R16 bracket + knockout** — rely on `football_core.knockout` (MEDIUM)
6. **Extra time / penalties** — required for UCL knockout correctness (MEDIUM)

**Defer:** Top-4 seeding protection (minor), simultaneous matchday (config), what-if scenarios (differentiator).

### League MVP (Phase ENG-05)
1. **Double round-robin table simulation** — 38-matchday engine (HIGH)
2. **Generic tiebreaker chain** — configurable per league (MEDIUM)
3. **Promotion/relegation logic** — N-up/M-down generic (MEDIUM)
4. **Full standings display** — 20-row table with form (MEDIUM)

**Defer:** Play-off promotion (complex), European qualification (derived metric), schedule difficulty (differentiator).

---

## Sources

- UEFA.com — 2025/26 UCL format, dates, draw rules: https://www.uefa.com/uefachampionsleague/news/0296-1d21e9bdf7e4-808a7511165c-1000--2025-26-champions-league-format-dates-draws-final/ (MEDIUM confidence — official source)
- Sporting News — UCL tiebreaker rules explained: https://www.sportingnews.com/uk/football/news/champions-league-tiebreaker-level-points-league-phase-uefa/54f8a7396551932b2a87fe87 (MEDIUM confidence — mainstream sports journalism, verified against UEFA regulations)
- Sporting News — UCL knockout bracket explained: https://www.sportingnews.com/uk/football/news/champions-league-bracket-explained-knockout-round-16-playoffs/09410346dd5c2cad44e6058f (MEDIUM confidence)
- NBC Sports — Premier League tiebreaker rules 2026: https://www.nbcsports.com/soccer/news/premier-league-tiebreaker-rules-2026-goal-difference-head-to-head-record-how-it-works (MEDIUM confidence)
- Premier League — 2025/26 relegation FAQ: https://www.premierleague.com/en/news/4657245/202526-premier-league-relegation-faq (HIGH confidence — official source)
- All About Football — La Liga relegation/promotion system: https://allaboutfootball.net/la-liga-relegation-and-promotion-system/ (MEDIUM confidence — niche sports analysis)
- Sporting News — Swiss Model explained: https://www.sportingnews.com/us/soccer/news/swiss-model-champions-league-uefa-debut-ucl-format-group-stage/a2d1e16bb0f0d24b364d4db4 (MEDIUM confidence)
- Project constraints — .planning/intel/constraints.md, .planning/PROJECT.md (HIGH confidence — project source)
- Existing codebase — football_core/{groups,knockout,elo}.py + competitions/worldcup/src/{groups,knockout}.py (HIGH confidence — verified source)
