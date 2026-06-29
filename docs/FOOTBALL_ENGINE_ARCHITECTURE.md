# Football Engine Architecture

## 1. Current Architecture (as-built)

```
FOOTBALL/
├── football_core/                ← SHARED ENGINE (flat package)
│   ├── __init__.py
│   ├── constants.py              ← generic constants only (K_FACTOR, DEFAULT_ELO, etc.)
│   ├── elo.py                    ← Elo math (expected_score, update_ratings, compute_k_factor)
│   ├── elo_sync.py               ← eloratings sync (URL parameterized)
│   ├── fetcher.py                ← BSD API fetch+dedup (accepts league_id)
│   ├── groups.py                 ← poisson engine + 7-step FIFA tiebreaker chain
│   ├── knockout.py               ← generic round simulation primitive
│   ├── math_utils.py             ← sigmoid
│   ├── state.py                  ← generic I/O (all functions accept data_dir)
│   └── predictors/
│       ├── __init__.py
│       ├── odds.py               ← market odds fetch
│       └── catboost.py           ← CatBoost prediction fetch
│
├── competitions/
│   ├── worldcup/                 ← World Cup 2026
│   │   ├── main.py               ← WC orchestrator (live loop, governance, blending)
│   │   ├── __init__.py           ← sys.path bootstrap
│   │   ├── src/
│   │   │   ├── constants.py      ← extends football_core.constants
│   │   │   ├── groups.py         ← extends football_core.groups (WC compute_standings etc.)
│   │   │   ├── state.py          ← extends football_core.state (WC validate + governance I/O)
│   │   │   ├── elo.py            ← re-exports football_core.elo
│   │   │   ├── elo_sync.py       ← re-exports football_core.elo_sync
│   │   │   ├── fetcher.py        ← re-exports football_core.fetcher
│   │   │   ├── math_utils.py     ← re-exports football_core.math_utils
│   │   │   ├── knockout.py       ← WC-only (R32, TPP, full simulation orchestrator)
│   │   │   ├── output.py         ← WC-only display
│   │   │   ├── blender.py        ← WC-only (calibrate_and_blend)
│   │   │   ├── evaluation.py     ← WC-only (evaluate_all_matches)
│   │   │   ├── governance.py     ← WC-only (_run_governance)
│   │   │   ├── enrichment.py     ← WC-only (stats/context extraction)
│   │   │   └── predictors/
│   │   │       ├── form.py       ← WC-only
│   │   │       └── lineup.py     ← WC-only
│   │   ├── tests/                ← 613 tests, 1 skip
│   │   └── data/                 ← WC teams, groups, bracket, historical
│   │
│   ├── euro/                     ← Euro 2024
│   │   ├── main.py               ← thin orchestrator
│   │   ├── __init__.py           ← sys.path bootstrap (repo root + worldcup/)
│   │   ├── simulation.py         ← Euro simulation engine
│   │   ├── display.py            ← Euro display
│   │   ├── config.py             ← Euro constants
│   │   └── data/                 ← Euro teams, groups, bracket
│   │
│   └── ucl/                      ← placeholder (README only)
│       └── README.md
│
├── docs/
│   ├── COMMONALITY_REPORT.md
│   └── FOOTBALL_ENGINE_ARCHITECTURE.md
├── .gitignore
└── RESPONSE.md
```

### Import strategy

**Sys.path bootstrap**: `competitions/worldcup/__init__.py` adds the repo root (for `football_core`) and the worldcup package dir (for `src`) to `sys.path`. This allows `from football_core.elo import *` and `from src import constants` to work regardless of CWD.

**Re-export pattern**: Shared modules in `competitions/worldcup/src/` are thin re-export wrappers:
```python
# competitions/worldcup/src/elo.py
from football_core.elo import *  # noqa: F401,F403
```

