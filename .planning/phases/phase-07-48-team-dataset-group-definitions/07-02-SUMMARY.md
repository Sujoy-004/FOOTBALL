---
phase: 07-48-team-dataset-group-definitions
plan: 02
subsystem: data
tags: [groups, annex-c, third-place, team-aliases, world-cup-2026]

requires:
  - phase: 07-01
    provides: teams.json with 48 canonical team keys
provides:
  - groups.json with 12 groups (A-L), 4 teams each, 72 match definitions
  - annex_c.json with 495 third-place routing entries from FIFA Annex C
  - team_aliases.json extended to cover all 48 teams
affects:
  - phase 08 (group simulation)
  - phase 09 (knockout bracket)
  - phase 10 (live integration)

tech-stack:
  added: none
  patterns: itertools.combinations for round-robin match generation

key-files:
  created:
    - worldcup_predictor/data/groups.json
    - worldcup_predictor/data/annex_c.json
  modified:
    - worldcup_predictor/data/team_aliases.json

key-decisions:
  - "Used official FIFA 2026 World Cup group draw (verified via sportsbrackets.net, roadtowc.com, and FIFA.com) for group assignments"
  - "Parsed Annex C from Wikipedia template (source: FIFA 2026 Competition Regulations) — 495 entries verified against all 5 structural invariants"
  - "Preserved Ivory Coast and DR Congo in team_aliases — these ARE qualified teams per official draw, contrary to out-of-date planning notes"
  - "Added known BSD API aliases for 12 teams with common alternative names; remaining 36 teams get empty arrays"

patterns-established:
  - "groups.json: top-level 'groups' object with A-L keys, each containing 'teams' (4) and 'matches' (6 round-robin)"
  - "annex_c.json: _meta key at top, then 495 data keys sorted as comma-separated group letters"
  - "team_aliases.json: canonical team name keys from teams.json, BSD API alternative names as values"

requirements-completed: [DATA2-02, DATA2-03, DATA2-04]

duration: 12min
completed: 2026-06-14
---

# Phase 7: 48-Team Dataset & Group Definitions — Plan 2 Summary

**Official FIFA 2026 World Cup group draw with 12 groups, 72 round-robin match definitions, 495-entry Annex C third-place routing table, and 48-team alias coverage**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-14T12:00:00Z (approx)
- **Completed:** 2026-06-14T12:12:00Z (approx)
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 extended)

## Accomplishments

- **groups.json**: 12 groups (A-L) with official FIFA 2026 draw composition, 4 teams each, 6 round-robin matches per group (72 total), all team names cross-validated against teams.json
- **annex_c.json**: 495-entry FIFA Annex C third-place routing table parsed from Wikipedia template (FIFA 2026 Competition Regulations source), with _meta metadata, valid for all 5 structural invariants
- **team_aliases.json**: Extended from 11 to 48 entries, removed 4 non-qualifiers (Great Britain, North Korea, Eswatini, North Macedonia), preserved known BSD aliases, added empty arrays for teams without known variations

## Task Commits

Each task was committed atomically:

1. **Task 1: Create groups.json with 12 groups x 4 teams, 72 round-robin match definitions** - `3f0036d` (feat)
2. **Task 2: Create annex_c.json with 495 entries from verified FIFA data** - `7c23118` (feat)
3. **Task 3: Extend team_aliases.json to cover all 48 teams** - `ba27799` (feat)

## Files Created/Modified

- `worldcup_predictor/data/groups.json` (created) - 12 group definitions with round-robin match slots
- `worldcup_predictor/data/annex_c.json` (created) - 495-entry third-place routing table
- `worldcup_predictor/data/team_aliases.json` (modified) - Extended from 11 to 48 alias entries

## Decisions Made

- **Group draw source:** Used official FIFA 2026 draw results (finalized April 2026 after playoff resolution) — Czech Republic, Bosnia and Herzegovina, Türkiye, Sweden, Iraq, and DR Congo confirmed as playoff winners
- **Annex C source:** Parsed from Wikipedia template (which transcludes official FIFA data) rather than algorithmic generation — ensures correctness mandated by plan
- **Non-qualifier handling:** Corrected plan's notes that listed Ivory Coast and DR Congo as non-qualifiers — both ARE in the official qualified teams (Ivory Coast in Group E, DR Congo in Group K)
- **Alias accuracy:** Added only known/common BSD API name variations; empty arrays for teams without established alternative names

## Deviations from Plan

### Deviation Applied (Rule 2 - Data Correction)

**1. [Rule 2 - Data Accuracy] Preserved Ivory Coast and DR Congo in team_aliases.json**
- **Found during:** Task 3 (Extend team_aliases.json)
- **Issue:** Plan's initial context listed "Ivory Coast" and "DR Congo" as non-qualifying teams to be removed. However, official FIFA 2026 group draw confirms both ARE qualified — Ivory Coast (Group E), DR Congo (Group K). Removing them would break `set(team_aliases.keys()) == set(teams.keys())`.
- **Fix:** Preserved both entries with their existing aliases
- **Files modified:** team_aliases.json (left them untouched)
- **Verification:** `set(team_aliases.keys()) == set(teams.keys())` passes with 48 entries
- **Committed in:** `ba27799` (Task 3 commit)

---

**Total deviations:** 1 (1 data accuracy correction)
**Impact on plan:** Necessary correction to align with ground truth. The plan's non-qualifier list was based on pre-playoff assumptions that were superseded by actual results.

## Issues Encountered

- Wikipedia template parsing for Annex C required handling multiple row formats (first row has `rowspan`, subsequent rows are flat). Parser was tested and validated against all 5 structural invariants.
- File encoding (UTF-8 with accented characters) caused minor verification assertion issues for "Côte d'Ivoire" alias — resolved by using repr-based comparison.

## Next Phase Readiness

- **All three data files required by downstream phases are ready:**
  - `groups.json` → consumed by Phase 8 group simulation engine
  - `annex_c.json` → consumed by Phase 9 knockout bracket (Round of 32 routing)
  - `team_aliases.json` → consumed by Phase 10 live integration (BSD API name resolution)
- Ready for **Plan 3 (state.py integration)** to add load_groups(), load_annex_c(), validate_groups(), and validate_annex_c()

---
*Phase: 07-48-team-dataset-group-definitions*
*Completed: 2026-06-14*
