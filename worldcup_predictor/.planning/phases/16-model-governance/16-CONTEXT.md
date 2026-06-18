# Phase 16: Model Governance — Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Add the three pillars of model governance — versioning (data/model/run), Brier monitoring per signal with drift detection, and backtesting against historical World Cups. Wraps the existing evaluation infrastructure (Phase 12b) with governance tooling.

Scope: V2-12 (model/data/run version tracking), V2-13 (per-signal Brier with drift detection), V2-14 (backtesting framework).

This phase does NOT implement auto-recalibration on drift (alert-only), per-match backtest history (tournament-level only), or UI interactivity (CLI only).

</domain>

<decisions>
## Implementation Decisions

### Versioning Scheme (V2-12)
- **D-01:** Three-version approach: `data_version`, `model_version`, `run_version` tracked in `data/versions.json`. Each answers: "Which data? Which model? Which run?"
- **D-02:** `data_version` increments only on material dataset change: (A) new completed match enters `prediction_history`, OR (B) existing `prediction_history` entry gains a new signal not previously present. NOT on merge execution, cache refresh, ledger update, governance run, or simulation run.
- **D-03:** `model_version` increments when the active signal lineup changes (signals added/removed) or calibration parameters are refitted.
- **D-04:** `run_version` is timestamp-based (ISO 8601), updated every poll cycle when `run_full_simulation` produces new probabilities.
- **D-05:** Version IDs stored at both prediction level (each `prediction_history` entry carries `data_version`, `model_version`, `run_version`) and run level (`versions.json` summary). Enables per-entry traceability.
- **D-06:** Run snapshots stored in `runs/{run_id}.json` with lean governance payload only (NOT full state dump):
  ```json
  {
    "run_version": "...",
    "data_version": "...",
    "model_version": "...",
    "timestamp": "...",
    "signal_counts": {...},
    "blend_weights": {...},
    "per_signal_brier": {...},
    "blended_brier": 0.0,
    "drift_status": "HEALTHY"
  }
  ```
  Calibration params NOT duplicated per run (already in `calibration_params.json`).
- **D-07:** `versions.json` file at `data/versions.json` with current version state.

### Drift Detection (V2-13)
- **D-08:** Two baselines per signal:
  - **Reference baseline**: Fixed Brier after cold-start threshold (30 matches). Never changes.
  - **Rolling baseline**: Mean Brier over last 50 matches. Updates continuously.
- **D-09:** Drift detection formula (per signal):
  ```
  rolling_sigma = std(per_match_brier_scores in last 50 matches)
  drift_alert = rolling_mean_brier > reference_baseline + 2 * rolling_sigma
  ```
  σ is per-signal (NOT pooled across signals). Rejects pooled σ (hides signal-specific degradation) and fixed absolute threshold (different signals have different variance).
- **D-10:** Drift action for Phase 16: **alert only** (print warning in console, flag in run snapshot). Auto-recalibration is already handled by `calibrate_and_blend()` which refits Platt params every cycle — drift detection is a monitoring signal, not a trigger.
- **D-11:** Drift check frequency: every governance run (startup + hourly + on drift), computed from current rolling window.

### Backtesting Framework (V2-14)
- **D-12:** Data source: static tournament files at `data/historical/`. Governance must not depend on external API — backtesting must be deterministic, repeatable, and offline.
- **D-13:** Initial coverage: **2018 + 2022** World Cups (two most recent tournaments, 64 matches each).
- **D-14:** Report format — per-tournament reports + aggregate:
  - **Per tournament**: match count, per-signal Brier, per-signal log loss, per-signal ECE, blended metrics, best signal, winner prediction result, signal ranking
  - **Aggregate**: all-tournament metrics, signal ranking across tournaments, drift summary, governance recommendation
- **D-15:** Per-match backtest history rejected for Phase 16 (governance scope creep). Match-level granularity can be added later.

