# Phase 12b: Evaluation Infrastructure — Context

## Purpose

Build the measurement framework that every subsequent phase uses to prove improvement — Brier score, log loss, calibration curves, persistent prediction history, and a baseline report for the current Elo-only model.

## Requirements

| ID | Requirement | Status |
|----|------------|--------|
| V2-18 | Baseline prediction evaluation framework (Brier, log loss, calibration) computed per match | 🔲 |
| V2-19 | Match-level prediction history stored persistently for analysis | 🔲 |

## Deliverables

1. `src/evaluation.py` — Brier, log loss, calibration metrics, prediction history data model
2. `src/state.py` extensions — prediction history persistence
3. Baseline measurement wired into `main.py` startup (replaces ad-hoc `_record_eval_baseline`)
4. `tests/test_evaluation.py` — comprehensive test suite
5. Baseline report: `data/eval_baseline_report.json`

## Design Decisions

- **D-01**: Prediction history stored as `data/prediction_history.json` — append-only log of per-match predictions without modifying existing data files
- **D-02**: Brier computed per-match as `(p - actual)^2`, aggregated as mean across all matches
- **D-03**: Log loss computed as `-[y*log(p) + (1-y)*log(1-p)]` with epsilon clamping
- **D-04**: Calibration computed as decile-binned reliability diagram (ECE = expected calibration error)
- **D-05**: Baseline report captures: Brier, log loss, ECE, n_matches, per-signal breakdown, generated_at
- **D-06**: Comparison workflow: load two baseline reports, produce delta table
- **D-07**: Evaluation data model: `EvaluationResult` = match_id + prediction + actual + signal_contributions + timestamp
- **D-08**: Separation of concerns: `evaluation.py` = pure computation, `state.py` = persistence, `main.py` = orchestration

## Interfaces

```python
# evaluation.py
def brier_score(prediction: float, actual: float) -> float
def log_loss(prediction: float, actual: float, eps: float = 1e-15) -> float
def compute_metrics(predictions: list[float], actuals: list[float]) -> dict
def calibration_curve(predictions: list[float], actuals: list[float], n_bins: int = 10) -> dict
def expected_calibration_error(curve: dict) -> float
def evaluate_all_matches(teams, played, played_groups) -> dict
def record_baseline(metrics: dict) -> None
def compare_baselines(before: dict, after: dict) -> dict
```

```python
# state.py additions
def load_prediction_history() -> list[dict]
def save_prediction_history(entry: dict) -> None
def load_eval_baseline_report() -> dict | None
def save_eval_baseline_report(report: dict) -> None
```
