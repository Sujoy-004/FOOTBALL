# Feature Landscape: Live Football Tournament Prediction

**Domain:** CLI-based live football tournament prediction (World Cup 2026)
**Researched:** 2026-06-13
**Mode:** Ecosystem research — features analysis (comparisons: FiveThirtyEight/SPI/PELE, ESPN, Silver Bulletin, open-source WC predictors on GitHub)

## Executive Summary

The football tournament prediction ecosystem is dominated by web dashboards (FiveThirtyEight/Silver Bulletin, ESPN, onthepitch) and open-source GitHub projects that replicate their methodology in Python/Node.js. Every credible predictor shares a core pipeline: **team ratings → match probability model → Monte Carlo tournament simulation → probability aggregation**. The differentiation lies in output richness, update cadence, transparency, and what additional analysis layers sit on top.

For this project (Python CLI, Elo-only, knockout stage, JSON persistence), the table stakes are modest, but there are clear differentiators that create competitive advantage for a *terminal-based* tool.

## Table Stakes

Features users expect. Missing these means the product feels incomplete vs. any existing predictor.

| # | Feature | Why Expected | Complexity | Notes |
|---|---------|--------------|------------|-------|
| 1 | **Championship probability (%) per team** | Every predictor (538, ESPN, open-source repos) outputs this as the headline number | Low | Direct output of Monte Carlo aggregation |
| 2 | **Round-by-round advancement probabilities** | Make R16 → QF → SF → Final → Win. Users expect stage-by-stage breakdown | Low | Simulated directly from bracket traversal counts |
| 3 | **Live match result ingestion** | Must detect and process real results without manual intervention. The project's core value prop | Medium | API polling + JSON persistence. Football-Data.org free tier |
| 4 | **Elo rating updates after each match** | The fundamental rating engine. Without it, predictions don't reflect reality | Low | Standard Elo formula with configurable K-factor |
| 5 | **Monte Carlo simulation engine** | Every major predictor uses MC. 50,000+ sims expected for stable probabilities | Medium | Pure Python `random`, vectorization considerations |
| 6 | **Team rating display** | Show current Elo rating alongside probability. Users want to see *why* a team is favored | Low | Simple table output |
| 7 | **Match-level win probability** | Head-to-head: "Team A has X% chance vs Team B". Elo → expected score is standard | Low | Derived from Elo difference |
| 8 | **Predictions update automatically** | Not a static snapshot. Must re-simulate when new results arrive. The "live" in the project name | Medium | Polling loop architecture |
| 9 | **Error-resilient operation** | API failures must not crash the loop. Graceful degradation with cached fallback | Medium | Retry logic + stale data fallback |
| 10 | **Console-formatted output** | Must be readable in terminal. Tables, percentages, clear formatting | Low | ANSI colors optional but valued |

**Confidence:** HIGH — consistent across FiveThirtyEight, ESPN/SPI, Silver Bulletin PELE, and every open-source GitHub predictor examined.

## Differentiators

Features that set this product apart from existing web-based predictors and other CLI tools.

