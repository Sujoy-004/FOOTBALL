# PHASE 8C — Statistical / Gate Review + Historical-vs-Live Consistency

**Reviewer**: Agent 8C (read-only; no tuning, no promotion, no commit)
**Date**: 2026-09-11 (UTC)
**Scope**: Evidence-threshold state, Phase-8G stop condition, Phase-8E historical-vs-live expectation baseline, and confirmation that no evaluation-sample-size / bootstrap code changed this phase.
**Data as inspected**: `competitions/ucl/data/shadow/2026_27/` (predictions/report/results/schema), `competitions/ucl/src/shadow_eval.py`, `competitions/ucl/src/historical.py`, `competitions/ucl/src/gate.py`, `competitions/ucl/data/historical/evaluation/{eval_results,market_elo_results,candidate_gate_results}.json`.

---

## 1. Evidence-Threshold State (re-verified by code read, not reused claims)

### 1.1 Policy code (current working copy, confirmed identical to Phase-7C claims)

| Rule | Location | Verified |
|---|---|---|
| Empty probs → `{"n": 0, "status": "insufficient"}` | `shadow_eval.py:772-773` | PASS |
| Missing strategy pair / no common matches → `verdict: "insufficient_evidence (n=0)"` | `shadow_eval.py:872` | PASS |
| `n < 30` → `verdict: "insufficient_evidence (n=N)"` | `shadow_eval.py:876-877` | PASS |
| `n >= 30` → paired bootstrap, CI-exclusion verdict (`preferred`/`no_decision`) | `shadow_eval.py:879-898` | PASS |
| Paired percentile bootstrap, `BOOT_SEED = 20260601`, `N_BOOT = 2000` | `shadow_eval.py:61,62,787-800` | PASS |
| Historical gate `min_oos = 30` default, `n_oos < min_oos` → UNVERIFIED | `historical.py:316-324,338-341` | PASS |

### 1.2 Live data as of 2026-09-11

| Measure | Value | Source |
|---|---|---|
| Prediction records | 357 (119 fixtures × 3 strategies) | `predictions.jsonl` (357 lines) |
| Production fixture records | 119 | probe count |
| Fixtures with `odds_available: true` | **0** | probe (`odds_true=0`, `odds_false=357`) |
| Unique frozen fixture ids | 119 | probe |
| Frozen-by-matchday (all `odds_unavailable`) | MD2–MD8 × 17 = 119 | probe |
| Result rows in `results.jsonl` | 11, all `status: "finished"` but **synthetic `gen-*` ids** | probe |
| Overlap result↔frozen match_ids | **0** | probe |
| Scored fixtures (n) | **0 in every segment** | `report.json` segments all `"n": 0`; overlaps |
| Pending fixtures | 119 | `report.json:honesty`; probe (all kickoffs ≥ 2026-10-13, earliest 2026-10-13T16:45:00Z) |
| Report comparison verdicts | `"insufficient_evidence (n=0)"` for all three pairs × all segments | `report.json:74-87` |

`build_report` can only score a match when its `match_id` is present in **both** the prediction sample and the result map (`shadow_eval.py:848-854,860-866,874`); the 11 synthetic `gen-*` results therefore cannot contribute to any metric. `report.json:honesty` is internally consistent: `n_prediction_records=357`, `n_unique_fixtures_frozen=119`, `n_scored_fixtures=0`, `n_pending_fixtures=119`, `n_attached_results=11`.

### 1.3 Verdicts

- **(a) No segment has n ≥ 30** — all segments report n = 0. Confirmed from data (`report.json`) and from code (n is the size of the scored common/segment match set).
- **(b) No formal review, no CI computation, no promotion eligibility.** All three report comparisons are at n=0 and are short-circuited at `shadow_eval.py:872` before the bootstrap is ever reached. The `"preferred"` path (`shadow_eval.py:885-890`) is unreachable until n ≥ 30.
- **(c) Required wording (exact)**, already present inch-perfect in `report.json:74-87` and `SHADOW_EVALUATION.md:38-40`:
  - `all` → **insufficient_evidence (n=0)**
  - `odds_available` → **insufficient_evidence (n=0)**
  - `odds_unavailable` → **insufficient_evidence (n=0)**

