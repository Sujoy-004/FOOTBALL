# Phase 3: Live API Integration — Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

System fetches live match results from Football-Data.org API, maps API responses to internal bracket matches via team-name matching, normalizes team names using aliases, and handles failures with retry logic and cached-data fallback. Fetcher never crashes the main loop.

Requirements: DATA-01, DATA-03

**Already decided (carried forward from Phase 1):**
- Dynamic team-name matching primary, `api_id_mapping.json` fallback (D-08)
- `api_id_mapping.json` is a Phase 3 concern (D-09) — not implementing per D-01 below
- Fallback flow: try dynamic → if ambiguous, consult api_id_mapping.json → error (D-10)
- `team_aliases.json` created in Phase 1 as reference file (D-12)
- Team name normalization belongs in Phase 3 (D-13) — implemented per D-10 below
- Known name ambiguities: USA/United States, Korea Republic/South Korea, IR Iran/Iran (D-14)

</domain>

<decisions>
## Implementation Decisions

### API-to-Bracket Matching
- **D-01:** Team-name matching only — no api_id_mapping.json for MVP. Match by comparing both API team names to bracket team names using aliases. Avoids manual mapping and maintenance burden.
- **D-02:** Match by both team names — identify the bracket match where both API team names match via alias resolution. Deterministic since knockout slots have unique team pairs.
- **D-03:** Unmatchable matches (unknown team names, group stage matches) — log a clear warning with raw API data for manual inspection, then skip. System continues operating without crashing.

### Module Responsibility Split
- **D-04:** Single `src/fetcher.py` module handling both HTTP fetching and match processing (~150 lines). No separate matcher module.
- **D-05:** Two public functions exported:
  - `fetch_raw_matches(api_key) -> list[dict]` — HTTP GET with retry, returns raw API response dicts
  - `process_matches(raw_matches, teams, bracket, aliases, played_ids) -> list[dict]` — alias resolution, bracket matching, filtering against played set
  Separating HTTP concerns from data processing makes each individually testable.
- **D-06:** process_matches returns full match records: `{'match_id': str, 'team_a': str, 'team_b': str, 'winner': str, 'home_score': int, 'away_score': int, 'completed_at': str}` — ready to pass directly to `elo.update_ratings()` and `state.save_played()`.

### Testing Approach
- **D-07:** Monkeypatch `requests.get` using pytest's `monkeypatch` fixture — zero additional test dependencies. Follows existing pure-pytest pattern.
- **D-08:** Single `test_fetcher.py` file following existing test patterns (`test_elo.py`, `test_state.py`). Covers: successful fetch, empty response, API timeout (retries), malformed JSON, unmatchable team names, partially played bracket.
- **D-09:** Minimal JSON dict fixtures — matching only the fields consumed by fetcher.py (`id`, `homeTeam.name`, `awayTeam.name`, `score.fullTime`, `status`). Not full API responses.

### Team Name Normalization
- **D-10:** Case-insensitive alias lookup using `team_aliases.json`. Algorithm: lowercase both sides + strip whitespace + alias dict lookup. No fuzzy matching — false positives on partial matches (e.g., "Korea" matching "North Korea") are worse than no match.
- **D-11:** Normalization logic lives as private function(s) inside `fetcher.py`. Extract to separate module only if reused elsewhere in the future.
- **D-12:** `team_aliases.json` loaded by `main.py` via `state.py` and passed as explicit parameter to `process_matches()`. No hidden file I/O in fetcher.py — explicit dependency, more testable, consistent with existing architecture.

### Failure Handling and API Outages
- **D-13:** General API failure strategy: retry 3x with exponential backoff (1s, 2s, 4s). If all retries fail: log warning, use last cached data (existing `played.json`), continue main loop. Never crashes on API failure.
- **D-14:** HTTP 429 (rate limited): parse `Retry-After` header if available; otherwise wait 60s before first retry. Same 3-try limit applies. 429 is a signaling mechanism — respect it differently from transient network errors.
- **D-15:** Data-level errors (malformed JSON, unmatchable team names, unmappable matches): log warning with raw data, skip that specific match or response, continue processing. One bad match does not discard good matches from the same response.
- **D-16:** API key validated on startup — make a test API call when `main.py` starts. If `FOOTBALL_API_KEY` missing or 403 received, print clear error and exit 1. Fail fast for configuration issues, not on every poll.
- **D-17:** HTTP timeout configured in `constants.py` as `API_TIMEOUT` (planned value: 10s). Matches existing pattern (`K_FACTOR`, `POLL_INTERVAL`). Easy to adjust without editing fetcher.py.