| # | Feature | Value Proposition | Complexity | Notes |
|---|---------|-------------------|------------|-------|
| 1 | **Probability delta tracking** | "Brazil: 22.1% (▼ 3.2% since last match)" — shows how odds shift in real time. No web dashboard does this in a live-updating CLI context | Medium | Store previous sim results, diff on re-sim |
| 2 | **Timeline/probability history** | Track how a team's odds evolved across the tournament. Plot as ASCII sparklines or JSON export for external charting | Medium | Append-only log of sim snapshots with timestamps |
| 3 | **Elo change annotations in match log** | When a match is detected, log: `Brazil 2-1 Serbia | Elo: +15.2 (2074 → 2089.2) | Δ prob: ▲ 1.8%`. Makes changes transparent | Low | Already have delta values; format them |
| 4 | **Most likely full bracket** | After each update, output the single most probable path through the knockout tree (most common simulated bracket) | Medium | Requires modal bracket tracking across MC runs |
| 5 | **Most likely scoreline per match** | "Brazil vs Serbia: most likely 2-0 (14.2%)" via Poisson from Elo expected goals | Medium | Requires Poisson goals model (beyond pure Elo W/D/L) |
| 6 | **"Dark horse" / surprise team detection** | Flag teams whose probability has risen X% above their initial rating. Creates narrative hooks | Low | Compare current vs initial probability |
| 7 | **Configurable everything without code changes** | K-factor, sim count, poll interval, display teams (top N), home advantage, draw probability — all via `constants.py` or simple config | Low | Already planned in STACK.md |
| 8 | **Exportable snapshot (JSON)** | `predictor-export.json` containing all probabilities, Elo ratings, match results. Feeds downstream analysis, charting, or sharing | Low | Already JSON-based; add dump command |
| 9 | **Backtest accuracy on command** | `python main.py --backtest`: simulate 2022 World Cup from its starting ratings, compare predicted vs actual outcomes. Reports Brier score, log-loss | High | Requires separate historical mode with known ground truth |
| 10 | **"What if" scenario mode** | `python main.py --set-result Brazil 2-1 Serbia`: force a result, re-simulate, see how odds change. Power user feature for "what happens if X wins?" | Medium | Allow overriding bracket.json before sim |
| 11 | **Bookmaker odds comparison (optional)** | Side-by-side: model probability vs market implied probability. Flags model vs market divergence | High | Requires third-party odds API (not free; deferred) |
| 12 | **Compact "dashboard" view** | Real-time terminal refresh: top 10 teams, last match result, time until next poll. Like `top` for tournament predictions | Medium | Requires terminal refresh lib (`colorama`) |

**Confidence:** HIGH (drawn from community expectations on open-source predictor repos and gaps in the existing CLI tool ecosystem)

## Anti-Features

Features to explicitly NOT build (for MVP; revisit decisions on technical merit, not popularity).

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **User accounts / authentication** | Single-user CLI tool. Auth adds complexity, state management, security surface with zero value | Run as a local script. No auth needed |
| **Web dashboard (Flask/Streamlit)** | Doubles scope. Web UI requires frontend code, deployment, state sync. Project explicitly console-only | Output JSON export for external charting if needed |
| **Machine learning models (XGBoost, neural nets)** | Opaque, requires training data, harder to debug. Elo is transparent and sufficient for MVP. 538's PELE recently doubled down on Elo-based approach | Pure Elo + optional Poisson extension. Document ML as post-MVP experiment |
| **Player-level modeling (Golden Boot, injury impact)** | Requires squad data, Transfermarkt API, player ratings. Massive data pipeline for a marginal gain | Team-level only. Player info is out of scope per PROJECT.md |
| **Fantasy football integration (FPL)** | Separate product domain with its own API, scoring rules, optimizer. Already exists as `pl-winner` | Not relevant to tournament prediction |
| **Betting advice / "value bet" alerts** | Legal gray area. Implies actionable wagering advice. Different user intent | Model vs market comparison as data, not advice |
| **Multi-tournament / historical archive** | Loading historical data across years adds data pipeline complexity. Not needed for live single-tournament use | Only current tournament. Historical as optional backtest mode |
| **Push notifications / desktop alerts** | Requires OS-specific integration (toast notifications). Out of scope for a terminal script | Log to console. User can grep/pipe the output |
| **Mobile app** | Entirely separate platform, build, deploy. Not the project's goal | CLI is the product. Cross-platform Python covers desktop |
| **Real-time WebSocket / live ticker** | Overengineering for a polling-based tool that updates every 60s | Polling loop is sufficient. Simplicity wins |
| **Group stage simulation** | Deferred per PROJECT.md. Adds significant bracket complexity (12 groups → R32 for 2026 format) | Knockout-only for MVP. Group stage is a natural post-MVP extension |
| **Multi-league / multiple tournaments simultaneously** | The project is about the World Cup. Adding e.g. Copa América, Euros dilutes focus | Single tournament mode. Parameterize for future tournaments |

**Confidence:** HIGH — decisions documented in PROJECT.md and consistent with research on scope management in open-source sports prediction projects.

## Feature Dependencies

