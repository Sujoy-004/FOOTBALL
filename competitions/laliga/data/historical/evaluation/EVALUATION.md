# LaLiga Out-of-Sample Model Evaluation — competitions/laliga/data/historical (2000/01-2025/26)

**Competition:** LaLiga  
**Dataset:** `competitions/laliga/data/historical (2000/01-2025/26)`  
**Generated:** `2026-10-16T04:19:14.713789+00:00`  
**Method:** replay: every match predicted with a prior-only context and its own season's pre-match Elo snapshot; no future-data leakage  
**Seed:** 20260601  

## Declarations

- LaLiga odds coverage: every match in the backtest carries Pinnacle closing odds (~100% coverage), so the reported numbers are computed on a fully-covered population with no odds-less subpopulation.
- 4-signal renormalization: `squad_value` has no historical data source, so the production weights are renormalized over the four historical signals (market_odds / refined_elo / rolling_form / rest_days); this is not the live 5-signal engine.
- D-01 window: the corpus spans competitions/laliga/data/historical (2000/01-2025/26); one fixed chronological split (train ≤ 2020-12-31, validate 2021–2026).

## Population counts

| Season | n usable | odds n | elo-covered n |
|---|---|---|---|
| 2000_01 | 380 | 0 | 380 |
| 2001_02 | 380 | 0 | 380 |
| 2002_03 | 380 | 379 | 380 |
| 2003_04 | 380 | 375 | 380 |
| 2004_05 | 380 | 380 | 380 |
| 2005_06 | 380 | 380 | 380 |
| 2006_07 | 380 | 380 | 380 |
| 2007_08 | 380 | 380 | 380 |
| 2008_09 | 380 | 380 | 380 |
| 2009_10 | 380 | 380 | 380 |
| 2010_11 | 380 | 380 | 380 |
| 2011_12 | 380 | 380 | 380 |
| 2012_13 | 380 | 380 | 380 |
| 2013_14 | 380 | 380 | 380 |
| 2014_15 | 380 | 380 | 380 |
| 2015_16 | 380 | 380 | 380 |
| 2016_17 | 380 | 380 | 380 |
| 2017_18 | 380 | 380 | 380 |
| 2018_19 | 380 | 380 | 380 |
| 2019_20 | 380 | 380 | 380 |
| 2020_21 | 380 | 380 | 380 |
| 2021_22 | 380 | 380 | 380 |
| 2022_23 | 380 | 380 | 380 |
| 2023_24 | 380 | 380 | 380 |
| 2024_25 | 380 | 380 | 380 |
| 2025_26 | 380 | 380 | 380 |

## Cross-season results

