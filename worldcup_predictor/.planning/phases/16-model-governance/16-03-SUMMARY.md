---
phase: 16-model-governance
plan: 03
subsystem: backtesting
tags: historical-data, elo-replay, offline-benchmark

requires:
  - phase: 16-01
    provides: state persistence layer, governance constants
  - phase: 16-02
    provides: _run_governance() orchestrator
  - phase: 12b-evaluation-infrastructure
    provides: compute_metrics, calibration_curve, brier_score, log_loss
  - phase: 01-state-elo-foundation
    provides: expected_score(), apply_elo_update()

provides:
  - data/historical/2018.json: 64 2018 World Cup matches with correct outcomes
  - data/historical/2022.json: 64 2022 World Cup matches with correct outcomes
  - backtest_tournament() in evaluation.py: replays historical tournaments through Elo pipeline
  - 5+ backtest unit tests in test_evaluation.py verifying metrics, winner prediction, deep-copy, empty handling

affects:
  - 16-03 Task 3 (_run_backtest orchestrator — deferred)

tech-stack:
  added: none (stdlib only: json, copy, math)
  patterns:
    - Deep-copy state before replay (Pitfall 6 guard)
    - Historical match data in prediction_history signal shape with Architecture Q1 fields
    - PK-decided matches stored as actual=0.5 with winner set and is_draw=false
    - True draws stored as actual=0.5 with winner=null and is_draw=true

key-files:
  created:
    - data/historical/2018.json: 64 match entries for 2018 World Cup
    - data/historical/2022.json: 64 match entries for 2022 World Cup
  modified:
    - src/evaluation.py: Added backtest_tournament() function (131 lines)
    - tests/test_evaluation.py: Added TestBacktestTournament class (6 tests, 117 lines)

key-decisions:
  - "Historical match data uses Architecture Q1 fields: winner, is_draw, home_score, away_score alongside actual"
  - "PK-decided matches (actual=0.5) have winner set and is_draw=false (prevents faulty metric computation)"
  - "Elo signal probability set to 0.5 as placeholder — overwritten by Elo replay in backtest_tournament"
  - "n_signals < 2 → blended omitted from report (Architecture Q3)"
  - "Empty tournament list returns empty report without crashing"

requirements-completed:
  - V2-14

duration: ongoing
completed: 2026-06-19
---

# Phase 16 Plan 03: Backtesting Framework Summary (Tasks 1-2)

**Historical tournament data files (2018+2022 World Cups) and backtest_tournament() evaluation pipeline with 6 comprehensive TDD tests — 41 evaluation tests pass, zero regressions**

## Performance

- **Duration:** Ongoing (Task 3 deferred to separate agent)
- **Started:** 2026-06-19T00:00:00Z
- **Completed:** 2026-06-19T00:15:00Z (Tasks 1-2)
- **Tasks:** 2 (1 auto, 1 TDD: RED+GREEN)
- **Files created/modified:** 4 (2 created, 2 modified)

## Accomplishments

- **Historical tournament data files** — `data/historical/2018.json` (64 matches) and `data/historical/2022.json` (64 matches). Each entry includes team_a, team_b, actual, winner, is_draw, home_score, away_score, and signals.elo. All 128 matches have correct results, scores, and winners verified against actual World Cup outcomes.
- **PK-decided matches handled correctly** — Croatia vs Denmark (2018 R16), Russia vs Spain (2018 R16), Argentina vs France (2022 Final), Croatia vs Brazil (2022 QF), Japan vs Croatia (2022 R16), Morocco vs Spain (2022 R16), and others: stored as actual=0.5, winner set, is_draw=false.
- **backtest_tournament() function** — replays historical matches chronologically through Elo expected_score() before each match, collects (prediction, actual) pairs, then applies Elo update. Computes per-signal Brier, log_loss, ECE metrics. Determines winner prediction (highest initial Elo team). Returns structured report with per_signal metrics, winner_prediction, signal_ranking.
- **Pitfall 6 guard** — deep-copies teams dict before replay; verified by test that original is unchanged.
- **Empty tournament list** — returns empty report gracefully (no crash).
- **n_signals < 2** — blended omitted from report (Architecture Q3).
- **6 TDD tests** — basic report structure, metrics correctness, winner prediction, empty list, deep-copy, single-signal report.

