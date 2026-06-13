# World Cup Dynamic Prediction

## What This Is

A self-updating tournament predictor for football fans and B.Tech students. It polls a live match API, updates team Elo ratings after every real result, re-runs thousands of Monte Carlo simulations, and prints updated championship probabilities to the console — all in real time. No manual bracket filling, no static predictions.

## Core Value

A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] **DATA-01**: Fetch live match results from a free public API
- [ ] **DATA-02**: Persist played matches and updated Elo ratings across script restarts
- [ ] **ELO-01**: Update Elo ratings for both teams after each real match result
- [ ] **SIM-01**: Simulate the remaining knockout tournament 50,000+ times using Monte Carlo
- [ ] **UI-01**: Output championship probabilities as formatted percentages in the console
- [ ] **UI-02**: Display top 5 teams with probability deltas after each update
- [ ] **UI-03**: Log timestamps, match detections, and Elo changes to console
- [ ] **LOOP-01**: Run continuously, polling every N seconds without manual intervention
- [ ] **ERR-01**: Handle API failures gracefully with retry logic and cached data fallback

### Out of Scope

- User accounts or login — not needed for a single-user CLI tool
- Web dashboard or graphical UI — console-only for MVP
- Machine learning models (XGBoost, neural nets) — beyond scope; Elo is sufficient
- Group stage simulation — knockout-only for MVP; can be added later
- Multi-tournament support — only the current World Cup
- Historical data analysis beyond the current tournament

## Context

- Python 3.10+ CLI application, no graphical interface
- Uses Football-Data.org free API (rate limit: 10 req/min, poll every 60s)
- All state persisted as JSON files (teams.json, bracket.json, played.json)
- Knockout stage only (Round of 16 → Quarterfinals → Semifinals → Final)
- Standard Elo rating system with configurable K-factor
- No draws in knockout matches (penalties produce a winner)

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
| Python 3.10+ | Fast prototyping, rich ecosystem, cross-platform | — Pending |
| Football-Data.org API | Free tier, reliable match data, well-documented | — Pending |
| Elo rating system | Simple, transparent, well-understood formula | — Pending |
| Monte Carlo simulation | Straightforward probability estimation | — Pending |
| JSON file persistence | No database setup, human-readable, easy to debug | — Pending |
| Console-only output | Simpler than web UI, immediate feedback | — Pending |

---

*Last updated: 2026-06-13 after initialization*
