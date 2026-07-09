<!-- generated-by: gsd-doc-writer -->
# Web Dashboard Layer

The web dashboard layer provides a browser-based frontend for exploring Monte Carlo simulation results, match insights, standngs, bracket visualizations, and what-if scenarios for the World Cup 2026 and UCL 2025/26 competitions. It consists of a **FastAPI server** that mounts competition sub-applications, shared **insight and what-if engines**, and a **vanilla JavaScript single-page application** served from `web/static/`.

---

## Architecture

```
web/server.py  (port 8080)
├── /                    → SPA shell (index.html)
├── /worldcup            → wc_app (FastAPI sub-app)
│   └── /api/…           → WC endpoints
├── /ucl                 → ucl_app (FastAPI sub-app)
│   └── /api/…           → UCL endpoints
├── /static              → shared.css, shared.js, wc.js, ucl.js
└── /euro                → stub (returns "coming_soon")
```

- **`server.py`** — creates the root `FastAPI` instance, registers a `lifespan` handler that calls `compute_or_load()` (WC) and `compute_all()` (UCL) on startup, mounts the two sub-apps, serves the SPA at `/`, and wraps everything in a `_NoCacheASGI` middleware that disables caching for `/static/` resources.
- **`wc_app.py`** — the World Cup sub-app, mounted at `/worldcup`. Generates a cache of all simulation results, group standings, bracket matchups, signal evaluations, governance data, and coverage audits at startup.
- **`ucl_app.py`** — the UCL sub-app, mounted at `/ucl`. Loads real results (if available) or runs a fresh Monte Carlo simulation on startup. Supports switching between "results" mode (deterministic standings from match data) and "simulation" mode.
- **`whatif_engine.py`** — shared natural-language what-if scenario parser and signal adjuster, used by both sub-apps.
- **`insight.py`** — shared match insight computation (form trends, head-to-head, signal strengths, outcome distribution), used primarily by the WC sub-app.
- **`common.py`** — shared utilities (`ts()` timestamps, `boot_step()` timing/logging, `load_json`/`load_json_list` file helpers).

### Cache / Persistent State

Both sub-apps maintain an in-memory global `cache: dict`. The WC sub-app also writes a `cache.json` file so subsequent restarts can skip full recomputation. The UCL sub-app re-computes on every startup. Both store the boot log (timed step-by-step startup progress) in the cache under the `"boot"` key.

---

## API Endpoints

### World Cup (`/worldcup/api`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/data` | Summary: team count, matches played, iteration count |
| GET | `/api/boot` | Startup boot log (timed steps) |
| GET | `/api/standings` | Group standings + third-place bubble |
| GET | `/api/bracket` | Resolved R32 bracket display |
| GET | `/api/bracket/full` | Full bracket (R32 → R16 → QF → SF → TPP → FINAL) with signal data |
| GET | `/api/evaluation` | Signal evaluation metrics (Brier, LogLoss, Accuracy) |
| GET | `/api/governance` | System health: data/model/run version, status, match count |
| GET | `/api/backtest` | Full backtest report |
| GET | `/api/coverage` | Feature coverage audit |
| GET | `/api/signals` | Signal statistics across all ledger entries |
| GET | `/api/signal/{name}` | Per-signal detail with live evaluation |
| GET | `/api/blend` | Signal blending weights and calibration status |
| POST | `/api/refresh` | Trigger async data refresh from BSD API; returns `task_id` |
| GET | `/api/refresh/progress/{task_id}` | Poll refresh progress |
| GET | `/api/match/insight?match_id=…` | Form trend, H2H, signal comparison, outcome distribution for a match |
| POST | `/api/what-if` | What-if scenario (instant or simulate mode) |
| GET | `/api/simulation/progress/{task_id}` | Poll what-if simulation progress |

