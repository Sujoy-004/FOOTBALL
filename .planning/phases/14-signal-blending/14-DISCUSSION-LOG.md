# Phase 14: Signal Blending — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-16
**Phase:** 14-Signal-Blending
**Areas discussed:** Platt scaling, Blender location, Poisson base rate, Cold-start strategy, Held-out evaluation, Weighting function

---

## Platt Scaling: sklearn vs pure Python

| Option | Description | Selected |
|--------|-------------|----------|
| sklearn | Full ML library, ~50MB+ dep for ~20 lines of logistic regression | |
| Pure Python | Newton-Raphson or gradient descent, no new dependencies | ✓ |

**User's choice:** Pure Python. Rejected sklearn — massive dependency for tiny requirement, CLI predictor not ML training platform.

---

## Blender Location: new module vs extend evaluation.py

| Option | Description | Selected |
|--------|-------------|----------|
| New module: src/blender.py | Clean separation: inference vs metrics | ✓ |
| Extend evaluation.py | Mixes inference with reporting | |
| ensemble/ package | Over-engineered for current scope | |

**User's choice:** `src/blender.py`. Rejected `evaluation.py` (responsibility leakage) and `ensemble/` (premature — Phase 15+).

---

## Poisson Base Rate: signal vs prior modifier

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone 4th signal | Treats base rate as another prediction signal | |
| Prior modifier | Anchors blended probabilities in data-sparse regimes | |
| Keep in groups.py | Score distribution layer, not signal pipeline | ✓ |

**User's choice:** Keep in `groups.py` score generation. Not a signal — Poisson produces score distributions, not match outcome probabilities. Flagged as the biggest architectural risk of the phase.

---

## Cold-Start Fitting Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Wait for N matches | Identity calibration until threshold | ✓ |
| Bayesian priors | Weak priors to avoid overfitting | |
| Incremental updates | Fit on startup, update per-iteration | |

**User's choice:** Identity calibration (`p_calibrated = p_raw`) until 30+ matches. Fitting on 20-30 observations can make calibration worse than raw.

---

## Held-Out Evaluation Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Leave-one-out CV | Maximizes data usage with small sample | ✓ |
| Train/test split | Too little data for reliable split | |
| Time-series split | Same reason — insufficient data | |

**User's choice:** Leave-one-out cross-validation. Maximizes data usage for the ~30-match sample.

---

## Weighting Function

| Option | Description | Selected |
|--------|-------------|----------|
| 1/Brier (inverse) | Lower Brier = higher weight (shown as baseline) | |
| Softmax(-Brier) | Smooth bounded weights | |
| Inverse squared | More aggressive discrimination | |
| Rank-based | Ignores magnitude, cares only about ordering | |
| Inverse with floor | 1 / max(brier, 0.05), then normalize | ✓ |

**User's choice:** Inverse Brier with floor (`1 / max(brier, 0.05)`). Rejected softmax — smoothness buys nothing when weights recompute per-iteration.

---

## the agent's Discretion

- Exact implementation of Platt logistic fit (Newton-Raphson vs gradient descent)
- Threshold value for cold-start (30 matches is recommendation)
- Rolling Brier window size (50 matches recommended)
- Whether `blended` key written to prediction_history at merge time or computed on-the-fly

## Deferred Ideas

None — discussion stayed within phase scope.
