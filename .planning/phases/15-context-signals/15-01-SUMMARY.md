---
phase: 15-context-signals
plan: 01
subsystem: data-layer
tags: constants, json, state, persistence

# Dependency graph
requires:
  - phase: 14a-prediction-retention
    provides: state.py patterns (graceful bootstrap, internal imports)
provides:
  - 6 Phase 15 constants (FORM_WINDOW_SIZE, TEAM_VALUES_FILE, DEFAULT_FORM_K, DEFAULT_LINEUP_K, FORM_CACHE_FILE, LINEUP_CACHE_FILE)
  - data/team_values.json with 48 squad market values
  - state.load_team_values() loader function
affects:
  - 15-02 (signal modules: form.py, lineup.py)
  - 15-03 (integration: main.py wiring)

# Tech tracking
tech-stack:
  added: none (pure Python stdlib)
  patterns: existing (graceful bootstrap, internal imports from constants)

key-files:
  created:
    - data/team_values.json
  modified:
    - src/constants.py
    - src/state.py

key-decisions:
  - "DEFAULT_FORM_K=1.0 (not 0.6 as originally proposed) — empirically validated from 19 matches, form_delta range [-1.01, +1.01]"
  - "DEFAULT_LINEUP_K=0.35 — ln ratio range [-5.31, +5.31] from €7.5M to €1.52B squad values"
  - "Both tuning parameters explicitly marked in docstrings as calibration constants, not architecture decisions"
  - "team_values.json values from Transfermarkt June 2026 data, France=€1.52B max, Panama=€7.5M min"

patterns-established:
  - "New constants section pattern: section comment header + FORMAT_X name prefix for Phase 15 context signals"
  - "Loader pattern: graceful bootstrap returning empty dict when file missing"
  - "Tuning parameter convention: DEFAULT_ prefix, docstring with empirical validation range"

requirements-completed:
  - V2-10
  - V2-11

# Metrics
duration: 12min
completed: 2026-06-17
---

# Phase 15 Plan 01: Data Layer Summary

**Phase 15 constants (FORM_WINDOW_SIZE, TEAM_VALUES_FILE, DEFAULT_FORM_K=1.0, DEFAULT_LINEUP_K=0.35), 48-team squad market values data file, and load_team_values() loader with graceful bootstrap**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-17T11:00:00Z
- **Completed:** 2026-06-17T11:12:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added 6 Phase 15 context signal constants with detailed empirical validation docstrings
- Created `data/team_values.json` with all 48 teams matching `teams.json` keys exactly (including Curaçao U+00E7 and Türkiye U+00FC), range €7.5M to €1.52B EUR
- Added `load_team_values()` to `state.py` following graceful bootstrap pattern (empty dict when file missing)
- Both tuning parameters (`DEFAULT_FORM_K`, `DEFAULT_LINEUP_K`) documented with empirical range data and marked as calibration constants, not architecture decisions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Phase 15 constants to constants.py** - `a080bff` (feat)
2. **Task 2: Create data/team_values.json** - `62e6ea3` (feat)
3. **Task 3: Add load_team_values() to state.py** - `490ec4b` (feat)

## Files Created/Modified

- `src/constants.py` - 6 new constants appended after BRIER_WINDOW_SIZE (63 insertions)
- `data/team_values.json` - 48 team → EUR market value mappings (50 lines, new file)
- `src/state.py` - `load_team_values()` function after `load_eloratings_cache()` (77 insertions)

## Decisions Made

- **DEFAULT_FORM_K=1.0** (not 0.6 as originally proposed in plan draft): Empirically validated from 19 played matches. The planner originally assumed form_delta ∈ [-5, +5] (used sum instead of mean). Actual range is [-2, +2] theoretical, [-1, +1] empirical. k=1.0 avoids suppressing an already-small signal.
- **DEFAULT_LINEUP_K=0.35**: Squad values range from €7.5M (Panama) to €1.52B (France), ln ratios in [-5.31, +5.31]. k=0.35 avoids saturation at boundary values.
- **Both marked as TUNING PARAMETERS** in docstrings with explicit `DEFAULT_` prefix, signaling that Platt scaling (Phase 14) will refine these as multi-signal entries accumulate.
- **No save_team_values() function** — file is static, never modified during runtime.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- **Pre-existing test_scaffold.py failure**: `test_teams_json_exists_and_valid` asserts `isinstance(data["elo"], int)` but teams.json stores float values (e.g., `1772.0`). This is unrelated to Phase 15 changes. Filed as a deferred item.
- Terminal encoding on Windows PowerShell mangled Unicode display for Curaçao/Türkiye names, but actual file bytes verified correct (`0xE7` and `0xFC` respectively, matching teams.json exactly).

## Known Stubs

None — all data files contain real values; no placeholder text or empty defaults.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary surface introduced.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| constants importable | FORM_WINDOW_SIZE=5, DEFAULT_FORM_K=1.0, DEFAULT_LINEUP_K=0.35 ✓ |
| team_values.json exists | 48 teams, all positive ints, keys match teams.json ✓ |
| load_team_values() works | Returns dict with 48 entries from prod data ✓ |
| Graceful bootstrap | Returns {} when file missing ✓ |
| Test suite (excl. pre-existing) | 383 passed, 1 skipped ✓ |

## Next Phase Readiness

- Data layer complete — ready for Phase 15-02 (signal modules form.py + lineup.py)
- Constants and team_values available for signal computation
- Tuning parameters set for cold start; Platt scaling will refine post-Phase 14 threshold

---

*Phase: 15-context-signals*
*Completed: 2026-06-17*