**Extension pattern**: Modules with both shared and WC-specific code import selectively from `football_core` then add WC-only functions:
```python
# competitions/worldcup/src/groups.py
from football_core.groups import expected_goals, _tiebreak_group, ...
# then WC-specific compute_standings(), rank_third_placed(), etc.
```

---

## 2. Module Classification

### 2.1 Extracted to `football_core/` (dual-proven by WC + Euro)

| Module | Functions | Reason |
|---|---|---|
| `football_core/elo.py` | `expected_score`, `update_ratings`, `apply_elo_update`, `compute_k_factor` | Pure Elo math; `K_FACTOR` and `HOME_ADVANTAGE` come from caller/config |
| `football_core/fetcher.py` | `fetch_raw_matches`, `process_matches`, `process_group_matches` | Accepts `league_id`; BSD API URLs built via `constants.api_url_for_league(league_id)` |
| `football_core/state.py` | All load/save/validate functions | Generic; every function accepts `data_dir` parameter |
| `football_core/groups.py` (core) | `expected_goals`, `_build_poisson_table`, `_poisson_sample`, `_simulate_single_match`, `precompute_matchup_lambdas`, `simulate_group_matches`, tiebreaker chain | Pure math; iterates whatever groups dict is given |
| `football_core/knockout.py` (core) | `_simulate_knockout_round`, `_get_blended_prob` | Identical implementation in WC and Euro |
| `football_core/elo_sync.py` | `sync_elo_from_eloratings` | URL already parameterized; team code map is the remaining WC-specific part |
| `football_core/math_utils.py` | `sigmoid` | Trivial utility |
| `football_core/predictors/odds.py` | `remove_vig`, `parse_odds_response`, `fetch_and_cache_odds` | League-agnostic; accepts `groups`, `bracket`, `alias_lookup` as parameters |
| `football_core/predictors/catboost.py` | `parse_catboost_response`, `fetch_and_cache_catboost` | League-agnostic; accepts `league_id` |

### 2.2 Remains WC-Specific (single-proven)

| Module | WC Assumption | Severity |
|---|---|---|
| `competitions/worldcup/src/constants.py` | `GROUP_COUNT=12`, `TEAMS_PER_GROUP=4`, `MATCHES_PER_GROUP=6`, `ANNEX_C_*`, `WC_START_DATE`, `ELORATINGS_TEAM_CODES` (48 codes), `GOV_BACKTEST_TOURNAMENTS=["2018","2022"]`, `DEFAULT_LEAGUE_ID=27`, `LEAGUES` dict only has WC 2026 | Deep |
| `competitions/worldcup/src/groups.py` (WC extras) | `compute_standings` — hardcodes `"ABCDEFGHIJKL"`, `rank_third_placed` — picks top 8 of 12, `select_advancers` — top8_groups, `resolve_r32_matchups` — Annex C R32 logic | Deep |
| `competitions/worldcup/src/state.py` (WC extras) | `validate_groups` — 12 groups A–L, `validate_annex_c` — 495-entry table, `migrate_prediction_history`, `ledger_upsert`, governance I/O | Medium |
| `competitions/worldcup/src/knockout.py` | `ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]`, `ROUND_KEYS = {"QF": "qf", "SF": "sf", "FINAL": "final"}`, 3rd-place playoff (`TPP`), R32 Annex C resolution | Deep |
| `competitions/worldcup/src/output.py` | Header prints "WORLD CUP DYNAMIC PREDICTOR — v1.1", 12-group standings, Annex C refs | Shallow |
| `competitions/worldcup/main.py` | WC-specific pipeline; `_parse_args` sets `prog="wc-predict"`; signal key list `["elo", "market_odds", "catboost", "form", "lineup_strength"]` | Deep |
| `competitions/worldcup/src/blender.py` | Signal key list, calibration params file names | Medium |
| `competitions/worldcup/src/evaluation.py` | I/O leak via `load_prediction_history` from state | Medium |
| `competitions/worldcup/src/governance.py` | Display leak via `print_governance_dashlet` from output | Medium |
| `competitions/worldcup/src/enrichment.py` | BSD field extraction (not used by Euro) | Low |
| `competitions/worldcup/src/predictors/form.py` | WC-specific form window size | Low |
| `competitions/worldcup/src/predictors/lineup.py` | WC-specific lineup K-factor | Low |
| `competitions/worldcup/data/` | WC 2026 specific data files | Data |

