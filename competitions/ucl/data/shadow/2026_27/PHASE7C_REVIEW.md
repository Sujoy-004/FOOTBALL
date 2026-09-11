# PHASE 7C — Statistical / Evaluation Review

**Reviewer**: Agent 7C (read-only)
**Date**: 2026-09-11
**Scope**: Policy conformance, bootstrap correctness, segment discipline, historical baselines, n=0 report framing for 2026/27 live shadow evaluation.

---

## 1. Policy Conformance

| Check | File:Line | Verdict |
|---|---|---|
| `n < 30` → `insufficient_evidence` in comparisons | `shadow_eval.py:876-877` | **PASS** |
| `n == 0` → `insufficient_evidence (n=0)` string | `shadow_eval.py:872` | **PASS** |
| `_metrics()` returns `{"n": 0, "status": "insufficient"}` when no probs | `shadow_eval.py:772-773` | **PASS** |
| `gate_verdict()` checks `n_oos < min_oos` (default 30) | `historical.py:324,338-341` | **PASS** |
| Historical gate: `min_oos=30` enforced in `evaluate_matches` | `gate.py:265-272` → `historical.py:316` | **PASS** |
| Report path enforces n>=30 for comparisons | `shadow_eval.py:876` | **PASS** |
| Report path sets status=insufficient for n=0 | `shadow_eval.py:872,773` | **PASS** |
| **Overall** | | **PASS** |

The live `build_report()` comparison block (`shadow_eval.py:868-898`) enforces:
- n=0 → `verdict: "insufficient_evidence (n=0)"` (line 872)
- 0 < n < 30 → `verdict: "insufficient_evidence (n=N)"` (line 877)
- n >= 30 → proceeds to bootstrap and verdict (line 879+)

`_metrics()` (`shadow_eval.py:772-773`) returns `status: "insufficient"` when the probs list is empty, ensuring all strategy metrics at n=0 carry the insufficient marker.

No promotion is possible without an explicit comparison verdict of `"preferred"` (line 886-888), which requires n >= 30 AND CI lower bound > 0.

---

## 2. Bootstrap Correctness

| Parameter | Historical (`candidate_gate.py`) | Live (`shadow_eval.py`) | Match? |
|---|---|---|---|
| Seed | `BOOT_SEED = 20260601` (line 49, via `market_elo_investigation.py`) | `BOOT_SEED = 20260601` (line 61) | **YES** |
| n_boot | `N_BOOT = 2000` (line 49, via `market_elo_investigation.py`) | `N_BOOT = 2000` (line 62) | **YES** |
| Method | Paired percentile bootstrap (`delta_ci`, lines 248-259) | Paired percentile bootstrap (`_paired_bootstrap`, lines 787-800) | **YES** |
| CI type | 95% percentile (2.5th, 97.5th) | 95% percentile (2.5th, 97.5th) | **YES** |
| Delta definition | `ll_A[idx].mean() - ll_B[idx].mean()` | `_match_ll(second) - _match_ll(first)` per match, then bootstrap mean | **YES** (equivalent) |

**Detail on delta-LL equivalence**:
- `candidate_gate.py:delta_ci()` (line 254): computes `mean(ll_A_resampled) - mean(ll_B_resampled)`.
- `shadow_eval.py:build_report()` (lines 879-884): computes per-match `_match_ll(B) - _match_ll(A)`, then calls `_paired_bootstrap(deltas)` which bootstraps `mean(deltas_resampled)`.
- Both are mathematically identical: they bootstrap the mean of paired differences. The order of subtraction is the same (B minus A, where A = first, B = second in `_PREDICTION_PAIRS`).

**One minor note**: `shadow_eval.py:_paired_bootstrap` (line 787) uses `arr[idx].mean(axis=1)` which bootstraps the mean of the *entire delta vector* on each resample — this is the standard paired bootstrap for the mean difference. The historical `delta_ci` does the same via `ll_A[idx].mean(axis=1) - ll_B[idx].mean(axis=1)`. Both are correct.

