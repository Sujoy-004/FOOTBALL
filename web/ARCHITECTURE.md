# Web layer architecture (Exchange 9C addendum)

Concise notes on how the live-data freshness machinery is layered. This
file documents the shared-vs-configurable split; the code that enforces
every rule below is `web/cache_control.py`, `web/static/refresh.js` and the
`liveRefresh` wiring in `web/static/shared.js`.

## Layers

- **Shared (one implementation, no per-competition branching)**
  - `cache_control.no_store_for_competition_api` — ASGI middleware that
    stamps `Cache-Control: no-store` on every path under a registered
    competition API prefix (`competition_api_prefixes()` derives prefixes
    from the REGISTRY, so a future competition is covered automatically).
    Composed in `web/server.py` outside the existing static no-cache
    wrapper: statics keep `no-cache, no-store, must-revalidate`, the
    landing page keeps no header.
  - `refresh.createRefreshManager` — one manager instance per page, shared
    by all competition modules via `shared.js`. Owns the *policy*: poll only
    while a competition is active, enabled, and the page is visible; one
    timer + one in-flight refresh per competition; activation/visibility
    coalescing; full stop on leaving to the landing page. Timing and
    visibility primitives are injectable, which is what makes the suite in
    `refresh.test.mjs` deterministic (fake clock).
  - `shared.js` SPA lifecycle wiring — the shell arms refresh after a
    module boots (`activateCompetitionRefresh`), asks for catch-up refresh
    on tab clicks (`requestCompetitionRefresh`), hard-stops on the landing
    page (`stopAllCompetitionRefresh`) and owns the single
    `visibilitychange` listener.