### 2.3 Remains Euro-Specific

| Module | Purpose |
|---|---|
| `competitions/euro/main.py` | Thin orchestrator, different CLI |
| `competitions/euro/simulation.py` | 6-group → R16 (top 2 + 4 best 3rd) → QF → SF → FINAL |
| `competitions/euro/display.py` | Simpler probability table, no trend arrows, no signal detail |
| `competitions/euro/config.py` | 6 groups, 4 third-placed advancers, Euro league ID |
| `competitions/euro/data/` | Euro 2024 teams, groups, bracket |

### 2.4 Aspirational Destination (not yet implemented)

The following is the *ideal* end state — `football_core` with subpackages (`compute/`, `signals/`, `bsd/`, `state/`). Currently `football_core` is flat (all modules at top level). The subpackage layout is deferred until a third competition justifies the reorganization.

```
football_core/                       ← CURRENT: flat
    compute/                         ← FUTURE: subpackages
    signals/
    bsd/
    state/
```

---

## 3. Destination Architecture (aspirational)

```
football-engine/
├── football_core/              ← pip-installable package
│   ├── __init__.py              ← public API exports
│   ├── compute/
│   │   ├── __init__.py
│   │   ├── elo.py               ← elo.expected_score, update_ratings, compute_k_factor
│   │   ├── blender.py           ← calibrate_signal, apply_calibration, blend_predictions,…
│   │   ├── evaluation.py        ← brier_score, log_loss, compute_metrics, calibration_curve,…
│   │   ├── governance.py        ← _compute_data_version, _compute_model_version, check_drift,…
│   │   └── math_utils.py        ← sigmoid
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── odds.py              ← remove_vig, parse_odds_response, fetch_and_cache_odds
│   │   ├── catboost.py          ← parse_catboost_response, fetch_and_cache_catboost
│   │   ├── form.py              ← compute_form_signal
│   │   └── lineup.py            ← compute_lineup_signal
│   ├── bsd/
│   │   ├── __init__.py
│   │   ├── fetcher.py           ← fetch_raw_matches, process_matches, process_group_matches
│   │   └── enrichment.py        ← extract_stats, extract_context
│   ├── state/
│   │   ├── __init__.py
│   │   └── persistence.py       ← load/save functions (was state.py)
│   └── exceptions.py            ← Core-specific exception types
│
├── competitions/
│   ├── worldcup/
│   │   ├── main.py              ← thin CLI (was ~1500 LOC)
│   │   ├── config.py            ← WC-specific constants
│   │   ├── simulation.py        ← groups.py + knockout.py (WC-specific)
│   │   ├── display.py           ← WC-specific output
│   │   └── data/
│   │
│   ├── euro/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── simulation.py
│   │   ├── display.py
│   │   └── data/
│   │
│   ├── ucl/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── simulation.py        ← UCL 2024+ Swiss-system + knockout
│   │   ├── display.py
│   │   └── data/
│   │
│   ├── laliga/                  ← future
│   │   └── … (same pattern)
│   │
│   └── premier_league/          ← future
│       └── … (same pattern)
│
├── pyproject.toml               ← core package definition
└── README.md
```

### Data flow

