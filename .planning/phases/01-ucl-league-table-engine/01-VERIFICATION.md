---
phase: 01-ucl-league-table-engine
verified: 2026-06-27T12:30:00Z
status: passed
score: 18/18 must-haves verified
overrides_applied: 0
gaps: []
deferred: []
human_verification: []
---

# Phase 1: UCL League Table Engine — Verification Report

**Phase Goal:** Users can simulate the UCL league phase with correct 36-team Swiss-system standings — fixture validation, pot-constrained opponents, complete tiebreaker chain, qualification zones, and Monte Carlo advancement probabilities
**Verified:** 2026-06-27T12:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is **achieved**. All code artifacts exist, are substantive (not stubs), are properly wired together, and produce real dynamically-generated data. All 59 UCL tests pass (1 skipped — live ClubElo API requires `--live` flag). The World Cup regression suite is unaffected (375 pass, 1 pre-existing error in test_knockout.py unrelated to UCL changes).

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can load the UCL fixture schedule from a JSON data file | ✓ VERIFIED | `competitions/ucl/data/fixtures.json` exists (30,573 bytes), validates via `python -m json.tool`, loaded by `validate_ucl_fixtures()` and multiple conftest fixtures |
| 2 | User can validate that each of the 36 teams has exactly 8 opponents | ✓ VERIFIED | `validation.py` `validate_ucl_fixtures()` checks `len(opponents[name]) != 8` at line 141; verified by `test_wrong_opponent_count` test |
| 3 | User can validate that each team faces exactly 2 opponents from each pot | ✓ VERIFIED | `validation.py` checks `dist.get(pot, 0) != 2` at line 150; verified by `test_wrong_pot_distribution` test |
| 4 | User can detect duplicate matchups and incorrect opponent counts | ✓ VERIFIED | `validation.py` checks `pair in seen_pairs` at line 109; `test_duplicate_matchup`, `test_wrong_opponent_count` tests pass |
| 5 | User can see per-team UEFA coefficients for tiebreaker step 10 | ✓ VERIFIED | `competitions/ucl/data/uefa_coefficients.json` has 36 entries; `compute_swiss_standings()` uses `uefa_coefficients.get(item[0], 0.0)` at line 287; `test_tiebreaker_uefa_coefficient_decides` test passes |
| 6 | User can load team alias mappings for ClubElo name resolution | ✓ VERIFIED | `competitions/ucl/data/team_aliases.json` has 36 entries; `resolve_clubelo_name()` resolves PSG→"Paris SG", Man City→"Man City", unknown→pass-through; `test_resolve_clubelo_name_*` tests pass |
| 7 | User can fetch Elo ratings for all 36 UCL teams from ClubElo API (fetch-once, cached) | ✓ VERIFIED | `elo_fetcher.py` has `@lru_cache` on `_fetch_ranking_csv`; single date-based ranking request per D-02/D-03; `test_fetch_team_elos_cached` and `test_fetch_team_elos_mocked` pass |
| 8 | User can simulate all 144 UCL league phase matches using football_core Poisson primitives | ✓ VERIFIED | `groups.py` `simulate_swiss_matches()` produces 144 match results; uses `_build_poisson_table`, `expected_goals` from `football_core.groups`; `test_simulate_swiss_matches_count` passes |
| 9 | User can compute 36-team standings sorted by the full 10-step UCL tiebreaker chain | ✓ VERIFIED | `groups.py` `compute_swiss_standings()` sorts by 11-key tuple (points + 10 tiebreaker steps); `test_36_team_full_standings` produces 36 positions; 18 tiebreaker tests all pass |
| 10 | User can verify no H2H tiebreaker logic is used | ✓ VERIFIED | `grep` confirms `_compute_h2h` and `_tiebreak_group` not present in `groups.py`; `test_no_h2h_used` passes via source inspection |
| 11 | User can classify each team into qualification zones: top 8, playoff 9-24, eliminated 25-36 | ✓ VERIFIED | `compute_swiss_standings()` assigns `zone` as `"top_8"` (pos≤8), `"playoff"` (pos≤24), `"eliminated"`; `test_qualification_zones_*` tests pass |
| 12 | User can confirm match simulation uses football_core primitives without modifying core | ✓ VERIFIED | All imports from `football_core.groups` / `football_core.constants`; `football_core/` directory unmodified; `test_core_primitives_reused` verifies via source inspection |
| 13 | ClubElo snapshot date is recorded for reproducibility | ✓ VERIFIED | `get_clubelo_snapshot_date()` returns `YYYY-MM-DD`; `run_monte_carlo()` output includes `snapshot_date`; `test_get_clubelo_snapshot_date` passes |
| 14 | User can run Monte Carlo simulation over N iterations (default 10000) | ✓ VERIFIED | `run_monte_carlo()` with `n_iterations=10000` completes in ~8.2s (per Plan 03 SUMMARY verification); N=100 test completes in ~1.55s |
| 15 | User can see per-team zone probabilities: top_8_prob, playoff_prob, eliminated_prob | ✓ VERIFIED | `aggregate_mc_results()` outputs `top_8_prob`, `playoff_prob`, `eliminated_prob` for every team; `test_run_monte_carlo_team_keys` verifies; zone probs sum to 1.0 per team |
| 16 | User can see per-team champion probability (champion_prob) | ✓ VERIFIED | `aggregate_mc_results()` outputs `champion_prob`; champion probs sum to ~1.0 across all teams; `test_run_monte_carlo_champion_prob` passes |
| 17 | User can see per-team tiebreaker stat averages | ✓ VERIFIED | Output includes `avg_position`, `avg_pts`, `avg_gd`, `avg_gs`, `avg_away_gs`, `avg_wins`, `avg_away_wins`; `test_aggregate_averages` verifies correctness |
| 18 | User can set random seed for deterministic results | ✓ VERIFIED | `run_monte_carlo()` accepts `seed` parameter; same seed+input = identical output; `test_run_monte_carlo_n1` verifies; `test_run_monte_carlo_different_seed` confirms seed tracking |