---

## 2. Stop-Condition Evaluation (Phase 8G)

Phase-8G stops the accumulation only when **A** (a segment first reaches n ≥ 30) or **B** (a data/integrity blocker that makes further accumulation meaningless) is met.

**Neither is met today (2026-09-11).**

| Condition | State | Verdict |
|---|---|---|
| A — first segment reaches n ≥ 30 | All segments n = 0; first scorable fixtures kick off 2026-10-13 (MD2) | NOT met |
| B — data/integrity blocker | 119 frozen fixtures intact; results ingestion healthy (0 overlap of the 11 synthetic rows with frozen ids); all kickoffs future | NOT met |

**Recommendation: continue accumulation.** Do not run formal review, do not compute CI, do not promote, do not tune.

### Eligibility arithmetic (forward-looking)

| Milestone | Scorable this MD | Cumulative `n_unavailable` | n ≥ 30? | Verdict |
|---|---|---|---|---|
| After MD2 (2026-10-13) | +17 | 17 | No | Still `insufficient_evidence (n=17)` |
| After MD3 (+17) | +17 | 34 | Yes | `odds_unavailable` segment becomes **ELIGIBLE for formal review** — *if all 34 fixtures play and are scored* |

- `odds_available` remains **empty by construction**: 0 of 119 frozen fixtures have `odds_available=true` (`predictions.jsonl`), so that segment contributes n=0 forever until a match is frozen with usable pre-match odds and later scored. Its verdict will stay `insufficient_evidence (n=0)`.
- At n=34, `build_report` will run the paired bootstrap for the three comparisons on the `all`/`odds_unavailable` common sets (`shadow_eval.py:876-884`); the historical gate additionally demands n_oos ≥ 30 (`historical.py:338`), which is satisfied.
- The dual-segment requirement (7C discrepancy D1) only becomes actionable at n ≥ 30; `odds_available` will provide no support this season on current data.

---

## 3. Historical-vs-Live Consistency Checklist (Phase 8E) — to execute once n ≥ 34

Performing **no** live evaluation today (zero scored fixtures). What follows is a fixed list of checks + expected signs + quoted historical baselines. Framework: each check is an **expectation to test**, not a tuning action.

Historical baselines quoted from:
- `market_elo_results.json` pooled ODDS (n=469): `market_only` LL **0.893925**, `me_equal` LL **0.923804**, `prod_ensemble` LL **0.961159**.
- `candidate_gate_results.json` pooled ODDS (n=469): production 0.961159 / market_only 0.893925 / me_equal 0.923804; pooled ALL (n=619) production 0.975163; pooled NOODS (n=150) production **1.018948** vs me_equal **1.035758**. ODDS delta-LL production−me_equal **+0.036977, CI [0.013525, 0.059045]** (strictly positive, G3). ALL delta-LL +0.02476, CI [−0.011024, 0.056559] (straddles 0, G2). NOODS delta-LL **−0.016968, CI [−0.122535, 0.084081]**.
- `eval_results.json` overall ALL (n=619) production ECE **0.063522**; overall ODDS production ECE 0.076132, market_only ECE 0.066142; `candidate_gate_results.json` NOODS production ECE 0.073044, me_equal ECE 0.139262 (Elo-only overconfidence), ODDS me_equal ECE 0.055613.
- `market_elo_results.json` learned-weights stability: per-signal min–max spreads ≤ 0.0263 (market_odds 0.248875–0.275126), window-to-window shifts small (e.g. 2023_24: ~≤0.003), so production-equivalent learned weights are expected to stay close to the frozen `signal_weights.json` / `market_elo_prior_weights.json`.

### Check list (5)

