---
phase: 15-context-signals
plan: 15-02
subsystem: predictors
tags: ["form", "lineup", "elo-residual", "market-value", "signal-computation"]
requires: ["15-01", "elo.py", "constants.py", "state.py"]
provides: ["compute_form_signal", "compute_lineup_signal"]
affects: ["prediction_ledger", "blender"]
tech-stack:
  added: []
  patterns: ["cache-dict output with fetched_at/expires_at/matches", "ledger_upsert per signal", "pure stdlib no numpy"]
key-files:
  created:
    - "src/predictors/form.py"
    - "src/predictors/lineup.py"
  modified:
    - "src/predictors/__init__.py"
metrics:
  duration_minutes: 12
  tasks_completed: 3
---

# Phase 15 Plan 2: Form and Lineup Signal Computation Summary

Created two signal computation modules (form.py and lineup.py) following the odds.py pattern: accept data → compute probabilities → return cache dict → upsert to prediction ledger. Both are pure Python stdlib with no numpy/sklearn dependencies.

## Files Created/Modified

### 1. `src/predictors/form.py` (356 lines)
- **`compute_form_signal(teams, groups, played, played_groups, bracket, k_factor, form_window)`**
- Computes per-team Elo residuals from played match results (played + played_groups)
- Residual = actual - expected_score; actual ∈ {1.0, 0.5, 0.0}, expected via `elo.expected_score(elo_a, elo_b, home_advantage=0)`
- Rolling window of FORM_WINDOW_SIZE (5) by recency; all available if fewer
- form_delta = avg(home_residuals) - avg(away_residuals); p = sigmoid(k * form_delta)
- k=1.0 (DEFAULT_FORM_K); clamps probability to [1e-15, 1-1e-15]
- **72 matches processed, 55 available** (17 teams have no match history yet in this cold tournament state)
- Helpers: `_sigmoid`, `_compute_residual`, `_build_team_residuals`, `_compute_match_form_signal`

### 2. `src/predictors/lineup.py` (206 lines)
- **`compute_lineup_signal(groups, team_values, bracket, k_factor)`**
- Computes strength_delta = ln(home_value / away_value); p = sigmoid(k * strength_delta)
- k=0.35 (DEFAULT_LINEUP_K); data from `state.load_team_values()` (static file)
- Accepts pre-loaded `team_values` dict or auto-loads; bracket auto-loads
- **72 matches processed, 72 available** (all 49 teams have market values in team_values.json)
- Helpers: `_sigmoid`, `_compute_match_lineup_signal`

### 3. `src/predictors/__init__.py` (modified)
- Updated package docstring to mention form.py and lineup.py alongside odds.py and catboost.py

## Edge Cases Handled (Both Modules)

| Edge Case | Behavior |
|-----------|----------|
| Missing team (not in data) | `available: false` with `reason: "team_not_found: {name}"` |
| 0 match history | `available: false` with `reason: "no_match_history: {name}"` |
| Non-positive market value | `available: false` with `reason: "non_positive_value: {name}={val}"` |
| Unresolved bracket slot | Silently skipped (team_a/team_b is None) |
| Ledger upsert failure | `try/except` with `logger.warning`, signal computation unaffected |
| Probability extreme values | Clamped to [1e-15, 1-1e-15] via max/min |
| Overflow in sigmoid | `try/except OverflowError` returns 0.0 or 1.0 |

## Verification Results

```python
# Form signal
>>> r = compute_form_signal(teams, groups, played=played, played_groups=played_groups)
>>> len(r["matches"]), sum(1 for m in r["matches"].values() if m.get("available"))
(72, 55)

# Lineup signal
>>> r = compute_lineup_signal(state.load_groups())
>>> len(r["matches"]), sum(1 for m in r["matches"].values() if m.get("available"))
(72, 72)

# No numpy/sklearn imports in either module ✓
# Both modules importable from src.predictors package ✓
```

## Deviations from Plan

None — plan executed exactly as written.

## Stub Tracking

No stubs found. All code paths provide real computations (no placeholder text, no hardcoded empty values that flow to UI).

## Self-Check: PASSED

- [x] `src/predictors/form.py` exists (356 lines)
- [x] `src/predictors/lineup.py` exists (206 lines)
- [x] `src/predictors/__init__.py` modified (docstring updated)
- [x] Commit `538649d` — form.py created
- [x] Commit `d2132f0` — lineup.py created
- [x] Commit `6a25fb5` — __init__.py updated
- [x] SUMMARY.md exists at `.planning/phases/15-context-signals/15-02-SUMMARY.md`