```
                       ┌─────────────────┐
                       │   BSD API        │
                       └────────┬────────┘
                                │ league_id=27 or 3 or …
                                ▼
                   football_core.bsd.fetcher
                                │
                   ┌────────────┼────────────┐
                   ▼            ▼            ▼
           football_core.   football_core.  football_core.
           signals.odds     signals.catboost signals.form/lineup
                   │            │            │
                   └────────────┼────────────┘
                                ▼
                   football_core.state.persistence
                   (per-competition data/<league_id>/)
                                │
                                ▼
                   football_core.compute.blender
                   (calibrate_and_blend)
                                │
            ┌───────────────────┴───────────────────┐
            │                                       │
            ▼                                       ▼
  competitions/worldcup/                    competitions/laliga/
  simulation.py                             simulation.py
  (groups → knockout)                        (38 matchdays)
            │                                       │
            ▼                                       ▼
  competitions/worldcup/                    competitions/laliga/
  display.py                                display.py
  (champion probabilities)                   (final table)
```

**Current vs aspirational**: The data flow above is the end goal. Currently `blender.py`, `evaluation.py`, `governance.py`, `enrichment.py`, `form.py`, `lineup.py` remain in `competitions/worldcup/src/` (single-proven). They move into `football_core` only when a second competition uses them.

---

## 4. Stable Abstractions

These interfaces must never change once `football_core` is published:

### 4.1 Domain Types

```
TeamId      = str           # Canonical team name
MatchId     = str           # "GS_A_01" or "M73"
EloRating   = float         # ~1000–2500
Probability = float         # [0.0, 1.0]
EpochSec    = float         # time.time()
```

### 4.2 Match Result Schema

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

### 4.3 Signal Cache Schema

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

### 4.4 Prediction History Entry

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

### 4.5 Blend Params Schema

```python
BlendParams = {
    "calibration_params": {SignalKey: {"A": float, "B": float, ...}},
    "blend_weights": {SignalKey: float},
    "match_probs": {MatchId: Probability},
}
```

### 4.6 Governance Snapshot Schema

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

---

## 5. Current `football_core` Public API

These are the actual imports supported by the current flat `football_core/` package:

