# PHASE 7B — INDEPENDENT METRIC RECOMPUTATION (RAW-DATA RECONSTRUCTION)

- **Season audited:** `2026/27` (path key `2026_27`)
- **Audit date:** 2026-09-11
- **Scope:** rebuild the scored set and metric table from RAW files only (not from `report.json`), verify the shadow `.report` path uses *literally the same* evaluation semantics as the historical framework (`historical_backfill/evaluate.py`, `src/gate.py`), and provide the matchday-accumulation skeleton for the next phase.
- **Disposition:** OBSERVATIONAL, READ-ONLY. No production/shadow file mutated. The existing `report` CLI was re-run to a temp output only (`.../Temp/opencode/p7b_report.json`). Independent code lives in `C:\Users\KIIT0001\AppData\Local\Temp\opencode\p7b_recompute.py` (writes `p7b_summary.json` there).
- **Result:**
  - scored-set reconstruction verdict: **EMPTY — 0 scored predictions per strategy** (`0` final matches, `n_scored_fixtures = 0`), fully consistent with the raw data, no reliance on `report.json`.
  - semantic conformance verdict: **EQUIVALENT** — shadow report metrics are the same shared functions/logic as the historical framework (evidence with `file:line` in Section 3).
  - `n=0` metric table and future matchday-accumulation skeleton in Sections 4 and 5.
  - **No discrepancies** vs `report.json` (Section 6).

---

## 1. Independent recomputation method

Raw inputs read directly by the independent script (no `report.json` consumed anywhere in the recomputation):

| Input | Path | Records |
|---|---|---|
| Frozen predictions | `competitions/ucl/data/shadow/2026_27/predictions.jsonl` | 357 (119 fixtures x 3 strategies) |
| Attached results | `competitions/ucl/data/shadow/2026_27/results.jsonl` | 11 |
| Canonical results | `competitions/ucl/data/seasons/2026_27/results.json` | 11 |
| Fixtures (for matchday labelling only) | `competitions/ucl/data/seasons/2026_27/fixtures.json` | 144 |

Reconstruction logic (mirrors `shadow_eval.build_report` *membership* test, independently re-derived):

1. Parse every `predictions.jsonl` record; keep those with `season` == `2026/27`. → 357 records, 119 unique `match_id`, per-strategy 119/119/119.
2. Resolve a result for a `match_id` only when a row exists **in the shadow result log** with `status == "finished"`, both scores present, and the `outcome` literal agrees with `H/A/D` derived from the scores.
3. Cross-check the shadow result log against `results.json`: identical 11 `match_id`s and identical `(home_score, away_score, outcome)` — the two raw sources agree (`agree == True` in `p7b_summary.json`).
4. **Scored observation** = a frozen prediction whose `match_id` has a resolved result. Computed per strategy and per segment (`all` / `odds_available` / `odds_unavailable`).
5. Metric values are produced with the **same shared library** the shadow and historical paths both call (`football_core.evaluation`), never a re-invented metric (Section 3).

Verification of correctness of the empty set:
- `fixtures.json` official-matchday distribution: MD1..MD8 have **17 fixtures each**, plus 8 fixtures with `official_matchday: None`.
- The 11 attached results are **all `official_matchday == 1`** and kicked off **2026-09-08/09 — strictly before the freeze** (`2026-09-11T01:47:19.912141Z`). Frozen predictions cover kickoffs **2026-10-13T16:45Z .. 2027-01-27T20:00Z** (official matchdays 2..8). MD1 was therefore never predicted — the correct isolation state.

## 2. Scored-set reconstruction verdict

`overlap = frozen_ids ∩ result_ids = []` (0 match ids). Per-strategy scored records: `{}` (0 for `production`, `market_elo_equal`, `market_elo_prior`).

| Strategy | Frozen records | Scored (frozen result known) |
|---|---:|---:|
| `production` | 119 | **0** |
| `market_elo_equal` | 119 | **0** |
| `market_elo_prior` | 119 | **0** |

