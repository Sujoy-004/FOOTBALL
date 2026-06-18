# Architecture

**Analysis Date:** 2026-06-14 (v2.0 update: Phases 7-12b complete — 48-team format, group stage, Annex C, evaluation, Elo sync)

> **Status:** Implemented. 11 src modules, 329 tests, 104-match full tournament pipeline live.

## System Overview

ASCII component diagram showing the layered architecture:

```
                        ┌─────────────────────────────────────┐
                        │     BSD Sports Data API              │
                        │  GET /api/events/?league_id=27       │
                        │  Auth: Authorization: Token {key}    │
                        └───────────────┬─────────────────────┘
                                        │ HTTP GET (60s interval)
                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Orchestration Layer                         │
│                   main.py (main loop)                            │
│                                                                  │
│  ┌─────────────────────┐   ┌────────────────────────────────┐   │
│  │ group_name != null  │   │ group_name == null              │   │
│  │ → process_group_    │   │ → process_matches() (knockout) │   │
│  │   matches()         │   │    → update_elo_ratings()      │   │
│  └─────────┬───────────┘   └───────────┬────────────────────┘   │
│            │                           │                         │
│            ▼                           ▼                         │
│  ┌──────────────────┐      ┌─────────────────────┐               │
│  │ save to          │      │ save to played.json  │               │
│  │ played_groups.json│     │ + update Elo         │               │
│  └────────┬─────────┘      └──────────┬──────────┘               │
│           │                           │                          │
│           └───────────┬───────────────┘                          │
│                       ▼                                          │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ run_full_simulation(elos, groups, bracket, annex_c,       │   │
│  │   played_set, played_groups, n=50000)                     │   │
│  │   → simulate_group_matches() → compute_standings()        │   │
│  │   → rank_third_placed() → resolve_r32_matchups()          │   │
│  │   → run_knockout() → champion probabilities               │   │
│  └───────────────────────────────────────────────────────────┘   │
│                       │                                          │
│                       ▼                                          │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ output: print_header() + print_group_standings()           │   │
│  │   + print_third_place_bubble() + print_probabilities()    │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## Modules (11 source files)

### Integration Layer
- **`src/fetcher.py`** (288 lines) — HTTP GET with retry/backoff, JSON parsing, BSD API polling, `group_name` field discrimination, `process_group_matches()` for group match ingestion, `process_matches()` for knockout, `_extract_group_letter()`, `_find_group_match()`, external-to-internal ID mapping, team name normalisation
  - Depends on: `requests`, `played.json`, `played_groups.json`, `groups.json`, `team_aliases.json`
  - Used by: `main.py`

### State / Persistence Layer
- **`src/state.py`** (573 lines) — Load/save all persistent data to JSON files; atomic writes (tmp+rename). Functions: `load_teams()`, `load_bracket()`, `load_played_matches()`, `save_teams()`, `save_played_matches()`, `load_groups()`, `load_annex_c()`, `validate_groups()`, `validate_annex_c()`, `load_prediction_history()`, `append_prediction_history()`, Elo sync persist
  - Depends on: Python `json`, `os`, `tempfile`, `pathlib`
  - Used by: `main.py`, `elo_sync.py`, `evaluation.py`

### Core Logic Layer
- **`src/elo.py`** (146 lines) — Standard World Football Elo formula: `expected_score()`, `update_ratings()`, `apply_elo_update()`. K-factor=60, home advantage, draw handling. Pure function, no I/O.
  - Depends on: `math`
  - Used by: `groups.py`, `knockout.py`, `simulation.py`, `evaluation.py`, `fetcher.py`

- **`src/groups.py`** (715 lines) — Group stage simulation engine. Round-robin group match simulation (Poisson model), 7-step tiebreaker, 5-step third-place ranking, Annex C R32 matchup resolution, precomputed matchup lambdas. Largest module.
  - Depends on: `math`, `random`, `collections`, `elo.py`
  - Used by: `knockout.py`, `main.py`

- **`src/knockout.py`** (268 lines) — Full 104-match tournament pipeline: groups → Annex C → R32 → R16 → QF → SF → TPP → FINAL. `run_full_simulation()` orchestrator with Monte Carlo aggregation. `run_knockout()` for stage-level probabilities.
  - Depends on: `random`, `collections`, `elo.py`, `groups.py`
  - Used by: `main.py`

- **`src/simulation.py`** (86 lines) — Legacy Monte Carlo simulation for pure-knockout scenarios (v1.0 compatibility). `run_simulation()` for 32-team knockout-only mode.
  - Depends on: `random`, `collections`, `elo.py`
  - Used by: `main.py`

- **`src/evaluation.py`** (118 lines) — Prediction quality metrics: Brier score, log loss, calibration curves, ECE computation. Post-hoc analysis of prediction accuracy.
  - Depends on: `copy`, `math`, `datetime`, `elo.py`, `state.py`
  - Used by: CLI or standalone scripts

- **`src/elo_sync.py`** (292 lines) — Elo synchronization from eloratings.net. Fetches World.tsv, parses, validates, applies graduated correction (D-10 through D-13) to reconcile our dynamic Elo with canonical source.
  - Depends on: `requests`, `csv`, `io`, `datetime`, `elo.py`, `state.py`
  - Used by: CLI (`python -m src.elo_sync`)

### Output / Presentation Layer
- **`src/output.py`** (318 lines) — Console formatting with ANSI colors. `print_header()` (48-team format), `print_group_standings()` (box-drawing tables, 12 groups), `print_third_place_bubble()` (cutoff indicator), `print_probabilities()`, `print_match_update()`, `print_error()`, `print_heartbeat()`. Delta tracking (▲/▼).
  - Depends on: `sys` (stdout), `logging`, `time`
  - Used by: `main.py`

### Configuration
- **`src/constants.py`** (101 lines) — All tunable parameters: `K_FACTOR=60`, `DEFAULT_ELO=1500`, `POLL_INTERVAL` (env-overridable), `API_URL`, `GROUP_COUNT=12`, `MATCHES_PER_GROUP=6`, `ANNEX_C_ENTRIES=495`, `ANNEX_C_WINNER_GROUPS`, data directory paths
  - Used by: All other modules

## Data Flow

### Primary Request Path (Match Detection → Probability Update)

1. **Poll API** — `main.py` calls `fetcher.fetch_new_results()` with BSD API endpoint (polled every POLL_INTERVAL seconds)
2. **Parse + Route response** — Filter finished matches by `status` field. Check `group_name`:
   - **Non-null (group match):** `process_group_matches()` → extract group letter → normalize team names → resolve match slot → dedup → save to `played_groups.json` → print group standings
   - **Null (knockout match):** `process_matches()` → map external IDs → compute Elo update → save to `played.json` + `teams.json`
3. **Re-run full simulation** — `knockout.run_full_simulation(elos, groups_data, bracket, played_set, played_groups, annex_c, n=50000)`
   - Simulate unplayed group matches (Poisson score model) → compute standings → rank third-placed → resolve Annex C → simulate R32→R16→QF→SF→TPP→FINAL
   - Aggregate champion counts → normalize to probabilities
4. **Output** — `output.print_probabilities(probs, timestamp, deltas)` + group standings if new group matches
5. **Sleep** — Deadline-based sleep in 0.5s increments for responsive Ctrl+C

### Startup & Shutdown
- **Startup:** Load teams, bracket, groups, annex_c, played matches from JSON → build `last_known_match_ids` → run initial simulation → print header + initial probabilities → enter main loop
- **Shutdown:** `KeyboardInterrupt` → save state → print final probabilities → exit 0

## Key Abstractions

| Abstraction | Description | File |
|---|---|---|
| `MatchResult` | Single finished match (match_id, team_a, team_b, winner, scores) | `fetcher.py` |
| `Bracket Tree` | 40-match knockout structure: R32→R16→QF→SF→TPP→FINAL, slot descriptors | `data/bracket.json` |
| `Group Stage Data` | 12 groups (A–L) × 4 teams, 72 round-robin match slots | `data/groups.json` |
| `Annex C Table` | 495-entry lookup: 8 third-place groups → R32 matchup mapping | `data/annex_c.json` |
| `Teams Dict` | In-memory `{team: {elo, group, eliminated, fifa_rank}}` | `data/teams.json` |
| `Played Matches` | `played.json` (knockout) + `played_groups.json` (group) — separate persistence | `data/` |
| `Probabilities` | `{team: float}` — champion probability, sum ≈ 1.0, from Monte Carlo | Runtime |

## Architectural Constraints

- **Threading:** Single-threaded, synchronous, blocking. No asyncio. CPU-bound simulation blocks polling (~15s at 50K iterations) — acceptable within 60s interval.
- **Global state:** No module-level singletons. All data dicts in `main.py`, passed explicitly to functions.
- **Circular imports:** None. Direction: `main.py` → everything. Leaf modules (`elo.py`, `state.py`, `output.py`) import only stdlib + `constants`.
- **External dependency:** `requests` for HTTP + `python-dotenv` for .env loading. All other modules use stdlib.
- **No database:** JSON files are sole persistence. No SQL, no ORM, no Redis.
- **API rate limit:** Free tier limited. 60s polling = 1 req/min, well within limit.
- **Group/knockout persistence separation:** `played_groups.json` independent from `played.json`.

## Data Files (14 files)
- `teams.json`, `bracket.json`, `groups.json`, `annex_c.json`, `team_aliases.json`
- Runtime: `played.json`, `played_groups.json`, `elo_applied.json`, `elo_update_log.json`, `eloratings_cache.json`, `prediction_history.json`
- Evaluation: `eval_baseline.json`, `eval_baseline_report.json`

## Entry Points
- **Main:** `python main.py` — flags: `--once`, `--no-color`, `--seed`, `--help`
- **Elo sync:** `python -m src.elo_sync` — standalone CLI for Elo update from eloratings.net

---

*Architecture analysis: 2026-06-14 (v2.0 update)*