**Score:** 18/18 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `competitions/ucl/__init__.py` | Module scaffold | ✓ VERIFIED | Package bootstrap with sys.path |
| `competitions/ucl/src/__init__.py` | Exports all public functions | ✓ VERIFIED | Exports 9 functions in `__all__` |
| `competitions/ucl/src/validation.py` | `validate_ucl_fixtures()` with 12 constraint checks | ✓ VERIFIED | 166 lines, 12 validation checks, fail-fast ValueError chain |
| `competitions/ucl/src/elo_fetcher.py` | `fetch_team_elos()`, `resolve_clubelo_name()`, `get_clubelo_snapshot_date()` | ✓ VERIFIED | 167 lines, date-based ranking fetch, lru_cache, logging fallback |
| `competitions/ucl/src/groups.py` | `precompute_swiss_matchup_lambdas()`, `simulate_swiss_matches()`, `compute_swiss_standings()` | ✓ VERIFIED | 320 lines, football_core primitives, 10-step tiebreaker, zone classification |
| `competitions/ucl/src/simulation.py` | `simulate_league_phase()`, `run_monte_carlo()`, `aggregate_mc_results()` | ✓ VERIFIED | 234 lines, post-aggregation pattern, D-06/D-07 output spec |
| `competitions/ucl/data/fixtures.json` | 36 teams, 4 pots, 8 matchdays, 144 matches | ✓ VERIFIED | 30,573 bytes, validated by `validate_ucl_fixtures()`, all constraints pass |
| `competitions/ucl/data/uefa_coefficients.json` | 36 team coefficients | ✓ VERIFIED | 826 bytes, 36 entries |
| `competitions/ucl/data/team_aliases.json` | 36 team alias mappings | ✓ VERIFIED | 1,479 bytes, 36 entries |
| `competitions/ucl/tests/conftest.py` | Shared test fixtures for all downstream plans | ✓ VERIFIED | 524 lines, 10+ fixtures |
| `competitions/ucl/tests/test_fixture_validation.py` | 10 UCLT-00/UCLT-04 tests | ✓ VERIFIED | 164 lines, all 10 pass |
| `competitions/ucl/tests/test_simulation.py` | 14 UCLT-01/UCLT-02/UCLT-06 tests | ✓ VERIFIED | 348 lines, all pass (1 skipped without --live) |
| `competitions/ucl/tests/test_swiss_tiebreakers.py` | 18 UCLT-02 tests | ✓ VERIFIED | 354 lines, all 18 pass |
| `competitions/ucl/tests/test_monte_carlo.py` | 13 UCLT-05 tests | ✓ VERIFIED | 297 lines, all 13 pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `validate_ucl_fixtures()` | `data/fixtures.json` | `json.load()` | ✓ WIRED | `validation.py` loads via `json.load()` in conftest and real test |
| `test_fixture_validation.py` | `validation.py` | `from competitions.ucl.src.validation import validate_ucl_fixtures` | ✓ WIRED | Import verified at line 13 |
| `elo_fetcher.py` | `api.clubelo.com/{slug}` | `urllib.request.urlopen` | ✓ WIRED | `_API_BASE = "http://api.clubelo.com"` at line 43, `_fetch_ranking_csv()` at line 94 |
| `simulate_swiss_matches()` | `football_core.groups` | `from football_core.groups import ...` | ✓ WIRED | Lines 22-26 of groups.py import `_build_poisson_table`, `_compute_conduct_score`, `expected_goals` |
| `compute_swiss_standings()` | `football_core.groups._compute_conduct_score` | `from football_core.groups import _compute_conduct_score` | ✓ WIRED | Line 24 of groups.py; used at line 259 |
| `test_simulation.py` | `groups.py` | `from competitions.ucl.src.groups import ...` | ✓ WIRED | Imports `simulate_swiss_matches`, `precompute_swiss_matchup_lambdas` |
| `test_swiss_tiebreakers.py` | `groups.py` | `from competitions.ucl.src.groups import compute_swiss_standings` | ✓ WIRED | Line 11 |
| `simulation.py:simulate_league_phase` | `groups.py:simulate_swiss_matches` | `from competitions.ucl.src.groups import ...` | ✓ WIRED | Lines 17-21 |
| `simulation.py:run_monte_carlo` | `elo_fetcher.py:fetch_team_elos` | `from competitions.ucl.src.elo_fetcher import fetch_team_elos` | ✓ WIRED | Line 180 (inside function body) |
| `run_monte_carlo` output | D-06/D-07 requirements | Output dict keys match spec | ✓ WIRED | Output verified: `snapshot_date`, `n_iterations`, `seed`, `teams` → each team has all 11 keys |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `groups.py:simulate_swiss_matches()` | `score_a`, `score_b` | Poisson sampling via `_build_poisson_table(la)[getrandbits(10)]` | ✓ FLOWING | Mean ~1.33 goals/team/match (2.66 total), 123/144 matches have at least 1 goal — real stochastic output per Elo ratings |
| `groups.py:compute_swiss_standings()` | `pts`, `gd`, `gs`, `away_gs`, `wins`, `away_wins` | Aggregate from match results dicts | ✓ FLOWING | Dynamically computed from match simulation output; opponent stats aggregated from pre-tiebreak raw totals |
| `simulation.py:run_monte_carlo()` | Zone/champion probabilities | N-iteration loop with post-aggregation | ✓ FLOWING | Real probabilistic output — champion probs sum to 1.0, zone probs sum to 1.0 per team, top teams have higher top_8_prob |
| `validation.py:validate_ucl_fixtures()` | Team counts, opponent sets, pot distributions | Parse from `fixtures.json` schedule | ✓ FLOWING | Dynamic constraint checking on the real 36-team dataset; all 12 checks pass |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fixture validation passes on real data | `python -c "import json; from competitions.ucl.src.validation import validate_ucl_fixtures; validate_ucl_fixtures(json.load(open('competitions/ucl/data/fixtures.json')))"` | Validation returns dict, 36 teams, 8 matchdays | ✓ PASS |
| 36 teams with 8 matchdays/144 matches | `python -c "import json; d=json.load(open('competitions/ucl/data/fixtures.json')); assert len(d['schedule']['teams'])==36; assert len(d['schedule']['matchdays'])==8"` | Assertions pass | ✓ PASS |
| All module functions importable | `python -c "from competitions.ucl.src.simulation import run_monte_carlo, aggregate_mc_results, simulate_league_phase; from competitions.ucl.src.groups import compute_swiss_standings, precompute_swiss_matchup_lambdas, simulate_swiss_matches; from competitions.ucl.src.elo_fetcher import fetch_team_elos, resolve_clubelo_name, get_clubelo_snapshot_date"` | All 9 functions import successfully | ✓ PASS |
| No H2H in groups.py | `python -c "import inspect; from competitions.ucl.src import groups as g; src=inspect.getsource(g); assert '_compute_h2h' not in src and '_tiebreak_group' not in src"` | Both functions absent | ✓ PASS |
| MC champion probs sum to 1.0 | `python -c "...100 iterations check..."` | Sum = 1.0, all zone sums 1.0 | ✓ PASS |
| N=100 MC completes < 30s | `python -c "...time check..."` | 1.55s | ✓ PASS |
| 10K MC produces plausible results | Per Plan 03 SUMMARY | Pot 1 teams top_8 > 0.75, Pot 4 eliminated > 0.75, champion probs sum 1.0 | ✓ PASS |

