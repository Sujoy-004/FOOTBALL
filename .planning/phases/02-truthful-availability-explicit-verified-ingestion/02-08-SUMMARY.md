---
phase: 02-truthful-availability-explicit-verified-ingestion
plan: 08
subsystem: ui
tags: [availability, banner, refresh, ingest, ui, accessibility, xss, shared-helpers]

# Dependency graph
requires:
  - phase: 02-truthful-availability-explicit-verified-ingestion
    provides: 02-05 freshness ledger (refresh block: provider/stale/last_success_at), 02-06 explicit POST /{comp}/api/refresh endpoints serving IngestReport, 02-07 four-state availability map + per-store availability_reason on all three payloads
provides:
  - Shared DOM-free render helpers in web/static/shared.js — renderAvailabilityBanner (C2), renderAvailPanel (C3), refreshButtonHtml (C1), acq-caption row in renderAcquisitionPanel (C4)
  - Matching CSS (.refresh-btn/.avail-banner/.avail-panel/.avail-head/.avail-body/.avail-meta/.acq-caption) + WC overrides + <=800px single-column status-bar rule
  - Single click-to-refresh ingest wiring across worldcup/ucl/laliga using one delegated handler; in-flight states + no page reload
  - Notice parity: SNAPSHOT/STALE/DEFERRED/LIVE/failed vocabulary unified across all three apps (legacy strings verbatim)
  - Node test coverage in web/static/refresh.test.mjs for copy verbatim, XSS escaping, ARIA, caption, I6 predicate
affects:
  - Any future dashboard surface that renders availability or triggers ingestion (reuse the shared helpers rather than re-implementing C1-C4)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DOM-free string-builder helpers in shared.js so render logic is node-testable without a browser; the three competition files do the wiring"
    - "renderAvailPanel REPLACES the results table (never overlays) for empty/missing/unavailable stores — I6 non-zeros contract"
    - "Every dynamic server string passes _esc() before innerHTML (T-08-X mitigation)"
    - "Availability blocking is scoped per-view: only the stores a given table actually depends on may replace it"

key-files:
  created:
    - web/static/refresh.test.mjs (extended with shared.js helper tests under a document/window stub)
  modified:
    - web/static/shared.js
    - web/static/shared.css
    - web/static/wc.js
    - web/static/ucl.js
    - web/static/laliga.js

key-decisions:
  - "C1-C4 live as four DOM-free exported helpers in shared.js (string builders only) and are unit-tested in Node; the per-competition files own the DOM wiring and click handler"
  - "The Refresh results button is the ONLY ingest trigger in the UI (D-03/I5) — no fetch on load, tab switch, or poll path; verified by grep gate"
  - "renderAvailPanel replaces the table node entirely rather than overlaying it, so no zeros or empty table can ever be shown for empty/missing/unavailable stores (TRUTH-01/I6)"
  - "Legacy SNAPSHOT/STALE/DEFERRED wording moved verbatim from ucl.js into the shared banner helper so all three apps render identical notices"
  - "UCL league-phase availability blocking must be scoped to the stores each view depends on — knockout_results.json is legitimately absent during the league phase and must never block the standings table"

patterns-established:
  - "Shared truthful-availability UI: one banner + one blocking panel helper consumed identically by WC/UCL/LaLiga"
  - "Per-view store-scoped availability blocking (a view blocks only on the stores it actually reads)"

requirements-completed:
  - TRUTH-01
  - TRUTH-03
  - INGEST-01
  - INGEST-02

# Metrics
duration: ~80min active (~12h15m wall clock incl. overnight pause + human checkpoint)
completed: 2026-10-09
---

# Phase 02: Truthful Availability & Explicit Verified Ingestion — Plan 08 Summary

**Shared truthful-availability UI across World Cup, UCL, and LaLiga: one-click Refresh results wired to POST /api/refresh with in-flight/no-reload states, a status-bar banner, a blocking "No data yet" panel that replaces (never overlays) unhealthy tables, and an acquisition-panel counter caption — with verbatim binding copy and _esc()-guarded dynamic strings.**

