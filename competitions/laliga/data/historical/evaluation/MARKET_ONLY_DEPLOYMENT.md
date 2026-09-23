# LaLiga market_only deployment evaluation — Phases 12C/12D/12E

Generated: `2026-09-21` (pinned to the dataset snapshot for byte-stable reproduction)  
Dataset: `competitions/laliga/data/historical (2019/20-2023/24) + live seasons/2026_27`  
Method: `replay with historical.build_context_for_match (prior-only) and per-season pre-match Elo snapshots; no future-data leakage; production config reuses evaluate.py renormalized weights verbatim; market_only is the REAL phase-12A candidate: build_strategy_engine('market_only') evaluated via engine.evaluate()`  
Bootstrap: seed `20260601`, n_boot `2000`, `plain resample-by-match, paired over identical resamples, 95% percentile`.

## Headline: live LaLiga is 100% odds-absent

`pipeline.fetch_live_data()` writes row dicts with only `match_id/home_team/away_team/event_date/status/matchday/stage` — **no odds fields**. The shipped live season 2026/27 (`fixtures.json` = 380, `results.json` = 69 finished) contains 69 odds-absent matches. A `market_only` engine therefore emits **exact uniform (1/3,1/3,1/3) on every live match**. This changes the deployment story decisively and is the headline finding of this evaluation.

## Population A — ODDS-PRESENT (historical, has_odds = all 1900)

| model | n | log_loss | brier | ECE | accuracy | mean_conf | delta-LL vs production (95% CI) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Production (renormalized 4-signal) | 1900 | 1.0054 | 0.2006 | 0.0631 | 0.4889 | 0.5256 | — |
| MarketOnly (real build_strategy_engine) | 1900 | 0.9758 | 0.1937 | 0.0290 | 0.5332 | 0.5110 | 0.0295 [0.0185, 0.0409] |
| Uniform 1/3 | 1900 | 1.0986 | 0.2222 | 0.1120 | 0.4453 | 0.3333 | -0.0933 [-0.1137, -0.0726] |
| Freq (prior-succession base rates) | 1900 | 1.0791 | 0.2177 | 0.0268 | 0.4453 | 0.4221 | -0.0736 [-0.0894, -0.0582] |
| Elo only | 1900 | 1.0924 | 0.2168 | 0.1583 | 0.4863 | 0.6446 | -0.0868 [-0.1040, -0.0700] |

Coverage: `100% odds coverage — has_odds(m) true for all 1900 historical matches`. Delta sign is `production − model`; positive means the model is better than production.

## Population C — ALL (historical, == A)

`== population A: the historical dataset is 100% odds-covered, so 'all' and 'odds-present' coincide (n=1900). Reported separately for completeness; numbers are identical to A.` — identical numbers to Population A (n = 1900); no separate recompute is possible on this dataset.

## Population B — ODDS-ABSENT

Historical odds-absent matches: **0** — `The historical dataset has ZERO odds-absent matches (100% odds coverage). No synthetic odds-less population is fabricated; the genuine odds-absent deployment population is the live 2026/27 season, reported as behavior/fallback evidence (never scored).`

### Live 2026/27 deployment population — behavior/fallback evidence (n=69, all odds-absent)

- fixtures `380`, finished `69`, unplayed `311`, odds-absent `69`, odds-present `0`.

- **production** (5-signal engine via `build_signal_engine(strategy='production')`): 69 distinct blended outputs over 69 matches, `all_uniform=False`. The `market_odds` contribution is exact uniform (weight 0.3); `squad_value` and `rolling_form` sit at their no-data constants; `refined_elo`/`rest_days` carry the lean. Example match output: `{'home': 0.474534, 'draw': 0.307826, 'away': 0.21764}`.

- **market_only** (`build_strategy_engine('market_only')`): `distinct_outputs=1`, `all_uniform=True` — **exact (1/3,1/3,1/3) on all 69**. Example output: `{'home': 0.333333, 'draw': 0.333333, 'away': 0.333333}`.

