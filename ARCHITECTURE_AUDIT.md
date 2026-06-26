# Architecture Audit — worldcup_predictor

> Generated: 2026-06-26  
> Mode: Read-only — every `.py` file under `src/` and `main.py` was read completely.  
> No code was modified, moved, or deleted.

---

## 1. Architecture Overview

### Project Layers

```
┌──────────────────────────────────────────────────────────────────┐
│                      main.py (1545 lines)                        │
│  CLI parsing, startup orchestration, continuous polling loop     │
│  ⚠ Contains SIGNIFICANT business logic (God Object smell)       │
├──────────────────────────────────────────────────────────────────┤
│                       src/predictors/                            │
│  odds.py │ catboost.py │ form.py │ lineup.py                     │
│  Signal ingestion/computation — each produces a cache dict       │
├──────────────────────────────────────────────────────────────────┤
│              src/ — Core Domain Modules                           │
├──────────┬──────────┬──────────┬──────────┬──────────┬───────────┤
│ elo.py   │ groups   │ knockout │ blender  │ evaluation│governance │
│ (182 L)  │ (907 L)  │ (347 L)  │ (528 L)  │ (445 L)   │ (589 L)   │
├──────────┴──────────┴──────────┴──────────┴──────────┴───────────┤
│                   src/ — Infrastructure                           │
├──────────┬──────────┬──────────┬─────────────────────────────────┤
│ state.py │ fetcher  │ elo_sync │ enrichment.py                   │
│ (1139 L) │ (402 L)  │ (370 L)  │ (93 L)                         │
├──────────┴──────────┴──────────┴─────────────────────────────────┤
│                      src/constants.py (267 lines)                 │
│  All magic numbers, URLs, thresholds, file names, team codes      │
├──────────────────────────────────────────────────────────────────┤
│                         data/*.json                               │
│  6 source files (teams, groups, annex_c, aliases, values,        │
│  bracket) + 14+ generated files (caches, logs, histories)        │
└──────────────────────────────────────────────────────────────────┘
```

### Execution Flow (startup → polling)

```
main()
│
├─ _parse_args()                         CLI → Namespace
├─ _resolve_league_id()                  config.json → league_id
├─ load_dotenv()                         BSD_API_KEY from .env
│
├─ _migrate_legacy_data()                data/ → data/<league_id>/
├─ _merge_probability_log()              data/ → data/27/ merge
│
├─ state.load_*()                        6 JSON files loaded
├─ validate_api_key()                    HTTP GET leagues/ endpoint
├─ state.load_aliases()
│
├─ _run_historical_catch_up()            ──┐
│   fetch_raw_matches()                     │ Startup: fetch all
│   process_group_matches()                 │ finished matches
│   process_matches()                       │ from tournament start
│   elo.apply_elo_update()                ──┘
│
├─ _run_draw_backfill()                  One-shot draw Elo fix
├─ _record_eval_baseline()               Brier/log-loss baseline
├─ migrate_prediction_history()          Flat→compound format
│
├─ fetch_and_cache_catboost()            Seed CatBoost cache
├─ _merge_signals_into_history()         Ledger → history merge
├─ compute_poisson_base_rate()           Warm cache
├─ _run_elo_sync()                       Elo sync from eloratings.net
│
├─ _run_governance(startup=True)         Backtest, baseline init
│
├─ [--once] _run_iteration() + exit       Single shot
│
├─ signal handlers                       SIGINT/SIGTERM/SIGBREAK
│
├─ while _running:                        ── Continuous poll loop ──
│   _next_poll_sleep(POLL_INTERVAL)         │
│   _run_iteration()                        │ See next section
│                                          ──────────────────────
│
└─ Shutdown: re-simulate + print_banner
```

### Prediction Pipeline (one `_run_iteration()` cycle)

```
_run_iteration()
│
├── 1. Periodic Elo sync check (24h)
├── 2. Staleness warning check
├── 3. Rate limiter sleep
├── 4. Hourly re-sim check (if no new matches)
│
├── 5. fetch_raw_matches()                   ← BSD API
├── 6. process_matches()                     ← new knockout results
│      ├── elo.apply_elo_update()            ← update Elo ratings
│      └── state.save_*()                    ← persist
│
├── 7. process_group_matches()               ← new group results
│      ├── elo.apply_elo_update()            ← update Elo
│      └── state.save_*()                    ← persist
│
├── 8. Create prediction_history entries     ← for new matches
│      └── state.append_prediction_history()
│
├── 9. Refresh signal caches
│      ├── odds_cache (from existing events — no extra API call)
│      ├── catboost_cache (dedicated API call)
│      ├── form_cache (local computation)
│      └── lineup_cache (local computation)
│
├── 10. Build xG overrides from CatBoost cache
├── 11. _merge_signals_into_history()        ← ledger → history
├── 12. _run_calibrate_and_blend()           ← blender.py
├── 13. Version tracking (_maybe_update_versions)
├── 14. Signal unavailability warnings
├── 15. _run_governance() if due
│
├── 16. run_full_simulation()                ← 50K Monte Carlo
│         ├── groups.simulate_group_matches()
│         ├── groups.compute_standings()
│         ├── groups.rank_third_placed()
│         ├── groups.select_advancers()
│         ├── groups.resolve_r32_matchups()
│         ├── knockout._simulate_r32_resolved()
│         ├── knockout._simulate_r16()
│         ├── knockout._simulate_knockout_round() (QF, SF)
│         ├── knockout._simulate_tpp()
│         └── knockout._simulate_knockout_round() (FINAL)
│
├── 17. Display: print_*() functions
│         ├── print_simulation_duration()
│         ├── print_group_standings()
│         ├── print_third_place_bubble()
│         ├── print_probability_table()
│         ├── print_ai_previews()
│         ├── print_delta_summary()
│         └── print_*() (match detail, focus card)
│
├── 18. state.append_probability_log()       ← trend tracking
└── 19. Print match detail / focus card       ← if --match-detail
```

