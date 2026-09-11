# UCL Out-of-Sample Model Evaluation — Historical Backfill (2019/20–2023/24)

Evaluated by `competitions/ucl/historical_backfill/evaluate.py` (READ-ONLY: no model code,
production weights, or UI changed). Raw numbers: `data/historical/evaluation/eval_results.json`.
Leak-free replay: every match predicted with a prior-only context and its own season's pre-match
Elo snapshot. ECE = `football_core.evaluation.multi_class_ece` (confidence-vs-accuracy ECE); the
production metric was fixed and this eval was regenerated with it — see the note at the end.

## Population counts
| Season | n usable | odds n | elo-covered n |
|---|---|---|---|
| 2019/20 | 119 | 0 | 97 |
| 2020/21 | 125 | 123 | 109 |
| 2021/22 | 125 | 108 | 103 |
| 2022/23 | 125 | 115 | 101 |
| 2023/24 | 125 | 123 | 109 |
| **All** | **619** | **469** | **519** |

## Cross-season results (LL = multi-class log-loss, Br = Brier, ECE = multi_class_ece)
| Season | Ens LL | Br | ECE | Unif LL | Elo LL | Freq LL (win) | Mkt LL (odds sub) |
|---|---|---|---|---|---|---|---|
| 2019/20 | 1.0217 | 0.2036 | 0.075 | 1.0986 | 1.0446 | 1.0109 | — |
| 2020/21 | 0.9793 | 0.1937 | 0.074 | 1.0986 | 1.1018 | 1.0309 | 0.8723 |
| 2021/22 | 0.9672 | 0.1903 | 0.090 | 1.0986 | 1.0298 | 1.1324 | 0.8928 |
| 2022/23 | 0.9539 | 0.1877 | 0.098 | 1.0986 | 0.9952 | 1.0325 | 0.9060 |
| 2023/24 | 0.9560 | 0.1884 | 0.077 | 1.0986 | 0.9825 | 1.0162 | 0.9052 |
| **All 619** | **0.9752** | **0.1926** | **0.064** | **1.0986** | **1.0307** | **1.0494 (n=186 win)** | **0.8939 (n=469)** |

Same-population baselines: Elo and uniform evaluated on the same 619; freq on the pooled 70/30
chronological holdout (n=186, ensemble 0.9497 vs freq 1.0494); market-odds-only on the 469
odds-covered matches (ensemble 0.9612 vs market 0.8939). Elo-covered subset n=519: ensemble
0.9966 vs Elo-only 1.0675.

## Leave-one-signal-out ablation (marginal ΔLL, pooled; positive = signal helps)
| Signal | Overall |
|---|---|
| market_odds | +0.031 |
| refined_elo | +0.031 |
| rolling_form | **−0.022** |
| rest_days | **−0.013** |

Consistent across seasons. Elo and market odds add value; **rolling-form and rest-days actively
hurt** in every season. Removing odds on (no-odds) 2019/20 helps (−0.008, pure uniform dilution).
`squad_value`: **unavailable** (no historical source) — excluded from fitting/ablation.

## Learned weights by training window (strictly-prior train → target season)
| Train → Eval | train n | odds | elo | form | rest | OOS LL (learned) | OOS LL (prod) |
|---|---|---|---|---|---|---|---|
| 2019/20 → 2020/21 | 119 | .2489 | .2617 | .2405 | .2489 | 0.9795 | 0.9793 |
| → 2021/22 | 244 | .2722 | .2496 | .2350 | .2432 | 0.9635 | 0.9672 |
| → 2022/23 | 369 | .2751 | .2501 | .2342 | .2406 | 0.9499 | 0.9539 |
| → 2023/24 | 494 | .2751 | .2513 | .2358 | .2378 | 0.9515 | 0.9560 |

