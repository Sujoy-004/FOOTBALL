<!-- generated-by: gsd-doc-writer -->
# Frontend JavaScript Modules Reference

The FOOTBALL SPA is a vanilla-JavaScript single-page application served by FastAPI.
All frontend modules live in `web/static/` and are loaded as ES modules (`type="module"`).
The SPA shell is served at `/` from `index.html`; competition-specific views are dynamically
imported on navigation.

**Entry point:** `index.html` loads `shared.js` via `<script type="module" src="static/shared.js">`.
Chart.js v4.4.7 is loaded from CDN (`chart.umd.min.js`) and available globally as `Chart`.

---

## `shared.js` — Core SPA Framework

**Path:** `web/static/shared.js` (470 lines)

### Module Pattern

`shared.js` is the root ES module. It defines the SPA shell and exports shared utilities
consumed by `wc.js` and `ucl.js`:

```js
import { competitions, currentCompetition, buildTable, destroyModalCharts, modalCharts, drawBracketConnectors, updateStatusBar, createSimPopup, showSimPopup } from "./shared.js";
```

### Competition Registry

```js
const competitions = { ... }
```

Static lookup table with three entries:

| Slug | Label | Route | API Prefix | Tabs | Module File |
|------|-------|-------|------------|------|-------------|
| `worldcup` | "World Cup 2026" | `/worldcup` | `/worldcup/api` | Overview, Bracket, Standings | `wc.js` |
| `ucl` | "UCL 2025/26" | `/ucl` | `/ucl/api` | Overview, Bracket, Standings | `ucl.js` |
| `euro` | "Euro 2028" | `/euro` | `/euro/api` | (empty, disabled) | `null` |

Each entry stores `module` (the filename without `.js`), `route`, `apiPrefix`, and `tabs`
array used to build the tab bar dynamically.

### SPA Router

- **`navigate(hash)`** — Parses `window.location.hash`, matches against `competitions[slug].route`,
  calls either `renderLanding()` (for `/`) or `loadCompetition(slug)`.
- **Hash change listeners** — `window.addEventListener("hashchange", ...)` and `window.addEventListener("load", ...)` both call `navigate()`.
- **Click delegation** — A document-level click handler intercepts clicks on `[data-route]` elements
  and sets `window.location.hash`. Elements with `[data-disabled]` are ignored.

### Landing Page

- **`renderLanding()`** — Renders the full landing hero with competition cards and feature grid.
  Clears `currentCompetition`, resets body class, calls `renderNavBar(null)`, and triggers
  `loadLandingStats()`.
- **`loadLandingStats()`** — Fetches `/worldcup/api/data` and `/ucl/api/data` in parallel via
  `Promise.allSettled`, then populates the competition card metadata (team count, simulation count,
  matches played, champion name).
- **`renderNavBar(activeSlug)`** — Rebuilds the nav bar with competition buttons (World Cup, UCL)
  marking the active competition with an `active` class.

### Competition Module Loader

**`loadCompetition(slug)`** is the heart of the SPA:

1. Hides the landing backdrop, sets `body.className = "competition-" + slug`.
2. Calls `renderNavBar(slug)`.
3. Builds the tab bar and content area shell from `comp.tabs`.
4. Wires tab switching (click handler on `#tabBar`).
5. Wires the modal overlay (close button + overlay click-to-dismiss).
6. Dynamically imports `./wc.js` or `./ucl.js`:
   ```js
   const mod = await import("./" + (comp.module || slug) + ".js");
   ```
7. Calls `mod.init(comp)` on the loaded module.

### Shared Helper Functions

| Function | Purpose |
|----------|---------|
| `buildTable(teams, cols, keyMap)` | Generates an HTML table with rank bars from array of team objects. Columns defined by `cols` array; labels by `keyMap`. |
| `destroyModalCharts()` | Destroys all Chart.js instances in `modalCharts` object and clears it. Called on modal close. |
| `modalCharts` | Global object `{}` holding active Chart.js instances keyed by chart name. |
| `drawBracketConnectors()` | Draws SVG connector paths between bracket rounds. Reads `window.__bracketData` (set by the competition module), iterates columns in `#bracketGrid`, draws `M ... L ...` paths for each match's `source_matches`. |
| `updateStatusBar(left, right)` | Sets `innerHTML` of `#statusLeft` and `#statusRight` in the bottom status bar. |

