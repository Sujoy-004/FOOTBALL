<!-- refreshed: 2026-06-13 -->
# Architecture

**Analysis Date:** 2026-06-13

> **Status:** Greenfield project — no application code yet. All architecture is based on the design documents in `SOTs/` (MVP.md, TRD.md, Backend_Schema.md, Appflow.md, Implementation_plan.md).

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                     External API Layer                               │
│         Football-Data.org (v4/matches?competition=WC)                │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Orchestration Layer                              │
│                    `main.py` (main loop)                             │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ fetch_new_    │  │ update_elo_  │  │ run_monte_carlo(50k)      │  │
│  │ results()     │  │ ratings()    │  │ + print_probabilities()   │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────────┘  │
│         │                │                       │                  │
└─────────┼────────────────┼───────────────────────┼──────────────────┘
          │                │                       │
          ▼                ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Module / Layer Boundaries                       │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │ Integration Layer                │  Core Logic Layer         │     │
│  │ `src/fetcher.py`                 │  `src/elo.py`            │     │
│  │ - HTTP GET + retry/backoff       │  - Elo formula            │     │
│  │ - JSON parsing                   │  - update_ratings()       │     │
│  │ - ID mapping (api_id_mapping)    │                          │     │
│  │ - Team name normalisation        │  `src/simulator.py`       │     │
│  └──────────────────────────────────│  - simulate_match()       │     │
│                                     │  - run_single_tournament()│     │
│  ┌───────────────────────────────┐  │  - run_monte_carlo()      │     │
│  │ State / Persistence Layer     │  └──────────────────────────┘     │
│  │ `src/state.py`                │                                   │
│  │ - load/save teams.json        │  ┌──────────────────────────┐     │
│  │ - load/save bracket.json      │  │ Output Layer             │     │
│  │ - load/save played.json       │  │ `src/output.py`          │     │
│  │ - atomic writes (tmp+rename)  │  │ - print_header()         │     │
│  │ - load/save api_id_mapping    │  │ - print_probabilities()  │     │
│  └───────────────────────────────┘  │ - print_match_update()   │     │
│                                     │ - ANSI color codes       │     │
└─────────────────────────────────────┴──────────────────────────┴─────┘
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
| **State manager** | Load/save team data, bracket, played matches, and API ID mapping to/from JSON on disk; atomic writes | `src/state.py` |
| **Elo updater** | Compute Elo rating changes after a real match result using standard Elo formula with configurable K-factor | `src/elo.py` |
| **Simulation engine** | Single-match simulation from Elo win probability; full tournament traversal; Monte Carlo aggregation (50,000+ runs) | `src/simulator.py` |
| **Live score fetcher** | Poll Football-Data.org API; filter new matches; map external IDs to internal bracket IDs; normalise team names | `src/fetcher.py` |
| **Console output formatter** | Timestamped logging, formatted probability table, match detection highlights, ANSI colors (with --no-color fallback) | `src/output.py` |
| **Constants & configuration** | Hardcoded defaults (K-factor, poll interval, simulation count, API URL, env var name) | `src/constants.py` |

## Pattern Overview

**Overall:** Modular synchronous single-threaded event-driven pipeline with file-based persistence.

**Key Characteristics:**
- Each module has a single responsibility and a well-defined function signature (specified in `Backend_Schema.md`)
- No shared mutable state between modules — all data flows through the orchestrator (`main.py`)
- File-based persistence replaces a database for MVP simplicity
- The main loop is a classic **poll-process-simulate** cycle with blocking sleep
- State transitions are linear: PENDING → COMPLETED → FROZEN (never re-simulated)

## Layers

**External API / Integration Layer:**
- Purpose: Retrieve live match results from Football-Data.org REST API
- Location: `src/fetcher.py`
- Contains: HTTP GET with retry/backoff, JSON parsing, external-to-internal ID mapping, team name normalisation
- Depends on: `requests` library, `api_id_mapping.json`, `played.json` (for filtering new matches)
- Used by: `main.py`

