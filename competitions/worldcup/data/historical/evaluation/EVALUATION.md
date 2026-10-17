# World Cup Out-of-Sample Model Evaluation — competitions/worldcup/data/historical (2002-2026)

**Competition:** World Cup  
**Dataset:** `competitions/worldcup/data/historical (2002-2026)`  
**Generated:** `2026-10-17T06:57:28.374161+00:00`  
**Method:** replay: every match predicted with a prior-only context and its own season's pre-match Elo snapshot; no future-data leakage  
**Seed:** 20260601  

## Declarations

- Weight-key mapping: `competitions/worldcup/config/signal_weights.json` carries `elo` and `squad_value` keys that the harness signal order does not have; `elo` is mapped to `refined_elo` and `squad_value` is dropped before calling `run_evaluation` (the harness would silently drop them otherwise).
- Confidence ECE (D-10): the WC calibration block uses the confidence `multi_class_ece` (not the per-class variant) because the ~100-match sample cannot satisfy the `observations/bin >= 20` small-n rule.
- Knockout H/D/A + Elo reconciliation: the knockout target is the advancing winner (0/2, never 1) and the forecast is renormalized two-way (`p_home/(p_home+p_away)`); the Elo update coding `W = 0.75/0.25` (`football_core/elo.py:37`) is a rating adjustment, not a 1X2 target.
- National-team Elo feed: no date-indexed historical feed exists; `refined_elo` is `insufficient_data:no_elo_ratings` and the Elo-only baseline is reported unavailable (never fabricated).

## Population counts

| Season | n usable | odds n | elo-covered n |
|---|---|---|---|
| 2002 | 64 | 0 | 0 |
| 2006 | 64 | 0 | 0 |
| 2010 | 64 | 0 | 0 |
| 2014 | 64 | 0 | 0 |
| 2018 | 64 | 0 | 0 |
| 2022 | 64 | 0 | 0 |
| 2026 | 104 | 0 | 0 |

## Cross-season results

| Season | Ens LL | Br | ECE | Unif LL | Elo LL | Mkt LL | Freq LL |
|---|---|---|---|---|---|---|---|
| 2002 | 1.0952 | 0.2202 | 0.0180 | 1.0986 | 1.2619 | — | 1.1041 |
| 2006 | 1.0391 | 0.2076 | 0.0591 | 1.0986 | 1.1361 | — | 0.9800 |
| 2010 | 1.1350 | 0.2293 | 0.0794 | 1.0986 | 1.3599 | — | 1.0559 |
| 2014 | 1.0753 | 0.2154 | 0.0321 | 1.0986 | 1.2447 | — | 0.9447 |
| 2018 | 1.1250 | 0.2259 | 0.0342 | 1.0986 | 1.3559 | — | 0.9208 |
| 2022 | 1.0805 | 0.2163 | 0.0456 | 1.0986 | 1.2036 | — | 0.9614 |
| 2026 | 1.0579 | 0.2119 | 0.0378 | 1.0986 | 1.1902 | — | 1.0269 |

## Holdout (fixed chronological split)

- Split: single fixed chronological (D-02)
- Cutoff: 2020-12-31T23:59:59Z
- n_train: 320
- n_test: 168

| Comparison | ΔLL | 95% CI | MDE | n |
|---|---|---|---|---|
| ensemble − uniform | -0.0322 | [-0.0779, 0.0125] | 0.0540 | 168 |
| ensemble − freq | +0.0401 | [-0.0092, 0.0884] | 0.0540 | 168 |
| ensemble − elo_only | -0.1288 | [-0.2058, -0.0523] | 0.0540 | 168 |
| ensemble − market_only | -0.0322 | [-0.0779, 0.0125] | 0.0540 | 168 |

### Match-level ordered score (RPS)

- RPS: 0.238581
- ordered_brier = rps/2: 0.119290
- Order: home → draw → away
- Note: secondary, not a gate

### Tournament-level TRPS (roadmap criterion 1)

- TRPS (mean over tournaments): 0.159574
- n_tournaments: 2
- Construction: teams ranked by summed test-match points (3/1/0); ensemble strength = Σ(p_win + 0.5·p_draw); soft rank distribution
- Order: rank 1 = top
- Note: tournament-level TRPS block (roadmap criterion 1); secondary, not a gate

| Season | TRPS |
|---|---|
| 2022 | 0.168710 |
| 2026 | 0.150438 |

### Calibration

- Variant: confidence (multi_class_ece)
- ECE: 0.0407

## Leave-one-signal-out ablation

| Config | n | LL | Brier | ECE |
|---|---|---|---|---|
| full | 488 | 1.0845 | 0.2176 | 0.0087 |
| without_elo | 488 | 1.0811 | 0.2178 | 0.0766 |
| without_odds | 488 | 1.1003 | 0.2198 | 0.0513 |
| without_form | 488 | 1.0795 | 0.2171 | 0.0276 |
| without_rest | 488 | 1.1012 | 0.2200 | 0.0638 |

## Learned weights by training window

| Train → Eval | train n | odds | elo | form | rest | OOS LL |
|---|---|---|---|---|---|---|
| 2006 | 64 | 0.2616 | 0.2278 | 0.2491 | 0.2615 | 1.0398 |
| 2010 | 128 | 0.2554 | 0.2340 | 0.2550 | 0.2555 | 1.1328 |
| 2014 | 192 | 0.2606 | 0.2285 | 0.2501 | 0.2607 | 1.0741 |
| 2018 | 256 | 0.2600 | 0.2284 | 0.2513 | 0.2604 | 1.1216 |
| 2022 | 320 | 0.2620 | 0.2263 | 0.2492 | 0.2625 | 1.0798 |
| 2026 | 384 | 0.2616 | 0.2280 | 0.2483 | 0.2621 | 1.0576 |

### Verdict

**not declared**
- Won by: freq
- MDE: 0.0540
- n: 168

## Disclosures

1. **4-signal surrogate.** The backtest measures a 4-signal ensemble (`market_odds`, `refined_elo`, `rolling_form`, `rest_days`). `squad_value` has no historical data source and is renormalized away, so this is not the live 5-signal engine.
2. **Odds non-transfer.** The backtest population has ~100% closing-odds coverage while live LaLiga has a handful of fixtures, `book_selection: "none"` and effectively no odds. The result does not transfer to a live population with sparse odds.
3. **Small-n ECE.** Classwise ECE bins with fewer than 20 observations are withheld (D-11); the withheld classes are listed rather than reporting a biased score.
4. **Brier ÷3.** `multi_class_brier` divides by 3, so the scale is `[0, 2/3]` while sklearn's Brier is `[0, 2]`. The ordered-score conversion is `ordered_brier = rps/2` for K=3 (EVAL-07).
5. **MDE context (direction-only).** At n≈144 (UCL) the MDE is ≈0.058 log-loss; at n≈104 (WC) ≈0.069. These confirm direction only — they are **not** effect claims. This report carries a CI, not a p-value.
