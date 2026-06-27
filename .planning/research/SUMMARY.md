# Project Research Summary

**Project:** Football Prediction Engine — UCL & League Modules
**Domain:** Sports simulation / football tournament prediction (Monte Carlo, Poisson, Elo)
**Researched:** 2026-06-27
**Confidence:** HIGH

## Executive Summary

This project extends an existing football prediction engine (proven on 48-team World Cup and 24-team Euro tournaments) to support the new UEFA Champions League Swiss-system format (2025+) and domestic league competitions (La Liga, Premier League). The engine uses Monte Carlo simulation (50K iterations), Poisson goal-scoring models, and Elo ratings to compute advancement probabilities. The UCL module introduces fundamentally new structural logic — a 36-team league table with no head-to-head tiebreakers, a two-legged knockout playoff between positions 9-24, and a seeded bracket construction — while the league module adds double round-robin season simulation, promotion/relegation mechanics, and configurable tiebreaker chains.

The recommended approach is to build UCL first (per PROJECT.md priority), then league modules. **No new runtime dependencies are required** — the existing Python 3.11+ stack, `football_core` library (Poisson scoring, Elo, knockout), JSON persistence, and Monte Carlo framework are sufficient. New competition-specific logic lives in `competitions/ucl/` and `competitions/league/` directories, extending `football_core` via imports rather than modifying shared code.

**The key risks are:** (1) reusing head-to-head tiebreaker logic from `football_core` in UCL's Swiss system (produces wrong standings), (2) incorrectly seeding the R16 bracket from playoff results, and (3) league simulation being 3-10× slower than tournament simulation due to 380+ matches per iteration. All three have clear prevention strategies documented in the pitfall research: dedicated tiebreaker chains, exact UEFA pairing tables, and flat-pass simulation precomputation.

---

## Key Findings

### Recommended Stack

The stack is **proven and unchanging**. The existing World Cup and Euro modules already validate the full technology chain. No new dependencies, no version upgrades, no infrastructure changes.

**Core technologies:**
- **Python 3.11+** — runtime, existing constraint (target 3.10-3.12)
- **`football_core` (current)** — shared engine: Poisson scoring, Elo ratings, knockout simulation, fetcher, predictors, math_utils
- **JSON files** (via tempfile+os.replace) — state persistence, existing pattern
- **CLI (argparse)** — entry point, no UI layer
- **python-dotenv** — environment variable loading for API keys
- **requests** — HTTP API calls (BSD API, eloratings.net)
- **catboost** — ML signal ingestion (BSD CatBoost predictions)

**New code lives in competition modules only** — no changes to `football_core` until the Rule of Two (two proven consumers) is satisfied. New modules include `league_table.py`, `tiebreakers.py`, `playoffs.py`, `bracket_setup.py`, `et_penalties.py` for UCL, and `standings.py`, `promotion.py`, `euro_qual.py` for league.

### Expected Features

Research identified a clear hierarchy across two competition targets:

**Must have (table stakes) — UCL:**
- 36-team league table simulation with pot-constrained opponents (8 matches per team) — HIGH complexity
- UCL-specific tiebreaker chain: GD → GS → away GS → wins → away wins → opponent points → opponent GD → opponent GS → disciplinary → UEFA coefficient — MEDIUM complexity
- Knockout playoff simulation (positions 9-24, two-legged with aggregate → ET → penalties) — HIGH complexity
- Seeded R16 bracket with top-4 seeding protection — MEDIUM complexity
- League standings display (36-row table with positions, points, GD, GS, form) — MEDIUM complexity

**Must have (table stakes) — League:**
- Double round-robin table simulation (38 or 46 matchdays) — HIGH complexity
- Configurable tiebreaker chain per league (PL: GD→GS→H2H or La Liga: H2H→GD→GS) — MEDIUM complexity
- Home/away form split tracking — LOW complexity
- Promotion/relegation logic (configurable N-up/M-down) — MEDIUM complexity
- European qualification mapping (position → UCL/Europa/Conference) — MEDIUM complexity
- Full league standings display (P, W, D, L, GF, GA, GD, Pts, Form) — MEDIUM complexity

