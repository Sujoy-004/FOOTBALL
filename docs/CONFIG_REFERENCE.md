<!-- generated-by: gsd-doc-writer -->

# Configuration & Calibration Reference

This document describes every JSON configuration file, runtime constant module, and calibration procedure used by the Football prediction system. It covers the World Cup (WC) and UEFA Champions League (UCL) competitions.

---

## 1. Signal Weights Configuration

Each competition maintains its own `signal_weights.json` that controls how individual prediction signals are blended into a single match forecast.

### 1.1 World Cup — `competitions/worldcup/config/signal_weights.json`

**Schema:**

```json
{
  "weights": {
    "<signal_name>": <float>
  },
  "description": "<string>"
}
```

**Current value (8 signals, uniform 0.125 each):**

| Signal              | Weight | Description                                     |
|----------------------|--------|-------------------------------------------------|
| `elo`                | 0.125  | Elo rating head-to-head expected score           |
| `market_odds`        | 0.125  | Betting market implied probabilities             |
| `catboost`           | 0.125  | CatBoost ML model predictions                    |
| `form`               | 0.125  | Recent form residual (rolling sigmoid)           |
| `lineup_strength`    | 0.125  | Squad market value comparison                    |
| `defensive_quality`  | 0.125  | Clean-sheet percentage + xGA composite           |
| `manager_effect`     | 0.125  | Manager win-rate / Elo-style rating              |
| `availability`       | 0.125  | Player availability / injury risk                |

**How weights are applied (Brier-weighted blending):**

The World Cup uses `competitions/worldcup/src/blender.py` which implements a **Brier-weighted inverse-score blending** strategy:

1. For each signal, a rolling Brier score is computed over the most recent `BRIER_WINDOW_SIZE` (50) matches using `compute_rolling_brier()` in `football_core/blender.py`.
2. Raw weights are calculated as `1.0 / max(brier, 0.05)` — signals with lower Brier (better accuracy) receive higher weight.
3. Raw weights are normalized to sum to 1.0.
4. Before blending, each signal's raw probability is optionally Platt-scaled (see §2.1).
5. The final blended prediction is a weighted average: `blended = Σ(w_i * p_i) / Σ(w_i)`.

The uniform 0.125 weights in the config file are the **initial defaults** and are dynamically overwritten at runtime by `calibrate_and_blend()` each poll cycle. The `BRIER_WINDOW_SIZE` and `COLD_START_THRESHOLD` (30 matches) constants are defined in `competitions/worldcup/src/constants.py`.

### 1.2 UCL — `competitions/ucl/config/signal_weights.json`

**Schema:**

```json
{
  "version": <int>,
  "calibrated_at": "<ISO-8601 datetime>",
  "n_matches": <int>,
  "threshold": <int>,
  "weights": {
    "<signal_name>": <float>
  },
  "per_signal": {
    "<signal_name>": {
      "log_loss": <float>,
      "n_matches": <int>,
      "excluded": <bool>
    }
  }
}
```

**Current calibrated weights (calibrated 2026-07-08 over 288 matches):**

| Signal          | Weight   | Log-Loss | Description                               |
|-----------------|----------|----------|-------------------------------------------|
| `market_odds`   | 0.144396 | 0.6365   | Betting market implied probabilities       |
| `player_form`   | 0.144396 | 0.6365   | Individual player form metrics             |
| `refined_elo`   | 0.135471 | 0.6784   | Elo with home advantage / goal-diff scaling|
| `rest_days`     | 0.144396 | 0.6365   | Rest advantage between fixtures            |
| `rolling_form`  | 0.139814 | 0.6574   | Rolling team form residual                 |
| `squad_value`   | 0.147131 | 0.6247   | Squad market value comparison              |
| `team_synergy`  | 0.144396 | 0.6365   | Team cohesion / lineup stability           |

**How weights are derived (log-loss-weighted uniform blend):**

UCL weights are produced **offline** by `competitions/ucl/src/calibrate.py`:

1. Replay data is loaded via `ReplayMatchResultProvider`.
2. All registered signals are evaluated against each historical match, producing home/draw/away probability triples.
3. For each signal, a **multi-class log-loss** is computed as the average of three binary log-losses (home, draw, away).
4. Inverse-log-loss weights are derived: `w_i = (1/ll_i) / Σ(1/ll_j)` via `compute_log_loss_weights()`.
5. Config is written atomically (write to temp file, `os.replace` to target).