Segment-level scored counts (independent): `all` = 0, `odds_available` = 0, `odds_unavailable` = 0 — matching `report.json` segment `n` values (0, 0, 0) and every strategy row `{"n": 0, "status": "insufficient"}`. Cross-checked `report.json` `honesty`: `n_prediction_records=357`, `n_unique_fixtures_frozen=119`, `n_scored_fixtures=0`, `n_pending_fixtures=119`, `n_attached_results=11` — all identical to the independent counts.

**Verdict: EMPTY scored set (0 per strategy), reproduced independently from raw data. Correct-and-expected: the only known results predate the freeze.**

## 3. Semantic conformance — shadow `.report` vs historical evaluation

**Verdict: EQUIVALENT.** The metrics in the shadow `.report` path are the same functions/logic used by the historical framework. `file:line` evidence below. No metric was invented; every value funnels through `football_core.evaluation`.

### 3.1 Point metrics (log-loss, Brier, ECE) — identical functions

| Path | Import / call site | `file:line` |
|---|---|---|
| Shadow report | `_metrics` imports `multi_class_brier, multi_class_ece, multi_class_log_loss` from `football_core.evaluation` | `competitions/ucl/src/shadow_eval.py:766-770` |
| Shadow report | empty probs → `{"n": 0, "status": "insufficient"}` (guard before any metric computed) | `shadow_eval.py:772-773` |
| Shadow report | `{"log_loss": round(multi_class_log_loss(...),6), "brier": round(multi_class_brier(...),6), "ece": round(multi_class_ece(...),6)}` | `shadow_eval.py:774-779` |
| Historical backfill | `from football_core.evaluation import multi_class_brier, multi_class_ece, multi_class_log_loss` | `historical_backfill/evaluate.py:30` |
| Historical backfill | `metrics_from` — same three functions, rounds to 6 dp | `evaluate.py:120-133` |
| Historical backfill | documented `ece = football_core.evaluation.multi_class_ece (confidence-vs-accuracy ECE; the production implementation)` | `evaluate.py:217-218` |
| Gate | same imports | `src/gate.py:25-29` |
| Gate | `ens_ll / ens_brier / ens_ece` via the same three functions | `gate.py:238-240` |

- **Outcome label index is identical:** shadow `_OUTCOME_INDEX = {"H": 0, "D": 1, "A": 2}` (`shadow_eval.py:59`) ↔ historical `outcome_index`: `0 = home win, 1 = draw, 2 = away win` (`src/historical.py:34-44`). Prob vectors are both `[home, draw, away]` (`shadow_eval.py:833-835`).
- **Brier "1/3-scale" convention:** `football_core.multi_class_brier` = `Σ_k (p_k − y_k)² / (3·N)` (`football_core/evaluation.py:232-262`). Historical harness computes the same number via `pooled_metrics` `brier = mean/3` (`historical_backfill/market_elo_investigation.py:227`) and documents `"brier = football_core multi_class_brier convention (…, 1/3 scale)"` (`market_elo_investigation.py:297-298`; also `candidate_gate.py:51-53`). Same scale, same function.
- **Log-loss epsilon:** shadow `_match_ll` clips with `eps=1e-15` (`shadow_eval.py:782-784`), identical to `multi_class_log_loss` default `eps=1e-15` (`football_core/evaluation.py:199-229`) used by both harnesses.

### 3.2 Corrected ECE

`multi_class_ece` is the confidence-vs-accuracy ECE with adaptive binning (`football_core/evaluation.py:265-335`). The historical investigation re-implements the same adaptive binning for resampling (`market_elo_investigation.py:200-205`) and documents `ece = football_core.evaluation.multi_class_ece (production)` (`market_elo_investigation.py:296`; `candidate_gate.py:51-52`). Shadow calls the same production function directly. EQUIVALENT.

### 3.3 delta-LL and paired percentile bootstrap CIs