### Module Interaction / Dependency Graph

```
main.py ─────────────────────────────────────────────────────────────────┐
 │                                                                       │
 ├──► constants.py                  (URLs, K_FACTOR, DATA_DIR, ...)     │
 ├──► state.py                      (persistence: load/save 20+ files)  │
 │      ├──► constants.py                                                │
 │      └── (no others)                                                  │
 ├──► elo.py                        (expected_score, update_ratings)     │
 │      └──► constants.py                                                │
 ├──► elo_sync.py                   (fetch TSV → parse → validate →      │
 │      ├──► state.py                resolve → correct → persist)        │
 │      └──► constants.py                                                │
 ├──► fetcher.py                    (BSD API fetch, process matches)     │
 │      ├──► constants.py                                                │
 │      └──► enrichment.py                                               │
 ├──► groups.py                     (Poisson sim, tiebreaker, Annex C)   │
 │      ├──► constants.py                                                │
 │      └──► blender.py (compute_poisson_base_rate)                      │
 ├──► knockout.py                   (bracket sim orchestrator)           │
 │      ├──► elo.py                                                      │
 │      └──► groups.py (6 functions imported)                            │
 ├──► blender.py                    (Platt scaling, Brier blending)      │
 │      ├──► elo.py                                                      │
 │      └── (stdlib only: math, json)                                    │
 ├──► evaluation.py                 (Brier, log loss, calibration)       │
 │      ├──► elo.py                                                      │
 │      └──► state.py (I/O: load/save prediction_history)                │
 ├──► governance.py                 (version tracking, drift)            │
 │      ├──► evaluation.py                                               │
 │      ├──► blender.py                                                  │
 │      ├──► state.py                                                    │
 │      └──► constants.py                                                │
 ├──► enrichment.py                 (stats/context extraction)           │
 ├──► output.py                     (display, ANSI formatting)           │
 │      ├──► constants.py                                                │
 │      └──► elo_sync.py (get_staleness_level)                           │
 │                                                                       │
 └──► predictors/                                                        │
        ├── odds.py                                                      │
        │     └──► constants.py, fetcher._* (3 private functions)        │
        ├── catboost.py                                                  │
        │     └──► constants.py, fetcher._* (3 private functions)        │
        ├── form.py                                                      │
        │     └──► constants.py, elo.py, state.py                       │
        └── lineup.py                                                    │
              └──► constants.py, state.py                                │
```

---

## 2. Module Review

### 2.1 `main.py` (1545 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | CLI entry point, startup orchestration, continuous polling loop, data migration, signal cache orchestration, governance trigger |
| Public interface | `main()` only |
| Dependencies | All modules — deeply coupled to everything |
| Cohesion | **Low** — mixes CLI parsing, I/O, business logic (Elo update, prediction history creation, signal blending), display, and migration |
| Coupling | **Extreme** — imports internal/private functions from fetcher (`_find_bracket_match` NOT imported directly but imports `process_matches` which uses them; actually imports from `knockout`, `output`, `elo`, `state`, `blender`, `governance`, `evaluation`, `predictors/odds`, `predictors/catboost`, `predictors/form`, `predictors/lineup`) |
| Complexity | **High** — `_run_iteration()` is ~400 lines, `_run_historical_catch_up()` is ~130 lines |

**Verdict: SPLIT** — God Object. Main currently owns:
- Data migration (`_migrate_legacy_data`, `_merge_probability_log`)
- Signal orchestration (`_run_calibrate_and_blend`, `_merge_signals_into_history`, `_gather_signal_data`)
- Iteration orchestration (`_run_iteration`)
- Historical catch-up (`_run_historical_catch_up`)
- Business logic (`_expected_score_for_match` duplicates `elo.expected_score`)
- Display orchestration (`_compute_group_display`)

---

### 2.2 `state.py` (1139 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Persistence layer: load/save 20+ JSON files, atomic writes, bracket validation, Annex C validation, group validation, data migration |
| Public interface | 30+ public functions |
| Dependencies | `constants.py` only |
| Cohesion | **Low** — three concerns in one file: (1) file I/O, (2) validation logic, (3) data migration |
| Coupling | **Low** — depends only on constants, but is depended on by nearly every module |
| Complexity | Medium — validation functions (validate_bracket, validate_annex_c, validate_groups) are well-structured but co-located with simple getters/setters |

**Key finding:** `validate_groups`, `validate_annex_c`, `validate_bracket` are pure validation logic (no I/O) living inside a persistence module. They are called by `load_groups`, `load_annex_c`, `load_bracket` which ARE I/O. The dual responsibility makes it impossible to validate without loading.