- **Configurable per competition (registry data, no code)**
  - The `liveRefresh: { enabled, intervalMs, refreshOnActivation }` block on
    each entry of the `competitions` registry. Intervals differ per
    competition (UCL 90s, WC 45s); both disable their whole mechanism with
    `enabled: false`. The server-side cache policy is unconditionally
    uniform no-store (correct regardless of a competition's polling).

- **Competition-specific (each module's own code)**
  - The `reload` hook each module passes to
    `configureCompetitionRefresh` in its `init()`: which payloads to
    refetch, and how to commit/re-render. `ucl.js` refetches only the five
    live endpoints (`data/standings/bracket/odds/signals`); `wc.js`
    refetches its five raw payloads (overview/standings/bracket/
    bracket-data/bracket-full) with the same per-fetch failure tolerance as
    its full load. The fully-loaded `loadAll` (which also fetches `/seasons`
    for UCL) is unchanged.

## Shared UI shell (Phase 12A addendum)

- Every competition renders the SAME primary shell from the shared registry's
  `tabs` array (Overview → Standings → Bracket|Fixtures → Simulation), with
  Simulation a first-class tab in all three modules, so no competition may
  fork the tab bar or ship its own copy of the simulation popup — WC and UCL
  call the single `showSimPopup` in `shared.js` (competition bounds passed as
  `opts`), and any auxiliary view such as LaLiga's pure-Elo Validation lives
  as a section inside Overview, never as an extra top-level tab.

## Refresh semantics

- Generation-token discipline: `loadAll` is the *only* incrementer of
  `_transitionGen`. `refreshLive` captures the current token, fetches, and
  checks `_stale(gen)` before each commit — so a live refresh can never
  commit over a newer full load, and a competition switch discards it.
- A refresh and a full load may both commit if they share the same token;
  both fetched the same server state and the later write wins, which is
  harmless.
- `refreshLive` never touches simulation state, in every competition: UCL,
  WC and LaLiga all refetch only factual live payloads on live refresh and
  re-render the Simulation tab from held `simMeta`/sim state — none of them
  re-fetches or re-applies `/api/simulation` in a refresh path, so a
  completed simulation survives live refresh and the shared simulation
  popup's progress is never disturbed by unrelated polling.

## Cache semantics

- `no-store` is applied to *all* competition API responses, including the
  idempotent simulation reads — a re-fetch never recomputes server state
  and never mutates the simulation cache, so reapplying the policy there is
  safe and keeps request/render ordering truthful for the user.
- Root cause it closes (Phase 9B): an open tab across a server-side refresh
  must not replay a stale cached JSON payload.

## Shared visual structure (Phase 12B addendum)

One shared stylesheet (`web/static/shared.css`). Every competition themes by
a body class that is the ONLY place palette colors live
(`.competition-laliga` / `-worldcup` / `-ucl`), so a competition fork is a
block of `color:` overrides, never new page structure.

- **Backgrounds are per-competition image + overlay.** WC (`images/wc.webp`),
  UCL (`images/ucl.webp`) and — new in 12B — LaLiga (`images/laliga.webp`)
  each declare a `linear-gradient(...), url("images/<comp>.webp") center /
  cover fixed no-repeat;` on the body class, and the same image as an
  `lc-card` landing tile (no absolute paths; the darkening gradient is the
  readability guarantee over the artwork). `fixed` rides the last layer the
  same way it does on the pre-existing W.C./UCL rules.
- **Shared structural primitives** (defined once, themed by the palette
  block): `.stats-row/.stat-card` (dashboard strip), `.chart-section/.title`
  (section), `.eval-table` (data tables), `.status-btn`, `.m-sub`/`.dim`
  (descriptors), `.phase-card`/`.pred-cell`/`.form-field` (cards + forms),
  `.sim-provenance` (+ `.failed`) — the simulation provenance banner.
- **Overview layout contract:** every Overview is `stats-row` strip →
  themed `.chart-section` blocks ordered around the competition's facts.
  Shared tables replace per-competition ad-hoc rows (`.ol-signal-list`,
  `buildTable` misuse, `.section-title` were removed). Acquisition is always
  rendered by the shared `shared.js:renderAcquisitionPanel` into a
  competition-owned host div.
- **Simulation layout contract:** every Simulation tab renders in canonical
  order — header → controls/launcher → run/status → result summary →
  detailed results → provenance (`.sim-provenance` carries runs/seed and the
  "projected, not real" honesty copy). A completed run must appear in-session
  (sim tab re-renders after `simMeta` commit) and refreshes must never wipe
  it. Competition outcome widgets are slots inside this order (WC: example
  simulated bracket; UCL: aggregate knockout/playoff table; LaLiga: champion
  bars + what-if).

## Shared simulation shell (Phase 12D addendum)

The Simulation tab is built by ONE shared presentation shell in
`shared.js`: `renderSimulationShell(state, opts)` emits the canonical
layout and `bindSimulationShell(state, opts)` wires the launcher to the
single shared `showSimPopup`. Competition modules contribute only *content
slots*; structure and state semantics live in the shell.

- **Canonical order** (shell-enforced, modules cannot reorder): title +
  purpose → current-state line → launcher (`#simLaunchBtn`, via the shared
  popup) → run/progress line → PRIMARY result slot → What-If → provenance
  footer (`.sim-provenance`, shared; `.sim-provenance.failed` for failures).
- **State contract** (`shared.js` reads `availability` / `request_state`
  from each competition's `/api/data` `simulation` block): five states —
  IDLE (no run asked yet), RUNNING (launcher disabled, prior results stay
  visible), COMPLETE (result slot + what-if + provenance), NOT_NEEDED
  (season decided: no launcher, decided-fact block, prior run preserved),
  FAILED (`.sim-provenance.failed`, never fabricated numbers).
- **State machine is implemented once**, in `renderSimulationShell`; each
  competition passes its raw `availability`/`request_state` plus opts and
  the shell owns branching, defaulting, provenance and empty/failed
  handling.
- **What-If**: LaLiga has exactly ONE in-tab whole-competition counterfactual
  panel (`/what-if`, 10k iterations, elo delta) rendered as the shell's
  what-if slot on available seasons; the duplicated modal What-If was
  removed. UCL/WC keep per-match What-If shortcuts inside match modals and
  do not render a whole-competition what-if slot.
- **Live-refresh isolation is now uniform**: `laliga.js:refreshLive`
  refetches `/api/data` only (the previous /simulation re-fetch + re-apply
  was removed), matching UCL/WC. A completed sim result survives refresh and
  the LaLiga sim tab re-renders from held state, never from a fresh
  simulation fetch.