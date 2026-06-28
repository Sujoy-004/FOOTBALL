---
phase: 03-ucl-orchestration-display
plan: 01
subsystem: orchestration-cli
tags: ["cli", "argparse", "dataclass", "result-contract"]

# Dependency graph
requires:
  - phase: 01-ucl-league-table-engine
    provides: Monte Carlo simulation (run_monte_carlo, simulate_league_phase)
  - phase: 02-ucl-knockout-phase
    provides: Knockout pipeline (playoff, bracket, tree, stage tracking)
provides:
  - SimulationResult dataclass — the abstract result contract consumed by all display functions (D-15, D-16, D-17)
  - ucl-predict CLI entry point with -n/--iterations, -s/--seed, -o/--output flags
  - sample_result fixture for downstream display tests

affects:
  - 03-ucl-orchestration-display (plans 02, 03: display layer)
  - 04-bsd-validation (Phase 4 consumes SimulationResult contract)

# Tech tracking
tech-stack:
  added: ["dataclasses (frozen)", "argparse"]
  patterns: ["SimulationResult as abstract result contract", "Orchestration imports simulation internals, display imports only result.py"]

key-files:
  created:
    - competitions/ucl/result.py — SimulationResult frozen dataclass
    - competitions/ucl/main.py — CLI entry point with _parse_args() and main()
    - competitions/ucl/tests/test_cli.py — 6 argparse unit tests
  modified:
    - competitions/ucl/__init__.py — re-exports SimulationResult and main
    - competitions/ucl/tests/conftest.py — added sample_result fixture

key-decisions:
  - "SimulationResult uses frozen=True and JSON-native types (list[dict], dict[str, dict]) for direct asdict() serialization"
  - "CLI uses string path for --output (not argparse.FileType) to avoid premature file truncation (Pitfall 5)"
  - "build_simulation_result() runs MC for probabilities + one extra iteration for bracket snapshot (run_monte_carlo() returns no per-iteration bracket data — Pitfall 2)"
  - "Same seed reused for MC and bracket iteration for deterministic display"
  - "Pre-loaded data files passed to knockout functions to avoid per-call disk I/O"

patterns-established:
  - "Contract layer: result.py (stdlib-only) — display depends on this"
  - "Orchestration layer: main.py — imports simulation internals, assembles result, prints output"
  - "D-17 enforcement: result.py imports zero competition internals; verifiable via grep"

requirements-completed: ["UCLO-01"]

# Metrics
duration: 8min
completed: 2026-06-28
---

# Phase 3 Plan 1: SimulationResult Contract + CLI Entry Point Summary

**SimulationResult frozen dataclass, ucl-predict CLI with 3 argparse flags, conftest fixture, and 6 argparse unit tests — establishing the three-layer orchestration architecture**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-28T18:00:37Z
- **Completed:** 2026-06-28T18:08:34Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Created `SimulationResult` frozen dataclass at `competitions/ucl/result.py` — the architectural spine of Phase 3 with 11 fields covering summary metadata, standings, per-team probabilities, playoff ties/bracket rounds, stage tracking, and stage order
- Created `ucl-predict` CLI at `competitions/ucl/main.py` with `_parse_args()` (3 flags: `-n`/`--iterations`, `-s`/`--seed`, `-o`/`--output`) and `main()` orchestrating MC simulation → bracket iteration → `SimulationResult` assembly → JSON export
- Added `sample_result` fixture to `conftest.py` producing a full 36-team `SimulationResult` with 8 playoff ties, 4 bracket rounds (R16/QF/SF/FINAL), and all 36 stage entries — ready for downstream display tests in plans 02 and 03
- Added 6 argparse unit tests at `test_cli.py` covering defaults, individual flags, combined flags, and non-int rejection
- Updated `__init__.py` to re-export `SimulationResult` and `main`

## Task Commits

Each task was committed atomically:

1. **Task 1: SimulationResult dataclass + conftest fixture + __init__.py** — `61b5a1c` (feat)
2. **Task 2: main.py CLI entry point** — `8dbdb46` (feat)
3. **Task 3: test_cli.py argparse tests** — `17d57b2` (test)

## Files Created/Modified

- `competitions/ucl/result.py` (NEW) — `SimulationResult` frozen dataclass with 11 fields
- `competitions/ucl/main.py` (NEW) — CLI entry point with `_parse_args()` and `main()`
- `competitions/ucl/tests/test_cli.py` (NEW) — 6 argparse unit tests
- `competitions/ucl/__init__.py` (MODIFIED) — re-exports `SimulationResult` and `main`
- `competitions/ucl/tests/conftest.py` (MODIFIED) — added `sample_result` fixture

## Decisions Made

- **SimulationResult uses frozen=True** — prevents mutation after construction; safe for passing between layers
- **CLI uses string path for --output** — avoids `argparse.FileType` which truncates at parse time (Pitfall 5); file opened only after successful simulation
- **Single seed for both MC and bracket iteration** — the representative bracket is deterministic and consistent with MC output; seed reported to user for reproducibility
- **Pre-loaded data files** — `build_simulation_result()` loads `playoff_pairings.json` and `bracket_rules.json` once and passes them to knockout functions, avoiding redundant disk I/O inside the iteration

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all tasks completed on first pass with zero errors.

## Known Stubs

None — all created files are fully functional. The `sample_result` fixture in conftest.py is production-grade (36 teams, 8 playoffs, 4 bracket rounds).

## Next Phase Readiness

- `SimulationResult` contract is stable and ready for display layer (plans 02, 03)
- `sample_result` fixture available for display unit tests
- CLI entry point is functional and tested — ready for integration testing
- D-17 enforcement verified: `result.py` has zero imports from `competitions.ucl.src`

---

*Phase: 03-ucl-orchestration-display*
*Completed: 2026-06-28*