### Governance Dashlet Output
- **D-16:** Display frequency: **on startup + hourly + on drift detection**. NOT every heartbeat (keeps default cycle clean).
- **D-17:** Cold-start display (0-29 matches): visible immediately with version info, match count, explicit cold-start status. NO fake metric placeholders.
  ```
  MODEL GOVERNANCE

  Data Version : D3
  Model Version: M2
  Run Version  : R47

  Matches Seen : 19 / 30
  Status       : COLD START

  Baseline     : PENDING
  Drift Check  : DISABLED
  Backtesting  : READY
  ```
- **D-18:** Active display (≥30 matches): compact table by default, expanded drift section only when drift exists.
  ```
  MODEL GOVERNANCE

  Data  : D14
  Model : M7
  Run   : R312

  Status : HEALTHY

  Signal            Brier    Drift
  --------------------------------
  elo               0.108    OK
  market_odds       0.097    OK
  catboost          0.101    OK
  form              0.112    OK
  lineup_strength   0.118    OK
  blended           0.093    OK

  Baseline Window : 30
  Rolling Window  : 50
  ```
  On drift:
  ```
  DRIFT DETECTED

  Signal      : market_odds
  Reference   : 0.094
  Rolling     : 0.132
  Threshold   : 0.121
  Delta       : +0.038
  ```
- **D-19:** Dashlet printed to stdout via `output.py` module, following existing console output patterns.

### the agent's Discretion
- Exact format of version strings (D1/D2 vs v1/v2 vs 20260617-1)
- File structure for historical tournament data
- Backtest runner CLI interface (subcommand vs function call)
- Run snapshot retention policy
- Whether `runs/` directory goes under `data/` or at project root

### Shared Architecture Constraints
- **D-20:** Pure Python stdlib — no numpy, no sklearn (Phase 14 D-01).
- **D-21:** JSON file persistence — no database (PROJECT.md constraint).
- **D-22:** Console-only output — no web UI (PROJECT.md constraint).
- **D-23:** Cold-start threshold = 30 matches (Phase 14 D-03/D-04).
- **D-24:** Brier rolling window = 50 matches (Phase 14 D-08).
- **D-25:** All governance state loads/saves follow existing `state.py` atomic pattern.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 16 definition: V2-12, V2-13, V2-14 requirements, success criteria, dependencies on Phase 15.
- `.planning/REQUIREMENTS.md` — V2-12 (version tracking), V2-13 (drift detection), V2-14 (backtesting).

### Prior Phase Context
- `.planning/phases/12b-evaluation-infrastructure/12b-01-PLAN.md` — Evaluation framework: Brier, log loss, calibration curves, prediction history.
- `.planning/phases/14-signal-blending/14-CONTEXT.md` — Blender decisions: Platt scaling, Brier-weighted blending, cold-start threshold 30, rolling window 50.
- `.planning/phases/15-context-signals/15-CONTEXT.md` — Context signals: form and lineup_strength signal definitions.

### Codebase Architecture
- `worldcup_predictor/src/evaluation.py` — Existing evaluation metrics: `brier_score()`, `log_loss()`, `compute_metrics()`, `calibration_curve()`, `evaluate_all_matches()`, `compare_baselines()`. Phase 16 extends with drift detection and backtesting.
- `worldcup_predictor/src/blender.py` — Existing blender: `BRIER_WINDOW_SIZE = 50`, `COLD_START_THRESHOLD = 30`, rolling per-signal Brier computation.
- `worldcup_predictor/src/state.py` — Atomic save/load patterns for `versions.json` and `runs/` snapshots.
- `worldcup_predictor/src/constants.py` — Governance constants (baseline window, sigma threshold, etc.).
- `worldcup_predictor/src/output.py` — Console output module. Governance dashlet integrates here.
- `worldcup_predictor/main.py:620-640` — Existing signal warning aggregation pattern. Governance dashlet follows similar insertion point.
- `worldcup_predictor/data/prediction_history.json` — Compound prediction entries with signal dicts. Version IDs attach to each entry.