```python
# ─── Core math ───────────────────────────────────────────────────────────
from football_core.elo import (
    expected_score,               # rating_a, rating_b, home_advantage=0 → float
    compute_k_factor,             # goal_diff, base_K=60 → int
    update_ratings,               # team_a, team_b, winner, current_elos, K=60, pk_winner=None → dict
    apply_elo_update,             # match, teams → dict
)
from football_core.math_utils import (
    sigmoid,                      # x → float
)

# ─── BSD API integration ─────────────────────────────────────────────────
from football_core.fetcher import (
    fetch_raw_messages,           # api_key, api_url="", league_id=27, timeout=10 → list[dict]
    process_matches,              # raw_matches, teams, bracket, aliases, played_ids → list[dict]
    process_group_matches,        # raw_matches, teams, groups, aliases, played_group_ids, played_bsd_event_ids → list[dict]
    find_bracket_match,           # home_norm, away_norm, bracket → str | None
    find_group_match,             # home_norm, away_norm, group_letter, round_number, groups → str | None
    normalize_team,               # api_name, alias_lookup → str | None
)

# ─── State persistence ───────────────────────────────────────────────────
from football_core.state import (
    load_teams,                   # data_dir=None → dict
    save_teams,                   # teams, data_dir=None → None
    load_played,                  # data_dir=None → dict
    save_played,                  # played, data_dir=None → None
    load_played_groups,           # data_dir=None → dict
    save_played_groups,           # played_groups, data_dir=None → None
    load_signal_cache,            # cache_filename, data_dir=None → dict
    save_signal_cache,            # cache, cache_filename, data_dir=None → None
    load_prediction_history,      # data_dir=None → list[dict]
    append_prediction_history,    # entry, data_dir=None → None
    load_eloratings_cache,        # data_dir=None → dict
    save_eloratings_cache,        # cache, data_dir=None → None
    load_elo_update_log,          # data_dir=None → list[dict]
    save_elo_update_log,          # log, data_dir=None → None
    load_probability_log,         # data_dir=None → list[dict]
    append_probability_log,       # entry, data_dir=None → None
    is_cache_valid,               # cache, ttl_hours=12 → bool
    validate_bracket,             # bracket → None
    _atomic_write_json,           # data, path → None
    _resolve_data_dir,            # data_dir → Path
)

# ─── Group stage simulation ─────────────────────────────────────────────
from football_core.groups import (
    expected_goals,               # team_a, team_b, elo_ratings, base_rate=1.25, home_advantage=1.05 → tuple[float, float]
    _build_poisson_table,         # → list[float]
    _poisson_sample,              # table, rng → int
    _simulate_single_match,       # team_a, team_b, lambda_a, lambda_b, rng → dict
    precompute_matchup_lambdas,   # groups, elo_ratings, base_rate, home_advantage → dict
    simulate_group_matches,       # groups, elo_ratings, rng, base_rate=1.25, home_advantage=1.05 → dict
    _compute_conduct_score,       # yellow_cards, red_cards → float
    _compute_h2h,                 # team_a, team_b, group_results → dict
    _resolve_by_values,           # teams, group_results → list
    _resolve_tied_cluster,        # cluster, group_results, remaining → list
    _tiebreak_group,              # teams, group_results → list
)

# ─── Knockout stage simulation ──────────────────────────────────────────
from football_core.knockout import (
    _simulate_knockout_round,     # matches, teams, elo_ratings, probs, rng → dict
    _get_blended_prob,            # team_a, team_b, elo_ratings, probs → float
)

# ─── Signal predictors ──────────────────────────────────────────────────
from football_core.predictors.odds import (
    remove_vig,                   # odds_home, odds_draw, odds_away → dict
    parse_odds_response,          # bsd_events, alias_lookup, groups, bracket=None → dict
    fetch_and_cache_odds,         # api_key, bsd_events, alias_lookup, groups, cache_ttl_hours=12, bracket=None → dict
)
from football_core.predictors.catboost import (
    parse_catboost_response,      # bsd_predictions, alias_lookup, groups, bracket → dict
    fetch_and_cache_catboost,     # api_key, alias_lookup, groups, bracket, cache_ttl_hours=24, league_id=27 → dict
)

# ─── Constants ───────────────────────────────────────────────────────────
from football_core.constants import (
    K_FACTOR, DEFAULT_ELO, MAX_EXPECTED_GOALS,
    HOME_ADVANTAGE_MULTIPLIER, POISSON_TABLE_BITS, POISSON_TABLE_SIZE,
    EXPECTED_GOALS_BASE_RATE, API_TIMEOUT,
    ELO_SYNC_RETRY_BACKOFFS, ELO_SYNC_TIMEOUT,
    ELO_DRIFT_TOLERANCE, ELO_BLEND_THRESHOLD, ELO_BLEND_FACTOR,
    ELO_STALENESS_WARN_HOURS, ELORATINGS_TSV_URL,
)
```

### What stays in `competitions/worldcup/src/` (not in `football_core`)

```python
# WC-specific group stage functions
from src.groups import compute_standings, rank_third_placed, select_advancers, resolve_r32_matchups

# WC-specific state functions
from src.state import load_groups, validate_groups, load_annex_c, validate_annex_c, ...

# WC-only modules
from src.knockout import run_full_simulation
from src.output import print_header, print_probability_table, print_shutdown_banner
from src.blender import calibrate_and_blend
from src.evaluation import evaluate_all_matches
from src.governance import _run_governance
from src.constants import GROUP_COUNT, ELORATINGS_TEAM_CODES, ...
```

---

## 6. Competition Boundary

### 6.1 What a competition module MUST provide

Each competition under `competitions/<name>/` must implement:

