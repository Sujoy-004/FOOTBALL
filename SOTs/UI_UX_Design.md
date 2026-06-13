# World Cup Dynamic Prediction – UI/UX Design Document

Note: All numeric values (poll interval, simulation count, K‑factor, Elo ratings, etc.) are example defaults. In code, define them in constants.py or environment variables.

## 1. Document Purpose

This document defines the **user interface and user experience** for the MVP described in `MVP.md`. Since the MVP is a **command‑line application**, “UI” refers to console output formatting, color schemes, information hierarchy, and user feedback patterns. It also sketches a **future web dashboard** as an extension.

---

## 2. Design Principles

| Principle            | Application in Console MVP                                      |
|----------------------|-----------------------------------------------------------------|
| **Clarity**          | Each output line has a timestamp and a clear purpose.          |
| **Minimalism**       | No unnecessary characters; show only what changed.             |
| **Feedback**         | Every action (API poll, match detected, Elo update, simulation) is logged. |
| **Scannability**     | Use color (if supported) and indentation to separate probabilities. |
| **Error resilience** | Errors are clearly marked but do not flood the screen.         |

---

## 3. Console Information Architecture

All console output blocks below are illustrative — actual numbers will vary based on real match data and configuration.

The console screen is **not interactive** – it’s a continuous scroll. Information appears in this order:

```
1. Header (once at start)
2. Periodic “no new matches” heartbeat
3. Match detection + Elo update block
4. New probabilities block
5. Error messages (when they occur)
```

### 3.1 Startup Screen
```
============================================================
   WORLD CUP DYNAMIC PREDICTOR – MVP
   Polling API every 60 seconds. Press Ctrl+C to stop.
   Initial Elo ratings loaded. Initial simulation complete.
============================================================
[2026-06-15 22:00:00] Initial probabilities:
  1. Argentina    34.2%
  2. France       27.9%
  3. Brazil       15.1%
  4. Spain        12.3%
  5. England      10.5%
```

### 3.2 Heartbeat (no new matches)
```
[2026-06-15 22:01:00] Polling... no new matches.
[2026-06-15 22:02:00] Polling... no new matches.
```

### 3.3 Match Detection & Elo Update (highlighted block)
```
[2026-06-15 22:03:00] NEW MATCH DETECTED!
   Argentina 2 - 1 Nigeria
   Winner: Argentina
[2026-06-15 22:03:00] Updating Elo:
   Argentina: 2100 → 2112 (+12)
   Nigeria:   1850 → 1838 (-12)
```

### 3.4 Updated Probabilities
```
[2026-06-15 22:03:02] Re‑simulating (50000 runs)...
[2026-06-15 22:03:07] UPDATED PROBABILITIES:
  1. Argentina    34.8%  ▲ +0.6
  2. France       27.5%  ▼ -0.4
  3. Brazil       14.9%  ▼ -0.2
  4. Spain        12.1%  ▼ -0.2
  5. England      10.7%  ▲ +0.2
```

### 3.5 Error Message (temporary, does not spam)
```
[2026-06-15 22:10:00] ⚠ API error: timeout. Retry in 60s. Using cached data.
```

---

## 4. Color & Styling Guidelines (ANSI escape codes)

For terminals that support color, the MVP **should** implement these (optional but recommended):

| Element                     | Color          | Example                              |
|-----------------------------|----------------|--------------------------------------|
| Timestamps                  | Dim gray       | `[2026-06-15 22:00:00]`              |
| Headers / separators        | Bold cyan      | `=================================`  |
| New match announcement      | Bold yellow    | `NEW MATCH DETECTED!`                |
| Team names in match result  | Bold white     | `Argentina 2 - 1 Nigeria`            |
| Elo increase                | Green          | `e.g., +12`                          |
| Elo decrease                | Red            | `e.g., -12`                          |
| Probability increase (▲)    | Green          | `e.g., ▲ +0.6`                       |
| Probability decrease (▼)    | Red            | `e.g., ▼ -0.4`                       |
| Warning / error             | Bold red       | `⚠ API error`                        |
| Success / simulation done   | Bold green     | `Re‑simulating... done`              |

**Fallback:** If terminal does not support color, all text remains plain with symbols (`▲`, `▼`, `⚠`) as visual cues.

---

## 5. User Interaction Patterns

The MVP has **zero direct interaction** after startup. The user’s only actions are:

| Action                     | System Response                                       |
|----------------------------|-------------------------------------------------------|
| `python main.py`           | Starts the infinite loop, prints header & initial probabilities. |
| `Ctrl+C`                   | Graceful shutdown: “Stopping… Final probabilities printed.” |
| `python main.py --help`    | Displays usage, options (e.g., `--seed 42` for reproducibility). |
| `python main.py --once`    | Runs one poll + simulation cycle, then exits (for testing). |

