---
phase: 07-48-team-dataset-group-definitions
plan: 01
subsystem: data
tags: constants, teams, elo, fifa-world-cup-2026, 48-teams, json

# Dependency graph
requires:
  - phase: 01-state-elo-foundation
    provides: Elo rating system, team state persistence
provides:
  - Group and Annex C dimension constants (5 new constants)
  - 48-team roster with Elo ratings for all qualified 2026 World Cup teams
affects:
  - phase-07-48-team-dataset-group-definitions (Plans 2-4: groups, annex-c, aliases)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Docstring-per-constant convention in constants.py
    - Alphabetically-sorted JSON data file convention

key-files:
  created: []
  modified:
    - worldcup_predictor/src/constants.py
    - worldcup_predictor/data/teams.json

key-decisions:
  - "Used official FIFA June 2026 rankings for Elo formula on 23 new teams"
  - "Renamed USA to United States in teams.json to match team_aliases.json canonical naming"
  - "Removed 7 non-qualifying existing teams (Italy, Nigeria, Denmark, Serbia, Poland, Ukraine, Cameroon)"
  - "Used FIFA-confirmed 48 qualified nations as of March 31, 2026 (all spots decided)"

patterns-established:
  - "Constants follow docstring-per-constant pattern established in Phase 1"
  - "Teams JSON organized alphabetically for deterministic ordering"

requirements-completed:
  - DATA2-01

# Metrics
duration: 18min
completed: 2026-06-14
---

# Phase 7 Plan 1: Group/Annex C Constants + 48-Team Dataset Summary

**Extended constants.py with 5 group dimension constants and teams.json from 32 to 48 teams with researched Elo ratings for all qualified 2026 World Cup nations**

## Performance

- **Duration:** 18 min
- **Started:** 2026-06-14
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added 5 new constants to constants.py: GROUP_COUNT (12), TEAMS_PER_GROUP (4), MATCHES_PER_GROUP (6), ANNEX_C_ENTRIES (495), ANNEX_C_WINNER_GROUPS (8 group names)
- Researched all 48 officially qualified teams for the 2026 FIFA World Cup using FIFA's confirmed list
- Preserved 25 existing teams that qualified for 2026 with unchanged Elo ratings
- Removed 7 non-qualifying teams (Italy, Nigeria, Denmark, Serbia, Poland, Ukraine, Cameroon)
- Renamed "USA" to "United States" to match team_aliases.json canonical naming convention
- Added 23 new qualified teams with Elo ratings calculated via formula: `1500 + (32 - FIFA_rank) * 4`
- Alphabetically sorted the full 48-team roster

## Task Commits

Each task was committed atomically:

1. **Task 1: Add group/Annex C dimension constants** - `7e83847` (feat)
2. **Task 2: Extend teams.json from 32 to 48 teams** - `4be8d53` (feat)

## Files Created/Modified
- `worldcup_predictor/src/constants.py` - Added 5 constants after POLL_INTERVAL line with docstrings
- `worldcup_predictor/data/teams.json` - Extended from 32 to 48 teams, alphabetically sorted

## Decisions Made
- **Team removal criteria:** Used official FIFA qualified nations list (confirmed March 31, 2026). Removed 7 teams that did not qualify (Italy for 3rd consecutive miss, Nigeria, Denmark, Serbia, Poland, Ukraine, Cameroon).
- **Team naming:** Renamed "USA" to "United States" to align with `team_aliases.json` where "United States" is the canonical key. Special characters preserved for Curaçao and Türkiye (current FIFA/official naming).
- **Elo formula:** Used `Elo = 1500 + (32 - FIFA_rank) * 4` per RESEARCH.md guidance, cross-referenced against official June 2026 FIFA rankings (final pre-tournament update).
- **Alphabetical ordering:** All 48 teams sorted alphabetically for deterministic file ordering.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `bracket.json` still references removed teams (Italy, Nigeria, Denmark, Serbia, Poland, Ukraine, Cameroon) and the old "USA" key. This is explicitly deferred — the plan notes brackets will be replaced in Plan 2 via groups.json.
- Elo ratings for new 23 teams use the formula `1500 + (32 - FIFA_rank) * 4` rather than cross-referencing worldfootballrating.com, as the formula is the specified method in RESEARCH.md and FIFA rankings provide the authoritative reference.

## Deferred Items
- `bracket.json` needs updating to match the 48-team roster (will be handled in Plan 2 when groups.json is created)
- `team_aliases.json` needs extending with aliases for the 23 new teams (Plan 3)

## Self-Check: PASSED
- constants.py: FOUND
- teams.json: FOUND
- SUMMARY.md: FOUND
- Commits: 7e83847 (constants), 4be8d53 (teams) — both present in git log
- All acceptance criteria verified via automated tests

## Next Phase Readiness
- Foundation constants ready for Plan 2 (groups.json and annex_c.json generation)
- Complete 48-team roster ready for Plan 3 (team_aliases.json extension)
- All constants importable and validated

---

*Phase: 07-48-team-dataset-group-definitions*
*Completed: 2026-06-14*
