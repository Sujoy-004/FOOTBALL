# Constraints

## Source: FOOTBALL_ENGINE_ARCHITECTURE.md (SPEC)

- **source:** docs/FOOTBALL_ENGINE_ARCHITECTURE.md
- **type:** SPEC
- **confidence:** high

### Architecture Constraints

| Constraint | Details |
|---|---|
| **Threading** | Single-threaded event loop with synchronous I/O. Polling uses `time.sleep()` with 0.5s granularity for responsive shutdown. |
| **No global state (enforced)** | Module-level `RunState` dataclass replaces mutable globals. No `global` keywords remain. |
| **No circular imports** | Dependency direction is strictly `football_core` ← competitions. No circular imports detected. |
| **sys.path bootstrap** | Each competition `__init__.py` inserts repo root and package dir into `sys.path` at import time. |
| **No config/ini/yaml** | Configuration entirely through Python constants and CLI args. |
| **Flat package over subpackages** | `football_core/` modules are flat. Subpackage split into `compute/`, `signals/`, `bsd/`, `state/` deferred until third competition justifies it. |
| **Re-export wrappers retained** | `competitions/worldcup/src/elo.py` remains as re-export to avoid changing all internal `from src import` references. |
| **Euro sys.path hack retained** | `competitions/euro/__init__.py` still adds `competitions/worldcup/` to path because Euro imports `from src.groups import compute_standings` for historical catch-up. |

### Domain Types (Stable Abstractions)

These interfaces must never change once `football_core` is published:

```
TeamId      = str           # Canonical team name
MatchId     = str           # "GS_A_01" or "M73"
EloRating   = float         # ~1000–2500
Probability = float         # [0.0, 1.0]
EpochSec    = float         # time.time()
```

### API / Data Contracts

#### MatchResult Schema
```python
@dataclass
class MatchResult:
    match_id: MatchId
    team_a: TeamId
    team_b: TeamId
    winner: TeamId | None         # None = draw
    is_draw: bool
    home_score: int
    away_score: int
    completed_at: str             # ISO 8601
    stats: dict | None = None     # enrichment output
    context: dict | None = None   # venue, referee
```

#### SignalCache Schema
```python
SignalCache = {
    "fetched_at": str,       # ISO 8601
    "expires_at": str,       # ISO 8601
    "matches": {
        MatchId: {
            "probability": Probability | None,
            "available": bool,
            "timestamp": str,
            "reason": str | None,
        }
    }
}
```

#### PredictionEntry Schema
```python
PredictionEntry = {
    "match_id": MatchId,
    "timestamp": str,
    "team_a": TeamId,
    "team_b": TeamId,
    "actual": float,          # 0.0, 0.5, or 1.0
    "signals": {
        SignalKey: {
            "probability": Probability,
            "version": str,
            "timestamp": str,
            "available": bool,
        }
    }
}
```

#### BlendParams Schema
```python
BlendParams = {
    "calibration_params": {SignalKey: {"A": float, "B": float, ...}},
    "blend_weights": {SignalKey: float},
    "match_probs": {MatchId: Probability},
}
```

#### GovernanceSnapshot Schema
```python
GovSnapshot = {
    "run_version": str,
    "data_version": str,
    "model_version": str,
    "timestamp": str,
    "signal_counts": {SignalKey: int},
    "blend_weights": {SignalKey: float},
    "per_signal_brier": {SignalKey: float},
    "blended_brier": float,
    "drift_status": "COLD_START" | "HEALTHY" | "DRIFT",
    "drift_details": list[dict] | None,
}
```

### Competition Boundary Contract

Each competition under `competitions/<name>/` must provide:

- `config.py`: `COMPETITION_NAME`, `COMPETITION_TYPE`, `SIMULATION_ITERATIONS`, `K_FACTOR`, `EXPECTED_GOALS_BASE_RATE`, `HOME_ADVANTAGE_MULTIPLIER`, `DATA_DIR`
- `simulation.py`: `def run_simulation(...) -> dict[str, dict[str, float]]`
- `display.py`: `print_probability_table()`, `print_header()`, `print_shutdown_banner()`

### Data Directory Convention

All state persists in `competitions/<name>/data/`. Every `state.py` function accepts `data_dir`. `football_core/state.py` functions use `data_dir` from caller.

### Adding a New Competition

1. Create `competitions/<name>/` directory
2. Provide `config.py` with competition constants
3. Provide `simulation.py` with competition's simulation engine
4. Provide `display.py` with competition-specific output
5. Provide competition data files in `data/`
6. Write a thin `main.py` that wires `football_core` → competition logic
7. **Zero changes to `football_core/`**

### Current `football_core` Public API

The following import paths are supported:

```python
# Core math
from football_core.elo import expected_score, compute_k_factor, update_ratings, apply_elo_update
from football_core.math_utils import sigmoid

# BSD API integration
from football_core.fetcher import fetch_raw_messages, process_matches, process_group_matches, find_bracket_match, find_group_match, normalize_team

# State persistence
from football_core.state import load_teams, save_teams, load_played, save_played, load_played_groups, save_played_groups, load_signal_cache, save_signal_cache, load_prediction_history, append_prediction_history, load_eloratings_cache, save_eloratings_cache, load_elo_update_log, save_elo_update_log, load_probability_log, append_probability_log, is_cache_valid, validate_bracket

# Group stage simulation
from football_core.groups import expected_goals, _build_poisson_table, _poisson_sample, _simulate_single_match, precompute_matchup_lambdas, simulate_group_matches, _compute_conduct_score, _compute_h2h, _resolve_by_values, _resolve_tied_cluster, _tiebreak_group

# Knockout stage simulation
from football_core.knockout import _simulate_knockout_round, _get_blended_prob

# Signal predictors
from football_core.predictors.odds import remove_vig, parse_odds_response, fetch_and_cache_odds
from football_core.predictors.catboost import parse_catboost_response, fetch_and_cache_catboost

# Constants
from football_core.constants import K_FACTOR, DEFAULT_ELO, MAX_EXPECTED_GOALS, HOME_ADVANTAGE_MULTIPLIER, POISSON_TABLE_BITS, POISSON_TABLE_SIZE, EXPECTED_GOALS_BASE_RATE, API_TIMEOUT, ELO_SYNC_RETRY_BACKOFFS, ELO_SYNC_TIMEOUT, ELO_DRIFT_TOLERANCE, ELO_BLEND_THRESHOLD, ELO_BLEND_FACTOR, ELO_STALENESS_WARN_HOURS, ELORATINGS_TSV_URL
```

### NFRs (Non-Functional Requirements)

- **Polling interval:** 60 seconds minimum between BSD API calls (configurable via `POLL_INTERVAL` env var)
- **API timeout:** 10 seconds for BSD API, 15 seconds for eloratings.net
- **Retry policy:** 3 retries with exponential backoff (1s/2s/4s)
- **Monte Carlo iterations:** 50,000 fixed (adaptive iteration count not yet implemented)
- **Cache TTLs:** Market odds = 12h, CatBoost = 24h, Elo sync = 24h
- **Elo drift tolerance:** ≤10 ignored, 11-30 50% blend, >30 full overwrite

*Generated by gsd-doc-synthesizer — merge mode, 2026-06-27*
