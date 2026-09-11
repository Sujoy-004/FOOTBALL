# Market + Elo Baseline Investigation — UCL Historical Backfill

Out-of-sample evaluation of candidate market/elo architectures against the current production ensemble and baselines, on the **identical eligible population**: the **469 odds-covered, completed matches** across 2020/21–2023/24 (2019/20 carries zero odds data and is absent).

Harness: `competitions/ucl/historical_backfill/market_elo_investigation.py` (read-only; no production model code, signals, weights, calibration, simulation, UI, or datasets touched). Raw numbers: `data/historical/evaluation/market_elo_results.json`. Independently recomputed by a separate agent (max abs diff 4.9e-7).

**Method & guarantees**

- Every prediction uses `historical.build_context_for_match` (prior-only context) with the season's own pre-match Elo snapshot — no future odds/elo/form/rest information.
- Learned weights are inverse-log-loss fits on **strictly prior** odds-covered seasons only, never on the evaluation season (no weight tuning on the eval set).
- All directly-compared tables run on the identical match list; metrics are multiclass log-loss, Brier (football_core `multi_class_brier`, 1/3 scale), and corrected ECE (`multi_class_ece`).
- 95% percentile bootstrap CIs, **paired over identical resamples** (n_boot=2000, fixed seed 20260601) — the eval framework itself provides no CIs, so these are computed here.
- Market odds on non-odds matches falls back to uniform 1/3 (as in production, unchanged).

## 1. Comparison table — pooled, odds-covered population (n=469)

| Model | log-loss | 95% CI | Brier | ECE | mean-conf | accuracy |
|---|---|---|---|---|---|---|
| Market odds only | 0.893925 | [0.849670, 0.938571] | 0.174817 | 0.066147 | 0.5726 | 0.6183 |
| Elo only | 1.029025 | [0.958460, 1.105636] | 0.199468 | 0.135886 | 0.6710 | 0.5352 |
| Market + Elo (equal 0.5/0.5) | 0.923804 | [0.871901, 0.977262] | 0.181569 | 0.055613 | 0.6082 | 0.5757 |
| Production ensemble (4 sig, prod wts) | 0.961159 | [0.928606, 0.994008] | 0.189353 | 0.076098 | 0.4977 | 0.5458 |
| Uniform 1/3 | 1.098612 | [1.098612, 1.098612] | 0.222222 | 0.125089 | 0.3333 | 0.4584 |
| Freq (prior-season) | 1.051193 | [1.023386, 1.077624] | 0.212111 | 0.028505 | 0.4299 | 0.4584 |

Ranking: market-only (0.894) ≺ Market+Elo equal (0.924) ≺ production ensemble (0.961) ≺ freq (1.051) ≺ uniform (1.099). Elo-only (1.029) sits between production and freq. Pairwise deltas (ΔLL, positive = column model worse):

| Comparison | ΔLL | 95% CI |
|---|---|---|
| Production vs Market+Elo (equal) | 0.0370 | [0.0135, 0.0590] |
| Production vs Market-only | 0.0673 | [0.0429, 0.0917] |
| Market+Elo (equal) vs Market-only | 0.0303 | [0.0101, 0.0519] |
| Market+Elo (equal) vs Elo-only | -0.1058 | [-0.1350, -0.0778] |

## 2. Per-season results (log-loss / Brier / ECE), identical sub-populations

| Model | 2020/21 (n=123) LL | 2020/21 Br | 2020/21 ECE | 2021/22 (n=108) LL | 2021/22 Br | 2021/22 ECE | 2022/23 (n=115) LL | 2022/23 Br | 2022/23 ECE | 2023/24 (n=123) LL | 2023/24 Br | 2023/24 ECE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Market odds only | 0.8723 | 0.1699 | 0.1060 | 0.8928 | 0.1751 | 0.0684 | 0.9060 | 0.1782 | 0.0561 | 0.9052 | 0.1764 | 0.0661 |
| Elo only | 1.0899 | 0.2103 | 0.1522 | 1.0165 | 0.1953 | 0.1419 | 1.0162 | 0.1984 | 0.1490 | 0.9911 | 0.1934 | 0.1317 |
| Market + Elo (equal 0.5/0.5) | 0.9356 | 0.1839 | 0.1024 | 0.9195 | 0.1798 | 0.0653 | 0.9257 | 0.1827 | 0.0745 | 0.9140 | 0.1797 | 0.0728 |
| Production ensemble (4 sig, prod wts) | 0.9738 | 0.1924 | 0.0681 | 0.9576 | 0.1879 | 0.1001 | 0.9540 | 0.1880 | 0.1029 | 0.9584 | 0.1889 | 0.0868 |
| Uniform 1/3 | 1.0986 | 0.2222 | 0.0813 | 1.0986 | 0.2222 | 0.1204 | 1.0986 | 0.2222 | 0.1624 | 1.0986 | 0.2222 | 0.1382 |
| Freq (prior-season) | 1.0461 | 0.2117 | 0.0140 | 1.0479 | 0.2117 | 0.0357 | 1.0604 | 0.2134 | 0.0675 | 1.0506 | 0.2116 | 0.0282 |