### Simulation Popup (shared)

Three functions implement a reusable simulation popup:

- **`createSimPopup()`** — Creates the overlay DOM element with preset buttons (10K/50K/100K/500K),
  custom input, cancel/start buttons, and a progress bar. Wires preset selection and cancel. Singleton
  pattern: creates once, caches in `_simOverlay`.
- **`showSimPopup(apiPrefix, opts)` — Shows the popup. Sets the Start button's click handler to
  call `_startSim()` with `opts.onComplete` callback and `opts.bodyBuilder`.
- **`_startSim(apiPrefix, onComplete, bodyBuilder)` — Posts to `{apiPrefix}/simulate`, polls
  `{apiPrefix}/simulation/progress/{taskId}` every 200ms, updates progress bar and ETA label.
  On completion, hides popup and calls `onComplete(iters)`.

**Polling state:** `_simPolling` flag prevents concurrent simulations.

---

## `wc.js` — World Cup Dashboard

**Path:** `web/static/wc.js` (904 lines)

### Module Entry

```js
export function init(comp) { loadAll(); }
```

Called by `shared.js` after dynamic import.

### State

```js
const appState = { data: null, overview: null, standings: null, bracket: null, fullBracket: null, eval: null, blend: null, signalCache: {} };
let refreshing = false;
let autoRefreshOn = false;
let autoTimer = null;
```

### API Endpoints Consumed

| Endpoint | Called By | Purpose |
|----------|-----------|---------|
| `GET /worldcup/api/overview` | `loadAll()` | Competition overview stats |
| `GET /worldcup/api/standings` | `loadAll()` | Group standings data |
| `GET /worldcup/api/bracket` | `loadAll()` | Bracket match list |
| `GET /worldcup/api/bracket/data` | `loadAll()` | Bracket tree with `chronological_rounds` and `knockout_tree` |
| `GET /worldcup/api/bracket/full` | `loadAll()` | Full bracket with round details for match modal |
| `POST /worldcup/api/simulate` | `startSimulation()`, `startMatchSim()` | Start simulation job |
| `GET /worldcup/api/simulation/progress/{taskId}` | `startSimulation()`, `startMatchSim()` | Poll simulation progress |
| `GET /worldcup/api/simulation` | `startSimulation()` | Fetch simulation results |
| `POST /worldcup/api/simulate-from-match` | `startMatchSim()` | Single-match simulation |
| `GET /worldcup/api/match/insight?match_id={id}` | `openMatchModal()` | Match-level prediction detail |
| `POST /worldcup/api/what-if` | `window.__sendWhatIf()` | What-if scenario analysis |

### Data Loading

**`loadAll()`** — Fetches overview, standings, bracket, bracket/data, and bracket/full sequentially.
Populates `appState` and calls `renderOverview()`, `updateStatus()`, `renderStandings()`,
`renderBracket()`.

### Views

#### `renderOverview()`
Renders the Overview tab (`#tab-overview`) with:
- Stats row (teams, matches played, signals available)
- Signal cache status table (`renderOverviewSignals()`)

Helper functions:
- **`renderSignalEval(signalEval)`** — Returns an HTML eval table with Brier score, accuracy, and
  matches count per signal, color-coded by Brier threshold (<0.15 green, <0.25 orange, >=0.25 red).
- **`renderOverviewStandings(standings)`** — Returns collapsible group detail `<details>` elements
  with group tables (position, team, pts, GD, GS).
- **`renderOverviewSignals(signals)`** — Returns table of signal name, availability dot, and
  last-updated timestamp.

#### `renderBracket()`
Renders the Bracket tab (`#tab-bracket`) with:
1. **Group Stage Accordion** — Matches grouped by round with play count badges. Each group round
   rendered via `renderMatchRow()`.
