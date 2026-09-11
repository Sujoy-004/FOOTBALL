# PHASE 8B — INDEPENDENT METRIC RECOMPUTATION (RE-VERIFICATION)

- **Season audited:** `2026/27` (path key `2026_27`)
- **Audit date:** 2026-09-11 (UTC)
- **Role:** Agent 8B — INDEPENDENT METRIC RECOMPUTATION for Phase 8.
- **Scope:** independently re-derive the scored set from raw files, re-verify report determinism/conformance, rebuild the matchday-accumulation skeleton, and format the empty metric table for the phase report.
- **Disposition:** READ-ONLY on the repo. Only `competitions/ucl/data/shadow/2026_27/PHASE8B_RECOMPUTE.md` was written; temp scripts/output live in `C:\Users\KIIT0001\AppData\Local\Temp\opencode` (`p8b_recompute.py`, `p8b_compare.py`, `p8b_summary.json`, `p8b_report.json`). No prediction, result, or report file was created or modified. No commit made.
- **Result:**
  - scored-set reconstruction: **EMPTY — 0 scored predictions per strategy** (0/0/0; `n_scored_fixtures = 0`) — reconfirmed independently from raw data.
  - report determinism/conformance: **CONFORMS** — the re-run `report` CLI output is deep-equal to the stored `report.json`; segment `n=0` / `status=insufficient` for every strategy × segment; metric keys absent at `n=0` (rendered NaN); `mean_delta_ll`/`ci95` omitted at `n<30` per Phase-5 convention (evidence with `file:line` in Section 3).
  - accumulation skeleton + first-eligible arithmetic in Section 5.
  - **No discrepancies** (Section 6).

---

## 1. Independent recomputation method (raw files only)

Raw inputs read by the independent script `p8b_recompute.py` — `report.json` is consumed **only** as the object under cross-check, never as an input to the recomputation:

| Input | Path | Records |
|---|---|---|
| Frozen predictions | `competitions/ucl/data/shadow/2026_27/predictions.jsonl` | 357 (119 fixtures × 3 strategies) |
| Attached results | `competitions/ucl/data/shadow/2026_27/results.jsonl` | 11 |
| Canonical results | `competitions/ucl/data/seasons/2026_27/results.json` | 11 |
| Fixtures (matchday labelling) | `competitions/ucl/data/seasons/2026_27/fixtures.json` | 144 |
| Report (cross-check only) | `competitions/ucl/data/shadow/2026_27/report.json` | — |

Reconstruction logic (independently re-derived; mirrors `shadow_eval.build_report` membership semantics):

1. Keep prediction records with `season == "2026/27"` → 357 records, 119 unique `match_id`, per-strategy 119/119/119.
2. A result is "fully resolved" only when `results.jsonl` has a row with `status == "finished"`, **both scores present**, and an `outcome` literal in `{H,D,A}` that **equals** the outcome re-derived from `home_score/away_score` (never a fabricated 0-0, never an ambiguous row).
3. Cross-check resolved log against canonical `results.json`: identical 11 `match_id`s and identical `(home_score, away_score, outcome)` per row — both raw sources agree (`canonical_results_agree_ids == true`, `canonical_results_agree_rows == true`).
4. **Scored observation** = a frozen prediction whose `match_id` has a resolved result — counted per strategy and per segment (`all` / `odds_available` / `odds_unavailable`), where `odds_available` mirrors the frozen record's own flag (all 357 frozen records carry `odds_available: false`).
5. Metrics are only ever produced via the shared `football_core.evaluation` functions (same as the historical framework); no metric is invented.

## 2. Scored-set reconstruction verdict

`overlap = frozen_ids ∩ resolved_ids = [] (0 match ids)`. Per-strategy scored counts: 0/0/0.

| Strategy | Frozen records | Scored (frozen ∩ resolved) |
|---|---:|---:|
| `production` | 119 | **0** |
| `market_elo_equal` | 119 | **0** |
| `market_elo_prior` | 119 | **0** |

Segment-level scored counts (independent): `all` = 0, `odds_available` = 0, `odds_unavailable` = 0 — matching every `report.json` segment `n` and every strategy row `{"n": 0, "status": "insufficient"}`. `report.json` `honesty` (`357 / 119 / 0 / 119 / 11`) matches the independent counts field-for-field (`honesty_matches_independent == true`).