### Established Patterns
- `worldcup_predictor/src/state.py:save_signal_cache()` — Atomic JSON write pattern for run snapshots.
- `worldcup_predictor/src/state.py:load_prediction_ledger()` — File loading pattern for `versions.json`.
- `worldcup_predictor/src/evaluation.py:evaluate_all_matches()` — Loop-over-signals pattern reusable for backtesting.
- `worldcup_predictor/src/main.py:590-620` — Signal computation + merge pattern reusable for governance snapshot.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/evaluation.py` — `compute_metrics()`, `calibration_curve()`, `evaluate_all_matches(signal_name=)`, `compare_baselines()`. All reusable for backtesting reports and drift metrics.
- `src/blender.py` — `_compute_rolling_brier()` if exists; rolling Brier logic can be extracted for drift detection.
- `src/state.py` — Atomic JSON write (`tempfile` + `os.rename`) for `versions.json` and run snapshots.
- `src/constants.py` — Existing constants: `BRIER_WINDOW_SIZE = 50`, `COLD_START_THRESHOLD = 30`. Add governance constants here.
- `src/output.py` — Existing console output functions. Add `print_governance_dashlet()` following same pattern.

### Established Patterns
- **Signal module pattern** (`odds.py`, `catboost.py`, `form.py`, `lineup.py`): fetch → compute → cache → ledger upsert. Governance has no cache — it reads existing data.
- **`_run_iteration()` flow** (main.py:590-640): signal refresh → merge → calibrate → simulate → print. Governance dashlet inserts after simulation, before heartbeat.
- **`evaluate_all_matches()` loop**: iterates `prediction_history`, groups by signal key, computes metrics. Backtesting follows same loop but over historical tournament files.

### Integration Points
- `main.py:_run_iteration()` (~line 640-660) — Governance dashlet print after simulation, on startup + hourly + drift triggers.
- `main.py:startup()` (~line 750) — One-shot backtest run trigger.
- `src/evaluation.py` — Backtesting `backtest_tournament()` function following `evaluate_all_matches()` pattern.
- `src/state.py` — `load_versions()`, `save_versions()`, `save_run_snapshot()`, `load_backtest_data()`.
- `src/output.py` — `print_governance_dashlet()`, `print_drift_alert()`.
- `data/versions.json` — New file for version tracking.
- `data/historical/` — New directory for historical tournament match files.
- `data/runs/` — New directory for run snapshots (or `runs/` at project root).

</code_context>

<specifics>
## Specific Ideas

- The user emphasized governance should answer: "Which data? Which model? Which run?" — a single version cannot answer all three.
- Brier σ is per-signal, not pooled. "Governance should identify which signal is drifting. Pooled σ hides signal-specific degradation."
- Backtest report must include a **winner prediction** section: did the model correctly predict the tournament winner?
- During cold start, show explicit status lines (`PENDING`, `DISABLED`, `READY`) rather than fake metric placeholders. "Governance starts before calibration starts."
- The drift alert section only appears when drift exists — no collapsible UI, just conditional print.
- `data_version` should represent "a change in the evaluation dataset, not a change in processing activity."
- The user rejected "auto-recalibrate on drift" for Phase 16 — "alert only". Recalibration already happens continuously via `calibrate_and_blend()`.

</specifics>

<deferred>
## Deferred Ideas

- **Per-match backtest history** — match-level granularity for time-series Brier charts. Rejected for Phase 16 as governance scope creep. Consider for Phase 18 (Historical Tracking).
- **Auto-recalibrate on drift** — automatic recalibration triggered by drift detection. Deferred — alert-only for Phase 16.
- **BSD API as backtest data source** — rejected for Phase 16 (governance must be deterministic, repeatable, offline).
- **Full state dump per run** — rejected (archive bloat). Lean run snapshots only.

</deferred>

---

*Phase: 16-Model-Governance*
*Context gathered: 2026-06-17*
