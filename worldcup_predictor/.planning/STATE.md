---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Prediction Engine Modernization
status: Phase 16 In Progress (1/3 plans), Phases 17-20 Defined
last_updated: "2026-06-18T23:43:00.000Z"
progress:
  total_phases: 20
  completed_phases: 15
  planned_phases: 5
  total_plans: 44
  completed_plans: 42
  percent: 76
---

# Project State

## Project Reference

- See: `.planning/PROJECT.md` (updated 2026-06-14)
- Core value: A live, self-updating tournament predictor in your terminal — when a match ends, within seconds the script detects it, updates Elo, re-simulates, and shows how every team's odds changed
- Current focus: Phase 16 — Model Governance (planned)
- 6 canonical docs generated on 2026-06-16 (README, ARCHITECTURE, GETTING-STARTED, DEVELOPMENT, TESTING, CONFIGURATION)
- Phase 13 executed: 3 plans, 16 commits, 387 tests, 17/17 must-haves VERIFICATION PASSED
- Phase 14 executed: 2 plans, 2 commits, 40 blender tests, 427 total passing
- Phase 14a executed: 1 plan, prediction ledger fix bridging Phase 13/14 gap
- Phase 15 executed: 3 plans, 9 commits, 51 form+lineup tests, 477 total passing
- Test suite: 16 test modules, 477+ passed (post-Phase 15), 1 skipped (live smoke needs BSD_API_KEY)

## Milestones & Completed Phases

### v1.0 MVP — Shipped 2026-06-14

- 6 phases, 10 plans, all complete
- 98 passing tests, ~2,200 LOC Python
- Full details: `.planning/milestones/v1.0-ROADMAP.md`

### v1.1 World Cup 2026 Support — Phases 7-10, shipped 2026-06-14

- 4 phases, 15 plans, 34 commits, all complete
- 48-team dataset, 12 groups (A-L), 495-entry Annex C
- Group stage simulation + full 104-match knockout pipeline
- BSD API integration with group match ingestion
- 212+ passing tests, ~3,200 LOC Python
- Console output: box-drawing group standings + third-place bubble

### Phase 7: 48-Team Dataset & Group Definitions

- 4 plans, 3 waves — teams.json, groups.json, annex_c.json, team_aliases.json
- 48 teams with researched Elo ratings, "USA" → "United States" rename
- 12 groups with 72 round-robin match definitions matching FIFA 2026 draw
- 4 new state.py functions: validate_groups, load_groups, validate_annex_c, load_annex_c
- 23 new tests, 41 total test_state.py tests pass (zero regressions)

### Phase 8: Group Stage Simulation Engine (GROUPS-07 resolved)

- 4 plans, 4 waves, 10 commits — Poisson match simulation
- 7-step H2H-first tiebreaker, Annex C R32 resolution
- 51 group tests + 174 total pass
- 50K iterations in 12.66s (target < 15s) — 64% optimization gain

### Phase 9: Knockout Bracket & Full Pipeline

- 3 plans, 3 waves, 5 commits — 32-match R32 bracket.json with slot descriptors
- knockout.py with run_full_simulation() orchestrator
- TPP from SF losers, bracket validation, 13 new tests
- BRKT-01 through BRKT-08 all satisfied

### Phase 10: Integration, Tests & BSD Verification

- 4 plans, 4 waves — BSD API group match ingestion + played_groups.json persistence
- 12-group standings display with box-drawing and third-place bubble
- 2 deferred test failures fixed, 18 new group integration tests
- Full test suite: 212 passed, 1 skipped, 0 failures
- All 7 SOTs batch-updated for 48-team format

### v2.0 Prediction Engine Modernization — Phases 11-20

**Phase 11: Data Integrity & Elo Foundation** — 3 plans, 2 waves, 12 commits

- 10 Elo sync constants in constants.py (URLs, thresholds, 48-entry team code map)
- 4 persistence functions in state.py (cache + audit log, atomic writes, graceful bootstrap)
- 367-line elo_sync.py with 7 public functions (fetch → parse → validate → resolve → correct → persist)
- Auto-sync wired into main.py startup + 24h periodic timer (+36h wake catch-up)
- 3 display functions in output.py (sync results, staleness warnings, drift flags)
- 45 tests across 7 test classes (TestParse, TestMapping, TestCorrection, TestValidation, TestStaleness, TestCache, TestSyncPipeline)
- Full suite: 276 passed, 1 skipped (live smoke needs BSD_API_KEY)
- V2-01 (48 Elo match eloratings.net within 5pts) and V2-02 (auto-sync every N minutes) satisfied