### UCL (`/ucl/api`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/data` | Summary: teams, iteration count, snapshot date, champion, mode |
| GET | `/api/boot` | Startup boot log |
| GET | `/api/standings` | League table (36 teams) + mode |
| GET | `/api/bracket` | Playoff results, bracket rounds, league matchdays, champion |
| GET | `/api/odds` | Champion / qualification odds for all teams |
| GET | `/api/signals` | Signal blend statistics |
| POST | `/api/simulate` | Trigger async Monte Carlo re-simulation; returns `task_id` |
| POST | `/api/reset` | Reset to real results mode (re-runs `compute_all()`) |
| GET | `/api/simulation/progress/{task_id}` | Poll simulation progress |
| GET | `/api/match/insight?match_id=…` | Form trend, H2H, signal comparison, outcome distribution |
| POST | `/api/what-if` | What-if scenario (instant or simulate mode) |

---

## WebSocket / Polling

Both sub-apps use an **async task + polling** pattern (not WebSockets) for long-running operations:

1. **POST** to the operation endpoint immediately returns a `task_id` (UUID).
2. The server spawns a **daemon thread** to execute the work, updating progress in a shared `active_simulations` dict protected by `sim_lock`.
3. The frontend polls `GET /api/…/progress/{task_id}` at 200–300ms intervals.
4. On completion or error, the server deletes the task entry and returns the final result / error in the poll response.

Operations using this pattern:
- **WC refresh** (`/api/refresh`): fetches new match data from the BSD API, re-computes predictions, invalidates the cache.
- **WC what-if simulate** (`POST /api/what-if` with `mode: "simulate"`): runs a full 50,000-iteration Monte Carlo simulation with adjusted parameters and compares against the baseline.
- **UCL simulation** (`/api/simulate`): runs a full Monte Carlo simulation (default 10,000 iterations) for the UCL Swiss league + knockout format.
- **UCL what-if simulate** (`POST /api/what-if` with `mode: "simulate"`): runs baseline + adjusted simulations and compares champion probabilities.

---

## Frontend SPA

The single-page application is built with **vanilla JavaScript (ES modules)** served from `web/static/`.

### File Structure

```
web/static/
├── index.html       → SPA shell (<div id="app">, hidden terminal input, module script)
├── shared.css       → All styles (~330 lines, dark theme, responsive)
├── shared.js        → Router, landing page, competition registry, tab system, terminal UI,
│                      bracket connector SVG drawing, modal chart lifecycle, status bar
├── wc.js            → World Cup module: dashboard, bracket, standings, match insight modal,
│                      what-if UI, terminal boot + commands
└── ucl.js           → UCL module: overview, league table, bracket, odds, signals,
│                      what-if page, terminal boot + commands
```

### SPA Architecture

**Router (shared.js):**
- Listens to `hashchange` and `load` events.
- Routes: `/` → landing page, `/{route}` → loads competition module.
- All navigation uses `[data-route]` attributes with delegated click handling.

**Competition Registry (shared.js):**
```javascript
const competitions = {
  worldcup: { label: "World Cup 2026", module: "wc", route: "/worldcup",
              apiPrefix: "/worldcup/api", tabs: ["Dashboard","Bracket","Standings","Terminal"] },
  ucl: { label: "UCL 2025/26", module: "ucl", route: "/ucl",
         apiPrefix: "/ucl/api", tabs: ["Overview","League Table","Bracket","Odds","Signals","Terminal"] },
  euro: { label: "Euro 2028", disabled: true, ... },
};
```

**Tab System (shared.js):**
- Each competition module defines an array of tabs.
- The shared shell renders tab buttons + content divs.
- Tab switching hides/shows via CSS class `.active`.
- First tab is automatically activated on load.

**Module Loading (shared.js):**
- Competition modules (`wc.js`, `ucl.js`) are loaded dynamically via `import()`.
- Each module exports an `init(comp)` function that wires the terminal, fetches API data, renders all tabs, and triggers the terminal boot sequence.

### Match Insight Modal

Clicking any match card in the bracket opens a modal with:
- **Left column:** form trend charts (last 5 results as line charts via Chart.js), signal comparison (horizontal bar chart), outcome distribution (doughnut chart).
- **Right column:** signal performance table (Brier / Accuracy per signal), natural language insight text.
- **Bottom section:** what-if scenario input with instant or simulate mode.