**Verdict: SPLIT** — extract `validate_groups`, `validate_annex_c`, `validate_bracket` (and `migrate_prediction_history`) into separate module(s). Keep `state.py` as pure persistence.

---

### 2.3 `constants.py` (267 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Centralized configuration: URLs, directory paths, magic numbers, team code mappings |
| Public interface | All module-level constants + 2 URL builder functions |
| Dependencies | `os`, `pathlib` |
| Cohesion | **High** — all constants, one concern |
| Coupling | **Low** — no imports from project modules |
| Complexity | Low |

**Verdict: KEEP**

---

### 2.4 `elo.py` (182 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Pure Elo rating engine: expected score, K-factor multiplier, rating update |
| Public interface | `expected_score()`, `compute_k_factor()`, `update_ratings()`, `apply_elo_update()` |
| Dependencies | `constants.py`, `math` |
| Cohesion | **High** — all Elo math, no I/O |
| Coupling | **Low** |
| Complexity | Low |

**Verdict: KEEP**

---

### 2.5 `elo_sync.py` (370 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Elo sync pipeline: fetch TSV from eloratings.net, parse, validate, resolve team names, apply graduated corrections, persist |
| Public interface | `sync_elo_from_eloratings()`, `get_staleness_level()` |
| Dependencies | `state.py`, `constants.py`, `requests`, `csv` |
| Cohesion | **High** — single pipeline, well-structured with helper functions |
| Coupling | **Medium** — depends on state.py for persistence |
| Complexity | Medium |

**Verdict: KEEP**

---

### 2.6 `fetcher.py` (402 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | BSD API HTTP layer: fetch events, process/filter matches, normalize team names, extract enrichment data |
| Public interface | `fetch_raw_matches()`, `process_matches()`, `process_group_matches()` |
| Dependencies | `constants.py`, `enrichment.py`, `requests` |
| Cohesion | **Medium** — contains both HTTP fetch logic and team name normalization functions |
| Coupling | **Medium** — used by main.py, odds.py, catboost.py (latter two import private `_*` functions) |
| Complexity | Medium |

**Critical issue:** Three private functions (`_build_alias_lookup`, `_normalize_team`, `_find_bracket_match`, `_find_group_match`) are **imported and used by `odds.py` and `catboost.py`**. These are implementation details of `fetcher.py` but have become de facto shared utilities. This violates encapsulation.

**Verdict: REVIEW** — extract `_normalize_team`, `_build_alias_lookup`, `_find_bracket_match`, `_find_group_match` into a shared utility module (e.g., `team_utils.py` or `matching.py`).

---

### 2.7 `enrichment.py` (93 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Extract stats and context from raw BSD event dicts |
| Public interface | `extract_stats()`, `extract_context()` |
| Dependencies | (none beyond stdlib `logging`) |
| Cohesion | **High** — two extractors, single concern |
| Coupling | **Low** — depended on by fetcher.py |
| Complexity | Low |

**Verdict: KEEP**

---

### 2.8 `groups.py` (907 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Group stage simulation: Poisson score model, precomputed λ lookup, 7-step tiebreaker, standings computation, third-place ranking, Annex C R32 match resolution |
| Public interface | 10+ public functions |
| Dependencies | `constants.py`, `blender.py` (Poisson base rate), `math`, `random` |
| Cohesion | **Medium** — group simulation + tiebreaker + R32 resolution in one file |
| Coupling | **Medium** — imports from `blender.py` for `compute_poisson_base_rate()` |
| Complexity | **High** — tiebreaker logic is deeply recursive (7 steps + recursion depth guard) |

**Key finding:** `precompute_matchup_lambdas()` has a circular import risk with `blender.py` (groups imports blender, blender imports elo — no actual cycle, but blender → elo → nothing, groups → blender → elo. No cycle). But the dependency direction is odd: `groups.py` (simulation engine) importing from `blender.py` (signal fusion) is a layer violation. The Poisson base rate should come from constants or a separate math module, not from the blender.

**Potential SPLIT:** The tiebreaker functions (`_tiebreak_group`, `_resolve_tied_cluster`, `_resolve_by_values`, `_compute_h2h`, `_compute_conduct_score`) could be extracted into a separate module.

**Verdict: REVIEW**

---

### 2.9 `knockout.py` (347 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Full tournament simulation: R32 → R16 → QF → SF → TPP → FINAL orchestration, blended probability injection |
| Public interface | `run_full_simulation()`, `resolve_knockout_slot_teams()` |
| Dependencies | `elo.py`, `groups.py` (6 functions) |
| Cohesion | **High** — all knockout simulation, well-structured rounds |
| Coupling | **Medium** — depends on groups.py for multiple functions |
| Complexity | Medium — well-factored into round-specific helper functions |

**Verdict: KEEP**

---

### 2.10 `blender.py` (528 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Platt scaling calibration (Newton-Raphson), Brier-weighted blending, LOO-CV evaluation, Poisson base rate, orchestrator `calibrate_and_blend()` |
| Public interface | `calibrate_signal()`, `apply_calibration()`, `compute_rolling_brier()`, `compute_blend_weights()`, `blend_predictions()`, `loo_cv_blended_brier()`, `compute_poisson_base_rate()`, `calibrate_and_blend()` |
| Dependencies | `elo.py` (expected_score only), `math` |
| Cohesion | **Medium** — contains both low-level math (Platt scaling, sigmoid) and high-level orchestration (`calibrate_and_blend`) |
| Coupling | **Low** — depends only on elo.py |
| Complexity | **High** — Newton-Raphson optimization, LOO-CV, and the large `calibrate_and_blend()` orchestrator |