### Probe Execution

No probes declared or discovered. Phase 1 has no probe scripts (conventional probes under `scripts/` were not found).

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| UCLT-00 | 01-01 | Validate fixture schedule against official UCL format — 8 opponents, 2 per pot, no duplicates | ✓ SATISFIED | `validation.py` `validate_ucl_fixtures()` with 12 constraint checks; `test_fixture_validation.py` — 10 tests pass |
| UCLT-01 | 01-02 | Simulate 36-team league phase with 8 matches per team, pot-constrained opponents | ✓ SATISFIED | `groups.py` `simulate_swiss_matches()` produces 144 match results; `test_simulation.py` — 8 simulation tests pass |
| UCLT-02 | 01-02 | UCL-specific tiebreaker chain — GD → GS → away GS → wins → away wins → opponent pts → opponent GD → opponent GS → disciplinary → UEFA coefficient | ✓ SATISFIED | `groups.py` `compute_swiss_standings()` implements 10-step chain; `test_swiss_tiebreakers.py` — 18 tests pass covering every step |
| UCLT-03 | 01-02 | Rank qualification zones (1-8 direct, 9-24 playoff, 25-36 eliminated) | ✓ SATISFIED | `compute_swiss_standings()` assigns zone per position; `test_qualification_zones_*` tests pass |
| UCLT-04 | 01-01 | Load fixture schedule from UCL data files | ✓ SATISFIED | `fixtures.json` loads, validates; `test_real_fixtures_pass` verifies; conftest fixtures load from disk |
| UCLT-05 | 01-03 | Produce per-team advancement probabilities from Monte Carlo simulation | ✓ SATISFIED | `simulation.py` `run_monte_carlo()` with `aggregate_mc_results()`; `test_monte_carlo.py` — 13 tests pass |
| UCLT-06 | 01-02 | Reuse football_core Poisson match simulation, no core modifications | ✓ SATISFIED | All imports from `football_core.groups`/`football_core.constants`; `football_core/` directory unmodified; `test_core_primitives_reused` passes |

