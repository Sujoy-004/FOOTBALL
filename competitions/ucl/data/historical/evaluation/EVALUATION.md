# UCL Out-of-Sample Model Evaluation — competitions/ucl/data/historical (2011/12-2025/26)

**Competition:** UCL  
**Dataset:** `competitions/ucl/data/historical (2011/12-2025/26)`  
**Generated:** `2026-10-16T04:22:07.189685+00:00`  
**Method:** replay: every match predicted with a prior-only context and its own season's pre-match Elo snapshot; no future-data leakage  
**Seed:** 20260601  

## Declarations

- Knockout mapping (D-05/D-06): UCL ties are two-legged, so a per-match "advancing winner" cannot be derived from a single match. Every UCL match in this report is scored as a three-way H/D/A outcome on that leg's own result (90/120-minute score); the two-legged tie winner is a separate figure and is not scored here. No per-match advancing-winner label is applied to UCL.
- Reconciliation with `football_core/elo.py:37`: the Elo update codes a penalty-shootout win as `W = 0.75/0.25` (a two-way partial result), whereas a leg result is a three-way H/D/A. The two codings must not be conflated: a shootout outcome is never rendered as a draw in the tie figure, and the per-match 1X2 labels stay three-way.
- LaLiga has no knockout stage, so this knockout mapping applies to UCL only.

## Population counts

| Season | n usable | odds n | elo-covered n |
|---|---|---|---|
| 2011_12 | 125 | 0 | 87 |
| 2012_13 | 125 | 0 | 101 |
| 2013_14 | 125 | 0 | 103 |
| 2014_15 | 125 | 0 | 89 |
| 2015_16 | 125 | 0 | 89 |
| 2016_17 | 125 | 0 | 97 |
| 2017_18 | 125 | 0 | 91 |
| 2018_19 | 125 | 0 | 107 |
| 2019_20 | 119 | 0 | 97 |
| 2020_21 | 125 | 123 | 109 |
| 2021_22 | 125 | 108 | 103 |
| 2022_23 | 125 | 115 | 101 |
| 2023_24 | 125 | 123 | 109 |
| 2024_25 | 189 | 178 | 151 |
| 2025_26 | 189 | 166 | 146 |

## Cross-season results

| Season | Ens LL | Br | ECE | Unif LL | Elo LL | Mkt LL | Freq LL |
|---|---|---|---|---|---|---|---|
| 2011_12 | 1.0040 | 0.1996 | 0.1193 | 1.0986 | 1.0568 | — | 1.0124 |
| 2012_13 | 1.0346 | 0.2066 | 0.0697 | 1.0986 | 1.1378 | — | 1.0664 |
| 2013_14 | 0.9904 | 0.1960 | 0.1273 | 1.0986 | 0.9815 | — | 0.9864 |
| 2014_15 | 0.9793 | 0.1942 | 0.1282 | 1.0986 | 0.9717 | — | 1.0274 |
| 2015_16 | 0.9563 | 0.1882 | 0.1833 | 1.0986 | 0.8914 | — | 1.0145 |
| 2016_17 | 0.9916 | 0.1975 | 0.1100 | 1.0986 | 0.9554 | — | 1.0518 |
| 2017_18 | 1.0195 | 0.2031 | 0.1144 | 1.0986 | 1.1206 | — | 1.0420 |
| 2018_19 | 1.0235 | 0.2037 | 0.1633 | 1.0986 | 1.0922 | — | 1.0303 |
| 2019_20 | 1.0217 | 0.2036 | 0.0749 | 1.0986 | 1.0446 | — | 1.0109 |
| 2020_21 | 0.9793 | 0.1937 | 0.0743 | 1.0986 | 1.1018 | 0.8723 | 1.0309 |
| 2021_22 | 0.9672 | 0.1903 | 0.0899 | 1.0986 | 1.0298 | 0.8928 | 1.1324 |
| 2022_23 | 0.9539 | 0.1877 | 0.0980 | 1.0986 | 0.9952 | 0.9060 | 1.0325 |
| 2023_24 | 0.9560 | 0.1884 | 0.0766 | 1.0986 | 0.9825 | 0.9052 | 1.0162 |
| 2024_25 | 0.9478 | 0.1862 | 0.1144 | 1.0986 | 1.0120 | 0.8750 | 1.0389 |
| 2025_26 | 0.9724 | 0.1914 | 0.0785 | 1.0986 | 1.0346 | 0.9215 | 1.0071 |

## Holdout (fixed chronological split)

- Split: single fixed chronological (D-02)
- Cutoff: 2020-12-31T23:59:59Z
- n_train: 1215
- n_test: 782

| Comparison | ΔLL | 95% CI | MDE | n |
|---|---|---|---|---|
| ensemble − uniform | -0.1347 | [-0.1603, -0.1097] | 0.0250 | 782 |
| ensemble − freq | -0.0661 | [-0.0847, -0.0486] | 0.0250 | 782 |
| ensemble − elo_only | -0.0602 | [-0.0957, -0.0234] | 0.0250 | 782 |
| ensemble − market_only | +0.0467 | [0.0273, 0.0660] | 0.0250 | 782 |

