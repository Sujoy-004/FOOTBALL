<!-- generated-by: gsd-doc-writer -->

# Providers, Predictors, and Signals Reference

This document describes the data provider architecture, legacy providers, predictors, and signal system used by the Football prediction pipeline. All paths are relative to the repository root.

---

## Table of Contents

1. [Data Provider Architecture](#1-data-provider-architecture)
2. [Provider Selection](#2-provider-selection)
3. [Legacy Providers](#3-legacy-providers)
4. [Predictors](#4-predictors)
5. [Signal Interface](#5-signal-interface)
6. [Signal Reference](#6-signal-reference)

---

## 1. Data Provider Architecture

The pluggable data provider system lives in `football_core/provider.py` and `football_core/data_providers/`. It provides a single protocol, `DataProvider`, implemented by two backends for external match data.

### 1.1 Core Data Types (`football_core/provider.py`)

| Dataclass | Fields | Description |
|---|---|---|
| `Team` | `name`, `pot`, `clubelo_name`, `coefficient` | A team participating in a fixture schedule. |
| `Match` | `match_id`, `team_a`, `team_b`, `home_pot`, `away_pot`, `event_date` | A single match within a fixture schedule. |
| `FixtureSchedule` | `teams`, `matchdays` | Validated fixture schedule; supports `from_dict()` and `validate()`. |

### 1.2 `DataProvider` Protocol

Defined in `football_core/provider.py` (lines 109–133). This `@runtime_checkable` protocol declares four fetch methods, each returning raw `list[dict]` data:

```python
class DataProvider(Protocol):
    def fetch_matches(self, competition_id: str, **kwargs) -> list[dict]: ...
    def fetch_predictions(self, competition_id: str, **kwargs) -> list[dict]: ...
    def fetch_managers(self, competition_id: str, **kwargs) -> list[dict]: ...
    def fetch_players(self, competition_id: str, **kwargs) -> list[dict]: ...
```

Competition identifiers are provider-specific (e.g. `"WC"`, `"CL"` for football-data.org; `27`, `7` for BSD league IDs).

### 1.3 BSD Provider (`football_core/data_providers/bsd_provider.py`)

**Class:** `BSDDataProvider`

Fetches from `https://sports.bzzoiro.com`. Created with an API token and league ID:

```python
provider = BSDDataProvider(api_key="...", league_id=27)
```

**Endpoints:**

| Method | API Path | Notes |
|---|---|---|
| `fetch_matches(url, league_id, timeout)` | `/api/events/?league_id={id}` | Paginated; filters results by league_id; returns raw events. |
| `fetch_predictions(league_id, timeout)` | `/api/predictions/?league={id}` | Returns CatBoost ML predictions. |
| `fetch_managers(league_id, timeout)` | `/api/managers/?league={id}` | Returns manager profiles with stats. |
| `fetch_players(league_id, timeout)` | `/api/v2/players/?league_id={id}&limit=200` | Paginated via `_paginate()`. |

**HTTP Behaviour:**
- Uses `requests.Session` with `Authorization: Token {api_key}` header.
- `_request()` implements retry/backoff (3 attempts: 1s, 2s, 4s). Returns `None` on repeated failure.
- HTTP 401 returns `None` silently (invalid key). Timeout, connection, and HTTP errors are logged at DEBUG level.
- `_paginate()` follows paginated `next` links automatically.

### 1.4 football-data.org Provider (`football_core/data_providers/football_data_org_provider.py`)

**Class:** `FootballDataOrgProvider`

Fetches from `https://api.football-data.org/v4`. Created with an API token:

```python
provider = FootballDataOrgProvider(api_key="...")
```

**Endpoints:**

| Method | API Path | Notes |
|---|---|---|
| `fetch_matches(competition_id, **kwargs)` | `/v4/competitions/{id}/matches` | Returns flattened BSD-compatible dicts via `_map_match()`. |
| `fetch_predictions(...)` | — | Returns `[]` — **not available** from this source. |
| `fetch_managers(...)` | — | Returns `[]` — **not available** from this source. |
| `fetch_players(...)` | — | Returns `[]` — **not available** from this source. |

**Field Mapping (football-data.org → BSD-compatible):**

| BSD Field | football-data.org Source |
|---|---|
| `home_team` | `homeTeam.name` |
| `away_team` | `awayTeam.name` |
| `home_score` | `score.fullTime.home` (or `score.regularTime.home` for penalty shootouts) |
| `away_score` | `score.fullTime.away` (or `score.regularTime.away` for penalty shootouts) |
| `status` | `status.lower()` |
| `event_date` | `utcDate` |
| `group_name` | `group` (`"GROUP_A"` → `"Group A"`) |
| `round_number` | `matchday` |
| `id` | `id` |
| `winner` | Derived from `score.winner` or score comparison |

**HTTP Behaviour:**
- Uses `requests.Session` with `X-Auth-Token` header.
- Same retry/backoff pattern as BSD; additionally handles HTTP 429 (rate limit) with exponential backoff (`2^attempt` seconds).
- HTTP 401 logged as warning.

### 1.5 Additional Protocols

**`MatchResultProvider`** (football_core/provider.py lines 69–90):
```python
class MatchResultProvider(Protocol):
    def load(self) -> dict[tuple[str, str], tuple[int, int]]: ...
```
Returns a dict keyed by `(team_a, team_b)` → `(home_score, away_score)`. Implementations include `ReplayMatchResultProvider` (from JSON files) and `BSDMatchResultProvider` (from BSD API) in `competitions/ucl/src/result_provider.py`.

**`FixtureProvider`** (football_core/provider.py lines 97–106):
```python
class FixtureProvider(Protocol):
    def load(self) -> FixtureSchedule: ...
```
Implemented by `BSDFixtureProvider` (BSD API with TTL cache) and `RepoFixtureProvider` (local JSON file) in `competitions/ucl/src/provider.py`.

---

## 2. Provider Selection

Selection is driven by the `DATA_PROVIDER` environment variable (set in `.env`).

### 2.1 UCL Pipeline

In `competitions/ucl/src/pipeline.py`, function `_select_provider()` (line 274):

```
DATA_PROVIDER=bsd       + BSD_API_KEY set       → BSDDataProvider(api_key, league_id=7)
DATA_PROVIDER=football-data + FOOTBALL_DATA_ORG_KEY set → FootballDataOrgProvider(api_key)
(no env var, BSD key present)                     → BSDDataProvider (fallback)
(no env var, football-data key present)           → FootballDataOrgProvider (fallback)
(neither)                                         → None (live data fetch skipped)
```

### 2.2 World Cup Pipeline

In `competitions/worldcup/src/pipeline.py` (line 68), the same `DATA_PROVIDER` env var switch applies:
- `DATA_PROVIDER=bsd` + `bsd_api_key` → `BSDDataProvider`
- `DATA_PROVIDER=football-data` + `football_data_org_key` → `FootballDataOrgProvider`

### 2.3 Graceful Degradation

When no provider is available, the pipeline logs a warning and returns `{"status": "skip", ...}`. BSD-specific features (market odds, CatBoost predictions, manager profiles, player availability) degrade silently — the consumer receives empty dicts and the calling code skips signal computation for those features.

---

## 3. Legacy Providers

Located in `football_core/providers/`. These are standalone fetch-and-parse modules that wrap `BSDDataProvider` for specific data types. They predate the unified `DataProvider` protocol and are still consumed directly by cache-dict pipelines (primarily the World Cup competition).

### 3.1 Team Provider (`football_core/providers/team.py`)

| Function | Signature | Purpose |
|---|---|---|
| `fetch_teams(api_key, league_id, timeout)` | → `dict[int, str]` | Fetch team listings from `BSD /api/teams/`. Returns `{team_id: team_name}`. |
| `fetch_and_cache_teams(api_key, league_id, cache_ttl_hours)` | → `dict` | Cache dict with `fetched_at`, `expires_at`, `team_map`. Default TTL: **48 hours**. |

**Used by:** `fetch_and_cache_players()` in `player.py` for resolving team IDs to names.
**API URL:** `https://sports.bzzoiro.com/api/teams/?league={id}&limit=100`

### 3.2 Player Provider (`football_core/providers/player.py`)

**Dataclass:** `PlayerProfile` — `name`, `team`, `position`, `rating`, `availability`, `injury_risk`, `market_value_eur`

| Function | Signature | Purpose |
|---|---|---|
| `fetch_players(api_key, league_id, timeout)` | → `list[dict]` | Delegates to `BSDDataProvider.fetch_players()`. |
| `parse_players(raw_players, team_map)` | → `dict[str, list[PlayerProfile]]` | Parses raw BSD data into team-keyed profiles. |
| `fetch_and_cache_players(api_key, league_id, cache_ttl_hours, team_map)` | → `dict` | Cache dict with `fetched_at`, `expires_at`, `players`. Default TTL: **6 hours** (shorter because availability changes rapidly). |

**Used by:** `AvailabilitySignal` and `PlayerFormSignal`.

### 3.3 Manager Provider (`football_core/providers/manager.py`)

**Dataclass:** `ManagerProfile` — `name`, `team`, `win_pct`, `avg_goals_scored`, `avg_goals_conceded`, `avg_xg_for`, `avg_xg_against`, `clean_sheet_pct`, `btts_pct`, `over_25_pct`, `avg_possession`, `preferred_formation`, `formations_used`, `team_style`, `pressing_intensity`, `defensive_line`, `profile`

| Function | Signature | Purpose |
|---|---|---|
| `fetch_managers(api_key, league_id, timeout)` | → `list[dict]` | Delegates to `BSDDataProvider.fetch_managers()`. |
| `parse_managers(raw_managers)` | → `dict[str, ManagerProfile]` | Parses raw BSD data into team-keyed profiles. |
| `fetch_and_cache_managers(api_key, league_id, cache_ttl_hours)` | → `dict` | Cache dict with `fetched_at`, `expires_at`, `managers`. Default TTL: **24 hours**. |

**Used by:** `DefensiveQualitySignal` and `ManagerEffectSignal`.

### 3.4 Caching Pattern

All legacy providers follow the same cache-dict pattern:

```python
{
    "fetched_at": "2025-07-28T12:00:00+00:00",
    "expires_at": "2025-07-29T12:00:00+00:00",
    "managers": { ... },   # or "players", "team_map"
}
```

- The orchestrator checks `expires_at` before calling the provider again.
- Failed fetches return an empty data dict (never raise) — graceful degradation.
- `is_cache_valid()` from `football_core.state` is used by the UCL `BSDFixtureProvider` to check fixture cache expiration.

---

## 4. Predictors

Located in `football_core/predictors/`. These ingest market odds and ML predictions from the BSD API, removing vig and normalizing probabilities.

### 4.1 Odds Predictor (`football_core/predictors/odds.py`)

**Vig Removal (`remove_vig`):**

```python
def remove_vig(odds_home: float, odds_draw: float, odds_away: float) -> dict[str, float]:
```
Converts decimal odds to fair probabilities by normalising implied probabilities to sum to 1.0:
- `p_home = (1/odds_home) / total`, where `total = 1/odds_home + 1/odds_draw + 1/odds_away`

**Key Functions:**

| Function | Purpose |
|---|---|
| `parse_odds_response(bsd_events, alias_lookup, groups, bracket)` | Match BSD events to internal match IDs; extract odds; return `{match_id: {probability, timestamp, available}}`. |
| `fetch_and_cache_odds(api_key, bsd_events, alias_lookup, groups, cache_ttl_hours, bracket)` | Wraps `parse_odds_response` in cache dict format. Default TTL: **12 hours**. |

- Skips finished events (`event["status"] == "finished"`).
- Skips events with unmatchable team names (uses `normalize_team` from `football_core.fetcher`).
- Resolves group matches by `group_letter + round_number` and bracket matches by team pairing.
- Returns `available: False` with `reason: "odds_not_available"` when odds fields are missing/invalid.

### 4.2 CatBoost Predictor (`football_core/predictors/catboost.py`)

**Key Functions:**

| Function | Purpose |
|---|---|
| `parse_catboost_response(bsd_predictions, alias_lookup, groups, bracket)` | Parse BSD predictions into `{match_id: {probability, confidence, model_version, timestamp, available, expected_home_goals, expected_away_goals}}`. |
| `fetch_and_cache_catboost(api_key, alias_lookup, groups, bracket, cache_ttl_hours, league_id)` | Fetches from BSD API and caches. Default TTL: **24 hours**. |

**Probability extraction:**
- Tries multiple field names for probabilities: `home_probability`, `prob_home_win`, `home_win`, `probability_home` (and similarly for draw/away).
- Divides by 100 to normalise to `[0, 1]`.
- Validates that probabilities sum sensibly and are within range.

**Expected goals extraction:**
- Tries: `expected_home_goals`, `home_expected_goals`, `xg_home` (and `xg_away` variants).

**Fallback behaviour:**
When the BSD API returns empty predictions, every match in `groups + bracket` is marked as `{"probability": 0.5, "available": False, "reason": "provider_not_available"}`.

The `CatBoostSignal` (`football_core/signals/catboost.py`) wraps this cache in the `Signal` protocol — it reads from a pre-loaded cache dict passed via constructor.

---

## 5. Signal Interface

Defined in `football_core/signal.py`.

### 5.1 Core Types

| Type | Fields | Description |
|---|---|---|
| `SignalOutput` | `home_prob`, `draw_prob`, `away_prob` | Probability distribution for one match from one signal. Should sum to ~1.0. |
| `PredictionContext` | `fixtures`, `elo_ratings`, `played_results`, `team_aliases`, `squad_values`, `manager_data`, `player_data` | Rich context passed to each signal's `predict()`. |

### 5.2 Signal Protocol

```python
class Signal(Protocol):
    name: str
    def predict(self, match: dict, context: PredictionContext) -> SignalOutput: ...
```

- Must not modify `match` or `context`.
- The `name` class attribute is used by `SignalRegistry` and for weight lookup.

### 5.3 SignalRegistry

Plugin-style registry (`football_core/signal.py`):

| Method | Purpose |
|---|---|
| `register(signal)` | Add signal; raises `SignalRegistryError` if name already registered. |
| `get(name)` | Retrieve by name. |
| `list()` | List all registered signal names (sorted). |
| `all()` | Return all registered signals. |
| `evaluate(match, context)` | Evaluate all signals for a match. Catches exceptions per-signal and returns uniform `1/3` fallback — never crashes the pipeline. |
| `clear()` | Remove all signals. |

### 5.4 BlendedPrediction

Produced by `EnsembleEngine.evaluate()` (`football_core.blender`):

```python
@dataclass
class BlendedPrediction:
    home_prob: float
    draw_prob: float
    away_prob: float
    signal_breakdown: dict[str, dict[str, float]]  # {signal_name: {home, draw, away, weight}}
    weights_applied: dict[str, float]
```

### 5.5 Signal Engine Construction

In `competitions/ucl/src/orchestrator.py`, function `build_signal_engine()`, signals are registered for the UCL competition:

```python
signals = [
    RefinedEloSignal(),
    MarketOddsSignal(),
    RollingFormSignal(result_provider=...),
    SquadValueSignal(),
    RestDaysSignal(),
    AvailabilitySignal(),
    ManagerEffectSignal(),
    DefensiveQualitySignal(),
    PlayerFormSignal(),
    TeamSynergySignal(),
]
```

Weights are loaded from `competitions/ucl/config/signal_weights.json` or provided via override. Falls back to uniform weights.

---

## 6. Signal Reference

### 6.1 Availability / Injury Impact (`football_core/signals/availability.py`)

**Signal class:** `AvailabilitySignal` — `name = "availability"`

**Inputs:** `context.player_data` — team→list of player dicts (from `providers.player.parse_players()`)

**Outputs:** `SignalOutput(home_prob, draw_prob=0.25, away_prob)`

**Formula:**
1. For each team, compute weighted unavailability:
   - `unavailable_pct = sum(rating × pos_weight for unavailable players) / sum(rating × pos_weight for all players)`
   - Position weighting: GK/striker harder to replace (1.5×), midfielders 1.2–1.3×, defenders 1.0–1.2×.
2. `p = sigmoid(k × (unavail_b - unavail_a))`, default `k=3.0`

**Unavailable statuses:** `{"injured", "suspended"}`  
**High injury risk:** `{"High", "Unlikely"}`
**Configuration:** `DEFAULT_K = 3.0`, `POSITION_WEIGHTS` dict (GK=1.5, ST=1.5, CM=1.3, etc.)

**Active when:** Player data available for both teams. Returns `available: False` with reason `"player_data_not_found"` when missing.

**Used by:** UCL pipeline (as `AvailabilitySignal`). World Cup cache-dict pipeline (via `compute_availability_signal`).

---

### 6.2 Defensive Quality (`football_core/signals/defensive_quality.py`)

**Signal class:** `DefensiveQualitySignal` — `name = "defensive_quality"`

**Inputs:** `context.manager_data` — team→manager profile dict (with `clean_sheet_pct`, `avg_xg_against`)

**Outputs:** `SignalOutput(home_prob, draw_prob=0.25, away_prob)`

**Formula:**
```python
defensive_rating = 0.5 × clean_sheet_pct + 0.5 × (1 - min(xga / 3.0, 1.0))
p = sigmoid(2.0 × (rating_a - rating_b))
```

**Configuration:** `DEFAULT_K = 2.0`, `DEFAULT_CS_WEIGHT = 0.5`, `DEFAULT_XGA_WEIGHT = 0.5`, `DEFAULT_MAX_XGA = 3.0`

**Active when:** Manager data available for both teams. Returns `available: False` with `"manager_data_not_found"` when missing.

**Cache TTL for standalone use:** 1 hour (via `compute_defensive_signal()`)

---

### 6.3 Manager Effect (`football_core/signals/manager_effect.py`)

**Signal class:** `ManagerEffectSignal` — `name = "manager_effect"`

**Inputs:** `context.manager_data` — team→manager profile dict (with `win_pct`, `formations_used`, `team_style`)

**Outputs:** `SignalOutput(home_prob, draw_prob=0.25, away_prob)`

**Formula:**
```python
base_rating = win_pct
tactical_bonus = len(formations_used) × 0.02
style_modifier = {"attacking": 0.02, "defensive": -0.02, "balanced": 0.0}[team_style]
effective_rating = base_rating + tactical_bonus + style_modifier
p = sigmoid(2.0 × (rating_a - rating_b))
```

**Configuration:** `DEFAULT_K = 2.0`, `FORMATION_BONUS_PER = 0.02`, `STYLE_MODIFIERS` dict

**Active when:** Manager data available for both teams. Falls back to uniform `1/3` when missing.

**Cache TTL for standalone use:** 1 hour (via `compute_manager_signal()`)

---

### 6.4 Market Odds (`football_core/signals/market_odds.py`)

**Signal class:** `MarketOddsSignal` — `name = "market_odds"`

**Inputs:** `match["odds_home"]`, `match["odds_draw"]`, `match["odds_away"]` (decimal odds on the match dict)

**Outputs:** `SignalOutput` with vig-removed fair probabilities

**Formula:** Calls `remove_vig(odds_home, odds_draw, odds_away)` from `football_core.predictors.odds`.

**Configuration:** `fallback_uniform` (default `True`) — returns `(1/3, 1/3, 1/3)` when odds are missing/invalid.

**Active when:** Decimal odds fields present on the match dict (`odds_home > 0`, etc.).

---

### 6.5 Refined Elo (`football_core/signals/refined_elo.py`)

**Signal class:** `RefinedEloSignal` — `name = "refined_elo"`

**Inputs:** `context.elo_ratings` — team→rating dict

**Outputs:** `SignalOutput(home_prob, draw_prob, away_prob)`

**Formula:**
```python
home_prob = expected_score(home_elo, away_elo, home_advantage=100)  # from football_core.elo
draw_prob = max(0.0, 1.0 - abs(home_prob - 0.5) * 2.0) * 0.35
away_prob = 1.0 - home_prob - draw_prob
```

**Configuration:**
| Parameter | Default | Description |
|---|---|---|
| `k_factor` | 60 | K-factor for Elo updates (used externally) |
| `home_advantage` | 100 | Elo points added to home team |
| `goal_diff_weighting` | True | Whether goal difference is considered in Elo updates |

**Active when:** `context.elo_ratings` contains both teams. Falls back to `DEFAULT_ELO` (1500) from `football_core.constants`.

---

### 6.6 Rest Days (`football_core/signals/rest_days.py`)

**Signal class:** `RestDaysSignal` — `name = "rest_days"`

**Inputs:** `context.fixtures` (list of match dicts with `team_a`, `team_b`, `event_date`), `match["event_date"]`

**Outputs:** `SignalOutput(home_prob, draw_prob=1/3, away_prob)`

**Formula:**
1. For each team, find the most recent match before `match_date` and compute days of rest.
2. `adjustment = max_advantage × tanh(diff / 7.0)`
3. `home_prob = 1/3 + adjustment`, `away_prob = 1/3 - adjustment`

**Configuration:** `max_advantage = 0.1` (maximum probability swing from rest difference).

**Active when:** Always active (no external dependencies). If no previous match found, assumes 7 days rest.

---

### 6.7 Rolling Form (`football_core/signals/rolling_form.py`)

**Signal class:** `RollingFormSignal` — `name = "rolling_form"`

**Inputs:** `MatchResultProvider` (injected at construction), `context.fixtures`, `match["event_date"]`

**Outputs:** `SignalOutput(home_prob, draw_prob, away_prob)`

**Formula:**
1. For each team, fetch recent results via `result_provider.get_team_results()`.
2. Apply exponential decay weighting: `weight = decay_factor^k` (k = position from most recent).
3. Outcome: win=1.0, draw=0.5, loss=0.0.
4. Convert form scores to probabilities via `expected_score()`:

```python
form_a = weighted_sum_a / total_weight_a
raw_home = expected_score(form_a × 100 + 1500, form_b × 100 + 1500, home_advantage=0)
```

**Configuration:**
| Parameter | Default | Description |
|---|---|---|
| `windows` | `[3, 5, 10]` | Form evaluation windows |
| `decay_factor` | 0.9 | Exponential decay per match |
| `result_provider` | (required) | `MatchResultProvider` instance |

**Active when:** Results are available for the team. Returns 0.5 if no results found.

**Note:** Uses `MatchResultProvider` protocol (line 7), making it agnostic to BSD vs replay data sources.

---

### 6.8 Squad Value (`football_core/signals/squad_value.py`)

**Signal class:** `SquadValueSignal` — `name = "squad_value"`

**Inputs:** `context.squad_values` or `competitions/ucl/data/squad_values.json` (falls back to file)

**Outputs:** `SignalOutput(normalized_home, draw_prob, away_prob)`

**Formula:**
```python
log_home = log(home_value)
log_away = log(away_value)
home_prob = log_home / (log_home + log_away)
diff_ratio = min(|log_home - log_away| / total_log, 0.5)
draw_prob = max(0.0, (1.0 - diff_ratio × 2.0) × 0.33)
normalized_home = home_prob × (1.0 - draw_prob)
```

Log-transform prevents teams with extremely high market values from dominating linearly.

**Configuration:** `data_path` — path to `squad_values.json` (default: `competitions/ucl/data/squad_values.json`).

**Active when:** Squad values available (from context or file). Missing teams fall back to median value. Returns uniform `(1/3, 1/3, 1/3)` when no data at all.

---

## 7. Additional Signals (UCL ensemble only)

The UCL ensemble in `build_signal_engine()` (orchestrator.py) includes two additional signals not detailed above:

### 7.1 Player Form (`football_core/signals/player_form.py`)

**Class:** `PlayerFormSignal` — `name = "player_form"`

Star-power signal using the combined rating of each team's top N players (default 11, representing a starting XI). Uses `sigmoid(k × (strength_ratio - 0.5) × 4)` where `k=1.5` default.

### 7.2 Team Synergy (`football_core/signals/team_synergy.py`)

**Class:** `TeamSynergySignal` — `name = "team_synergy"`

Attack/defence balance measured from played results. Synergy = `avg_scored / (avg_scored + avg_conceded)`. Uses `sigmoid(2.0 × (synergy_a - synergy_b) × 3)`.

### 7.3 Lineup Strength (`football_core/signals/lineup.py`)

**Class:** `LineupStrengthSignal` — `name = "lineup_strength"`

Squad market value log-ratio signal. Uses `sigmoid(0.35 × log(val_a / val_b))`. Reads from `context.squad_values`. This signal is registered separately for the World Cup pipeline.

### 7.4 CatBoost (`football_core/signals/catboost.py`)

**Class:** `CatBoostSignal` — `name = "catboost"`

Wraps a pre-loaded CatBoost cache dict (from `predictors/catboost.fetch_and_cache_catboost()`). Returns `SignalOutput(prob, draw_prob=0.25, away=1-prob-0.25)`. Falls back to uniform on cache miss. This signal is registered separately for the World Cup pipeline.

---

## 8. Cache TTL Summary

| Data | Default TTL | Configured In |
|---|---|---|
| BSD fixtures (UCL) | Configurable (`CACHE_TTL_HOURS` in `constants.py`) | `competitions/ucl/src/provider.py` |
| Team listings | 48 hours | `providers/team.fetch_and_cache_teams()` |
| Manager profiles | 24 hours | `providers/manager.fetch_and_cache_managers()` |
| Player profiles | 6 hours | `providers/player.fetch_and_cache_players()` |
| Market odds | 12 hours | `predictors/odds.fetch_and_cache_odds()` |
| CatBoost predictions | 24 hours | `predictors/catboost.fetch_and_cache_catboost()` |
| Availability/Defensive/Manager signals (standalone) | 1 hour | `signals/availability/defensive/manager` compute functions |