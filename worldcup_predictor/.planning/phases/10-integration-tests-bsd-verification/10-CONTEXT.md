# Phase 10: Integration, Tests & BSD Verification - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 10 delivers the final integration layer: BSD API group match ingestion, `played_groups.json` persistence, console group standings display with third-place bubble indicator, updated E2E test fixtures, and batch SOT updates. Phase 10 does NOT modify `src/groups.py` or `src/knockout.py` simulation logic — integration only.

Requirement scope: INTG-01 through INTG-10 from `.planning/REQUIREMENTS.md`.

</domain>

<decisions>
## Implementation Decisions

### Group Match Ingestion (INTG-01)
- **D-01:** Single BSD API call `GET /api/events/?status=finished&league_id=27` returns all WC matches. Split routing post-fetch:
  - `group_name` is non-null → `process_group_matches()` (new function)
  - `group_name` is null → `process_matches()` (existing knockout flow)
- **D-02:** Match → group letter: extract from `group_name` field directly (`"Group A"` → `"A"`). No team inference.
- **D-03:** Match → group match slot: resolve using three-key composite: **`group_name` + `round_number` + normalized team pair**. This is preferred over team pair alone to handle edge cases where the same team pair could appear in different rounds (e.g., replay scenario is not possible in group stage, but round_number provides unambiguous slot resolution).
- **D-04:** `played_groups.json` entry structure:
  ```json
  {
    "GS_A_01": {
      "match_id": "GS_A_01",
      "team_a": "Mexico",
      "team_b": "South Africa",
      "winner": "Mexico",
      "home_score": 2,
      "away_score": 1,
      "completed_at": "2026-06-14T17:00:00Z"
    }
  }
  ```
- **D-05:** Dedup tracking via BSD event `id` (not match_id) — prevents re-ingesting the same BSD event on subsequent polls even if match_id mapping is identical.
- **D-06:** Failure handling:
  - Unmatchable team names (alias lookup fails) → log warning, skip match
  - Team pair + round_number not found in any group match slot → log warning, skip match
  - group_name not a valid A-L → log warning, skip match
  - Draw match (no winner) → skip (aligns with knockout behavior)
- **D-07:** `run_full_simulation()` accepts new `played_groups` param alongside existing `played`. `simulate_group_matches()` skips matches present in either.

### played_groups.json Persistence (INTG-02)
- **D-08:** New load/save functions in `state.py`: `load_played_groups()`, `save_played_groups()`. Follow same atomic write pattern as `save_played()`.
- **D-09:** Initial `played_groups.json` created empty `{}` if not present (graceful bootstrap).

### Group Standings Console Display (INTG-03, INTG-04, INTG-05)
- **D-10:** Show ALL 12 groups every display cycle (not only on change).
- **D-11:** Columns: Position, Team, Pts, GD, GS. Do NOT expose fair-play/conduct_score or Elo values in normal output.
- **D-12:** Use box-drawing characters (`│ ─ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼`) for group table borders.
- **D-13:** Compact 4-line block per group, 12 groups stacked vertically with horizontal separators.
- **D-14:** Third-place bubble: show 8th and 9th teams plus the deciding metric.
  - Format: `8. Ghana  3 pts  GD +0  ADVANCES  9. Panama  3 pts  GD -2  OUT  Cutoff margin: GD = 2`
  - Rank all 12 third-placed teams by Pts → GD → GS, highlight the 8th/9th cutoff.
- **D-15:** Refresh behavior:
  - New group match ingested → re-print full standings block
  - Hourly auto-refresh → re-print full standings block
  - Regular heartbeat (no new matches) → skip
  - First startup with 0 played groups → show placeholder: `(no group matches played yet)`

### FIFA Ranking (D-16 from Phase 8)
- **D-16:** Keep Elo proxy. Do NOT introduce a FIFA ranking data source in Phase 10. D-16 is closed.
- **D-17:** Document limitation in `STATE.md` and `FEATURES.md` that tiebreaker Step 7 uses Elo-as-FIFA-ranking-proxy with `~0.92` correlation.

### Code Architecture
- **D-18:** New functions in `output.py`: `print_group_standings(standings, third_place_rankings)`, `print_third_place_bubble(third_place_rankings)`.
- **D-19:** New function in `fetcher.py`: `process_group_matches(raw_matches, teams, groups, aliases, played_group_ids, played_bsd_event_ids)`.
- **D-20:** `main.py` `_run_iteration()`: load `played_groups`, pass to `run_full_simulation()`, call `print_group_standings()` in output sequence.
- **D-21:** `knockout.py` `run_full_simulation()`: forward `played_groups` to `simulate_group_matches()`.

### Test Fixes (INTG-09)
- **D-22:** `test_main_loop_runs_iterations`: change assertion from `"Fetched"` to `"Polling"` (cosmetic rename).
- **D-23:** `test_expected_goals_very_strong_dominates`: update assertion from `> 10.0` to `== 8.0` and add comment documenting `MAX_EXPECTED_GOALS=8.0` cap rationale.

### E2E Tests (INTG-06, INTG-07)
- **D-24:** New `test_group_integration.py` covering:
  - `process_group_matches()` with mock BSD response containing group matches
  - `played_groups.json` roundtrip (save → load → verify)
  - `compute_standings()` output matches group standings table format
  - Full pipeline with mock: API returns group matches → process → sim → standings match expected
  - Third-place bubble calculation

### SOT Batch Update (INTG-10)
- **D-25:** Update all 7 SOTs in one batch at end of Phase 10:
  - `PROJECT.md` — mark all INTG reqs `[x]`, Phase 10 complete
  - `REQUIREMENTS.md` — update traceability, mark all complete
  - `STATE.md` — Phase 10 entry, mark v1.1 complete
  - `ROADMAP.md` — Phase 10 success criteria, mark complete
  - `ARCHITECTURE.md` — add group match ingestion and output module docs
  - `FEATURES.md` — update for live integration features
  - `codebase/INTEGRATIONS.md` — replace Football-Data.org refs with BSD

