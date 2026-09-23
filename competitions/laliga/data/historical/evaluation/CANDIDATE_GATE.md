# LaLiga Reduced-Architecture Investigation + Promotion Gate (OOS/leak-free harness)

Generated: `2026-09-22T04:50:11.893803+00:00`  
Dataset: `competitions/laliga/data/historical (2019/20-2023/24)`  
Method: replay with `historical.build_context_for_match` (prior-only) + per-season pre-match Elo snapshot; no future-data leakage; production config reuses evaluate.py's renormalized weights verbatim (squad_value has no historical source).

## 1. Pooled results — full population (n = 1900)

| config | log_loss | 95% CI | brier | ece | acc |
| --- | --- | --- | --- | --- | --- |
| Market odds only | 0.9758 | [0.9560, 0.9955] | 0.1937 | 0.0290 | 0.5332 |
| Elo only | 1.0924 | [1.0562, 1.1287] | 0.2168 | 0.1583 | 0.4863 |
| Market + Elo (equal 0.5/0.5) | 0.9978 | [0.9728, 1.0233] | 0.1990 | 0.0650 | 0.5026 |
| Market + Form (equal 0.5/0.5) | 1.0031 | [0.9863, 1.0198] | 0.2001 | 0.0491 | 0.4916 |
| Market + Form + Rest (0.55/0.35/0.10) | 0.9971 | [0.9819, 1.0122] | 0.1987 | 0.0532 | 0.5058 |
| Market + Form + Rest + Elo (equal 0.25) | 1.0098 | [0.9939, 1.0258] | 0.2015 | 0.0509 | 0.4879 |
| Production ensemble (5 wts renormalized /4) | 1.0054 | [0.9849, 1.0260] | 0.2006 | 0.0631 | 0.4889 |

## 2. Architecture exploration — ranking (pooled log-loss)

1. **Market odds only** — LL 0.9758, ECE 0.0290, acc 0.5332
2. **Market + Form + Rest (0.55/0.35/0.10)** — LL 0.9971, ECE 0.0532, acc 0.5058
3. **Market + Elo (equal 0.5/0.5)** — LL 0.9978, ECE 0.0650, acc 0.5026
4. **Market + Form (equal 0.5/0.5)** — LL 1.0031, ECE 0.0491, acc 0.4916
5. **Production ensemble (5 wts renormalized /4)** — LL 1.0054, ECE 0.0631, acc 0.4889
6. **Market + Form + Rest + Elo (equal 0.25)** — LL 1.0098, ECE 0.0509, acc 0.4879
7. **freq_prior_season** — LL 1.0791, ECE 0.0267, acc 0.4453
8. **Elo only** — LL 1.0924, ECE 0.1583, acc 0.4863
9. **uniform** — LL 1.0986, ECE 0.1119, acc 0.4453

## 3. Ablation (leave-one-signal-out, production-renormalized weights)

| removal | delta-LL (removal - full) | effect |
| --- | --- | --- |
| remove_refined_elo | -0.0038 | helps |
| remove_market_odds | +0.0413 | hurts |
| remove_rolling_form | -0.0112 | helps |
| remove_rest_days | +0.0013 | hurts |

- **Most contributing signal**: `remove_market_odds` (removal most hurtful).
- **Closest to redundant**: `remove_rest_days` (removal barely moves log-loss).

## 4. Bootstrap CIs (95%, 2000 resamples, seed 20260601, plain resample-by-match)

| model | log_loss CI | brier CI | ece CI | accuracy CI |
| --- | --- | --- | --- | --- |
| production_with_historical_inputs | [0.9849, 1.0260] | [0.1959, 0.2055] | [0.0412, 0.0845] | [0.4652, 0.5121] |
| market_only | [0.9560, 0.9955] | [0.1891, 0.1982] | [0.0209, 0.0543] | [0.5100, 0.5563] |
| uniform | [1.0986, 1.0986] | [0.2222, 0.2222] | [0.0893, 0.1346] | [0.4226, 0.4679] |
| freq_prior_season | [1.0697, 1.0886] | [0.2155, 0.2199] | [0.0189, 0.0514] | [0.4226, 0.4679] |

Paired delta-LL CIs:
- production_with_historical_inputs_vs_market_only: `0.0295` [`0.0185`, `0.0409`]
- production_with_historical_inputs_vs_uniform: `-0.0933` [`-0.1137`, `-0.0726`]
- production_with_historical_inputs_vs_freq_prior_season: `-0.0736` [`-0.0894`, `-0.0582`]
- market_only_vs_uniform: `-0.1228` [`-0.1426`, `-0.1031`]
- market_only_vs_freq_prior_season: `-0.1031` [`-0.1203`, `-0.0851`]
- production_with_historical_inputs_vs_elo_only: `-0.0868` [`-0.1040`, `-0.0700`]
- market_only_vs_elo_only: `-0.1163` [`-0.1416`, `-0.0922`]

## 5. Promotion-gate verdict

### C1: PASS
- Condition: Ensemble beats uniform 1/3 on the full population
- Test: production pooled LL < uniform (1.0986) and delta-LL CI (production - uniform) entirely negative
- production LL `1.0054` vs reference `1.0986`; delta-LL `-0.0933`, 95% CI `[-0.1137, -0.0726]`

### C2: PASS
- Condition: Ensemble beats empirical-frequency baseline
- Test: production pooled LL < freq_prior_season and delta-LL CI entirely negative; supplementary: pooled chronological 70/30 window from evaluate.py
- production LL `1.0054` vs reference `1.0791`; delta-LL `-0.0736`, 95% CI `[-0.0894, -0.0582]`

### C3: PASS
- Condition: Acceptable calibration (ECE)
- Test: production pooled ECE <= 0.10 with the bootstrap 95% CI upper bound also <= 0.10 (0.05 = 'good', 0.10 = acceptable)
- ECE point `0.0631`, 95% CI `[0.0412, 0.0845]`

### C4: FAIL
- Condition: Ensemble beats market-only (net LL gain w/ CI)
- Test: bootstrap delta-LL (production - market_only) 95% CI upper bound strictly below 0 (i.e. production better)
- production LL `1.0054` vs reference `0.9758`; delta-LL `0.0295`, 95% CI `[0.0185, 0.0409]`

### C5: PASS
- Condition: No catastrophic season in per-season results
- Test: production beats uniform in every season and no season's production - market_only deficit exceeds 2x the pooled deficit (season-collapse guard)
- per-season production-market deficit: {'2019_20': 0.0324, '2020_21': 0.0303, '2021_22': 0.0248, '2022_23': 0.0175, '2023_24': 0.0434}; worst 0.0434, pooled 0.0297

## Recommendation

**CONDITIONAL** — The production 4-signal config clears uniform, frequency, and calibration (C1/C2/C3/C5 PASS) but is DECISIVELY worse than calling the market on the fully odds-covered population: delta-LL (production - market_only) = +0.0295, 95% CI [0.0185, 0.0409] — CI excludes zero, so market_only is significantly better. On LaLiga historical data every match has usable market odds, so there is no coverage gap to justify the diluted ensemble. CONDITIONAL: promote only behind a market-only (or market+elo) reference and a reweighted blend — not as the standalone historical baseline.