| Aspect | Shadow | Historical framework | Match |
|---|---|---|---|
| Resampler | `np.random.default_rng(seed=20260601)` | `np.random.default_rng(BOOT_SEED)` with `BOOT_SEED=20260601` | identical |
| Draw scheme | `rng.integers(0, n, size=(2000, n))` | `rng.integers(0, n, size=(N_BOOT, n))` with `N_BOOT=2000` | identical |
| CI aggregation | `np.percentile(means, 2.5 / 97.5)` | `np.percentile(..., 2.5 / 97.5)` | identical |
| Rounding | 6 dp | 6 dp | identical |
| Borrowing | `shadow_eval.py:787-800` (`_paired_bootstrap`) | `market_elo_investigation.py:72-73, 234-274` (`bootstrap_cis`); re-used by `candidate_gate.py:90-98, 250-258` | identical |
| Per-match delta | `Δ = ll(second) − ll(first)`, resample mean-of-deltas | `d = ll(a) − ll(b)` on same resample rows (mean-of-mean, linear => same) | identical up to pair ordering |

Because `mean over resample rows (Δ) = mean(ll_b, rows) − mean(ll_a, rows)`, the shadow's mean-of-per-match-delta is arithmetically the historical harness's resampled mean difference; the delta-LL sign is a pair-ordering convention and the verdict logic (`positive favours <first>`, lower log loss better, `shadow_eval.py:884-897`) is consistent with the historical `_delta_ll` semantics (`"positive favours <first>"`-style comparisons, `market_elo_investigation.py:253-274`). The framework documents `"95% percentile bootstrap, paired over identical resamples, n_boot=2000, seed=20260601"` (`market_elo_investigation.py:299-300`); shadow declares `n_boot=2000, seed=20260601` in report `meta` (`shadow_eval.py:61-62, 954-956`). **EQUIVALENT.**

Numeric spot-check (independent script): calling shadow `_metrics` on a synthetic scored set returns exactly `football_core` `multi_class_log_loss/brier/ece` (`n=3 → ll=0.459442, brier=0.071111, ece=0.366667` identical); `_metrics([],[])` → `{"n": 0, "status": "insufficient"}`.

### 3.4 Minor, non-metric differences (no semantic impact)

- Segment predicates differ *slightly* in the odds test: shadow `odds_available` requires usable odds per `_usable_odds` (each of the 3 keys numeric and >0 — `shadow_eval.py:462-467`); historical `has_odds` requires only `is not None` (`evaluate.py:189-190`). Irrelevant here: all 119 frozen fixtures are `odds_available=False` → the entire cohort is in `odds_unavailable`; nothing is computed in the empty set.
- Empty-set reporting shape: shadow emits `{"n": 0, "status": "insufficient"}`; historical `metrics_from` emits `{"n": 0}` and gate emits `None` metrics. Shape only — no metric is invented by either at `n=0`.

## 4. Metric table recomputed from raw data for n = 0

Legacy table structure for the current (empty) scored set. `LL / Brier / ECE / delta-LL / CI = NaN (None)`, `status = insufficient`, exactly as the shadow `.report` path and the independent recomputation agree:

### Segment: all (n=0)

| strategy | n | log_loss | brier | ece | delta-LL vs production | paired 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| production | 0 | NaN | NaN | NaN | — | — |
| market_elo_equal | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] |
| market_elo_prior | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] |

### Segment: odds_available (n=0)

| strategy | n | log_loss | brier | ece | delta-LL vs production | paired 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| production | 0 | NaN | NaN | NaN | — | — |
| market_elo_equal | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] |
| market_elo_prior | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] |

### Segment: odds_unavailable (n=0)

| strategy | n | log_loss | brier | ece | delta-LL vs production | paired 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| production | 0 | NaN | NaN | NaN | — | — |
| market_elo_equal | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] |
| market_elo_prior | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] |

Paired comparisons (all three pairs): `n=0`, `verdict = insufficient_evidence (n=0)`; no bootstrap can run (and the report path requires `n >= 30` before it does, `shadow_eval.py:876-878`).