**Key finding:** `compute_poisson_base_rate()` reads from a file path — this is I/O in a module that claims (docstring line 8) to be "PURE computation. No file I/O." This is a documentation/contract violation.

**Verdict: REVIEW** — split `compute_poisson_base_rate()` out; consider splitting `calibrate_and_blend()` from the low-level math.

---

### 2.11 `evaluation.py` (445 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Brier score, log loss, calibration curve, ECE, multi-signal evaluation, backtesting, baseline comparison |
| Public interface | `brier_score()`, `log_loss()`, `compute_metrics()`, `calibration_curve()`, `expected_calibration_error()`, `evaluate_all_matches()`, `backtest_tournament()`, `compare_baselines()` |
| Dependencies | `elo.py`, `state.py` |
| Cohesion | **Low** — mixes pure metric computation (brier_score, log_loss) with I/O-bound orchestration (`evaluate_all_matches`, `backtest_tournament`) |
| Coupling | **Medium** — `evaluate_all_matches()` calls `state.load_prediction_history()` and `state.append_prediction_history()` — I/O mixed with computation |
| Complexity | High — `evaluate_all_matches` has 3 distinct code paths (None, "elo", other signal_name) |

**Verdict: SPLIT** — extract pure functions (brier_score, log_loss, compute_metrics, calibration_curve, ece) into a `metrics.py` module; keep I/O orchestration in `evaluation.py`.

---

### 2.12 `governance.py` (589 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Version tracking (data/model/run), drift detection, governance dashlet orchestration, backtesting |
| Public interface | `_run_governance()`, `_run_backtest()`, `check_drift()`, `compute_reference_baselines()`, plus 6 `_*` functions |
| Dependencies | `evaluation.py`, `blender.py`, `state.py`, `constants.py`, `output.py` |
| Cohesion | **Low** — mixes version tracking, drift detection, backtesting, and print display |
| Coupling | **High** — depends on 4 different modules including the output display layer |
| Complexity | High — `_run_governance()` and `_run_backtest()` do I/O, computation, and display |

**Key finding:** `_run_governance()` directly imports and calls `output.print_governance_dashlet()` — this couples governance logic to display format.

**Verdict: SPLIT** — extract display logic; separate version tracking from drift detection from backtesting.

---

### 2.13 `output.py` (952 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | All console output: probability tables, group standings, match alerts, Elo changes, sync results, governance dashlet, coverage audit, match detail, focus cards |
| Public interface | 20+ `print_*` functions |
| Dependencies | `constants.py`, `elo_sync.py` (get_staleness_level) |
| Cohesion | **Medium** — all display, but includes computation (Wilson CI, coverage audit) |
| Coupling | **Medium** — `print_governance_dashlet` knows about governance data structures; `coverage_audit()` is pure computation embedded in a display module |
| Complexity | Medium |

**Key finding:** `coverage_audit()` returns structured data — it's a pure computation function embedded in a display module. `wilson_score_ci()`, `format_ci()`, `wilson_ci_from_prob()` are pure math functions in a display module.

**Verdict: REVIEW** — extract `coverage_audit()`, `wilson_score_ci()`, `format_ci()`, `wilson_ci_from_prob()` into a more appropriate location. Keep print functions in output.py.

---

### 2.14 `predictors/__init__.py` (6 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Package docstring only — no registry, no imports |
| Dependencies | None |
| Cohesion | N/A (empty package) |
| Coupling | None |

**Verdict: KEEP** (needed for package structure)

---

### 2.15 `predictors/odds.py` (212 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Market odds ingestion: vig removal, odds parsing from BSD events, cache creation |
| Public interface | `remove_vig()`, `parse_odds_response()`, `fetch_and_cache_odds()` |
| Dependencies | `constants.py`, `fetcher.py` (imports 3 private functions) |
| Cohesion | **High** |
| Coupling | **Medium** — importing private functions from fetcher.py |
| Complexity | Low |

**Verdict: KEEP** (after extracting shared utilities from fetcher.py)

---

### 2.16 `predictors/catboost.py` (387 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | CatBoost prediction ingestion: BSD API fetch, response parsing, field-name fallback, xG extraction, cache creation |
| Public interface | `parse_catboost_response()`, `fetch_and_cache_catboost()` |
| Dependencies | `constants.py`, `fetcher.py` (imports 3 private functions) |
| Cohesion | **High** — single pipeline |
| Coupling | **Medium** — importing private functions from fetcher.py |
| Complexity | Medium |

**Verdict: KEEP** (after extracting shared utilities from fetcher.py)

---

### 2.17 `predictors/form.py` (356 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Form signal: Elo residual computation, per-team residual history, sigmoid conversion, cache creation |
| Public interface | `compute_form_signal()` |
| Dependencies | `constants.py`, `elo.py`, `state.py` |
| Cohesion | **High** — well-structured with `_build_team_residuals`, `_compute_match_form_signal`, `compute_form_signal` |
| Coupling | **Medium** — imports from state.py for auto-loading data |
| Complexity | Medium |

