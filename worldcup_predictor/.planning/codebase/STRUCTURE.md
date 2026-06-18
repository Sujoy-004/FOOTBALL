# Codebase Structure

**Analysis Date:** 2026-06-16

**Status:** Implemented — 11 src modules, 16 test files, 14 data files, 329 tests.

## Directory Layout

```
worldcup_predictor/
├── src/                           # 11 application source modules
│   ├── __init__.py                # Package marker (empty)
│   ├── constants.py               # All tunable parameters (101 lines)
│   ├── state.py                   # JSON persistence + validation (573 lines)
│   ├── elo.py                     # Elo rating formula (146 lines)
│   ├── groups.py                  # Group stage simulation, tiebreakers (715 lines)
│   ├── knockout.py                # Full tournament pipeline (268 lines)
│   ├── simulation.py              # Legacy v1.0 knockout-only MC (86 lines)
│   ├── fetcher.py                 # BSD API polling + match processing (288 lines)
│   ├── elo_sync.py                # Elo sync from eloratings.net (292 lines)
│   ├── evaluation.py              # Prediction quality metrics (118 lines)
│   └── output.py                  # Console formatting + ANSI colors (318 lines)
│
├── tests/                         # 16 test files
│   ├── conftest.py                # Shared test fixtures
│   ├── fixtures/                  # Test data fixtures
│   ├── test_state.py              # State load/save roundtrip
│   ├── test_elo.py                # Elo formula correctness
│   ├── test_groups.py             # Group simulation, standings, tiebreakers
│   ├── test_knockout.py           # Full knockout pipeline
│   ├── test_simulation.py         # Legacy MC simulation
│   ├── test_fetcher.py            # API polling + match processing
│   ├── test_output.py             # Console output formatting
│   ├── test_elo_sync.py           # Elo sync from eloratings.net
│   ├── test_evaluation.py         # Prediction metrics
│   ├── test_cli.py                # CLI argument parsing
│   ├── test_integration.py        # End-to-end mock API flow
│   ├── test_main_loop.py          # Main loop orchestration
│   ├── test_group_integration.py  # Group match integration tests
│   ├── test_scaffold.py           # Skeleton/structure tests
│   ├── test_state_load.py         # State loading edge cases
│   └── test_live_smoke.py         # Live BSD API smoke test (needs API key)
│
├── data/                          # 14 JSON data files
│   ├── teams.json                 # 48 teams with Elo, group, FIFA rank
│   ├── bracket.json               # 40-match knockout bracket
│   ├── groups.json                # 12 group definitions (A–L)
│   ├── annex_c.json               # 495-entry Annex C lookup table
│   ├── team_aliases.json          # BSD API name variations for 48 teams
│   ├── played.json                # Completed knockout matches (runtime)
│   ├── played_groups.json         # Completed group matches (runtime)
│   ├── prediction_history.json    # Probability history (runtime)
│   ├── elo_applied.json           # Elo sync changes (runtime)
│   ├── elo_update_log.json        # Elo sync audit (runtime)
│   ├── eloratings_cache.json      # Cached eloratings.net data (runtime)
│   ├── eval_baseline.json         # Evaluation baseline (runtime)
│   └── eval_baseline_report.json  # Evaluation report (runtime)
│
├── main.py                        # Entry point — infinite polling loop
├── requirements.txt               # pip dependencies
├── .env.example                   # Environment variable template
├── README.md                      # Setup & usage instructions
├── RESPONSE.md                    # Architecture response doc
├── MODERNIZATION-PROPOSAL.md      # Future improvements proposal
│
├── benchmarks/                    # Performance benchmarks
├── scripts/                       # Utility scripts
├── docs/                          # Generated documentation
│
└── .planning/                     # GSD planning artifacts
    └── codebase/                  # Codebase analysis docs (this file)
```

## Directory Purposes

**`src/`:**
- All application source code organized by module responsibility
- 11 Python modules (2905 total lines)
- Dependency direction: Leaf modules have no inter-dependencies; `main.py` depends on all

**`tests/`:**
- Unit and integration tests for all modules
- 16 test files, 329 tests, 1 skipped (requires BSD_API_KEY)
- Testing framework: `pytest >= 9.0`

**`data/`:**
- Static JSON files: teams, bracket, groups, annex_c, team_aliases
- Runtime JSON files: played (knockout), played_groups (group), prediction_history, elo sync, evaluation

## Key File Locations

**Entry Points:**
- `main.py`: `python main.py` — infinite poll loop, module coordination, signal handlers
- `python -m src.elo_sync`: Standalone Elo sync CLI

**Configuration:**
- `src/constants.py`: `K_FACTOR`, `POLL_INTERVAL`, `SIMULATION_COUNT`, `API_URL`, `DEFAULT_ELO`, group constants

**Core Logic:**
- `src/elo.py`: Elo formula — `expected_score()`, `update_ratings()`, `apply_elo_update()`
- `src/groups.py`: Group simulation — `simulate_group_matches()`, `compute_standings()`, `rank_third_placed()`, `resolve_r32_matchups()`
- `src/knockout.py`: Full pipeline — `run_full_simulation()`, `run_knockout()`
- `src/simulation.py`: Legacy — `run_simulation()` (v1.0 knockout-only)
- `src/state.py`: JSON persistence — load/save for all data files. Atomic write pattern
- `src/fetcher.py`: API integration — `fetch_new_results()`, `process_group_matches()`, `process_matches()`
- `src/evaluation.py`: Metrics — Brier score, log loss, calibration
- `src/elo_sync.py`: Elo correction — graduated approach, audit logging
- `src/output.py`: Console output — `print_header()`, `print_probabilities()`, `print_group_standings()`, ANSI colors

**Testing:**
- `tests/test_groups.py`: Group simulation, tiebreaker chains, Annex C resolution
- `tests/test_knockout.py`: Full tournament pipeline correctness
- `tests/test_integration.py`: End-to-end mock API flow

## Naming Conventions

- Snake case for all Python files
- JSON files are lowercase
- Test files: `test_<module>.py` prefix for pytest auto-discovery
- Functions: snake_case verbs: `load_teams()`, `update_ratings()`, `compute_standings()`
- Constants: `UPPER_SNAKE_CASE` in `constants.py`

---

*Structure analysis: 2026-06-16*