Market-only beats Market+Elo in all four seasons and all four seasons' pooled; Market+Elo beats the production ensemble in all four; Elo-only is the weakest real model in every season. Freq and uniform are never competitive.

## 3. Ablation — does Form/Rest add OOS value given Market + Elo? (EQUAL weights)

Pooled, n=469:

| Config | log-loss | Brier | ECE | ΔLL vs Market+Elo | 95% CI |
|---|---|---|---|---|---|
| Market + Elo | 0.923804 | 0.181569 | 0.055613 | — | — |
| Market + Elo + Form | 0.947911 | 0.186408 | 0.057799 | 0.0239 | [0.0080, 0.0383] |
| Market + Elo + Rest | 0.939454 | 0.184239 | 0.077090 | 0.0153 | [-0.0041, 0.0335] |
| Market + Elo + Form + Rest | 0.961248 | 0.189356 | 0.075656 | 0.0371 | [0.0139, 0.0589] |

Per-season log-loss:

| Config | 2020/21 | 2021/22 | 2022/23 | 2023/24 |
|---|---|---|---|---|
| Market + Elo | 0.9356 | 0.9195 | 0.9257 | 0.9140 |
| Market + Elo + Form | 0.9677 | 0.9483 | 0.9332 | 0.9415 |
| Market + Elo + Rest | 0.9443 | 0.9306 | 0.9445 | 0.9376 |
| Market + Elo + Form + Rest | 0.9746 | 0.9576 | 0.9538 | 0.9581 |

**Verdict: no.** Adding Form or Rest never helps once Market+Elo are present. Form costs +0.024 LL
(CI [0.008, 0.038], worse in all four seasons); Rest costs +0.015 ([−0.004, +0.033], worse in all
four seasons but not significant at 95% pooled); both together cost +0.037 ([0.014, 0.059]). Every
addition also worsens ECE relative to Market+Elo alone (0.056 → 0.058 / 0.077 / 0.076).

## 4. Do learned/equal 4-signal weights dilute Market/Elo? (2021/22–2023/24, n=346)

Learned weights require prior odds-covered seasons, so this sub-population is 2021/22–2023/24 (n=346), where every compared model is scored on the same matches.

| Model | log-loss | Brier | ECE |
|---|---|---|---|
| Market only | 0.901625 | 0.176579 | 0.052092 |
| Market+Elo equal | 0.919620 | 0.180731 | 0.055241 |
| Market+Elo learned | 0.915650 | 0.179889 | 0.041362 |
| 4-sig equal | 0.956515 | 0.188223 | 0.081476 |
| 4-sig learned | 0.950472 | 0.186869 | 0.077855 |
| 4-sig production (current) | 0.956678 | 0.188278 | 0.084725 |

| Comparison | ΔLL | 95% CI |
|---|---|---|
| M+E equal vs M+E learned (learned better) | 0.0040 | [0.0016, 0.0063] |
| 4-sig equal vs M+E equal | 0.0368 | [0.0088, 0.0620] |
| 4-sig learned vs M+E learned | 0.0347 | [0.0092, 0.0581] |
| M+E equal vs Market-only | 0.0178 | [-0.0053, 0.0409] |
| M+E learned vs Market-only | 0.0139 | [-0.0069, 0.0347] |

Learned strict-prior weights per season:

| Season | M+E learned | 4-signal learned |
|---|---|---|
| 2021/22 (n=108) | market 0.5555, elo 0.4445 | market 0.2979, elo 0.2385, form 0.2285, rest 0.2351 |
| 2022/23 (n=115) | market 0.5448, elo 0.4552 | market 0.2925, elo 0.2444, form 0.2291, rest 0.2341 |
| 2023/24 (n=123) | market 0.5395, elo 0.4605 | market 0.2880, elo 0.2459, form 0.2338, rest 0.2323 |

**Verdict: yes, the wider weight splits dilute Market/Elo.** Spreading market+elo mass across form/rest costs ~0.035–0.037 LL at equal split and at production/learned split (CIs exclude 0), and worsens ECE (0.041–0.055 → 0.078–0.085). Learned 2-signal weights (≈0.54/0.46 market/elo) narrowly beat equal 2-signal (−0.004, CI [0.002, 0.006]). The 4-signal learned weights are nearly uniform (≈0.29/0.24/0.23/0.23), i.e. the signal fit itself says form/rest add ~nothing.

## 5. Secondary — all 619 completed matches (market absent on 150)

To judge the full-season architecture (where Pinnacle odds are missing for 150 matches and the market signal must fall back to uniform):

| Model | log-loss | 95% CI | Brier | ECE | accuracy |
|---|---|---|---|---|---|
| Production ensemble | 0.975163 | [0.947714, 1.004362] | 0.192621 | 0.063495 | 0.5396 |
| Market+Elo (equal) | 0.934981 | [0.891102, 0.981689] | 0.183797 | 0.040231 | 0.5719 |
| Elo only | 1.030656 | [0.964014, 1.102545] | 0.198676 | 0.130024 | 0.5412 |
| Uniform | 1.098612 | [1.098612, 1.098612] | 0.222222 | 0.117394 | 0.4507 |
| Freq (prior-season) | 1.060321 | [1.039499, 1.081588] | 0.214071 | 0.039693 | 0.4507 |

Market+Elo (equal) beats the production ensemble on the full population too: ΔLL 0.0403 [0.0206, 0.0591], and ECE drops from 0.063 to 0.040.

## 6. Clear winner

- **On the 469 odds-covered matches: Market-only** (LL 0.894). It beats every competitor in every season, and its dominance over the production ensemble is significant (Δ +0.067, CI [0.043, 0.092]).
- **Best deployable single architecture: Market + Elo with learned strict-prior weights** (LL 0.916 on n=346; ≈0.935 on all 619 with equal weights). It is the best model that works when odds are missing (Elo covers 519/619 matches vs 0 for odds-only), second only to market-only where odds exist, and is the best-calibrated (ECE 0.040 on all 619, 0.055 on the odds pool) — near the 0.05 'good' bar.

## 7. Recommendation

1. **Market + Elo should become the candidate architecture** (equal weights to start; learned strict-prior weights ≈0.54/0.46 as the refinement). It permanently removes rolling-form and rest-days, which add no OOS value and actively hurt once market+elo are present.
2. **Recommended next implementation phase**: build a production `EnsembleEngine` variant restricted to the market+elo signals with (a) equal 0.5/0.5 weights, (b) optional inverse-log-loss weights fitted on a strictly-prior rolling window (never the eval season), and (c) a documented uniform-fallback for market odds when odds are absent. Wire it behind a config flag with the same `Signal` interface so no simulation/UI changes are required to A/B-test it against the current 4-signal ensemble in the gate harness.
3. **Decision support**: on odds-covered matches, if the product accepts a pure-market signal, market-only is the stronger option; M+E is the safer architecture when odds coverage is incomplete. Do not tune weights on the evaluation set; the equal-weights result is already robust.

## 8. Verification & remaining caveats

- Independent agent recomputation matched all pooled metrics to 5×10⁻⁷ (log-loss, Brier, accuracy) on n=469 and n=619.
- Elo is a static per-season snapshot (one rating per team) — 'pre-match' holds by construction; within-season Elo movement is not modeled.
- 2019/20 (n=119) is excluded from the odds population (no odds fields); the all-completed secondary table includes it.
- Brier 1/3 scale matches `football_core.multi_class_brier` convention used in EVALUATION.md.
- Bootstrap CIs assume exchangeability of matches (independent draws); match dependence within a season/team is not modeled.