## Performance

- **Duration:** ~80 min active engineering; ~12h15m wall-clock span (includes an overnight pause and the blocking human-verify checkpoint)
- **Started:** 2026-10-08T13:57:03Z (approx — task 1 commit time)
- **Completed:** 2026-10-09T02:12:15Z (deviation-fix commit) / human-approved 2026-10-09
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint, approved)
- **Files modified:** 6 (5 code + 1 test)

## Accomplishments

- Shared.js gained four DOM-free render helpers — `renderAvailabilityBanner` (C2), `renderAvailPanel` (C3, blocking), `refreshButtonHtml` (C1), and the C4 counter caption inside `renderAcquisitionPanel` — each a pure string builder so render logic is unit-testable in Node.
- All three competition files (`wc.js`, `ucl.js`, `laliga.js`) wire a single delegated click handler on `.refresh-btn` that POSTs `/{comp}/api/refresh`, shows `Refreshing…`/disabled/`aria-busy`, renders the returned IngestReport into the acquisition panel, and returns the button to idle — with NO page reload (I1-I4).
- I6 placeholder swap: when a store is empty/missing/unavailable the results table node is replaced by the `.avail-panel` carrying the binding copy (BODY_MISSING/EMPTY/UNAVAIL), provider/reason/timestamp metadata, and `role="status"` — never zeros, never an empty table.
- Notice parity achieved: the three legacy SNAPSHOT/STALE/DEFERRED strings now live once in `shared.js` and are rendered byte-identically by WC/UCL/LaLiga, alongside the new LIVE/success/failed/refreshing vocabulary.
- CSS tokens added for all new classes with WC overrides and the <=800px single-column status-bar rule; no existing selector restyled.
- `refresh.test.mjs` extended with Node tests for CTA copy, D-04 verbatim copy, XSS escaping (`<img onerror>`), `role="status"`/`aria-live="polite"`, caption presence-only, legacy-wording byte-identity, and the I6 predicate.

## task Commits

Each task was committed atomically:

1. **task 1: shared availability banner, panel, refresh button, caption** — `e4ff688` (feat)
2. **task 2: wire refresh button, banner, placeholder across competitions** — `b9a5582` (feat)
3. **task 3: human visual + interaction verification** — no code commit (checkpoint, approved by user)
4. **deviation auto-fix: scope UCL standings blocking to league_results** — `ce70bc1` (fix) — see Deviations below

**Plan metadata commit:** `docs(02-08): add plan summary` (this SUMMARY only)

_Note: task 3 was a `checkpoint:human-verify` gate (`autonomous: false`), not an atomic code change; it produced no commit._

## Files Created/Modified

- `web/static/shared.js` — four exported DOM-free helpers: `renderAvailabilityBanner` (all banner states, legacy strings verbatim), `renderAvailPanel` (blocking panel, `_esc()`-guarded substitutions), `refreshButtonHtml` (idle/in-flight), and the `.acq-caption` row appended by `renderAcquisitionPanel` (renders only when counters exist)
- `web/static/shared.css` — `.refresh-btn`, `.avail-banner`, `.avail-panel`/`.avail-head`/`.avail-body`/`.avail-meta`, `.acq-caption`; `.competition-worldcup` overrides; `@media (max-width: 800px)` single-column status bar
- `web/static/wc.js` — C1 button + banner via `updateStatusBar`, delegated refresh handler, I6 table→panel swap, notice parity
- `web/static/ucl.js` — same wiring; local SNAPSHOT/STALE/DEFERRED literals deleted in favor of the shared helper; `_blockingAvailability(keys)` parameterized so the league table blocks only on `league_results`
- `web/static/laliga.js` — same wiring + notice parity
- `web/static/refresh.test.mjs` — document/window stub before `await import("./shared.js")` plus helper tests (21 tests total, all passing)

