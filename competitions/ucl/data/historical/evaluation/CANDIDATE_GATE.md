# UCL Market+Elo Candidate Gate — Evaluation (OOS/leak-free harness)

Generated: `2026-09-11T02:51:58.271150+00:00`  
Dataset: `competitions/ucl/data/historical (2019/20-2023/24)`  
Method: replay: every match predicted with historical.build_context_for_match (prior-only) + per-season pre-match Elo snapshot; no future-data leakage; no weight tuning on the evaluation set

Populations (identical-match lists per directly-compared table):
- **ALL**: n = 619  seasons 2019_20, 2020_21, 2021_22, 2022_23, 2023_24
- **ODDS**: n = 469  seasons 2020_21, 2021_22, 2022_23, 2023_24
- **NOODS**: n = 150  seasons 2019_20, 2020_21, 2021_22, 2022_23, 2023_24
- **me_prior_valid**: ALL n = 375, ODDS n = 346  seasons 2021_22, 2022_23, 2023_24

## 1. Pooled results (ALL)

| model | n | log_loss | 95% CI | brier | ece | mean_conf | acc |
| --- | --- | --- | --- | --- | --- | --- | --- |
| me_equal | 619 | 0.9509 | [0.8960, 1.0101] | 0.1851 | 0.0623 | 0.6236 | 0.5719 |
| me_prior_fixed | 619 | 0.9476 | [0.8934, 1.0060] | 0.1844 | 0.0534 | 0.6205 | 0.5719 |
| prod_ensemble | 619 | 0.9752 | [0.9477, 1.0044] | 0.1926 | 0.0635 | 0.4854 | 0.5396 |
| elo_only | 619 | 1.0307 | [0.9640, 1.1025] | 0.1987 | 0.1300 | 0.6712 | 0.5412 |
| uniform | 619 | 1.0986 | [1.0986, 1.0986] | 0.2222 | 0.1174 | 0.3333 | 0.4507 |
| freq | 619 | 1.0603 | [1.0395, 1.0816] | 0.2141 | 0.0397 | 0.4110 | 0.4507 |

Paired delta-LL CIs:
- production_vs_me_equal: `0.0248` [`-0.0110`, `0.0566`]
- production_vs_me_prior_fixed: `0.0281` [`-0.0073`, `0.0596`]
- me_prior_vs_me_equal_ALL_valid: `-0.0037` [`-0.0059`, `-0.0015`]

## 2. Pooled results (ODDS)

| model | n | log_loss | 95% CI | brier | ece | mean_conf | acc |
| --- | --- | --- | --- | --- | --- | --- | --- |
| me_equal | 469 | 0.9238 | [0.8719, 0.9773] | 0.1816 | 0.0556 | 0.6082 | 0.5757 |
| me_prior_fixed | 469 | 0.9194 | [0.8683, 0.9714] | 0.1806 | 0.0557 | 0.6040 | 0.5757 |
| prod_ensemble | 469 | 0.9612 | [0.9286, 0.9940] | 0.1894 | 0.0761 | 0.4977 | 0.5458 |
| market_only | 469 | 0.8939 | [0.8497, 0.9386] | 0.1748 | 0.0661 | 0.5726 | 0.6183 |
| elo_only | 469 | 1.0290 | [0.9585, 1.1056] | 0.1995 | 0.1359 | 0.6710 | 0.5352 |
| uniform | 469 | 1.0986 | [1.0986, 1.0986] | 0.2222 | 0.1251 | 0.3333 | 0.4584 |
| freq | 469 | 1.0512 | [1.0234, 1.0776] | 0.2121 | 0.0285 | 0.4299 | 0.4584 |

Paired delta-LL CIs:
- production_vs_me_equal: `0.0370` [`0.0135`, `0.0590`]
- me_equal_vs_market_only: `0.0303` [`0.0101`, `0.0519`]
- me_prior_vs_me_equal_ODDS_valid: `-0.0040` [`-0.0063`, `-0.0016`]

## 3. Pooled results (NOODS — Elo-fallback population)

