# Phase 14: Signal Blending — Research

**Researched:** 2026-06-16
**Domain:** Calibrated ensemble prediction — Platt scaling, Brier-weighted blending, Poisson base rate
**Confidence:** HIGH

## Summary

Phase 14 implements three connected capabilities: (1) per-signal Platt scaling on log-odds using pure Python Newton-Raphson, (2) a Brier-weighted dynamic blender that combines calibrated predictions into a single probability, and (3) computation of a calibrated Poisson base rate from historical World Cup data. The blender is a new `src/blender.py` inference module (not evaluation). Blended probabilities flow into `knockout.py:run_full_simulation()` to replace Elo-only probabilities during Monte Carlo simulation.

**Key architectural insight:** There are two distinct data flows — (A) calibration fitting from **past** matches in prediction_history, and (B) blended prediction for **future/upcoming** matches from signal caches (odds_cache, catboost_cache). The planner must account for both. The LOO-CV evaluation (D-11) uses flow A. The live simulation uses flow B.

**Primary recommendation:** Implement Platt scaling via Newton-Raphson (standard for this use case, converges in 3-5 iterations). Store fitted parameters per-signal in a small JSON file alongside prediction_history. Blend probabilities in `_run_iteration()` after signal cache merge and pass them to `run_full_simulation()` via a new `blended_probs` parameter.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Pure Python Platt scaling (no sklearn, no scipy)
- **D-02:** Logistic fit on log-odds, 2 params (A, B): `1 / (1 + exp(A * log_odds(p) + B))`
- **D-03:** Identity calibration for < 30 matches (cold start)
- **D-04:** Threshold of 30 matches is a default — planner may refine
- **D-05:** New module `src/blender.py` (not evaluation.py, not ensemble/)
- **D-06:** Public exports: calibrate_signal, apply_calibration, compute_blend_weights, blend_predictions
- **D-07:** Weighting: `w_s = 1 / max(brier_s, 0.05)`, then normalized to sum=1
- **D-08:** Rolling Brier window: default 50 matches, configurable
- **D-09:** Poisson base rate stays in groups.py (NOT a 4th signal)
- **D-10:** Poisson rate feeds groups.py score generation (currently EXPERT_GOALS_BASE_RATE=1.25)
- **D-11:** LOO-CV for held-out evaluation
- **D-12:** Success = blended_Brier < best_single_signal_Brier (directional, no arbitrary threshold)

### the agent's Discretion
- Exact implementation of Platt logistic fit (Newton-Raphson vs gradient descent)
- Threshold value for cold-start (30 matches is a recommendation)
- Rolling Brier window size (50 matches default)
- Whether `blended` key is written to prediction_history.json during _merge_signals_into_history() or computed on-the-fly during simulation
- Test fixture design for calibration and blending tests

### Deferred Ideas
- None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| V2-07 | Signal calibration layer (Platt scaling per signal) | Section 1: Pure Python Newton-Raphson fitting on log-odds with clamping, identity cold-start, per-signal parameter persistence |
| V2-08 | Dynamic signal blender (Brier-weighted) integrated into simulation | Section 2+4: Blend weights from rolling Brier, dual data flow for fitting vs. live prediction, injection into knockout.py via blended_probs dict |
| V2-09 | Calibrated Poisson base rate from historical World Cup data | Section 3: Computation from empirical goals data, integration point already exists in groups.py expected_goals(), historical data sourcing strategy |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Platt parameter fitting | Backend (blender.py) | — | Pure computation on historical prediction data from prediction_history. No external services needed. |
| Probability calibration | Backend (blender.py) | — | apply_calibration(p_raw, A, B) is a simple math transform. Called per-signal per-match during blending step. |
| Brier-weighted blend | Backend (blender.py) | — | Weights computed from per-signal Brier scores. Pure math — no data fetching. |
| Poisson base rate computation | Backend (groups.py) | — | V2-09 computation lives at the score-generation layer per D-09/D-10. |
| Simulation of matches with blended probs | Backend (knockout.py) | — | blended_probs replaces expected_score() calls in _simulate_r32_resolved, _simulate_r16, _simulate_knockout_round. |
| LOO-CV evaluation | Backend (evaluation.py) | — | Cross-validation is a metrics/evaluation concern. LOO-CV calls calibrate_signal in a loop per held-out match. |

---

## 1. Platt Scaling in Pure Python (V2-07)

### Approach: Newton-Raphson (recommended)

Platt scaling fits two parameters (A, B) for the logistic model:
```
P_calibrated = 1 / (1 + exp(A * log_odds(p) + B))
```

where `log_odds(p) = log(p / (1-p))`.

