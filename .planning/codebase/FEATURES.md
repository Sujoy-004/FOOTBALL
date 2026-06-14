# Features

**Analysis Date:** 2026-06-14 (v1.1 update: Phase 10 complete)

## Feature Inventory

### Live Group Match Ingestion (Phase 10, INTG-01/INTG-02)
- **Source:** BSD API single endpoint `GET /api/events/?status=finished&league_id=27`
- **Routing:** BSD response entries split by `group_name` field:
  - Non-null `group_name` (e.g., `"Group A"`) → `process_group_matches()` (new in Phase 10)
  - Null `group_name` → `process_matches()` (existing knockout flow)
- **`process_group_matches()`** in `src/fetcher.py`:
  - Extract group letter via `_extract_group_letter("Group A")` → `"A"`
  - Normalize team names via alias lookup (includes all group team names from `groups.json` to handle teams not in `team_aliases.json`)
  - Resolve match slot via team pair set equality against `groups.json` slot definitions
  - Dedup via BSD event `id` (in-memory set, per-poll) and `match_id` (persisted `played_groups.json`)
  - Draw matches (equal scores) stored with `winner: null`
  - Unmatchable teams, invalid group names, unresolvable slots → log warning, skip match
- **Persistence:** `played_groups.json` follows same pattern as `played.json` — separate file to prevent knockout bracket contamination
- **No Elo updates for group matches** (per D-09 scope)

### Group Standings Console Display (Phase 10, INTG-03/INTG-04/INTG-05)
- **`print_group_standings()`** in `src/output.py`:
  - Box-drawing characters (`\u2502 \u2500 \u250c \u2510 \u2514 \u2518 \u251c \u2524 \u252c \u2534 \u253c`) for table borders
  - Columns: Position (P), Team (28-char width), Points (Pts), Goal Difference (GD), Goals Scored (GS)
  - All 12 groups (A–L) displayed stacked vertically with horizontal separators
  - GD formatting: `+X` for positive, raw number for zero/negative
  - Empty standings placeholder: `(no group matches played yet)` on startup with no data
- **`print_third_place_bubble()`** in `src/output.py`:
  - Ranks all 12 third-placed teams by Pts \u2192 GD \u2192 GS
  - Shows 8th (ADVANCES, green) and 9th (OUT, red) with cutoff margin
  - Format: `8. Ghana  3 pts  GD +0  ADVANCES  9. Panama  3 pts  GD -2  OUT  Cutoff margin: GD = 2`
- **`print_header()`** updated for 48-team format:
  - Shows `48 teams, 12 groups (72 group matches, 40 bracket matches)`
- **Deterministic display sim:** Single group simulation iteration with `random.Random(0)` for display data (~0.01s overhead)
- **Refresh behavior (D-15):** Show standings on new group matches or hourly refresh; skip on heartbeat

### 48-Team Console Header (Phase 10, INTG-05)
- **Updated startup banner:**
  ```
  WORLD CUP DYNAMIC PREDICTOR \u2014 v1.1
  Polling API every 60 seconds. Press Ctrl+C to stop.
  48 teams, 12 groups (72 group matches, 40 bracket matches)
  495 Annex C scenarios \u2014 Initial simulation complete.
  ```

### Known Limitations
- **Tiebreaker Step 7** uses Elo-as-FIFA-ranking-proxy (~0.92 correlation). Not a real FIFA ranking data source (D-16 closed). See `STATE.md` deferred items.
- **Fair play data:** Group matches from BSD API don't include card counts. Simulated group matches use `Poisson(2.0)/Poisson(0.05)` defaults for fair play points.
- **Live smoke test** requires manual `BSD_API_KEY` environment variable. Test is skipped automatically if key is not set.

### Core Features (v1.0)
- 48-team dataset with Elo ratings and group assignments (Phase 7)
- 12 group definitions (A–L), 495-entry Annex C lookup table (Phase 7)
- Group stage simulation engine with Poisson scoring, 7-step tiebreaker (Phase 8)
- Full 104-match tournament pipeline: Groups \u2192 Annex C \u2192 R32 \u2192 R16 \u2192 QF \u2192 SF \u2192 TPP \u2192 FINAL (Phase 9)
- BSD API live match polling with retry/backoff (Phase 3, updated Phase 10)
- Elo rating updates for knockout matches (Phase 1)
- Console output with ANSI colors, delta tracking (\u25b2/\u25bc), heartbeat (Phase 5)
- CLI flags: `--once`, `--no-color`, `--seed`, `--help` (Phase 6)

## Data Flow

```
[BSD API] \u2192 fetch_new_results()
    \u2192 group_name != null ? process_group_matches() : process_matches()
    \u2192 group match: save to played_groups.json \u2192 print group standings
    \u2192 knockout match: update Elo \u2192 save to played.json
    \u2192 run_full_simulation(played_groups) \u2192 print probabilities
```

## Test Coverage
- 212 passing tests, 1 skipped (live smoke requires BSD_API_KEY), 0 failures
- 18 group integration tests covering INTG-01 through INTG-07
- `test_live_smoke.py` for manual BSD API smoke testing

---

*Feature inventory: 2026-06-14 (v1.1 complete)*
