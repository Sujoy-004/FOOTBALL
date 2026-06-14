# World Cup Dynamic Prediction MVP – Project Document

Note: All numeric values (poll interval, simulation count, K‑factor, Elo ratings, etc.) are example defaults. In code, define them in constants.py or environment variables.

## 1. MVP Goal

Build a **self‑updating tournament simulation** that:
- Ingests live match results from a free API.
- Updates team strength (Elo ratings) immediately after each real match.
- Re‑runs a Monte Carlo simulation of the remaining tournament using the updated ratings.
- Prints new championship probabilities to the console (or a simple text file).

No web dashboard, no complex ML models – just a working Python pipeline.

---

## 2. Core Components

| Component              | Purpose                                                                 |
|------------------------|-------------------------------------------------------------------------|
| **Data store**         | Holds initial Elo ratings and the tournament bracket (Round of 16 → Final). |
| **Live score fetcher** | Polls a public football API every N seconds (e.g., 60) for finished matches.      |
| **Elo updater**        | Updates both teams’ ratings after a real result using standard Elo formula. |
| **Simulation engine**  | Runs 10,000–100,000 tournament simulations using current Elo ratings.   |
| **State manager**      | Locks real match results so they are never re‑simulated.                |

---

## 3. Data Flow (How It Works)

1. **Start** – Load initial Elo ratings and the bracket.
2. **Poll API** – Check for any newly finished matches (compare with last known state).
3. **If new result exists:**
   - Apply Elo update to the two teams.
   - Mark that match as “played” in the state manager.
4. **Re‑run simulation** – For each remaining match path, use updated Elo ratings. Already played matches are fixed.
5. **Output** – Show top 3 teams’ chances to win the whole tournament.
6. **Sleep** – Wait 60 seconds, then repeat from step 2.

---

## 4. Technology Stack (MVP only)

| Layer        | Choice                          | Reason                                  |
|--------------|----------------------------------|-----------------------------------------|
| Language     | Python 3.10+                    | Fast prototyping, rich libraries.       |
| API client   | `requests`                       | Simple HTTP calls.                      |
| Data storage | Python dictionary + JSON file    | No database needed for MVP.             |
| Simulation   | Pure Python (random module)      | Good enough for 100k runs.              |
| Logging      | Print to console                 | Minimal, visible feedback.              |

No web framework, no database, no frontend – keep it a single script.

---

## 5. Step‑by‑Step Build Plan

### v1.1+ Enhancements (Beyond MVP)

- ✅ **48-team format with group stage** — Shipped in v1.1 (Phase 7–10)
- 📋 Replace simple Elo with a **Logistic Regression / XGBoost** model using features like xG, possession, injuries
- 📋 Add a **web dashboard** (Flask + Chart.js) to show live probabilities
- 📋 Store historical probabilities to see how predictions evolve
- 📋 Add a **betting odds comparator** – compare your probabilities with bookmaker odds

### Step 0 – Setup
- Create folder `worldcup_mvp/`
- Create virtual environment
- Install `requests` only

### Step 1 – Hardcode initial data (`initial_data.py`)
- Elo ratings for all 32 teams (source: eloratings.net, take values just before tournament starts).
- Bracket list: list of tuples `(team1, team2)` for Round of 16, then manually define the knockout tree (e.g., winner of match A plays winner of match B).

### Step 2 – Live score fetcher (`live_scores.py`)
- Choose a free API with no key: **ESPN public API** (reverse‑engineered) or **Football-Data.org** (free tier with key).
- Write a function `get_finished_matches()` that returns list of dicts: `{team_a, team_b, winner, home_score, away_score}`.

### Step 3 – Elo calculator (`elo.py`)
- Function `update_elo(rating_a, rating_b, result_a, K=60 (example default))`
- `result_a = 1` (win), `0.5` (draw), `0` (loss)
- Return `(new_rating_a, new_rating_b)`

### Step 4 – Single‑match simulator (`simulate_match.py`)
- Input: two team names + their Elo ratings
- Compute expected score: `1 / (1 + 10^((rating_b - rating_a)/400))`
- Generate random number → decide winner (or draw if desired, but for knockout we force a winner after 120 min → treat as win/loss)

### Step 5 – Full tournament simulator (`tournament_sim.py`)
- Input: current Elo dict + list of already‑played results
- Walk through the bracket:
  - If match is already played → use real winner.
  - Else → call `simulate_match()`.
- Return champion name.

### Step 6 – Main loop (`main.py`)
- Load initial data.
- Keep a set `played_matches` (e.g., `("Argentina","Nigeria")`).
- Loop:
  - Fetch live results.
  - For each new result, update Elo ratings and add to `played_matches`.
  - Run tournament simulation 50,000 times (configurable) → count champion frequencies.
  - Print top 3 teams with percentages.
  - Sleep N seconds (e.g., 60).

---

## 6. MVP Acceptance Criteria

- [x] The script starts and prints initial championship probabilities.
- [x] When a real match finishes (test by manually setting a mock result), the script detects it within 120 seconds.
- [x] After detection, Elo ratings of the two teams change (print old vs new).
- [x] The next simulation output shows different probabilities (the winner's chances increase).
- [x] Already finished matches are never simulated again (even if script restarts – use a small JSON file to persist `played_matches`).
- [x] The script runs without crashing for at least 24 hours (or during a match day).

### v1.1 Additional Criteria (2026-06-14)

- [x] 48 teams, 12 groups (A–L) with validated structure.
- [x] Group stage simulation: round-robin scoring, 7-step tiebreaker, Poisson match model.
- [x] Annex C third-place routing: 495-entry lookup table with validated invariants.
- [x] Full 104-match tournament pipeline: groups → R32 → R16 → QF → SF → TPP → FINAL.
- [x] BSD API live-data ingestion for group matches with `played_groups.json` persistence.
- [x] Console display: box-drawing group standings + third-place bubble indicator.
- [x] 212 passing tests, 0 failures (full regression suite).

---

## 8. Timeline (for a B.Tech student with 4–6 hours/day)

| Day | Task                                                                 |
|-----|----------------------------------------------------------------------|
| 1   | Environment setup, hardcode initial Elo and bracket.                 |
| 2   | Write Elo updater and test with mock matches.                        |
| 3   | Write the tournament simulator (single run).                         |
| 4   | Add Monte Carlo loop (many runs).                                    |
| 5   | Integrate live API – fetch and parse real results.                   |
| 6   | Build main loop + state persistence (JSON).                          |
| 7   | Test with a live match day, debug, add simple logging.               |

After Day 7 you have a working MVP. Then you can proudly put it on GitHub and start adding ML features.

---

## 9. Why This Expands Your Vision & Intelligence

- You learn **event‑driven architecture** (react to new data).
- You practice **persistence** (saving state between runs).
- You understand **Elo rating systems** – used in chess, sports, and ranking algorithms.
- You experience **real‑world API integration** (rate limits, data cleaning).
- You see how **probabilistic simulations** are used in finance, logistics, and AI.

Most importantly, you **build something that feels alive** – updating predictions as the tournament unfolds. That’s the kind of project that makes interviews memorable.

---