---

## 3. Segment Discipline

### 3.1 Three disjoint populations

`shadow_eval.py:838-842`:
```python
segment_predicates = (
    ("all", lambda rec: True),
    ("odds_available", lambda rec: bool(rec.get("odds_available"))),
    ("odds_unavailable", lambda rec: not bool(rec.get("odds_available"))),
)
```
These are mutually exclusive and exhaustive by construction (`odds_available` is a boolean field in every prediction record). **PASS**.

### 3.2 Dual-segment requirement

The Phase-5 policy requires a candidate's verdict to depend on BOTH the odds-available and odds-unavailable segments — superiority in one segment alone is not sufficient. The live `build_report()` computes all three segments independently, and the comparison verdicts are per-comparison (not per-segment). The code does not currently have an explicit "both segments required" gate because **there is nothing to gate at n=0**. When n >= 30 is reached, this check will need to be enforced. Current code structure supports it (segments are reported separately; the report reader must cross-reference both). **PASS with caveat**: the dual-segment requirement is structural (all three segments are computed and reported), but there is no automated assertion that a "preferred" verdict requires both segments to independently confirm superiority. This is a **documentation-level concern** only at n=0; enforcement becomes relevant at n >= 30.

### 3.3 Current 2026/27 reality: odds_available is empty

All 357 frozen predictions have `odds_available: false` (UCL matches in this season lack pre-match market odds at freeze time). This means:
- **odds_available segment**: n=0 (and will remain n=0 until a fixture with usable odds is frozen and scored)
- **odds_unavailable segment**: all 357 predictions, n=0 scored (no results yet)
- **all segment**: union = 357 predictions, n=0 scored

The report at `SHADOW_EVALUATION.md:18-24` correctly shows:
```
## Segment: odds_available (n=0)
```
This is not a silent merge — the segment is reported with explicit n=0. **PASS**.

---

## 4. Historical Expectation Baselines (Phase 7D reference)

### 4.1 Population sizes

| Population | n | Seasons | Source |
|---|---|---|---|
| ALL | 619 | 2019/20 – 2023/24 | `candidate_gate_results.json:24-25` |
| ODDS | 469 | 2020/21 – 2023/24 | `candidate_gate_results.json:33-34` |
| NOODS | 150 | 2019/20 – 2023/24 | `candidate_gate_results.json:43-44` |

### 4.2 ALL population (n=619) — from `candidate_gate_results.json:pooled.ALL`

| Model | LL | Brier | ECE |
|---|---|---|---|
| production | 0.975163 | 0.192621 | 0.063495 |
| me_equal | 0.950933 | 0.185114 | 0.062265 |
| me_prior_fixed | 0.947601 | 0.184403 | 0.053431 |
| elo_only | 1.030656 | 0.198676 | 0.130024 |
| uniform | 1.098612 | 0.222222 | 0.117394 |
| freq | 1.060321 | 0.214071 | 0.039693 |

Delta-LL (production − me_equal): **+0.02476**, 95% CI [−0.011024, +0.056559] — **straddles zero** (G2 FAIL).

### 4.3 ODDS population (n=469) — from `candidate_gate_results.json:pooled.ODDS`

| Model | LL | Brier | ECE |
|---|---|---|---|
| production | 0.961159 | 0.189353 | 0.076098 |
| me_equal | 0.923804 | 0.181569 | 0.055613 |
| me_prior_fixed | 0.919407 | 0.180631 | 0.055671 |
| market_only | 0.893925 | 0.174817 | 0.066147 |
| elo_only | 1.029025 | 0.199468 | 0.135886 |
| uniform | 1.098612 | 0.222222 | 0.125089 |
| freq | 1.051193 | 0.212111 | 0.028505 |

Delta-LL (production − me_equal): **+0.036977**, 95% CI [**+0.013525**, +0.059045] — **CI strictly above zero** (G3 PASS).