### the agent's Discretion
- Exact box-drawing character set for group standings table (e.g., single vs double lines)
- Whether `process_group_matches()` lives in `fetcher.py` or a new `src/groups_fetcher.py` module (prefer `fetcher.py` unless it exceeds reasonable size)
- Exact ANSI color codes for third-place bubble (ADVANCES green, OUT red)
- Whether `played_bsd_event_ids` dedup is persisted across restarts (likely not needed — already-played match_ids in `played_groups` provide dedup on reload)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/REQUIREMENTS.md` — INTG-01 through INTG-10 requirements with acceptance criteria

### Architecture & Design
- `.planning/codebase/INTEGRATIONS.md` — BSD API integration patterns, pagination, auth (needs Football-Data.org → BSD update in this phase)
- `.planning/research/ARCHITECTURE.md` — Full pipeline architecture, output module design
- `RESPONSE.md` (section "Phase 10 Architecture Proposals") — Approved architecture with user refinements

### Data Files
- `worldcup_predictor/data/groups.json` — 12 groups with match slots (GS_A_01 through GS_L_06)
- `worldcup_predictor/data/teams.json` — 48 teams with Elo ratings
- `worldcup_predictor/data/team_aliases.json` — Canonical → alias mapping

### Code to Reference
- `worldcup_predictor/src/fetcher.py` — `process_matches()` (pattern to follow for `process_group_matches()`)
- `worldcup_predictor/src/state.py` — `load_played()` / `save_played()` pattern (replicate for played_groups)
- `worldcup_predictor/src/output.py` — Console display patterns, ANSI codes, `print_probability_table()`
- `worldcup_predictor/src/groups.py` — `compute_standings()` (data source for display)
- `worldcup_predictor/src/knockout.py` — `run_full_simulation()` (add `played_groups` param)
- `worldcup_predictor/main.py` — `_run_iteration()` (integration point)
- `worldcup_predictor/src/constants.py` — `API_URL`, `POLL_INTERVAL`, `GROUP_COUNT`
- `worldcup_predictor/tests/test_fetcher.py` — Test patterns for API mocks
- `worldcup_predictor/tests/test_main_loop.py` — `test_main_loop_runs_iterations` (D-22 fix target)
- `worldcup_predictor/tests/test_groups.py` — `TestExpectedGoals.test_expected_goals_very_strong_dominates` (D-23 fix target)

### Prior Context
- `.planning/phases/08-group-stage-simulation-engine/08-CONTEXT.md` — D-16 (FIFA ranking proxy, now closed)
- `.planning/phases/09-knockout-bracket-annex-c-routing/09-CONTEXT.md` — Prior phase decisions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`_build_alias_lookup()`** in `fetcher.py:129` — team alias normalization, directly reusable for group match processing
- **`_normalize_team()`** in `fetcher.py:146` — team name normalization, directly reusable
- **`_find_bracket_match()`** in `fetcher.py:150` — pattern to replicate for group match slot finding
- **`_atomic_write_json()`** in `state.py:98` — atomic file write pattern, reusable for `save_played_groups()`
- **`compute_standings()`** in `groups.py:534` — produces the standings data dict consumed by group display
- **`_tiebreak_group()`** in `groups.py` — third-place ranking already computed by groups engine, display just picks position 3 entries

### Established Patterns
- **Load→Validate→Return** — All state loaders follow this pattern
- **MockResponse class** in `test_fetcher.py:11` — test patching pattern to replicate for group match tests
- **`_runner_code()` pattern** in `test_main_loop.py:14` — inline Python mock for full pipeline tests
- **Sequential validation with ValueError** — All validators raise descriptive ValueError on first failure

### Integration Points
- `main.py` `_run_iteration()` (line 82) — add `played_groups` to params, call `load_played_groups()`, pass to `run_full_simulation()`
- `main.py` `main()` (line 189) — add `played_groups = state.load_played_groups()` alongside other data loads
- `knockout.py` `run_full_simulation()` — accept `played_groups` param, forward to `simulate_group_matches()`
- `output.py` — add `print_group_standings()` and `print_third_place_bubble()` called from `main.py`
- BSD API: `GET /api/events/?status=finished&league_id=27` — single call, paginated response, fields: `id`, `status`, `home_team`, `away_team`, `home_score`, `away_score`, `event_date`, `group_name`, `round_number`, `round_name`

</code_context>

<specifics>
## Specific Ideas

- Third-place bubble format approved with this specific layout:
  ```
  8. Ghana  3 pts  GD +0  ADVANCES
  9. Panama  3 pts  GD -2  OUT
  Cutoff margin: GD = 2
  ```
- Box-drawing table is preferred over plain ASCII for readability
- All 12 groups shown each cycle, not just changed groups
- Fair-play and Elo values deliberately hidden from normal output (only Pts, GD, GS shown)

</specifics>

<deferred>
## Deferred Ideas

- **Real FIFA ranking data source** — D-16 closed. Elo proxy kept. A future release can add `data/fifa_rankings.json` if desired.
- **Historical fair play calibration per confederation** — not needed for MVP. `Poisson(2.0)/Poisson(0.05)` defaults sufficient.
- **Live WebSocket subscription** — BSD offers WebSocket at `/ws/live/` but this is out of scope for Phase 10 (deferred to future v1.2).
- **BSD MCP server integration** — available at `/mcp` but not needed (deferred to future v1.2).

</deferred>

---

*Phase: 10-Integration-Tests-BSD-Verification*
*Context gathered: 2026-06-14*