**Verdict: KEEP**

---

### 2.18 `predictors/lineup.py` (206 lines)

| Aspect | Assessment |
|--------|------------|
| Responsibility | Lineup strength signal: market value log-ratio, sigmoid conversion, cache creation |
| Public interface | `compute_lineup_signal()` |
| Dependencies | `constants.py`, `state.py` |
| Cohesion | **High** |
| Coupling | **Medium** — imports from state.py for auto-loading data |
| Complexity | Low |

**Verdict: KEEP**

---

## 3. Main Entry Analysis

### Is it orchestration only?
**No.** `main.py` contains significant business logic beyond orchestration:

1. **`_run_iteration()` (~400 lines)** — Contains the core iteration logic including Elo update application, prediction history creation, signal cache refresh logic, blend invocation, governance triggering, and display orchestration. This is NOT just wiring — it makes decisions about when to refresh caches, how to create history entries, and what to display.

2. **`_merge_signals_into_history()`** — Business logic: decides which signals to merge into which history entries based on availability. This is data fusion logic, not orchestration.

3. **`_gather_signal_data()`** — Duplicates the blending logic from `blender.py` using a different algorithm (sequential averaging instead of Brier-weighted blend). Contains the formula: `blended = elo_prob; if odds: blended = (blended + odds) / 2; if cb: blended = (blended + cb) / 2`. This is **different from** `blender.blend_predictions()` which uses proper Brier-weighted blending.

4. **`_expected_score_for_match()`** — Pure duplicate of `elo.expected_score()`.

5. **`_run_historical_catch_up()`** — Contains duplicate/altered versions of match processing logic that exists in `fetcher.py`. The PK shootout detection, team normalization, and winner logic are reimplemented here.

6. **`_compute_group_display()`** — Wraps groups.py functions with display-specific configuration (seed=0, fair_play=False). Thin wrapper, but still logic.

### Is it acting as a God Object?
**Yes.** Evidence:
- 1545 lines — largest file in the project
- Imports from every single module in the project
- Contains its own data structures (7 module-level globals with type annotations)
- Contains I/O logic, business logic, display logic, migration logic, and CLI parsing
- Contains duplicate implementations of existing module functions

### Should its responsibilities remain as-is?
**No.** The recommended split would be:
- `main.py` → pure CLI entry point + loop driver (< 200 lines)
- Extract a `pipeline.py` or `orchestrator.py` for `_run_iteration()`, `_run_calibrate_and_blend()`, `_merge_signals_into_history()`, `_gather_signal_data()`
- Extract a `migration.py` for `_migrate_legacy_data()`, `_merge_probability_log()`, `_run_draw_backfill()`
- Extract a `catchup.py` for `_run_historical_catch_up()`
- Remove `_expected_score_for_match()` in favor of `elo.expected_score()`
- Fix `_gather_signal_data()` to use `blender.blend_predictions()` instead of sequential averaging

---

## 4. Dependency Analysis

### 4.1 Circular Dependencies

| Cycle | Path | Risk |
|-------|------|------|
| `groups.py` → `blender.py` → `elo.py` | No cycle (groups → blender → elo) | Layer violation only |
| `evaluation.py` → `state.py` | No cycle (evaluation → state) | I/O in computation |
| `governance.py` → `evaluation.py` | No cycle | Acceptable |
| `governance.py` → `blender.py` | No cycle | Acceptable |
| `governance.py` → `state.py` → (nothing back) | No cycle | Acceptable |

**No actual circular dependencies detected.** However, the dependency from `groups.py` (simulation) to `blender.py` (signal processing) is architecturally inverted: the simulation engine should not depend on signal processing.

### 4.2 Unnecessary Dependencies

| Dependency | Why It's Unnecessary |
|------------|---------------------|
| `groups.py` → `blender.py` | Only for `compute_poisson_base_rate()`. Could be a constant or a separate utility. |
| `output.py` → `elo_sync.py` | Only for `get_staleness_level()`. Could be resolved by passing the level as a parameter. |
| `governance.py` → `output.py` | `_run_governance()` calls `print_governance_dashlet()`. Governance orchestrator should return data, not call display. |
| `evaluation.py` → `state.py` | `evaluate_all_matches()` calls `load_prediction_history()` and `append_prediction_history()`. Should accept history as a parameter. |

### 4.3 Hidden Coupling

1. **`odds.py` and `catboost.py` import private functions from `fetcher.py`:**
   - `fetcher._find_bracket_match()`
   - `fetcher._find_group_match()`
   - `fetcher._normalize_team()`
   
   These are prefixed with `_` indicating they are implementation details. Three external modules depend on them.

2. **`main.py` knows the internal data structure of every module:**
   - Directly accesses `cache["matches"]`, `cache.get("fetched_at")`, `entry.get("probability")`
   - Directly constructs prediction history entries with specific key names
   - Directly calls `state._atomic_write_json()` via `_merge_probability_log()`

3. **Cache dict schema is undocumented and implicitly shared:**
   - All signal caches return `{fetched_at, expires_at, matches: {match_id: {probability, available, ...}}}`
   - This schema is enforced only by convention, not by types or validation