- Determinism (two fresh engine instances, identical output incl. breakdown): `{'production_identical_across_two_engine_instances': True, 'market_only_identical_across_two_engine_instances': True, 'production_breakdown_identical': True, 'market_only_breakdown_identical': True}`.

- `BEHAVIOR / FALLBACK EVIDENCE ONLY — outputs above are NOT scored against outcomes (no pre-kickoff frozen predictions exist for LaLiga; retroactive prediction creation is forbidden this phase).`

## Fallback comparison (Phase 12B)

**1. market_only where odds exist** — n=1900, LL 0.9758, Br 0.1937, ECE 0.0290, acc 0.5332, conf 0.5110
**2. production's existing fallback when odds absent** — live behavior — MarketOddsSignal contribution degrades to exact uniform (weight 0.3) inside the 5-signal blend; the other four signals carry on (see populations.B_odds_absent.live.production)
**3. natural neutral/prior fallback = exact uniform** — MarketOddsSignal.predict() returns (1/3,1/3,1/3) on missing/invalid odds (football_core/signals/market_odds.py:44-49) — deterministic, prior-only, never fabricates, provenance-preserving, independently testable; identical to what market_only emits live.

**Verdict**: On the live odds-absent population, mechanism 1 and mechanism 3 produce byte-identical outputs (exact uniform) because market_only's sole signal degrades to the uniform fallback; mechanism 2 (production) continues to blend the four non-market signals with the market component pinned to uniform. Rationale is evidence-based (fallback_checks), not gate-driven.

## Per-season production vs market_only (Phase 12D)

| season | n | prod LL | mkt LL | prod Br | mkt Br | prod ECE | mkt ECE | delta-LL (prod−mkt) | 95% CI | CI width |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019_20 | 380 | 1.0132 | 0.9808 | 0.2025 | 0.1955 | 0.0778 | 0.0312 | +0.0324 | [0.0060, 0.0577] | 0.0518 |
| 2020_21 | 380 | 1.0139 | 0.9836 | 0.2024 | 0.1948 | 0.0371 | 0.0538 | +0.0303 | [0.0027, 0.0553] | 0.0526 |
| 2021_22 | 380 | 1.0107 | 0.9859 | 0.2019 | 0.1957 | 0.0968 | 0.0507 | +0.0248 | [0.0013, 0.0484] | 0.0471 |
| 2022_23 | 380 | 0.9972 | 0.9797 | 0.1986 | 0.1944 | 0.0387 | 0.0385 | +0.0175 | [-0.0074, 0.0421] | 0.0495 |
| 2023_24 | 380 | 0.9922 | 0.9488 | 0.1977 | 0.1880 | 0.0956 | 0.0516 | +0.0434 | [0.0210, 0.0660] | 0.0450 |

- **Direction** (monotone): market_only has lower LL in every season (all production-market deltas positive).
- **Single-season significance**: the per-season bootstrap CIs exclude zero for 2019_20, 2020_21, 2021_22 and 2023_24, but **2022_23** includes zero (CI `[-0.0074, 0.0421]`) — the smallest per-season effect is not significant on its own.
- **Magnitude**: per-season deltas {'2019_20': 0.032405, '2020_21': 0.030347, '2021_22': 0.024787, '2022_23': 0.017522, '2023_24': 0.043396} vs pooled point delta `+0.0297` (equal n ⇒ pooled == mean of per-season deltas).
- **Dominance**: no single season carries the pooled effect alone. Largest contributor `2023_24` (share 0.2923), smallest `2022_23` (share 0.118).
- **CI width per season**: each CI spans roughly the widths shown above; the 2023_24 delta is biggest while 2022_23 is smallest, and production's pooled CI (see bootstrap_cis.json) still excludes zero.

## Live 2026/27 — current-season check (Phase 12E)

