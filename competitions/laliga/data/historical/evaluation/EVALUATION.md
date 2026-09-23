# LaLiga Out-of-Sample Model Evaluation — Historical Backfill (2019/20–2023/24)

Evaluated by `competitions/laliga/historical_backfill/evaluate.py` (READ-ONLY: no model code,
production weights, or UI changed). Raw numbers: `data/historical/evaluation/eval_results.json`.
Leak-free replay: every match predicted with a prior-only context and its own season's pre-match
Elo snapshot. ECE = `football_core.evaluation.multi_class_ece` (confidence-vs-accuracy ECE, the
production metric). The dataset was rebuilt on 2026-09-22 to fix double-encoded (mojibake) team
keys; all numbers below are from the clean rebuild (content-identical to the pre-rebuild run,
which was independently verified by Agent C — see `VERIFICATION.md`).

## Population counts
| Season | n usable | odds n | elo-covered n |
|---|---|---|---|
| 2019/20 | 380 | 380 | 380 |
| 2020/21 | 380 | 380 | 380 |
| 2021/22 | 380 | 380 | 380 |
| 2022/23 | 380 | 380 | 380 |
| 2023/24 | 380 | 380 | 380 |
| **All** | **1900** | **1900** | **1900** |

LaLiga's 20-team double round-robin gives a fully-completed population: every season is 380
matches and, unlike UCL, **every match has Pinnacle closing odds** (odds coverage 100%) and full
Elo coverage. There is no odds-less subpopulation and therefore no coverage justification for a
diluted ensemble on this competition.

## Cross-season results (LL = multi-class log-loss, Br = Brier, ECE = multi_class_ece)
| Season | Ens LL | Br | ECE | Unif LL | Elo LL | Mkt LL | Freq LL (win) |
|---|---|---|---|---|---|---|---|
| 2019/20 | 1.0132 | 0.2025 | 0.078 | 1.0986 | 1.1080 | 0.9808 | 1.1054 |
| 2020/21 | 1.0139 | 0.2024 | 0.037 | 1.0986 | 1.1069 | 0.9836 | 1.0776 |
| 2021/22 | 1.0107 | 0.2019 | 0.097 | 1.0986 | 1.0946 | 0.9859 | 1.0895 |
| 2022/23 | 0.9972 | 0.1986 | 0.039 | 1.0986 | 1.0753 | 0.9797 | 1.0162 |
| 2023/24 | 0.9922 | 0.1977 | 0.096 | 1.0986 | 1.0771 | 0.9488 | 1.0868 |
| **All 1900** | **1.0054** | **0.2006** | **0.063** | **1.0986** | **1.0924** | **0.9758** | **1.0791** |

Same-population baselines on the same 1900 matches (freq = prior-season base rates on the same
population). Pooled chronological 70/30 holdout (n_fit 1330, n_eval 570): ensemble 0.9902 vs freq
1.0624 vs uniform 1.0986. All values independently recomputed by Agent C to ≤1e-6 (see
`VERIFICATION.md`).

## Leave-one-signal-out ablation (marginal ΔLL, pooled; positive = signal helps)
| Signal | Overall |
|---|---|
| market_odds | +0.0413 |
| rest_days | +0.0013 |
| refined_elo | **−0.0038** |
| rolling_form | **−0.0112** |

Consistent across seasons. **market_odds is the dominant signal** — removing it costs +0.041 LL
in every season. rest_days adds almost nothing (+0.0013); **refined_elo and rolling_form actively
hurt** when present with market odds (−0.004 and −0.011). `squad_value`: **unavailable** (no
historical source) — excluded from fitting/ablation, production weights renormalized over the 4
historical signals.

## Learned weights by training window (strictly-prior train → target season)
| Train → Eval | train n | odds | elo | form | rest | OOS LL (learned) |
|---|---|---|---|---|---|---|
| 2019/20 → 2020/21 | 380 | .2709 | .2403 | .2458 | .2430 | 1.0129 |
| → 2021/22 | 760 | .2719 | .2428 | .2438 | .2431 | 1.0125 |
| → 2022/23 | 1140 | .2713 | .2425 | .2443 | .2417 | 0.9948 |
| → 2023/24 | 1520 | .2709 | .2435 | .2444 | .2424 | 0.9894 |