```python
# competitions/<name>/config.py
COMPETITION_NAME: str            # "World Cup 2026"
COMPETITION_TYPE: str            # "tournament" | "league"
SIMULATION_ITERATIONS: int       # 50000
K_FACTOR: int                    # 60 for WC, 20 for league play
EXPECTED_GOALS_BASE_RATE: float  # 1.25 for WC
HOME_ADVANTAGE_MULTIPLIER: float # 1.05
DATA_DIR: Path                   # path to competition data/

# competitions/<name>/simulation.py
def run_simulation(...) -> dict[str, dict[str, float]]:
    """Return {team_name: {stage: probability}}."""
    ...

# competitions/<name>/display.py
def print_probability_table(probs, prev_probs=None, prob_log=None) -> None: ...
def print_header(teams, bracket, played, aliases, groups, annex_c) -> None: ...
def print_shutdown_banner(probs) -> None: ...
```

### 6.2 What `football_core` provides to competitions

The core exposes a single flat API:

```python
from football_core.elo import expected_score, apply_elo_update
from football_core.fetcher import fetch_raw_matches, ...
from football_core.state import load_teams, save_teams, ...
from football_core.groups import simulate_group_matches, _tiebreak_group, ...
from football_core.knockout import _simulate_knockout_round, ...
from football_core.constants import K_FACTOR, DEFAULT_ELO, ...
from football_core.predictors.odds import fetch_and_cache_odds
from football_core.predictors.catboost import fetch_and_cache_catboost
```

### 6.3 Data directory convention

```
football_core/state.py           # functions use data_dir from caller
competitions/worldcup/main.py    # passes data/<league_id> to every persistence call
```

All state persists in `competitions/<name>/data/`. Every `state.py` function accepts `data_dir`.

### 6.4 Adding a new competition

1. Create `competitions/<name>/` directory
2. Provide `config.py` with competition constants
3. Provide `simulation.py` with the competition's simulation engine
4. Provide `display.py` with competition-specific output
5. Provide competition data files in `data/`
6. Write a thin `main.py` that wires `football_core` → competition logic
7. Zero changes to `football_core/`

---

## 7. Migration Execution Summary

| Phase | Status | Description |
|---|---|---|
| Phase 1 — Build Euro | **Done** | Euro runs as `competitions/euro/`, imports generic modules |
| Phase 2 — Observe common patterns | **Done** | `COMMONALITY_REPORT.md` documents dual-proven modules |
| Phase 3 — Extract `football_core` | **Done** | Flat extraction; 12 shared modules at repo root; 613 WC tests pass; Euro sim unchanged |
| Phase 4 — Shared tournament simulation | **Deferred** | WC and Euro simulation differ too much (R32 vs R16 entry, Annex C vs precomputed) |
| Phase 5 — League abstraction | **Future** | Pending third competition (UCL or league) |

### Key decisions made during execution

- **Flat package over subpackages**: `football_core/` modules are flat to minimize friction. Subpackage split into `compute/`, `signals/`, `bsd/`, `state/` is deferred until a third competition justifies the reorganization.
- **Sys.path bootstrap over absolute imports**: `from football_core import *` works via `sys.path` manipulation in `__init__.py` rather than rewriting all import paths to use `competitions.worldcup.src.elo`. This avoids touching every module.
- **Re-export wrappers kept**: `competitions/worldcup/src/elo.py` remains as `from football_core.elo import *` to avoid changing all internal `from src import` references in WC-specific modules.
- **Euro sys.path hack retained**: `competitions/euro/__init__.py` still adds `competitions/worldcup/` to path because Euro imports `from src.groups import compute_standings` for historical catch-up.

### Remaining work

| Item | Priority |
|---|---|
| Extract single-proven modules when second competition needs them (blender, evaluation, governance, form, lineup) | Low |
| Reorganize `football_core` into subpackages when justified | Low |
| Remove Euro sys.path hack by refactoring `resolve_knockout_slot_teams` | Low |
| Parameterize `compute_standings`/`rank_third_placed`/`select_advancers` for group count/labels | Medium |
| Build UCL or league competition to prove more abstractions | High |