### 4.4 Duplicated Responsibilities

| Responsibility | Location 1 | Location 2 | Impact |
|---------------|------------|------------|--------|
| Elo expected score | `elo.expected_score()` | `main._expected_score_for_match()` | Divergent implementations possible |
| Match probability blending | `blender.blend_predictions()` (Brier-weighted) | `main._gather_signal_data()` (sequential average) | Different results for same data |
| Team name normalization | `fetcher._normalize_team()` | `main._run_historical_catch_up` (inline) | Duplicate logic |
| PK shootout detection | `fetcher.process_matches()` | `main._run_historical_catch_up()` | Different implementations |
| Standings display data preparation | `groups.compute_standings()` + `rank_third_placed()` | `main._compute_group_display()` | Thin wrapper, but still duplication of call chain |

---

## 5. Prediction Pipeline Audit

### Trace: BSD API → Console Output

```
Step                   Module           Responsibility           Clean?
─────                  ──────────────   ───────────────────────   ──────
1. Fetch raw events     fetcher.py      HTTP GET, pagination     ✅
2. Process knockout     fetcher.py      Filter, normalize,       ✅
   matches                               Alias resolution,
                                         PK detection
3. Process group        fetcher.py      Same + group letter      ✅
   matches                               extraction
4. Elo update           elo.py          apply_elo_update()       ✅
5. Persist results      state.py        save_teams, save_played  ✅
6. Create prediction    main.py         Build entry struct,      ❌ Logic in
   history                               compute actual_a         main.py
7. Load signal caches   state.py        Load from disk           ✅
8. Refresh odds         predictors/     Extract from events,     ✅
                         odds.py         vig removal
9. Refresh CatBoost     predictors/     API call, parse,         ✅
                         catboost.py     field fallback
10. Compute form        predictors/     Residual computation     ✅
    signal               form.py
11. Compute lineup      predictors/     Value log-ratio          ✅
    signal               lineup.py
12. Build xG overrides  main.py         Extract from CB cache    ❌ Logic in
                                                                   main.py
13. Merge into history  main.py         Ledger → history merge   ❌ Logic in
                                                                   main.py
14. Calibrate & blend   blender.py      Platt scaling,           ⚠ I/O via
                                         Brier-weighted            poisson_base_rate
15. Version tracking    governance.py   _maybe_update_versions   ✅
16. Signal warnings     main.py         Count unavailables       ❌ Logic in
                                                                   main.py
17. Governance check    governance.py   Drift detection,         ⚠ Prints
                                         backtest                  in module
18. Monte Carlo sim     knockout.py +   Full tournament sim       ✅
                         groups.py
19. Console output      output.py       Display functions        ✅
20. Probability log     state.py        Append snapshot          ✅
```

**Purity assessment:** Steps 6, 12, 13, 16 contain business logic in main.py that belongs in dedicated modules. Step 14 violates its own purity contract. Step 17 couples governance to display.

---

## 6. Dead Code Audit

### Unused Functions

| Function | Module | Evidence |
|----------|--------|----------|
| `save_bracket()` | `state.py` | Bracket is never saved — only loaded. No caller in source. |
| `load_state_meta()` | `state.py` | No caller in source. |
| `save_state_meta()` | `state.py` | No caller in source. |
| `save_eval_baseline_report()` | `state.py` | Only called from main.py once — could be considered used, but only on startup. |
| `load_eval_baseline_report()` | `state.py` | No caller in source. |
| `load_backtest_report()` | `state.py` | No caller in source. |
| `loo_cv_blended_brier()` | `blender.py` | Exported but no caller in source or test files that I've found. |
| `compare_baselines()` | `evaluation.py` | Exported but no caller in source. |

### Unreachable Code

| Location | Lines | Reason |
|----------|-------|--------|
| `blender.py:524-528` | `if __name__ == "__main__"` block | Only runs when executed directly, never via import |
| `output.py:18-19` | `sys.stdout.reconfigure()` | Only runs on Python 3.7+ with TTY stdout — dead on non-TTY |

### Possibly Obsolete

| Item | Location | Reason |
|------|----------|--------|
| `LEAGUES` dict | `constants.py:11-13` | Only has one entry (World Cup 2026). `--list-leagues` exits with just this one entry. |
| `WC_START_DATE` | `constants.py:41` | Used only in `build_historic_url()` — properly used, but is a hardcoded date. |
| Form predictor's auto-load fallback | `form.py:293-307` | Brackets auto-load from state, but caller (main.py) always passes these explicitly. |

### Unused Imports

| Location | Import | Reason |
|----------|--------|--------|
| `evaluation.py:5` | `import copy` | Used in `backtest_tournament` and `evaluate_all_matches` (elo path) |
| `output.py:15` | `import math` | Used for Wilson CI and _sigmoid |
| `groups.py:9` | `from collections import defaultdict` | Used in `_resolve_by_values` |

No conclusively unused imports found — all verified.

---

## 7. Architectural Smells

### 7.1 God Object — `main.py`

**Evidence:** 1545 lines, imports every module, contains CLI parsing + I/O + business logic + display orchestration + migration + duplicate functions. `_run_iteration()` alone is ~400 lines.