| model | n | log_loss | 95% CI | brier | ece | mean_conf | acc |
| --- | --- | --- | --- | --- | --- | --- | --- |
| me_equal | 150 | 1.0358 | [0.8923, 1.1796] | 0.1962 | 0.1393 | 0.6718 | 0.5600 |
| me_prior_fixed | 150 | 1.0358 | [0.8923, 1.1796] | 0.1962 | 0.1393 | 0.6718 | 0.5600 |
| prod_ensemble | 150 | 1.0189 | [0.9738, 1.0623] | 0.2028 | 0.0730 | 0.4470 | 0.5200 |
| elo_only | 150 | 1.0358 | [0.8923, 1.1796] | 0.1962 | 0.1393 | 0.6718 | 0.5600 |
| uniform | 150 | 1.0986 | [1.0986, 1.0986] | 0.2222 | 0.0933 | 0.3333 | 0.4267 |
| freq | 150 | 1.0889 | [1.0684, 1.1101] | 0.2202 | 0.0764 | 0.3520 | 0.4267 |

Paired delta-LL CIs:
- production_vs_me_equal: `-0.0170` [`-0.1225`, `0.0841`]
- production_vs_me_prior_fixed: `-0.0170` [`-0.1225`, `0.0841`]

Note: on NOODS the market+Elo candidates have no usable odds and return the refined-Elo probabilities unchanged (no fabricated odds), so me_equal == me_prior_fixed == elo_only by construction.

## 4. me_prior-valid populations (2021/22-2023/24)

- **ALL-valid** (n = 375):
  - me_equal: LL `0.921538`, Brier `0.180097`, ECE `0.054652`
  - me_prior: LL `0.917874`, Brier `0.17932`, ECE `0.043721`
  - delta-LL (me_prior − me_equal): `-0.003675` 95% CI `[-0.005881, -0.001526]`
- **ODDS-valid** (n = 346):
  - me_equal: LL `0.91962`, Brier `0.180731`, ECE `0.055241`
  - me_prior: LL `0.91565`, Brier `0.179889`, ECE `0.041362`
  - delta-LL (me_prior − me_equal): `-0.003961` 95% CI `[-0.006299, -0.001638]`

## 5. Per-season log-loss

### ALL
| season | n | me_equal | me_prior_fixed | prod_ensemble | elo_only | uniform | freq | me_prior |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019_20 | 119 |   1.0446 |   1.0446 |   1.0217 |   1.0446 |   1.0986 |   1.0986 |        — |
| 2020_21 | 125 |   0.9499 |   0.9427 |   0.9793 |   1.1018 |   1.0986 |   1.0503 |        — |
| 2021_22 | 125 |   0.9460 |   0.9425 |   0.9672 |   1.0298 |   1.0986 |   1.0578 |   0.9412 |
| 2022_23 | 125 |   0.9120 |   0.9088 |   0.9539 |   0.9952 |   1.0986 |   1.0499 |   0.9084 |
| 2023_24 | 125 |   0.9066 |   0.9041 |   0.9560 |   0.9825 |   1.0986 |   1.0468 |   0.9041 |

### ODDS
| season | n | me_equal | me_prior_fixed | prod_ensemble | market_only | elo_only | uniform | freq | me_prior |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019_20 | 0 |        — |        — |        — |        — |        — |        — |        — |        — |
| 2020_21 | 123 |   0.9356 |   0.9282 |   0.9738 |   0.8723 |   1.0899 |   1.0986 |   1.0461 |        — |
| 2021_22 | 108 |   0.9195 |   0.9155 |   0.9576 |   0.8928 |   1.0165 |   1.0986 |   1.0479 |   0.9140 |
| 2022_23 | 115 |   0.9257 |   0.9222 |   0.9540 |   0.9060 |   1.0162 |   1.0986 |   1.0604 |   0.9218 |
| 2023_24 | 123 |   0.9140 |   0.9114 |   0.9584 |   0.9052 |   0.9911 |   1.0986 |   1.0506 |   0.9114 |

### NOODS
| season | n | me_equal | me_prior_fixed | prod_ensemble | elo_only | uniform | freq | me_prior |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019_20 | 119 |   1.0446 |   1.0446 |   1.0217 |   1.0446 |   1.0986 |   1.0986 |        — |
| 2020_21 | 2 |   1.8321 |   1.8321 |   1.3225 |   1.8321 |   1.0986 |   1.3080 |        — |
| 2021_22 | 17 |   1.1144 |   1.1144 |   1.0280 |   1.1144 |   1.0986 |   1.1210 |        — |
| 2022_23 | 10 |   0.7539 |   0.7539 |   0.9525 |   0.7539 |   1.0986 |   0.9294 |        — |
| 2023_24 | 2 |   0.4521 |   0.4521 |   0.8082 |   0.4521 |   1.0986 |   0.8135 |        — |