**Report-command confirmation:** re-ran `python -m competitions.ucl.src.shadow_eval report --season 2026/27 --out <Temp/opencode>/p7b_report.json` (temp out; production files untouched beyond the standard deterministic regeneration). Output is **deep-equal to the stored `report.json`** (segments 0/0/0, comparisons `insufficient_evidence (n=0)`, `honesty` 357/119/0/119/11, `meta.bootstrap = {n_boot: 2000, seed: 20260601}`). The recomputed table above and the report command agree on every field.

## 5. Future matchday / cumulative accumulation skeleton

The report path already supports grouping by `official_matchday` and cumulative accumulation: `breakdowns["by_matchday"]` groups scored records via `rec.get("official_matchday")` (`shadow_eval.py:901-923`), and `segments["all"]` + comparisons accumulate automatically as `attach_results` appends rows to `results.jsonl` (idempotent per `match_id`, `shadow_eval.py:683-757`). Per-matchday stats only materialise per strategy when a matchday's scored count reaches **n >= 10** (`shadow_eval.py:915-921`); below that the group is reported `status: insufficient`.

Frozen-fixture matchday distribution (119 unique fixtures, production records — identical per strategy):

| official_matchday | # frozen fixtures | odds_available | kickoff window |
|---|---:|---:|---|
| 2 | **17** | 0 | from 2026-10-13T16:45Z |
| 3 | **17** | 0 | — |
| 4 | **17** | 0 | — |
| 5 | **17** | 0 | — |
| 6 | **17** | 0 | — |
| 7 | **17** | 0 | — |
| 8 | **17** | 0 | to 2027-01-27T20:00Z |
| Total | **119** | 0 | — |

- **First scorable matchday: MD2** (min frozen kickoff 2026-10-13). As MD2 results land in `results.json`, `segments["all"]`/`odds_unavailable` and the paired comparisons become non-trivial after the first finished fixture; the `by_matchday` breakdown turns on for MD2 at its **10th** scored fixture.
- The 11 already-attached results are all **official_matchday 1** (pre-freeze; not frozen, unscoreable) — MD1 contributes nothing.
- 8 fixtures in `fixtures.json` carry `official_matchday: None` (provisional; not frozen, not part of the accumulation plan).
- `simulation_matchday` is also present on records (`simulation_matchday → {1:17, 2:14, 3:14, 4:14, 5:18, 6:13, 7:13, 8:16}`) but `breakdowns` derive from `official_matchday`.

**Accumulation plan for the next phase:** freeze footprint = MD2..MD8 × 17 fixtures × 3 strategies; score-once-repeat per `match_id`; cumulative `segments["all"]` + 3 paired delta-LL CIs (seed 20260601, n_boot=2000); per-MD gates at n>=10/strategy.

## 6. Discrepancies detected

None (severity: none).

- Independent recomputation and `report.json` are identical on every comparable field (segment n, strategy rows, comparisons, honesty). The `report` CLI re-run is deterministic and byte/deep-identical to the stored report.
- Single presentational note (not a discrepancy): at `n=0` the report command *omits* `mean_delta_ll` / `ci95` keys in comparison entries (they are only emitted when the `n>=30` bootstrap branch runs, `shadow_eval.py:872-898`); the Phase-7B table renders them as `NaN/None` for readability. The stored `report.json` is authoritative and is unchanged.

## 7. Conclusion

Independently reconstructed from raw data, the 2026/27 shadow scored set is empty (0 per strategy, 0 scored fixtures), the shadow `.report` evaluation semantics are EQUIVALENT to the historical framework (same `football_core.evaluation` functions; same label index; same paired-bootstrap config `n_boot=2000, seed=20260601`; same Brier 1/3 scale; same delta-LL convention), and the `n=0` metric table matches the report command exactly. Accumulation will start with **MD2 (17 frozen fixtures)**, with per-matchday metrics turning on at its 10th scored fixture. No discrepancies found; no further action required for Phase 7B.