**Decisions captured in CONTEXT.md (22 decisions across 5 areas):**

- Sync interval: startup + daily (never per-poll)
- World.tsv parsing (not HTML — eloratings.net is a JS SPA)
- Dynamic Elo: hybrid with graduated thresholds (<10 ignore, 10-30 blend, >30 flag)
- Caching: last-known-good, graduated staleness warnings, never block
- Startup: auto-sync, warn-and-continue (never block)

**Phase 12: Draw Handling & Elo Math** — 3 plans, 2 waves, 15 commits

- Plan 12-01 — Elo engine extensions:
  - `compute_k_factor()` step-function: G=1 (GD≤1), G=1.5 (GD=2), G=(11+N)/8 (GD≥3)
  - `update_ratings()` accepts `pk_winner` param for 0.75/0.25 PK split
  - `apply_elo_update()` computes K-multiplier from goal diff + detects PK mode from entry shape
  - 30 Elo tests pass
- Plan 12-02 — Draw pipeline fix:
  - 3 draw-skip sites fixed in fetcher.py:126 (knockout), fetcher.py:314 (group), main.py:251 (historical)
  - Each produces `{winner: null, is_draw: true}` for true draws, `{winner: team, is_draw: false}` for PKs
  - PK detection in knockout paths only (group stage never goes to PKs)
  - 12 fetcher + 18 group integration + 18 main loop tests pass
- Plan 12-03 — Historical backfill & baseline:
  - `_run_draw_backfill()` scans played.json + played_groups.json for draws not yet Elo'd
  - `_record_eval_baseline()` replays all matches through draw-fixed Elo
  - Baseline: Brier=0.127, LogLoss=0.406 (7 matches)
  - 6 backfill tests in test_elo.py + integration tests in test_main_loop.py
- Bug fixes: teams.json corruption (PowerShell `>` mangling UTF-8) fixed via `subprocess.Popen`; 5 TestDrawBackfill tests lacked monkeypatches — fixed
- Final: 300 passed, 1 skipped

**Phase 12b: Evaluation Infrastructure** — 1 plan executed

- `src/evaluation.py`: brier_score(), log_loss(), compute_metrics(), calibration_curve(), expected_calibration_error(), evaluate_all_matches(), compare_baselines()
- `src/state.py` extended: load_prediction_history, append_prediction_history, load_eval_baseline_report, save_eval_baseline_report
- `main.py` refactored: `_record_eval_baseline()` delegates to evaluation.evaluate_all_matches() + state.save_eval_baseline_report()
- 28 tests across 6 test classes in tests/test_evaluation.py
- test_main_loop.py updated: test_baseline_records_brier for new report shape
- Data: `data/eval_baseline_report.json` (Brier=0.127059, LogLoss=0.406068, ECE=0.2335)
- Data: `data/prediction_history.json` (7 per-match entries)
- Full suite: 328 passed, 1 skipped

**Phase 14: Signal Blending** — 2 plans, 2 waves, 2 commits

- `src/blender.py`: 8 exports — Platt calibration, Brier blending, LOO-CV, rolling Brier, Poisson base rate, full `calibrate_and_blend()` pipeline
- `src/knockout.py`: `_get_blended_prob()` helper, `blend_params` wired through all 4 simulation helpers + `run_full_simulation`
- `src/groups.py`: `_POISSON_BASE_RATE_CACHE` + auto-warming in `expected_goals()`
- `main.py`: `_run_calibrate_and_blend()` orchestrator, Poisson base rate warmup, shutdown blend path
- 40 blender tests (1 integration), 427 total passing
- Cold start: identity calibration until ≥30 matches, rolling Brier window 50

**Phase 14a: Prediction Retention Architecture Fix** — 1 plan

Design flaw discovered during operational validation:

