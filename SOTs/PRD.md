# World Cup Dynamic Prediction – Product Requirements Document (PRD)

Note: All numeric values (poll interval, simulation count, K‑factor, Elo ratings, etc.) are example defaults. In code, define them in constants.py or environment variables.

## 1. Document Purpose

This document defines the **product vision, user goals, feature scope, success metrics, and constraints** for the MVP described in `MVP.md`. It answers “what are we building and why” – separate from the technical details in `TRD.md`.

---

## 2. Product Vision

**For football fans and B.Tech students,**  
a self‑updating tournament predictor that  
**automatically learns from live match results**  
and **recalculates championship probabilities in real time** –  
without manual bracket filling or static predictions.

Unlike generic sports websites (ESPN, FiveThirtyEight) that update predictions only after match days, our product **re‑simulates the tournament within seconds** of a match ending, using fresh Elo ratings. It’s lightweight, transparent, and designed for a single command‑line run.

---

## 3. User Personas (Who is this for?)

| Persona                  | Needs                                                                 |
|--------------------------|-----------------------------------------------------------------------|
| **Casual football fan**  | Wants to see how a single upset changes the whole tournament’s odds.  |
| **B.Tech student**       | Wants a fun, real‑world data project to learn simulations & APIs.     |
| **Data science beginner**| Wants an intuitive example of Monte Carlo + Elo systems.              |
| **Sports bettor (casual)**| Wants to compare model probabilities with bookmaker odds.            |

For the MVP, the primary persona is the **B.Tech student** building the project. The secondary persona is the **casual fan** running the script.

---

## 4. Feature Scope (MoSCoW)

### Must Have (Critical for MVP)
- [ ] Fetch live match results from a free public API.
- [ ] Update Elo ratings of teams based on real match outcomes.
- [ ] Simulate the remaining knockout tournament 10,000+ times.
- [ ] Output championship probabilities as percentages in the console.
- [ ] Persist state (played matches, updated Elo) across script restarts.
- [ ] Run continuously (poll every 60 seconds) without manual intervention.

### Should Have (High priority but not blocking MVP)
- [ ] Display top 3‑5 teams with probabilities after each update.
- [ ] Log timestamps and Elo changes to console.
- [ ] Handle API failures gracefully (retry, use old data).

### Could Have (Nice to have – post‑MVP)
- [ ] Simple web dashboard (one HTML page with chart).
- [ ] Compare predictions against actual tournament outcomes.
- [ ] Add betting odds overlay.
- [ ] Send mobile notifications for probability shifts.

### Won’t Have (Out of scope for MVP)
- [ ] User accounts or login.
- [ ] Historical data analysis beyond current tournament.
- [ ] Machine learning models beyond Elo (XGBoost, neural nets – these will be separate enhancements).
- [ ] Multi‑tournament support (only current World Cup).

---

## 5. User Stories

As a **B.Tech student building the project**, I want to:
1. Run a single Python script that starts predicting immediately.
2. See probabilities change automatically after I manually test a fake match result.
3. Understand exactly how Elo is calculated (simple formula, no black box).
4. Stop and restart the script without losing progress.

As a **casual fan running the script**, I want to:
1. See the current championship odds printed every few minutes.
2. Notice a clear difference in probabilities after a major upset.
3. Not need any technical setup beyond “install Python and run one command”.

As a **data science beginner learning from the code**, I want to:
1. Read well‑commented modules with clear separation of concerns.
2. Easily swap the simulation logic (e.g., try a different K‑factor).
3. Extend the project later (e.g., add group stage simulation).

---

## 6. Functional Requirements

| ID   | Requirement                                                                 | Acceptance Criteria                                                                 |
|------|-----------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| FR1  | System fetches match data from Football-Data.org API every configured interval (e.g., 60 seconds).      | API call timestamp logged; on success, parses JSON without crashing.                |
| FR2  | System detects newly finished matches by comparing match IDs.               | A match finished 5 minutes ago appears in the next poll; repeated polls ignore it.  |
| FR3  | When a new match result is found, system updates Elo ratings for both teams.| Console prints “Updating Elo: TeamA X → Y, TeamB Z → W”.                             |
| FR4  | System marks the match as played and never simulates it again.              | Even after restart, that match’s winner is fixed.                                   |
| FR5  | After any Elo update (or at least hourly), system re‑runs Monte Carlo simulation.| Simulation completes simulation completes within a target time (e.g., 5 seconds for 50,000 runs).                              |
| FR6  | System outputs championship probabilities for at least top 5 teams.         | Output format: “Argentina: 32.4%, France: 28.1%, Brazil: 15.3% ...”                 |
| FR7  | System continues running after an API failure (no crash).                   | Logs error, waits 60 seconds, retries.                                              |

---

## 7. Non‑Functional Requirements

