# Phase 14: Signal Blending — Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Combine Elo, market odds, and CatBoost into a single calibrated prediction via Platt scaling per signal and dynamic Brier-weighted ensemble. Compute Poisson base rate as a separate input to group-stage score generation (not a prediction signal).

Scope: V2-07 (Platt scaling per signal), V2-08 (Brier-weighted dynamic blender into simulation), V2-09 (Poisson base rate from historical data).

This phase does NOT add new signals (Phase 15), build governance infrastructure (Phase 16), or enhance output display (Phase 17). The blender produces blended probabilities that flow into the existing simulation pipeline.

</domain>

<decisions>
## Implementation Decisions

### Platt Scaling — Implementation
- **D-01:** Pure Python implementation. No sklearn, no scipy. The project's lightweight dependency profile is non-negotiable — adding a 50MB+ ML library for ~20 lines of logistic regression is rejected. Implement Newton-Raphson or gradient descent for the 2-parameter (A, B) logistic fit.
- **D-02:** Platt scaling fits on log-odds: `log(p / (1-p))` as input feature, actual outcome (0/0.5/1) as target. Output is calibrated probability via `1 / (1 + exp(A * log_odds + B))`.

### Cold-Start Strategy
- **D-03:** Identity calibration until threshold reached. If `n_matches < 30` for a signal, use `p_calibrated = p_raw` (no Platt fitting). Avoids overfitting on tiny samples — fitting on 20–30 observations can make calibration worse than raw predictions.
- **D-04:** Threshold of 30 matches is a default — planner may refine during implementation.

### Blender Architecture
- **D-05:** New module: `src/blender.py`. NOT in `evaluation.py` (which owns metrics/reporting, not inference). NOT in an `ensemble/` package (premature — Phase 15+ if complexity grows).
- **D-06:** `src/blender.py` exports:
  - `calibrate_signal(predictions: list[float], actuals: list[float]) -> tuple[float, float]` — fits Platt params A, B
  - `apply_calibration(p_raw: float, A: float, B: float) -> float` — applies Platt transform
  - `compute_blend_weights(signal_briers: dict[str, float]) -> dict[str, float]` — Brier-to-weight conversion
  - `blend_predictions(signal_preds: dict[str, float], weights: dict[str, float]) -> float` — weighted combination

### Weighting Function
- **D-07:** Inverse Brier with floor. Per-signal weight formula:
  ```
  score_s = max(brier_s, 0.05)
  weight_s = 1 / score_s
  weight_s /= sum(weight for all signals)
  ```
  Floor at 0.05 prevents division by zero and extreme weights from near-perfect signals. Softmax and rank-based approaches rejected — they add complexity without benefit since weights are recomputed per iteration.
- **D-08:** Rolling Brier window: default 50 matches, configurable via constant. Window size is a parameter the planner may refine.

### Poisson Base Rate
- **D-09:** NOT a 4th signal. Poisson base rate operates at a different layer — it produces score distributions, not match outcome probabilities. Keep separate from the signal→calibrate→blend pipeline.
- **D-10:** Poisson base rate feeds into `groups.py` score generation (currently `EXPECTED_GOALS_BASE_RATE = 1.25`). Phase 14 computes the rate from historical WC data and may refine the constant, but the integration point is the group simulation engine, not the blender.

### Held-Out Evaluation
- **D-11:** Leave-one-out cross-validation (LOO-CV). Not train/test split (too little data), not time-series split (same reason). LOO-CV maximizes data usage and provides the most stable Brier estimate with the current ~30-match sample.
- **D-12:** Compare blended Brier vs best single-signal Brier using LOO-CV. Target: ≥0.02 improvement (from ROADMAP success criteria).

### the agent's Discretion
- Exact implementation of Platt logistic fit (Newton-Raphson vs gradient descent — both pure Python)
- Threshold value for cold-start (30 matches is a recommendation, may be refined)
- Rolling Brier window size (50 matches default, may be refined)
- Whether `blended` key is written to `prediction_history.json` entries during `_merge_signals_into_history()` or computed on-the-fly during simulation
- Test fixture design for calibration and blending tests

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 14 definition: V2-07, V2-08, V2-09 requirements, success criteria, dependencies on Phase 13.
- `.planning/REQUIREMENTS.md` — V2-07 (Platt scaling), V2-08 (Brier-weighted blender), V2-09 (Poisson base rate).