A signal is **excluded** from the blend if it has fewer than `threshold` (20) matches worth of data. No dynamic runtime recalibration occurs for UCL — weights are computed once from replay data and read from the file.

---

## 2. Calibration Configuration

### 2.1 UCL Online (Simplex Temperature Scaling) — `competitions/ucl/config/calibration.json`

**Schema:**

```json
{
  "alpha": <float>,
  "T": <float>,
  "log_loss": <float>,
  "log_loss_before": <float>,
  "n_samples": <int>
}
```

**Purpose:** After the ensemble merges all signals into a single `BlendedPrediction`, that prediction may be overconfident (probabilities too extreme) due to correlated signal errors. Calibration applies **simplex temperature scaling** to flatten or sharpen the blended probabilities.

**Current fitted parameters (from 144 samples):**

| Parameter          | Value     | Meaning                                      |
|--------------------|-----------|----------------------------------------------|
| `alpha` (α)        | 1.860877  | Exponent for simplex scaling: q_i = p_i^α / Σ|
| `T`                | 0.537381  | Temperature = 1/α. T < 1 **sharpens** probs  |
| `log_loss`         | 0.995298  | Multi-class log-loss **after** calibration   |
| `log_loss_before`  | 1.017035  | Multi-class log-loss **before** calibration  |
| `n_samples`        | 144       | Number of calibration hold-out matches        |

**How it works (`football_core/blender.py` — `CalibrationPipeline`):**

