<!-- generated-by: gsd-doc-writer -->
# Competition Engines — Internal Architecture Reference

This document describes the internal architecture of the two competition engines: the **World Cup (WC) engine** and the **UEFA Champions League (UCL) engine**. Both engines share a common `football_core` library for signal blending, Elo computation, and evaluation metrics, but each has its own pipeline orchestration, signal predictors, and validation patterns.

---

## 1. World Cup Engine

**Location:** `competitions/worldcup/src/engine.py`

The World Cup engine is a **poll-cycle orchestration engine** that runs repeated fetch → process → simulate cycles. It is designed for live tournament use where new match results arrive over time and the system must update probabilities in near-real-time.

### 1.1 Signal Build Order

The primary factory function is `build_signal_engine()` (line 36 of engine.py). It constructs an `EnsembleEngine` (from `football_core.blender`) by wrapping **13 signals** — 12 via `_CacheSignal` adapters and 1 (`elo`) via a separate `_EloSignal` class:

| Signal Name | Cache Source | Predictor Module |
|---|---|---|
| `elo` | Live Elo ratings from `context.elo_ratings` (via `_EloSignal`, not `_CacheSignal`) | `football_core.elo.expected_score` |
| `market_odds` | `odds_cache.json` | `src.predictors.odds` |
| `catboost` | `catboost_cache.json` | `src.predictors.catboost` |
| `form` | `form_cache.json` | `src.predictors.form` |
| `lineup_strength` | `lineup_cache.json` | `src.predictors.lineup` |
| `defensive_quality` | `defensive_cache.json` | `src.predictors.manager_signals` |
| `manager_effect` | `manager_effect_cache.json` | `src.predictors.manager_signals` |
| `availability` | `availability_cache.json` | `src.predictors.availability` |
| `elo_odds` | `elo_odds_cache.json` | `src.predictors.elo_odds` |
| `team_synergy` | `team_synergy_cache.json` | `src.predictors.team_synergy` |
| `rolling_form` | `rolling_form_cache.json` | `src.predictors.rolling_form` |
| `squad_value` | `squad_value_cache.json` | `src.predictors.squad_value` |
| `rest_days` | `rest_days_cache.json` | `src.predictors.rest_days` |

The `build_signal_engine()` function accepts all 12 cache parameters (the Elo signal has no cache — it reads ratings from `PredictionContext.elo_ratings`) plus optional `weights` dict or `weights_path`. Internally it:

1. Creates a raw `_EloSignal` that computes home/away/draw probabilities using `expected_score()` with a +100 home advantage.
2. For each named signal cache, creates a `_CacheSignal` instance that looks up `match_id` in the cache dict and returns `SignalOutput(prob, 0.25, 1.0 - prob - 0.25)`.
3. Returns `EnsembleEngine(signals, weights=...)`.

A convenience wrapper `build_engine_from_caches()` (line 1221) loads all 12 cache files from disk via `state.load_signal_cache()` (the Elo signal is computed inline from `PredictionContext.elo_ratings`, so no cache file is needed) and delegates to `build_signal_engine()`.

### 1.2 Poll Cycle Lifecycle

The main loop function is `run_poll_cycle()` (line 637). It accepts the full tournament state (teams, groups, bracket, annex_c, played, played_groups, etc.) and runs one complete cycle:

```
┌─────────────────────────────────────────────────┐
│ run_poll_cycle()                                │
│                                                 │
│  1. Check Elo sync staleness                    │
│     (ELO_SYNC_INTERVAL_HOURS=24)                │
│                                                 │
│  2. Rate-limit sleep (POLL_INTERVAL=60s)        │
│                                                 │
│  3. Hourly auto-refresh: skip fetch,            │
│     run simulation if last_sim_time > 3600s      │
│                                                 │
│  4. Fetch raw matches from BSD API              │
│     → process_matches() for knockout            │
│     → process_group_matches() for groups        │
│     → apply Elo updates                         │
│     → save to state                             │
│                                                 │
│  5. Update prediction_history for new matches   │
│                                                 │
│  6. Refresh all 13 signal caches (TTL-gated)    │
│     → odds, catboost, form, lineup, defensive,  │
│       manager, availability, elo_odds,           │
│       team_synergy, rolling_form, squad_value,   │
│       rest_days                                 │
│                                                 │
│  7. Merge signals into prediction_history        │
│     (merge_signals_into_history)                │
│                                                 │
│  8. Build EnsembleEngine & blend predictions    │
│                                                 │
│  9. Version tracking (governance)                │
│     → _maybe_update_versions()                  │
│                                                 │
│ 10. Run governance check                        │
│     (GOVERNANCE_INTERVAL_SECONDS)               │
│                                                 │
│ 11. Run full simulation (50,000 iterations)     │
│     → run_full_simulation()                     │
│                                                 │
│ 12. Compute group standings display             │
│                                                 │
│ 13. Gather match detail signals                 │
│     (if match_detail_enabled)                   │
│                                                 │
│ 14. Return structured dict                      │
└─────────────────────────────────────────────────┘
```