Phase 13 caches predictions in TTL-based files (12h odds, 24h CatBoost) that are evicted after expiry. By the time a match finishes and enters `prediction_history`, its pre-match predictions have already been discarded. This prevents multi-signal Brier computation and calibration for Phase 14.

Fix: Permanent prediction ledger (`data/predictions_ledger.json`). Every prediction is written once at fetch time, keyed by `match_id`. Never deleted. TTL caches continue serving live freshness; the ledger serves as the historical archive.

Implementation:
- `src/constants.py`: Added `PREDICTION_LEDGER_FILE`
- `src/state.py`: Added `load_prediction_ledger()`, `save_prediction_ledger()`, `ledger_upsert()`
- `src/predictors/odds.py`: Upsert into ledger after each fetch
- `src/predictors/catboost.py`: Upsert into ledger after each fetch
- `src/main.py`: `_merge_signals_into_history()` reads from ledger instead of TTL caches

**Key decisions (D-01 through D-08 in CONTEXT.md):**

- Prediction history as append-only log (never overwritten)
- Brier per-match as (p - actual)², aggregated as mean
- Log loss epsilon-clamped (1e-15) to avoid log(0)
- Decile-binned calibration with ECE
- Structured baseline report with metrics, calibration bins, history reference
- Comparison workflow with structured delta + verdict
- Separation of concerns: evaluation.py (pure computation), state.py (persistence), main.py (orchestration)

## Current Position

Phase: 16 — MODEL GOVERNANCE — ▼ In Progress
Plans: 1/3 complete (Plan 01: Version Tracking — done), Plans 02-03 remaining
Status: Plan 01 executed — 4 commits, 4 files modified, 16 governance tests passing

- **Next:** Execute Plan 16-02 (Governance Orchestrator + Drift Detection + Dashlet)
- **Plan:** `/gsd-execute-phase 16` (then Phase 17 → 18 → 19 → 20)

## Performance Metrics

**Velocity:**

- Total plans completed: 42 (10 v1.0 + 4 P7 + 4 P8 + 3 P9 + 4 P10 + 3 P11 + 3 P12 + 1 P12b + 3 P13 + 2 P14 + 1 P14a + 3 P15 + 1 P16)
- Total plans planned: 44 (all above + 3 P16); P17-20 TBD
- Average duration: ~10 min per plan (Phases 11-15)
- Total commits: 96 (63 pre-P13 + 16 P13 + 2 P14 + 5 P14a + 6 P15 + 4 P16)

**By Phase:**
| Phase | Plans | Duration | Avg/Plan |
|-------|-------|----------|----------|
| 7 | 4 | 48 min | 12 min |
| 8 | 4 | 39 min | 10 min |
| 9 | 3 | 26 min | 9 min |
| 10 | 4 | ~38 min | ~10 min |
| 11 | 3 | ~28 min | ~9 min |
| 12 | 3 | ~25 min | ~8 min |
| 12b | 1 | ~15 min | ~15 min |
| 13 | 3 | ~40 min | ~13 min |
| 14 | 2 | ~20 min | ~10 min |
| 14a | 1 | ~X min | ~X min |
| 15 | 3 | ~35 min | ~12 min |
| 16 | 1/3 | 6 min (so far) | 6 min (Plan 01) |
| 17 | TBD | defined | — |
| 18 | TBD | defined | — |
| 19 | TBD | defined | — |
| 20 | TBD | defined | — |

**Performance (Phase 8 GROUPS-07):**
| Metric | Value | Status |
|--------|-------|--------|
| 50K iterations | 12.66s | [PASS] (target < 15s) |
| 1K iterations | 0.295s | [PASS] |
| Matches/s | 284,473 | [PASS] |
| Optimization gain | 35.5s → 12.66s (64%) | [PASS] |

## Accumulated Context

### Decisions

