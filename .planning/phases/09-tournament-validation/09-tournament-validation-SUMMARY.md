---
phase: 09-tournament-validation
plan: 01-03
type: execute
subsystem: validation
tags: [trps, evaluation, validation-suite, walk-forward, replay, cli, baseline]
requires: [06-simulation-modes, 08-signal-blending-market-integration]
provides: [trps-metric, validation-framework, uncalibrated-baseline]
affects: [10-probability-calibration-uncertainty]
tech-stack:
  added: [numpy]
  patterns: [three-tier-validation, walk-forward-cv, confidence-calibration]
key-files:
  created:
    - competitions/ucl/src/validation_suite.py
    - competitions/ucl/tests/test_validation_suite.py
    - competitions/ucl/data/baseline_uncalibrated.json
  modified:
    - football_core/evaluation.py
    - football_core/tests/test_evaluation.py
    - competitions/ucl/tests/conftest.py
    - competitions/ucl/main.py
    - competitions/ucl/tests/test_cli.py
decisions:
  - "TRPS: uniform rank weights initially; champion-weighting deferred as enhancement"
  - "ECE: confidence-based binning (max predicted probability) for 3-class output"
  - "Validation report: structured dict matching D-04 schema, JSON-serializable"
  - "Seasons_data: flexible dict format allowing both real and synthetic season data"
duration: 9
completed_date: 2026-07-03
metrics:
  total_tests_added: 68
  total_tests_passing: 529
  files_created: 3
  files_modified: 5
---

# Phase 9 Tournament Validation: Summary

Three-tier tournament validation framework measuring prediction quality at match-level (walk-forward), tournament-level (TRPS cross-tournament backtest), and calibration level (replay validation), establishing the uncalibrated baseline for Phase 10 before/after comparison.

## Plans Executed

| Plan | Type | Tasks | Key Output |
|------|------|-------|------------|
| 09-01 | execute | 1 | TRPS + multi-class evaluation metrics |
| 09-02 | execute | 1 | ValidationSuite with Tier 2 (walk-forward) + Tier 3 (replay) |
| 09-03 | execute | 2 | Tier 1 (cross-tournament) + run_all() + baseline + CLI |

## Key Outcomes

### TRPS (Tournament Rank Probability Score)
- **Implemented** `trps()` in `football_core/evaluation.py` per Ekstrøm et al. (2021)
- Pure numpy implementation with (R x T) matrix, cumulative distribution comparison
- Optional rank weighting with broadcasting support
- `validate_tournament_matrix()` helper ensures well-formed inputs (column sums=1, rank range) with descriptive ValueError messages

### Multi-Class Evaluation Helpers
- `multi_class_log_loss()` — epsilon-clamped, handles 3-outcome (home/draw/away)
- `multi_class_brier()` — sum of squared differences across 3 classes, divided by 3N
- `multi_class_ece()` — confidence-based binning using max predicted probability, adaptive binning for small samples

### ValidationSuite Class
- **ValidationResult** dataclass: tier, date, n_matches, n_seasons, metrics, details, baseline flag
- **Tier 1 — Cross-Tournament Backtest:**
  - Chronological splitting: source seasons < eval season
  - Predicted ranking from engine evaluation aggregated across matches
  - TRPS, champion accuracy, stage accuracy (Jaccard similarity per stage group)
  - Stage groups: champion (1), runner-up (1), semifinal (2), QF (4), R16 (8), playoff (8), eliminated (12)
- **Tier 2 — Walk-Forward Match-Level:**
  - Sliding window temporal splits with shift(1) feature context
  - Per-season and macro-averaged metrics (log_loss, brier, ece)
- **Tier 3 — Replay Validation:**
  - Matchday-by-matchday injection of real results
  - Confidence-based calibration across all decision points
  - Per-matchday breakdown + overall calibration bins

### Combined Report & Baseline
- `run_all()` merges all three tiers into D-04 structured dict
- `save_baseline()` writes `baseline_uncalibrated.json` for Phase 10 comparison
- CLI `--validate --tier {cross-tournament|walk-forward|replay|all}` integration

### CLI Integration
- New `--tier` argument with 4 choices (cross-tournament, walk-forward, replay, all)
- `_run_validation_suite()` builds engine + seasons_data from fixture schedule
- Validation report printed to stdout with tier-specific metric sections
- Report saved to `--output` path when provided
- Backward-compatible: old BSD validation still runs if API key available

## Deviations from Plan

None — all three plans executed as written. Stubs for Tier 1/run_all/save_baseline in Plan 09-02 were replaced with real implementations in Plan 09-03 as specified.

## Commits

| Hash | Message |
|------|---------|
| f8b7c80 | feat(09-01): implement TRPS and multi-class evaluation metrics |
| 6852a86 | feat(09-02): create ValidationSuite with Tier 2 (walk-forward) and Tier 3 (replay) |
| 700ee0c | feat(09-03): add Tier 1 cross-tournament, run_all(), baseline recording, CLI integration |
| 15f6f97 | chore(09): add baseline_uncalibrated.json recording |

## Self-Check

- [x] `football_core/evaluation.py` contains `trps()`, `validate_tournament_matrix()`, `multi_class_log_loss()`, `multi_class_brier()`, `multi_class_ece()`
- [x] `competitions/ucl/src/validation_suite.py` exists with `class ValidationSuite` and `ValidationResult` dataclass
- [x] All three validation tiers implemented (Tier 1, 2, 3)
- [x] `run_all()`, `save_baseline()` methods implemented
- [x] CLI `--validate --tier` flags integrated in `main.py`
- [x] Baseline JSON at `competitions/ucl/data/baseline_uncalibrated.json`
- [x] 529 tests pass (516 UCL + 45 evaluation, 1 skipped = live API test)
- [x] No regressions in existing metrics

## Self-Check: PASSED