The function returns a dict with keys: `simulation`, `new_matches`, `signal_warnings`, `blend_params`, `governance`, `elo_sync`, `match_detail`, `group_standings`, `sim_elapsed`, `last_sim_time`, `last_request_time`, `probs`, `elo_last_sync_time`, `last_gov_time`, `prev_signal_data`.

### 1.3 Integration with the Web Layer

All `print()` calls are stripped from the engine functions. They return structured dicts that the web layer (in `web/wc_app.py`) formats for display. The web layer is responsible for:

- Managing `active_simulations` state
- Updating the global `cache` with overview + metadata
- Writing snapshots to disk
- Calling `run_poll_cycle()` in a loop or on-demand

### 1.4 Relationship with Pipeline

The pipeline module (`competitions/worldcup/src/pipeline.py`) provides higher-level orchestration functions that wrap engine capabilities for web API consumption:

- **`fetch_live_data()`** — Fetches live match data and all signal caches from the configured data provider (BSD or Football-Data.org), writing caches to disk.
- **`run_simulation_compute()`** — Core simulation computation: calls `fetch_live_data()`, loads state, builds engine, runs Monte Carlo via `run_full_simulation()`, computes top teams, evaluates predictions, builds full bracket, and returns a complete results dict.
- **`run_calibration_compute()`** — Calibration computation: loads all signal caches from disk, calls `run_calibrate_and_blend()`, returns blend parameters and calibration params.

---

## 2. World Cup Analysis & Governance

### 2.1 Counterfactual Analysis

**Location:** `competitions/worldcup/src/analysis.py`

The `run_counterfactual()` function (line 153) performs what-if simulation:

1. Deep-copies the baseline tournament state (teams, groups, bracket).
2. Applies overrides from a parsed what-if JSON file (Elo changes, blend weight overrides, xG overrides, calibration temperature).
3. Runs `run_full_simulation()` with the modified state and a shifted seed (`seed + 1`).
4. Returns `(cf_result, change_descriptions)`.

The `parse_what_if()` function (line 25) validates the override JSON file against allowed keys: `elo_changes`, `blend_weights`, `xg_overrides`, `calibration_temperature`.

The `run_calibrated_validation()` function (line 215) runs validation twice — uncalibrated (baseline) and calibrated — computing Brier score, log loss, and champion accuracy against the known actual champion.

### 2.2 Drift Detection and Version Tracking

**Location:** `competitions/worldcup/src/governance.py`

Governance implements a **three-version system**:

| Version | Prefix | Increment Condition |
|---|---|---|
| `data_version` | `D` | New match_id appears OR an existing entry gains a new signal key |
| `model_version` | `M` | Signal keys change OR calibration params change |
| `run_version` | `R` | ISO 8601 timestamp per governance cycle |

Key functions:

- **`_compute_data_version()`** — Increments `D` per conditions A (new match_id) or B (new signal key on existing entry).
- **`_compute_model_version()`** — Increments `M` when signal key set differs or `calibration_changed`.
- **`_compute_run_version()`** — Returns `datetime.now(timezone.utc).isoformat()`.
- **`_maybe_update_versions()`** — Calls all three `_compute_*` functions and updates timestamps.

**Drift detection** uses a rolling-window Brier score approach (per D-09):

1. **`_deduplicate_history()`** — Deduplicates prediction_history entries by match_id (keeps last entry).
2. **`_per_match_briers()`** — Extracts per-match Brier scores for a given signal.
3. **`check_drift()`** — Computes rolling mean Brier over the last `window` (default 50) matches. If `rolling_mean > reference_baseline + 2.0 * sigma`, signals drifted. Cold-start guard at `COLD_START_THRESHOLD`.
4. **`compute_reference_baselines()`** — Overall mean Brier per signal across all history.

