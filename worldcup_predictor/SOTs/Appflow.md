# World Cup Dynamic Prediction – Application Flow Document (Appflow.md)

Note: All numeric values (poll interval, simulation count, K‑factor, Elo ratings, etc.) are example defaults. In code, define them in constants.py or environment variables.

## 1. Document Purpose

This document describes the **end‑to‑end application flow** of the MVP: how data moves between modules, the sequence of operations in the main loop, state transitions, and error handling paths. It serves as a visual and textual guide for developers implementing the code.

---

## 2. High‑Level Flow Diagram (Textual)

```
START
  │
  ▼
Load initial state (Elo, bracket, groups, annex C, played matches from JSON)
  │
  ▼
Run initial Monte Carlo simulation (groups → Annex C → bracket) → print first probabilities + group standings
  │
  ▼
┌─────────────────────────────────────────┐
│          MAIN LOOP (infinite)           │
│  ┌─────────────────────────────────┐    │
│  │ 1. Poll BSD API for finished    │    │
│  │    matches (single endpoint)    │    │
│  └─────────────┬───────────────────┘    │
│                ▼                         │
│  ┌─────────────────────────────────┐    │
│  │ 2. Split by group_name field    │    │
│  │    - non-null → group match     │    │
│  │    - null → knockout match      │    │
│  └──────┬──────────────┬───────────┘    │
│         ▼              ▼                │
│  ┌────────────┐  ┌──────────────┐       │
│  │ process_   │  │ process_     │       │
│  │ group_     │  │ matches()    │       │
│  │ matches()  │  │ (knockout)   │       │
│  └─────┬──────┘  └──────┬───────┘       │
│        ▼                ▼               │
│  ┌────────────────┐  ┌──────────────┐   │
│  │ Save to        │  │ Update Elo   │   │
│  │ played_groups  │  │ + save to    │   │
│  │ .json          │  │ played.json  │   │
│  └───────┬────────┘  └──────┬───────┘   │
│          ▼                  │           │
│  ┌──────────────────────┐   │           │
│  │ Print/refresh group  │   │           │
│  │ standings (12 groups)│   │           │
│  │ + third-place bubble │   │           │
│  └───────┬──────────────┘   │           │
│          └──────┬───────────┘           │
│                 ▼                        │
│  ┌─────────────────────────────────┐    │
│  │ 3. Re‑run Monte Carlo           │    │
│  │    simulation (50,000 iters)    │    │
│  │    using full pipeline:         │    │
│  │    groups→Annex C→R32→bracket   │    │
│  └─────────────┬───────────────────┘    │
│                ▼                         │
│  ┌─────────────────────────────────┐    │
│  │ 4. Print updated championship   │    │
│  │    probabilities + deltas       │    │
│  └─────────────┬───────────────────┘    │
│                ▼                         │
│  ┌─────────────────────────────────┐    │
│  │ 5. Sleep N seconds (e.g., 60)    │    │
│  └─────────────────────────────────┘    │
│                │                         │
│                └──────────┐              │
│                           ▼              │
│                   (loop back to step 1)  │
└─────────────────────────────────────────┘
```

---

## 3. Detailed Sequence Diagram (Module Interactions)

```
User          main.py         fetcher       state_mgr       groups_display   simulator
  │               │              │              │               │               │
  │──python main.py─────────────▶│              │               │               │
  │               │──load_state()─────────────▶│               │               │
  │               │  (teams, bracket, groups,  │               │               │
  │               │   annex_c, played,         │               │               │
  │               │   played_groups)           │               │               │
  │               │◀───────────────────────────│               │               │
  │               │──initial_simulate()──────────────────────────────────────▶│
  │               │◀─────────────────────────────────────────────────────────│
  │               │──print_group_standings()────────────────▶ (console)      │
  │               │──print_probs()▶ (console)                                 │
  │               │              │              │               │             │
  │               │◀─────LOOP─────────────────────────────────────────────────│
  │               │──poll_api()──▶│              │               │             │
  │               │◀──results────│              │               │             │
  │               │              │              │               │             │
  │               │──split by group_name────────▶                              │
  │               │  non-null → process_group_matches()                        │
  │               │  null → process_matches()                                  │
  │               │              │              │               │             │
  │               │──for each new group match:──▶                              │
  │               │  save to played_groups.json  │                            │
  │               │  --print_group_standings()──▶ (console)                   │
  │               │              │              │               │             │
  │               │──for each new knockout match:─▶                            │
  │               │──update_elo(match)───────────────────────────────────────▶│
  │               │  save to played.json         │                            │
  │               │              │              │               │             │
  │               │──run_full_simulation()───────────────────────────────────▶│
  │               │  (groups→Annex C→bracket)                                 │
  │               │◀─────────────────────────────────────────────────────────│
  │               │──print_probs()▶ (console)                                 │
  │               │              │              │               │             │
  │               │──sleep(60)───│              │               │             │
  │               │              │              │               │             │
  │               │◀─────LOOP repeats────────────────────────────────────────│
  │               │              │              │               │             │
  │◀──Ctrl+C──────│              │              │               │             │
  │               │──save_state()───────────────▶│               │             │
  │               │──print_final_probs()▶ (console)                           │
  │               │──exit()       │              │               │             │
```