| ID   | Requirement                | Target                                      |
|------|----------------------------|---------------------------------------------|
| NFR1 | Latency                    | New match detected within 120 seconds (2 polls max). |
| NFR2 | Simulation performance     | target: 50,000 runs < 5 seconds on reference hardware|
| NFR3 | Availability               | Script runs for 24+ hours without manual restart. |
| NFR4 | Error tolerance            | API fails 5 times in a row → still no crash, keeps old data. |
| NFR5 | Portability                | Runs on Windows, macOS, Linux with Python 3.10+. |
| NFR6 | User skill level           | One command (`python main.py`) starts everything. No config files to edit (all hardcoded initially). |

---

## 8. User Interface Requirements (MVP)

The MVP has **no graphical interface**. The interface is the **console**.

All console output below is illustrative — actual numbers will vary based on real match data and configuration.

**Welcome message:**
```
================================================
 World Cup Dynamic Prediction MVP
 Polling API every 60 seconds...
================================================
```

**Normal output (no new match):**
```
[2026-06-15 22:00:01] Polling... no new matches.
[2026-06-15 22:00:01] Current probabilities (from last run):
  1. Argentina  32.4%
  2. France     28.1%
  3. Brazil     15.3%
```

**After a new match:**
```
[2026-06-15 22:05:01] New match: Argentina 2 - 1 Nigeria
[2026-06-15 22:05:01] Updating Elo: Argentina 2100 → 2112(example values), Nigeria 1850 → 1838(example values)
[2026-06-15 22:05:02] Re‑simulating tournament...
[2026-06-15 22:05:06] Updated probabilities:
  1. Argentina  34.1% (+1.7)
  2. France     27.3% (-0.8)
  3. Brazil     14.9% (-0.4)
```

**Error message (API timeout):**
```
[2026-06-15 22:10:01] API error: timeout. Retry in 60s (using cached data).
```

All output is simple, readable, and timestamped.

---

## 9. Success Metrics (How do we know we succeeded?)

| Metric                       | Target for MVP                                          |
|------------------------------|---------------------------------------------------------|
| Correct detection of matches | 100% of real matches (tested against API documentation) |
| Probability change after upset | Detectable shift (e.g., underdog winning increases its odds by >5%) |
| Runtime stability            | No crash over 3 consecutive match days (simulated or real) |
| Ease of setup                | A first‑time user can go from clone to first output in <10 minutes |
| Learning value (self‑eval)   | The builder can explain Elo, Monte Carlo, and API polling to a peer |

---

## 10. Constraints & Assumptions

**Constraints:**
- API rate limit: 10 requests/minute. Our 1 request/minute is safe.
- Free API only provides match results after ~30–60 seconds delay. We accept this.
- No live ball‑by‑ball data; only final results.
- Knockout stage only (group stage is out of scope for MVP; can be added later).

**Assumptions:**
- User has a stable internet connection.
- Python 3.10+ is installed.
- The World Cup bracket does not change after tournament starts (fixed tree).
- No draws in knockout matches (penalties produce a winner; API provides that winner).

---

## 11. Risks & Product‑Level Mitigations

| Risk                                | Mitigation                                                              |
|-------------------------------------|-------------------------------------------------------------------------|
| User doesn’t understand console output | Add a short help text (`--help` flag) explaining probabilities.        |
| API changes endpoint or data format | Keep a mock data fallback; plan for quick adaptation (hardcoded sample).|
| Bracket mismatch (e.g., team names differ from API) | Maintain a mapping table (e.g., “USA” → “United States”).               |
| User wants group stage simulation   | Document that MVP covers knockout only; provide a roadmap for adding groups. |
| Simulation results seem random      | Allow user to set a random seed (via command line) for reproducibility. |

---

## 12. Glossary

| Term                 | Definition                                                                 |
|----------------------|----------------------------------------------------------------------------|
| **Elo rating**       | A method for calculating relative skill levels, originally for chess.      |
| **Monte Carlo simulation** | Running a model many times with random inputs to estimate probabilities. |
| **K‑factor**         | How much a single match affects Elo rating (higher = more volatile).       |
| **Knockout stage**   | Single‑elimination matches (Round of 16 → Quarterfinals → Semifinals → Final). |
| **MVP**              | Minimum Viable Product – the simplest version that works.                  |

---

## 13. Future Product Roadmap (Post‑MVP)

| Version | Feature                                                             |
|---------|---------------------------------------------------------------------|
| v1.1    | Add group stage simulation + group draw probabilities.              |
| v1.2    | Simple web dashboard (Flask + bar chart).                           |
| v1.3    | Replace Elo with XGBoost model using historical match features.     |
| v2.0    | Real‑time push notifications (webhooks) for probability swings.     |

But the MVP (v1.0) delivers the core promise: **a live, self‑updating tournament predictor in your terminal**.

---

**Approval (for your own sign‑off):**

- [ ] Product vision clear
- [ ] Must‑have features defined
- [ ] Success metrics are measurable
- [ ] Constraints understood
- [ ] Ready to proceed to technical design (see TRD.md)
```