**No menus, no prompts, no input required.** This follows the Unix philosophy: a tool that does one thing well.

---

## 6. User Experience Flow (Mental Model)

1. **User runs the script.**  
   → Sees header, initial odds. Feels confident it’s working.

2. **User leaves terminal open (or runs in background).**  
   → Every minute, a heartbeat line confirms it’s alive.

3. **A real match ends.**  
   → Within ~2 minutes, the user sees a highlighted block showing the result and Elo change.

4. **User watches probabilities shift.**  
   → The delta arrows show how each team’s chance moved. This is the core “aha” moment.

5. **User stops script (Ctrl+C).**  
   → Final probabilities printed. No data loss.

**Emotional goal:** The user should feel **informed, surprised, and intellectually curious** – not overwhelmed.

---

## 7. Future Web Dashboard (UI Extension)

If the project grows to a web version, the design would follow these principles:

### 7.1 Layout (Desktop first)
```
+--------------------------------------------------+
|  Header: World Cup Predictor (live)              |
+-------------------+------------------------------+
| Bracket visual    | Top 5 probabilities (bar chart) |
| (clickable)       |                              |
|                   | Last match: Arg 2-1 Nigeria  |
|                   | Elo change: Arg +12          |
+-------------------+------------------------------+
| Timeline of probability changes (line chart)     |
+--------------------------------------------------+
| Footer: Last updated 2 seconds ago              |
+--------------------------------------------------+
```

### 7.2 Key features for web MVP
- **Auto‑refresh** every 30 seconds (no page reload, use WebSocket or polling).
- **Hover over team** to see Elo history.
- **Dark mode toggle** (because sports fans watch at night).
- **Shareable link** to current probabilities.

### 7.3 Technology suggestions for web
- Backend: Flask or FastAPI (exposes current probabilities as JSON).
- Frontend: Plain HTML + Chart.js (no React overhead for MVP).
- Real‑time: Server‑Sent Events (simpler than WebSockets).

But **do not build web version until console MVP is fully stable**.

---

## 8. Accessibility Considerations (Console)

Even for a terminal app, we can follow basic accessibility:

| Guideline                          | Implementation                                      |
|------------------------------------|-----------------------------------------------------|
| No reliance on color alone         | Use symbols (▲, ▼, ⚠) alongside color.             |
| Readable font                      | Use monospace; avoid tiny fonts (user’s terminal setting). |
| Screen reader support (rare for CLI)| Use clear plain text descriptions (e.g., “Elo increased by 12”). |
| Low vision                         | Allow user to disable color with `--no-color` flag. |

---

## 9. User Testing Scenarios (for the builder)

Test the console UI with these scenarios:

| Scenario                                  | Expected user reaction                              |
|-------------------------------------------|------------------------------------------------------|
| First run – no matches yet                | Sees initial odds, understands the heartbeat.       |
| After a real match (simulate with mock API)| Immediately notices the highlighted block and delta changes. |
| After an upset (underdog wins)            | Sees underdog’s probability jump significantly.     |
| API key invalid (error)                   | Sees clear error message, script continues.         |
| Ctrl+C during simulation                  | Exits cleanly without stack trace.                  |

**Success metric:** A friend who is not technical can look at the console output and tell you what just happened (e.g., “Argentina won, so their chances went up”).

---

## 10. Deliverables for UI/UX (MVP)

- [ ] Console output follows the format described in section 3.
- [ ] ANSI colors implemented (with fallback).
- [ ] Symbols (▲, ▼, ⚠) used even when colors off.
- [ ] `--no-color` flag available.
- [ ] `--once` flag for single run.
- [ ] Graceful shutdown on `Ctrl+C` with final probabilities.

These are **lightweight** to implement and dramatically improve perceived quality.

---

## 11. Future UI Enhancements (Post‑MVP)

| Version | Enhancement                                         |
|---------|-----------------------------------------------------|
| v1.1    | Progress bar during Monte Carlo simulation (`tqdm` library). |
| v1.2    | Save output to a log file (`--log predictions.log`). |
| v1.3    | Simple curses‑based live dashboard (refreshing in place). |
| v2.0    | Full web dashboard as described in section 7.      |

But for now, focus on the **clean, colorful, informative console** – it’s the face of your project during demos and interviews.

---

**Approval (for your own sign‑off):**

- [ ] Console output format finalised
- [ ] Color scheme defined
- [ ] Interaction model (no input) accepted
- [ ] Accessibility basics covered
- [ ] Ready to implement alongside code
```