---

## 4. State Transition Diagram (For the Bracket)

Each match in the bracket transitions through states as the real tournament progresses:

```
       ┌─────────────┐
       │  PENDING    │ (initial state; not yet played)
       └──────┬──────┘
              │ Real match result detected
              ▼
       ┌─────────────┐
       │  COMPLETED  │ (winner stored, Elo updated)
       └──────┬──────┘
              │ (no further transitions)
              ▼
       ┌─────────────┐
       │  FROZEN     │ (locked in state, never simulated again)
       └─────────────┘
```

**State persistence:** The `played.json` file stores all completed matches, so even if the script restarts, those matches are immediately loaded as `FROZEN`.

**For the simulation:**  
- If match state = PENDING → simulate using current Elo ratings.  
- If match state = COMPLETED/FROZEN → use real winner directly.

---

## 5. Data Flow Through the System

| Stage                    | Input                            | Output                                    | Storage               |
|--------------------------|----------------------------------|-------------------------------------------|-----------------------|
| **Initialisation**       | Hardcoded Elo, bracket, groups, annex_c, empty played.json/played_groups.json | Initialised `teams` dict, `bracket` tree, groups data | `teams.json`, `bracket.json`, `groups.json`, `annex_c.json` |
| **API polling**          | HTTP GET `sports.bzzoiro.com/api/events/` | List of finished matches (JSON) with `group_name` field | None (volatile)       |
| **Match routing**        | `group_name` field               | Group match → `process_group_matches()`; null → `process_matches()` | None (runtime decision) |
| **Group match processing** | `group_name` non-null match     | New entry in `played_groups.json`, group standings refresh | `played_groups.json` |
| **Knockout match processing** | `group_name` null match       | Updated Elo ratings for two teams          | `teams.json` (rewritten), `played.json` |
| **State saving**         | Updated Elo + new match result   | Updated `teams.json` + `played.json`      | Disk (JSON files)     |
| **Simulation**           | Current Elo + bracket + groups + played + played_groups | Probabilities per team via full pipeline | Memory (printed)      |
| **Group standings**      | `compute_standings()` + `played_groups` | 12-group box-drawing table + third-place bubble | Console               |
| **Output**               | Probabilities                    | Formatted console output (header + standings + probs) | Console               |

**No database** – all persistence via JSON files.

---

## 6. Error Handling Flow

```
API request
     │
     ▼
┌─────────────┐
│ Success?    │
└──────┬──────┘
   Yes │          No
       ▼           ▼
┌─────────────┐ ┌─────────────────────────────┐
│ Parse data  │ │ Log error, increment retry  │
└─────────────┘ │ counter, sleep 60s          │
                │ If retries < 3: keep old    │
                │ data, continue loop         │
                │ If retries >=3: use mock    │
                │ data (if available) or      │
                │ skip poll for this cycle    │
                └─────────────────────────────┘
```

**Other error scenarios:**
- **Malformed JSON from API:** Same as API failure.
- **Team name mismatch (API vs internal):** Use a mapping dictionary; if still missing, log and skip match.
- **File write failure (disk full):** Print critical error but continue (state lost on restart).
- **KeyboardInterrupt (Ctrl+C):** Graceful shutdown (save state, print final).

---

## 7. Module Execution Order (Call Graph)