| # | Check (live vs historical) | Expected sign / value | Historical baseline (quoted) |
|---|---|---|---|
| **E1** | **Odds-present advantage.** On `odds_available` (future), `market_elo_equal` LL should beat production; delta_ll = production − me_equal should be **positive**, CI excluding 0 is plausible at n≈470 but at n=34 expect a wide CI that may straddle 0 — treat as directional, not decisive. | `LL(me_equal) < LL(production) < LL(market_only)`; market_only remains best single model. | ODDS n=469: market_only 0.893925 vs me_equal 0.923804 vs production 0.961159 (`market_elo_results.json:405-435`); delta +0.036977, CI [0.013525, 0.059045] (`candidate_gate_results.json:1188-1192`). |
| **E2** | **No-odds fallback behaviour.** On `odds_unavailable` (this season's actual data), candidates must return the refined-Elo probabilities unmodified (identical across me_equal/me_prior_fixed/elo_only by construction); production should be marginally better or statistically equivalent. Expected delta_ll = production − me_equal **negative or ~0**. | `LL(production) ≤ LL(me_equal)` (delta ≤ 0), CI straddles 0; also verify the three Elo-degenerate strategies produce *identical* metrics. | NOODS n=150: production 1.018948 vs me_equal 1.035758; delta −0.016968, CI [−0.122535, +0.084081] (`candidate_gate_results.json:1246-1260,1366-1368`). |
| **E3** | **Equal-vs-prior stability.** `market_elo_equal` vs `market_elo_prior` LL should be practically identical (difference a few mils) on any segment, with CI near 0. Any material live divergence flags a prior-weights / fallback bug. | delta_ll(me_equal − me_prior_fixed) between −0.005 and +0.005 at historical scale. | ODDS: me_equal 0.923804 vs me_prior_fixed 0.919407 (d=0.0044); ALL: 0.950933 vs 0.947601 (d=0.0033); ODDS-valid me_prior−me_equal −0.003961, CI [−0.006299, −0.001638] (`candidate_gate_results.json:1031-1044,1221-1225`). Weight stability `market_elo_results.json:weights_learned.stability`. |
| **E4** | **ECE plausibility.** Production (adaptively-binned `multi_class_ece`) should land ~0.06–0.08 on scored live matches; me_equal ECE should be **low on odds_available** (~0.05–0.06) but **elevated on odds_unavailable** (~0.12–0.14) because the candidate degrades to overconfident Elo-only on no-odds matches. Big deviations → suspect ECE path or score attachment first. | production ECE ∈ [0.05, 0.08]; me_equal ECE lower on odds_available than on odds_unavailable. | `eval_results.json` overall ALL production ECE 0.063522; ODDS 0.076132 (me_equal ODDS 0.055613); `candidate_gate_results.json` NOODS production 0.073044, me_equal 0.139262. |
| **E5** | **Divergence directive — provenance before model.** If any of E1–E4 deviates beyond expectation, first suspect **provenance / data-integrity** failure (odds snapshot at freeze, elapsed-scoring binding, kickoff/season scoping, fixture identity, wrong weights_hash), and audit the pipeline — **not** a model/weight change. No live tuning is permitted from a single-season n=34–469 point estimate. | Deviation ⟹ data audit first; model blame only after provenance cleared. | Baseline principle established by the leak-free historical harness (no future-data leakage, prior-only contexts, pre-match Elo snapshots) — `candidate_gate_results.json:meta.method`. |

**None of E1–E5 have been computed today** (n=0 everywhere). They are registered as the mandated checks for the first formal review at n ≥ 34 (and re-run at the full odds population if it ever materialises).

---

## 4. No Code-Changed Confirmation (evaluation-sample-size / bootstrap)

`git status` — tracked files modified in the working copy this phase:

| File | Diff summary | Touches sample-size / bootstrap? |
|---|---|---|
| `competitions/ucl/src/orchestrator.py` | `_ReplayResultProvider` date/chronology resolution refactor (RollingFormSignal replay) | No |
| `competitions/ucl/tests/test_replay_provider.py` | tests for the provider refactor | No |
| `football_core/evaluation.py` | single line, `multi_class_ece` bin accuracy: `acc = sum(1 for ok in bin_correct)` → `acc = sum(bin_correct)` (numerically identical; bools sum as ints) | No (ECE cosmetic/correctness clarity; not count/bootstrap) |
| `football_core/tests/test_evaluation.py` | +3 ECE correctness tests | No |

- `git diff HEAD -- competitions/ucl/src/gate.py competitions/ucl/src/historical.py competitions/ucl/src/shadow_eval.py` → **empty** (no changes to gate/historical; shadow_eval untracked).
- Full-diff grep for `boot|bootstrap|min_oos|insufficient|n_boot|BOOT_SEED|resample|gate|threshold` over the changed files → **no matches** (only CRLF warnings).
- `shadow_eval.py`, `ensemble.py`, `historical_backfill/*` are **untracked** (never committed; no git baseline exists for a literal diff). Content re-verified by read: `_metrics`/comparison guard behaviour at `shadow_eval.py:772-773,872,876-877` matches Phase-7C's documented line numbers exactly, and the bootstrap constants are unchanged (`shadow_eval.py:61,62`).

**Conclusion: no evaluation-sample-size or bootstrap code changed this phase.** The single evaluation-adjacent working-copy edit (`football_core/evaluation.py:314`) is identity-equivalent for the reported metrics and could not affect this report (n=0).

---

## 5. No-Promotion Confirmation

- All three segments: n = 0 → `status: "insufficient"` (`_metrics` short-circuit, `shadow_eval.py:772-773`).
- All three comparisons: `insufficient_evidence (n=0)` (`shadow_eval.py:872`); bolding of the shared conclusion: **promotion is not permitted and nothing was promoted.** No CI was produced (bootstrap unreachable at n=0), so no `"preferred"` verdict exists anywhere in `report.json`.
- Next formal-review trigger: `odds_unavailable` reaching n ≥ 30 — currently projected at **MD3** (cumulative 34) assuming all frozen fixtures play and score; first candidate trigger after MD2 is n=17 (< 30, still insufficient).

---

## 6. Discrepancies / Notes (severity)

| # | Finding | Severity |
|---|---|---|
| D1 | `football_core/evaluation.py:314` (ECE bin-accuracy wording) changed this phase in the working copy. Functionally identity-equivalent (`sum(bool_list)` == count of True), cannot alter any n=0 report value; flagged only for the record because it sits in the metric path. | Low |
| D2 | 11 synthetic `gen-*` finished result rows coexist with the frozen fixture set in `results.jsonl`. No overlap with the 119 frozen ids (0), and `build_report` scores only on prediction∩result match overlap (`shadow_eval.py:851,861-866,874`), so cross-contamination is impossible in the current report. Provenance note: these rows must never acquire frozen match_ids. | Low |
| D3 | No automated dual-segment gate assertion (inherited from 7C D1): `odds_available` will remain n=0 all season, so the Phase-5 "both segments" requirement is moot for 2026/27 unless odds get frozen; enforcement point remains the future n ≥ 30 review. | Low |
| D4 | ECE baselines differ slightly across sources by design (eval_results ALL production 0.063522 adaptively-binned vs candidate_gate 0.063495 10-bin) — both quoted here and both ~0.0635; use the same `multi_class_ece` call as `_metrics()` (`shadow_eval.py:778`) when comparing live. | None |

---

## 7. Summary

| Area | Verdict |
|---|---|
| Threshold state ((a) n>=30, (b) no review/CI/promotion, (c) exact wording) | PASS — all segments n=0, wording `insufficient_evidence (n=0)` present in report |
| Stop condition (8G) | NEITHER A nor B met → **continue accumulation**; MD2=17 (<30 insufficient), MD3=34 (≥30 eligible if all play & score) |
| Historical-vs-live (8E) | 5 expectations registered (E1–E5), no computation at n=0; baselines quoted |
| No code changed (sample-size/bootstrap) | PASS — only orchestrator/test/ECE-binning-identical edits; gate/historical/shadow_eval untouched (verified diff + grep) |
| Promotion | None permitted, none made |