**Market-only loss:** ensemble loses to market-only by 0.0467 LL (CI [0.0273, 0.0660]).

### Match-level ordered score (RPS)

- RPS: 0.207317
- ordered_brier = rps/2: 0.103659
- Order: home → draw → away
- Note: secondary, not a gate

### Tournament-level TRPS (roadmap criterion 1)

- TRPS (mean over tournaments): 0.159232
- n_tournaments: 6
- Construction: teams ranked by summed test-match points (3/1/0); ensemble strength = Σ(p_win + 0.5·p_draw); soft rank distribution
- Order: rank 1 = top
- Note: tournament-level TRPS block (roadmap criterion 1); secondary, not a gate

| Season | TRPS |
|---|---|
| 2020_21 | 0.218067 |
| 2021_22 | 0.156877 |
| 2022_23 | 0.161874 |
| 2023_24 | 0.155665 |
| 2024_25 | 0.120664 |
| 2025_26 | 0.142247 |

### Calibration

- Home ECE: 0.0685
- Draw ECE: 0.0934
- Away ECE: 0.0781
- Macro ECE: 0.0800

## Leave-one-signal-out ablation

| Config | n | LL | Brier | ECE |
|---|---|---|---|---|
| full | 1997 | 0.9847 | 0.1949 | 0.0848 |
| without_elo | 1997 | 1.0315 | 0.2064 | 0.1092 |
| without_odds | 1997 | 0.9934 | 0.1964 | 0.0672 |
| without_form | 1997 | 0.9717 | 0.1919 | 0.0955 |
| without_rest | 1997 | 0.9699 | 0.1912 | 0.0565 |

## Learned weights by training window

| Train → Eval | train n | odds | elo | form | rest | OOS LL |
|---|---|---|---|---|---|---|
| 2012_13 | 125 | 0.2451 | 0.2548 | 0.2560 | 0.2442 | 1.0332 |
| 2013_14 | 250 | 0.2485 | 0.2488 | 0.2546 | 0.2481 | 0.9882 |
| 2014_15 | 375 | 0.2461 | 0.2554 | 0.2525 | 0.2460 | 0.9750 |
| 2015_16 | 500 | 0.2441 | 0.2587 | 0.2532 | 0.2440 | 0.9499 |
| 2016_17 | 625 | 0.2418 | 0.2635 | 0.2531 | 0.2416 | 0.9856 |
| 2017_18 | 750 | 0.2414 | 0.2654 | 0.2522 | 0.2411 | 1.0161 |
| 2018_19 | 875 | 0.2427 | 0.2623 | 0.2526 | 0.2424 | 1.0204 |
| 2019_20 | 1000 | 0.2436 | 0.2609 | 0.2521 | 0.2434 | 1.0180 |
| 2020_21 | 1119 | 0.2442 | 0.2610 | 0.2508 | 0.2440 | 0.9810 |
| 2021_22 | 1244 | 0.2490 | 0.2588 | 0.2487 | 0.2435 | 0.9662 |
| 2022_23 | 1369 | 0.2516 | 0.2582 | 0.2473 | 0.2429 | 0.9520 |
| 2023_24 | 1494 | 0.2534 | 0.2580 | 0.2468 | 0.2418 | 0.9540 |
| 2024_25 | 1619 | 0.2551 | 0.2580 | 0.2461 | 0.2408 | 0.9459 |
| 2025_26 | 1808 | 0.2579 | 0.2572 | 0.2450 | 0.2399 | 0.9703 |

### Verdict

**skill declared**
- MDE: 0.0250
- n: 782

## Disclosures

1. **4-signal surrogate.** The backtest measures a 4-signal ensemble (`market_odds`, `refined_elo`, `rolling_form`, `rest_days`). `squad_value` has no historical data source and is renormalized away, so this is not the live 5-signal engine.
2. **Odds non-transfer.** The backtest population has ~100% closing-odds coverage while live LaLiga has a handful of fixtures, `book_selection: "none"` and effectively no odds. The result does not transfer to a live population with sparse odds.
3. **Small-n ECE.** Classwise ECE bins with fewer than 20 observations are withheld (D-11); the withheld classes are listed rather than reporting a biased score.
4. **Brier ÷3.** `multi_class_brier` divides by 3, so the scale is `[0, 2/3]` while sklearn's Brier is `[0, 2]`. The ordered-score conversion is `ordered_brier = rps/2` for K=3 (EVAL-07).
5. **MDE context (direction-only).** At n≈144 (UCL) the MDE is ≈0.058 log-loss; at n≈104 (WC) ≈0.069. These confirm direction only — they are **not** effect claims. This report carries a CI, not a p-value.