**State / Persistence Layer:**
- Purpose: Load and save all persistent data to JSON files; ensure data integrity with atomic writes
- Location: `src/state.py`
- Contains: `load_teams()`, `load_bracket()`, `load_played_matches()`, `save_teams()`, `save_played_matches()`, `load_api_id_mapping()`, `save_api_id_mapping()`
- Depends on: Python `json` module, `os`, `tempfile`
- Used by: `main.py`

**Core Logic Layer:**
- Purpose: Compute Elo rating updates and run Monte Carlo tournament simulations
- Location: `src/elo.py` and `src/simulator.py`
- Contains: Elo formula (`expected_score`, `update_ratings`), match simulation, bracket traversal, Monte Carlo aggregation
- Depends on: `random` module, `collections` (Counter)
- Used by: `main.py`

**Output / Presentation Layer:**
- Purpose: Format and print all console output with timestamps, ANSI colors, and visual indicators (▲, ▼, ⚠)
- Location: `src/output.py`
- Contains: `print_header()`, `print_probabilities()`, `print_match_update()`, `print_error()`, `print_heartbeat()`
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

1. **Poll API** — `main.py` calls `fetcher.fetch_new_results(last_known_match_ids)` (`src/fetcher.py`)
2. **Parse response** — Filter matches with `status == "FINISHED"` and `id` not in `last_known_ids`
3. **Map external IDs** — Convert API numeric `id` to internal `match_id` using `api_id_mapping.json` (`src/state.py`)
4. **For each new match:**
   - Construct `MatchResult` dict: `{match_id, team_a, team_b, winner, home_score, away_score}`
   - Call `elo.update_ratings(team_a, team_b, winner, current_elos)` → returns updated Elo dict (`src/elo.py`)
   - Merge updated Elo values into in-memory `teams` dict
   - Call `state.save_teams(teams)` and `state.save_played_matches(played_details)` (`src/state.py`)
   - Add `match_id` to `last_known_match_ids`
5. **Re-run simulation** — `main.py` calls `simulator.run_monte_carlo(elos, bracket, played_set, n=50000)` (`src/simulator.py`)
   - For each of N iterations: traverse bracket tree; use real winner if played, else `simulate_match()` based on Elo win probability
   - Return `{team_name: probability}` dict
6. **Output** — `main.py` calls `output.print_probabilities(probs, timestamp, deltas)` (`src/output.py`)
7. **Sleep** — `time.sleep(POLL_INTERVAL_SECONDS)` (60s default)

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
- Fields: `match_id: str`, `team_a: str`, `team_b: str`, `winner: str`, `home_score: int`, `away_score: int`

**Bracket Tree:**
- Purpose: Represents the World Cup knockout stage as a nested structure (R16 → QF → SF → Final)
- File: `data/bracket.json`
- Structure: Dict with keys `round_of_16`, `quarterfinals`, `semifinals`, `final`; each match has `match_id`, `winner` (nullable), and for later rounds `source_matches` array linking earlier matches

**Teams Dict:**
- Purpose: In-memory mapping of team name → Elo rating + metadata
- File: `data/teams.json`
- Schema: `{team_name: {"elo": int, "group": str, "eliminated": bool, "fifa_rank": int}}`

**Played Matches:**
- Purpose: Dual representation — `set[str]` for O(1) lookup during simulation, `dict[str, dict]` for persisted details
- File: `data/played.json`
- Schema: `{match_id: {"winner": str, "home_score": int, "away_score": int, "timestamp": str}}`

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
- **External dependency:** Only `requests` library for HTTP. All other modules use only Python standard library (`random`, `json`, `os`, `time`, `sys`, `tempfile`, `collections`, `datetime`).
- **No database:** JSON files are the sole persistence mechanism. No SQL, no ORM, no Redis.
- **API rate limits:** Free tier limited to 10 requests/minute. Polling interval of 60s ensures 1 req/min, well within limit.
- **File system:** All data files live under `data/` directory. No external paths or user-provided file paths.

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
- API key read from environment variable `FOOTBALL_API_KEY` in `main.py`
- Never stored in JSON files or committed to git

---

*Architecture analysis: 2026-06-13*