### Agent's Discretion
- Retry backoff implementation details (sleep between retries, error classification)
- Exact console log format for match detection, retry attempts, and warnings
- Internal function naming within fetcher.py
- JSON key mapping from API response shape to internal field names

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/ROADMAP.md` — Phase 3 goal: "System fetches live match results from Football-Data.org API with robust error handling"
- `.planning/REQUIREMENTS.md` — DATA-01 (fetch live matches), DATA-03 (retry + fallback)

### Phase 1 Decisions (carried forward)
- `.planning/phases/01-state-elo-foundation/01-CONTEXT.md` — D-08 (dynamic matching), D-09 (api_id_mapping.json is Phase 3), D-10 (fallback flow), D-12 (team_aliases.json), D-13 (normalization in Phase 3), D-14 (known ambiguities)

### Technical Specifications
- `SOTs/TRD.md` §5.1 — Fetcher module specification (fetch_new_results, retry logic, MatchResult schema)
- `SOTs/TRD.md` §6 — API contract (endpoint, headers, response format)
- `SOTs/PRD.md` §6 — Functional requirements FR1–FR7 (fetching, detection, Elo update, fallback)

### Codebase Architecture
- `.planning/codebase/INTEGRATIONS.md` — API details, auth (X-Auth-Token), rate limits (10 req/min), error handling, environment config
- `.planning/codebase/ARCHITECTURE.md` — Module boundaries, data flow (API → Fetcher → State → Elo → Sim → Output)
- `.planning/codebase/STACK.md` — Python 3.10+, requests library, no other deps

### Existing Data Files
- `worldcup_predictor/data/team_aliases.json` — Alias mapping (USA/United States, Iran/IR Iran, Korea Republic/South Korea, etc.)
- `worldcup_predictor/src/constants.py` — Constants pattern (K_FACTOR, DATA_DIR, etc.) — add API_TIMEOUT here
- `worldcup_predictor/src/state.py` — load/save patterns, load_aliases to be added
- `worldcup_predictor/src/elo.py` — update_ratings() consumes new match records from fetcher

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `state.py` load/save functions — existing JSON persistence pattern; add `load_aliases()` for team_aliases.json
- `constants.py` — constants pattern; `API_TIMEOUT` and `API_URL` to be added
- `elo.update_ratings()` — consumes match records with shape `(team_a, team_b, winner, elos)` — fetcher output matches this interface
- `conftest.py` — existing pytest fixtures for test setup

### Established Patterns
- Pure functional style — no classes, dict/list data structures, explicit parameters
- Module pattern: single-purpose, no inter-dependencies between src/ modules
- main.py as dependency injector — loads state, passes to modules
- pytest + monkeypatch for mocking — no external mock libraries

### Integration Points
- `main.py` — fetcher hooks in after state loading, before simulation call
- `data/team_aliases.json` — reference file created in Phase 1, consumed by fetcher
- `data/played.json` — played match set used to filter already-processed API matches
- `data/bracket.json` — bracket matches used to match API responses to bracket slots

</code_context>

<specifics>
## Specific Ideas

- "Test only what you consume" — minimal JSON fixtures matching only the fields fetcher.py actually reads
- "One bad match should not discard good matches" — per-match skip granularity, not per-response
- "Visible failure, no crash, easy debugging" — log warnings with raw data for manual inspection
- "Explicit dependency, more testable" — pass aliases dict as parameter, not import-time file read
- "429 is different from a network error" — respect Retry-After header, longer backoff

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 3-Live API Integration*
*Context gathered: 2026-06-13*
