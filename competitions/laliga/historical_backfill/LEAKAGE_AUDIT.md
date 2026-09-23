# Phase 11 — LaLiga Historical Evaluation: Leakage Audit

**Auditor:** Agent B (Phase 11 integrity audit) · **Date:** 2026-09-22
**Scope:** 5-signal ensemble (rolling_form, rest_days, squad_value, market_odds,
refined_elo) evaluated out-of-sample on `competitions/laliga/data/historical/`
seasons 2019/20–2023/24 (1900 matches).
**Invariant under audit:** only strictly-earlier information may influence a
prediction — a target match must never see itself, same-kickoff siblings, or
any later match.
**Auditee code (READ-ONLY, not modified):** `competitions/ucl/src/historical.py`
(re-exported by `competitions/laliga/src/historical.py`),
`football_core/signals/{rolling_form,rest_days,market_odds,refined_elo}.py`,
`football_core/blender.py`, `competitions/laliga/historical_backfill/evaluate.py`.

## 1. Methodology

1. **Code reading** of all context-construction and evaluation paths (the
   chronological-key machinery, the replay provider, each signal's input
   channel, the ensemble weight fit, the frequency baseline windows).
2. **Empirical verification** across **all 1900 matches** of
   `replay_2019_20_2023_24.json` and the per-season `matches.json` /
   `elo_ratings.json` files via a throwaway script (temp dir, not committed):
   strict-before prior windows, same-date exclusion, form sensitivity, market
   odds provenance, Elo snapshot constancy, weight-fit and frequency-baseline
   window disjointness.
3. **Adversarial synthetics** (same team at the same kickoff in two matches,
   match_id collision, homogeneous-format/timezone edge, absent anchor) —
   none of which occur in the real LaLiga data (verified: 0 same-kickoff
   siblings, 0 duplicate match_ids, all dates ISO-UTC `…Z`) but all of which
   the machinery must tolerate without leaking.
4. **Regression tests** covering every invariant, committed at
   `competitions/laliga/tests/test_historical_leakage.py` (13 tests, all pass
   via `$env:PYTHONPATH="."; python -m pytest competitions/laliga/tests/test_historical_leakage.py -q`).

## 2. Per-signal verdicts

| Component | Verdict | Evidence |
|---|---|---|
| — context construction (`prior_matches` / `build_context_for_match`) | **PASS** | strict `<` key compare at `ucl/src/historical.py:161`; fixtures/played_results built only from `prior` at `ucl/src/historical.py:180-188` |
| — chronology (`chronological_key` / `order_matches`) | **PASS** | event_date is the sole ordering key for all 1900 matches (`ucl/src/historical.py:117-123`; homogeneous ISO-UTC `…Z`, monotonic in the pool) |
| `rolling_form` | **PASS** | `ReplayResultProvider.get_team_results` excludes `event_date >= before_date` at `ucl/src/historical.py:103`; result list sorted by event_date, not position (`:106`); anchor = target event_date (`football_core/signals/rolling_form.py:57`) |
| `rest_days` | **PASS** | strict `event_date < match_date` filter at `football_core/signals/rest_days.py:28`; a same-date match does not count as a rest opportunity (returns default 7) |
| `market_odds` | **PASS** | reads odds only from the target match dict (`football_core/signals/market_odds.py:23-38`); `odds_known_at == event_date` for all 1900 matches, set at `historical_backfill/sources/results_fd.py:123`; no odometer / look-back anywhere |
| `refined_elo` | **PASS** | reads only `context.elo_ratings`, a **fixed per-season snapshot** strictly before the season's first match (`historical_backfill/sources/elo_clubelo.py:95`, `:100`); never updated with in-season outcomes (verified identical outputs for same team pair across a season) |
| `squad_value` | **PASS (not applicable)** | no historical data source exists, so it is excluded (renormalized away) in `evaluate.py:22`/`evaluate.py:84-89`; it is never fitted, so it cannot leak |
| ensemble weights (`compute_log_loss_weights`) | **PASS** | pure deterministic function (`football_core/blender.py:23-47`), no global/random state; `EnsembleEngine.weights` resolved at construction only |
| weight-fit windows (`weights_learned`) | **PASS** | fit pool is **strictly prior seasons** only: `for prev in SEASONS[:i]` at `evaluate.py:395`; eval season never touched by the fit (`evaluate.py:418-421`); train pool = 380·n prior seasons, verified disjoint from eval match_ids |
| frequency baseline | **PASS** | constant base rates computed only on a strictly-earlier 70% window: per-season `frequency_baseline(fit_m)` at `evaluate.py:256-259`, pooled `frequency_baseline(pfit)` at `evaluate.py:340-343`; the current/later OOS match is never in its own baseline | 
| global/network state | **PASS** | no `random`/`np.random`/seed, no in-season refit, no list-sort side-channel: the only ordering is `order_matches` keyed by date |