- Phase numbering continues from v1.0: v1.1 starts at Phase 7
- Phase ordering enforced by data dependencies: Dataset → Group Engine → Knockout Bracket → Integration
- Requirements map cleanly: DATA2→P7, GROUPS→P8, BRKT→P9, INTG→P10
- No UI/frontend work in v1.1 — purely console CLI
- DEFAULT_FORM_K=1.0 (not 0.6) — empirically validated from 19 matches, form_delta range [-1.01, +1.01]
- DEFAULT_LINEUP_K=0.35 — ln ratio range [-5.31, +5.31] from €7.5M to €1.52B squad values
- D-01 through D-07 (Phase 16): Three-version tracking — data_version increments per D-02 (new match OR new signal), model_version per D-03 (signal change OR calibration refit), run_version per D-04 (ISO 8601). Version IDs stored at entry and file level per D-05. Run snapshots stored in data/runs/ per D-06 with retention enforcement. versions.json at data/versions.json per D-07.

### Resolved in Phase 10

| Category | Item | Resolution |
|----------|------|-----------|
| test | `test_main_loop_runs_iterations` checks "Fetched" → "Polling" | Assertion changed to match current heartbeat text |
| test | `test_expected_goals_very_strong_dominates` expects >10.0, MAX_EXPECTED_GOALS=8.0 | Assertion changed to `== 8.0` with cap rationale comment |
| main_loop | test_main_loop_runs_iterations failure | Fixed in Plan 03 — docstring updated, test passes |
| integration | BSD API group match ingestion + played_groups.json | Implemented in Plan 01 |
| display | Group standings box-drawing + third-place bubble | Implemented in Plan 02 |
| e2e | Full pipeline integration tests | Implemented in Plan 03 (18 new tests) |

### Deferred Items

| Category | Item | Deferred At |
|----------|------|-------------|
| verification | End-to-end with real Football-Data.org API key (superseded by BSD) | v1.0 close |
| smoke | Live BSD smoke test requires manual BSD_API_KEY | Phase 10 |
| utf8 | JSON encoding on Windows must use `encoding='utf-8'` (default cp1252) | Phase 9 close |
| test | test_scaffold.py::test_teams_json_exists_and_valid asserts isinstance(int) but teams.json has floats | Pre-existing, found P15-01 |
| governance | Per-match backtest history belongs in Phase 18 | Phase 16 |
| governance | BSD API as backtest data source violates offline constraint | Phase 16 |
| governance | Auto-recalibrate on drift deferred — alert-only for Phase 16 | Phase 16 |
| governance | Full state dump per run deferred — lean snapshots only | Phase 16 |

### Research Flags (resolved)

| Phase | Flag | Resolution |
|-------|------|-----------|
| Phase 7 | Annex C data source extraction; 48-team Elo rating initialization | Annex C sourced from verified FIFA mirror, Elo assigned via formula |
| Phase 8 | Poisson goal model calibration; fair play card distribution data | Calibrated base_rate=1.25, fair play Poisson(2.0 YC, 0.05 RC) |
| Phase 9 | R32 bracket integration with Annex C routing; TPP match simulation | R32 slot descriptors, Annex C, TPP all implemented |
| Phase 10 | BSD API group match response format; 48-team alias coverage | group_name field identified for split routing, aliases expanded |

## Session Continuity

- Last session: 2026-06-18
- Phase 16 Plan 01 executed: 4 commits, 4 files, version tracking foundation complete
  - Added 6 governance constants to constants.py
  - Added 6 governance persistence functions to state.py
  - Created src/governance.py with 4 pure version computation functions
  - Created tests/test_governance.py with 16 passing tests
  - V2-12 satisfaction: D-01 through D-07 fully implemented
  - 0 regressions on 469+ passing tests
- Phase 15 fully executed: 3 plans (15-01: data layer, 15-02: form.py + lineup.py, 15-03: main.py wiring + 51 new tests). 477 tests passing. k_form=1.0, k_lineup=0.35.
- Phase 16 context discussion complete: 4 areas covered (Versioning, Backtesting, Drift Detection, Governance Output). CONTEXT.md + DISCUSSION-LOG.md written.
- Phase 16 research complete: 10 integration points analyzed, 8 pitfalls catalogued, validation architecture mapped.
- Phase 16 planned: 3 plans (16-01 complete, 16-02 and 16-03 remaining).
- **Phase 17-20 redesigned to target 85% API coverage: P17 Enriched Match Context, P18 xG & AI Signals, P19 Multi-League Framework, P20 Output & Coverage Seal**
- Next: Execute Plan 16-02 (Governance Orchestrator + Drift Detection + Dashlet).