**Impact:** Any change to the prediction pipeline requires modifying main.py. Testability is reduced (most logic is embedded in private `_` functions not directly testable in isolation).

**Confidence:** High

### 7.2 God Class — `state.py`

**Evidence:** 1139 lines, contains 30+ public functions mixing 3 concerns: persistence (load/save), validation (validate_groups, validate_annex_c, validate_bracket), and migration (migrate_prediction_history).

**Impact:** State module is hard to reason about. Validation logic is coupled to file format.

**Confidence:** High

### 7.3 Feature Envy — `_gather_signal_data()` in main.py

**Evidence:** `main._gather_signal_data()` accesses the internal cache dict structure of every signal module and reimplements blending logic. The data and its operations belong in `blender.py`.

**Impact:** Blending behavior diverges (sequential avg vs Brier-weighted). Violates Tell Don't Ask.

**Confidence:** High

### 7.4 Feature Envy — `_merge_signals_into_history()` in main.py

**Evidence:** This function knows the internal schema of prediction_history entries and the prediction ledger. It belongs in state.py or a dedicated history module.

**Impact:** History merge logic is not reusable from tests or other entry points.

**Confidence:** High

### 7.5 Duplicate Logic — `_expected_score_for_match()`

**Evidence:** `main.py:642-647` reimplements `elo.expected_score()` with a 0.5 fallback.

**Impact:** If Elo formula changes, this duplicate must be updated too.

**Confidence:** High

### 7.6 Duplicate Logic — sequential average blend

**Evidence:** `main.py:722-725` blends by sequential averaging (`blended = (blended + odds_prob) / 2; blended = (blended + cb_prob) / 2`), while `blender.py` uses proper Brier-weighted blending via `compute_blend_weights()` and `blend_predictions()`.

**Impact:** The match detail table shows different probabilities than the actual simulation.

**Confidence:** High

### 7.7 Long Method — `_run_iteration()`

**Evidence:** ~400 lines, 19 steps, handles Elo sync, API fetch, match processing, signal refresh, calibration, blending, governance, simulation, display.

**Impact:** Impossible to understand in one reading. Difficult to test.

**Confidence:** High

### 7.8 Long Method — `_run_historical_catch_up()`

**Evidence:** ~130 lines, reimplements match processing and PK detection.

**Impact:** Duplicate logic that can diverge from `fetcher.process_matches()`.

**Confidence:** High

### 7.9 Tight Coupling — Private functions used as public API

**Evidence:** `odds.py` and `catboost.py` import `fetcher._find_bracket_match`, `fetcher._find_group_match`, `fetcher._normalize_team`. These are prefixed `_` but used externally.

**Impact:** If fetcher.py refactors internals, odds.py and catboost.py break. No encapsulation.

**Confidence:** High

### 7.10 Low Cohesion — `evaluation.py`

**Evidence:** Pure math functions (brier_score, log_loss) mixed with I/O-bound orchestration (evaluate_all_matches calls load_prediction_history, append_prediction_history).

**Impact:** Pure functions cannot be easily moved to a math library. Testing requires state fixtures.

**Confidence:** High

### 7.11 Low Cohesion — `governance.py`

**Evidence:** Version tracking, drift detection, backtesting orchestrator, and display logic (print_governance_dashlet call) in one module.

**Impact:** Governance logic cannot be reused without display side effects.

**Confidence:** High

### 7.12 Low Cohesion — `output.py`

**Evidence:** Contains Wilson CI math (`wilson_score_ci`, `format_ci`, `wilson_ci_from_prob`) and data structure computation (`coverage_audit`) alongside pure display functions.

**Impact:** Math functions are not reusable from non-display contexts.

**Confidence:** High

### 7.13 Layer Violation — `groups.py` imports from `blender.py`

**Evidence:** The simulation engine depends on the signal processing module for a base rate calculation.

**Impact:** Circular dependency risk if blender.py ever needs group functions.

**Confidence:** Medium

### 7.14 Layer Violation — `governance.py` imports from `output.py`

**Evidence:** Governance orchestrator calls `print_governance_dashlet()`. Orchestration should return data, not call display.

**Impact:** Cannot run governance without console output.

**Confidence:** High

### 7.15 Hidden State — Module-level globals in main.py

**Evidence:** 7 globals: `_running`, `_elo_last_sync_time`, `_last_gov_time`, `_ai_preview_enabled`, `_match_detail_enabled`, `_prev_signal_data`, `_prev_history`, `_prev_cal_params`.

**Impact:** State is implicit, not explicit. Testing requires resetting globals.

**Confidence:** High

### 7.16 Hidden State — Module-level cache in groups.py

**Evidence:** `_POISSON_BASE_RATE_CACHE` and `_POISSON_TABLES` are module-level mutable caches. `_reset_poisson_base_rate_cache()` exists solely for testing.

**Impact:** Tests can interfere with each other through shared mutable state. `_POISSON_TABLES` grows without bound (one table per unique lambda encountered).

**Confidence:** Medium

### 7.17 Magic Constants — Scattered thresholds

**Evidence:** `main.py:70` (3600s hardcoded as hourly check), `main.py:72` (3600 again), `main.py:789` (3600 again). `groups.py:59` (1.05 home advantage multiplier), `groups.py:81` (0.999999 CDF threshold), `groups.py:161-163` (2.0 yellow card rate, 0.05 red card rate), `output.py:70` (0.005 trend threshold).