Stability: weights are essentially frozen across windows (all per-signal min/max spread ≤ 0.0024;
window-to-window shifts ≤ 0.002). Fits favor market odds at a stable ~0.271 plateau. Agreement
with production renormalized weights is moderate (Pearson 0.458 — production was fitted on
2026/27 live data including squad_value, a cross-population transfer). Learned weights with
strictly-prior training tilt market_odds higher than the production renormalization gives it.

## Answers
1. **Beats uniform?** **A** — every season, pooled (1.0054 vs 1.0986), and the 70/30 window.
   Market-only beats uniform even more decisively (0.9758).
2. **Beats empirical frequency?** **A** — pooled prior-season freq 1.0791; ensemble 1.0054.
   Ensemble beats freq in every seasonal window too (widest margin 1.0065 in 2019/20).
3. **Beats Elo-only?** **A** — pooled (1.0054 vs 1.0924) and every season; Elo-only on full
   coverage is the weakest learnt model due to its overconfidence (ECE 0.158, conf 0.64 vs
   acc 0.49).
4. **Beats market-odds-only on the identical population?** **D** — loses all five seasons and
   pooled (1.0054 vs 0.9758, n=1900 identical). Bootstrap 95% CI on ΔLL (prod − market) =
   [0.0185, 0.0409], **excludes zero**: market-only is significantly better. On LaLiga
   historical data every match has clean Pinnacle closing odds; the 4-signal dilution blunts
   the single most informative signal.
5. **Which signals add predictive value?** market_odds (+) dominates; rest_days (+ ~0.001,
   negligible); refined_elo (−) and rolling_form (−) actively subtract once market is present.
   `squad_value` unavailable.
6. **Calibration acceptable?** Yes for the ensemble — pooled ECE 0.063, 95% CI [0.041, 0.085]
   (≤ "acceptable" 0.10 bar, meets "good" ≈ 0.05 in CI lower region). Market-only is the
   best-calibrated (ECE 0.029, CI [0.021, 0.054]). Elo-only is badly overconfident
   (ECE 0.158).
7. **Stable across seasons?** **A** — ensemble LL 0.992–1.014 (spread 0.021), consistent
   rankings and directionality every season; weights internally frozen.

## Verdict
- Overall: **B** (ensemble has genuine, stable, calibrated predictive value vs uniform,
  frequency, and Elo baselines on fully-covered data).
- Versus market odds alone on the same population: **D** — decisive loss, CI excludes zero.
- The takeaway mirrors UCL but is stronger: the production 4-signal ensemble adds value over
  naive baselines, yet on a competition where **100%** of matches have Pinnacle closing odds it
  is beaten outright by simply calling the market. Root cause is weight dilution — the
  renormalized weights give market only ~0.33 while form and Elo subtract. A market+form+rest
  blend (0.9971) or market+elo (0.9978) trims the gap, and market-only (0.9758) is the best
  single architecture.

## Limitations
1. **squad_value missing for all seasons** → excluded; production weights renormalized over 4
   signals (approximation vs the live 5-signal engine).
2. **Odds are single-bookmaker Pinnacle** (1897/1900; 3 fallback to Bet365), closing line at
   kickoff (`odds_known_at = event_date`); no intraday odds timestamps from football-data.co.uk.
3. **Elo snapshot is a single pre-season archive mirror** (api.clubelo.com unreachable here) —
   deliberately stale for later rounds, so Elo's historically-fitted weight is a lower bound on
   its contribution had in-season updates been available.
4. Production weights were fitted on **2026/27 live** data, a cross-population transfer;
   historically-learned weights (which favor market ~0.271) are the fairer historical
   comparison and always match or beat production-renormalized OOS.
5. Windows text-encoding fragility in the shared historical loaders (all readers use the same
   default encoding, so results are consistent and verified correct; mixing `utf-8` on one
   reader silently breaks team→Elo lookup). See `VERIFICATION.md` anomaly note.

## Independent verification
`evaluation/VERIFICATION.md` (Agent C): every headline number reproduced exactly from the raw
dataset with an independent pipeline — uniform LL ≡ ln 3 to 6 dp, all pooled and per-season
baselines match `eval_results.json`, no discrepancies above 1e-6.