Stability: weights converge as the pool grows (window-to-window shifts collapse 0.023 → ≤0.003);
fits favour market odds (rising to a ~0.275 plateau). Low agreement with production renormalized
weights (Pearson 0.23 — production was fitted on 2026/27 league data incl. squad_value).
Learned weights beat production-renormalized OOS in 3/4 seasons (best −0.004 LL), ties 2020/21.

## Answers
1. **Beats uniform?** **A** — every season, pooled, and holdout windows.
2. **Beats empirical frequency?** **B** — clear pooled win (0.950 vs 1.049, n=186) and 3/5 seasonal
   windows, but loses the no-odds 2019/20 window and 2020/21 marginally.
3. **Beats Elo-only?** **A** — pooled (0.975 vs 1.031), elo-covered (0.997 vs 1.068), every season
   (only 2022/23 holdout window flips).
4. **Beats market-odds-only on the same odds-covered matches?** **D** — loses all four odds
   seasons and pooled (0.961 vs 0.894). Near-uniform ensemble weights dilute the market signal.
5. **Which signals add predictive value?** market_odds (+), refined_elo (+) strongly; rolling_form
   (−), rest_days (−). `squad_value` unavailable.
6. **Calibration acceptable?** Marginal. Ensemble ECE 0.06–0.10 (slightly underconfident:
   mean-confidence ≈ 0.49 vs accuracy ≈ 0.54); above the 0.05 "good" bar. Elo-only is
   overconfident (ECE 0.13: conf 0.67 vs acc 0.54). Market ECE 0.066.
7. **Stable across seasons?** **A** — LL 0.954–1.022 (spread 0.068), consistent rankings and
   directionality in all five seasons; weights internally convergent.

## Verdict
- Overall: **B** (some evidence, but inconclusive).
- Versus market odds alone on odds-covered matches: **D** (decisively worse).
- The ensemble is a genuinely predictive, stable model vs uniform/Elo/frequency baselines, but on
  the 76% of matches with clean Pinnacle closing odds it underperforms simply calling the market.
  Root cause is weight dilution: the near-uniform production weights over 4 signals (market gets
  ~0.26) blunt the single most informative signal while form/rest actively subtract.

## Limitations from missing / imperfect data
1. **2019/20 has 0 market odds** (prebuilt dataset gap): no market comparison possible; ensemble
   degrades to Elo+form+rest and is the weakest season (LL 1.022); freq baseline beats it there.
2. **squad_value missing for all seasons** → excluded; production weights renormalized over 4
   signals (slight approximation vs live 5-signal engine).
3. **Elo coverage 88–91%** (ClubElo mirror lacks UA/CZ/HR/RS/MD/IL/CH/HU): 3–4 teams/season fall
   back to DEFAULT_ELO 1500; elo-covered subset (519) reported separately.
4. **Odds are single-bookmaker Pinnacle**, no consensus averaging; 2-4 matches/season (2020/21,
   2021/22, 2023/24) arrive odds-less.
5. Near-uniform-to-4-signal weights were fitted on **2026/27 live** data, not historical — a
   cross-population transfer; historically-learned weights fix this and help 3/4 seasons.
6. ECE binning is adaptive and confidence-based (max-p); per-season n<100 windows use fewer bins.
7. Holdout windows cover later rounds (MD07–10: KO), measurably harder than group stage.

## NOTE — production ECE helper fixed; eval regenerated with it
`football_core/evaluation.py:multi_class_ece` previously computed `acc = sum(1 for _ in
bin_correct)`, making accuracy ≡ 1.0 and the output `1 − mean_confidence` (a vagueness metric),
not calibration error. Fixed to `acc = sum(bin_correct) / len(bin_correct)` (one line) with
regression tests. `evaluate.py` now calls the production metric directly: the local
`confidence_ece` workaround and the `ece_legacy_buggy` field were removed, and `eval_results.json`
was regenerated. Only ECE-related fields changed; every LL/Brier/baseline value is unchanged. The
production metric rounds per-bin mean-confidence/accuracy to 4dp internally before the weighted
mean, so ECE values differ by ≤5e-5 from the interim local computation (same population, same bins).