| Season | Ens LL | Br | ECE | Unif LL | Elo LL | Mkt LL | Freq LL |
|---|---|---|---|---|---|---|---|
| 2000_01 | 1.0053 | 0.2001 | 0.0598 | 1.0986 | 1.0355 | — | 1.0616 |
| 2001_02 | 1.0369 | 0.2075 | 0.0145 | 1.0986 | 1.1007 | — | 1.0581 |
| 2002_03 | 1.0458 | 0.2097 | 0.0626 | 1.0986 | 1.1322 | 1.0282 | 1.0772 |
| 2003_04 | 1.0612 | 0.2125 | 0.0702 | 1.0986 | 1.1696 | 1.0324 | 1.0591 |
| 2004_05 | 0.9913 | 0.1965 | 0.0771 | 1.0986 | 1.0515 | 0.9782 | 1.0786 |
| 2005_06 | 1.0732 | 0.2154 | 0.0952 | 1.0986 | 1.1929 | 1.0304 | 1.0948 |
| 2006_07 | 1.0446 | 0.2090 | 0.0601 | 1.0986 | 1.1385 | 1.0176 | 1.0501 |
| 2007_08 | 1.0366 | 0.2056 | 0.0867 | 1.0986 | 1.1240 | 1.0105 | 1.0388 |
| 2008_09 | 1.0069 | 0.1992 | 0.0469 | 1.0986 | 1.0949 | 0.9706 | 1.0119 |
| 2009_10 | 0.9454 | 0.1871 | 0.0455 | 1.0986 | 0.9978 | 0.9214 | 1.0270 |
| 2010_11 | 0.9520 | 0.1867 | 0.0555 | 1.0986 | 0.9941 | 0.9292 | 1.0334 |
| 2011_12 | 0.9608 | 0.1899 | 0.0225 | 1.0986 | 1.0101 | 0.9468 | 1.0294 |
| 2012_13 | 0.9672 | 0.1901 | 0.0610 | 1.0986 | 1.0192 | 0.9412 | 1.0776 |
| 2013_14 | 0.9892 | 0.1954 | 0.0920 | 1.0986 | 1.0826 | 0.9559 | 1.0659 |
| 2014_15 | 0.9510 | 0.1869 | 0.0607 | 1.0986 | 1.0131 | 0.9016 | 1.0991 |
| 2015_16 | 0.9603 | 0.1896 | 0.0744 | 1.0986 | 1.0333 | 0.9272 | 1.0389 |
| 2016_17 | 0.9417 | 0.1856 | 0.0878 | 1.0986 | 1.0096 | 0.9042 | 1.0419 |
| 2017_18 | 0.9898 | 0.1966 | 0.0338 | 1.0986 | 1.1006 | 0.9598 | 1.0477 |
| 2018_19 | 1.0219 | 0.2037 | 0.0748 | 1.0986 | 1.1047 | 1.0090 | 1.0549 |
| 2019_20 | 1.0132 | 0.2025 | 0.0778 | 1.0986 | 1.1080 | 0.9808 | 1.1054 |
| 2020_21 | 1.0139 | 0.2024 | 0.0371 | 1.0986 | 1.1069 | 0.9836 | 1.0776 |
| 2021_22 | 1.0107 | 0.2019 | 0.0968 | 1.0986 | 1.0946 | 0.9859 | 1.0895 |
| 2022_23 | 0.9972 | 0.1986 | 0.0387 | 1.0986 | 1.0753 | 0.9797 | 1.0162 |
| 2023_24 | 0.9922 | 0.1977 | 0.0956 | 1.0986 | 1.0771 | 0.9488 | 1.0868 |
| 2024_25 | 0.9992 | 0.1986 | 0.0748 | 1.0986 | 1.0970 | 0.9524 | 1.0987 |
| 2025_26 | 0.9784 | 0.1931 | 0.0615 | 1.0986 | 1.0247 | 0.9644 | 1.0172 |

## Holdout (fixed chronological split)

- Split: single fixed chronological (D-02)
- Cutoff: 2020-12-31T23:59:59Z
- n_train: 7755
- n_test: 2125

| Comparison | ΔLL | 95% CI | MDE | n |
|---|---|---|---|---|
| ensemble − uniform | -0.1042 | [-0.1233, -0.0851] | 0.0152 | 2125 |
| ensemble − freq | -0.0736 | [-0.0858, -0.0615] | 0.0152 | 2125 |
| ensemble − elo_only | -0.0788 | [-0.0946, -0.0637] | 0.0152 | 2125 |
| ensemble − market_only | +0.0301 | [0.0202, 0.0407] | 0.0152 | 2125 |

**Market-only loss:** ensemble loses to market-only by 0.0301 LL (CI [0.0202, 0.0407]).

### Match-level ordered score (RPS)

- RPS: 0.201570
- ordered_brier = rps/2: 0.100785
- Order: home → draw → away
- Note: secondary, not a gate

### Tournament-level TRPS (roadmap criterion 1)

- TRPS (mean over tournaments): 0.184077
- n_tournaments: 6
- Construction: teams ranked by summed test-match points (3/1/0); ensemble strength = Σ(p_win + 0.5·p_draw); soft rank distribution
- Order: rank 1 = top
- Note: tournament-level TRPS block (roadmap criterion 1); secondary, not a gate

| Season | TRPS |
|---|---|
| 2020_21 | 0.182339 |
| 2021_22 | 0.213086 |
| 2022_23 | 0.184292 |
| 2023_24 | 0.175861 |
| 2024_25 | 0.166420 |
| 2025_26 | 0.182464 |

### Calibration

- Home ECE: 0.0910
- Draw ECE: 0.0084
- Away ECE: 0.0651
- Macro ECE: 0.0548

## Leave-one-signal-out ablation

| Config | n | LL | Brier | ECE |
|---|---|---|---|---|
| full | 9880 | 0.9995 | 0.1985 | 0.0459 |
| without_elo | 9880 | 1.0001 | 0.1990 | 0.0465 |
| without_odds | 9880 | 1.0357 | 0.2055 | 0.0687 |
| without_form | 9880 | 0.9882 | 0.1963 | 0.0427 |
| without_rest | 9880 | 1.0006 | 0.1987 | 0.0466 |