The `_run_governance()` orchestrator (line 320) runs one governance cycle:
1. Deduplicates entries
2. Computes per-signal rolling Brier
3. Computes or loads reference baselines
4. Checks drift per signal
5. Determines drift status: `COLD_START`, `DRIFT`, or `HEALTHY`
6. Builds and saves a D-06 snapshot dict

### 2.3 Backtest Methodology

The `_run_backtest()` function (line 450 in governance.py) runs one-shot backtesting:

1. Iterates over `GOV_BACKTEST_TOURNAMENTS` (historical tournament config).
2. For each tournament file in `data/historical/{tournament}.json`, loads match data and calls `backtest_tournament()`.
3. Aggregates per-tournament reports into an aggregate report with:
   - Per-signal weighted Brier and log loss (weighted by n_matches)
   - Signal ranking sorted by ascending Brier
   - Governance recommendation text
4. Saves to `eval_backtest_report.json` via `state.save_backtest_report()`.

---

## 3. World Cup Pipeline

**Location:** `competitions/worldcup/src/pipeline.py`

The pipeline module extracts 7 core functions from the web layer for reuse and testability:

### 3.1 `fetch_live_data()`
Fetches live match data + all signal caches from the configured data provider (`BSDDataProvider` or `FootballDataOrgProvider`, selected via `DATA_PROVIDER` env var or auto-detected). Writes results to JSON files. Uses multi-pass bracket resolution (up to 3 passes) for knockout matches. Availability signal is fetched with a 30s timeout via `ThreadPoolExecutor`.

### 3.2 `build_chronological_matches()`
Builds a chronological match listing grouped by round (group stage then knockout: R32, R16, QF, SF, TPP, FINAL).

### 3.3 `build_knockout_tree()`
Builds knockout tree structure with resolved teams for all rounds. Calls `compute_full_bracket()` from `web.wc_app`.

### 3.4 `collect_downstream_matches()`
Traverses bracket `source_matches` to collect all downstream match IDs reachable from a target match ID.

### 3.5 `simulate_from_match()`
Runs full simulation for a specific match + its downstream matches. Returns per-team stage probabilities for the target match.

### 3.6 `run_simulation_compute()`
The **core simulation pipeline**:

```
run_simulation_compute(data_dir, iterations=50000, seed, weights, api_keys, progress_cb)
│
├─ 1. fetch_live_data()        → Refresh match data + signal caches
├─ 2. Load teams, groups, bracket, annex_c, played
├─ 3. build_engine_from_caches → Build EnsembleEngine from disk caches
├─ 4. Compute engine predictions for all matches
├─ 5. run_full_simulation()    → Monte Carlo (50,000 iterations)
├─ 6. Compute top team rankings
├─ 7. compute_signal_eval()    → Prediction accuracy metrics
├─ 8. compute_full_bracket()   → Enriched bracket tree
├─ 9. Enrich unplayed matches with predicted scores
├─ 10. compute_overview()      → Overview stats
└─ 11. Return {overview, top_teams, eval_metrics, full_bracket, sim_result, snapshot}
```

### 3.7 `run_calibration_compute()`
Loads all signal caches from disk and calls `run_calibrate_and_blend()` from engine.py, then returns blend params and calibration params.

---

## 4. UCL Orchestrator

**Location:** `competitions/ucl/src/orchestrator.py`

The UCL orchestrator routes between **simulate**, **replay**, and **live** modes (per D-05). Each mode resolves played_matches from its source, then delegates to the mode-agnostic simulation engine.

### 4.1 Mode Selection

The `resolve_played_matches()` function (line 316) selects mode based on CLI args:

| Mode | `args.mode` | Data Source |
|---|---|---|
| **Replay** | `"replay"` | `ReplayMatchResultProvider` from `--replay-data PATH` |
| **Live** | `"live"` | `BSDMatchResultProvider` from `BSD_API_KEY` + BSD API |
| **Results** | (default) | `results.json` on disk via `ReplayMatchResultProvider` |

### 4.2 Fixture, Results, and Elo Loading

The `run_simulation()` function (line 353) orchestrates the full flow:

1. **`resolve_played_matches()`** — Get played matches from the appropriate provider.
2. **`build_simulation_result()`** — Run MC simulation + representative bracket iteration, return `SimulationResult`.
3. The `SimulationResult` dataclass (from `competitions/ucl/result.py`) contains: `snapshot_date`, `n_iterations`, `seed`, `standings`, `teams`, `playoff_ties`, `playoff_winners`, `bracket_rounds`, `bracket_champion`, `stages`.

