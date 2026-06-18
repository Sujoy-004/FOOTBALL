---
phase: 12b-evaluation-infrastructure
plan: 01
type: execute
wave: 1
depends_on: 
  - 12-01
  - 12-02
  - 12-03
files_modified:
  - worldcup_predictor/src/evaluation.py
  - worldcup_predictor/src/state.py
  - worldcup_predictor/src/constants.py
  - worldcup_predictor/main.py
  - worldcup_predictor/data/eval_baseline_report.json
  - worldcup_predictor/tests/test_evaluation.py
  - worldcup_predictor/tests/test_main_loop.py
autonomous: true
requirements:
  - V2-18
  - V2-19
---

<objective>
Build the complete evaluation infrastructure: Brier/log-loss computation, calibration metrics, prediction persistence, and a baseline measurement workflow. Replace the ad-hoc `_record_eval_baseline` with a proper evaluation module consumed by later phases.

**Purpose:** Every signal added after this phase (market odds, CatBoost, form) can be measured against the same baseline and justified with evidence.

**Outputs:**
- `src/evaluation.py` — pure metric computation functions
- `src/state.py` extensions — prediction history + baseline report persistence
- `data/prediction_history.json` — append-only log of per-match predictions
- `data/eval_baseline_report.json` — structured baseline report
- `tests/test_evaluation.py` — comprehensive test suite (20+ tests)
</objective>

<context>

<interfaces>
From src/state.py (existing):
```
load_teams() -> dict[str, dict]
load_played() -> dict[str, dict]
load_played_groups() -> dict[str, dict]
load_elo_update_log() -> list[dict]
_atomic_write_json(data, path) -> None
```

From src/elo.py:
```
expected_score(rating_a, rating_b, home_advantage=0) -> float
apply_elo_update(match, teams) -> dict[str, dict[str, float]]
```

From main.py (existing):
```
_record_eval_baseline(teams, played, played_groups) -> None  # Will be replaced
_run_draw_backfill(teams, played, played_groups, elo_applied) -> set[str]
```

Current data/eval_baseline.json shape:
```json
{"brier": 0.127, "log_loss": 0.406, "n_matches": 7, "generated_at": "2026-06-15T..."}
```

Target baseline report shape (D-05):
```json
{
  "model": "elo-only",
  "phase": "12b",
  "generated_at": "2026-06-15T...",
  "n_matches": 7,
  "metrics": {
    "brier": 0.127,
    "log_loss": 0.406,
    "ece": 0.05,
    "accuracy": 0.714,
    "brier_skill_score": 0.0
  },
  "calibration": {
    "bins": [
      {"bin_start": 0.0, "bin_end": 0.1, "count": 2, "mean_predicted": 0.05, "fraction_positives": 0.0},
      ...
    ],
    "ece": 0.05
  },
  "history_file": "data/prediction_history.json",
  "n_history_entries": 7
}
```

