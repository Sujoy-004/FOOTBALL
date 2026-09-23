# LaLiga Market-only Candidate — Phase 12 Hard Gate

Evidence: `market_only_deployment.json` (same seed 20260601, n_boot=2000, paired
resample-by-match bootstrap), `MARKET_ONLY_DEPLOYMENT.md`, `MARKET_ONLY_AUDIT.md`,
`PRODUCTION_SAFETY.md`. Historical population: 2019/20–2023/24, n=1900, 100% odds coverage.

Gate reuse note: the historical `gate_verdict` primitive requires `n_real_signals >= 2`.
A market-only candidate has exactly 1 real signal by construction, so that specific
criterion is deliberately NOT force-applied; the 12G conditions below supersede it and
are stated on their own evidence.

## Conditions (12G)

### 1. Market-only vs production on odds-present matches — PASS
Pooled n=1900, delta-LL (production − market_only) = **+0.0295, 95% CI [0.0185, 0.0409]**
— strictly positive, CI excludes zero. market_only LL 0.9758 vs production 1.0054.
Direction holds in every season. The candidate is meaningfully and significantly better
on the fully odds-covered population.

### 2. No unacceptable degradation on odds-absent matches — FAIL (no evidence; degradation is fundamental)
- Historical odds-absent population: **n=0** (100% coverage). No synthetic population is
  fabricated — the phase limitation is explicit.
- Genuine odds-absent deployment population = live 2026/27: 69/69 completed matches
  have NO odds. Behavior evidence: market_only emits exact (1/3,1/3,1/3) on all 69
  (`distinct_outputs=1`, `all_uniform=True`); production continues to blend four
  non-market signals (example output 0.4745/0.3078/0.2176) with market pinned to uniform.
- Conclusion: on odds-absent matches the candidate is indistinguishable from the uniform
  baseline — a complete, not partial, degradation. This is not "no unacceptable
  degradation"; it is total degradation. The candidate cannot carry the live deployment
  while live odds are absent.

### 3. All-match deployment population — FAIL (deployment reality)
Historical all-match population (1900) is odds-covered, where the candidate wins. But the
actual deployment population — live LaLiga 2026/27 (69 scored, 311 scheduled) — is **100%**
odds-absent because `fetch_live_data()` persists no odds fields (`pipeline.py:431-450`).
On the deployment population market_only == uniform. Historical superiority does not
transfer to the real deployment population today.

### 4. Uniform/frequency baseline comparisons — PASS
market_only beats uniform (0.9758 < 1.0986) and freq (0.9758 < 1.0791); paired CI vs
uniform entirely negative. Also beats elo_only (0.9758 vs 1.0924). ECE 0.029 vs uniform
0.112 vs freq 0.027.

### 5. Calibration — PASS
market_only pooled ECE **0.0290**, 95% CI [0.021, 0.054] (from Phase-11 bootstrap_cis.json)
— meets the "good" bar (~0.05) and far inside "acceptable" (0.10). No evidence of
systematic over/under-confidence on odds-covered data (mean_confidence 0.511 vs accuracy
0.533 on 1900). Failure-mode audit confirms uniform fallback, no fabricated odds, and
determinism; only caveat is an `inf`-odds edge that produces valid remove_vig output
(no NaN/crash; 0 occurrences in the dataset).

### 6. Cross-season stability — PASS
market_only better LL in all 5 seasons (deltas 0.032/0.030/0.025/0.018/0.043, all
positive). No single season dominates: largest = 2023/24 at 29% of the summed delta,
smallest = 2022/23 at 12%; seasons have equal n so pooled delta == seasonal mean. Per-season
CI excludes zero in 4/5; only 2022/23 straddles zero ([-0.007, 0.042]) — the smallest
effect, not a catastrophic reversal.

### 7. Strict temporal correctness — PASS
Audit (MARKET_ONLY_AUDIT.md): all candidate predictions route through prior-only
`build_context_for_match` with the season's own pre-match Elo snapshot; market_odds reads
only the match dict's own fields (identical output with or without context); frequency
baselines strictly-prior; candidate weights fixed at {market_odds: 1.0}, never fitted on
the evaluation season. Artifacts: all 10 checksums match PROVENANCE, offline regen is
byte-identical, 27/27 team keys clean (no mojibake). Determinism verified (fresh engines
→ identical output). ECE/LL conventions documented.

## Verdict

| Condition | Result |
|---|---|
| 1. Odds-present vs production | **PASS** (+0.0295, CI excludes 0) |
| 2. No degradation on odds-absent | **FAIL** (total degradation → uniform; no historical population) |
| 3. All-match deployment population | **FAIL** (live LaLiga ingests zero odds) |
| 4. Beats uniform / freq baselines | **PASS** |
| 5. Calibration | **PASS** (ECE 0.029) |
| 6. Cross-season stability | **PASS** (5/5 seasons, no dominance) |
| 7. Strict temporal correctness | **PASS** |

**HARD GATE: CONDITIONAL**

market_only is the best historically-evidenced model on the fully odds-covered population
(conditions 1, 4, 5, 6, 7 PASS) but is **not eligible for deployment to the live LaLiga
engine as-is**: live LaLiga currently ingests zero odds, so on the real deployment
population the candidate is exactly the uniform baseline (conditions 2 and 3 FAIL). It
remains **behind the `market_only` strategy flag** — selectable, overridable, and A/B-testable
for odds-covered evaluation — but it is NOT promoted as a live default.

**Eligible for a separate promotion phase? YES — but only for odds-covered deployment.**
Market-only qualifies for a promotion phase that is explicitly scoped to matches where live
odds are present; that phase first requires a pipeline change (`fetch_live_data()` must
persist provider odds fields), which is out of scope here. Until then the candidate stays
behind its flag, and condition 2 must be re-evaluated the moment an odds-absent-but-covered
historical or frozen-live population exists.