2. **Knockout Tree** — Visual bracket using `div.bracket-col` columns inside `#bracketGrid`.
   Rounds: R32, R16, QF, SF, TPP, FINAL. Each round column contains `.match-card` elements with
   team names, scores, and winner labels. Cards are spaced using `getRowRange()` and `getLeafOrder()`
   recursive tree traversal to calculate vertical position.
3. SVG connectors drawn via shared `drawBracketConnectors()`.
4. "Simulate All Remaining" button wired to `window.__simulateAllRemaining()`.
5. Per-match "Simulate" buttons on unplayed matches wired to `window.__simulateMatch(matchId)`.

**Simulation overlay:** Simulated bracket data from `appState.simBracket` is merged into the
knockout tree, showing predicted scores and percentage labels.

#### `renderMatchRow(m)`
Returns a single match row for the group stage accordion. Shows team A, score, team B, and
played/TBD status with green/orange dot.

#### `renderStandings()`
Renders the Standings tab (`#tab-standings`) with a grid of group cards. Each card shows a
group table with position, team, pts, GD, GS. Rows are CSS-classed as `advancing` (top 2),
`bubble` (middle), or `eliminated` (last). Handles both legacy format (`{standings: {A: [...]}}`)
and flat array format.

### Simulation

#### Independent Popup (not using shared `showSimPopup`)

WC has its own simulation popup implementation:
- **`showSimPopup()`** — Creates/brings up the popup overlay. Wire presets, cancel, and start.
- **`startSimulation()`** — Sends `POST /worldcup/api/simulate`, polls progress, then reloads
  all data via `loadAll()`, fetches `/worldcup/api/simulation` for bracket results,
  and calls `renderBracket()`.

#### Match-Level Simulation

- **`showMatchSimPopup(title)`** — Separate popup for individual match simulation with preset
  options (5K/10K/50K). Sets `simMatchId`.
- **`startMatchSim()`** — If `simMatchId === '__all__'` runs full tournament sim; otherwise sends
  `POST /worldcup/api/simulate-from-match` and displays top contender probabilities and
  downstream match count.

### Match Insight Modal

**`openMatchModal(mid)`** — Opens the shared modal overlay with:
- **Left column:** Form trend line charts (Chart.js) for each team, signal comparison horizontal
  bar chart, outcome distribution doughnut chart.
- **Right column:** Signal performance table (Brier, accuracy per signal from `appState.eval`),
  match insight text from API.
- **Bottom:** What-If scenario input with instant/simulate mode selector, iteration count selector,
  progress bar, and result display.

### What-If Analysis

**`window.__sendWhatIf(mid)`** — Exposed on `window` for inline `onclick`.
- **Instant mode:** Sends `POST /worldcup/api/what-if` with `mode: "instant"`. Displays insight
  text, adjusted signal deltas (with toggle detail), and detection confidence.
- **Simulate mode:** Sends `POST /worldcup/api/what-if` with `mode: "simulate"` and `iterations`.
  Polls `/worldcup/api/simulation/progress/{taskId}` for progress, displays top 5 champion
  probabilities on completion.

### Refresh & Auto-Refresh

- **`updateStatus()`** — Updates the shared status bar with team count, matches played, active
  signal count. Skipped during `refreshing`.
- **`toggleAuto(on)`** — Enables/disables 60-second auto-refresh interval.
- **`window.__refreshWC`** — Alias to `showSimPopup()`, used by the status bar. `doRefresh` is referenced in `toggleAuto()` but is not defined.

---

## `ucl.js` — UCL Dashboard

**Path:** `web/static/ucl.js` (555 lines)

### Module Entry

```js
export function init(comp) { loadAll(); }
```

Called by `shared.js` after dynamic import.

### State

```js
const appState = { data: null, standings: [], bracket: null, odds: [], signals: {}, matches: [] };
const sigLabels = { refined_elo: "Refined Elo", ... };
const sigOrder = ["refined_elo", "rolling_form", "market_odds", ...];
```

### API Endpoints Consumed