## Learned weights by training window

| Train → Eval | train n | odds | elo | form | rest | OOS LL |
|---|---|---|---|---|---|---|
| 2001_02 | 380 | 0.2425 | 0.2573 | 0.2575 | 0.2427 | 1.0397 |
| 2002_03 | 760 | 0.2456 | 0.2526 | 0.2558 | 0.2460 | 1.0415 |
| 2003_04 | 1140 | 0.2514 | 0.2481 | 0.2542 | 0.2462 | 1.0533 |
| 2004_05 | 1520 | 0.2550 | 0.2448 | 0.2528 | 0.2474 | 0.9983 |
| 2005_06 | 1900 | 0.2571 | 0.2453 | 0.2523 | 0.2453 | 1.0620 |
| 2006_07 | 2280 | 0.2591 | 0.2430 | 0.2514 | 0.2466 | 1.0395 |
| 2007_08 | 2660 | 0.2602 | 0.2424 | 0.2507 | 0.2467 | 1.0324 |
| 2008_09 | 3040 | 0.2611 | 0.2421 | 0.2502 | 0.2466 | 1.0092 |
| 2009_10 | 3420 | 0.2623 | 0.2421 | 0.2496 | 0.2460 | 0.9615 |
| 2010_11 | 3800 | 0.2633 | 0.2430 | 0.2493 | 0.2444 | 0.9645 |
| 2011_12 | 4180 | 0.2641 | 0.2440 | 0.2486 | 0.2433 | 0.9706 |
| 2012_13 | 4560 | 0.2646 | 0.2448 | 0.2482 | 0.2425 | 0.9756 |
| 2013_14 | 4940 | 0.2652 | 0.2453 | 0.2477 | 0.2418 | 0.9924 |
| 2014_15 | 5320 | 0.2659 | 0.2451 | 0.2474 | 0.2416 | 0.9623 |
| 2015_16 | 5700 | 0.2669 | 0.2455 | 0.2466 | 0.2409 | 0.9703 |
| 2016_17 | 6080 | 0.2675 | 0.2457 | 0.2463 | 0.2405 | 0.9555 |
| 2017_18 | 6460 | 0.2682 | 0.2460 | 0.2459 | 0.2399 | 0.9921 |
| 2018_19 | 6840 | 0.2686 | 0.2457 | 0.2459 | 0.2399 | 1.0183 |
| 2019_20 | 7220 | 0.2684 | 0.2455 | 0.2459 | 0.2401 | 1.0144 |
| 2020_21 | 7600 | 0.2686 | 0.2452 | 0.2459 | 0.2403 | 1.0145 |
| 2021_22 | 7980 | 0.2688 | 0.2451 | 0.2457 | 0.2404 | 1.0125 |
| 2022_23 | 8360 | 0.2688 | 0.2450 | 0.2457 | 0.2405 | 1.0011 |
| 2023_24 | 8740 | 0.2689 | 0.2450 | 0.2456 | 0.2405 | 0.9987 |
| 2024_25 | 9120 | 0.2691 | 0.2449 | 0.2456 | 0.2403 | 1.0031 |
| 2025_26 | 9500 | 0.2695 | 0.2448 | 0.2454 | 0.2403 | 0.9874 |

### Verdict

**skill declared**
- MDE: 0.0152
- n: 2125

## Disclosures

1. **4-signal surrogate.** The backtest measures a 4-signal ensemble (`market_odds`, `refined_elo`, `rolling_form`, `rest_days`). `squad_value` has no historical data source and is renormalized away, so this is not the live 5-signal engine.
2. **Odds non-transfer.** The backtest population has ~100% closing-odds coverage while live LaLiga has a handful of fixtures, `book_selection: "none"` and effectively no odds. The result does not transfer to a live population with sparse odds.
3. **Small-n ECE.** Classwise ECE bins with fewer than 20 observations are withheld (D-11); the withheld classes are listed rather than reporting a biased score.
4. **Brier ÷3.** `multi_class_brier` divides by 3, so the scale is `[0, 2/3]` while sklearn's Brier is `[0, 2]`. The ordered-score conversion is `ordered_brier = rps/2` for K=3 (EVAL-07).
5. **MDE context (direction-only).** At n≈144 (UCL) the MDE is ≈0.058 log-loss; at n≈104 (WC) ≈0.069. These confirm direction only — they are **not** effect claims. This report carries a CI, not a p-value.