**Verdict: EMPTY scored set (0 per strategy). Correct and expected — all 11 known results are MD1 (`official_matchday == 1`), kicked off 2026-09-08/09, strictly before the freeze (`2026-09-11T01:47:19.912141Z`); the 119 frozen fixtures all kick off from 2026-10-13 onward and none has a result.**

## 3. Report determinism & conformance verdict

**Verdict: CONFORMS (deterministic and deep-identical).**

1. **Re-run to temp copy:** `python -m competitions.ucl.src.shadow_eval report --season 2026/27 --out C:\Users\KIIT0001\AppData\Local\Temp\opencode\p8b_report.json` (temp out; `SHADOW_EVALUATION.md` also went to the temp dir; no production file touched). `p8b_compare.py` deep-compares it against the stored `report.json`: **`deep_equal: True`, `keys_equal: True`, no differences.**
2. **Empty-table conformance:** the produced report has `n=0`, `status="insufficient"` for all 3 strategies in all 3 segments (`report.json:22-72`, temp copy identical). At `n=0`, `_metrics` returns `{"n": 0, "status": "insufficient"}` with **no `log_loss`/`brier`/`ece` keys** (`shadow_eval.py:772-773`) — so the phase report renders them as NaN, and the model/config + honesty blocks are preserved.
3. **`mean_delta_ll`/`ci95` omission at n<30 (Phase-5 convention):** confirmed by reading `shadow_eval.py`. Comparisons branch: `n < 30 → comparisons[key] = {"verdict": "insufficient_evidence (n=…)", "n": n}` and `continue` (`shadow_eval.py:876-878`) — no `mean_delta_ll`, no `ci95` are ever written on this path. The keys are emitted **only** in the `n >= 30` bootstrap branch (`shadow_eval.py:891-898`). `p8b_summary.json.comparison_key_presence` confirms the stored `report.json` has `has_mean_delta_ll: false`, `has_ci95: false` for all three pairs at `n=0`.
4. **Metric semantics:** point metrics call the identical shared functions used by the historical framework — `multi_class_brier`, `multi_class_ece`, `multi_class_log_loss` from `football_core.evaluation` (`shadow_eval.py:766-770`), paired percentile bootstrap `np.random.default_rng(20260601)`, `n_boot=2000` (`shadow_eval.py:61-62, 787-800`, mirrored in `report.json meta.bootstrap`). No metric divergence (fully established in PHASE7B_RECOMPUTE.md; unchanged in Phase 8).

## 4. Empty metric table (as it will appear in the phase report)

Compares `production`, `market_elo_equal`, `market_elo_prior` on `n`, `log_loss`, `brier`, `ece`, `delta_ll_vs_prod`, `ci95`, for all three segments. At `n=0` every value is NaN/not-applicable and every strategy row is tagged `insufficient_evidence (n=0)`; `delta_ll_vs_prod` / `ci95` only become non-NaN once the paired bootstrap runs (`n >= 30`).

### Segment: all (n=0)

| strategy | n | log_loss | brier | ece | delta_ll_vs_prod | ci95 | verdict |
|---|---:|---:|---:|---:|---:|---|---|
| production | 0 | NaN | NaN | NaN | — | — | insufficient_evidence (n=0) |
| market_elo_equal | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] | insufficient_evidence (n=0) |
| market_elo_prior | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] | insufficient_evidence (n=0) |

### Segment: odds_available (n=0)

| strategy | n | log_loss | brier | ece | delta_ll_vs_prod | ci95 | verdict |
|---|---:|---:|---:|---:|---:|---|---|
| production | 0 | NaN | NaN | NaN | — | — | insufficient_evidence (n=0) |
| market_elo_equal | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] | insufficient_evidence (n=0) |
| market_elo_prior | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] | insufficient_evidence (n=0) |

### Segment: odds_unavailable (n=0)

| strategy | n | log_loss | brier | ece | delta_ll_vs_prod | ci95 | verdict |
|---|---:|---:|---:|---:|---:|---|---|
| production | 0 | NaN | NaN | NaN | — | — | insufficient_evidence (n=0) |
| market_elo_equal | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] | insufficient_evidence (n=0) |
| market_elo_prior | 0 | NaN | NaN | NaN | NaN | [NaN, NaN] | insufficient_evidence (n=0) |

