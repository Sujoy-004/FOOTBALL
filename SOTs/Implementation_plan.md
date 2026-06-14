# World Cup Dynamic Prediction – Implementation Plan (Implementation_plan.md)

Note: All numeric values (poll interval, simulation count, K‑factor, Elo ratings, etc.) are example defaults. In code, define them in constants.py or environment variables.

## 1. Document Purpose

This document provides a **detailed, actionable plan** to implement the MVP defined in `MVP.md`, following the technical specifications in `TRD.md`, data schemas in `Backend_Schema.md`, application flow in `Appflow.md`, and UI/UX guidelines in `UI_UX_Design.md`.

The plan is designed for a **single B.Tech student** working 4–6 hours per day. Total estimated effort: **40–50 hours** (roughly 7–9 days).

---

## 2. Development Phases Overview

| Phase | Name                          | Duration | Key Deliverable                          | Status |
|-------|-------------------------------|----------|------------------------------------------|--------|
| 0     | Environment Setup             | 0.5 day  | Working Python environment + API key     | ✅ Complete |
| 1     | Data & State Layer            | 1 day    | JSON files + `state.py` module           | ✅ Complete |
| 2     | Elo & Simulation Engine       | 1.5 days | `elo.py` + `simulator.py` (unit tested)  | ✅ Complete |
| 3     | Live API Integration          | 1 day    | `fetcher.py` + mapping logic             | ✅ Complete |
| 4     | Main Loop & Output            | 1 day    | `main.py` + `output.py` (colored console)| ✅ Complete |
| 5     | Error Handling & Persistence  | 0.5 day  | Retries, graceful shutdown, state saves  | ✅ Complete |
| 6     | Integration Testing & Debug   | 1 day    | End‑to‑end working script                | ✅ Complete |
| 7     | Documentation & Polish        | 0.5 day  | README, comments, final demo             | ✅ Complete |

**Buffer:** 1 day for unexpected issues → total ~8 days.

### v1.1 Phases (48-Team Format) — All Complete 2026-06-14

| Phase | Name | Key Deliverable | Status |
|-------|------|-----------------|--------|
| 7     | 48-Team Dataset & Group Definitions | teams.json (48 teams), groups.json, annex_c.json, team_aliases.json | ✅ Complete |
| 8     | Group Stage Simulation Engine | Poisson scoring, 7-step tiebreaker, Annex C routing, performance benchmark | ✅ Complete |
| 9     | Knockout Bracket & Full Pipeline | 104-match pipeline, R32 slot descriptors, run_full_simulation() | ✅ Complete |
| 10    | Integration, Tests & BSD Verification | Group match ingestion, standings display, 212 tests, SOT batch update | ✅ Complete |

---

## 3. Detailed Task Breakdown

### Phase 0: Environment Setup (0.5 day)