```
main.py
   ├─> state.py::load_teams()
   ├─> state.py::load_bracket()
   ├─> state.py::load_played_matches()
   ├─> simulator.py::run_monte_carlo(elos, bracket, played, n=50000)
   │      └─> for _ in range(n):
   │            simulator.py::run_single_tournament()
   │                 └─> recursively for each match:
   │                       if match in played: use real winner
   │                       else: simulator.py::simulate_match()
   │                                 └─> probability based on Elo diff
   ├─> (loop)
   │    ├─> fetcher.py::fetch_new_results(last_known_ids)
   │    ├─> for each new result:
   │    │     elo.py::update_ratings(team_a, team_b, winner, current_elos)
   │    │     state.py::save_teams(updated_elos)
   │    │     state.py::save_played_matches(updated_played)
   │    ├─> simulator.py::run_monte_carlo(...)  # re-run
   │    └─> output.print_probabilities()
   └─> (on exit)
        ├─> state.py::save_teams()
        ├─> state.py::save_played_matches()
        └─> output.print_final()
```

---

## 8. Concurrency & Async Notes

The MVP is **single‑threaded** and synchronous:
- API calls block the loop (but only for ~1–2 seconds).
- Simulations are CPU‑bound but run in the main thread.
- No asyncio, no threading – simplicity for MVP.

**Future improvement:** Move Monte Carlo simulations to a separate thread so that API polling continues concurrently, but this adds complexity. For MVP, simple blocking is acceptable because 5 seconds every minute is fine.

---

## 9. Lifecycle of a Single Match (From API to Probability Update)

1. **API returns** `{id: 123456, home: "Argentina", away: "Nigeria", winner: "home", score: "2-1"}`.
2. **Fetcher** maps API match ID to internal `match_id` (e.g., `R16_1`) using a static mapping file.
3. **Main loop** checks if `match_id` is already in `played_matches` set. If not, it’s new.
4. **Elo updater** computes new ratings (example values):
   - Old: Arg 2100, Nig 1850.
   - Expected Arg = 0.81, result Arg = 1 → new Arg = 2100 + 60*(1-0.81) = 2112.
   - Expected Nig = 0.19, result Nig = 0 → new Nig = 1850 + 60*(0-0.19) = 1838.
5. **State manager** writes new Elo values to `teams.json` and adds `R16_1` to `played.json` with winner = "Argentina".
6. **Simulation engine** now sees that `R16_1` is fixed. It uses real winner in all future runs.
7. **Re‑simulation** runs N times (e.g., 50,000); Argentina’s championship probability typically increases.
8. **Output** shows the delta (e.g., +0.6%).

This entire sequence happens within 2–5 seconds after the API returns the match data.

---

## 10. Configuration & Environment Flow

No configuration files for MVP. All parameters are constants in the code. However, the flow for a future configurable version would be:

```
Start
  │
  ▼
Check for config.json
  │
  ├── exists → load parameters (K‑factor, poll interval, simulation count)
  │
  └── not exist → use hardcoded defaults, optionally create a default config file
  │
  ▼
Proceed with main flow
```

**Constants in MVP (defined in `constants.py` with example defaults):**
- `K_FACTOR = 60` # example – can be changed
- `POLL_INTERVAL_SECONDS = 60` # example
- `SIMULATION_COUNT = 50000` # example
- `API_URL = "https://api.football-data.org/v4/matches?competition=WC&status=FINISHED"`
- `API_KEY = "your_key_here"` (read from environment variable `FOOTBALL_API_KEY` for security)

---

## 11. Shutdown & Cleanup Flow

```
User presses Ctrl+C
         │
         ▼
Signal handler in main.py catches KeyboardInterrupt
         │
         ▼
Print "\n[INFO] Shutting down gracefully..."
         │
         ▼
Call state.save_teams() and state.save_played_matches() (ensure latest state is written)
         │
         ▼
Run one final simulation using current state (optional)
         │
         ▼
Print final probabilities and exit with code 0
```

No temporary files to clean; JSON files remain for next run.

---

## 12. Summary of Key Flows (Bullet Points)

- **Initialisation flow:** Load → simulate → print → loop.
- **Match detection flow:** Poll → compare IDs → process new → update Elo → save → re‑simulate → print → sleep.
- **Error flow:** API fail → log → retry → fallback to cached data.
- **Shutdown flow:** Catch interrupt → save state → final simulation → exit.

All flows are linear, deterministic, and easy to debug – ideal for an MVP.

---

**Approval (for your own sign‑off):**

- [ ] High‑level flow diagram matches intended behaviour
- [ ] Sequence diagram covers all module interactions
- [ ] State transitions are clearly defined
- [ ] Error handling paths documented
- [ ] No missing flows (e.g., initialisation, shutdown)
```