The `load_calibration()` function (line 41) loads temperature calibration from `config/calibration.json` (extracting `T`, `alpha`, `log_loss`, `log_loss_before`, `n_samples`, `ece`).

### 4.3 Signal Engine

`build_signal_engine()` (line 116) constructs an `EnsembleEngine` with **10 signals**:

1. `RefinedEloSignal`
2. `MarketOddsSignal`
3. `RollingFormSignal` (with `_ReplayResultProvider` or `_EmptyResultProvider`)
4. `SquadValueSignal`
5. `RestDaysSignal`
6. `AvailabilitySignal`
7. `ManagerEffectSignal`
8. `DefensiveQualitySignal`
9. `PlayerFormSignal`
10. `TeamSynergySignal`

Weights are loaded from `config/signal_weights.json`, with optional override via `weights_override` parameter.

### 4.4 Monte Carlo Simulation Trigger

`build_simulation_result()` (line 168) triggers the MC simulation:

1. Checks if a Glicko-1 `rating_system` is provided; if so, calls `run_monte_carlo_glicko()`; otherwise calls `run_monte_carlo()`.
2. Runs one representative league phase via `simulate_league_phase()`.
3. Loads playoff pairings and bracket rules from JSON.
4. Simulates playoff round, builds R16 bracket, simulates knockout tree, tracks stages.
5. Returns populated `SimulationResult`.

### 4.5 Validation

`run_validation()` (line 250) cross-checks simulation predictions against real match outcomes using `compute_metrics()` and `calibration_curve()` from `football_core.evaluation`.

### 4.6 Deterministic Compute

`run_deterministic_compute()` (line 372) runs a fully deterministic computation from real results (not simulation): loads results, computes standings, builds brackets, evaluates signals — no Monte Carlo needed.

`run_compute_all()` (line 502) is the top-level dispatcher: if `results.json` and `knockout_results.json` exist, runs deterministic mode; otherwise runs simulation mode.

---

## 5. UCL Pipeline

**Location:** `competitions/ucl/src/pipeline.py`

The UCL pipeline provides pure functions extracted from `web/ucl_app.py`.

### Key Functions

| # | Function | Purpose |
|---|---|---|
| 1 | `fetch_ucl_managers()` | Fetch UCL manager data via BSD provider, mapped by team alias |
| 2 | `compute_deterministic_standings()` | Compute league table from finished match results |
| 3 | `build_deterministic_bracket()` | Build deterministic bracket display from real KO results |
| 4 | `compute_signal_eval()` | Evaluate signal accuracy vs real results |
| 5 | `_select_provider()` | Select BSD or Football-Data.org provider |
| 6 | `fetch_live_data()` | Fetch live match data from provider, update results/KO files |
| 7 | `load_results()` | Load results from `results.json` |
| 8 | `load_knockout_results()` | Load knockout results from `knockout_results.json` |
| 9 | `build_league_matchdays()` | Group results by matchday prefix |
| 10 | `ucl_form_trend()` | Last 5 results for a team |
| 11 | `ucl_head_to_head()` | H2H stats between two teams |
| 12 | `ucl_outcome_dist()` | Outcome distribution from blended probability |
| 13 | `ucl_insight_text()` | Natural-language insight text for a match |
| 14 | `run_mc_simulation()` | Full Monte Carlo simulation pipeline |
| 15 | `run_calibration_task()` | Run calibration against replay data |

### 5.1 Relationship with Orchestrator

The pipeline functions are **pure computations** with no side effects (no global state, no disk writes). The orchestrator (`orchestrator.py`) is responsible for mode routing, I/O, and composing pipeline functions. For example:

- `run_mc_simulation()` → calls `build_simulation_result()` (from orchestrator) → which calls pipeline functions internally
- `run_calibration_task()` → calls `run_calibration()` from `calibrate.py`

### 5.2 Relationship with Simulation

The `run_mc_simulation()` function (line 602) is the UCL analogue of the WC `run_simulation_compute()`. It:

1. Loads fixtures via `RepoFixtureProvider`
2. Fetches Elo ratings (with coefficient-based fallback)
3. Blends manager data into Elo ratings
4. Calls `build_simulation_result()` for MC simulation
5. Builds enriched bracket, playoff display, odds display, standings display
6. Computes signal stats via engine evaluation
7. Loads calibration from `load_calibration()`
8. Returns complete results dict

---