**Tasks:**
- [ ] Create project folder: `worldcup_predictor/`
- [ ] Set up virtual environment: `python -m venv venv`
- [ ] Activate environment and install dependencies: `pip install requests`
- [ ] Create `requirements.txt` (initially just `requests`, later add `pytest` for testing)
- [ ] Sign up for free API key at [Football-Data.org](https://www.football-data.org/)
- [ ] Set environment variable `FOOTBALL_API_KEY` (test in terminal)
- [ ] Create directory structure:
  ```
  worldcup_predictor/
  ├── data/
  │   ├── teams.json
  │   ├── bracket.json
  │   ├── played.json
  │   └── api_id_mapping.json
  ├── src/
  │   ├── __init__.py
  │   ├── state.py
  │   ├── elo.py
  │   ├── simulator.py
  │   ├── fetcher.py
  │   ├── output.py
  │   └── constants.py
  ├── tests/
  ├── main.py
  └── requirements.txt
  ```

**Acceptance:** Running `python --version` shows 3.10+; API key accessible in Python via `os.environ`.

---

### Phase 1: Data & State Layer (1 day)

**Tasks:**
- [ ] Create initial `data/teams.json` with 16 knockout teams (Elo ratings from eloratings.net)
- [ ] Create `data/bracket.json` with R16 → QF → SF → Final structure (as per Backend_Schema)
- [ ] Create empty `data/played.json` `{}`
- [ ] Create `data/api_id_mapping.json` (start empty, fill later)
- [ ] Implement `src/state.py`:
  - `load_teams()`, `load_bracket()`, `load_played_matches()`
  - `save_teams()`, `save_played_matches()` (atomic write using temp file)
  - `load_api_id_mapping()`, `save_api_id_mapping()` (for dynamic updates)
- [ ] Write unit tests (`tests/test_state.py`): verify load/save roundtrips

**Acceptance:** Python can load all JSON files into dicts and write back without data loss.

---

### Phase 2: Elo & Simulation Engine (1.5 days)

**Tasks:**
- [ ] Create `src/constants.py` with example defaults (e.g., `K_FACTOR = 60`, `SIMULATION_COUNT = 50000`)
- [ ] Implement `src/elo.py`:
  - `expected_score(rating_a, rating_b)`
  - `update_ratings(team_a, team_b, winner, elos, K=60)` returning new elos dict
- [ ] Write unit tests for Elo (known examples: 2100 vs 1850, winner = higher → +12/-12) — (example values)
- [ ] Implement `src/simulator.py`:
  - `simulate_match(team_a, team_b, elo_a, elo_b)` → returns winner
  - `run_single_tournament(elos, bracket, played_set)` → champion
  - `run_monte_carlo(elos, bracket, played_set, n)` → probabilities dict
- [ ] Test simulation with hardcoded data (e.g., 100 runs, verify probabilities sum to 1.0)
- [ ] Optimise: target e.g., 50,000 runs < 5 seconds as a goal (use profiling if needed)

**Acceptance:** `simulate_match` produces plausible win percentages (e.g., 2000 vs 1800 → ~76% chance for higher). Monte Carlo outputs sum to 1.0.

---

### Phase 3: Live API Integration (1 day)

**Tasks:**
- [ ] Implement `src/fetcher.py`:
  - `fetch_finished_matches()`: GET request to Football-Data.org with API key
  - Parse JSON, extract `id`, `homeTeam.name`, `awayTeam.name`, `winner`, `score`
  - Normalise team names (e.g., "United States" → "USA", "Korea Republic" → "South Korea")
  - Return list of raw match dicts (using external IDs)
- [ ] Implement `match_processor` inside `fetcher.py` or as separate function:
  - Use `api_id_mapping.json` to convert external ID → internal `match_id`
  - If new external ID appears, prompt user to map? For MVP, manually pre‑fill mapping for known matches.
  - Compare with `played_set` to filter only new matches.
- [ ] Write a mock API responder for testing (simulate different responses)
- [ ] Test with live API: fetch recent finished matches (maybe from previous tournament or friendlies)

**Acceptance:** `fetch_new_results(last_known_ids)` returns only matches not yet in `played_set`, with internal match IDs.

---

### Phase 4: Main Loop & Output (1 day)

**Tasks:**
- [ ] Implement `src/output.py`:
  - `print_header()`: banner, initial instructions
  - `print_probabilities(probs, deltas=None)`: formatted table, color coded (use ANSI codes, with `--no-color` fallback)
  - `print_match_update(match, elo_changes)`: highlight new match and Elo changes
  - `print_error(msg)`: red text
  - `print_heartbeat()`: optional, for "no new matches"
- [ ] Implement `main.py`:
  - Load all state
  - Run initial simulation and print probabilities
  - Enter infinite loop:
    - Call `fetch_new_results()`
    - For each new match:
      - Call `update_ratings()`
      - Update `teams` dict and save
      - Add to `played_set` and save
    - If any new matches OR time since last simulation > 1 hour:
      - Re‑run Monte Carlo
      - Compute deltas from previous probabilities
      - Print updated probabilities
    - Sleep `POLL_INTERVAL_SECONDS` (60)
- [ ] Implement graceful shutdown: catch `KeyboardInterrupt`, save state, print final probabilities

**Acceptance:** Running `python main.py` shows header, initial probs, then periodic heartbeats. Pressing Ctrl+C saves state and exits cleanly.

---

### Phase 5: Error Handling & Persistence (0.5 day)

**Tasks:**
- [ ] Add retry logic in `fetcher.py` (max 3 retries, exponential backoff: 1s, 2s, 4s)
- [ ] Handle API timeouts: log error, continue loop with old data
- [ ] Handle malformed JSON: catch `json.JSONDecodeError`, treat as API failure
- [ ] Handle team name mismatches: log warning, skip match (or use a fallback mapping file)
- [ ] Ensure `save_teams` and `save_played_matches` are called after every state change
- [ ] Test crash recovery: kill script mid‑run, restart, verify `played.json` contains last recorded match

**Acceptance:** Script survives simulated API outages, network disconnections, and invalid responses without crashing.

---

### Phase 6: Integration Testing & Debug (1 day)

**Tasks:**
- [ ] Create a test script `tests/integration_test.py`:
  - Mock API responses for a sequence of matches (e.g., R16 matches one by one)
  - Run main loop in a controlled way (or call functions directly)
  - Verify Elo updates and probability changes match expectations
- [ ] Run a full 24‑hour simulation using historical match data (if available)
- [ ] Test with real API during a live match day (or friendly matches)
- [ ] Debug any issues:
  - Probability sum not exactly 1.0 (floating point) → acceptable within 1e-6
  - Slow simulation → check for unnecessary deep copies, consider caching
  - ANSI colors not working on Windows → add fallback or use `colorama`
- [ ] Validate that `played.json` grows correctly and bracket winners are locked

**Acceptance:** All tests pass; script runs for at least 2 hours without errors, probabilities update correctly after each mock match.

---

### Phase 7: Documentation & Polish (0.5 day)

**Tasks:**
- [ ] Write `README.md` in project root:
  - Project description
  - Setup instructions (clone, venv, API key, run)
  - Example output screenshots
  - Link to documentation files (MVP.md, PRD.md, etc.)
- [ ] Add inline comments to all modules (especially complex formulas)
- [ ] Create a short demo video or GIF of the console output (optional)
- [ ] Push to GitHub repository with clean commit history
- [ ] Write a `demo.md` showing sample output for a realistic match sequence

**Acceptance:** Another person can clone the repo, set up API key, and run the script in <10 minutes without asking for help.

---

## 4. Dependencies Between Tasks

```
Phase 0 (Env)
   │
   ▼
Phase 1 (State) ──────────────────────┐
   │                                  │
   ▼                                  ▼
Phase 2 (Elo & Sim)              Phase 3 (API)
   │                                  │
   └──────────┬───────────────────────┘
              ▼
         Phase 4 (Main + Output)
              │
              ▼
         Phase 5 (Error Handling)
              │
              ▼
         Phase 6 (Integration Test)
              │
              ▼
         Phase 7 (Docs & Polish)
```

**Critical path:** Phase 1 → Phase 2 → Phase 4 → Phase 6. Phase 3 can be developed in parallel after Phase 1, but must be ready before Phase 4 integration.

---

## 5. Daily Schedule (Example for a 7‑day sprint)

| Day | Phase(s)                      | Focus                                                       | Output                                     |
|-----|-------------------------------|-------------------------------------------------------------|--------------------------------------------|
| 1   | Phase 0 + Phase 1             | Setup, JSON files, state.py module                         | Data files load/save successfully          |
| 2   | Phase 2 (first half)          | elo.py + unit tests                                        | Elo updates correct                        |
| 3   | Phase 2 (second half)         | simulator.py + Monte Carlo                                 | Simulation runs, probabilities sum to 1.0  |
| 4   | Phase 3                       | fetcher.py, API integration, mapping                       | Can fetch live matches                     |
| 5   | Phase 4                       | main.py loop, output.py, colored console                   | Script runs end‑to‑end (manual test)       |
| 6   | Phase 5 + Phase 6             | Error handling, integration tests, debugging               | Stable script passes tests                 |
| 7   | Phase 7                       | README, comments, GitHub push                              | Public repository ready                    |

If extra day needed: use buffer.

---

## 6. Testing Checklist (Per Phase)

| Phase | Test                                                         | How to verify                                  |
|-------|--------------------------------------------------------------|------------------------------------------------|
| 1     | JSON load/save preserves data                               | Load, modify, save, reload – values match     |
| 2     | Elo update matches known examples (e.g., from chess)        | Compute by hand, compare code output          |
| 2     | Monte Carlo probabilities sum to 1.0 (within 0.001)          | Run `sum(probs.values())`                     |
| 3     | API returns at least one finished match (or mock)            | Print response; check parsing                 |
| 3     | New match filtering works (no duplicates after restart)     | Run script, stop, run again – same match not reprocessed |
| 4     | Colored output appears (or fallback plain text)              | Visual inspection                             |
| 4     | Ctrl+C shutdown saves state                                 | Compare `played.json` before and after kill   |
| 5     | API failure does not crash script                           | Disconnect internet, script continues         |
| 6     | End‑to‑end: simulate R16 matches one by one, probabilities evolve | Mock API returns sequential results, check deltas |

---

## 7. Milestones & Deliverables

| Milestone                 | Date (relative) | Deliverable                                                  |
|---------------------------|-----------------|--------------------------------------------------------------|
| Environment ready         | Day 1 end       | `requirements.txt`, API key configured                      |
| State layer complete      | Day 1 end       | `state.py` tested, JSON files created                       |
| Elo & simulation complete | Day 3 end       | `elo.py`, `simulator.py` passing unit tests                 |
| API integration complete  | Day 4 end       | `fetcher.py` can pull real data                             |
| Full MVP working          | Day 5 end       | `main.py` runs, updates probabilities on new matches        |
| Stable & tested           | Day 6 end       | All integration tests pass, error handling proven           |
| Public release            | Day 7 end       | GitHub repo with README, documentation files, demo          |

---

## 8. Risk Mitigation in Implementation

| Risk                          | Mitigation Action in Plan                                      |
|-------------------------------|----------------------------------------------------------------|
| API rate limits               | Poll every 60 sec (well within 10/min). Implemented in Phase 4.|
| Team name mismatches          | Create a name mapping dict in `fetcher.py` (Phase 3).          |
| Simulation too slow (>5 sec)  | Use `functools.lru_cache` for expected scores? Or reduce runs to 20k initially. |
| Windows ANSI colors not working| Use `colorama` library or provide `--no-color` flag (Phase 4). |
| API key exposed on GitHub     | Use environment variable; add `.env` to `.gitignore`. Document in README. |
| Bracket structure is static   | Hardcode for MVP; add a validation script to ensure no logical loops. |

---

## 9. Definition of Done (for the entire MVP + v1.1)

- [x] Running `python main.py` displays initial probabilities.
- [x] When a real match finishes, within 2 minutes the script detects it, updates Elo, and reprints probabilities with deltas.
- [x] The script can run for 24+ hours (or simulated match day) without crashing.
- [x] After restarting, previously played matches are not re‑processed.
- [x] All JSON files remain valid and human‑readable.
- [x] A `README.md` exists with setup and run instructions.
- [x] All code is committed to a GitHub repository with the documentation files.
- [x] **v1.1**: 48-team format with group stage, Annex C routing, BSD API integration, group standings display, third-place bubble, 212 passing tests.

---

## 10. Next Steps After v1.1 (Future Enhancements)

Completed in v1.1:
- ✅ Group stage simulation (12 groups, Poisson scoring, 7-step tiebreaker)
- ✅ Annex C third-place routing (495-entry lookup table)
- ✅ BSD API integration (group match ingestion, played_groups.json)
- ✅ Group standings console display + third-place bubble indicator
- ✅ 212 passing pytest tests across 14 modules

Planned for v2.0+:
- 📋 Replace Elo with XGBoost.
- 📋 Build a web dashboard (Flask + Chart.js).
- 📋 Add historical probability logging.
- 📋 Containerise with Docker for easy deployment.

But for now – **focus on the plan above**. Build the MVP first.

---

**Approval (for your own sign‑off):**

- [ ] Phases and tasks are clear
- [ ] Timeline is realistic for a B.Tech student
- [ ] Dependencies understood
- [ ] Testing and risk mitigation included
- [ ] Ready to start coding
```