**Impact:** Constants are scattered across modules, not centralized in constants.py.

**Confidence:** High

---

## 8. Risk Assessment

| # | Issue | Severity | Category | Rationale |
|---|-------|----------|----------|-----------|
| 1 | `main.py` God Object | **Critical** | Maintainability | 1545 lines, all changes touch this file |
| 2 | Duplicate blending logic | **High** | Correctness | Match detail table shows different probabilities than simulation |
| 3 | Private functions as public API | **High** | Maintainability | 3 modules import `fetcher._*` — encapsulation broken |
| 4 | I/O mixed with computation | **High** | Testability | evaluation.py, governance.py, state.py |
| 5 | `state.py` multi-concern | **High** | Maintainability | 1139 lines, 3 concerns |
| 6 | `_run_iteration()` Long Method | **High** | Understandability | ~400 lines, 19 steps |
| 7 | Governance coupled to display | **Medium** | Testability | print_governance_dashlet called from orchestrator |
| 8 | Duplicate `expected_score` | **Medium** | Correctness | Two implementations of same formula |
| 9 | Groups imports blender | **Medium** | Architecture | Simulation depends on signal processing |
| 10 | Module-level mutable state | **Medium** | Reliability | Shared caches, test interference |
| 11 | Scattered magic constants | **Medium** | Maintainability | Not centralized |
| 12 | Dead code (unused functions) | **Low** | Maintainability | 6+ exported functions never called |
| 13 | Hardcoded tournament dates | **Low** | Flexibility | WC_START_DATE, home advantage multiplier |
| 14 | Undocumented cache schema | **Low** | Understandability | Cache dict format is convention-only |

---

## 9. Future Readiness

### Long-term maintenance
**Concerning.** The God Object in `main.py` means any new feature requires changing the 1545-line entry point. The lack of separation between orchestration and business logic makes the system brittle. The dead/unused functions indicate the module structure has outgrown its original design.

### Additional tournaments
**Feasible but risky.** The Phase 19 multi-league framework laid groundwork (league_id, data dirs), but the League catalog only has 1 entry. The stub projects (`euro_predictor/`, `ucl_predictor/`) have zero code. Adding a new tournament would require duplication of the entire `worldcup_predictor` structure or a significant refactoring into a shared framework.

### New prediction signals
**Well-supported.** The predictor architecture (odds.py, catboost.py, form.py, lineup.py) is clean and consistent. Adding a new signal means: create a new file in `predictors/`, implement a `compute_*_signal()` returning a cache dict, add it to the signal_keys list in main.py. The blender already handles arbitrary signal keys.

### Scalability
**Not relevant.** This is a single-machine console application running 50K Monte Carlo iterations in ~13s. No horizontal scaling is needed or designed for.

### Testing
**Problematic.** The God Object in main.py makes integration testing difficult. Most logic is in `_` private functions. `_run_iteration()` cannot be tested in isolation without mocking 10+ services. The module-level mutable state requires test setup/teardown.

### Production deployment
**Not applicable.** This is a CLI tool, not a web service. It runs in a terminal. The design is appropriate for this use case.

---

## 10. Executive Verdict

### Architecture Score: **5.5 / 10**

### Biggest Strengths
1. **Clean signal predictor architecture** — `predictors/` package has a consistent pattern (`compute_*_signal()` → cache dict). Easy to add new signals.
2. **Well-separated simulation engine** — `groups.py` and `knockout.py` are well-factored, testable, and performant (50K iterations in ~13s).
3. **Good use of pure functions** — `elo.py`, `blender.py` (mostly), `enrichment.py` are pure computation with no I/O.
4. **Centralized configuration** — `constants.py` keeps all magic numbers, URLs, and thresholds in one place (though not complete).
5. **Atomic writes** — `state._atomic_write_json()` prevents data corruption on crash.

### Biggest Weaknesses
1. **`main.py` is a God Object** — 1545 lines containing CLI, orchestration, migration, business logic, display, and duplicate implementations. Every feature change requires modifying it.
2. **Real blending diverges from displayed blending** — `_gather_signal_data()` uses sequential averaging while `blender.py` uses Brier-weighted blend. The match detail table shows different probabilities than the actual simulation.
3. **Encapsulation violations** — 3 external modules import private `_` functions from `fetcher.py`. No module boundary enforcement.
4. **I/O mixed with computation** — `evaluation.py`, `governance.py`, and parts of `state.py` combine pure logic with file persistence or display.
5. **Multi-concern modules** — `state.py` (persistence + validation + migration), `output.py` (display + math), `governance.py` (orchestration + computation + display).

### Approval for Future Development
**Conditional.** The architecture is functional but has significant structural debt that will compound with each new feature. The core domain model (simulation, signal prediction, blending) is sound. The orchestration layer needs refactoring before it can be a stable foundation for:
- Adding `euro_predictor` and `ucl_predictor` as real projects
- Adding new prediction signals
- Adding comprehensive integration tests
- Any significant feature work beyond the current scope

**Recommended action:** Structural refactoring of `main.py` into a clean orchestrator, extraction of shared utilities from `fetcher.py`, and separation of I/O from computation in `evaluation.py` and `governance.py` before adding new features.
