# LaLiga Out-of-Sample Evaluation — Independent Verification (Phase 11)

Verified by Agent C (independent throwaway verification script, temp dir, not committed) against
`competitions/laliga/data/historical/evaluation/eval_results.json` (generated 2026-09-22 by
`competitions/laliga/historical_backfill/evaluate.py`). No files under `data/` were modified;
results confirm the published numbers **exactly** (all deltas ≤ 6 dp).

## Method

Independent pipeline, not a re-run of `evaluate.py` and not a call to `EnsembleEngine`:

1. **Own replay loop** per season: prior-only context via
   `build_context_for_match(match, season_matches, elo_ratings=season_elo)` (leak-free ordering
   from `event_date`), all 380 completed matches × 5 seasons = n = 1900.
2. **Own signal math wherever possible**: market probabilities recomputed inline from raw
   `odds_*` via the `1/odds → normalize` vig-removal formula; Elo recomputed inline from
   `football_core.elo.expected_score(..., home_advantage=100)` + the
   `draw = max(0, 1 − |hp − 0.5|·2)·0.35` heuristic; the ensemble blended by my own weighted-sum
   arithmetic over the 4 active signals with production weights renormalized over
   market_odds/refined_elo/rolling_form/rest_days (squad_value excluded). Rolling-form/rest-days
   signal output obtained from the production signal classes.
3. **Metrics**: the canonical `multi_class_log_loss` / `multi_class_brier` / `multi_class_ece`
   from `football_core/evaluation.py` (label order home=0/draw=1/away=2; accuracy = argmax
   match; ECE = confidence-vs-accuracy, adaptive bins).
4. **Independent cross-checks**: `sklearn.metrics.log_loss` on market-probs and uniform; pool-wide
   and per-season frequency baselines recomputed from raw outcome counts; per-match uniform
   reference `ln 3 = 1.0986122886681098`.
5. Window splits reproduced independently: within-season `round(380·0.7) = 266` fit / 114 eval;
   pooled chronological `round(1900·0.7) = 1330` fit / 570 eval.

## Population

| Season | n | odds n | elo-covered n | my counts |
|---|---|---|---|---|
| 2019/20–2023/24 | 380 each | 380 each | 380 each | identical |
| **All** | **1900** | **1900** | **1900** | **identical** |

Every match has Pinnacle odds and both teams in the season Elo map (`odds_n == elo_covered_n == 1900`), so full-pool, odds-pool and elo-covered-pool are the same population.

## Per-check table (LL = multi-class log-loss; Δ = |recomputed − claimed|)