| Endpoint | Called By | Purpose |
|----------|-----------|---------|
| `GET /ucl/api/data` | `loadAll()`, `reloadData()` | Competition overview |
| `GET /ucl/api/standings` | `loadAll()`, `reloadData()` | Swiss league table |
| `GET /ucl/api/bracket` | `loadAll()`, `reloadData()` | Bracket tree + playoff + league matchdays |
| `GET /ucl/api/odds` | `loadAll()`, `reloadData()` | Championship/qualification odds |
| `GET /ucl/api/signals` | `loadAll()`, `reloadData()` | Signal metadata and evaluation |
| `POST /ucl/api/simulate` | via shared `showSimPopup()` | Start simulation |
| `GET /ucl/api/simulation/progress/{taskId}` | via shared `showSimPopup()` | Poll simulation progress |
| `GET /ucl/api/simulation` | reload after sim | Fetch simulation bracket results |
| `GET /ucl/api/match/insight?match_id={id}` | `openMatchModal()` | Match-level prediction detail |
| `POST /ucl/api/what-if` | `window.__sendModalWhatIf()` | What-if scenario analysis (instant only) |
| `POST /ucl/api/reset` | `window.__resetResults()` | Reset simulation results |

### Data Loading

**`loadAll()`** — Fetches all five endpoints in parallel via `Promise.all([fetch(...), ...])`.
Populates `appState` with data, standings, bracket, odds, signals. Builds a flat `matches` array
from `bracket.playoff` and `bracket.bracket_rounds`. Calls render functions in individual
try/catch blocks.

**`reloadData()`** — Identical to `loadAll()` but also called after simulation completes to
refresh the UI.

### Views

#### `renderOverview()`
Renders the Overview tab (`#tab-overview`) with:
- Stats row: teams, matches played, signal availability.
- Signal cache status table with columns: Signal, Available (dot), Matches, Avg Prob, Weight.

#### `renderStandings()`
Renders the Standings tab (`#tab-standings`) as a **Swiss-system league table** with:
- Columns: Pos, Team, Pld, W, D, L, GF, GA, GD, Pts, Zone.
- Zone badges: `TOP 8` (green), `PLAYOFF` (teal), `OUT` (red).
- Row CSS classes: `zone-top8`, `zone-playoff`, or default (eliminated).

#### `renderBracket()`
Renders the Bracket tab (`#tab-bracket`) with three sections:
1. **League Phase Accordion** — Matchdays from `bracket.league_matchdays` rendered as collapsible
   `<details>`-style cards. The first matchday is open by default.
2. **Playoff Round** — Grid of playoff cards showing two-legged aggregate scores with ET/penalty
   indicators.
3. **Knockout Tree** — Visual bracket for R16, QF, SF, FINAL rounds. Uses same `bracket-col` /
   `match-slot` / `match-card` structure as WC. Simulated scores from `appState.simBracket` are
   displayed for unplayed matches. SVG connectors drawn via shared `drawBracketConnectors()`.

Round order for UCL KO tree: `["R16", "QF", "SF", "FINAL"]` (no R32 or TPP).

#### `renderOdds()`
Renders the Odds tab (`#tab-odds`) with:
- Table columns: Rank, Team, Champion (with horizontal bar), Final, SF, QF, Top 8.
- Probabilities displayed as percentages. Champion probability bar width is `champion_prob * 200`.

#### `renderSignals()`
Renders the Signals tab (`#tab-signals`) with:
- Table columns: Signal, Avg Prob, Matches, Avail (High/Medium/Low %, color-coded), Weight.
- Extra columns Brier and Accuracy when `mode === "results"` (actual matches played).
- Signal availability dot colors: >=80% green, >=50% orange, <50% red.
- Brier dot colors: <0.15 green, <0.25 orange, >=0.25 red.

### Simulation

UCL reuses the shared **`showSimPopup(API, opts)`** from `shared.js`:

```js
window.__simulateAllRemaining = function () {
  showSimPopup(API, {
    bodyBuilder: iters => ({ iterations: iters }),
    onComplete: async () => {
      await reloadData();
      // fetch simulation bracket
      const simResp = await fetch("/ucl/api/simulation").then(r => r.json());
      appState.simBracket = ...;
      renderBracket();
    },
  });
};
```

