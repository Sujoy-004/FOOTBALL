# Features

**Analysis Date:** 2026-06-16 (v2.0 complete: Phases 7 through 12b)

## Feature Inventory

### Live Group Match Ingestion (Phase 10, INTG-01/INTG-02)
- **Source:** BSD API single endpoint `GET /api/events/?league_id=27&limit=200`
- **Status:** Finished (completed, then iterated — see Phase 10)
- **Routing:** BSD response entries split by `group_name` field:
  - Non-null `group_name` (e.g., `"Group A"`) → `process_group_matches()` (new in Phase 10)
  - Null `group_name` → `process_matches()` (existing knockout flow)
- **`process_group_matches()`** in `src/fetcher.py`:
  - Extract group letter via `_extract_group_letter()`
  - Normalize team names via alias lookup (all 48 teams in `groups.json`)
  - Resolve match slot via team pair set equality against `groups.json` slot definitions
  - Dedup via BSD event `id` (in-memory set) and `match_id` (persisted `played_groups.json`)
  - Draw matches (equal scores) stored with `winner: null`
- **Persistence:** `played_groups.json` — separate from knockout `played.json`
- **No Elo updates for group matches** (per D-09 scope)

### Group Standings Console Display (Phase 10, INTG-03/INTG-04/INTG-05)
- **`print_group_standings()`** in `src/output.py`:
  - Box-drawing characters for table borders
  - Columns: Position (P), Team, Points (Pts), Goal Difference (GD), Goals Scored (GS)
  - All 12 groups (A–L) stacked vertically with horizontal separators
  - Empty standings placeholder on startup with no data
- **`print_third_place_bubble()`** in `src/output.py`:
  - Ranks 12 third-placed teams by Pts → GD → GS
  - Shows 8th (ADVANCES, green) and 9th (OUT, red) with cutoff margin
- **`print_header()`** updated for 48-team format
- **Deterministic display sim:** Single group iteration with `random.Random(0)` (~0.01s overhead)

### 48-Team Console Header (Phase 10, INTG-05)
- Updated startup banner showing 48 teams, 12 groups, 72 group matches, 40 bracket matches, 495 Annex C scenarios

### Elo Rating Updates for Knockout Matches
- Standard World Football Elo formula (`elo.py`)
- K-factor = 60, configurable
- Applied after every detected knockout match
- Teams updated in-memory and persisted to `teams.json`

### Full 104-Match Tournament Pipeline (Phase 9)
- Groups (72 matches) → Annex C → R32 (16) → R16 (8) → QF (4) → SF (2) → TPP (1) → FINAL (1)
- Poisson score model for group matches (no numpy dependency)
- Monte Carlo simulation at configurable iteration count (default 50,000)
- Championship probabilities + stage-level advancement probabilities

### BSD API Live Match Polling
- 60s polling interval (configurable via `POLL_INTERVAL` env var)
- 3-retry loop with exponential backoff (1s, 2s, 4s)
- Team name normalization via `team_aliases.json` (48 teams)
- Cache fallback on API failure — never crashes

### CLI Flags
- `--once` — single cycle, then exit
- `--no-color` — plain text output
- `--seed <int>` — reproducible randomness
- `--help` — usage documentation

### Elo Sync from eloratings.net (Phase 11, D-10 through D-13)
- Standalone CLI: `python -m src.elo_sync`
- Fetches World.tsv, parses, validates
- Graduated correction approach reconciles dynamic Elo with canonical source
- Audit logging: `elo_applied.json`, `elo_update_log.json`

### Evaluation Metrics (Phase 12b)
- Brier score, log loss, calibration curves, ECE computation
- `prediction_history.json` for post-hoc analysis
- `eval_baseline.json` + `eval_baseline_report.json` for baseline runs

## Data Flow
```
[BSD API] → fetch_new_results()
    → group_name != null ? process_group_matches() : process_matches()
    → group match: save to played_groups.json → print group standings
    → knockout match: update Elo → save to played.json
    → run_full_simulation(played_groups) → print probabilities
```

## Test Coverage
- 329 passing tests, 1 skipped (live smoke requires BSD_API_KEY), 0 failures
- 16 test files covering all 11 src modules
- Integration tests: full pipeline mock API flow, group integration (INTG-01 through INTG-07), live smoke test

## Known Limitations
- **Tiebreaker Step 7** uses Elo-as-FIFA-ranking-proxy (~0.92 correlation). Not real FIFA ranking data.
- **Fair play data:** Group matches from BSD API don't include card counts. Simulated group matches use Poisson defaults.
- **Live smoke test** requires manual `BSD_API_KEY` environment variable. Skip if not set.
- **Performance:** Full 104-match simulation at 50K iterations takes ~10-15s (within 60s poll interval).

---

*Feature inventory: 2026-06-16 (v2.0 complete)*