Prediction history entry shape (D-01):
```json
{
  "match_id": "GS_D_01",
  "timestamp": "2026-06-15T...",
  "team_a": "United States",
  "team_b": "Paraguay",
  "prediction": 0.85,
  "actual": 1.0,
  "signal": "elo",
  "team_a_elo": 2100,
  "team_b_elo": 1850
}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create evaluation.py with Brier, log-loss, calibration metrics</name>
  <files>
    worldcup_predictor/src/evaluation.py
    worldcup_predictor/tests/test_evaluation.py
    worldcup_predictor/src/constants.py
  </files>

  <behavior>
    RED: Write failing tests for evaluation.py functions BEFORE the module exists.
    
    Tests to add to test_evaluation.py:
    - test_brier_score_perfect: prediction=1.0, actual=1.0 → 0.0
    - test_brier_score_worst: prediction=0.0, actual=1.0 → 1.0
    - test_brier_score_half: prediction=0.5, actual=1.0 → 0.25
    - test_brier_score_draw: prediction=0.6, actual=0.5 → 0.01
    - test_log_loss_perfect: prediction=0.99, actual=1.0 → ~0.01
    - test_log_loss_worst: prediction=0.01, actual=1.0 → ~4.6
    - test_log_loss_clamping: prediction=0.0, actual=1.0 → no inf (clamped)
    - test_compute_metrics: list of predictions/actuals → dict with brier, log_loss, accuracy, n
    - test_calibration_curve: uniform predictions → 10 bins with correct counts
    - test_calibration_curve_edge: all predictions in one bin → only that bin has entries
    - test_ece_perfect: perfectly calibrated → ECE == 0.0
    - test_ece_miscalibrated: overconfident → ECE > 0.0
    
    GREEN: Implement evaluation.py with:
    - brier_score(prediction, actual) → float
    - log_loss(prediction, actual, eps=1e-15) → float
    - compute_metrics(predictions, actuals) → dict with brier, log_loss, accuracy, n
    - calibration_curve(predictions, actuals, n_bins=10) → dict with bins list + ece
    - expected_calibration_error(curve) → float
  </behavior>

  <action>
    Step 1 — Create tests/test_evaluation.py with all RED tests.
    Import from src.evaluation (which doesn't exist yet). Use pytest.approx for float comparisons.
    
    Step 2 — Confirm RED: pytest tests/test_evaluation.py -x -q → ImportError
    
    Step 3 — Create src/evaluation.py:
    
    ```python
    """Evaluation metrics for prediction quality assessment.
    
    Provides Brier score, log loss, calibration curves, and ECE computation
    used by the baseline measurement and comparison workflow (Phase 12b,
    V2-18, V2-19).
    """
    
    import math
    
    
    def brier_score(prediction: float, actual: float) -> float:
        """Compute Brier score for a single prediction.
        
        Brier = (prediction - actual)^2 where actual ∈ {0.0, 0.5, 1.0}
        
        Args:
            prediction: Predicted probability (0.0 to 1.0).
            actual: Actual outcome (0.0 = loss, 0.5 = draw, 1.0 = win).
        
        Returns:
            Brier score (0.0 = perfect, 1.0 = worst).
        """
        return (prediction - actual) ** 2
    
    
    def log_loss(prediction: float, actual: float, eps: float = 1e-15) -> float:
        """Compute log loss for a single prediction.
        
        Log loss = -[y*log(p) + (1-y)*log(1-p)]
        
        Prediction is clamped to [eps, 1-eps] to avoid log(0).
        
        Args:
            prediction: Predicted probability (0.0 to 1.0).
            actual: Actual outcome (0.0, 0.5, or 1.0).
            eps: Small epsilon for numerical stability.
        
        Returns:
            Log loss (0.0 = perfect, >0 = worse).
        """
        p = max(eps, min(1 - eps, prediction))
        if actual == 0.5:
            return -0.5 * (math.log(p) + math.log(1 - p))
        return -(actual * math.log(p) + (1 - actual) * math.log(1 - p))
    
    
    def compute_metrics(
        predictions: list[float],
        actuals: list[float],
    ) -> dict:
        """Compute aggregate evaluation metrics.
        
        Args:
            predictions: List of predicted probabilities.
            actuals: List of actual outcomes (0.0, 0.5, or 1.0).
        
        Returns:
            Dict with brier, log_loss, accuracy, n.
        """
        if not predictions or len(predictions) != len(actuals):
            return {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0}
        
        n = len(predictions)
        brier_sum = 0.0
        ll_sum = 0.0
        correct = 0
        
        for p, a in zip(predictions, actuals):
            brier_sum += brier_score(p, a)
            ll_sum += log_loss(p, a)
            # Accuracy: prediction > 0.5 and actual == 1.0, or prediction < 0.5 and actual == 0.0
            # Draws (actual == 0.5): always count as half-correct
            if a == 0.5:
                correct += 0.5
            elif (p >= 0.5 and a == 1.0) or (p < 0.5 and a == 0.0):
                correct += 1
        
        return {
            "brier": brier_sum / n,
            "log_loss": ll_sum / n,
            "accuracy": correct / n,
            "n": n,
        }
    
    
    def calibration_curve(
        predictions: list[float],
        actuals: list[float],
        n_bins: int = 10,
    ) -> dict:
        """Compute calibration curve (reliability diagram).
        
        Partitions predictions into n_bins by predicted probability,
        then computes mean predicted probability and fraction of positives
        in each bin.
        
        Args:
            predictions: List of predicted probabilities.
            actuals: List of actual outcomes (0.0, 0.5, or 1.0).
            n_bins: Number of equal-width bins (default 10).
        
        Returns:
            Dict with bins list and ece.
        """
        bins = []
        for i in range(n_bins):
            lo = i / n_bins
            hi = (i + 1) / n_bins
            bin_preds = []
            bin_actuals = []
            for p, a in zip(predictions, actuals):
                if lo <= p < hi or (i == n_bins - 1 and p == 1.0):
                    bin_preds.append(p)
                    bin_actuals.append(a)
            
            if bin_preds:
                mean_pred = sum(bin_preds) / len(bin_preds)
                # For calibration, treat draws as 0.5 positives
                frac_pos = sum(a for a in bin_actuals) / len(bin_actuals)
                bins.append({
                    "bin_start": round(lo, 2),
                    "bin_end": round(hi, 2),
                    "count": len(bin_preds),
                    "mean_predicted": round(mean_pred, 4),
                    "fraction_positives": round(frac_pos, 4),
                })
            else:
                bins.append({
                    "bin_start": round(lo, 2),
                    "bin_end": round(hi, 2),
                    "count": 0,
                    "mean_predicted": 0.0,
                    "fraction_positives": 0.0,
                })
        
        ece = expected_calibration_error({"bins": bins})
        return {"bins": bins, "ece": round(ece, 6)}
    
    
    def expected_calibration_error(calibration: dict) -> float:
        """Compute Expected Calibration Error from a calibration curve.
        
        ECE = Σ (|bin| / N) * |mean_predicted - fraction_positives|
        
        Args:
            calibration: Dict with 'bins' list from calibration_curve().
        
        Returns:
            Expected Calibration Error (0.0 = perfect).
        """
        bins = calibration.get("bins", [])
        total = sum(b.get("count", 0) for b in bins)
        if total == 0:
            return 0.0
        
        ece = 0.0
        for b in bins:
            n = b.get("count", 0)
            if n > 0:
                ece += (n / total) * abs(b["mean_predicted"] - b["fraction_positives"])
        
        return ece
    ```
    
    Step 4 — Verify: pytest tests/test_evaluation.py -x -q → all 12+ tests pass.
  </action>

  <verify>
    <automated>pytest tests/test_evaluation.py -x -q</automated>
  </verify>

  <done>
    - evaluation.py exists with brier_score, log_loss, compute_metrics, calibration_curve, expected_calibration_error
    - test_evaluation.py has 12+ tests covering all functions and edge cases
    - All tests pass
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add prediction history and baseline report persistence to state.py</name>
  <files>
    worldcup_predictor/src/state.py
    worldcup_predictor/tests/test_state.py
  </files>

  <behavior>
    RED: Add failing tests for load/save_prediction_history and load/save_eval_baseline_report.
    
    GREEN: Implement in state.py:
    - load_prediction_history(data_dir=None) -> list[dict]
    - append_prediction_history(entry, data_dir=None) -> None
    - load_eval_baseline_report(data_dir=None) -> dict | None
    - save_eval_baseline_report(report, data_dir=None) -> None
  </behavior>

  <action>
    Step 1 — Add to tests/test_state.py:
    - test_save_load_prediction_history: save entry, load, verify contents
    - test_prediction_history_append: save two entries, verify both present
    - test_prediction_history_empty: file doesn't exist → returns []
    - test_save_load_baseline_report: save report dict, load, verify
    - test_baseline_report_not_exists: file doesn't exist → returns None
    
    Step 2 — Implement state.py functions:
    
    ```python
    def load_prediction_history(data_dir: Path | str | None = None) -> list[dict]:
        """Load prediction history entries.
        
        Args:
            data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.
        
        Returns:
            List of prediction history entries, empty list if file doesn't exist.
        """
        path = _resolve_data_dir(data_dir) / "prediction_history.json"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data: list[dict] = json.load(f)
        return data
    
    
    def append_prediction_history(
        entry: dict,
        data_dir: Path | str | None = None,
    ) -> None:
        """Append a single prediction history entry.
        
        Loads existing history, appends new entry, saves all. Atomic write.
        
        Args:
            entry: Prediction history entry dict.
            data_dir: Directory for the JSON files. Defaults to constants.DATA_DIR.
        """
        history = load_prediction_history(data_dir)
        history.append(entry)
        path = _resolve_data_dir(data_dir) / "prediction_history.json"
        _atomic_write_json(history, path)
    
    
    def load_eval_baseline_report(data_dir: Path | str | None = None) -> dict | None:
        """Load evaluation baseline report.
        
        Args:
            data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.
        
        Returns:
            Baseline report dict, or None if file doesn't exist.
        """
        path = _resolve_data_dir(data_dir) / "eval_baseline_report.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    
    
    def save_eval_baseline_report(
        report: dict,
        data_dir: Path | str | None = None,
    ) -> None:
        """Save evaluation baseline report.
        
        Args:
            report: Baseline report dict.
            data_dir: Directory for the JSON files. Defaults to constants.DATA_DIR.
        """
        path = _resolve_data_dir(data_dir) / "eval_baseline_report.json"
        _atomic_write_json(report, path)
    ```
    
    Step 3 — Verify: pytest tests/test_state.py -x -q → all existing + new tests pass.
  </action>

  <verify>
    <automated>pytest tests/test_state.py -x -q</automated>
  </verify>

  <done>
    - load_prediction_history() returns list, empty if missing
    - append_prediction_history() appends atomically
    - load_eval_baseline_report() returns dict or None
    - save_eval_baseline_report() saves atomically
    - All state tests pass
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Build evaluate_all_matches() and wire into main.py, replacing _record_eval_baseline</name>
  <files>
    worldcup_predictor/src/evaluation.py
    worldcup_predictor/main.py
    worldcup_predictor/tests/test_evaluation.py
    worldcup_predictor/tests/test_main_loop.py
  </files>

  <behavior>
    RED: Write tests for evaluate_all_matches() that exercise the full replay pipeline.
    
    GREEN: Add evaluate_all_matches() to evaluation.py that:
    1. Combines played.json + played_groups.json
    2. Sorts chronologically
    3. Deep-copies teams for replay
    4. Computes pre-match prediction via expected_score
    5. Applies Elo update (simulating the actual pipeline)
    6. Records per-match metrics + aggregate metrics
    7. Returns structured baseline report
    
    Then refactor main.py to use evaluate_all_matches() instead of inline _record_eval_baseline().
  </behavior>

  <action>
    Step 1 — Add to test_evaluation.py:
    - test_evaluate_all_matches_small: 2-match fixture, verify brier and log_loss values by hand
    - test_evaluate_all_matches_empty_played: empty played.json, only played_groups
    - test_evaluate_all_matches_creates_report: verify report shape matches D-05
    
    Step 2 — Implement evaluate_all_matches() in evaluation.py:
    
    ```python
    def evaluate_all_matches(
        teams: dict[str, dict],
        played: dict[str, dict],
        played_groups: dict[str, dict],
    ) -> dict:
        """Replay all played matches and produce a full evaluation report.
        
        Replays matches chronologically through the Elo pipeline, computing
        pre-match predictions vs actual outcomes. Produces a structured report
        with aggregate metrics, calibration curve, and per-match history.
        
        Args:
            teams: Team data dict (deep-copied for replay).
            played: Played knockout matches dict.
            played_groups: Played group matches dict.
        
        Returns:
            Baseline report dict matching D-05 shape.
        """
        import copy
        from datetime import datetime, timezone
        
        from src.elo import apply_elo_update, expected_score
        from src.state import append_prediction_history
        
        all_matches: list[dict] = []
        for match_dict in [played, played_groups]:
            for m in match_dict.values():
                all_matches.append(dict(m))
        
        all_matches.sort(key=lambda x: (x.get("completed_at", ""), x.get("match_id", "")))
        
        replay_teams = copy.deepcopy(teams)
        predictions: list[float] = []
        actuals: list[float] = []
        history_entries: list[dict] = []
        
        for m in all_matches:
            t_a, t_b = m["team_a"], m["team_b"]
            if t_a not in replay_teams or t_b not in replay_teams:
                continue
            
            p_a = expected_score(replay_teams[t_a]["elo"], replay_teams[t_b]["elo"])
            
            winner = m.get("winner")
            if winner is None:
                actual_a = 0.5
            elif winner == t_a:
                actual_a = 1.0
            elif winner == t_b:
                actual_a = 0.0
            else:
                continue
            
            predictions.append(p_a)
            actuals.append(actual_a)
            
            entry = {
                "match_id": m.get("match_id", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "team_a": t_a,
                "team_b": t_b,
                "prediction": round(p_a, 4),
                "actual": actual_a,
                "signal": "elo",
                "team_a_elo": replay_teams[t_a]["elo"],
                "team_b_elo": replay_teams[t_b]["elo"],
            }
            history_entries.append(entry)
            
            try:
                apply_elo_update(m, replay_teams)
            except Exception:
                pass
        
        if not predictions:
            return {
                "model": "elo-only",
                "phase": "12b",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "n_matches": 0,
                "metrics": {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0},
                "calibration": {"bins": [], "ece": 0.0},
                "history_file": "data/prediction_history.json",
                "n_history_entries": 0,
            }
        
        metrics = compute_metrics(predictions, actuals)
        cal = calibration_curve(predictions, actuals)
        
        report = {
            "model": "elo-only",
            "phase": "12b",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_matches": metrics["n"],
            "metrics": {
                "brier": round(metrics["brier"], 6),
                "log_loss": round(metrics["log_loss"], 6),
                "accuracy": round(metrics["accuracy"], 6),
                "brier_skill_score": 0.0,  # No baseline to compare against yet
                "n": metrics["n"],
            },
            "calibration": cal,
            "history_file": "data/prediction_history.json",
            "n_history_entries": len(history_entries),
        }
        
        # Persist prediction history
        for entry in history_entries:
            try:
                append_prediction_history(entry)
            except Exception:
                pass
        
        return report
    ```
    
    Step 3 — Wire into main.py:
    
    Find `_record_eval_baseline` function (line 384) and replace with a thin wrapper:
    ```python
    def _record_eval_baseline(
        teams: dict[str, dict],
        played: dict[str, dict],
        played_groups: dict[str, dict],
    ) -> None:
        """Record baseline evaluation report using the evaluation framework.
        
        Delegates to evaluation.evaluate_all_matches() and persists the report.
        Replaces the ad-hoc Brier/log-loss computation from Phase 12.
        """
        from src.evaluation import evaluate_all_matches
        from src.state import save_eval_baseline_report
        
        report = evaluate_all_matches(teams, played, played_groups)
        save_eval_baseline_report(report)
        
        if report["n_matches"] > 0:
            m = report["metrics"]
            print(f"Baseline: Brier={m['brier']:.4f}, LogLoss={m['log_loss']:.4f}, "
                  f"Acc={m['accuracy']:.3f}, ECE={report['calibration']['ece']:.4f} "
                  f"({report['n_matches']} matches)")
        else:
            print("Baseline: no matches to evaluate")
    ```
    
    Verify the call site at line 657 still works (it calls _record_eval_baseline(teams, played, played_groups)).
    
    Step 4 — Update import at top of main.py: add `copy` if not already imported.
    Check: `import copy` should be at top of main.py.
    
    Step 5 — Update tests in test_main_loop.py if they reference _record_eval_baseline.
    Step 6 — Verify: pytest tests/test_evaluation.py tests/test_main_loop.py -x -q
  </action>

  <verify>
    <automated>pytest tests/test_evaluation.py tests/test_main_loop.py -x -q</automated>
  </verify>

  <done>
    - evaluate_all_matches() in evaluation.py produces full baseline report
    - _record_eval_baseline in main.py delegates to evaluation module
    - prediction_history.json created with per-match entries
    - eval_baseline_report.json created with structured report
    - All tests pass
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: Build comparison workflow and produce baseline report</name>
  <files>
    worldcup_predictor/src/evaluation.py
    worldcup_predictor/tests/test_evaluation.py
    worldcup_predictor/main.py
  </files>

  <behavior>
    RED: Add compare_baselines() test.
    
    GREEN: Implement compare_baselines() that loads two baseline reports and produces a structured comparison dict with deltas.
    
    Then produce the production baseline report by running main.py startup sequence.
  </behavior>

  <action>
    Step 1 — Add test_compare_baselines to test_evaluation.py:
    - test_compare_baselines: two reports with different brier values → correct delta
    - test_compare_baselines_identical: same report twice → all deltas == 0
    
    Step 2 — Implement compare_baselines() in evaluation.py:
    
    ```python
    def compare_baselines(before: dict, after: dict) -> dict:
        """Compare two baseline reports and produce a structured comparison.
        
        Args:
            before: Baseline report before change.
            after: Baseline report after change.
        
        Returns:
            Dict with comparison metrics and deltas.
        """
        b_m = before.get("metrics", {})
        a_m = after.get("metrics", {})
        
        def delta(key):
            return round(a_m.get(key, 0) - b_m.get(key, 0), 6)
        
        return {
            "comparison": f"{before.get('model', '?')} vs {after.get('model', '?')}",
            "before": {
                "model": before.get("model"),
                "generated_at": before.get("generated_at"),
                "n_matches": before.get("n_matches"),
                "metrics": b_m,
                "ece": before.get("calibration", {}).get("ece"),
            },
            "after": {
                "model": after.get("model"),
                "generated_at": after.get("generated_at"),
                "n_matches": after.get("n_matches"),
                "metrics": a_m,
                "ece": after.get("calibration", {}).get("ece"),
            },
            "deltas": {
                "brier": delta("brier"),
                "log_loss": delta("log_loss"),
                "accuracy": delta("accuracy"),
                "ece": round(
                    after.get("calibration", {}).get("ece", 0)
                    - before.get("calibration", {}).get("ece", 0),
                    6,
                ),
                "n_matches": a_m.get("n", 0) - b_m.get("n", 0),
            },
            "verdict": _verdict(b_m, a_m),
        }
    
    
    def _verdict(before: dict, after: dict) -> str:
        """Produce a human-readable verdict from metric comparison."""
        brier_delta = after.get("brier", 0) - before.get("brier", 0)
        if brier_delta < -0.01:
            return "IMPROVED"
        elif brier_delta > 0.01:
            return "REGRESSED"
        elif abs(brier_delta) <= 0.01:
            return "SIMILAR"
        return "INCONCLUSIVE"
    ```
    
    Step 3 — Run main.py --once to produce the baseline report:
    ```bash
    cd worldcup_predictor
    python main.py --once 2>&1 || echo "Non-zero exit expected if no API key"
    ```
    (This will attempt live data but gracefully degrade. The baseline is already generated
    by the startup sequence's _record_eval_baseline call.)
    
    Step 4 — Verify baseline report exists:
    ```bash
    python -c "import json; r=json.load(open('data/eval_baseline_report.json')); print(r['metrics'])"
    ```
    
    Step 5 — Upload the baseline report to data/.
  </action>

  <verify>
    <automated>python -c "import json; r=json.load(open('worldcup_predictor/data/eval_baseline_report.json')); assert r['metrics']['n'] > 0; print(f'Baseline: {r[\"metrics\"]}')"</automated>
  </verify>

  <done>
    - compare_baselines() implemented and tested
    - baseline report produced with current Elo-only model
    - baseline report shows Brier, log loss, accuracy, ECE
    - Ready for future signal comparison
  </done>
</task>

</tasks>

<verification>
1. `pytest tests/test_evaluation.py -x -q` — all evaluation tests pass (20+)
2. `pytest tests/test_state.py -x -q` — all state persistence tests pass
3. `pytest tests/test_main_loop.py -x -q` — main loop tests unaffected
4. `python -c "import json; json.load(open('worldcup_predictor/data/eval_baseline_report.json'))"` — valid JSON
5. `python -c "import json; r=json.load(open('worldcup_predictor/data/eval_baseline_report.json')); assert r['metrics']['n'] > 0"` — non-empty
6. `pytest tests/ -x -q` — full test suite green
</verification>

<success_criteria>
1. evaluation.py exists with brier_score, log_loss, compute_metrics, calibration_curve, expected_calibration_error, evaluate_all_matches, compare_baselines
2. state.py has load_prediction_history, append_prediction_history, load_eval_baseline_report, save_eval_baseline_report
3. main.py _record_eval_baseline delegates to evaluation module
4. data/eval_baseline_report.json contains structured baseline with Brier, log loss, accuracy, ECE
5. data/prediction_history.json contains per-match prediction entries
6. compare_baselines() produces structured comparisons for future signal evaluation
7. Full test suite passes (300+ tests)
</success_criteria>