### Terminal UI

Both competition modules implement a retro terminal interface with:
- **Boot sequence:** fetches `/api/boot` steps and renders them with animated timing.
- **Command interpreter:** `top N`, `elo`, `rank`, `standings`, `bracket`, `eval`, `form`, `lineup`, `defensive`, `manager`, `odds`, `cboost`, `blend`, `coverage`, `gov`, `refresh`, `auto`, `clear`, `help` (WC); `top N`, `table`, `odds`, `bracket`, `playoff`, `signals`, `champion`, `clear`, `help` (UCL).
- **Input handling:** buffers keystrokes, supports history navigation (arrow up/down), hidden `<input>` element, with visual cursor.

---

## What-If Engine (`web/whatif_engine.py`)

The what-if engine allows users to describe scenarios in natural language and see how win probabilities shift.

### Scenario Parsing (`parse_scenario`)

The parser:
1. **Detects target team** — matches team names (case-insensitive) from `competitions/ucl/data/teams.json` against the scenario text.
2. **Detects player names** — a built-in `player_map` maps known players to their national teams.
3. **Matches condition patterns** — 20+ regex patterns organized by category (injuries, form, defense, manager, odds, weather, fatigue, momentum). Each pattern maps to multiplier adjustments on one or more signals.

Pattern categories and their signal adjustments:

| Category | Example Keywords | Signals Adjusted |
|----------|-----------------|-----------------|
| Injury / absence | `injured`, `suspended`, `out` | `lineup_strength`, `form` |
| Form | `on fire`, `slump`, `poor form` | `form` |
| Defense | `weak defense`, `solid defense` | `defensive_quality` |
| Manager | `new manager`, `sacked` | `manager_effect` |
| Weather | `rain`, `heat`, `home crowd` | `form`, `defensive_quality` |
| Fatigue | `tired`, `short rest`, `extra time` | `form`, `lineup_strength` |
| Momentum | `winning streak`, `demoralized` | `form` |

Each matched pattern applies a multiplier (e.g., `0.30` for weak defense, `1.60` for strong form). Multiple pattern matches are compounded multiplicatively. Confidence is calculated from team detection (0.3) + player match (0.2) + 0.2 per matched pattern (capped at 1.0).

### Instant Mode (`handle_instant_scenario`)

Adjusts signal probabilities in-place without re-running the simulation:
1. Calls `parse_scenario()` to get adjustments.
2. Calls `apply_adjustments()` which multiplies signal probabilities toward/away from 0.5 depending on whether the target team is team_a or team_b.
3. Computes `blended_before` and `blended_after` probabilities (weighted average across all signals).
4. Generates natural language insight describing which signals changed, by how much, and what the impact on win probability is.

### Simulate Mode

Runs a full Monte Carlo simulation with adjusted parameters:
1. Parses the scenario and computes signal adjustments as in instant mode.
2. Converts signal adjustments into `xg_overrides` (goal rate multipliers) for the affected teams.
3. Runs the full simulation pipeline (50,000 iterations by default) with the overrides.
4. Compares scenario results against the cached baseline and generates insight text showing which teams gained/lost champion probability.

### Signal Labels

```python
SIGNAL_LABELS = {
    "form": "current form",
    "lineup_strength": "lineup strength",
    "defensive_quality": "defensive quality",
    "manager_effect": "manager effect",
    "market_odds": "market odds",
    "catboost": "catboost model",
    "elo": "Elo rating",
}
```

---

## Insight Engine (`web/insight.py`)

The insight engine provides per-match analysis for the World Cup bracket. It reads directly from the predictions ledger, played matches, and player/group data files in `competitions/worldcup/data/`.

### Key Functions

- **`compute_team_signal_strengths(ledger, played_groups)`** — Aggregates per-signal probabilities across all historical matches to build a per-team average rating for each signal type. For `defensive_quality` and `manager_effect`, it uses dedicated rating fields; for all other signals it derives team ratings from win probability data.