**Should have (differentiators — v2+):**
- Post-Swiss knockout path visualization — MEDIUM
- What-if scenarios for final matchday — HIGH
- League schedule difficulty analysis (SoS) — MEDIUM
- Relegation probability with "points needed" projection — MEDIUM
- Promotion play-off probability breakdown (auto vs play-off vs none) — LOW
- Form trend overlay (rolling 5-match vs season average) — LOW
- Home/away form divergence detector — LOW
- Confidence interval on league position — MEDIUM
- UCL pot simulation at season start — LOW
- Form-weighted Poisson lambda — MEDIUM
- Derby/matchup-specific adjustments — LOW
- Transfer window impact estimation — HIGH (complex, needs winter window modeling)
- Injury-impact simulation — HIGH (needs lineup data integration)

**Anti-features (explicitly NOT to build):**
- Head-to-head tiebreaker for UCL (incorrect — Swiss system doesn't support H2H)
- Away goals rule (abolished 2021)
- Country protection in UCL R16 (doesn't exist in new format)
- Betting odds display, live in-play adjustment, web UI, pip-installable package, real-time odds scraping, squad depth modeling, manager tactical modeling — all out of scope

### Architecture Approach

The architecture follows the **extend-via-import** pattern established by the existing WC and Euro modules. Competition-specific logic lives entirely within `competitions/ucl/` and `competitions/league/` directories, importing generic primitives (Poisson scoring, Elo, knockout shells) from `football_core`. The **Competition-Boundary Contract** enforces zero competition-specific logic in the shared core — new shared utilities (like extra time/penalties) are added to `football_core` only when two competitions require them (Rule of Two).

**Major components — UCL:**
1. `ucl/simulation.py` — orchestrates 50K MC: league phase → playoff → knockout, all in a single loop
2. `ucl/src/league_table.py` — computes 36-team Swiss standings with UCL tiebreaker chain, determines qualification bands
3. `ucl/src/playoffs.py` — pairs 9-16 vs 17-24, simulates two-legged ties with aggregate → ET → pens
4. `ucl/src/bracket_setup.py` — builds R16 pairings with exact UEFA seed pairings, top-4 protection
5. `ucl/src/et_penalties.py` — ET simulation (reduced Poisson lambda) + penalty shootout (50/50 + skill factor)
6. `ucl/display.py` — 36-row league table + knockout bracket visualization

**Major components — League:**
1. `league/simulation.py` — iterates 38-46 matchdays, accumulates standings, applies promotion/relegation
2. `league/src/standings.py` — per-matchday table with configurable tiebreaker chain (tuple-based)
3. `league/src/promotion.py` — auto-promotion, relegation, play-off participants with configurable structure
4. `league/src/euro_qual.py` — position-to-tournament mapping
5. `league/display.py` — P/W/D/L/GF/GA/GD/Pts/Form table

**Key data flow patterns:**
- Precompute match lambdas before the MC loop (not per-iteration) for performance
- For UCL two-legged ties: aggregate-first, detail-second (simulate aggregate, only ET/pens if tied)
- For league: flat-pass all 380 matches per iteration, compute final standings once (not per-matchday)
- Eliminated teams (positions 25-36 in UCL) stop being tracked — no Europa League drop-down

### Critical Pitfalls

1. **Reusing H2H tiebreaker in UCL league phase** — Using `football_core.groups._tiebreak_group()` for Swiss standings produces incorrect results because not all teams play each other. **Prevention:** Implement a separate `compute_swiss_standings()` with GD → GS → away GS → wins → away wins → opponent strength chain. Add a protection assertion.

2. **Simulating UCL playoff as single-leg knockout** — The 9-24 playoff is two-legged, but `football_core.knockout._simulate_knockout_round()` handles single-match. **Prevention:** Build dedicated `simulate_two_legged_tie()` with aggregate → ET → penalties.

3. **Incorrect knockout playoff seed inheritance** — R16 pairings follow a specific UEFA table (1st/2nd vs winner of [15th/16th vs 17th/18th], etc.), not a generic "top seed vs lowest survivor." **Prevention:** Implement exact UEFA pairing table; validate with test cases.

4. **League simulation performance blowup** — 380+ matches × 50K MC iterations = 19M match simulations. Naive per-matchday nesting is 3-10× slower. **Prevention:** Flat-pass all matches per iteration; precompute lambdas; investigate numpy vectorized Poisson sampling.

5. **Breaking WC regression suite during UCL development** — Modifying `football_core` could break 613 existing tests. **Prevention:** New modules > modifying existing; add ET/pens as `football_core.et_penalties` rather than modifying `football_core.knockout`; run full test suite before every commit.

---

## Implications for Roadmap

Based on the combined research, the recommended phase structure follows a **UCL-first, foundation-before-polish** ordering. UCL phases are prioritized by PROJECT.md, and within each competition, the core simulation engine must come before visualization, analysis, or differentiators.

### Suggested Phase Structure

### Phase ENG-01: UCL League Table Engine
**Rationale:** The 36-team league table is the foundational piece — everything else (playoffs, bracket, knockout) depends on correct standings. No other phase can begin until this is functional and correct.
**Delivers:** Working UCL league phase simulation — 36-team standings with correct tiebreaker chain, Monte Carlo over 144 matches per iteration, qualification band determination (1-8, 9-16, 17-24, 25-36).
**Addresses (FEATURES.md):** UCL table stakes #1 (36-team table), #2 (UCL tiebreakers), #10 (standings display)
**Avoids (PITFALLS.md):** Pitfall #1 (H2H tiebreaker — dedicated Swiss tiebreaker function), Pitfall #7 (WC tests — no `football_core` changes)
**Research flag:** Well-documented pattern. No deeper research needed — domain rules are officially documented by UEFA.

### Phase ENG-02: UCL Knockout Phase (Playoffs + Bracket + ET/Pens)
**Rationale:** Once league phase produces correct standings, the next layer is the knockout pipeline — playoff (positions 9-24), seeded R16 bracket construction, and full knockout through to the final. ET/penalties are required for realistic two-legged aggregate resolution.
**Delivers:** Complete UCL tournament simulation — league → playoff → R16 → QF → SF → Final with correct bracket seeding, two-legged playoff resolution, and ET/pens decider.
**Addresses (FEATURES.md):** UCL table stakes #3 (playoff), #4 (seeded bracket), #5 (top-4 protection), #6 (no away goals), #7 (ET/pens), #9 (second-leg home advantage)
**Avoids (PITFALLS.md):** Pitfall #2 (two-leg simulation), Pitfall #3 (no away goals), Pitfall #4 (no country protection), Pitfall #5 (exact seed pairing), Pitfall #7 (new `football_core.et_penalties` module)
**Research flag:** Bracket seeding rules need careful implementation — use the exact UEFA pairing table. ET/penalties module may be extracted to `football_core` if Rule of Two later satisfied.

### Phase ENG-03: UCL Simulation Orchestration + Display
**Rationale:** With individual components built, this phase wires them into a single simulation pipeline and produces the full output. This is where the "product" becomes usable.
**Delivers:** `ucl/simulation.py` orchestrating all phases, `ucl/display.py` producing formatted output, CLI entry point with options for iterations, output format, etc. Config flags for simultaneous final matchday scheduling.
**Addresses (FEATURES.md):** UCL table stakes #8 (simultaneous matchday), full integration of ENG-01 + ENG-02 outputs
**Avoids (PITFALLS.md):** Performance is less critical here — 144 matches per iteration is manageable at 50K

### Phase ENG-04: UCL Differentiators
**Rationale:** Once the core simulation is stable and correct, add analytical features that provide competitive advantage. These are independent of each other and can be parallelized.
**Delivers:** Post-Swiss knockout path visualization, what-if scenario engine for final matchday, UCL pot simulation, form-weighted Poisson lambda, confidence intervals on advancement.
**Addresses (FEATURES.md):** UCL differentiators #1 (path visualization), #2 (playoff qualification probability breakdown), #3 (what-if scenarios), #13 (pot simulation), #14 (form-weighted lambda)
**Avoids (PITFALLS.md):** None new — all anti-features already documented
**Research flag:** What-if engine is HIGH complexity and may need its own shorter research phase during planning. The approach (re-running MC with one result constrained) is conceptually clear but implementation detail needs thought.

### Phase ENG-05: League Core Engine (Double Round-Robin)
**Rationale:** UCL completion frees up focus for league module. The core league engine needs to handle fundamentally different dynamics — 380+ matches per iteration, per-matchday standings accumulation, and league-specific tiebreaker chains.
**Delivers:** `league/simulation.py` with flat-pass simulation, `league/src/standings.py` with configurable tiebreaker chains (PL/La Liga presets), `league/display.py` with full 20-row table output.
**Addresses (FEATURES.md):** League table stakes #1 (double round-robin), #2 (tiebreaker chain), #3 (home/away split), #8 (form indicator), #9 (standings display)
**Avoids (PITFALLS.md):** Pitfall #6 (performance blowup — flat-pass simulation, precomputed lambdas), moderate pitfalls (home advantage coefficient mismatch, configurable tiebreakers)
**Research flag:** **Performance is critical here.** This phase likely needs a `/gsd-plan-phase --research-phase` call during planning to validate performance targets. Investigate numpy vectorized Poisson sampling and benchmark against 50K iterations × 380 matches. If runtime exceeds 30s, optimization strategies must be committed before feature work.

### Phase ENG-06: League Promotion/Relegation Play-offs
**Rationale:** Promotion and relegation are distinct enough from basic standings to warrant a separate phase. The logic is modular — `league/src/promotion.py` and `league/src/euro_qual.py` are self-contained.
**Delivers:** Configurable N-up/M-down relegation, automatic promotion positions, play-off promotion (configurable team count and round structure), European qualification position mapping.
**Addresses (FEATURES.md):** League table stakes #4 (promotion/relegation), #5 (auto-promotion), #6 (play-off promotion), #7 (Euro qualification)
**Avoids (PITFALLS.md):** Moderate pitfalls (hardcoded promotion counts, play-off format differences — make everything configurable)
**Research flag:** Play-off structure varies significantly across leagues (EFL Championship 6-team format from 2026-27, La Liga Segunda 4-team, National League 6-team with different format). This needs detailed parameter research during planning.

### Phase ENG-07: League Differentiators
**Rationale:** Analytical features that build on the core league engine and make it valuable beyond basic probability output.
**Delivers:** Schedule difficulty analysis (SoS), relegation threshold projection, promotion probability breakdown, form trend overlay, home/away form divergence detector, confidence interval on league position, transfer window impact (simplified), injury-impact (if lineup data available).
**Addresses (FEATURES.md):** League differentiators #4-12, #14
**Research flag:** Injury-impact (#9) and transfer window (#10) are HIGH complexity and may need a separate research/validation phase. The simpler Elo-based approach (capture strength changes through results) may be sufficient without per-player modeling.

### Phase Ordering Rationale

- **UCL before League** — mandated by PROJECT.md, and UCL's simpler match density (144 matches vs 380) makes it a gentler on-ramp for developing the new simulation patterns
- **Core engine before polish** — standings correctness must be validated before any analytics layer can be built on top
- **Foundation before differentiators** — differentiators are valuable but add complexity; deferring them avoids slowing down the core implementation
- **Performance work in league phase** — league simulation is 3-10× more expensive than UCL; performance optimization belongs with the league core, not retrofitted later
- **Anti-features documented upfront** — prevents wasted effort on H2H tiebreakers, away goals, country protection, etc.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase ENG-05 (League Core):** **Critical research needed on performance.** Must validate flat-pass simulation overhead, benchmark against 50K × 380 matches, and determine if numpy vectorization is necessary. This phase should include a `/gsd-plan-phase --research-phase` call.
- **Phase ENG-07 (League Differentiators):** Injury-impact and transfer window features need data availability research — can existing BSD API provide lineup data? Is there a proxy approach that avoids per-player modeling?
- **Phase ENG-04 (UCL Differentiators):** What-if scenario engine design needs thought — constrained MC re-run or conditional probability calculation? Complexity is HIGH.

Phases with standard patterns (skip research-phase):
- **Phase ENG-01 (UCL Table):** UEFA rules are officially documented and well-understood. Patterns from existing WC/Euro code directly transfer.
- **Phase ENG-02 (UCL Knockout):** Bracket simulation follows existing `football_core.knockout` patterns; the new elements (two-leg, seed pairing) are well-specified by UEFA documentation.
- **Phase ENG-06 (League Promotion):** Rules are well-documented even if varying; the parameterized approach is standard.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** | No new dependencies required. Stack is proven by 2 existing competition modules (WC + Euro). Existing constraints and codebase are primary sources. |
| Features | **MEDIUM** | Table stakes are well-documented from UEFA, PL, La Liga official sources. Differentiators are inferred from analytical value, not user research. Confidence is HIGH for must-haves, LOW for which differentiators provide most value. |
| Architecture | **HIGH** | Extend-via-import and Competition-Boundary Contract patterns are proven across existing modules. The recommended file structure directly mirrors WC/Euro conventions. Performance estimates need validation. |
| Pitfalls | **HIGH** | Top 7 critical pitfalls have clear prevention strategies verified against multiple sources (UEFA, Sporting News, codebase, project constraints). Moderate/minor pitfalls are well-understood. |

**Overall confidence:** HIGH for the UCL module (good official documentation, close analog to existing patterns). MEDIUM for the league module (performance uncertainty, varying league rules, less established pattern).

### Gaps to Address

- **Lineup/injury data availability:** Injury-impact simulation (differentiator #9) requires per-player data. Current BSD API provides team-level odds only. Needs validation during planning — if unavailable, skip or use Elo-only proxy.
- **Transfer window impact validation:** Modeling winter transfer impact is high-complexity with limited data validation path. The Elo-drift approach (ratings adjust through results) may be sufficient without explicit transfer modeling.
- **League tiebreaker chains for non-PL/La Liga leagues:** Research covers PL and La Liga as primary targets. Bundesliga, Serie A, Ligue 1 may have subtle variations. Documented as configurable, but presets need verification.
- **Performance benchmarks:** League simulation runtime estimates (8-20s per 50K pass) are extrapolated from WC patterns, not measured. Actual benchmarking is needed during Phase ENG-05 planning.
- **UCL coefficient data:** The 10th tiebreaker (UEFA club coefficient) requires hardcoded data from latest UEFA rankings. Source has MEDIUM confidence — needs verification during implementation.
- **Simultaneous matchday scheduling edge cases:** Final matchday simultaneity may affect how results are exposed to the model. Currently flagged as a config option, but the impact on MC iteration ordering needs thought.

---

## Sources

### Primary (HIGH confidence)
- Codebase: `football_core/{groups,knockout,elo}.py` — existing Poisson modeling, Elo ratings, knockout simulation
- Codebase: `competitions/worldcup/src/{groups,knockout}.py` — proven WC simulation patterns
- PROJECT.md (`.planning/PROJECT.md`) — project priorities, constraints, scope decisions
- Constraints (`.planning/intel/constraints.md`) — architecture boundaries, test requirements
- Premier League — [relegation FAQ](https://www.premierleague.com/en/news/4657245/202526-premier-league-relegation-faq) — official relegation rules
- Sky Sports — [Championship play-off expansion](https://www.skysports.com/football/news/11688/13515549/championship-play-offs-efl-confirms-expansion-from-four-to-six-teams-from-2026-27-season-onwards) — official confirmation of 6-team format
- UEFA.com — [UCL format documentation](https://www.uefa.com/uefachampionsleague/news/0296-1d21e9bdf7e4-808a7511165c-1000--2025-26-champions-league-format-dates-draws-final/) — official UCL format rules

### Secondary (MEDIUM confidence)
- Sporting News — [UCL tiebreaker rules](https://www.sportingnews.com/uk/football/news/champions-league-tiebreaker-level-points-league-phase-uefa/54f8a7396551932b2a87fe87) — verified against UEFA regulations
- Sporting News — [UCL knockout bracket explained](https://www.sportingnews.com/uk/football/news/champions-league-bracket-explained-knockout-round-16-playoffs/09410346dd5c2cad44e6058f) — bracket structure analysis
- Sporting News — [Swiss Model explained](https://www.sportingnews.com/us/soccer/news/swiss-model-champions-league-uefa-debut-ucl-format-group-stage/a2d1e16bb0f0d24b364d4db4) — format rationale
- NBC Sports — [Premier League tiebreaker rules 2026](https://www.nbcsports.com/soccer/news/premier-league-tiebreaker-rules-2026-goal-difference-head-to-head-record-how-it-works) — PL tiebreaker chain
- All About Football — [La Liga relegation/promotion system](https://allaboutfootball.net/la-liga-relegation-and-promotion-system/) — league system analysis

### Tertiary (LOW confidence)
- Various blog/forum sources on specific league tiebreaker edge cases — not relied upon for critical decisions
- UEFA coefficient data (needs verification from official UEFA club ranking published in-season)

---

*Research completed: 2026-06-27*
*Ready for roadmap: yes*