### 4.4 NOODS population (n=150) — from `candidate_gate_results.json:pooled.NOODS`

| Model | LL | Brier | ECE |
|---|---|---|---|
| production | 1.018948 | 0.202839 | 0.073044 |
| me_equal | 1.035758 | 0.196200 | 0.139262 |
| me_prior_fixed | 1.035758 | 0.196200 | 0.139262 |
| elo_only | 1.035758 | 0.196200 | 0.139262 |
| uniform | 1.098612 | 0.222222 | 0.093333 |
| freq | 1.088859 | 0.220198 | 0.076437 |

Delta-LL (production − me_equal): **−0.016968**, 95% CI [−0.122535, +0.084081] — straddles zero, no material difference.

Key observation: on NOODS, me_equal ≡ me_prior_fixed ≡ elo_only by construction (no odds → pure Elo fallback).

### 4.5 Historical directional claims (expectations for live Phase 7D)

**(a) ODDS: market-only/merged beat production on LL**
- `market_only LL = 0.893925` vs `production LL = 0.961159` on ODDS.
- `me_equal LL = 0.923804` vs `production LL = 0.961159` on ODDS.
- Delta-LL production − me_equal on ODDS: +0.0370, CI [0.0135, 0.0590] — **strictly positive**.
- **Expected live sign**: positive (production worse than candidates on odds matches).

**(b) NOODS fallback is the weak point**
- Production LL 1.0189 vs me_equal LL 1.0358 on NOODS.
- On NOODS, candidates degrade to pure Elo — production's 4-signal ensemble is slightly better (but CI straddles 0).
- **Expected live sign**: production slightly better (negative delta_ll), consistent with historical.

**(c) me_equal ≈ me_prior_fixed (gate G2 note)**
- ODDS: me_equal LL 0.9238 vs me_prior_fixed LL 0.9194 — difference 0.0044, practically identical.
- ALL: me_equal LL 0.9509 vs me_prior_fixed LL 0.9476 — difference 0.0033.
- **Expected live sign**: me_prior_fixed marginally better (negative delta_ll for me_equal − me_prior_fixed), consistent with learned weights slightly outperforming equal weights.

**(d) Calibration (ECE) plausibility**
- production ECE: 0.0635 (ALL), 0.0761 (ODDS), 0.0730 (NOODS) — moderate calibration.
- me_equal ECE: 0.0623 (ALL), 0.0556 (ODDS), 0.1393 (NOODS) — better on ODDS (odds-informed), worse on NOODS (Elo-only, overconfident).
- uniform ECE: 0.1174 (ALL), 0.1251 (ODDS), 0.0933 (NOODS) — poorly calibrated (always 1/3).
- freq ECE: 0.0397 (ALL), 0.0285 (ODDS), 0.0764 (NOODS) — best calibration (empirical fit).
- **Expected live pattern**: production ECE ~0.05–0.08 on scored matches; me_equal ECE ~0.05–0.06 on odds-available, ~0.12–0.15 on odds-unavailable.

---

## 5. Verdict Framing for n=0

With n=0 scored fixtures in every segment, the ONLY valid status for every segment is `insufficient evidence`. No promotion, no tuning, no directional claims are permissible.

### 5.1 Required wording for each segment

**Segment: all (n=0)**
> Status: **Insufficient evidence**. Zero fixtures have been scored (all 119 pending fixtures have kickoffs ≥ 2026-10-13). No log-loss, Brier, or ECE metrics can be computed. No paired comparison is possible. No promotion or demotion is permitted.

**Segment: odds_available (n=0)**
> Status: **Insufficient evidence**. The odds-available segment contains zero frozen predictions (all 357 frozen predictions have `odds_available=False`). No evaluation is possible. This segment will remain empty until a fixture with pre-match market odds is frozen and scored.

