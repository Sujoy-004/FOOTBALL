# Roadmap: World Cup Dynamic Prediction

## Overview

A live, self-updating tournament predictor in your terminal. Starting from bare-metal data structures and Elo math, we build up through Monte Carlo simulation, live API integration, continuous polling, polished console output, and finally CLI controls — each phase delivering a coherent, verifiable capability. By the end, the user runs a single command and gets a continuously updating championship probability feed for the World Cup knockout stage.

## Phases

- [x] **Phase 1: State & Elo Foundation** - JSON persistence, Elo rating engine, and bracket validation
- [ ] **Phase 2: Monte Carlo Simulation** - 50K+ iteration tournament simulation and probability aggregation
- [ ] **Phase 3: Live API Integration** - Football-Data.org API fetcher with retry logic and cached fallback
- [ ] **Phase 4: Main Loop & Shutdown** - Continuous polling loop with Ctrl+C graceful shutdown
- [ ] **Phase 5: Console Output & Formatting** - Formatted probability tables, delta tracking, and ANSI colors
- [ ] **Phase 6: CLI Interface & Polish** - Command-line flags and final integration polish

## Phase Details

### Phase 1: State & Elo Foundation
**Goal**: Tournament bracket and Elo ratings can be loaded, computed, validated, and persisted across restarts via JSON files.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: DATA-02, ELO-01, VAL-01
**Success Criteria** (what must be TRUE):
  1. User can define starting teams with Elo ratings in teams.json and the system loads them correctly at startup
  2. System validates bracket.json structure on startup (unique match_ids, valid source_matches, no circular dependencies) and reports errors clearly
  3. After a match result is recorded, both teams' Elo ratings update correctly using standard Elo formula with configurable K-factor (default 60)
  4. All state (played matches, Elo ratings) persists across script restarts by loading from JSON files (teams.json, bracket.json, played.json)
  5. JSON writes use atomic write pattern (write to .tmp, then os.replace) to prevent file corruption on crash
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Data Loading & Bracket Validation (scaffold, state.py load+validate, seed data, main.py entry, validation tests)
- [x] 01-02-PLAN.md — Elo Engine & State Persistence (elo.py, atomic save functions, integration test)

**UI hint**: yes

### Phase 2: Monte Carlo Simulation
**Goal**: System can simulate the remaining knockout tournament 50,000+ times and compute accurate championship probabilities from current Elo ratings.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: SIM-01
**Success Criteria** (what must be TRUE):
  1. System runs 50,000+ Monte Carlo simulations of the remaining bracket in under 5 seconds (iterative Python)
  2. Each team receives a championship probability percentage, and all probabilities sum to ~100% (within floating-point tolerance)
  3. Simulation uses current Elo ratings to determine match win probabilities via the Elo expected score formula
  4. Simulation output is reproducible when using a fixed random seed
  5. Simulation handles bracket edge cases correctly (e.g., partially completed bracket skips already-played matches)
**Plans**: 2 plans

Plans:
- [ ] 02-01-PLAN.md — Core simulation engine (simulation.py + tests + main.py wiring)
- [ ] 02-02-PLAN.md — Performance benchmark (benchmark script + verification)

### Phase 3: Live API Integration
**Goal**: System fetches live match results from Football-Data.org API with robust error handling — retries on failure, cached data fallback, and never crashes due to network issues.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: DATA-01, DATA-03
**Success Criteria** (what must be TRUE):
  1. System fetches match results from Football-Data.org API and filters to finished knockout matches
  2. API failures automatically trigger retry logic (3 retries with exponential backoff) before giving up
  3. On persistent API failure, system falls back to last known cached data and continues operating without crashing
  4. System matches API response teams to internal bracket teams via ID mapping, with clear error if mapping is missing
  5. Console log shows informative messages for API fetch success, failure, retries, and match detection events
**Plans**: TBD

### Phase 4: Main Loop & Shutdown
**Goal**: System runs autonomously — polls continuously, detects new matches, triggers re-simulation, and shuts down gracefully on Ctrl+C.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: LOOP-01, SHUT-01
**Success Criteria** (what must be TRUE):
  1. System runs continuously, polling for new match results every configurable N seconds (default 60) without manual intervention
  2. When a new match is detected, system automatically updates Elo ratings and re-runs the Monte Carlo simulation
  3. Ctrl+C triggers graceful shutdown: saves current state to JSON files and prints final championship probabilities before exiting
  4. System re-simulates at least once per hour even without new matches (to refresh probability display)
  5. Polling respects API rate limits (10 req/min) with a client-side rate limiter
**Plans**: TBD

### Phase 5: Console Output & Formatting
**Goal**: System displays beautiful, colored, delta-tracking championship probabilities in the terminal — readable at a glance with rich formatting and plain-text fallback.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: UI-01, UI-02, UI-03
**Success Criteria** (what must be TRUE):
  1. System outputs the top 5 teams by championship probability as formatted percentages with timestamps in a clean table layout
  2. Probability deltas (▲ increase in green, ▼ decrease in red) show how each team's odds changed since the last simulation
  3. Output uses ANSI colors for clear visual hierarchy on supported terminals (team names, percentages, deltas)
  4. On terminals without ANSI support (or same-pipe output), output falls back to clean plain text automatically
  5. Console output includes timestamped match detection events, Elo change summaries, and simulation progress
**Plans**: TBD
**UI hint**: yes

### Phase 6: CLI Interface & Polish
**Goal**: User controls the tool via command-line flags with full usage documentation — one-off runs, color control, reproducibility, and help on demand.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: CLI-01
**Success Criteria** (what must be TRUE):
  1. `--help` flag shows complete usage information listing all available flags and their descriptions
  2. `--once` flag runs a single poll-simulate-output cycle then exits cleanly
  3. `--no-color` flag disables ANSI color output explicitly (overrides auto-detection)
  4. `--seed <N>` flag enables reproducible Monte Carlo simulation runs
  5. All flags work together correctly (e.g., `python wc-predict.py --once --no-color --seed 42`)
**Plans**: TBD

## Progress

**Execution Order:** Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. State & Elo Foundation | 2/2 | Complete | 2026-06-13 |
| 2. Monte Carlo Simulation | 2/2 | Planned | - |
| 3. Live API Integration | 0/0 | Not started | - |
| 4. Main Loop & Shutdown | 0/0 | Not started | - |
| 5. Console Output & Formatting | 0/0 | Not started | - |
| 6. CLI Interface & Polish | 0/0 | Not started | - |