## 6. UCL Validation

### 6.1 Multi-Tier Validation

**Location:** `competitions/ucl/src/validation_suite.py`

The `ValidationSuite` class orchestrates a three-tier validation framework:

#### Tier 1: Cross-Tournament Backtest (`run_tier_1_cross_tournament()`)
- **Method:** For each historical season Y, use all seasons < Y as source, predict tournament Y outcomes.
- **Scoring:** TRPS (Tagged Rank Probability Score), champion accuracy, stage accuracy.
- **Stage groups:** 7 groups — champion (1), runner-up (1), semifinal (2), quarterfinal (4), R16 (8), playoff (8), eliminated (12).

#### Tier 2: Walk-Forward Match-Level Validation (`run_tier_2_walk_forward()`)
- **Method:** Sliding window over seasons (default window=3). Train on window seasons, eval on next season.
- **Scoring:** Multi-class log loss, multi-class Brier, multi-class ECE.

#### Tier 3: Replay Validation (`run_tier_3_replay()`)
- **Method:** Step through matchdays chronologically. At each step d, use results from matchdays 0..d as played, simulate fixtures matchdays d+1..N-1.
- **Scoring:** ECE (Expected Calibration Error) with calibration bins.

#### Combined Report
`run_all()` runs all three tiers and produces a combined D-04 format report. `save_baseline()` saves the uncalibrated baseline as `baseline_uncalibrated.json`.

### 6.2 Fixture Schedule Validation

**Location:** `competitions/ucl/src/validation.py`

`validate_ucl_fixtures()` validates the UCL league phase fixture schedule against constraints:

| Constraint | Expected | Error if |
|---|---|---|
| Team count | 36 | Not 36 |
| Matchdays | 8 | Not 8 |
| Matches per matchday | 18 | Not 18 |
| Total matches | 144 | Not 144 |
| Opponents per team | 8 | Not 8 |
| Pot distribution | 2 from each of 4 pots | Not 2 per pot |
| Home/away balance | 4 home, 4 away | Not balanced |
| Duplicate matchups | None | Duplicate pair found |
| Team references | All valid | Unknown team name |

Raises `ValueError` on constraint violation.

### 6.3 Cross-Season Validation

Cross-season validation is handled by Tier 1 (cross-tournament) and Tier 2 (walk-forward) in `ValidationSuite`. The `ValidationResult` dataclass stores:

```python
@dataclass
class ValidationResult:
    tier: str           # "walk_forward" | "replay" | "cross_tournament"
    date: str           # ISO date
    n_matches: int
    n_seasons: int
    metrics: dict       # log_loss, brier, ece (varies by tier)
    details: dict | None  # Per-season or per-matchday breakdowns
    baseline: bool      # True if uncalibrated baseline
```

---

## 7. UCL Calibrate

**Location:** `competitions/ucl/src/calibrate.py`

The offline weight calibration flow:

### Flow

```
run_calibration(replay_data_path, threshold=20, output_path)
│
├─ 1. Load replay data via ReplayMatchResultProvider
│      → {(team_a, team_b): (home_score, away_score)}
│
├─ 2. Build SignalRegistry with 7 signals:
│      RefinedEloSignal
│      MarketOddsSignal
│      RollingFormSignal (with _EmptyResultProvider)
│      SquadValueSignal
│      RestDaysSignal
│      PlayerFormSignal
│      TeamSynergySignal
│
├─ 3. For each match in replay data:
│      registry.evaluate(match, context)
│      → accumulate per-signal home/draw/away probs + actual outcomes
│
├─ 4. Compute per-signal multi-class log-loss
│      = average of 3 binary log-losses (home, draw, away)
│      → Exclude signals with < threshold matches
│
├─ 5. compute_log_loss_weights(log_losses)
│      → inverse-log-loss weighting
│
├─ 6. Atomic write to signal_weights.json
│      (via tempfile + os.replace, per Pitfall 2)
│
└─ 7. Return config dict:
      {version, calibrated_at, n_matches, threshold, weights, per_signal}
```

### Replay Data Usage

The calibration uses **replay data** (past completed seasons) to evaluate each signal's predictive accuracy. The `ReplayMatchResultProvider` loads match results with `team_a`, `team_b`, `home_score`, `away_score`. Each match is evaluated through all registered signals in the `SignalRegistry`. Per-signal log-loss scores are computed, and inverse-log-loss weights are derived — lower log-loss (better accuracy) yields higher weight.
