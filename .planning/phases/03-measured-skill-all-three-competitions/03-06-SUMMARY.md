---
phase: 03-measured-skill-all-three-competitions
plan: 06
subsystem: evaluation
tags: [worldcup, historical-corpus, leak-free-primitives, knockout-mapping, elo, openfootball]

# Dependency graph
requires:
  - phase: 02-truthful-availability-explicit-verified-ingestion
    provides: verified ingestion infrastructure, atomic write primitives, truthful availability patterns
provides:
  - WC leak-free primitives (KO-aware outcome_index, two-way renormalization, prior-only context)
  - WC historical corpus: 488 real matches across 7 tournaments (2002-2026) from openfootball
  - WC contract + builder + sources (window-generic national-team acquisition)
  - COVERAGE.md with accepted/excluded tournament provenance
affects: [03-07, 03-08, worldcup-evaluation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "KO-aware outcome_index: advancing winner (0/2, never 1) with two-way renormalization"
    - "Window-generic national-team results adapter with exclude-and-report semantics"
    - "Provenance-tracked corpus acquisition with SHA-256 verification"

key-files:
  created:
    - competitions/worldcup/src/historical.py
    - competitions/worldcup/tests/test_worldcup_historical.py
    - competitions/worldcup/historical_backfill/__init__.py
    - competitions/worldcup/historical_backfill/contract.py
    - competitions/worldcup/historical_backfill/build.py
    - competitions/worldcup/historical_backfill/sources/__init__.py
    - competitions/worldcup/historical_backfill/sources/results_intl.py
    - competitions/worldcup/historical_backfill/sources/elo_snapshots.py
    - competitions/worldcup/data/historical/ (23 files: 7 seasons x {matches, elo_ratings, PROVENANCE}.json + replay_2002_2026.json + COVERAGE.md)
  modified: []

key-decisions:
  - "KO target is the advancing winner (0/2, never 1); forecast renormalized two-way p_home/(p_home+p_away)"
  - "No date-indexed historical national-team Elo feed exists; per-tournament elo_ratings.json left empty with coverage gap recorded"
  - "Corpus acquired solely from openfootball (CC0-1.0); bracket-slot labels from data/played.json never consumed as team identities"
  - "All 7 contracted tournaments (2002-2026) acquired successfully; zero exclusions"

patterns-established:
  - "WC historical.py: KO-aware outcome_index with two-way renormalization (D-05/D-06 declared once)"
  - "Window-generic results adapter: fetch() returns None for absent tournaments, never []"
  - "Provenance schema: source URL + license + SHA-256 per tournament"

requirements-completed: [EVAL-01]

# Metrics
duration: 40min
completed: 2026-10-16
---

# Phase 03 Plan 06: WC Historical Corpus & Leak-Free Primitives Summary

**488 real World Cup matches (2002-2026) acquired from openfootball with KO-aware leak-free primitives, two-way renormalization, and honest Elo coverage gaps**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-10-16T08:00:00Z
- **Completed:** 2026-10-16T08:53:20Z
- **Tasks:** 3 (2 code + 1 human-verify checkpoint)
- **Files modified:** 11 source/test files + 23 corpus data files

## Accomplishments

- WC leak-free primitives with KO-aware `outcome_index` (advancing winner, never draw) and `two_way_renormalize` — D-05/D-06 declared once and reconciled with `football_core/elo.py:37`
- Real national-team corpus: 488 matches across 7 tournaments (2002-2026) from openfootball (CC0-1.0), with per-tournament PROVENANCE.json (source URL + license + SHA-256)
- Contract-owned window (SEASONS, REPLAY_NAME) with exclude-and-report semantics for absent tournaments
- COVERAGE.md naming all accepted tournaments, signal availability (rolling_form/rest_days available; market_odds/refined_elo/squad_value honestly absent), and knockout mapping

## Task Commits

Each task was committed atomically:

1. **task 1: WC leak-free primitives with KO-aware label and two-way renormalization** - `8ce2d46` (feat)
2. **task 2: WC contract, sources, builder + real corpus acquisition** - `9f225d6` (feat)
3. **task 3: verify the World Cup corpus is real** - human-verify checkpoint approved (no code commit)

## Files Created/Modified

- `competitions/worldcup/src/historical.py` - WC-specific leak-free primitives: `outcome_index` (KO-aware), `is_knockout`, `two_way_renormalize`, `build_context_for_match`, `ReplayResultProvider`, `frequency_baseline`, `load_replay_matches`
- `competitions/worldcup/tests/test_worldcup_historical.py` - 29 tests covering KO label, two-way renormalization, leak guard, group vs KO end-to-end
- `competitions/worldcup/historical_backfill/__init__.py` - Package init
- `competitions/worldcup/historical_backfill/contract.py` - SEASONS (7 tournaments), REPLAY_NAME, HISTORICAL_DIR, match_id, __all__
- `competitions/worldcup/historical_backfill/build.py` - build() orchestrator: fetch, validate, write_season_dataset, merge replay, COVERAGE.md
- `competitions/worldcup/historical_backfill/sources/__init__.py` - Sources package init
- `competitions/worldcup/historical_backfill/sources/results_intl.py` - Window-generic national-team results adapter (openfootball)
- `competitions/worldcup/historical_backfill/sources/elo_snapshots.py` - National-team Elo snapshots (wraps elo_sync, records coverage gaps)
- `competitions/worldcup/data/historical/` - 23 files: 7 seasons x {matches.json, elo_ratings.json, PROVENANCE.json} + replay_2002_2026.json + COVERAGE.md

## Decisions Made

- **KO target = advancing winner (0/2, never 1):** A level score with no recorded advancing winner returns `None` (never a fabricated draw). Forecast renormalized two-way: `s = p_home + p_away; [p_home/s, 0, p_away/s]`.
- **No date-indexed Elo feed exists:** eloratings.net serves only the current TSV; date-indexed URLs return HTTP 404. Per-tournament `elo_ratings.json` left empty with coverage gap recorded in PROVENANCE.json. `available_signals` reports `refined_elo` as `insufficient_data:no_elo_ratings`. Using current TSV as per-tournament snapshot would leak up to 24 years of subsequent results — forbidden.
- **Corpus source: openfootball only (CC0-1.0):** Real national teams, real scores, real event_dates. Bracket-slot labels from `data/played.json` never consumed as team identities.
- **All 7 tournaments acquired:** 2002, 2006, 2010, 2014, 2018, 2022, 2026. Zero exclusions. 1998 deliberately absent (predates D-01 window).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The build ran cleanly on first execution. All automated checks pass:
- 29/29 tests in `test_worldcup_historical.py` pass
- Contract imports work (7 tournaments)
- Build module imports work with no network access
- No bracket-slot labels in historical_backfill source
- COVERAGE.md exists with comprehensive provenance

## Human Verification

Task 3 (checkpoint:human-verify) was approved by the user on 2026-10-16. The user verified:
- 488 real matches from openfootball across 7 tournaments (2002-2026)
- Real acquisition, not synthesized
- Elo gap is honest (no date-indexed feed exists)
- No bracket-slot labels used as team identities

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- WC corpus is ready for 03-07 (shared report renderer) and 03-08 (WC block publication)
- The leak-free primitives are ready for the driver in 03-08
- The KO mapping (D-05/D-06) is declared and reconciled
- No blockers for downstream phases

---
*Phase: 03-measured-skill-all-three-competitions*
*Completed: 2026-10-16*