**Newton-Raphson** is strongly recommended over gradient descent for this use case:
- 2 parameters → 2x2 Hessian → closed-form Newton step via 2x2 matrix inversion (uses Cramer's rule, no library needed)
- Converges in 3-5 iterations vs 50-200 for gradient descent
- The original Platt paper uses a closely related approach (Levenberg-Marquardt variant via `fmin`)
- For N < 50 (our range), each iteration is O(N) — negligible cost

**Gradient descent** is simpler but slower (more iterations, needs learning rate tuning). The planner may choose it if code simplicity is valued over convergence speed, but Newton-Raphson is the standard for logistic regression with few parameters.

### Numerical Stability Concerns

Five edge cases that need protection:

1. **Log-odds of 0 or 1:** `log(p / (1-p))` produces ±inf when p=0 or p=1. **Fix:** Clamp p to `[eps, 1-eps]` before log-odds transform, where `eps = 1e-15` (matches log_loss clamping in evaluation.py:18).

2. **Hessian near-singular with < 30 samples:** With very few samples, the Hessian can be near-singular, causing Newton steps to explode. **Fix:** Add a tiny ridge regularization (λ=1e-6) to the Hessian diagonal: `H_ridge = H + λ * I`. This is standard practice for small-sample logistic regression.

3. **All predictions identical:** If all p values are the same (e.g., cold start), any (A, B) pair with A=0 and `B = logit(mean_actual)` fits equally well → Hessian is singular. **Fix:** The identity cold-start guard (D-03, n<30) catches this already.

4. **Target variable: 0, 0.5, 1.0:** For logistic regression, targets should be in (0, 1), not [0, 1]. Use Platt's adjustment:
   - For N+ positive samples and N- negative samples:
     - `t+ = (N+ + 1) / (N+ + 2)` for targets where actual=1.0
     - `t- = 1 / (N- + 2)` for targets where actual=0.0
     - For draws (actual=0.5), use `t = 0.5` (draws are not in standard Platt scaling; treat as half-weight positive, half negative)
   - This prevents overfitting at probability extremes.

5. **Class imbalance:** If most matches are wins by the higher-Elo team, the positive class dominates. Platt's adjustment (above) handles this.

### Algorithm Pseudocode

```
def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid. Clips to [eps, 1-eps]."""
    if x < -100: return 1e-15
    if x > 100: return 1 - 1e-15
    return 1.0 / (1.0 + math.exp(-x))

def calibrate_signal(predictions: list[float], actuals: list[float],
                     threshold: int = 30) -> tuple[float, float]:
    n = len(predictions)
    if n < threshold:
        return (1.0, 0.0)  # Identity: P_cal = P_raw

    # Convert to log-odds (clamped)
    EPS = 1e-15
    x = [math.log(max(p, EPS) / (1.0 - min(p, 1-EPS))) for p in predictions]

    # Platt target adjustment
    n_pos = sum(1 for a in actuals if a == 1.0)
    n_neg = sum(1 for a in actuals if a == 0.0)
    t_pos = (n_pos + 1) / (n_pos + 2) if n_pos > 0 else 0.0
    t_neg = 1.0 / (n_neg + 2) if n_neg > 0 else 0.0
    t = []
    for a in actuals:
        if a == 1.0: t.append(t_pos)
        elif a == 0.0: t.append(t_neg)
        else: t.append(0.5)  # draw

    # Newton-Raphson to minimize cross-entropy
    A, B = 0.0, 0.0  # init at identity
    for _ in range(50):  # max iterations
        f = [A * xi + B for xi in x]
        p = [_sigmoid(fi) for fi in f]
        # Gradient
        dA = sum(xi * (pi - ti) for xi, pi, ti in zip(x, p, t))
        dB = sum(pi - ti for pi, ti in zip(p, t))
        # Hessian (with ridge)
        H_AA = sum(xi*xi * pi * (1-pi) for xi, pi in zip(x, p)) + 1e-6
        H_AB = sum(xi * pi * (1-pi) for xi, pi in zip(x, p))
        H_BB = sum(pi * (1-pi) for pi in p) + 1e-6
        det = H_AA * H_BB - H_AB * H_AB
        if abs(det) < 1e-12:
            break  # near-singular, stop early
        # Newton step
        dA_step = (H_BB * dA - H_AB * dB) / det
        dB_step = (H_AA * dB - H_AB * dA) / det
        A -= dA_step
        B -= dB_step
        if abs(dA_step) < 1e-6 and abs(dB_step) < 1e-6:
            break  # converged
    return (A, B)
```

**Key references:**
- Platt, J. (1999). "Probabilistic Outputs for Support Vector Machines and Comparisons to Regularized Likelihood Methods." The original paper.
- Niculescu-Mizil, A. & Caruana, R. (2005). "Predicting Good Probabilities with Supervised Learning." Confirms Platt scaling works for calibrated outputs from non-SVM models.
- `[CITED: Context would reference sklearn's internal implementation pattern — but D-01 explicitly rejects sklearn]`

### Parameter Persistence (the agent's Discretion — recommendation)

Store fitted (A, B) parameters per signal in a small JSON file `data/calibration_params.json`:

```json
{
  "elo": {"A": 1.2, "B": -0.3, "n_matches": 45, "brier": 0.127, "fitted_at": "2026-06-16T..."},
  "market_odds": {"A": 0.9, "B": 0.1, "n_matches": 30, "brier": 0.095, "fitted_at": "2026-06-16T..."},
  "catboost": {"A": null, "B": null, "n_matches": 12, "brier": 0.110, "fitted_at": null}
}
```

This enables:
- Quick lookup during live simulation (no refit per iteration)
- Detect cold-start per signal (null A/B means use identity)
- Track per-signal Brier for weight computation

Refit on each poll cycle (every ~60s) is fast for N<100 — don't optimize prematurely.

### Don't Hand-Roll (Platt Scaling)

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Logistic regression (2 param) | Anything beyond Newton-Raphson | The ~40 lines of Newton-Raphson above | 2-param is trivially invertible. Gradient descent is slower. Anything more is over-engineering. |
| Matrix inversion for 2x2 | numpy.linalg | Cramer's rule (ad-bc) | The 2x2 inverse is 4 multiplications and 1 division. A library for this is absurd. |
| Parameter persistence | Database, pickle | Simple JSON file | Matches project pattern (state.py). ~3 keys, < 200 bytes. |

---

## 2. Rolling Brier Window (V2-08)

### Computation Strategy

With the current ~30 match samples, the "window" effectively covers all available matches. The rolling aspect only matters as more matches accumulate during the tournament.

**Approach:** Compute on-the-fly from prediction_history. No ring buffer or separate persistence needed.

```
def compute_rolling_brier(signal_key: str, window: int = 50) -> float:
    history = load_prediction_history()
    # Collect (probability, actual) for signal_key where available
    pairs = []
    for entry in history:
        sig = entry.get("signals", {}).get(signal_key, {})
        if sig.get("available") and sig.get("probability") is not None and entry.get("actual") is not None:
            pairs.append((sig["probability"], entry["actual"]))
    # Take last N by entry order (history is chronologically ordered)
    windowed = pairs[-window:]
    if not windowed:
        return 1.0  # worst case — no data
    brier = sum((p - a)**2 for p, a in windowed) / len(windowed)
    return brier
```

**Performance:** For N_history entries (currently ~30, future ~104) and 3 signals, this is ~300 sum iterations per poll cycle — negligible.

### Window Size Consideration

- **50 matches default (D-08):** Good for tournament context. The WC has 104 matches total. A window of 50 captures the last ~half of the tournament, responsive to signal degradation/changes.
- **Minimum viable window:** At least 15-20 for stable Brier estimate. Below this, Brier variance is high and weights will be noisy.
- **No upper bound:** If window >= total matches, all matches are used. This is fine.

### Where to Store Per-Signal Brier

**Recommendation:** Compute on-the-fly from prediction_history during `compute_blend_weights()`. No separate Brier storage needed. The computation is O(N_history * n_signals) which is ~300 operations — trivial.

If optimization is needed later (Phase 16+), cache the per-signal Brier in `calibration_params.json` and update incrementally.

---

## 3. Poisson Base Rate from Historical WC Data (V2-09)

### Current State

`constants.py:42` — `EXPECTED_GOALS_BASE_RATE = 1.25`  
This was set during Phase 8 research as the historical World Cup group stage average goals per team per match.

The integration point already exists in `groups.py:expected_goals()`:
```python
adj_base = (base_rate if base_rate is not None else constants.EXPECTED_GOALS_BASE_RATE) * 1.05
```

The function already accepts `base_rate=None` and defaults to the constant. `precompute_matchup_lambdas()` passes no base_rate, so the constant is used.

### What V2-09 Requires

V2-09 says "calibrated Poisson base rate from historical World Cup data." This means:
1. Source historical WC match data (goals scored per match)
2. Compute the empirical average goals-per-team-per-match
3. Update the constant (or provide a computed value)

### Data Sourcing

The repo has NO historical WC match data file. Options:

**Option A: Create a historical dataset file**
- Add `data/historical_wc_matches.json` — all WC 1930-2022 match scores
- ~900 matches across 21 tournaments
- Compute mean goals per team per match
- This is the most robust approach but represents significant scope (creating/verifying a dataset)

**Option B: Compute from existing played data**
- If the user has been running the tool and accumulating played.json data, use that
- Risk: small sample, may not converge on true historical mean

**Option C: Keep the constant but add a computation function**
- Add `compute_poisson_base_rate(data_file: str) -> float` to blender.py or groups.py
- Wire it into startup flow: if historical data file exists, compute; else use constant
- This is the lowest-risk, most flexible approach

**Recommendation:** Option C. Add a function that computes the rate from a data file. If the file doesn't exist, fall back to the constant 1.25. This defers the data sourcing decision to the user while providing the architecture for V2-09.

### Integration Points

The function signature should be:
```python
def compute_poisson_base_rate(
    match_data_path: Path | str | None = None
) -> float:
    """Compute expected goals per team per match from historical WC data."""
```

Called during startup or lazily by `groups.py::expected_goals()`:

```python
from src.blender import compute_poisson_base_rate
computed_rate = compute_poisson_base_rate()
```

The computed rate is cached in `groups.py._POISSON_BASE_RATE_CACHE` (not in a compiled constant).
`groups.py::expected_goals()` uses the fallback chain: explicit `base_rate` param → `_POISSON_BASE_RATE_CACHE` → `constants.EXPECTED_GOALS_BASE_RATE`.

### What NOT to Do (re: D-09, D-10)

- **Do NOT** make Poisson rate a 4th signal in the blender pipeline. It operates at a different layer (score distribution → goals, not match outcome probability).
- **Do NOT** blend Poisson rate with Elo/market/CatBoost probabilities. They measure different things.
- **Do NOT** move Poisson rate computation into blender.py as a "signal" — keep it in groups.py or as a standalone function called during initialization.

---

## 4. Blended Probability Injection into Simulation

### The Two Data Flows

This is the most architecturally critical section. There are TWO fundamentally different flows:

**Flow A — Calibration Fitting** (runs on every poll cycle or on demand):
```
prediction_history (past matches with actuals)
    → extract per-signal (prediction, actual) pairs
    → calibrate_signal() → (A, B, Brier) per signal
    → store calibration_params.json
```

**Flow B — Live Blended Prediction** (runs every simulation):
```
signal caches (odds_cache, catboost_cache) + Elo
    → apply_calibration(p_raw, A, B) → calibrated p per signal
    → compute_blend_weights(signal_briers) → weights per signal
    → blend_predictions(signal_preds, weights) → blended p per match
    → feed to simulation
```

Flow A uses past data with actual outcomes. Flow B uses future/upcoming match data from caches.

### Injection Point in main.py

In `_run_iteration()`, after signal cache refresh and `_merge_signals_into_history()` (~line 575), add:

```python
# ── Calibrate signals and blend ──
from src.blender import calibrate_signal, compute_blend_weights, blend_predictions

# Flow A: Fit calibration params from history
history = state.load_prediction_history()
for signal_key in ["elo", "market_odds", "catboost"]:
    pairs = extract_prediction_pairs(history, signal_key)
    if len(pairs) >= 30:
        preds, actuals = zip(*pairs)
        A, B = calibrate_signal(list(preds), list(actuals))
        calibration_params[signal_key] = {"A": A, "B": B}

# Flow B: Blend for each upcoming match and pass to simulation
# (blended_probs computed from signal caches + calibration params)
blended_probs = compute_blended_probs_for_simulation(
    teams, groups, bracket, signal_caches, calibration_params
)
```

Then pass `blended_probs` to `run_full_simulation()`.

### Modification to knockout.py

Current simulation uses `expected_score(elo_a, elo_b)` for every match. To inject blended probabilities:

Add a `blended_probs: dict[str, float]` parameter to `run_full_simulation()`, where keys are match_ids and values are team_a probabilities. When present, override `expected_score()`:

```python
def _simulate_r32_resolved(r32_matchups, played, elo_ratings, rng, blended_probs=None):
    for mid, match in r32_matchups.items():
        if mid in played:
            winner_progression[mid] = played[mid]["winner"]
            continue
        if blended_probs and mid in blended_probs:
            p_a = blended_probs[mid]
        else:
            p_a = expected_score(elo_ratings[team_a], elo_ratings[team_b])
        winner_progression[mid] = team_a if rng.random() < p_a else team_b
```

Same pattern for `_simulate_r16()` and `_simulate_knockout_round()`.

**Key consideration:** R32 match_ids are dynamically generated (e.g., "R32_01", "R32_02") and their teams depend on group outcomes. The blended probability must be for the *specific teams* in the match, not just the slot. This means blending must happen per-match for *all possible* R32 matchups, or more practically:

**For R32:** Blend probability when teams are known (during the simulation loop, after group standings are computed). This requires the blender to be callable *inside* the iteration loop for R32.

**For R16+:** Same issue — teams are determined by earlier round winners. Blended probabilities for these matches can only be computed after the matchups are known.

**Simplest approach:** Instead of pre-computing blended_probs for every possible match, create a function `get_blended_prob(team_a, team_b, signal_caches, calibration_params, elo_ratings) -> float` that blends on-the-fly. Called from within the simulation loop.

Wait — but signal caches don't contain probabilities for *every* team pair. Market odds and CatBoost are fetched for specific matches. The caches are keyed by match_id (R32_01, GS_A_01, etc.), not by team pair.

**Revised approach:** Pre-compute match-level blended probabilities from signal caches before calling simulation. The caches already contain per-match probabilities for all tournament matches. The R32 matchups are known from group stage results — you can look up the match_id in the cache and use the blended probability.

But during simulation, the actual R32 matchups depend on the randomly-simulated group results. You'd need probabilities for all ~500+ possible R32 matchups.

**Recommendation (the agent's Discretion):** The simplest correct approach is:

1. For **group matches** — use signal cache probabilities (match_id already known)
2. For **R32+ knockout matches** — fall back to Elo `expected_score()` for now
3. Add a `blend_prob_for_matchup(team_a, team_b, signal_caches, params) -> float` function that:
   - Checks if match_id is in any signal cache → blend cached probabilities
   - Falls back to Elo if no cache data → return `expected_score(elo_a, elo_b)` (effectively unblended)
   - This gracefully degrades per D-22 (never block)

This covers the common case (group matches have cached probabilities) while handling the edge case (knockout matchups depend on earlier results) with graceful fallback. The planner may refine this.

### What Changes in main.py Flow

```
_run_iteration() flow:
  ...
  └─ Signal cache refresh (line 546-573)
  └─ _merge_signals_into_history() (line 575)
  └─ [NEW] Calibration fitting (Flow A):
  │     - Load history
  │     - calibrate_signal() per signal
  │     - Store calibration_params.json
  └─ [NEW] Compute blend weights:
  │     - compute_blend_weights(signal_briers)
  └─ [MODIFIED] run_full_simulation(teams, groups, bracket, annex_c,
  │                                  played, played_groups, blend_params=...)
  │     - Inside simulation, for known match_ids:
  │       blend signal cache probs + apply calibration + weight
  │     - Fall back to Elo for unknowns
  └─ output results
```

---

## 5. Calibration Improvement Measurement (D-11, D-12)

### How to Measure

**Before calibration:** Use `evaluate_all_matches(signal_name="elo")` → get raw Brier and ECE for each signal.
**After calibration:** Use LOO-CV to compute calibrated Brier per signal and blended Brier.

### LOO-CV Implementation

```python
def loo_cv_brier(predictions: list[float], actuals: list[float],
                 calibrator) -> float:
    """Leave-one-out cross-validated Brier score.

    For each sample i, fits calibrator on all samples except i,
    predicts calibrated prob for sample i, computes Brier.
    Returns mean Brier across all folds.
    """
    n = len(predictions)
    if n < 2:
        return 1.0
    errors = []
    for i in range(n):
        train_preds = predictions[:i] + predictions[i+1:]
        train_actuals = actuals[:i] + actuals[i+1:]
        A, B = calibrator(train_preds, train_actuals)
        p_cal = apply_calibration(predictions[i], A, B)
        errors.append(brier_score(p_cal, actuals[i]))
    return sum(errors) / n
```

**Performance:** For N=30 and 3 signals, this does 90 calibrate_signal calls (~90 * 3 iterations * 30 samples ≈ 8,100 operations) — still negligible (< 0.01s).

### Blended Brier via LOO-CV

The `blended_Brier` in D-12 is the LOO-CV Brier of the *blended* predictions, not individual signals. Algorithm:

```
for each match i:
    # LOO: fit calibration on all other matches
    for each signal s:
        A_s, B_s = calibrate_signal(train_preds[s], train_actuals)
        p_cal_s = apply_calibration(pred_i[s], A_s, B_s)
    # Compute blend weight for signal s (from training data Brier)
    w_s = compute_blend_weights({s: brier_s for s in signals})
    # Blend
    p_blended = blend_predictions({s: p_cal_s for s in signals}, w_s)
    # Compute Brier for this fold
    brier_i = (p_blended - actual_i)^2

blended_Brier = mean(brier_i over all folds)
```

### Comparison to Baseline

Use existing `compare_baselines()` in evaluation.py:

```python
before = evaluate_all_matches(teams, played, played_groups, signal_name="elo")
# ... run LOO-CV to compute blended_Brier ...
after = {"model": "blended_loo", "metrics": {"brier": blended_Brier, "n": n}}
delta = compare_baselines(before, after)
# D-12: PASS if blended_Brier < best_single_signal_Brier
```

### Success Criterion (D-12)

`blended_Brier < best_single_signal_Brier` — directional only.

With ~30 matches, the standard error of Brier is approximately `sqrt(Brier*(1-Brier)/n)` ≈ `sqrt(0.127*0.873/30)` ≈ 0.06. A threshold like 0.02 is within noise range. The directional check is correct — if blending consistently beats single signals, it's working. Phase 16 adds significance testing.

---

## 6. Platt Scaling Cold-Start (D-03, D-04)

### Threshold Recommendation

**30 matches (D-03 default):** Supported by literature. For logistic regression with 2 parameters, the rule of thumb is 10-20 events per parameter (EPV). With 2 parameters and ~50% win rate:
- 30 matches → ~15 win events → ~7.5 EPV — marginal but workable
- Below 20 matches → <10 win events → <5 EPV — high risk of overfitting

**Per-signal, not global:** Elo may have 30+ matches while market_odds has 12. Each signal's threshold is checked independently.

### Transition from Identity to Calibrated

When `n_matches >= threshold`, fit Platt params. Store them in `calibration_params.json`. On the next poll cycle, use the stored params.

The transition is seamless: `apply_calibration()` with `(A=1.0, B=0.0)` returns the identity transform. With fitted params, it returns the calibrated probability.

### Detection of Insufficient Data

`calibrate_signal()` checks `len(predictions) < threshold`. If below threshold, returns `(1.0, 0.0)` for identity.

The caller (blend pipeline) does NOT need special logic — `(A=1.0, B=0.0)` naturally means "no calibration."

### Edge Case: Threshold Hit Mid-Tournament

If a signal crosses 30 matches mid-tournament, the next LOO-CV evaluation will include calibrated predictions for that signal. The blended Brier may temporarily increase as the calibrator fits on noisy data. This is expected — after ~40-50 matches, the calibrator stabilizes.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Logistic regression (2-param) | Anything custom | Newton-Raphson (40 lines) | Standard for Platt, converges in 3-5 iterations |
| Brier storage | Ring buffer, DB | Compute from prediction_history | ~300 operations per poll, no persistence needed |
| Simulation probability injection | Rewrite simulation engine | Add blended_probs param to knockout.py | Minimal surface area, clean separation |
| Calibration comparison | Custom comparison code | evaluation.compare_baselines() | Already exists, returns structured delta+verdict |
| 2x2 matrix inverse | numpy | Cramer's rule | 4 multiplications, 1 division |
| Cross-validation | sklearn's GridSearchCV | Pure Python LOO-CV loop | ~100 calibrate_signal calls, negligible cost |

---

## Common Pitfalls

### Pitfall 1: Log-Odds Infinity
**What goes wrong:** `log(p / (1-p))` produces ±inf for p=0 or p=1, crashing Newton-Raphson.
**Root cause:** Market odds or CatBoost may return 0.0 or 1.0 probabilities.
**How to avoid:** Clamp p to [1e-15, 1-1e-15] before log-odds transform. This matches the existing `eps=1e-15` clamping in `evaluation.py:log_loss()`.
**Warning signs:** NaN in A or B values.

### Pitfall 2: Hessian Singularity with Small Samples
**What goes wrong:** 2x2 Hessian has determinant ≈ 0, Newton step division by zero.
**Root cause:** < 20 matches with near-constant predictions.
**How to avoid:** Add ridge regularization (1e-6) to Hessian diagonal. Detect near-singular determinant (`abs(det) < 1e-12`) and break early.
**Warning signs:** `det` near zero during fitting.

### Pitfall 3: Opaque Cold-Start
**What goes wrong:** Blender produces identity probabilities without warning. Operator sees "blended" in output but gets unblended values.
**Root cause:** Cold-start is silent by design (graceful degradation), but operator may not know blending is inactive.
**How to avoid:** Log a message when `n_matches < threshold` for any signal: `"Signal {name}: using identity calibration ({n} matches, threshold {threshold})"`. Use python `logging` or `print()` matching existing project patterns.
**Warning signs:** Blended Brier equals best single-signal Brier.

### Pitfall 4: Blender Runs Everywhere
**What goes wrong:** `calibrate_signal()` is called during `_merge_signals_into_history()` AND during `_run_iteration()` AND during LOO-CV — fitting the same params 3x per poll cycle.
**Root cause:** No caching of fitted params.
**How to avoid:** Fit params once per poll cycle in `_run_iteration()`, store result, reuse for blending and LOO-CV. Write to `calibration_params.json` for persistence across restarts.
**Warning signs:** Duplicate fitting calls in trace.

### Pitfall 5: Rolling Window vs All Matches
**What goes wrong:** Rolled Brier (last 50 matches) differs from all-match Brier. Blend weights switch unexpectedly mid-tournament.
**Root cause:** Window edge effect when crossing match 50/51 boundary.
**How to avoid:** Default window of 50 is fine for 104-match tournament. Document in constants.py: `BRIER_WINDOW_SIZE = 50  # default, matches in window for rolling Brier computation`.
**Warning signs:** Brier jumps at window boundary.

### Pitfall 6: Blend Weights for Missing Signals
**What goes wrong:** A signal has no predictions for the current match but has a Brier weight from past matches. The blend sum is missing a signal.
**Root cause:** `compute_blend_weights()` works on Brier values. `blend_predictions()` works on per-match signal values. They can disagree.
**How to avoid:** In `blend_predictions()`, only include signals that have a prediction for this match. Re-normalize weights to sum to 1. Graceful degradation per D-22.

---

## Code Examples

### Newton-Raphson Platt Fitting (pure Python)

```python
import math

EPS = 1e-15
RIDGE = 1e-6
MAX_ITER = 50
CONV_TOL = 1e-6

def _sigmoid(x: float) -> float:
    if x < -100: return EPS
    if x > 100: return 1 - EPS
    return 1.0 / (1.0 + math.exp(-x))

def _log_odds(p: float) -> float:
    p = max(EPS, min(1 - EPS, p))
    return math.log(p / (1 - p))

def calibrate_signal(predictions: list[float], actuals: list[float],
                     threshold: int = 30) -> tuple[float, float]:
    """Fit Platt scaling parameters A, B via Newton-Raphson.

    Returns (A, B) where calibrated = sigmoid(A * log_odds(p) + B).
    Returns (1.0, 0.0) for identity if n < threshold.
    """
    n = len(predictions)
    if n < threshold:
        return (1.0, 0.0)  # identity calibration

    # Convert to log-odds space
    x = [_log_odds(p) for p in predictions]

    # Platt-adjusted targets
    n_pos = sum(1 for a in actuals if a == 1.0)
    n_neg = sum(1 for a in actuals if a == 0.0)
    # Handle edge cases (all draws, etc.)
    t_pos = (n_pos + 1) / (n_pos + 2) if n_pos > 0 else 0.5
    t_neg = 1.0 / (n_neg + 2) if n_neg > 0 else 0.5
    t = [t_pos if a == 1.0 else t_neg if a == 0.0 else 0.5 for a in actuals]

    A, B = 0.0, 0.0  # identity initialization

    for _ in range(MAX_ITER):
        f = [A * xi + B for xi in x]
        p = [_sigmoid(fi) for fi in f]

        # Gradient: dL/dA, dL/dB
        dA = sum(xi * (pi - ti) for xi, pi, ti in zip(x, p, t))
        dB = sum(pi - ti for pi, ti in zip(p, t))

        # Hessian (with ridge for numerical stability)
        wx = [pi * (1 - pi) for pi in p]
        H_AA = sum(xi * xi * w for xi, w in zip(x, wx)) + RIDGE
        H_AB = sum(xi * w for xi, w in zip(x, wx))
        H_BB = sum(wx) + RIDGE

        det = H_AA * H_BB - H_AB * H_AB
        if abs(det) < 1e-12:
            break

        # Newton step: H^{-1} * gradient
        dA_step = (H_BB * dA - H_AB * dB) / det
        dB_step = (H_AA * dB - H_AB * dA) / det

        A -= dA_step
        B -= dB_step

        if abs(dA_step) < CONV_TOL and abs(dB_step) < CONV_TOL:
            break

    return (A, B)
```

### Brier-Weighted Blending

```python
def compute_blend_weights(signal_briers: dict[str, float]) -> dict[str, float]:
    """Convert per-signal Brier scores to blend weights.

    w_s = 1 / max(brier_s, 0.05), normalized to sum=1.
    """
    raw = {}
    for key, brier in signal_briers.items():
        raw[key] = 1.0 / max(brier, 0.05)
    total = sum(raw.values())
    if total == 0:
        equal_weight = 1.0 / max(len(raw), 1)
        return {k: equal_weight for k in raw}
    return {k: v / total for k, v in raw.items()}


def blend_predictions(
    signal_preds: dict[str, float],
    weights: dict[str, float],
) -> float:
    """Compute weighted blend of calibrated probabilities.

    Only includes signals present in both dicts.
    Re-normalizes weights to sum to 1 for the available signals.
    """
    available = {k: v for k, v in signal_preds.items() if k in weights and v is not None}
    if not available:
        return 0.5  # no data, uniform prior
    w_sum = sum(weights[k] for k in available)
    if w_sum == 0:
        return sum(available.values()) / len(available)
    blended = sum(weights[k] * available[k] for k in available) / w_sum
    return round(blended, 6)
```

### LOO-CV Blended Brier

```python
def loo_cv_blended_brier(
    histories: dict[str, tuple[list[float], list[float]]],
) -> float:
    """Leave-one-out cross-validated Brier for blended predictions.

    histories: {signal_name: (predictions, actuals)} — all aligned by match index.
    """
    signal_names = list(histories.keys())
    if not signal_names:
        return 1.0
    n = len(next(iter(histories.values()))[0])
    if n < 2:
        return 1.0

    errors = []
    for i in range(n):
        # LOO: fit calibration on all except i
        cal_params = {}
        train_briers = {}
        for sig in signal_names:
            preds, actuals = histories[sig]
            train_preds = preds[:i] + preds[i+1:]
            train_actuals = actuals[:i] + actuals[i+1:]
            A, B = calibrate_signal(train_preds, train_actuals, threshold=1)
            cal_params[sig] = (A, B)
            # Brier on training data for weight computation
            train_brier = compute_metrics(train_preds, train_actuals)["brier"]
            train_briers[sig] = train_brier

        # Predict held-out match
        cal_probs = {}
        for sig in signal_names:
            A, B = cal_params[sig]
            p = histories[sig][0][i]
            cal_probs[sig] = apply_calibration(p, A, B)

        weights = compute_blend_weights(train_briers)
        p_blended = blend_predictions(cal_probs, weights)
        actual = histories[signal_names[0]][1][i]
        errors.append((p_blended - actual) ** 2)

    return sum(errors) / n
```

---

## Validation Architecture

> workflow.nyquist_validation is enabled in config.json.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, 388 tests) |
| Config file | `pyproject.toml` (pytest options) or pytest.ini |
| Quick run | `pytest tests/test_blender.py -x -v` |
| Full suite | `pytest tests/ -x -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| V2-07 | calibrate_signal returns identity (1,0) for < N matches | unit | `pytest tests/test_blender.py::TestCalibrateSignal::test_cold_start -x` |
| V2-07 | calibrate_signal fits A,B via Newton-Raphson | unit | `pytest tests/test_blender.py::TestCalibrateSignal::test_fit -x` |
| V2-07 | apply_calibration maps raw prob through sigmoid(A*x+B) | unit | `pytest tests/test_blender.py::TestApplyCalibration::test_identity -x` |
| V2-07 | apply_calibration with fitted params changes probabilities | unit | `pytest tests/test_blender.py::TestApplyCalibration::test_calibrated -x` |
| V2-08 | compute_blend_weights = 1/max(brier,0.05) normalized | unit | `pytest tests/test_blender.py::TestBlendWeights::test_formula -x` |
| V2-08 | compute_blend_weights handles single signal | unit | `pytest tests/test_blender.py::TestBlendWeights::test_single -x` |
| V2-08 | blend_predictions weighted average normalized | unit | `pytest tests/test_blender.py::TestBlend::test_basic -x` |
| V2-08 | blend_predictions handles missing signal gracefully | unit | `pytest tests/test_blender.py::TestBlend::test_missing_signal -x` |
| V2-09 | compute_poisson_base_rate from historical data | unit | `pytest tests/test_blender.py::TestPoisson::test_base_rate -x` |
| V2-09 | compute_poisson_base_rate falls back to default | unit | `pytest tests/test_blender.py::TestPoisson::test_fallback -x` |
| V2-11/D-11 | LOO-CV blended Brier < best single-signal Brier | integration | `pytest tests/test_blender.py::TestLOOCV::test_improvement -x` |
| V2-12/D-12 | Calibrated ECE < raw ECE (or comparable) | integration | `pytest tests/test_blender.py::TestCalibration::test_ece_improvement -x` |

### Existing Test Patterns to Follow

- `tests/test_evaluation.py` — pure function tests with pytest, no fixtures needed for unit tests
- Test classes per component (TestCalibrateSignal, TestApplyCalibration, etc.)
- Use `pytest.approx()` for float comparisons
- Follow existing rounding convention (`round(x, 6)`)

### Wave 0 Gaps

- [ ] `tests/test_blender.py` — new test module, all tests are Wave 0 gaps
- [ ] `tests/conftest.py` — may need fixture for sample prediction data if shared across blender tests

---

## Security Domain

> security_enforcement is enabled by default.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Clamp p to [1e-15, 1-1e-15] before log_odds. Validate input list lengths match. |
| V6 Cryptography | no | No encryption operations in blender.py. JSON persistence uses no crypto. |

### Known Threat Patterns for Python stdlib

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| JSON injection via calibration_params.json | Tampering | Read via `json.load()` (safe by definition — no eval). Atomic write via state.py pattern. |
| Division by zero in weight computation | DoS | Floor at 0.05 (D-07). Guard `det == 0` in Newton step. |
| Floating-point overflow in sigmoid | DoS | Clamp sigmoid input at ±100. Match evaluation.py EPS pattern. |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | No historical WC match data exists in the repo | Section 3 | Confirmed by file inspection — no historical match data file found. If one is added externally, the compute function will find it. |
| A2 | Newton-Raphson converges in < 10 iterations for N < 100 | Section 1 | If data is severely ill-conditioned, max 50 iterations prevents infinite loop. Risk: LOW. |
| A3 | prediction_history entries are chronologically ordered | Section 2 | [VERIFIED] `evaluate_all_matches()` sorts by completed_at + match_id. The append pattern also preserves order. If entries are out of order, window slicing will include wrong matches. Risk: LOW. |
| A4 | Signal cache match_ids match simulation match_ids | Section 4 | [VERIFIED from Phase 13 design] Signal caches are keyed by same match_id as bracket.json and groups.json. Risk: LOW. |
| A5 | LOO-CV with N=30 provides stable Brier estimate | Section 5 | SE ≈ 0.06 with 30 matches. Directional check (D-12) is robust. Phase 16 adds significance testing. Risk: MEDIUM — do not report LOO-CV Brier as precise estimate. |
| A6 | The user has historical World Cup data available for V2-09 | Section 3 | ASSUMED. No such file exists in the repo. The task may need to create one, or use the existing constant. Planner should gate this behind a checkpoint. |

---

## Open Questions (RESOLVED)

1. **Poisson base rate data source: What historical data should V2-09 use?**
   - RESOLVED: Option C — add `compute_poisson_base_rate()` infrastructure function in `groups.py` that reads from a data file if it exists, otherwise falls back to 1.25 constant. Data file creation gated for future (no existing historical WC data file in repo).
   - Planner decision per D-09/D-10: Keep the constant as default, add the computation infrastructure. The function `compute_poisson_base_rate(None)` returns 1.25 gracefully.

2. **Knockout match blending: Should R32+ matches use blended probabilities or fall back to Elo?**
   - RESOLVED: Group matches only. R32+ knockout matches fall back to Elo `expected_score()` per existing pattern.
   - Planner decision: `_get_blended_prob()` helper in `knockout.py` returns blended prob when match_id is in blend_params, falls back to `expected_score()` for all other cases. This naturally handles the "unknown teams until simulation" issue for R32+.

3. **Should `blended` key be written to prediction_history?**
   - RESOLVED: Yes — write `blended` key during `_merge_signals_into_history()` per agent discretion (D-03 precedent).
   - Planner decision: After `_calibrate_and_blend()` returns match_probs, iterate prediction_history and add `signals["blended"]` entries. This enables `evaluate_all_matches(signal_name="blended")` which was already wired in Phase 13 D-11.

---

## Environment Availability

> Step 2.6: SKIPPED (no external dependencies for this phase beyond Python stdlib `math` module, which is always available. No new packages are installed.)

This phase uses only Python stdlib (`math`, `json`). No external tools, runtimes, or services are required beyond what the project already uses (Python 3.10+).

---

## Sources

### Primary (HIGH confidence)
- **Codebase read**: `worldcup_predictor/src/evaluation.py` — existing Brier, calibration_curve, ECE, evaluate_all_matches pattern
- **Codebase read**: `worldcup_predictor/src/constants.py` — EXPERT_GOALS_BASE_RATE=1.25, signal cache TTLs
- **Codebase read**: `worldcup_predictor/main.py:_run_iteration()` — signal cache refresh and merge flow (lines 545-621)
- **Codebase read**: `worldcup_predictor/src/knockout.py:run_full_simulation()` — simulation entry point for probability injection
- **Codebase read**: `worldcup_predictor/src/groups.py:expected_goals()` — Poisson base rate integration point
- **Codebase read**: `worldcup_predictor/src/simulation.py` — knockout-only simulation (no blend)
- **Codebase read**: `worldcup_predictor/src/state.py` — load/save prediction_history, signal cache helpers
- **Codebase read**: `worldcup_predictor/data/prediction_history.json` — actual data format with compound entries
- **Codebase read**: `worldcup_predictor/tests/test_evaluation.py` — existing test patterns (pure functions, pytest.approx)

### Secondary (MEDIUM confidence)
- **CONTEXT.md**: 14-CONTEXT.md with all 12 decisions and canonical refs — verified primary source for user decisions
- **REQUIREMENTS.md**: V2-07, V2-08, V2-09 requirement definitions
- **STATE.md**: Project history and phase dependency tracking

### Tertiary (LOW confidence)
- None — all claims verified against codebase or decision documents

---

## Metadata

**Confidence breakdown:**
- Standard stack (Platt scaling approach, Newton-Raphson): HIGH — verified against established literature and codebase constraints
- Architecture (blender → knockout injection): HIGH — verified against actual code flow in main.py, knockout.py, simulation.py
- LOO-CV approach: HIGH — verified against evaluation.py patterns
- Cold-start threshold: MEDIUM — 30 matches is the user's recommendation but may be refined; literature supports 10-20 EPV
- Poisson base rate data source: LOW — no historical data file confirmed in repo; recommendation is to add infrastructure + fall back to constant
- Rolling Brier implementation: HIGH — on-the-fly computation from prediction_history is simple, matches project patterns

**Research date:** 2026-06-16
**Valid until:** 2026-07-16 (stable — Newton-Raphson math and codebase structure won't change in 30 days)

---

## RESEARCH COMPLETE

**Phase:** 14 - Signal Blending
**Confidence:** HIGH

### Key Findings
1. **Newton-Raphson is recommended** for Platt scaling — 2 parameters, converges in 3-5 iterations, pure Python. Add ridge regularization (1e-6) for small-sample stability.
2. **Two data flows are architecturally distinct:** (A) calibration fitting from past prediction_history entries, (B) live blended prediction from signal caches for upcoming matches. The planner must create tasks for both.
3. **Probability injection into simulation** happens via a new `blended_probs` param on `run_full_simulation()`. Inside, override `expected_score()` calls with blended probabilities when available. Fall back to Elo for dynamically-determined matchups (R32+).
4. **Rolling Brier is computed on-the-fly** from prediction_history — no storage needed for current data volumes (~30-104 entries).
5. **Poisson base rate computation** infrastructure belongs in groups.py. Data sourcing is an open question (no historical WC data file exists). Recommend adding infrastructure + keeping 1.25 constant.
6. **Cold-start threshold at 30 matches** is well-supported. Per-signal, not global. Identity calibration below threshold.

### File Created
`.planning/phases/14-signal-blending/14-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack (Platt scaling, Newton-Raphson) | HIGH | Verified against known logistic regression literature, D-01 constraint, codebase patterns |
| Architecture (blender/simulation integration) | HIGH | Verified against actual main.py/knockout.py code flow |
| Poisson Base Rate | MEDIUM | Computation approach is clear; data sourcing is unresolved |
| LOO-CV | HIGH | Verified against existing evaluation.py patterns |
| Rolling Brier | HIGH | Straightforward computation from existing data structures |

### Open Questions (RESOLVED)
- **Poisson base rate data:** RESOLVED — Option C: infrastructure function `compute_poisson_base_rate()` added with graceful fallback to 1.25. Data file creation gated for future.
- **Knockout blending:** RESOLVED — Group matches only. R32+ fall back to Elo `expected_score()` via `_get_blended_prob()` helper.

### Ready for Planning
Research complete. Planner can now create PLAN.md files with full understanding of the two data flows, Newton-Raphson approach, calibration parameter persistence, simulation injection point, and test strategy.