Paired comparisons (all three pairs): `n=0`, `verdict = insufficient_evidence (n=0)`, and `mean_delta_ll`/`ci95` keys are omitted by the report path itself (`shadow_eval.py:876-878`); the table renders them as NaN. Because all 357 frozen records are `odds_available: false`, `odds_unavailable` subsumes the whole cohort — it is the segment on which bootstrap eligibility is tracked (Section 5).

## 5. Matchday accumulation skeleton (119 frozen match_ids)

Per official_matchday, from `fixtures.json` restricted to the 119 frozen `match_id`s (independent count; identical per strategy):

| official_matchday | frozen fixtures | odds_available | kickoff window | cumulative (if all scored) |
|---|---:|---:|---|---:|
| 1 | 0 (pre-freeze; all 11 attached results are MD1) | — | 2026-09-08/09 | 0 |
| 2 | **17** | 0 | 2026-10-13T16:45Z → 2026-10-14T19:00Z | 17 |
| 3 | **17** | 0 | — | **34** |
| 4 | **17** | 0 | — | 51 |
| 5 | **17** | 0 | — | 68 |
| 6 | **17** | 0 | — | 85 |
| 7 | **17** | 0 | — | 102 |
| 8 | **17** | 0 | 2027-01-27T20:00Z | 119 |
| None | 0 frozen (8 provisional fixtures in the store, not frozen) | — | — | 119 |
| **Total** | **119** | 0 | — | 119 |

- **First scorable matchday: MD2** (min frozen kickoff 2026-10-13T16:45Z). After the first finished MD2 fixture the `segments`/comparisons turn non-trivial in `odds_unavailable` (the whole cohort); the `by_matchday` breakdown turns on for a matchday at its 10th scored fixture (`shadow_eval.py:915-921`).
- **Minimum matchdays to first reach n>=30 in `odds_unavailable` (arithmetic; not a promise):**
  - per scored matchday, upper bound = 17 scored fixtures (all MD fixtures scored),
  - `ceil(30 / 17) = ceil(1.7647…) = 2` matchdays,
  - cumulative after MD2 = 17 (below 30); cumulative after MD3 = 17 + 17 = **34 ≥ 30**,
  - ⇒ first eligibility at the **2nd scorable matchday**, i.e. **once MD3 has fully completed** — *if and only if* all 17 fixtures per matchday are scored. Any postponed/abandoned MD2 fixture delays it, and cross-checking `odds_available` fixtures (currently 0) is a non-issue.
- Bootstrap/CI mechanics only become live at that threshold (paired `n>=30` branch, `shadow_eval.py:876-898`, seed `20260601`, `n_boot=2000`).

## 6. Discrepancies

**None (severity: none).**

- Independent recomputation and both the stored and freshly re-run `report.json` agree on every comparable field (per-strategy scored 0/0/0, segment n 0/0/0, `honesty` 357/119/0/119/11); the stored report is byte/deep-identical to the temp re-run.
- `simulation_matchday` is present on records (`simulation_matchday → {1:17, 2:14, 3:14, 4:14, 5:18, 6:13, 7:13, 8:16}`) but report `breakdowns` use `official_matchday`; the accumulation skeleton is keyed on `official_matchday` accordingly. Minor, non-discrepancy note: not frozen (MD1/None) fixtures never join the scored set, so the 11 attached MD1 results remain permanently unscoreable — the correctness isolation the freeze design intends.

## 7. Conclusion

Independently reconfirmed from raw files: the 2026/27 shadow scored set is empty (0 scored predictions per strategy, 0 scored fixtures; segment n 0/0/0), the `report` command is deterministic (temp re-run deep-equal to stored `report.json`), the empty table renders NaN/insufficient with `mean_delta_ll`/`ci95` omitted at n<30 exactly per Phase-5 convention, and accumulation will begin at **MD2 (17 frozen fixtures, kickoff 2026-10-13)**, with bootstrap eligibility in `odds_unavailable` first reached after **2 scorable matchdays (after MD3 completes, cumulative 34 ≥ 30 — assuming all 17/MD are scored).** No discrepancies.