**`window.__resetResults()`** — Posts `POST /ucl/api/reset`, then refetches all five API
endpoints and re-renders all views.

### Match Insight Modal

**`openMatchModal(m)`** — Opens the shared modal for a match object (not just match ID like WC).
Same layout as WC:
- Form trend line charts per team (Chart.js)
- Signal comparison bar chart
- Outcome distribution doughnut
- Signal performance table with Brier/accuracy (from `appState.signals`, not `appState.eval`)
- What-If input at the bottom

### What-If Analysis

**`window.__sendModalWhatIf(matchId, teamA, teamB)`** — Instant-mode only (no simulation mode).
Sends `POST /ucl/api/what-if` and displays insight text, adjusted signal deltas with toggle
detail, and detection confidence.

Signals used in UCL what-if: `refined_elo`, `rolling_form`, `market_odds`, `defensive_quality`,
`manager_effect`, `squad_value`, `player_form`, `team_synergy`, `availability`, `rest_days`.

### Status Bar

**`updateStatus()`** — Reports team count, matches played, and active signal count
(active = `available || available_pct > 0 || n_matches > 0`).

---

## Shared Patterns

### Tab System

Each competition module has a three-tab layout: Overview, Bracket, Standings.
Tabs are built declaratively by `shared.js` from `competitions[slug].tabs`.
Tab buttons have `data-tab` attribute; content panels have `id="tab-{name}"`.
Active tab toggling is handled by the tab bar click handler in `loadCompetition()`.
Bracket tab switching triggers `setTimeout(drawBracketConnectors, 300)`.

### Modal System

A single modal overlay (`#modalOverlay` > `.modal`) is created in `loadCompetition()`.
Competition modules populate it via:
- `destroyModalCharts()` — called before showing a new modal
- `document.getElementById("modalTitle")`, `#modalSub`, `#modalBody` — content targets
- Chart.js instances stored in `modalCharts` for cleanup

### Bracket SVG Connectors

Both modules set `window.__bracketData` to their knockout tree data before rendering.
`drawBracketConnectors()` in `shared.js` reads this global and draws connecting paths between
rounds. The algorithm:
1. Gets bounding rects of each `.bracket-col`
2. Finds `.match-card[data-mid]` elements in adjacent columns
3. For each match, looks up `source_matches` in bracket data
4. Draws orthogonal SVG `<path>` lines from the right edge of source matches to the left
   edge of parent matches

### Chart.js Usage

Chart.js v4.4.7 is loaded from CDN in `index.html`. Both `wc.js` and `ucl.js` create
Chart.js instances directly (`new Chart(canvas, { ... })`) without importing — Chart is
a global. Chart types used:
- **Line:** Form trend charts (last 5 matches, win=1 draw=0.5 loss=0)
- **Bar (horizontal):** Signal comparison probabilities
- **Doughnut:** Outcome distribution (Team A win / Draw / Team B win)

### Global Exports

Functions exposed on `window` for inline HTML event handlers:

| Global | Module | Purpose |
|--------|--------|---------|
| `window.__refreshWC` | `wc.js` | Alias for `showSimPopup` |
| `window.__simulateMatch(id)` | `wc.js` | Single-match simulation from bracket card |
| `window.__simulateAllRemaining()` | `wc.js`, `ucl.js` | Full tournament simulation |
| `window.__sendWhatIf(mid)` | `wc.js` | What-if analysis with mode selector |
| `window.__sendModalWhatIf(mid, ta, tb)` | `ucl.js` | What-if analysis (instant only) |
| `window.__resetResults()` | `ucl.js` | Reset simulation results |
| `window.__bracketData` | set by both | Knockout tree for SVG connector drawing |

### Backend Interaction

All modules communicate with the FastAPI backend via `fetch()` to the competition's `apiPrefix`
(`/worldcup/api` or `/ucl/api`). The backend is served from `web/server.py` (port 8080),
with competition sub-apps in `web/wc_app.py` and `web/ucl_app.py`. The SPA shell is mounted
at `/` serving `index.html`, and static assets are served under `/static/`.
