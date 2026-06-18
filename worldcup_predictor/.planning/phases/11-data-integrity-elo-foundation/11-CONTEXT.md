# Phase 11: Data Integrity & Elo Foundation — Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the Elo foundation — correct all 48 Elo ratings to match eloratings.net (the canonical source), apply missing updates from early tournament matches, and implement auto-sync so Elo values self-heal without manual entry for the rest of the tournament.

Assumptions supporting these decisions were proved via literature review beforehand — see worldcup_predictor/MODERNIZATION-PROPOSAL.md §1–4 for the full audit evidence.

</domain>

<decisions>
## Implementation Decisions

### Sync Interval
- **D-01:** Sync on startup (always, immediate fetch from eloratings.net)
- **D-02:** Incremental sync every 24 hours thereafter
- **D-03:** If last sync was > 36 hours ago (e.g., laptop wake from sleep), catch up immediately — do not wait for next 24h window
- **D-04:** Never sync on every poll cycle (60s). The daily cadence is sufficient for a sanity-check correction signal

### HTML Parsing Strategy
- **D-05:** Separate fetch from parse — `fetch_eloratings_html()` does network I/O, `parse_eloratings_table(html)` does pure parsing with no network dependency
- **D-06:** Use stdlib `html.parser` (not BeautifulSoup) — eloratings.net's table is clean and predictable; avoids adding a dependency to the project
- **D-07:** Save a snapshot of current eloratings.net HTML as a test fixture — parsing must be testable without network access
- **D-08:** Add a schema validation step after parsing — verify all 48+ teams present, ratings in expected range (1000–2500), no negative or NaN values
- **D-09:** eloratings.net is the sole source of truth for canonical Elo. Not FIFA rankings, not teams.json.

### Dynamic Elo Interaction
- **D-10:** Hybrid approach — dynamic Elo updates from BSD match results remain primary during tournament; auto-sync is a correction signal, not a replacement
- **D-11:** Graduated correction thresholds:
  - **< 10 pt drift:** Ignore — expected noise from different Elo formulae (K-factors, draw handling, goal-diff multiplier differ between our system and eloratings.net)
  - **10–30 pt drift:** Blend 50% toward eloratings value — dampened correction
  - **> 30 pt drift:** Overwrite and FLAG for investigation — possible bug in dynamic Elo logic
- **D-12:** Every drift detection and correction is logged to `elo_update_log.json` with timestamp, team, old value, new value, source, reason, and drift magnitude
- **D-13:** Hard overwrite (full replacement) is NOT used — it would create audit noise from systematic differences between two Elo systems that are both correct for their own formula

### Caching & Fallback
- **D-14:** Maintain a last-known-good cache of eloratings.net values (in-memory + persisted JSON)
- **D-15:** If eloratings.net is unreachable, continue operation with cached values — never block prediction because a third-party website is down
- **D-16:** Graduated staleness warnings:
  - 24h: no signal (green)
  - 48h: LOG informational (systemic, not user-visible)
  - 72h: ⚠ yellow warning in health output
  - 7 days: 🚨 red critical warning (still does not block)
- **D-17:** On network failure, retry 3 times with exponential backoff (1s, 2s, 4s) before falling back to cache

### Startup Validation
- **D-18:** Auto-sync on startup — always fetch fresh Elo values before the first simulation
- **D-19:** If auto-sync fails and cache exists, warn and continue with cache — never block
- **D-20:** If auto-sync fails and NO cache exists (first-ever run), warn with clear message and continue with teams.json initial values. D-22 takes precedence — never block the prediction loop.
- **D-21:** Partial sync rule — if sync succeeds for 40/48 teams and fails for 8 (e.g., renamed teams), apply what you can, log WARNING for unmapped teams, continue
- **D-22:** Startup must not block or degrade the main prediction loop for any reason related to Elo data source availability

### the agent's Discretion
- Parser implementation details (regex patterns, HTML element selection) — agent may choose the most robust approach within stdlib `html.parser`
- Test fixture format (full HTML snapshot vs. simplified table) — agent may choose for testability

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Proposal
- `worldcup_predictor/MODERNIZATION-PROPOSAL.md` — Full modernization architecture, signal inventory, Elo replacement strategy, ROI analysis, GSD phase definitions. Section 4 (Elo Replacement Strategy) is the primary reference for this phase.

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 11 definition: V2-01 and V2-02 requirements, success criteria, dependencies
- `.planning/REQUIREMENTS.md` — All requirements including V2-01 (Elo ratings match eloratings.net within 5pts) and V2-02 (auto-sync every N minutes)

### Codebase
- `.planning/codebase/INTEGRATIONS.md` — Existing API integration patterns, team alias mapping, caching patterns
- `.planning/codebase/CONCERNS.md` — Known concerns about team name normalization, team_aliases.json fragility
- `.planning/codebase/ARCHITECTURE.md` — System architecture for integration points

### Proof-of-Assumptions Research
- Session evidence (prior conversation): eloratings.net source-of-truth justification, CatBoost predictive value benchmarks, expected Brier improvements — all documented inline in the session preceding this context

### External Source (for reference, not checked in)
- `https://www.eloratings.net/` — Live Elo ratings; source of truth for canonical values. No official API — HTML parsing required.
- `https://www.international-football.net/elo-ratings-table` — Structured mirror, potential secondary source if eloratings.net HTML changes

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/state.py` — `save_teams()`, `load_teams()` — existing persistence patterns for teams.json; auto-sync will write through these functions
- `data/team_aliases.json` — 48-entry alias mapping; inverse lookup needed for eloratings.net → canonical name mapping
- `src/fetcher.py` — Existing API fetch patterns (requests with retry, exponential backoff, error handling); auto-sync fetcher should follow same patterns
- `src/constants.py` — Centralized constants; add `ELO_SYNC_INTERVAL_HOURS`, `ELO_SYNC_TOLERANCE`, `ELORATINGS_URL` here

### Established Patterns
- Atomic JSON writes (write to temp, rename) — must be used for elo_update_log.json and any cache file
- Environment variable auth (`BSD_API_KEY`) — eloratings.net is public (no auth needed), but pattern documented
- Retry with exponential backoff (1s, 2s, 4s) — defined in fetcher.py, should be reused
- Test fixture pattern — existing test fixtures in `tests/` for JSON data; HTML fixtures for parser tests follow same pattern

### Integration Points
- `src/state.py` — Auto-sync writes to teams dict (in-memory) and teams.json (persisted)
- `src/main.py` — Startup validation hook; health monitoring for staleness display
- `src/elo.py` — Expected_score and update_ratings functions remain unchanged; auto-sync is a data-layer operation, not an Elo algorithm change

</code_context>

<specifics>
## Specific Ideas

- The drift-logged-and-blended approach (D-10 through D-13) is a deliberate design choice to handle the fact that our dynamic Elo and eloratings.net use different formulae (K-factors, draw handling, goal-diff multiplier). Both are "correct" for their own system. The graduated threshold prevents audit noise from these systematic differences.
- eloratings.net name variations already mapped in team_aliases.json, but may need expansion (e.g., "Korea Republic" → "South Korea", "Côte d'Ivoire" → "Ivory Coast")

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 11-Data Integrity & Elo Foundation*
*Context gathered: 2026-06-15*