| # | Check | Recomputed | Claimed | Δ | Verdict |
|---|---|---|---|---|---|
| 1 | Pooled uniform LL (n=1900) | 1.098612 | 1.098612 | 0.000000 | **PASS** (≡ ln 3) |
| 2 | Pooled uniform accuracy | 0.445263 (846/1900) | 0.445263 | 0.000000 | **PASS** |
| 3 | Pooled uniform Brier | 0.222222 | 0.222222 | 0.000000 | **PASS** |
| 4 | Pool window freq LL (fit 1330 → eval 570) | 1.062449 | 1.062449 | 0.000000 | **PASS** |
| 5 | Pool window freq accuracy | 0.466667 | 0.466667 | 0.000000 | **PASS** |
| 6 | Pool window freq_dist (H/D/A) | .436090/.278947/.284962 | same | 0 | **PASS** |
| 7 | Pool window ensemble LL | 0.990224 | 0.990224 | 0.000000 | **PASS** |
| 8 | Pool window elo-only LL | 1.065261 | 1.065261 | 0.000000 | **PASS** |
| 9 | Pooled elo-only LL (n=1900) | 1.092397 | 1.092397 | 0.000000 | **PASS** |
| 10 | Pooled market-odds LL (odds_n=1900) | 0.975754 | 0.975754 | 0.000000 | **PASS** |
| 11 | Pooled market accuracy (sanity ~0.53) | 0.533158 | 0.533158 | 0.000000 | **PASS** |
| 12 | Pooled market Brier / ECE | 0.193663 / 0.029002 | 0.193663 / 0.029002 | 0 | **PASS** |
| 13 | Pooled ensemble LL / Brier / ECE | 1.005445 / 0.200626 / 0.063070 | 1.005445 / 0.200626 / 0.063070 | 0 | **PASS** |
| 14 | Pooled ensemble accuracy | 0.488947 | 0.488947 | 0.000000 | **PASS** |
| 15 | sklearn market LL (independent implementation) | 0.975754 | 0.975754 | 0.000000 | **PASS** |
| 16 | sklearn uniform LL | 1.098612 | 1.098612 | 0.000000 | **PASS** |
| 17 | Per-season ensemble LL ×5 | 1.013182/1.013925/1.010662/0.997219/0.992237 | identical | 0 | **PASS** |
| 18 | Per-season elo-only LL ×5 | 1.108036/1.106945/1.094620/1.075269/1.077113 | identical | 0 | **PASS** |
| 19 | Per-season market LL ×5 | 0.980778/0.983578/0.985875/0.979697/0.948841 | identical | 0 | **PASS** |
| 20 | Per-season window freq LL ×5 | 1.105443/1.077618/1.089460/1.016239/1.086757 | identical | 0 | **PASS** |
| 21 | Per-season window freq_dist ×5 | bit-for-bit | identical | 0 | **PASS** |
| 22 | Counts (window n_fit/n_eval; season n; odds n) | 1330/570; 380; 380 | identical | 0 | **PASS** |

**Result: every headline number in `eval_results.json` is reproduced exactly.** No discrepancy
exceeds 1e-6 (let alone the 1e-4 / 1e-3 thresholds). The published ensemble LL 1.005445
beats uniform (1.098612) and Elo-only (1.092397); market-odds-only (0.975754, acc 0.533) is the
strongest single signal and beats the ensemble on the identical population — both consistent
with the original claims.

## Anomaly found (no impact on results, but a latent risk)

**Windows text-encoding fragility in the historical loaders.** Both `matches.json` and
`elo_ratings.json` are UTF-8; non-ASCII accents (e.g. "Real Sociedad de **Fút**bol",
"Atlético", "Alavés") decode to mojibake under cp1252, the Windows default text encoding
(`locale.getpreferredencoding(False) == 'cp1252'`, no `PYTHONUTF8`/`PYTHONIOENCODING` set).
`evaluate.py` opens **both** files with the default encoding through `load_replay_matches`
(`with open(path)`) and `json.load(f)`, so both sides mangle *consistently* → team→Elo lookups
still resolve and all numbers are correct (measured: consistent-mangling Elo LL = 1.092397,
0 fallbacks — identical to clean UTF-8).

However, if any single reader forces `encoding="utf-8"` while the other remains default, the team
keys silently stop matching and `RefinedEloSignal` falls back to `DEFAULT_ELO` (1500) with **no
warning**. I reproduced this inside my first verification pass (elo file as UTF-8, matches as
default): 494/1900 matches hit the fallback and the Elo-only LL degraded 1.092397 → **1.203449**
(mean confidence 0.645 → 0.659), with the ensemble pulled to 1.019609. This was a bug in *my*
harness, not in `eval_results.json`, but the failure mode is invisible and measureable, so any
future pipeline that mixes encodings will silently corrupt every Elo-dependent aggregate.

Fix if desired: read both files with explicit `encoding="utf-8"` (or set `PYTHONUTF8=1`) in
`competitions/ucl/src/historical.py:load_replay_matches` and the elo loader in
`Competitions/laliga/historical_backfill/evaluate.py`, keeping both sides identical.

## Verdict

**All checks PASS.** Publication `eval_results.json` is an accurate leak-free evaluation of the
LaLiga historical backfill: ensemble regression LL 1.005445 (BEATS uniform and Elo-only, loses to
the raw market on all-odds data) is correct and stable across all five seasons.