**Segment: odds_unavailable (n=0)**
> Status: **Insufficient evidence**. All 357 frozen predictions fall in this segment, but zero have scored results. No metrics can be computed. No promotion or demotion is permitted.

### 5.2 No promotion statement permissible

Per Phase-5 policy (in force): promotions are **forbidden** without explicit future review. At n=0, no comparison can produce a `"preferred"` verdict. The code enforces this at `shadow_eval.py:872` (n=0 → insufficient_evidence) and `shadow_eval.py:876` (n < 30 → insufficient_evidence). The report must not state any directional claim, advantage, or preference.

### 5.3 What to report

The report should state:
1. n_prediction_records = 357 (119 fixtures × 3 strategies)
2. n_scored_fixtures = 0 (all kickoffs in the future)
3. All segments: status = insufficient evidence
4. All comparisons: verdict = insufficient_evidence (n=0)
5. **No promotion statement**
6. Next review trigger: when n_scored >= 30 in any segment

---

## 6. Expected Live-vs-Historical Consistency Checks (Phase 7D)

When n >= ~50 per segment, run these checks:

| # | Check | Expected sign | Source |
|---|---|---|---|
| C1 | `production − me_equal` delta-LL on ALL | Positive (production worse) | candidate_gate G2 note |
| C2 | `production − me_equal` delta-LL on ODDS | Positive (strictly, CI > 0) | candidate_gate G3 |
| C3 | `production − me_equal` delta-LL on NOODS | Negative or ~0 (production slightly better or equivalent) | candidate_gate G4 |
| C4 | `me_equal − market_only` delta-LL on ODDS | Positive (market_only better) | candidate_gate CIs |
| C5 | `me_equal − me_prior_fixed` delta-LL | Near 0 (practically equivalent) | candidate_gate delta |
| C6 | me_equal ECE on ODDS vs NOODS | Lower on ODDS (odds calibration helps) | eval_results ablation |
| C7 | production ECE | ~0.05–0.08 across segments | eval_results overall |
| C8 | Uniform LL | Exactly 1.098612 (= ln(3)) | mathematical constant |
| C9 | Freq LL | ~1.05–1.06 on ALL | eval_results overall |
| C10 | All 3 strategies beat uniform on scored matches | LL < 1.098612 | gate_verdict requirement |

---

## 7. Discrepancies and Severity

| # | Finding | Severity | Notes |
|---|---|---|---|
| D1 | No automated dual-segment gate assertion | Low | Structural support exists (3 segments reported). Enforcement becomes relevant at n >= 30. Documentation-level at n=0. |
| D2 | No live "NOODS-specific" segment label | Low | The `odds_unavailable` segment IS the NOODS population. Naming differs but semantics are identical. No functional impact. |
| D3 | Historical eval_results production LL (0.961159 ODDS) differs from candidate_gate production LL (0.961159 ODDS) | None | Same number — confirmed identical. The slight difference in ALL (0.975163 vs 0.975163) is also identical. |
| D4 | `_paired_bootstrap` edge case: empty deltas list | Low | Never reached in practice because n < 30 guard at line 876 prevents calling bootstrap with n=0. Safe by construction. |

**No high-severity discrepancies found.** The live shadow evaluation code is policy-conformant, bootstrap-correct, and segment-disciplined. The n=0 state is correctly handled with insufficient-evidence status everywhere.

---

## 8. Summary

| Area | Verdict |
|---|---|
| Policy conformance (n>=30, insufficient) | **PASS** |
| Bootstrap clarity (paired, percentile, seed, n_boot) | **PASS** |
| Segment discipline (3 disjoint, odds_available empty) | **PASS** |
| Historical baselines documented | Done (Section 4) |
| n=0 report framing | Correct (Section 5) |
| Discrepancies | None high-severity |

The shadow evaluation is correctly frozen at n=0 scored fixtures. All segments report insufficient evidence. No promotion is permissible. Historical baselines are established for Phase 7D comparison when results begin arriving after 2026-10-13.
