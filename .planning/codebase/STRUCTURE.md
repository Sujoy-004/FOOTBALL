# Codebase Structure

**Analysis Date:** 2026-06-13

> **Status:** Greenfield project — no application code yet. Structure is planned per `SOTs/Implementation_plan.md`. All paths listed are the intended target layout for the MVP build.

## Directory Layout

```
worldcup_predictor/               # Project root (working name)
├── data/                         # Static & dynamic data (JSON files)
│   ├── teams.json                # Initial + updated Elo ratings per team
│   ├── bracket.json              # Knockout bracket tree structure
│   ├── played.json               # Record of completed real matches
│   └── api_id_mapping.json       # Maps external API IDs → internal match_ids
│
├── src/                          # Application source modules
│   ├── __init__.py               # Marks src/ as a Python package
│   ├── state.py                  # State persistence: load/save JSON files
│   ├── elo.py                    # Elo rating update formula
│   ├── simulator.py              # Match simulation + Monte Carlo engine
│   ├── fetcher.py                # Live API polling + response parsing
│   ├── output.py                 # Console formatting + ANSI color output
│   └── constants.py              # All tunable parameters (K, poll interval, etc.)
│
├── tests/                        # Unit and integration tests
│   ├── test_state.py             # State load/save roundtrip tests
│   ├── test_elo.py               # Elo formula correctness tests
│   ├── test_simulator.py         # Simulation probability validation
│   └── integration_test.py       # End-to-end mock API sequence test
│
├── main.py                       # Single entry point — orchestrates everything
├── requirements.txt              # Python dependencies (requests, pytest)
├── README.md                     # Setup & usage instructions (post-MVP)
│
├── SOTs/                         # Source of Truth design documents (already exist)
│   ├── MVP.md                    # MVP overview, components, build plan
│   ├── PRD.md                    # Product requirements, user stories
│   ├── TRD.md                    # Technical requirements, architecture
│   ├── Backend_Schema.md         # Data schemas, module interfaces, API contracts
│   ├── Appflow.md                # Flow diagrams, sequence diagrams, state transitions
│   ├── UI_UX_Design.md           # Console output format, color scheme
│   └── Implementation_plan.md    # Detailed build plan with phases & timeline
│
└── .planning/                    # GSD planning artifacts
    └── codebase/                 # Codebase analysis documents
        ├── ARCHITECTURE.md       # Architecture analysis (this file)
        └── STRUCTURE.md          # Structure analysis (this file)
```

## Directory Purposes

**`data/`:**
- Purpose: Hold all persistent data as human-readable JSON files
- Contains: 4 JSON files — `teams.json` (team Elo ratings and metadata), `bracket.json` (knockout bracket structure), `played.json` (completed matches record), `api_id_mapping.json` (external ID to internal match_id mapping)
- Key files: `teams.json`, `bracket.json`, `played.json`
- Note: Created in Phase 1 of implementation plan. Initial data file is static; `played.json` starts empty and grows; `teams.json` gets rewritten on each Elo update.

**`src/`:**
- Purpose: All application source code organised by module responsibility
- Contains: 7 Python files — `state.py`, `elo.py`, `simulator.py`, `fetcher.py`, `output.py`, `constants.py`, `__init__.py`
- Key files: `state.py` (persistence), `elo.py` (core algorithm), `simulator.py` (Monte Carlo engine)
- Dependency direction: Leaf modules (`state.py`, `elo.py`, `simulator.py`, `fetcher.py`, `output.py`) have no inter-dependencies; `main.py` depends on all of them

**`tests/`:**
- Purpose: Unit and integration tests for all modules
- Contains: 4 test files — `test_state.py`, `test_elo.py`, `test_simulator.py`, `integration_test.py`
- Testing framework: `pytest`
- Key targets: Elo formula correctness, simulation probability distribution, state persistence roundtrips, end-to-end mock API flow

**`SOTs/`:**
- Purpose: Single Source of Truth design documents — already written, define the entire project
- Contains: 7 markdown files covering MVP scope, PRD, TRD, data schemas, app flow, UI/UX, and implementation plan

**Root files:**
- `main.py`: Single entry point for the application. Called with `python main.py`. Options: `--seed`, `--once`, `--no-color`, `--help`.
- `requirements.txt`: Lists `requests` (runtime) and `pytest` (dev).

## Key File Locations

**Entry Points:**
- `main.py`: Sole entry point. Invoked via `python main.py` from project root. Contains the infinite main loop, module coordination, and signal handlers.

**Configuration:**
- `src/constants.py`: All tunable parameters as module-level constants — `K_FACTOR`, `POLL_INTERVAL_SECONDS`, `SIMULATION_COUNT`, `API_URL`, `API_KEY_ENV_VAR`. No config files for MVP.