## 6. Required delta comparisons (paired 95% delta-LL CIs)

| comparison | delta-LL | 95% CI |
| --- | --- | --- |
| production − me_equal on ALL (n=619) | 0.0248 | [-0.0110, 0.0566] |
| me_equal − market_only on ODDS (n=469) | 0.0303 | [0.0101, 0.0519] |
| me_prior − me_equal on ALL-valid (n=375) | -0.0037 | [-0.0059, -0.0015] |
| me_prior − me_equal on ODDS-valid (n=346) | -0.0040 | [-0.0063, -0.0016] |
| production − me_equal on NOODS (n=150) | -0.0170 | [-0.1225, 0.0841] |
| production − me_prior_fixed on NOODS (n=150) | -0.0170 | [-0.1225, 0.0841] |

## 7. Candidate-gate verdict

### G1: PASS
- Condition: No temporal leakage
- Test: every prediction uses historical.build_context_for_match (prior-only), per-season pre-match Elo snapshot; chronology must be date/matchday; ensemble beats uniform+freq; n_real_signals>=2 (gate_verdict on ALL)
- chronology: date
- provenance used_signals on ALL: {'n_2_signals': 469, 'n_1_signal': 150}
- gate_verdict(PASS): []
### G2: FAIL
- Condition: G2: candidate improves meaningfully over current production on the relevant all-match population (ALL)
- Test: paired 95% CI for delta-LL = production - me_equal on ALL lies strictly above 0 (CI lower bound > 0)
- delta-LL (production − me_equal): `0.02476`, CI `[-0.011024, 0.056559]`
### G3: PASS
- Condition: G3: no material regression vs production on odds-covered matches (ODDS)
- Test: same CI for delta-LL = production - me_equal on ODDS is above 0; document that market_only remains numerically better than me_equal on ODDS (expected; Elo coverage is the reason)
- delta-LL (production − me_equal): `0.036977`, CI `[0.013525, 0.059045]`
- tradeoff me_equal − market_only (ODDS): `0.030313`, CI `[0.010129, 0.05192]` — market_only remains numerically better on ODDS (expected; the candidate's advantage is Elo coverage for no-odds matches)
### G4: PASS
- Condition: G4: Elo fallback validated on NOODS
- Test: (a) tests cover missing-odds fallback + provenance + determinism and pass; (b) NOODS table shows me_equal/me_prior_fixed not materially worse than production on the 150 no-odds matches (95% CI vs production)
- targeted tests returncode: `0` (PASS) — 104 passed, 0 failed/errors
- NOODS delta production − me_equal: `-0.016968`, CI `[-0.122535, 0.084081]`
- NOODS delta production − me_prior_fixed: `-0.016968`, CI `[-0.122535, 0.084081]`
- note: on NOODS the Market+Elo signal has no usable odds and returns the refined-Elo probabilities unchanged (no fabricated odds), so me_equal/me_prior_fixed/elo_only are identical by construction
### G5: PASS
- Condition: G5: tests remain green (targeted subset result; final full-suite verification left to the main agent)
- Test: run the targeted test subset and report the result
- returned 0; summary: 104 passed, 0 failed/errors
- targeted pytest tail: `........................................................................ [ 69%]
................................                                         [100%]
104 passed`

## 8. Does the candidate remain superior after including no-odds matches?

- production − me_equal delta-LL on **ODDS**: `0.036977` CI `[0.013525, 0.059045]`
- production − me_equal delta-LL on **ALL (with no-odds)**: `0.02476` CI `[-0.011024, 0.056559]`
- production - me_equal delta-LL is POSITIVE on both the ODDS population (0.0370, CI [0.0135, 0.0590]) and the ALL population including the 150 no-odds matches (0.0248, CI [-0.0110, 0.0566]) — i.e. me_equal has lower (better) OOS log-loss than production on the full 619-match population, not only on the 469 odds-covered ones. The candidate's superiority is driven by the odds-covered matches (me_equal LL 0.9238 vs production 0.9613 on ODDS); on the 150 no-odds matches it degrades to pure refined-Elo (LL 1.0358 vs production 1.0179) and the market-only signal remains the best single predictor on ODDS (LL 0.8939). The ALL-population 95% CI still straddles zero, so the overall gain is not declared 'meaningful' at 95% (see G2).
