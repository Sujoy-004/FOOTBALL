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

## Refresh semantics

- Generation-token discipline: `loadAll` is the *only* incrementer of
  `_transitionGen`. `refreshLive` captures the current token, fetches, and
  checks `_stale(gen)` before each commit — so a live refresh can never
  commit over a newer full load, and a competition switch discards it.
- A refresh and a full load may both commit if they share the same token;
  both fetched the same server state and the later write wins, which is
  harmless.
- `refreshLive` never touches simulation state: UCL keeps its sim session
  payload, WC keeps `simBracket`/the simulation overlay, and neither
  touches the shared simulation popup. A running simulation's progress is
  owned by the popup, so unrelated live refresh does not disturb it.

## Cache semantics

- `no-store` is applied to *all* competition API responses, including the
  idempotent simulation reads — a re-fetch never recomputes server state
  and never mutates the simulation cache, so reapplying the policy there is
  safe and keeps request/render ordering truthful for the user.
- Root cause it closes (Phase 9B): an open tab across a server-side refresh
  must not replay a stale cached JSON payload.