1. `CalibrationPipeline.fit()` is called with a list of uncalibrated `BlendedPrediction` objects and corresponding `MatchOutcome` ground-truths.
2. The optimizer (`_brent_minimize`, Brent's method from `football_core/blender.py`) searches α ∈ [0.1, 10] to minimize multi-class log-loss.
3. Scaling maps calibrated probability `q_i = p_i^α / Σ(p_j^α)` — this is **simplex scaling**, not logit-temperature scaling (no pre-softmax logits available in a probability-only ensemble).
4. T = 1.0 is identity; T > 1 flattens (reduces overconfidence); T < 1 sharpens.
5. The fitted α = 1.860877 (T ≈ 0.537) indicates that the raw ensemble was **underconfident** and requires sharpening.

**Lifecycle:** `fit()` → `transform()`/`predict()` → `save()`/`load()`. The serialization format supports both `alpha` (v2) and `T` (legacy v1) keys.

### 2.2 WC Per-Signal Platt Scaling (`competitions/worldcup/src/blender.py`)

The World Cup calibrates each signal **individually** via Platt scaling before blending, rather than calibrating the blended output:

1. For each signal, Platt scaling parameters (A, B) are fitted via iterative reweighted least squares in `calibrate_signal()` (`football_core/blender.py`).
2. Fitting transforms predictions to log-odds space: `x = log(p / (1-p))`, then fits `sigmoid(A*x + B)`.
3. Targets use the `_platt_targets()` smoothing: `t_pos = (n_pos + 1) / (n_pos + 2)`.
4. A cold-start threshold of 30 matches (`COLD_START_THRESHOLD`) must be met; below this, identity calibration (A=1, B=0) is used.
5. Calibration parameters are stored per-signal in the `calibration_params` dict returned by `calibrate_and_blend()`.

---

## 3. Cache TTL Configuration

### 3.1 UCL — `competitions/ucl/config/cache_ttls.json`

```json
{"odds": 12, "catboost": 24}
```

A simple flat JSON object mapping signal key to TTL in **hours**:

| Cache Key     | TTL (hours) | Signal(s) served              |
|---------------|-------------|-------------------------------|
| `odds`        | 12          | `market_odds` signal          |
| `catboost`    | 24          | CatBoost predictions          |

### 3.2 Caching Mechanism

**Cache validity** is determined by `is_cache_valid()` in `football_core/state.py`:

```python
def is_cache_valid(cache: dict, ttl_hours: int = 12) -> bool:
```

1. The cache dict must contain an `expires_at` ISO-8601 UTC timestamp.
2. `expires_at` is set to `(now + timedelta(hours=ttl))` at fetch time by `fetch_and_cache_odds()` in `football_core/predictors/odds.py`.
3. If `datetime.now(timezone.utc) < expiry`, the cache is valid.
4. Empty caches or caches without `expires_at` are always invalid.

**Cache files** are JSON files stored under `data/` with names configured in each competition's constants module. For World Cup, these are defined in `competitions/worldcup/src/constants.py`:

| Cache file constant           | Filename                    | Default TTL |
|-------------------------------|-----------------------------|-------------|
| `ODDS_CACHE_FILE`             | `odds_cache.json`           | 12h         |
| `CATBOOST_CACHE_FILE`         | `catboost_cache.json`       | 24h         |
| `FORM_CACHE_FILE`             | `form_cache.json`           | 1h (local)  |
| `LINEUP_CACHE_FILE`           | `lineup_cache.json`         | 1h (local)  |
| `MANAGER_CACHE_FILE`          | `manager_cache.json`        | 24h         |
| `DEFENSIVE_CACHE_FILE`        | `defensive_cache.json`      | 1h (local)  |
| `MANAGER_EFFECT_CACHE_FILE`   | `manager_effect_cache.json` | 1h (local)  |
| `AVAILABILITY_CACHE_FILE`     | `availability_cache.json`   | 6h          |
| `ELO_ODDS_CACHE_FILE`         | `elo_odds_cache.json`       | 24h         |
| `TEAM_SYNERGY_CACHE_FILE`     | `team_synergy_cache.json`   | 1h (local)  |
| `ROLLING_FORM_CACHE_FILE`     | `rolling_form_cache.json`   | 1h (local)  |
| `SQUAD_VALUE_CACHE_FILE`      | `squad_value_cache.json`    | 24h         |
| `REST_DAYS_CACHE_FILE`        | `rest_days_cache.json`      | 1h (local)  |

Local signals (form, synergy, rolling form, rest days) use a `LOCAL_SIGNAL_CACHE_TTL_HOURS` of 1h since they are computed from already-fetched data rather than external API calls.

**Load/save pattern:** All caches use `load_signal_cache()` / `save_signal_cache()` in `football_core/state.py` with atomic write (temp file + `os.replace`).

---

## 4. Glicko-1 Rating System — `football_core/glicko.py`

Glicko-1 is an evolution of Elo that models each team's rating as a **Gaussian distribution** N(μ, σ²), where σ (rating deviation, RD) captures uncertainty. Used for the UCL competition.

### 4.1 Module-Level Constants

| Constant         | Value   | Meaning                                            |
|------------------|---------|----------------------------------------------------|
| `Q`              | 0.00576 | Scale constant: `ln(10) / 400` from the Elo scale  |
| `PI_SQ`          | π²      | Used in `g(RD)` calculation                        |
| `DEFAULT_MU`     | 1500.0  | Default rating for new teams                       |
| `DEFAULT_SIGMA`  | 350.0   | Default RD for new teams (high uncertainty)        |
| `MIN_SIGMA_SQ`   | 2500.0  | Minimum variance floor (σ ≥ 50)                    |
| `C`              | 30.0    | Rating volatility (unused in v1)                   |

### 4.2 `TeamRating` Dataclass

```python
@dataclass
class TeamRating:
    mu: float      # Mean rating (point estimate)
    sigma: float   # Standard deviation (RD)

    @property
    def sigma_sq(self) -> float:  # σ² variance
```

### 4.3 `RatingSystem` Class

Manages ratings for a set of teams:

- **`get_rating(team)`** — Returns current `TeamRating` or default (1500, 350) for unseen teams.
- **`set_rating(team, mu, sigma)`** — Direct assignment (e.g., initial fetch).
- **`update_ratings(team_a, team_b, score_a, score_b, k_multiplier=1.0)`** — Paired Glicko update after a match. Updates each team against the **other team's pre-match rating** (not the already-updated version).
- **`to_dict()` / `from_dict(data)`** — Serialization to/from `{"team": {"mu": ..., "sigma": ...}}`.
- **`to_elo_dict()`** — Compatibility shim returning point estimates only: `{"team": mu}`.

### 4.4 Core Functions

**`g(rd)`** — Probability deflation factor:

```
g(σ) = 1 / sqrt(1 + 3 * Q² * σ² / π²)
```

A perfectly known rating (σ=0) gives g=1.0 (full Elo impact). Higher RD reduces the impact, pulling expected probability toward 0.5.

**`expected_score_bayesian(mu_a, mu_b, sigma_b)`** — Expected score for team A against team B, incorporating B's uncertainty:

```
E_A = 1 / (1 + 10^(-g(σ_B) * (μ_A - μ_B) / 400))
```

When σ_B = 0 this reduces to standard Elo expected score.

**`update_glicko(mu, sigma_sq, opponent_mu, opponent_sigma_sq, score, k_multiplier=1.0)`** — Closed-form Glicko-1 update (Equations 4 from Glickman 1999):

1. Computes `d²` (variance of rating estimate): `d² = 1 / (Q² * g² * E * (1 - E))`
2. `k_multiplier` scales information: larger k → more weight on observed outcome.
3. New variance: `σ²_new = 1 / (1/σ² + 1/d²)`, floored at 2500.
4. New mean: `μ_new = μ + Q * σ²_new * g * (score - E) * k_multiplier`.

**`compute_glicko_k_factor(goal_diff, base_K=1.0)`** — Goal-difference multiplier mirroring Elo's `compute_k_factor()`:

| Goal Diff | Multiplier            |
|-----------|-----------------------|
| 0–1       | `base_K` (1.0)        |
| 2         | `base_K * 1.5`        |
| ≥3        | `base_K * (11 + gd)/8`|

### 4.5 How Glicko-1 Differs from Elo

| Aspect              | Elo (`football_core/elo.py`)        | Glicko-1 (`football_core/glicko.py`)    |
|---------------------|-------------------------------------|-----------------------------------------|
| Rating model        | Point estimate (single number)      | Gaussian N(μ, σ²) with uncertainty      |
| Expected score      | Fixed K-factor                      | g(RD) deflates uncertain opponents      |
| Update scale        | K = base_K * G(goal_diff)           | k_multiplier scaled via d² variance      |
| New-team handling   | Fixed starting Elo                  | High σ (350) — limited impact early on  |
| Draw handling       | result_a = 0.5                      | score_a = 0.5 (same, via score param)   |
| PK outcome          | 0.75 / 0.25 weighting               | Not handled (pass score directly)        |
| Competition         | World Cup                           | UCL                                      |

### 4.6 Competition Usage

Glicko-1 is used by the **UCL** competition. The `refined_elo` signal in the UCL signal registry (`competitions/ucl/src/calibrate.py`) consumes Glicko ratings. The World Cup uses standard Elo from `football_core/elo.py`.

---

## 5. Competition-Specific Constants

### 5.1 Shared — `football_core/constants.py`

| Constant                   | Value   | Purpose                                  |
|----------------------------|---------|------------------------------------------|
| `K_FACTOR`                 | 60      | Base K-factor for Elo updates            |
| `DEFAULT_ELO`              | 1500    | Default Elo rating for new teams         |
| `MAX_EXPECTED_GOALS`       | 8.0     | Upper cap for Poisson expected goals     |
| `HOME_ADVANTAGE_MULTIPLIER`| 1.05    | Home advantage scaling factor            |
| `POISSON_TABLE_BITS`       | 10      | Bits for precomputed Poisson lookup table|
| `POISSON_TABLE_SIZE`       | 1024    | Entries in Poisson lookup table (`1<<10`)|
| `EXPECTED_GOALS_BASE_RATE` | 1.25    | Baseline expected goals rate             |
| `API_TIMEOUT`              | 10      | Default HTTP request timeout (seconds)   |
| `ELO_SYNC_RETRY_BACKOFFS`  | (1,2,4)| Retry delays for eloratings.net sync (s) |
| `ELO_SYNC_TIMEOUT`         | 15      | Elo sync HTTP timeout (seconds)          |
| `ELO_DRIFT_TOLERANCE`      | 10      | Max Elo drift before alert (points)      |
| `ELO_BLEND_THRESHOLD`      | 30      | Min points diff to blend external Elo    |
| `ELO_BLEND_FACTOR`         | 0.5     | Blend factor for external Elo merge      |
| `ELO_STALENESS_WARN_HOURS` | (24,48,72,168) | Warning thresholds for stale Elo   |
| `ELORATINGS_TSV_URL`       | `https://www.eloratings.net/World.tsv` | External Elo source URL <!-- VERIFY: Hosted by eloratings.net, assume availability -->|

### 5.2 World Cup — `competitions/worldcup/src/constants.py`

Extends all shared constants and adds:

**League & API:**
| Constant            | Value    | Purpose                                  |
|---------------------|----------|------------------------------------------|
| `DEFAULT_LEAGUE_ID` | 27       | BSD league ID for World Cup 2026         |
| `API_URL`           | `https://sports.bzzoiro.com/api/events/?league_id=27&limit=200` | BSD API endpoint <!-- VERIFY: Non-public API -->|
| `WC_START_DATE`     | 2026-06-11| Tournament start for historical catch-up |
| `POLL_INTERVAL`     | 60 (env) | Poll cycle interval in seconds           |

**Tournament structure (48-team format):**
| Constant                        | Value | Purpose                              |
|---------------------------------|-------|--------------------------------------|
| `GROUP_COUNT`                   | 12    | Groups A–L                           |
| `TEAMS_PER_GROUP`               | 4     | Teams per group                      |
| `MATCHES_PER_GROUP`             | 6     | Round-robin matches per group        |
| `ANNEX_C_ENTRIES`               | 495   | Third-place lookup table entries C(12,8)|
| `ANNEX_C_WINNER_GROUPS`         | A,B,D,E,G,I,K,L | Group winners hosting R32 third-placers|
| `TREND_THRESHOLD`               | 0.005 | Min probability change for trend arrow |
| `ELORATINGS_TEAM_CODES`         | 48 2-letter→name mappings | eloratings.net code lookup |

**Signal tuning parameters:**
| Constant                | Value | Purpose                                  |
|-------------------------|-------|------------------------------------------|
| `DEFAULT_FORM_K`        | 1.0   | Form signal sigmoid steepness            |
| `DEFAULT_LINEUP_K`      | 0.35  | Lineup strength sigmoid steepness        |
| `DEFAULT_DEFENSIVE_K`   | 2.0   | Defensive quality sigmoid steepness      |
| `DEFAULT_MANAGER_K`     | 2.0   | Manager effect sigmoid steepness         |
| `DEFAULT_AVAILABILITY_K`| 3.0   | Availability signal sigmoid steepness    |
| `FORM_WINDOW_SIZE`      | 5     | Rolling window for form residual         |
| `COLD_START_THRESHOLD`  | 30    | Min matches before Platt scaling activates|
| `BRIER_WINDOW_SIZE`     | 50    | Rolling Brier window for blend weights   |

**Cache files (see §3.2 for complete table):**
| Constant                       | Value                         |
|--------------------------------|-------------------------------|
| `ODDS_CACHE_TTL_HOURS`         | 12                            |
| `CATBOOST_CACHE_TTL_HOURS`     | 24                            |
| `MANAGER_CACHE_TTL_HOURS`      | 24                            |
| `AVAILABILITY_CACHE_TTL_HOURS` | 6                             |
| `LOCAL_SIGNAL_CACHE_TTL_HOURS` | 1                             |
| `SQUAD_VALUE_CACHE_TTL_HOURS`  | 24                            |
| `ELO_ODDS_CACHE_TTL_HOURS`     | 24                            |

**Governance:**
| Constant                         | Value  | Purpose                        |
|----------------------------------|--------|--------------------------------|
| `GOV_INTERVAL_HOURS`             | 1      | Governance check interval      |
| `GOV_DRIFT_SIGMA_THRESHOLD`      | 2.0    | Drift alert standard deviations|
| `GOV_BACKTEST_TOURNAMENTS`       | [2018, 2022] | Historical tournaments for backtesting|
| `GOV_RUN_SNAPSHOT_RETENTION`     | 1000   | Max run snapshots to retain    |

### 5.3 UCL — `competitions/ucl/src/constants.py`

| Constant           | Value    | Purpose                                  |
|--------------------|----------|------------------------------------------|
| `UCL_LEAGUE_ID`    | 7        | BSD league ID for UEFA Champions League  |
| `BSD_API_URL`      | `https://sports.bzzoiro.com/api/events/` | BSD API base URL <!-- VERIFY: Non-public API -->|
| `CACHE_TTL_HOURS`  | 1        | General fixture cache TTL                |
| `CACHE_FILENAME`   | `cached_fixtures.json` | Fixture cache file name     |

The UCL constants module is intentionally minimal — it defers to `football_core.constants` for shared values and configures only the BSD league ID, API URL, and cache settings. All UCL signal weights and calibration parameters live in the `config/` JSON files rather than Python constants.