## Task Commits

Each task committed atomically (TDD RED/GREEN for Task 2):

1. **Task 1: Create historical tournament data files (2018 + 2022)** — `51dc8e2` (feat)
2. **Task 2 RED: Add failing tests for backtest_tournament** — `d5e27b9` (test)
3. **Task 2 GREEN: Implement backtest_tournament** — `56d3518` (feat)

## Files Created/Modified

- `data/historical/2018.json` — 64 match entries, 2018 World Cup results (new file)
- `data/historical/2022.json` — 64 match entries, 2022 World Cup results (new file)
- `src/evaluation.py` — Added `backtest_tournament()` function with deep-copy, Elo replay, metric computation, winner prediction, signal ranking (+131 lines)
- `tests/test_evaluation.py` — Added `TestBacktestTournament` class with 6 tests: basic, metrics, winner_prediction, empty, deepcopy, single_signal (+117 lines)

## Decisions Made

- **Architecture Q1 fields included**: Each historical match dict includes `winner`, `is_draw`, `home_score`, `away_score` alongside `actual`. This enables downstream analysis tools to distinguish PK-decided matches from true draws.
- **PK handling**: PK matches use `actual=0.5` (consistent with aggregate prediction task) but set `winner` and `is_draw=false`. This prevents faulty metric computation that would occur if PK matches were treated as true draws.
- **Elo signal placeholder**: `signals.elo.probability` is set to 0.5 in historical files. The `backtest_tournament()` function overwrites this by computing actual Elo expected scores during replay.
- **No per-match history**: Following D-15, the report is per-tournament (not per-match). Individual predictions/actuals are used for aggregate metric computation only.
- **Task 3 deferred**: `_run_backtest()` orchestrator, startup wiring, and governance integration will be handled by a separate agent.

## Deviations from Plan

None — plan executed exactly as written (Tasks 1-2 only).

## Issues Encountered

- **Flaky test**: `test_main_loop_clean_shutdown` — a pre-existing flaky integration test (passes on retry). Not related to backtest changes.

## Threat Surface

All mitigations from threat register T-16-06 (JSON parse validation), T-16-07 (deep copy guard), and T-16-08 (try/except around backtest in _run_backtest — will be implemented in Task 3) are accounted for.

## TDD Gate Compliance

- [x] RED commit exists: `d5e27b9` — `test(16-03): add failing tests for backtest_tournament`
- [x] GREEN commit exists: `56d3518` — `feat(16-03): implement backtest_tournament for historical tournament replay`
- [x] RED commit precedes GREEN commit

## Deferred Items

- Task 3 of Plan 16-03 (`_run_backtest` orchestrator, governance integration, startup wiring) is deferred to a separate agent.

## Self-Check: PASSED

- [x] `data/historical/2018.json` exists with 64 match entries
- [x] `data/historical/2022.json` exists with 64 match entries
- [x] Each entry has match_id, team_a, team_b, actual, signals.elo shape
- [x] Both files pass JSON validation
- [x] `src/evaluation.py` has `backtest_tournament()` function
- [x] 41 evaluation tests pass (35 original + 6 new)
- [x] 3 commits: feat(16-03) → test(16-03) → feat(16-03)
- [x] Fan-in reference data shape matches prediction_history.json signal dict format
- [x] PK-decided matches correctly flagged (winner set, is_draw=false)
- [x] Elo state deep-copied before replay (Pitfall 6)

---

*Phase: 16-Model-Governance*
*Completed: 2026-06-19*
