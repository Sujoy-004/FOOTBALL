# World Cup Dynamic Prediction – Technical Requirements Document (TRD)

Note: All numeric values (poll interval, simulation count, K‑factor, Elo ratings, etc.) are example defaults. In code, define them in constants.py or environment variables.

## 1. Document Purpose

This document defines the **technical architecture, data models, algorithms, API contracts, and non‑functional requirements** for the MVP described in `MVP.md`. It serves as the engineering blueprint before coding begins.

---

## 2. System Overview

The system is a **console‑based Python application** that:
- Polls a public football API at regular intervals.
- Detects newly finished World Cup matches.
- Updates team Elo ratings based on actual results.
- Re‑runs a Monte Carlo simulation of the remaining tournament.
- Outputs updated championship probabilities.

No graphical interface, no database – only JSON for state persistence.

---

## 3. High‑Level Architecture

```
[External API] ──► [Fetcher Module] ──► [State Manager (JSON)]
                                              │
                                              ▼
                                    [Elo Updater Module]
                                              │
                                              ▼
                                    [Simulation Engine]
                                              │
                                              ▼
                                    [Console Output]
```

All modules are invoked by a main loop inside `main.py`.

---

## 4. Data Models

### 4.1 Team Object (stored in `teams.json`)
```json
{
  "name": "Argentina",
  "elo": 2100,
  "group": "C",
  "eliminated": false
}
```

### 4.2 Bracket Tree (stored in `bracket.json`)
Represents the knockout stage as a nested structure:
```json
{
  "round_of_16": [
    {"match_id": "R16_1", "team_a": "Argentina", "team_b": "Nigeria", "winner": null},
    {"match_id": "R16_2", "team_a": "France", "team_b": "Denmark", "winner": null}
  ],
  "quarterfinals": [
    {"match_id": "QF_1", "source_matches": ["R16_1", "R16_2"], "winner": null}
  ],
  "semifinals": [...],
  "final": {"match_id": "FINAL", "source_matches": ["SF_1", "SF_2"], "winner": null}
}
```

### 4.3 Played Matches Log (`played.json`)
```json
{
  "R16_1": {"winner": "Argentina", "home_score": 2, "away_score": 1},
  "R16_2": {"winner": "France", "home_score": 3, "away_score": 0}
}
```

### 4.4 Simulation Output (ephemeral, printed to console)
```json
{
  "timestamp": "2026-06-15T22:30:00Z",
  "probabilities": [
    {"team": "Argentina", "chance": 0.324},
    {"team": "France", "chance": 0.281},
    {"team": "Brazil", "chance": 0.153}
  ]
}
```

---

## 5. Module Specifications

### 5.1 Fetcher Module (`fetcher.py`)

**Responsibility:** Retrieve finished matches from the external API.

**Function:** `fetch_new_results(last_known_match_ids: set) -> list[MatchResult]`

**API Choice:** Football-Data.org (free tier, API key required)  
- Endpoint: `https://api.football-data.org/v4/matches?competition=WC&status=FINISHED`
- Rate limit: 10 requests per minute (free tier). Our polling interval will be 60 seconds → 1 request/min, well within limit.

**Pseudo‑logic:**
1. Send GET request with header `X-Auth-Token`.
2. Parse JSON response.
3. Filter matches where `status == "FINISHED"` and `match_id` not in `last_known_match_ids`.
4. Return list of `MatchResult` objects.

**MatchResult schema:**
```python
class MatchResult:
    match_id: str
    team_a: str
    team_b: str
    winner: str   # "team_a", "team_b", or None for draw (but knockout has no draw)
    home_score: int
    away_score: int
```

**Error handling:** Retry up to 3 times with exponential backoff (1s, 2s, 4s). On persistent failure, log error and continue with old data.

---

### 5.2 Elo Updater Module (`elo.py`)

**Responsibility:** Apply Elo rating changes after a confirmed match result.

**Formula (standard Elo with K‑factor = 60 (adjustable constant)):**
```
expected_a = 1 / (1 + 10**((elo_b - elo_a) / 400))
new_elo_a = elo_a + K * (result_a - expected_a)
new_elo_b = elo_b + K * ((1 - result_a) - (1 - expected_a))
```
Where `result_a = 1` if team A wins, `0` if team A loses (draws not possible in knockout).

**Function:** `update_ratings(team_a: str, team_b: str, winner: str, current_elos: dict) -> dict`  
Returns a new dictionary with updated Elo values for the two teams.

**Constraints:**  
- Elo changes are applied **immediately** after a real match finishes.
- No retroactive changes (even if later results would theoretically change earlier expected scores).

---

### 5.3 Simulation Engine (`simulator.py`)

**Responsibility:** Run a single tournament simulation and aggregate many simulations.

**Sub‑module 1:** `simulate_match(team_a, team_b, elo_a, elo_b) -> winner`  
- Compute win probability from Elo difference.
- Use `random.random()` to decide winner (no draws).

**Sub‑module 2:** `run_single_tournament(elos, bracket, played_matches) -> champion`  
- Walk through bracket tree.
- If match ID is in `played_matches`, use real winner.
- Else, call `simulate_match()` with current Elo values.

**Sub‑module 3:** `run_monte_carlo(elos, bracket, played_matches, n_simulations=50000 #default, can be changed) -> dict`  
- Repeat `run_single_tournament` n times.
- Count wins per team.
- Return dictionary `{team: win_count / n_simulations}`.