- **`compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings)`** — Computes per-signal win probabilities for a knockout match. For each of 6 signals (`form`, `lineup_strength`, `defensive_quality`, `manager_effect`, `market_odds`, `catboost`), it compares the two teams' strength ratings: `prob = sa / (sa + sb)`. Falls back to Elo probability if signal data is unavailable.

- **`compute_match_insight(match_id, fb_data, eval_data, blend_weights)`** — Aggregates all insight data for a single match:
  1. Locates the match in the full bracket by `match_id`.
  2. Computes per-signal probabilities via `compute_ko_signal_probs`.
  3. Computes form trends for both teams (last 5 results across all competitions).
  4. Computes head-to-head history between the two teams.
  5. Computes outcome distribution (a_win / draw / b_win) from blended probability.
  6. Generates natural language insight text.

- **`compute_form_trend(team_name, played, played_groups)`** — Returns the last 5 match results for a team, combining both knockout and group-stage fixtures.

- **`compute_head_to_head(ta, tb, played, played_groups)`** — Returns H2H win/loss/draw counts and individual match scores between two teams.

- **`compute_match_outcome(blended_prob, ta, tb, elo_ratings)`** — Estimates outcome distribution by estimating a draw probability from Elo difference, then distributing remaining probability proportionally to the blend.

- **`generate_insight_text(ta, tb, signals, form_trends, h2h, outcome, eval_data)`** — Produces a natural language string summarizing which signal leads, the form streak of each team, H2H record, predicted probabilities, most/least reliable signals.

---

## Shared Utilities (`web/common.py`)

| Function | Description |
|----------|-------------|
| `ts()` | Returns an ISO-8601 UTC timestamp string (`YYYY-MM-DD HH:MM:SS`) |
| `boot_step(step_name, action, boot_log)` | Times an action, appends a `{step, status, elapsed, output}` record to the boot log. Returns the action result or `None` on exception. |
| `load_json(data_dir, name)` | Opens and parses a JSON file as `dict` |
| `load_json_list(data_dir, name)` | Opens and parses a JSON file as `list` |

---

## Development

### Running the Server

```bash
python -m web.server
```

Starts uvicorn on `127.0.0.1:8080`. The server loads all competition data and runs Monte Carlo simulations during the lifespan startup — this may take 30–90 seconds depending on data size.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BSD_API_KEY` | No | `""` | API key for the BSD sports data provider. Required for `/api/refresh` (WC) and manager data (UCL). |

### Project Dependencies

- `fastapi`, `uvicorn` — server framework
- `starlette` — ASGI middleware (`_NoCacheASGI`)
- `requests` — BSD API fetches
- `python-dotenv` — `.env` file loading
- `chart.js` (CDN) — frontend charts
- `playfair+display`, `orbitron`, `jetbrains+mono` (Google Fonts, CDN) — typography

### Debugging Tips

- **Cache invalidation:** Delete `web/cache.json` to force full re-computation on next startup.
- **Data refresh:** Call `POST /worldcup/api/refresh` (requires `BSD_API_KEY` in `.env`), or manually re-run data fetcher scripts.
- **UCL results mode:** Place `results.json` and `knockout_results.json` in `competitions/ucl/data/` to switch from simulation mode to deterministic results mode.
- **Frontend changes:** Edit `web/static/` files directly — the `_NoCacheASGI` middleware ensures no stale caching.
- **Logging:** Boot steps are logged to the `boot_log` array accessible via `/api/boot`. Errors during startup are printed to stdout.

### Adding a New Competition

1. Add an entry to the `competitions` object in `shared.js`.
2. Create a new module file (e.g., `euro.js`) with an `init(comp)` export.
3. Create a new FastAPI sub-app (e.g., `euro_app.py`) and mount it in `server.py`.
4. Define API endpoints and the cache/boot mechanism following the pattern in `wc_app.py` or `ucl_app.py`.
<!-- VERIFY: BSD API base URL (https://sports.bzzoiro.com) is an external service endpoint -->
<!-- VERIFY: BSD_API_KEY is required for data refresh; key name may differ by deployment -->