<!-- refreshed: 2026-06-14 -->
# Architecture

**Analysis Date:** 2026-06-14 (v1.1 update: Phase 10 complete — group match ingestion, standings display)

> **Status:** Greenfield project — no application code yet. All architecture is based on the design documents in `SOTs/` (MVP.md, TRD.md, Backend_Schema.md, Appflow.md, Implementation_plan.md).

## System Overview

```text
┌───────────────────────────────────────────────────────────────────────┐
│                       External API Layer                              │
│         BSD Sports Data (sports.bzzoiro.com/api/events/)              │
│         GET ?status=finished&league_id=27                             │
│         Auth: Authorization: Token {api_key}                          │
└────────────────────────────┬──────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       Orchestration Layer                             │
│                      `main.py` (main loop)                            │
│                                                                       │
│  ┌─────────────────────┐   ┌───────────────────────────────────┐     │
│  │ group_name != null  │   │ group_name == null                │     │
│  │  → process_group_   │   │  → process_matches() (knockout)  │     │
│  │    matches()        │   │     → update_elo_ratings()       │     │
│  └─────────┬───────────┘   └────────────┬──────────────────────┘     │
│            │                            │                            │
│            ▼                            ▼                            │
│  ┌─────────────────┐         ┌────────────────────┐                  │
│  │ save to         │         │ update Elo + save  │                  │
│  │ played_groups   │         │ to played.json     │                  │
│  │ .json           │         │                    │                  │
│  └────────┬────────┘         └────────┬───────────┘                  │
│           │                           │                              │
│           └───────────┬───────────────┘                              │
│                       ▼                                              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ run_full_simulation(played_groups)                               │  │
│  │   → simulate_group_matches() → compute_standings()              │  │
│  │   → rank_third_placed() → resolve_r32_matchups()                │  │
│  │   → run_knockout() → championship probabilities                 │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                       │                                              │
│                       ▼                                              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ output: print_header() + print_group_standings()                │  │
│  │         + print_third_place_bubble() + print_probabilities()   │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      Module / Layer Boundaries                       │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │ Integration Layer                    │  Core Logic Layer       │   │
│  │ `src/fetcher.py`                     │  `src/elo.py`          │   │
│  │ - HTTP GET + retry/backoff           │  - Elo formula          │   │
│  │ - JSON parsing                       │  - update_ratings()     │   │
│  │ - ID mapping (api_id_mapping)        │                         │   │
│  │ - Team name normalisation            │  `src/groups.py`        │   │
│  │ - process_group_matches()            │  - simulate_group_      │   │
│  │   (group_name routing)               │    matches()            │   │
│  │ - _extract_group_letter()            │  - compute_standings()  │   │
│  │ - _find_group_match()                │  - rank_third_placed()  │   │
│  │                                      │  - resolve_r32_         │   │
│  │                                      │    matchups()           │   │
│  └──────────────────────────────────────│                         │   │
│                                         │  `src/knockout.py`      │   │
│  ┌─────────────────────────────────┐    │  - run_full_            │   │
│  │ State / Persistence Layer       │    │    simulation()         │   │
│  │ `src/state.py`                  │    │  - 104-match pipeline   │   │
│  │ - load/save teams.json          │    └────────────────────────┘   │
│  │ - load/save bracket.json        │                                 │
│  │ - load/save played.json         │  ┌────────────────────────┐    │
│  │ - load/save played_groups.json  │  │ Output Layer           │    │
│  │ - load/save api_id_mapping      │  │ `src/output.py`        │    │
│  │ - atomic writes (tmp+rename)    │  │ - print_header()       │    │
│  │ - load_groups() + validate_     │  │ - print_group_         │    │
│  │   groups()                      │  │   standings()          │    │
│  │ - load_annex_c() + validate_    │  │ - print_third_place_   │    │
│  │   annex_c()                     │  │   bubble()             │    │
│  └─────────────────────────────────┘  │ - print_probabilities()│    │
│                                       │ - print_match_update() │    │
│                                       │ - ANSI color codes     │    │
└───────────────────────────────────────┴────────────────────────┴─────┘
                                        │
                                        ▼
                               ┌─────────────────────┐
                               │   Console Output     │
                               │  (stdout scrolling)  │
                               └─────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File (planned) |
|-----------|----------------|----------------|
| **Main loop orchestrator** | Infinite poll-detect-update-simulate-output cycle; coordinates all modules; handles graceful shutdown | `main.py` |
| **State manager** | Load/save team data, bracket, groups, annex_c, played matches, played_groups, and API ID mapping to/from JSON on disk; atomic writes | `src/state.py` |
| **Elo updater** | Compute Elo rating changes after a real match result using standard Elo formula with configurable K-factor | `src/elo.py` |
| **Group stage engine** | Round-robin group match simulation (Poisson model), 7-step tiebreaker, 5-step third-place ranking, Annex C R32 matchup resolution | `src/groups.py` |
| **Simulation engine / Bracket** | Full 104-match tournament pipeline: groups → Annex C → R32 → R16 → QF → SF → TPP → FINAL; `run_full_simulation()` orchestrator | `src/knockout.py` |
| **Live score fetcher** | Poll BSD API; filter new matches; route by `group_name` field; map external IDs to internal bracket IDs; normalise team names; process group matches | `src/fetcher.py` |
| **Console output formatter** | Timestamped logging, formatted probability table, box-drawing group standings table, third-place bubble indicator, match detection highlights, ANSI colors (with --no-color fallback) | `src/output.py` |
| **Constants & configuration** | Hardcoded defaults (K-factor, poll interval, simulation count, API URL, env var name, group count) | `src/constants.py` |

## Pattern Overview

**Overall:** Modular synchronous single-threaded event-driven pipeline with file-based persistence. Extended for v1.1 with group match ingestion and split routing.

**Key Characteristics:**
- Each module has a single responsibility and a well-defined function signature (specified in `Backend_Schema.md`)
- No shared mutable state between modules — all data flows through the orchestrator (`main.py`)
- File-based persistence replaces a database for MVP simplicity
- The main loop is a classic **poll-process-simulate** cycle with blocking sleep
- BSD API responses are split at runtime by the `group_name` field: non-null → group match; null → knockout match
- Group match results stored in separate `played_groups.json` to prevent knockout bracket contamination
- State transitions for group matches: PENDING → COMPLETED (real result injected); draws allowed (winner = null)
- Deterministic group simulation iteration (`random.Random(0)`) for display standings with zero overhead

## Layers

**External API / Integration Layer:**
- Purpose: Retrieve live match results from BSD (Bzzoiro Sports Data) REST API; route by match type
- Location: `src/fetcher.py`
- Contains: HTTP GET with retry/backoff, JSON parsing, `group_name` field discrimination, `process_group_matches()` for group match ingestion, `process_matches()` for knockout, `_extract_group_letter()`, `_find_group_match()`, external-to-internal ID mapping, team name normalisation (including group team names from `groups.json`)
- Depends on: `requests` library, `api_id_mapping.json`, `played.json`, `played_groups.json`, `groups.json`, `team_aliases.json`
- Used by: `main.py`

**State / Persistence Layer:**
- Purpose: Load and save all persistent data to JSON files; ensure data integrity with atomic writes
- Location: `src/state.py`
- Contains: `load_teams()`, `load_bracket()`, `load_played_matches()`, `save_teams()`, `save_played_matches()`, `load_api_id_mapping()`, `save_api_id_mapping()`, `load_played_groups()`, `save_played_groups()`, `load_groups()`, `load_annex_c()`, `validate_groups()`, `validate_annex_c()`
- Depends on: Python `json` module, `os`, `tempfile`
- Used by: `main.py`

**Core Logic Layer:**
- Purpose: Compute Elo rating updates, run group stage simulation, execute full 104-match tournament pipeline
- Location: `src/elo.py`, `src/groups.py`, `src/knockout.py`
- Contains: Elo formula (`expected_score`, `update_ratings`), group match simulation (`simulate_group_matches()` with Poisson scoring), group standings (`compute_standings()`, 7-step tiebreaker), third-place ranking (`rank_third_placed()`, 5-step), Annex C R32 resolution (`resolve_r32_matchups()`), full tournament pipeline (`run_full_simulation()` orchestrator), Monte Carlo aggregation
- Depends on: `random` module, `collections` (Counter), `math`, `itertools`
- Used by: `main.py`

**Output / Presentation Layer:**
- Purpose: Format and print all console output with timestamps, ANSI colors, visual indicators, and group standings
- Location: `src/output.py`
- Contains: `print_header()` (48-team format), `print_group_standings()` (box-drawing table, 12 groups), `print_third_place_bubble()` (cutoff indicator), `print_probabilities()`, `print_match_update()`, `print_error()`, `print_heartbeat()`
- Depends on: `sys` (stdout), ANSI escape code constants, `datetime`
- Used by: `main.py`

**Orchestration Layer:**
- Purpose: Drive the infinite main loop, coordinate all modules, handle errors and shutdown
- Location: `main.py`
- Contains: Main loop (`while True`), initialisation, state loading, new match processing, simulation scheduling, sleep, `try/except` wrapper, `KeyboardInterrupt` handler
- Depends on: All `src/*` modules, `time`, `os`
- Entry point: `python main.py`

## Data Flow

### Primary Request Path (Match Detection → Probability Update)

1. **Poll API** — `main.py` calls `fetcher.fetch_new_results(last_known_match_ids)` with BSD API (`src/fetcher.py`)
2. **Parse + Route response** — Filter matches with `status == "finished"` and `id` not in `last_known_ids`. Check `group_name` field:
   - **Non-null (group match):** — Call `process_group_matches(raw_matches, teams, groups, aliases, played_group_ids, played_bsd_event_ids)` (`src/fetcher.py`)
     - Extract group letter from `group_name`
     - Normalize team names (alias lookup includes group team names from `groups.json`)
     - Resolve match slot via team pair + group letter against `groups.json`
     - Dedup via BSD event `id` and `match_id`
     - Return processed group match dicts
     - Save to `played_groups.json` via `state.save_played_groups()` (`src/state.py`)
     - Print refreshed group standings via `output.print_group_standings()` + `output.print_third_place_bubble()` (`src/output.py`)
   - **Null (knockout match):** — Continue with existing `process_matches()` flow
     - Map external IDs — Convert API numeric `id` to internal `match_id` using `api_id_mapping.json`
     - Construct `MatchResult` dict: `{match_id, team_a, team_b, winner, home_score, away_score}`
     - Call `elo.update_ratings(team_a, team_b, winner, current_elos)` (`src/elo.py`)
     - Merge updated Elo values into in-memory `teams` dict
     - Call `state.save_teams(teams)` and `state.save_played_matches(played_details)`
3. **Re-run full simulation** — `main.py` calls `knockout.run_full_simulation(elos, groups_data, bracket, played_set, played_groups, annex_c, n=50000)` (`src/knockout.py`)
   - Groups → Annex C → R32 → R16 → QF → SF → TPP → FINAL (full 104-match pipeline)
   - Uses real results from `played.json` and `played_groups.json` where available
   - Returns `{team_name: probability}` dict
4. **Output** — `main.py` calls `output.print_probabilities(probs, timestamp, deltas)` (`src/output.py`)
5. **Sleep** — `time.sleep(POLL_INTERVAL_SECONDS)` (60s default)

### Startup Flow

1. Load `state.load_teams()`, `state.load_bracket()`, `state.load_played_matches()` from JSON files
2. Build `last_known_match_ids` from played matches keys
3. Run initial `simulator.run_monte_carlo()` → print initial probabilities via `output.print_header()` + `output.print_probabilities()`
4. Enter main loop

### Shutdown Flow

1. `KeyboardInterrupt` caught in `main.py`
2. Call `state.save_teams()` and `state.save_played_matches()` (ensure latest state on disk)
3. Optionally run one final simulation
4. Print final probabilities
5. Exit with code 0

**State Management:**
- All state is held in-memory as Python dicts/lists during runtime
- Persisted to JSON files on every state change (played matches + Elo updates)
- No database — JSON files serve as both persistence and debug visibility
- Atomic writes: write to temp file, then `os.rename()` to prevent corruption

## Key Abstractions

**MatchResult:**
- Purpose: Represents a single finished match returned by the API or used internally
- Defined in: `src/fetcher.py` (backed by schema in `SOTs/Backend_Schema.md §5.1`)
- Fields: `match_id: str`, `team_a: str`, `team_b: str`, `winner: str|None`, `home_score: int`, `away_score: int`

**Bracket Tree:**
- Purpose: Represents the World Cup knockout stage as a nested structure (R32 → R16 → QF → SF → TPP → Final)
- File: `data/bracket.json`
- Structure: Dict with keys `r32`, `round_of_16`, `quarterfinals`, `semifinals`, `third_place_playoff`, `final`; R32 matches use `group_position` and `annex_c_third` slot descriptors; later rounds use `source_matches` array

**Group Stage Data:**
- File: `data/groups.json`, `data/annex_c.json`, `data/team_aliases.json`
- Groups: 12 groups (A–L) × 4 teams each, 72 round-robin match slots
- Annex C: 495-entry lookup table for third-place → R32 matchup resolution
- Aliases: 48 teams with BSD API name variations for reliable live match ingestion

**Teams Dict:**
- Purpose: In-memory mapping of team name → Elo rating + metadata
- File: `data/teams.json`
- Schema: `{team_name: {"elo": int, "group": str, "eliminated": bool, "fifa_rank": int}}`

**Played Matches (Knockout):**
- Purpose: Dual representation — `set[str]` for O(1) lookup during simulation, `dict[str, dict]` for persisted details
- File: `data/played.json`
- Schema: `{match_id: {"winner": str, "home_score": int, "away_score": int, "timestamp": str}}`

**Played Group Matches:**
- Purpose: Group match results stored separately from knockout data
- File: `data/played_groups.json`
- Schema: `{match_id: {"winner": str|null, "home_score": int, "away_score": int, "completed_at": str}}`
- Draws allowed (winner = null)

**Probabilities:**
- Purpose: Champion probability distribution output by Monte Carlo simulation
- Format: `dict[str, float]` — `{"Argentina": 0.341, "France": 0.275, ...}`
- Constraint: Values sum to 1.0 (±0.001 floating tolerance)

## Entry Points

**Main entry point:**
- Location: `main.py` (project root)
- Triggers: `python main.py` (command line)
- Options: `--seed <int>` (reproducible randomness), `--once` (single cycle), `--no-color` (plain output), `--help`
- Responsibilities: Load state, orchestrate initial simulation, run infinite poll-loop, handle graceful shutdown

## Architectural Constraints

- **Threading:** Single-threaded, synchronous, blocking. No asyncio, no threading, no multiprocessing for MVP. API calls and CPU-bound simulations both block the main thread.
- **Global state:** No module-level singletons or global mutable state. All data dicts live in `main.py` and are passed explicitly to module functions.
- **Circular imports:** None. Dependency direction: `main.py` → every other module. `state.py`, `elo.py`, `simulator.py`, `fetcher.py`, `output.py` are leaf modules with no inter-dependencies.
- **External dependency:** Only `requests` library for HTTP. All other modules use only Python standard library (`random`, `json`, `os`, `time`, `sys`, `tempfile`, `collections`, `datetime`, `math`, `itertools`).
- **No database:** JSON files are the sole persistence mechanism. No SQL, no ORM, no Redis.
- **API rate limits:** Free tier limited to 10 requests/minute. Polling interval of 60s ensures 1 req/min, well within limit.
- **File system:** All data files live under `data/` directory. No external paths or user-provided file paths.
- **Group/knockout persistence separation:** `played_groups.json` is independent from `played.json` — group match results never contaminate knockout bracket data.

## Anti-Patterns

### No explicit anti-patterns yet — codebase is greenfield.

**However, the design explicitly avoids these common pitfalls (per SOTs):**
- No deep copying of large dicts during simulation loops (use reference passing)
- No hardcoded API keys in source files (use environment variable `FOOTBALL_API_KEY`)
- No mutable default arguments in function signatures
- No bare `except:` — use `except Exception as e:` with logging

## Error Handling

**Strategy:** Catch at the main loop level; log and continue; retry transient failures.

**Patterns:**
- **API failures:** Retry up to 3 times with exponential backoff (1s, 2s, 4s). On persistent failure, log error and continue with last known data.
- **Malformed JSON:** Catch `json.JSONDecodeError`, treat as API failure.
- **Team name mismatch:** Log warning, skip match (or use mapping table).
- **File write failure:** Print critical error but continue (unsaved state lost on restart).
- **KeyboardInterrupt:** Graceful shutdown — save state, print final probabilities, exit code 0.
- **Top-level wrapper:** Entire main loop wrapped in `try/except Exception` to prevent single crash from terminating the process.

## Cross-Cutting Concerns

**Logging:** Console-only with timestamps. Each log line prefixed with `[YYYY-MM-DD HH:MM:SS]`. No external log files for MVP. Future: `--log` flag for file output.

**Validation:**
- Team names must match between `teams.json`, `bracket.json`, and API mapping
- Elo ratings must be positive integers; updates must not produce negative values
- `played.json` winner must exist in `teams.json`
- Every `source_matches` list must contain valid `match_id`s
- Simulation probabilities must sum to 1.0 (±0.001 tolerance)

**Configuration:** All tunable parameters defined in `src/constants.py` as module-level constants. No config files for MVP. Parameters: `K_FACTOR`, `POLL_INTERVAL_SECONDS`, `SIMULATION_COUNT`, `API_URL`, `API_KEY_ENV_VAR`.

**Secrets:**
- API key read from environment variable `BSD_API_KEY` in `main.py`
- Never stored in JSON files or committed to git

---

*Architecture analysis: 2026-06-14 (v1.1 update)*