Completed `69`, unplayed `311`, odds-absent `69`. **INSUFFICIENT EVIDENCE** (`True`): No pre-kickoff frozen predictions exist for LaLiga live matches and there is no LaLiga shadow store (the UCL shadow store exists and stays untouched). Without pre-kickoff frozen predictions, scoring the 69 completed live matches would require retroactive prediction creation, which the phase forbids — so live 2026/27 is INSUFFICIENT EVIDENCE for any model ranking. Nothing was tuned from it.

## Cross-checks vs Phase 11 artifacts

- pooled market_only log_loss: ours `0.975754` vs phase11 `0.975754` (abs_diff 0.00e+00)
- pooled elo_only log_loss: ours `1.092397` vs phase11 `1.092397` (abs_diff 0.00e+00)
- pooled uniform log_loss: ours `1.098612` vs phase11 `1.098612` (abs_diff 0.00e+00)
- per-season 2019_20 production log_loss: ours `1.013182` vs phase11 `1.013182` (abs_diff 0.00e+00)
- per-season 2019_20 market_only log_loss: ours `0.980778` vs phase11 `0.980778` (abs_diff 0.00e+00)
- per-season 2020_21 production log_loss: ours `1.013925` vs phase11 `1.013925` (abs_diff 0.00e+00)
- per-season 2020_21 market_only log_loss: ours `0.983578` vs phase11 `0.983578` (abs_diff 0.00e+00)
- per-season 2021_22 production log_loss: ours `1.010662` vs phase11 `1.010662` (abs_diff 0.00e+00)
- per-season 2021_22 market_only log_loss: ours `0.985875` vs phase11 `0.985875` (abs_diff 0.00e+00)
- per-season 2022_23 production log_loss: ours `0.997219` vs phase11 `0.997219` (abs_diff 0.00e+00)
- per-season 2022_23 market_only log_loss: ours `0.979697` vs phase11 `0.979697` (abs_diff 0.00e+00)
- per-season 2023_24 production log_loss: ours `0.992237` vs phase11 `0.992237` (abs_diff 0.00e+00)
- per-season 2023_24 market_only log_loss: ours `0.948841` vs phase11 `0.948841` (abs_diff 0.00e+00)
- pooled delta (production − market_only): ours `{'delta_ll': 0.029525, '2.5': 0.018461, '97.5': 0.040917}` vs phase11 `{'delta_ll': 0.029525, '2.5': 0.018461, '97.5': 0.040917}` — Phase 11 bootstrap used the BARE MarketOddsSignal for market_only; this run uses build_strategy_engine('market_only'), so tiny differences must come only from the engine's 6-dp output rounding.
- ECE note: point ECE via metrics_from -> multi_class_ece (10 bins); bootstrap_cis previously stored ece via pooled_metrics/ece_points, which can differ at ~1e-5 from pure float accumulation — both conventions are reported where used.

## Deployment implications

- **Live odds ingestion**: fetch_live_data() (pipeline.py:431-450) builds row dicts with ONLY match_id/home_team/away_team/event_date/status/matchday/stage — no odds fields; the 2026/27 fixtures (380) and results (69) contain no odds for any match, so the live deployment population is 100% odds-absent.
- **Promoting market_only today**: build_strategy_engine('market_only') contains exactly one MarketOddsSignal weighted 1.0; on every live match it emits exact (1/3,1/3,1/3). Promoting market_only now therefore means uniform predictions on every live match.
- **Historical superiority scope**: market_only's historical superiority (pooled delta production - market_only = +0.0295, 95% CI exclusively positive) holds ONLY on the fully odds-covered historical population — it says nothing about an odds-absent population.
- **Promotion meaningfulness**: Promotion of market_only as the live engine is only meaningful if/when live odds are ingested, which requires a pipeline change (fetch_live_data must populate odds fields from the provider) — OUT OF SCOPE for this phase.