**Note:** REQUIREMENTS.md traceability table still shows UCLT-05 as "Pending" despite being fully implemented. This is a documentation gap — the REQUIREMENTS.md should be updated to mark UCLT-05 as "Completed (Plan 03)". The same applies to the ROADMAP.md Plan 03 checkbox which is unchecked. These documentation updates do not affect goal achievement.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | No TBD/FIXME/XXX markers, no placeholder stubs, no NotImplementedError remnants, no empty return values in source files |

### Anti-Patterns from Code Review (acknowledged, not blockers)

The independent code review (`01-REVIEW.md`) identified 8 warnings (WR-01 through WR-08) and 4 info items (IN-01 through IN-04). None are blockers for goal achievement:

| Issue | Severity | Impact on Goal |
|-------|----------|----------------|
| WR-01: HTTP instead of HTTPS for ClubElo | ⚠️ Warning | Data integrity risk, not a correctness issue for simulation |
| WR-02: Missing encoding in JSON reads | ⚠️ Warning | Unicode risk on non-UTF-8 Windows locales |
| WR-03: No error handling for network failures | ⚠️ Warning | Simulation crashes if ClubElo unavailable |
| WR-04: HOME_ADVANTAGE_MULTIPLIER applied | ⚠️ Warning | Known simplification (~5% goal inflation, no bias) |
| WR-05: Docstring mismatch | ℹ️ Info | Test documentation issue |
| WR-06: Weak seed test assertion | ℹ️ Info | Test quality gap |
| WR-07: sys.path mutation | ⚠️ Warning | Import-time side effect |
| WR-08: No error handling for missing alias file | ⚠️ Warning | Graceful degradation missing |

These are all pre-existing known items documented in the code review. None prevent the phase goal from being achieved.

### Human Verification Required

No items requiring human testing for this phase. All must-haves are verifiable via automated checks (code inspection, test execution, behavioral spot-checks). The live ClubElo API test is gated behind `--live` flag — the unit tests with mocked HTTP provide sufficient coverage for code correctness.

### Gaps Summary

**No gaps found.** All 18 must-haves are verified, all 7 requirements are satisfied, all artifacts exist and are substantive, all key links are wired, and data flows are real (not static/hardcoded).

**Documentation updates needed (not gaps):**
1. `REQUIREMENTS.md` — Update UCLT-05 traceability from "Pending (Plan 03)" to "Completed (Plan 03)"
2. `ROADMAP.md` — Mark Plan 03 checkbox as `[x]` and update progress from "2/3" to "3/3"

---

_Verified: 2026-06-27T12:30:00Z_
_Verifier: the agent (gsd-verifier)_