### Prior Phase Context
- `.planning/phases/13-signal-ingestion/13-CONTEXT.md` — Phase 13 decisions: compound signal entry model (D-01/D-02/D-03), graceful degradation (D-07/D-08), evaluate_all_matches signal_name param (D-11). Phase 14 consumes these.
- `.planning/phases/12b-evaluation-infrastructure/12b-CONTEXT.md` — Prediction history format, Brier/log-loss interface.
- `.planning/phases/11-data-integrity-elo-foundation/11-CONTEXT.md` — Graceful degradation philosophy (D-22: never block).

### Codebase Architecture
- `worldcup_predictor/src/evaluation.py` — `evaluate_all_matches()` with per-signal Brier via signal_name param (D-11). Phase 14 uses this for computing per-signal Brier for blender weights.
- `worldcup_predictor/src/predictors/odds.py` — Market odds signal. Phase 14 consumes calibrated probabilities.
- `worldcup_predictor/src/predictors/catboost.py` — CatBoost signal. Phase 14 consumes calibrated probabilities.
- `worldcup_predictor/src/elo.py` — `expected_score()` for Elo signal probabilities.
- `worldcup_predictor/src/state.py` — `load_prediction_history()` for reading signal entries. `save_prediction_history()` for writing blended entries.
- `worldcup_predictor/main.py:37-70` — `_merge_signals_into_history()` — where blended probabilities may be injected.
- `worldcup_predictor/main.py:545-596` — Signal cache refresh and merge flow in `_run_iteration()`.
- `worldcup_predictor/src/constants.py:42` — `EXPECTED_GOALS_BASE_RATE = 1.25` — current Poisson base rate, may be refined in Phase 14.

### Established Patterns (from scout)
- `worldcup_predictor/src/evaluation.py:24-37` — `compute_metrics()` pattern: list-of-floats in, metrics dict out. Blender follows same signature convention.
- `worldcup_predictor/src/evaluation.py:40-56` — `calibration_curve()` pattern: decile-binned reliability diagram. Phase 14's Platt scaling is a parametric calibration method that should produce better ECE.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/evaluation.py:compute_metrics()` — Per-signal Brier computation. Phase 14 calls this per-signal to get rolling Brier for weight computation.
- `src/state.py:load_prediction_history()` — Access to all historical signal entries for Platt fitting.
- `src/main.py:_merge_signals_into_history()` — Natural injection point for adding `blended` key to compound entries.
- `src/evaluation.py:evaluate_all_matches(signal_name="elo")` — Elo replay pipeline that already produces compound entries. Blender training data comes from these entries.

### Established Patterns
- **Pure stdlib math** — No numpy, no pandas, no sklearn. All math is stdlib `math` module. Platt scaling must follow this pattern.
- **Float-precision rounding** — All metrics rounded to 6 decimal places (`round(x, 6)`). Blender output follows same convention.
- **Compound entry model** (D-01) — `signals` dict per match with per-signal sub-dicts. The `blended` key follows same format.
- **Graceful degradation** — Every module has a fallback path. Blender must handle 0, 1, 2, or 3 available signals.

### Integration Points
- `main.py:_run_iteration()` — After signal cache refresh (~line 595), before simulation call. Blender runs here to produce per-match blended probabilities for the simulation.
- `main.py:_merge_signals_into_history()` — Optional injection point for writing `blended` key into prediction_history entries.
- `groups.py` — Poisson base rate integration for score generation. Currently uses hardcoded `EXPECTED_GOALS_BASE_RATE`.
- `evaluation.py:evaluate_all_matches(signal_name="blended")` — Already wired (Phase 13 D-11) to accept `signal_name="blended"` and read from history.

</code_context>

<specifics>
## Specific Ideas

- The user explicitly rejected sklearn as a dependency. The project's lightweight philosophy (pytest, pytest-cov, python-dotenv as only direct deps) is a firm constraint.
- "Blending is inference logic, evaluation is metrics" — the architecture boundary between `blender.py` (inference) and `evaluation.py` (measurement) should be clean.
- Weighting function: `1 / max(brier, 0.05)` was explicitly chosen over softmax because softmax adds complexity without benefit given iteration-level weight recomputation.
- The user flagged the Poisson base rate integration as the biggest architectural risk — keep it in the score generation layer, not the signal pipeline.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 14-Signal-Blending*
*Context gathered: 2026-06-16*
