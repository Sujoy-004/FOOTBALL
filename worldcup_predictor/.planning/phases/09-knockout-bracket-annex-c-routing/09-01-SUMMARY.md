---
phase: 09-knockout-bracket-annex-c-routing
plan: 01
subsystem: data
tags: [bracket, knockout, r32, r16, qf, sf, tpp, final, annex-c, slot-descriptors]
requires:
  - phase: 08-group-stage-simulation-engine
    provides: group standings, Annex C third-place resolution
provides:
  - 32-match knockout bracket (R32→R16→QF→SF→TPP→FINAL) replacing 23-match v1.0 bracket
  - Slot descriptors for R32: group_position (1/2) and annex_c_third kinds
  - FIFA Article 12.7 fixed R16 wiring
affects:
  - phase-10-integration-live-data
  - simulation.py (requires bracket reader for new slot format)
  - test_state_load.py (requires update for new bracket structure)
tech-stack:
  added: []
  patterns:
    - R32 matches use home/away slot descriptor objects instead of hardcoded team_a/team_b strings
    - R16+ matches use source_matches array (unchanged from v1.0)
    - annex_c_third slots store the group_winner whose opponent should be resolved via Annex C lookup
key-files:
  created: []
  modified:
    - worldcup_predictor/data/bracket.json
key-decisions:
  - "Corrected spec arithmetic: 16+8+4+2+1+1=32 matches, not 40 — a knockout bracket from 32 advancing teams always has 32 matches"
  - "Used M73-M88 for R32, M89-M96 for R16 (matching FIFA Article 12.7 convention per architecture research)"
  - "M83/M84 swapped vs ARCHITECTURE.md: K2 vs L2 at M83, H1 vs J2 at M84 (matches FIFA fixture order, not architecture diagram ordering)"
requirements-completed:
  - BRKT-01
duration: 5 min
completed: 2026-06-14
---

# Phase 9 Plan 1: Knockout Bracket — 32-Match R32→FINAL Format with Slot Descriptors

**Replaced bracket.json with the full 32-match knockout bracket using slot descriptors for R32 (group_position and annex_c_third kinds), FIFA Article 12.7 fixed R16 wiring, and existing source_matches pattern for QF→FINAL**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-14T18:15:00Z
- **Completed:** 2026-06-14T18:20:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- 16 R32 matches (M73-M88) with slot descriptors: 4x ru-vs-ru, 4x winner-vs-ru, 8x winner-vs-annex_c_third
- 8 R16 matches (M89-M96) wired per FIFA Article 12.7 fixed routing
- 4 QF matches, 2 SF matches, TPP, FINAL (all using source_matches pattern)
- No hardcoded team names — all R32 slots use kind-typed descriptors

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace bracket.json with 32-match format** - `24e770d` (feat)

## Files Created/Modified
- `worldcup_predictor/data/bracket.json` - 32 matches (was 23), using slot descriptors for R32

## Decisions Made
- **Corrected match count:** The spec states 40 matches, but 16+8+4+2+1+1 = 32 for a knockout bracket starting at R32 (32 advancing teams → 16 R32 matches). The 40 was an arithmetic error.
- **M83/M84 ordering:** ARCHITECTURE.md shows M83=H1 vs J2, M84=K2 vs L2. The spec (and FIFA fixture order) places K2 vs L2 at M83, H1 vs J2 at M84. Followed spec as authoritative.
- **Slot descriptor design:** `home`/`away` objects with `kind`, `group`, `position` or `group_winner` keys, matching the architecture research's proposed structure exactly.

## Deviations from Plan

### Spec Correction

**1. [Spec Arithmetic Error] Match count corrected from 40 to 32**
- **Found during:** Verification
- **Issue:** Spec states "16 + 8 + 4 + 2 + 1 + 1 = 40 matches" but this arithmetic is incorrect (equals 32). A knockout bracket from 32 advancing teams always generates 32 matches.
- **Fix:** Created 32 matches (correct count), updated verification assertions accordingly
- **Verification:** All 32 matches verified structurally correct with correct round distribution
- **Committed in:** `24e770d`

---

**Total deviations:** 1 spec correction
**Impact on plan:** Minimal — corrected a counting error in the specification. No structural impact.

## Issues Encountered
None — plan executed correctly with one spec arithmetic correction noted above.

## Known Stubs
None — the bracket contains no stub data. All matches use valid slot descriptors, and winner values are initialized to null (ready for simulation).

## Next Phase Readiness
- bracket.json ready for Phase 9 Plan 2 (R32/knockout simulation integration)
- BRKT-01 requirement satisfied: bracket defines all knockout matches with slot descriptors
- Next: Phase 9 Plan 2 — R32 simulation (resolve group_position and annex_c_third slots)
## Self-Check: PASSED

- ✅ bracket.json: 32 matches, valid JSON, correct structure
- ✅ SUMMARY.md: created and committed
- ✅ feat(09-01) commit: `24e770d`
- ✅ docs(09-01) commit: `75bc9ed`
- ✅ All structural assertions pass (round counts, slot types, source_matches wiring, FIFA Article 12.7 R16 routing)

---

*Phase: 09-knockout-bracket-annex-c-routing*
*Completed: 2026-06-14*
