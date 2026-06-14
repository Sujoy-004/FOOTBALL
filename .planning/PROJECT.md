# World Cup Dynamic Prediction

## What This Is

A self-updating tournament predictor for football fans and B.Tech students. It polls a live match API, updates team Elo ratings after every real result, re-runs thousands of Monte Carlo simulations, and prints updated championship probabilities to the console — all in real time. No manual bracket filling, no static predictions.

## Core Value

A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.

## Current State (v1.0)

**Shipped:** 2026-06-14

The v1.0 MVP is complete. The tool can:

1. **Load state** from JSON files (32 teams, 23 bracket matches)
2. **Compute Elo ratings** using standard Elo formula with configurable K-factor
3. **Simulate** the remaining knockout tournament 50,000+ times in ~1.3s
4. **Fetch live results** from Football-Data.org API with automatic retry and cached fallback
5. **Poll continuously** every 60 seconds, auto-detecting new matches and re-simulating
6. **Display** color-coded probability tables with delta tracking (▲/▼)
7. **Run one-off** with `--once`, control color with `--no-color`, reproduce with `--seed`

**Test coverage:** 98 passing tests across 10 test modules
**Codebase:** ~2,200 LOC Python

## Requirements

### Validated (v1.0)

- ✓ **DATA-01**: Fetch live match results from Football-Data.org API — v1.0
- ✓ **DATA-02**: Persist played matches and Elo ratings across restarts via JSON — v1.0
- ✓ **DATA-03**: Graceful API failure handling with retry and cached fallback — v1.0
- ✓ **ELO-01**: Update Elo ratings after each match using standard formula — v1.0
- ✓ **SIM-01**: Monte Carlo simulation of remaining bracket (50K+ iterations) — v1.0
- ✓ **UI-01**: Championship probabilities as formatted table with timestamps — v1.0
- ✓ **UI-02**: Probability deltas (▲ increase, ▼ decrease) — v1.0
- ✓ **UI-03**: Colored console output with plain-text fallback — v1.0
- ✓ **LOOP-01**: Continuous polling every N seconds with hourly auto-resim — v1.0
- ✓ **VAL-01**: Bracket structure validation on startup — v1.0
- ✓ **SHUT-01**: Save state and print final probabilities on Ctrl+C — v1.0
- ✓ **CLI-01**: CLI flags: --once, --no-color, --help, --seed — v1.0

### Active (v2.0)

- [ ] **V2-01**: Most-likely full bracket visualization
- [ ] **V2-02**: Dark horse detection (gap between Elo and probability)
- [ ] **V2-03**: Historical probability log (track odds over time)
- [ ] **V2-04**: Simple web dashboard (Flask + Chart.js)
- [ ] **V2-05**: What-if mode (simulate hypothetical match results)
- [ ] **V2-06**: Backtesting against historical tournaments
- [ ] **V2-07**: NumPy-accelerated simulation for larger iterations
- [ ] **V2-08**: Group stage simulation

### Out of Scope

| Feature | Reason |
|---------|--------|
| User accounts or login | Not needed for single-user CLI tool |
| Web dashboard | Console-only for MVP; v2.0 candidate |
| ML models (XGBoost, neural nets) | Beyond scope; Elo is sufficient |
| Multi-tournament support | Only current World Cup |
| Historical data analysis | Beyond current tournament scope |
| Mobile notifications | Post-MVP enhancement |
| Betting odds comparison | Post-MVP enhancement |

## Context

- Python 3.10+ CLI application, no graphical interface
- Uses Football-Data.org free API (rate limit: 10 req/min, poll every 60s)
- All state persisted as JSON files (teams.json, bracket.json, played.json)
- Knockout stage only (Round of 16 → Quarterfinals → Semifinals → Final)
- Standard Elo rating system with configurable K-factor (default 60)
- No draws in knockout matches (penalties produce a winner)
- Codebase: ~2,200 LOC Python across 8 modules + 10 test files

## Constraints

- **Language**: Python 3.10+ — must run on Windows, macOS, Linux
- **Dependencies**: Minimal (requests library for HTTP, random for simulation)
- **Storage**: JSON files only — no database
- **API**: Football-Data.org free tier — 10 requests/min limit
- **UI**: Console-only — no web framework, no frontend
- **Scope**: Knockout stage only — group stage deferred
- **Persistence**: State must survive script restarts via JSON files

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python 3.10+ | Fast prototyping, rich ecosystem, cross-platform | ✓ Good |
| Football-Data.org API | Free tier, reliable match data, well-documented | ✓ Good |
| Elo rating system | Simple, transparent, well-understood formula | ✓ Good |
| Monte Carlo simulation | Straightforward probability estimation | ✓ Good |
| JSON file persistence | No database setup, human-readable, easy to debug | ✓ Good |
| Console-only output | Simpler than web UI, immediate feedback | ✓ Good |
| Pure stdlib ANSI | No colorama dependency, works cross-platform | ✓ Good |
| `--once` skips state save | Single-cycle mode doesn't change state, no save needed | ✓ Good |
| `--seed` on every sim | Reproducibility without global random state pollution | ✓ Good |

---

*Last updated: 2026-06-14 after v1.0 milestone*