## 3. Confirmed invariants with evidence (the two that matter most)

1. **Strict-before prior window.** For every target, `prior_matches` compares
   chronological keys with `<`, so the target, its same-kickoff siblings, and
   every later match are excluded: `ucl/src/historical.py:161`; the same
   guarantee applies to the replay provider used by rolling form:
   `ucl/src/historical.py:103`. Verified on all 1900 matches (every prior
   `event_date` < target `event_date`; zero same-date entries in prior /
   fixtures / played_results / provider rows).
2. **Weight fit never touches the eval season.** `evaluate.py:395`
   (`for prev in SEASONS[:i]`) fits each target season `SEASONS[i]` only on
   the strictly-prior pool; `train_pool_n == 380·i` and the fit pool and eval
   season match_ids are disjoint (test `test_weights_fit_uses_only_prior_seasons`).

## 4. Findings turned into tests

`competitions/laliga/tests/test_historical_leakage.py` (13 tests, all passing):

1. `test_context_is_strictly_before_across_dataset`
2. `test_no_same_date_matches_in_context`
3. `test_replay_provider_orders_by_event_date_not_position`
4. `test_rest_days_excludes_same_date_match`
5. `test_market_odds_no_lookahead`
6. `test_form_changes_after_removing_prior_result`
7. `test_weights_fit_uses_only_prior_seasons`
8. `test_frequency_baseline_excludes_self`
9. `test_two_matches_same_team_same_kickoff_no_crossover` (adversarial)
10. `test_elo_snapshot_constant_across_season` (adversarial)
11. `test_match_id_collision_self_exclusion` (adversarial)
12. `test_dataset_dates_are_homogeneous_iso_utc` (adversarial / timezone-id edge)
13. `test_provider_empty_or_absent_anchor_returns_nothing` (adversarial)

## 5. Residual caveats

- **No actual leak found.** Chromology relies on **lexicographic comparison of
  homogeneous ISO-UTC timestamps**. All 1900 records are `…T…Z` and time-ordered
  (guarded by test 12); a future backfill emitting a different ISO variant
  (date-only, non-Z, mixed `+HH:MM` offsets) would silently mis-order strict-before
  windows. `results_fd.py:75-94` converts Europe/Madrid local times to UTC to keep
  this true.
- `rolling_form` consumes history via the **result-provider channel**, not
  `context.played_results`; sensitivity must therefore be tested through the
  provider (test 6 does this).
- A match with a missing `event_date` would fall back to matchday/position
  ordering (`ucl/src/historical.py:122-123`) and would not be safely orderable —
  currently impossible (all 1900 have dates); no match is excluded from `rest_days`
  ordering.
- At the time of this audit `competitions/laliga/data/historical/` was **untracked** in git and
  the then-current `evaluation/eval_results.json` was a stale artifact (missing the
  `weights_source` field now written by `evaluate.py:421`). The audit verified against
  working-tree data; the post-rebuild `eval_results.json` (generated 2026-09-22, containing
  `weights_source`) is verified in `MARKET_ONLY_AUDIT.md` §1e and committed with this cleanup.

## 6. Conclusion

**Verdict: PASS — no leakage found.** Every signal consumes only strictly-earlier
information; weight fits and frequency baselines are confined to strictly-prior
windows; no global/random/in-season state exists. All invariants are locked in by
the 13 committed regression tests.