```
Elo Rating System
  └── Match probability (Elo → expected score)
       └── Monte Carlo simulation (uses match probs to sample outcomes)
            ├── Championship probability (aggregate of simulation finals)
            ├── Round-by-round advancement (aggregate of simulation stages)
            ├── Most likely bracket (modal path across simulations)
            └── Probability delta (diff previous aggregate vs current)

API Polling
  └── Match detection (new result identified)
       └── Elo rating update
            └── Re-run Monte Carlo simulation
                 └── Probability delta computation
                      └── Console output (delta display)

JSON Persistence
  ├── teams.json (Elo ratings + metadata)
  ├── bracket.json (bracket structure + match winners)
  ├── played.json (completed match records)
  └── simulate on startup from persisted state
```

**Critical dependency chain:** Working API poll → correct Elo update → meaningful MC simulation → useful output. If any link in this chain breaks, the entire pipeline produces garbage.

## Complexity Estimates for MVP

| Feature | Lines of Code (est.) | Dependencies | Risk |
|---------|---------------------|--------------|------|
| Elo rating system | 30-50 | None (pure math) | Low — textbook formula |
| API polling + match detection | 100-150 | `requests` library | Medium — rate limits, error handling |
| JSON persistence layer | 80-120 | `json` module | Low — basic file I/O |
| Monte Carlo simulator | 150-250 | None (pure `random`) | Medium — correctness of bracket traversal |
| Console output (probabilities) | 50-80 | None | Low — string formatting |
| Probability delta tracking | 30-50 | Previous state | Low — diff current vs last snapshot |
| Elo change logging | 20-30 | Elo module | Low — format existing values |
| **MVP Total** | **~460-730** | **`requests` only** | **Medium — MC correctness is the hard part** |

### Post-MVP (not in Phase 1)

| Feature | Est. Effort | Complexity | Why Deferred |
|---------|------------|------------|-------------|
| Poisson scoreline model | 80-120 lines | Medium | Adds Dixon-Coles complexity; Elo W/D/L is sufficient |
| Most likely bracket | 60-100 lines | Medium | Requires tracking mode across MC sims |
| Backtest historical mode | 150-250 lines | High | Needs separate data ingestion + evaluation pipeline |
| JSON export command | 30-50 lines | Low | Trivial; defer until someone asks for it |
| "What if" scenario mode | 80-150 lines | Medium | Requires modifying bracket state mid-run |
| Group stage | 200-400 lines | High | Significant bracket logic; deferred per PROJECT.md |
| Bookmaker odds comparison | 150-250 lines | High | Requires paid API access |

## Feature Distribution by Phase (Roadmap Suggestion)

| Phase | Features | Category |
|-------|----------|----------|
| **Phase 1: Core Pipeline** | Elo system, MC simulator, API polling, JSON persistence, basic console output | Table stakes |
| **Phase 2: Live Loop** | Continuous polling loop, auto-re-simulation, error handling, rate-limit compliance | Table stakes |
| **Phase 3: Rich Output** | Probability deltas, Elo change logging, top N display, timestamped logs | Differentiators #1, #3, #4 |
| **Phase 4: Analytics** | Most likely bracket, dark horse detection, compact dashboard view | Differentiators #4, #6, #12 |
| **Phase 5: Power Features** | JSON export, config system, what-if mode | Differentiators #2, #7, #8, #10 |
| **Post-MVP** | Poisson model, backtest, group stage, bookmaker comparison | Differentiators #5, #9, #11 |

## Sources

- **FiveThirtyEight SPI/Silver Bulletin PELE** — natesilver.net/p/pele and substack articles (HIGH confidence)
- **ESPN Soccer Power Index** — espn.com/world-cup/story (HIGH confidence, official documentation)
- **onthepitch World Cup model** — onthepitch.now/docs/methodology (HIGH confidence, detailed model docs)
- **GitHub open-source predictors:** mundial-monte, pl-winner, wc2026 Bayesian model, GoallineIQ (HIGH confidence — direct source code review)
- **Medium post-mortems:** "When Your Model Is Right and the Answer Is Wrong" (MEDIUM confidence — experience report, verified against multiple sources)
- **MVP scoping decisions:** PROJECT.md, STACK.md (HIGH confidence — project-level authority)