**Core Logic:**
- `src/elo.py`: Elo formula implementation — `expected_score()`, `update_ratings()`. Pure function, no side effects.
- `src/simulator.py`: Tournament simulation — `simulate_match()`, `run_single_tournament()`, `run_monte_carlo()`. Uses `random` module.
- `src/state.py`: JSON persistence — load/save functions for all data files. Atomic write pattern.
- `src/fetcher.py`: API integration — `fetch_new_results()`. HTTP GET with retry/backoff, JSON parsing, ID mapping.
- `src/output.py`: Console output — `print_header()`, `print_probabilities()`, `print_match_update()`, `print_error()`, `print_heartbeat()`. ANSI color codes.

**Testing:**
- `tests/test_elo.py`: Known-example test cases for Elo formula
- `tests/test_simulator.py`: Probability sum validation, edge cases
- `tests/test_state.py`: Load/save roundtrip, atomic write, empty state handling
- `tests/integration_test.py`: Mock API responses → verify full pipeline from match detection to probability update

**Data:**
- `data/teams.json`: 32 or 16 teams (knockout MVP) with initial Elo ratings
- `data/bracket.json`: Nested knockout tree — `round_of_16` → `quarterfinals` → `semifinals` → `final`
- `data/played.json`: Starts as empty object `{}`; grows as matches complete
- `data/api_id_mapping.json`: Static pre-filled mapping of API numeric IDs to our match IDs

## Naming Conventions

**Files:**
- Snake case for all Python files: `state.py`, `elo.py`, `simulator.py`, `fetcher.py`, `output.py`, `constants.py`, `main.py`. (Conforms to PEP 8.)
- JSON files are lowercase: `teams.json`, `bracket.json`, `played.json`, `api_id_mapping.json`.
- Test files: Prefix with `test_` for pytest auto-discovery: `test_elo.py`, `test_state.py`, `test_simulator.py`, `integration_test.py`.

**Functions:**
- Snake case verbs: `load_teams()`, `save_played_matches()`, `update_ratings()`, `fetch_new_results()`, `simulate_match()`, `run_monte_carlo()`, `print_probabilities()`.
- Boolean-returning functions: `is_match_played()` (if introduced), `is_eliminated()` (if introduced).
- Pure functions named by what they return: `expected_score()` → float, `load_teams()` → dict.

**Variables:**
- Snake case throughout: `last_known_ids`, `played_set`, `played_details`, `elo_a`, `elo_b`, `current_elos`, `n_simulations`, `poll_interval`.
- Module-level constants in `constants.py`: `UPPER_CASE` naming: `K_FACTOR`, `SIMULATION_COUNT`, `API_URL`, `POLL_INTERVAL_SECONDS`, `API_KEY_ENV_VAR`.

**Types:**
- No explicit custom types for MVP (no `@dataclass` or `TypedDict` required — simple dicts suffice).
- Future: If type annotations are desired, use Python 3.10+ `dict[str, float]`, `set[str]`, etc.

## Where to Add New Code

**New Feature:**
- Primary code: Add a new file under `src/` if it represents a new module/responsibility (e.g., `src/group_stage.py` for future group stage). Update `main.py` to integrate it.
- If extending an existing module (e.g., adding a new output format), add functions to the relevant file (`src/output.py`).

**Tests:**
- Unit tests: Add `tests/test_<module>.py` for the new module.
- Integration tests: Add scenarios to `tests/integration_test.py`.

**Data:**
- New persistent data: Add a new JSON file under `data/` and add load/save functions to `src/state.py`.

**Configuration:**
- New tunable parameter: Add a constant to `src/constants.py` and reference it from the consuming module.

**Utilities:**
- Shared helpers: If a common utility (e.g., date formatting, file helpers) is needed across modules, create `src/utils.py`. Currently not needed for MVP — each module is self-contained.

## Special Directories

**`data/`:**
- Purpose: Persistent data storage (JSON files)
- Generated: Yes — `played.json` is generated and grows during runtime; `teams.json` is rewritten when Elo changes. `bracket.json` and `api_id_mapping.json` are static (pre-created).
- Committed: Yes — initial versions of `teams.json`, `bracket.json`, and `api_id_mapping.json` with placeholder data are committed. `played.json` starts empty and is gitignored or committed as `{}`.

**`SOTs/`:**
- Purpose: Source of Truth design documents
- Generated: No — hand-written design specifications
- Committed: Yes — mandatory. These are the project's design authority.

**`tests/`:**
- Purpose: Test files
- Generated: Yes — written during development
- Committed: Yes

---

*Structure analysis: 2026-06-13*