**Performance requirement:** e.g., 50,000 iterations < 5 seconds on a typical laptop (target, not a hard limit).

---

### 5.4 State Manager (`state.py`)

**Responsibility:** Persist and load Elo ratings, bracket, and played matches across script restarts.

**Functions:**
- `load_teams() -> dict` – reads `teams.json`
- `load_bracket() -> dict` – reads `bracket.json`
- `load_played_matches() -> dict` – reads `played.json`
- `save_played_matches(played_matches)` – writes to `played.json` after each update
- `save_teams(teams_data)` – writes updated Elo ratings

**File format:** JSON (human‑readable, easy to debug).

**Atomic writes:** Write to a temporary file then rename to avoid corruption.

---

### 5.5 Main Loop (`main.py`)

**Pseudo‑code:**
```python
initialize modules
load persisted state
last_known_match_ids = set(played_matches.keys())

while True:
    try:
        new_results = fetcher.fetch_new_results(last_known_match_ids)
        for result in new_results:
            update_elo_ratings(result)
            mark_match_as_played(result)
            last_known_match_ids.add(result.match_id)
            save_state()
        
        if new_results or time_to_refresh_probabilities:
            probabilities = run_monte_carlo(...)
            print_probabilities(probabilities)
        
        sleep(poll_interval) #e.g. 60 sec
    except Exception as e:
        log_error(e)
        sleep(poll_interval) #e.g. 60 sec
```

**Refresh condition:** Re‑run simulation after every new match OR at least once per hour even if no matches (to keep output fresh).

---

## 6. API Contract (Football-Data.org)

**Request:**
```
GET https://api.football-data.org/v4/matches?competition=WC&status=FINISHED
Headers: X-Auth-Token: <your_api_key>
```

**Response snippet (relevant fields):**
```json
{
  "matches": [
    {
      "id": 123456,
      "homeTeam": {"name": "Argentina"},
      "awayTeam": {"name": "Nigeria"},
      "score": {"fullTime": {"home": 2, "away": 1}},
      "status": "FINISHED"
    }
  ]
}
```

**Match ID mapping:** We convert API’s `id` to our internal `match_id` (e.g., `R16_1`) using a static mapping file `api_id_to_bracket.json`.

---

## 7. Non‑Functional Requirements

| Requirement        | Target                                      |
|--------------------|---------------------------------------------|
| Latency            | New match detected within 120 seconds       |
| Simulation speed   | 50,000 iterations < 5 seconds               |
| Availability       | Script runs continuously for 24+ hours      |
| Error resilience   | API failure → uses last known data, retries |
| Memory usage       | < 500 MB                                     |
| Logging            | Console logs with timestamps, no external files needed for MVP |

---

## 8. Testing Strategy

| Test Type          | Description                                                                 |
|--------------------|-----------------------------------------------------------------------------|
| Unit tests         | Elo update formula, match simulation randomness (seed control)              |
| Integration test   | Mock API returns a fake finished match → verify Elo change + re‑simulation |
| End‑to‑end         | Run script for 1 hour with real API (but historical/friendly matches)       |
| Persistence test   | Kill script, restart – played matches and Elo ratings persist               |

Use `pytest` for unit/integration tests.

---

## 9. Deployment & Execution

**Requirements:**
- Python 3.10+
- Internet connection for API calls
- API key from [Football-Data.org](https://www.football-data.org/) (free)

**Run command:**
```bash
python main.py
```

**Logging example:**
```
[2026-06-15 22:00:01] Polling API...
[2026-06-15 22:00:02] No new matches.
[2026-06-15 22:01:01] Polling API...
[2026-06-15 22:01:03] New match found: Argentina vs Nigeria (2-1). Winner: Argentina.
[2026-06-15 22:01:03] Updating Elo: Argentina 2100 → 2112, Nigeria 1850 → 1838. (example)
[2026-06-15 22:01:05] Running 50000 simulations...
[2026-06-15 22:01:08] Probabilities: Argentina 34.1%, France 27.3%, Brazil 15.2%.
```

---

## 10. Risks & Mitigations

| Risk                                      | Mitigation                                                               |
|-------------------------------------------|--------------------------------------------------------------------------|
| API rate limit exceeded                   | Poll every 60 seconds; free tier allows 10/min → safe.                   |
| API returns inconsistent team names       | Use a team name mapping table (e.g., "USA" vs "United States").          |
| Simulation too slow                       | Use efficient data structures (no deep copies of large dicts each run).  |
| Real match goes to penalties (draw after 120 min) | Treat as win/loss based on penalty shootout winner. API provides winner. |
| Script crashes at 3 AM                    | Wrap main loop in `try/except`, log error, and continue.                 |

---

## 11. Future Technical Additions (Post‑MVP)

- Replace simple random with **weighted random based on xG models**.
- Add **Redis** for real‑time state sharing if we ever add a web frontend.
- Use **Celery** to parallelise Monte Carlo runs.
- Switch to a **PostgreSQL** database to store historical probabilities.

For now, the MVP stays lean and meets the TRD above.

---

**Approval (for your own sign‑off):**

- [ ] Architecture reviewed
- [ ] Data models finalised
- [ ] API selected & tested with sample call
- [ ] Performance criteria are realistic
- [ ] Ready to start coding
```