# Requirements: World Cup Dynamic Prediction

**Defined:** 2026-06-13
**Core Value:** A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed.

## v1 Requirements

### Data & State

- [ ] **DATA-01**: System fetches live match results from Football-Data.org API every configured interval (e.g., 60 seconds)
- [ ] **DATA-02**: System persists played matches and updated Elo ratings across script restarts via JSON files (teams.json, bracket.json, played.json)
- [ ] **DATA-03**: System handles API failures gracefully with retry logic (3 retries, exponential backoff) and falls back to cached data without crashing

### Elo & Simulation

- [ ] **ELO-01**: System updates Elo ratings for both teams after each real match result using standard Elo formula with configurable K-factor (default 60)
- [ ] **SIM-01**: System runs Monte Carlo simulation of remaining knockout tournament (50,000+ iterations) to compute championship probabilities for every team

### Output

- [ ] **UI-01**: System outputs championship probabilities for top 5 teams as formatted percentages in the console with timestamps
- [ ] **UI-02**: System displays probability deltas (▲ increase, ▼ decrease) showing how each team's odds changed since the last simulation
- [ ] **UI-03**: System uses colored console output (ANSI) for readability with plain-text fallback for unsupported terminals

### Main Loop

- [ ] **LOOP-01**: System runs continuously, polling every N seconds without manual intervention, and re-simulates after each new match or at least once per hour

### Bracket & Validation

- [ ] **VAL-01**: System validates bracket structure on startup (all match_ids unique, source_matches exist, no circular dependencies)

### Shutdown

- [ ] **SHUT-01**: System saves state and prints final probabilities on Ctrl+C (graceful shutdown)

### CLI

- [ ] **CLI-01**: System supports command-line flags: --once (single run), --no-color (disable ANSI), --help (usage), --seed (reproducibility)

## v2 Requirements

### Analytics & Polish

- **V2-01**: Most-likely full bracket visualization
- **V2-02**: Dark horse detection (team with biggest gap between Elo and probability)
- **V2-03**: Historical probability log (track odds over time)
- **V2-04**: Simple web dashboard (Flask + Chart.js)

### Optimization

- **V2-05**: What-if mode (simulate hypothetical match results)
- **V2-06**: Backtesting against historical tournaments
- **V2-07**: NumPy-accelerated simulation for larger iteration counts
- **V2-08**: Group stage simulation

## Out of Scope

| Feature | Reason |
|---------|--------|
| User accounts or login | Not needed for single-user CLI tool |
| Web dashboard | Console-only for MVP; post-MVP enhancement |
| ML models (XGBoost, neural nets) | Beyond scope; Elo is sufficient for MVP |
| Multi-tournament support | Only current World Cup |
| Historical data analysis | Beyond current tournament scope |
| Mobile notifications | Post-MVP enhancement |
| Betting odds comparison | Post-MVP enhancement |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 3 | Pending |
| DATA-02 | Phase 1 | Pending |
| DATA-03 | Phase 3 | Pending |
| ELO-01 | Phase 1 | Pending |
| SIM-01 | Phase 2 | Pending |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 5 | Pending |
| UI-03 | Phase 5 | Pending |
| LOOP-01 | Phase 4 | Pending |
| VAL-01 | Phase 1 | Pending |
| SHUT-01 | Phase 4 | Pending |
| CLI-01 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 12 total
- Mapped to phases: 12
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-13*
*Last updated: 2026-06-13 after initial definition*