## Decisions Made

See key-decisions frontmatter: DOM-free shared helpers (node-testable), C1 as the sole ingest trigger (D-03/I5), panel-replaces-table (no zeros/empty table), verbatim notice parity, and per-view store-scoped UCL blocking (the deviation fix).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 – Bug / correctness] UCL standings table was wrongly replaced by the availability panel during the league phase**
- **Found during:** task 2 wiring (surfaced by the human-verify checkpoint)
- **Issue:** `_blockingAvailability` looped `["league_results", "knockout_results"]` at `web/static/ucl.js:268`. `knockout_results.json` is legitimately absent during the UCL league phase, so `load_json_store` correctly reports it `missing` — the standings view was then replaced by the "No data yet" blocking panel even though `league_results` was healthy. This asserted unavailability for a store the view does not depend on.
- **Fix:** parameterized `_blockingAvailability(keys)` (per-view store scoping) and changed the standings call site (`web/static/ucl.js:697`) to pass `["league_results"]`. Added an explanatory comment at `:264-267` documenting that knockout_results is legitimately absent in the league phase and must never block standings.
- **Files modified:** `web/static/ucl.js`
- **Verification:** `node --check web/static/ucl.js` clean (exit 0); `node --test web/static/refresh.test.mjs` 21/21 pass, 0 fail; human-visual re-verification approved.
- **Committed in:** `ce70bc1` (fix, standalone deviation commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — correctness/blocking)
**Impact on plan:** The fix restores correct I6 behavior for the UCL league phase (block only on the stores a view actually reads). No scope creep; it satisfies the plan's TRUTH-01/I6 intent and the D-12 truth rule that an absent store must not be treated as a view-blocking error.

## Issues Encountered

- `python -m pytest tests/test_truth_payloads.py -q` fails due to a **pre-existing UCL data state unrelated to 02-08** (root `results.json` absent / data moved to `seasons/2026_27/`; the same class of failures documented as baseline in `02-07-SUMMARY.md`). Not caused by this plan's changes.
- Browser-only checkpoint steps 5–7 could not be self-verified in this runtime — no browser / Chrome DevTools MCP was available to exercise the `played.json`→`.bak` rename, the <=800px responsive layout, or the devtools accessibility tree (`role=status`). The user visually approved the checkpoint instead of these being machine-verified here.
- No new full-suite regressions introduced: this plan touches only `web/static/*` JS/CSS + the Node test file, none of which are collected by pytest.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The dashboard now exposes the Phase-2 interaction contract end-to-end: banner (C2), blocking panel (C3), refresh button (C1), and counter caption (C4) all consume the truthful availability/report payloads from 02-05/06/07.
- Remaining Phase 02 plans (02-09, 02-10) can wire the refresh endpoint's `written_files`/lifecycle surface (noted as 02-06's deferred wire-up owner) without touching the shared helpers.
- `availability_reason` and the `refresh` block are the only inputs the helpers need — no new server contract is required by this plan.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-08-X mitigated | web/static/shared.js | Server report strings (provider/reason/timestamp) rendered to innerHTML pass `_esc()`; Node test injects `<img onerror>` and asserts escaping |
| T-08-E mitigated | web/static/{wc,ucl,laliga}.js | Grep gate confirms `/api/refresh` appears only in the click handler — no load/tab/poll ingest (D-03/I5) |

## Self-Check

PASSED — Commits `e4ff688`, `b9a5582`, `ce70bc1` present in `git log`; `web/static/refresh.test.mjs` runs 21/21 pass / 0 fail; `node --check web/static/ucl.js` exits 0; modified files `shared.js`, `shared.css`, `wc.js`, `ucl.js`, `laliga.js`, `refresh.test.mjs` all exist; human-verify checkpoint (task 3) approved by the user.

---

*Phase: 02-truthful-availability-explicit-verified-ingestion*
*Completed: 2026-10-09*
