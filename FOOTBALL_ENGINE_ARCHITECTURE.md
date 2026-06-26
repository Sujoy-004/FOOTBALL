# Football Engine Architecture

## 1. Current Architecture

```
worldcup_predictor/          ← single-competition monolith
├── main.py                  ← god object (1538 LOC, 21 functions)
├── src/
│   ├── constants.py         ← mixed: 70% WC, 30% generic
│   ├── elo.py               ← generic
│   ├── elo_sync.py          ← mostly generic (URL is WC-specific)
│   ├── fetcher.py           ← generic (accepts league_id)
│   ├── state.py             ← generic (all functions accept data_dir)
│   ├── groups.py            ← WC-specific (12 groups, Annex C, R32 definition)
│   ├── knockout.py          ← WC-specific (R32→R16→QF→SF→FINAL, M73-M88)
│   ├── blender.py           ← generic (pure computation, no I/O)
│   ├── evaluation.py        ← generic (pure computation, but has I/O leak)
│   ├── governance.py        ← generic (pure computation, but has display leak)
│   ├── enrichment.py        ← generic
│   ├── math_utils.py        ← generic
│   ├── output.py            ← mostly generic (some WC branding)
│   └── predictors/
│       ├── odds.py          ← generic
│       ├── catboost.py      ← generic
│       ├── form.py          ← generic
│       └── lineup.py        ← generic
└── data/
    ├── group.json           ← WC: 12 groups A–L, 48 teams
    ├── bracket.json         ← WC: 104-match bracket
    ├── annex_c.json         ← WC: third-place advancement table
    ├── teams.json           ← WC: 48 teams with Elo
    └── historical/          ← WC: [2018, 2022]
```

### Cross-cutting problem

`main.py` is the **sole orchestrator**. Every signal pipeline, simulation flow, and display decision is hard-wired in one 1538-line module. To add a new competition you must fork the entire repo (as `euro_predictor/` and `ucl_predictor/` are currently empty README stubs).

---

## 2. Module Classification

### 2.1 Already Generic — zero WC assumptions in logic

| Module | Functions | Reason |
|---|---|---|
| `src/elo.py` | `expected_score`, `update_ratings`, `apply_elo_update`, `compute_k_factor` | Pure Elo math; `K_FACTOR` and `HOME_ADVANTAGE` come from caller/config |
| `src/blender.py` | `calibrate_signal`, `apply_calibration`, `compute_rolling_brier`, `compute_blend_weights`, `blend_predictions`, `calibrate_and_blend` | Pure computation; signal keys, window sizes, thresholds passed as parameters |
| `src/evaluation.py` | `brier_score`, `log_loss`, `compute_metrics`, `calibration_curve`, `expected_calibration_error`, `evaluate_all_matches`, `backtest_tournament` | Pure math — **but**: I/O leak via `load_prediction_history` and `append_prediction_history` from `state` |
| `src/governance.py` | Version computation, drift detection, `_run_governance` | Pure computation — **but**: display leak via `print_governance_dashlet` from `output` |
| `src/enrichment.py` | `extract_stats`, `extract_context` | Stateless BSD field extraction |
| `src/math_utils.py` | `sigmoid` | Trivial utility |
| `src/predictors/odds.py` | `remove_vig`, `parse_odds_response`, `fetch_and_cache_odds` | League-agnostic; accepts `groups`, `bracket`, `alias_lookup` as parameters |
| `src/predictors/catboost.py` | `parse_catboost_response`, `fetch_and_cache_catboost` | League-agnostic; accepts `league_id` |
| `src/predictors/form.py` | `compute_form_signal` | League-agnostic; accepts `played`, `played_groups`, `teams` as parameters |
| `src/predictors/lineup.py` | `compute_lineup_signal` | League-agnostic; accepts `team_values` as parameter |
| `src/state.py` | All load/save/validate functions | Generic; every function accepts `data_dir` parameter |
| `src/fetcher.py` | `fetch_raw_matches`, `process_matches`, `process_group_matches` | Accepts `league_id`; BSD API URLs built via `constants.api_url_for_league(league_id)` |

### 2.2 World-Cup-Specific

| Module | WC Assumption | Severity |
|---|---|---|
| `src/constants.py` | `GROUP_COUNT=12`, `TEAMS_PER_GROUP=4`, `MATCHES_PER_GROUP=6`, `ANNEX_C_ENTRIES=495`, `ANNEX_C_WINNER_GROUPS`, `WC_START_DATE`, `ELORATINGS_TSV_URL`, `ELORATINGS_TEAM_CODES` (48 codes), `K_FACTOR=60`, `EXPECTED_GOALS_BASE_RATE=1.25`, `HOME_ADVANTAGE_MULTIPLIER=1.05`, `GOV_BACKTEST_TOURNAMENTS=["2018","2022"]`, `DEFAULT_LEAGUE_ID=27`, `LEAGUES` dict only has WC 2026 | Deep |
| `src/groups.py` | 12 groups A–L hardcoded (`"ABCDEFGHIJKL"`), FIFA 7-step tiebreaker (steps 1-7), Annex C C(12,8)=495 lookup, R32 matchups M73–M88 hardcoded in `resolve_r32_matchups` | Deep |
| `src/knockout.py` | `ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]`, `ROUND_KEYS = {"QF": "qf", "SF": "sf", "FINAL": "final"}`, 3rd-place playoff (`TPP`), bracket source-match wiring | Deep |
| `src/output.py` | Header prints "WORLD CUP DYNAMIC PREDICTOR — v1.1" | Shallow |
| `main.py` | Orchestrates WC-specific pipeline; `_parse_args` sets `prog="wc-predict"`; `_run_iteration` is WC pipeline; signal key list `["elo", "market_odds", "catboost", "form", "lineup_strength"]` | Deep |
| `data/groups.json` | 12 groups of 4 = 48 WC teams | Data |
| `data/bracket.json` | WC 2026 bracket structure (R32→R16→…) | Data |
| `data/annex_c.json` | WC 2026 third-place advancement | Data |
| `data/teams.json` | 48 WC teams with Elo ratings | Data |
| `data/historical/2018.json`, `2022.json` | Historical WC data | Data |

### 2.3 Destination: `football_core` Package (Rule of Two — not yet extracted)

All modules in 2.1 are candidates for eventual extraction into `football_core`, but **no extraction happens until at least two competitions prove the abstractions are right**.

- **Pure computation layer** → `football_core/compute/`
  - `elo.py`
  - `blender.py`
  - `evaluation.py`
  - `governance.py`
  - `math_utils.py`

- **Signal ingestion layer** → `football_core/signals/`
  - `predictors/odds.py` → `signals/odds.py`
  - `predictors/catboost.py` → `signals/catboost.py`
  - `predictors/form.py` → `signals/form.py`
  - `predictors/lineup.py` → `signals/lineup.py`

- **BSD integration layer** → `football_core/bsd/`
  - `fetcher.py`
  - `enrichment.py`

- **State layer** → `football_core/state/`
  - `state.py`

**Rule of Two**: Extraction happens only after the Euro and World Cup implementations are both running and their common patterns are proven. The architecture diagram in §3 is the *destination*, not the *starting path*.

### 2.4 Remains Competition-Specific

| Item | Reason |
|---|---|
| `worldcup_predictor/` | Competition entry point, CLI, WC-specific orchestrator, WC data files |
| `competitions/euro/` | Competition entry point, Euro-specific constants/simulation/data |
| `competitions/ucl/` | Competition entry point, UCL-specific constants/simulation/data |
| **Future:** `competitions/laliga/` | League-style simulation (double round-robin, no groups/knockout) |
| **Future:** `competitions/premier_league/` | Same as La Liga with different constants/data |

Each competition directory owns:
- Its own `main.py` (thin orchestrator using `football_core`)
- Its own `config.py` (competition-specific constants)
- Its own `simulation.py` (competition-specific engine)
- Its own `output.py` (competition-specific display)
- Its own `data/` directory (teams, fixtures, etc.)

---

## 3. Destination Architecture (after Rule of Two extraction)

```
football-engine/
├── football_core/              ← pip-installable package (extracted in Phase 3)
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
│   │   ├── main.py              ← thin CLI (20-50 LOC, was 1538)
│   │   ├── config.py            ← WC-specific constants
│   │   ├── simulation.py        ← groups.py + knockout.py (WC-specific)
│   │   ├── display.py           ← WC-specific output
│   │   ├── data/
│   │   │   ├── teams.json
│   │   │   ├── groups.json
│   │   │   ├── bracket.json
│   │   │   ├── annex_c.json
│   │   │   └── historical/
│   │   └── tests/
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
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── simulation.py        ← 38-matchday double round-robin
│   │   ├── display.py           ← Final table, relegation zone
│   │   └── data/
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
           signals.odds     signals.catboost signs.form/lineup
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
                                ▼
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
# Every signal cache follows this shape:
SignalCache = {
    "fetched_at": str,       # ISO 8601
    "expires_at": str,       # ISO 8601
    "matches": {
        MatchId: {
            "probability": Probability | None,
            "available": bool,
            "timestamp": str,
            "reason": str | None,    # if not available
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
    "blend_weights": {SignalKey: float},    # sums to 1.0
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

## 5. Public Interfaces

### 5.1 `football_core.compute.elo`

```python
def expected_score(rating_a: float, rating_b: float, home_advantage: int = 0) -> float
def compute_k_factor(goal_diff: int, base_K: int = 60) -> float
def update_ratings(team_a: str, team_b: str, winner: str | None,
                   current_elos: dict[str, float], K: int = 60,
                   pk_winner: str | None = None) -> dict[str, float]
def apply_elo_update(match: dict, teams: dict[str, dict]) -> dict[str, dict[str, float]]
```

### 5.2 `football_core.compute.blender`

```python
def calibrate_signal(predictions: list[float], actuals: list[float],
                     threshold: int = 30) -> tuple[float, float]
def apply_calibration(p_raw: float, A: float, B: float) -> float
def compute_rolling_brier(entries: list[dict], signal_key: str,
                          window: int = 50) -> float
def compute_blend_weights(signal_briers: dict[str, float]) -> dict[str, float]
def blend_predictions(signal_preds: dict[str, float],
                      weights: dict[str, float]) -> float
def calibrate_and_blend(history: list[dict], signal_keys: list[str],
                        elo_ratings: dict[str, float],
                        groups_data: dict, bracket_data: list[dict],
                        odds_cache: dict, cb_cache: dict,
                        brier_window: int = 50,
                        cold_start_threshold: int = 30,
                        form_cache: dict | None = None,
                        lineup_cache: dict | None = None) -> dict | None
def compute_poisson_base_rate(match_data_path: str | None = None) -> float
```

### 5.3 `football_core.compute.evaluation`

```python
def brier_score(prediction: float, actual: float) -> float
def log_loss(prediction: float, actual: float, eps: float = 1e-15) -> float
def compute_metrics(predictions: list[float], actuals: list[float]) -> dict
def calibration_curve(predictions: list[float], actuals: list[float],
                      n_bins: int = 10) -> dict
def expected_calibration_error(calibration: dict) -> float
def evaluate_all_matches(teams: dict, played: dict, played_groups: dict,
                         signal_name: str | None = None) -> dict
def backtest_tournament(tournament_matches: list[dict], teams: dict,
                        tournament_name: str = "") -> dict
```

### 5.4 `football_core.compute.governance`

```python
def check_drift(entries: list[dict], signal_key: str, reference_baseline: float,
                window: int = 50, sigma_threshold: float = 2.0) -> dict | None
def compute_reference_baselines(entries: list[dict],
                                signal_keys: list[str]) -> dict[str, float]
def _run_governance(entries: list[dict], versions: dict, signal_keys: list[str],
                    blend_weights: dict[str, float], startup: bool = False,
                    teams: dict | None = None,
                    data_dir: Path | str | None = None) -> dict
```

### 5.5 `football_core.signals.*`

```python
# odds
def remove_vig(odds_home: float, odds_draw: float, odds_away: float) -> dict[str, float]
def parse_odds_response(bsd_events: list[dict], alias_lookup: dict[str, str],
                        groups: dict, bracket: list[dict] | None = None) -> dict[str, dict]
def fetch_and_cache_odds(api_key: str, bsd_events: list[dict],
                         alias_lookup: dict[str, str], groups: dict,
                         cache_ttl_hours: int = 12,
                         bracket: list[dict] | None = None) -> dict

# catboost
def parse_catboost_response(bsd_predictions: list[dict],
                            alias_lookup: dict[str, str],
                            groups: dict, bracket: list[dict]) -> dict[str, dict]
def fetch_and_cache_catboost(api_key: str, alias_lookup: dict[str, str],
                             groups: dict, bracket: list[dict],
                             cache_ttl_hours: int = 24,
                             league_id: int = 27) -> dict

# form
def compute_form_signal(teams: dict, groups: dict, played: dict | None = None,
                        played_groups: dict | None = None,
                        bracket: list[dict] | None = None,
                        k_factor: float | None = None,
                        form_window: int | None = None) -> dict

# lineup
def compute_lineup_signal(groups: dict, team_values: dict | None = None,
                          bracket: list[dict] | None = None,
                          k_factor: float | None = None) -> dict
```

### 5.6 `football_core.state.persistence`

```python
def load_teams(data_dir: Path | str | None = None) -> dict[str, dict]
def load_bracket(data_dir: Path | str | None = None) -> list[dict]
def load_groups(data_dir: Path | str | None = None, teams: ... = None) -> dict
def load_played(data_dir: Path | str | None = None) -> dict[str, dict]
def load_played_groups(data_dir: Path | str | None = None) -> dict[str, dict]
def load_aliases(data_dir: Path | str | None = None) -> dict[str, list[str]]
def save_teams(teams: dict, data_dir: ... = None) -> None
def save_played(played: dict, data_dir: ... = None) -> None
def save_played_groups(played_groups: dict, data_dir: ... = None) -> None
def load_prediction_history(data_dir: ... = None) -> list[dict]
def append_prediction_history(entry: dict, data_dir: ... = None) -> None
def load_signal_cache(cache_filename: str, data_dir: ... = None) -> dict
def save_signal_cache(cache: dict, cache_filename: str, data_dir: ... = None) -> None
def load_calibration_params(data_dir: ... = None) -> dict
def save_calibration_params(params: dict, data_dir: ... = None) -> None
def load_prediction_ledger(data_dir: ... = None) -> dict[str, dict]
def save_prediction_ledger(ledger: dict, data_dir: ... = None) -> None
def ledger_upsert(match_id: str, signal_name: str, entry: dict, data_dir: ... = None) -> None
def is_cache_valid(cache: dict, ttl_hours: int = 12) -> bool
def load_versions(data_dir: ... = None) -> dict
def save_versions(versions: dict, data_dir: ... = None) -> None
def save_run_snapshot(snapshot: dict, data_dir: ... = None) -> None
def save_backtest_report(report: dict, data_dir: ... = None) -> None
def load_probability_log(data_dir: ... = None) -> list[dict]
def append_probability_log(snapshot: dict, data_dir: ... = None) -> None
```

### 5.7 `football_core.bsd.fetcher`

```python
def fetch_raw_matches(api_key: str, api_url: str = "", league_id: int = 27,
                      timeout: int = 10) -> list[dict]
def process_matches(raw_matches: list[dict], teams: dict, bracket: list[dict],
                    aliases: dict, played_ids: set[str]) -> list[dict]
def process_group_matches(raw_matches: list[dict], teams: dict, groups: dict,
                          aliases: dict, played_group_ids: set[str],
                          played_bsd_event_ids: set[str]) -> list[dict]
def find_bracket_match(home_norm: str, away_norm: str,
                       bracket: list[dict]) -> str | None
def find_group_match(home_norm: str, away_norm: str, group_letter: str,
                     round_number: int, groups: dict) -> str | None
def normalize_team(api_name: str, alias_lookup: dict[str, str]) -> str | None
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
def run_simulation(
    teams: dict[str, dict],
    groups: dict | None,
    bracket: list[dict] | None,
    annex_c: dict | None,
    played: dict[str, dict],
    iterations: int,
    seed: int | None = None,
    played_groups: dict[str, dict] | None = None,
    blend_params: dict | None = None,
    **competition_kwargs,
) -> dict[str, dict[str, float]]:
    """Return {team_name: {stage: probability}}.
    
    For tournaments: stages = {qf, sf, final, champion}.
    For leagues: stages = {champion, ucl, relegation, avg_points}.
    """
    ...

# competitions/<name>/display.py
def print_probability_table(probs: dict, prev_probs: dict | None = None,
                            prob_log: list[dict] | None = None) -> None: ...
def print_header(teams, bracket, played, aliases, groups, annex_c) -> None: ...
def print_shutdown_banner(probs: dict) -> None: ...
```

### 6.2 What `football_core` provides to competitions

The core exposes a **single orchestrator protocol**:

```python
from football_core.compute.blender import calibrate_and_blend
from football_core.compute.elo import expected_score, apply_elo_update
from football_core.compute.evaluation import evaluate_all_matches
from football_core.compute.governance import _run_governance
from football_core.bsd.fetcher import fetch_raw_matches, ...
from football_core.bsd.enrichment import extract_stats, extract_context
from football_core.signals.odds import fetch_and_cache_odds
from football_core.signals.catboost import fetch_and_cache_catboost
from football_core.signals.form import compute_form_signal
from football_core.signals.lineup import compute_lineup_signal
from football_core.state.persistence import (load_teams, save_teams, ...)
```

### 6.3 Data directory convention

```
football_core/state/persistence.py  # functions use data_dir from caller
competitions/worldcup/main.py       # passes data/<league_id> to every persistence call
```

All state persists in `competitions/<name>/data/<league_id>/`. This already works — every `state.py` function accepts `data_dir`.

### 6.4 Adding a new competition

1. Create `competitions/<name>/` directory
2. Provide `config.py` with competition constants
3. Provide `simulation.py` with the competition's simulation engine
4. Provide `display.py` with competition-specific output
5. Provide competition data files in `data/`
6. Write a thin `main.py` that wires `football_core` → competition logic
7. Zero changes to `football_core/`

---

## 7. Migration Strategy (Rule of Two)

The strategy follows the **Rule of Two**: extract nothing until at least two independent implementations prove the abstraction is right. Optimize for the minimum necessary abstraction at each step.

```
Phase 1: Build Euro (imports generic modules from worldcup_predictor.src/)
           ↓
Phase 2: Observe common patterns and document shared abstractions
           ↓
Phase 3: Extract proven common modules into football_core/
           ↓
Phase 4: Extract shared tournament simulation (if warranted)
           ↓
Phase 5: League abstraction + La Liga
```

### Phase 1 — Build Euro Predictor (minimum necessary duplication)

Euro imports *generic* modules from `worldcup_predictor.src/` directly — no shared package exists yet. Only competition-specific code is newly created.

| Step | Action | Risk |
|---|---|---|
| 1.1 | Fix `evaluation.py` I/O leak and `governance.py` display leak in-place (benefits both competitors, zero extraction) | Low |
| 1.2 | Make `elo_sync.py` `ELORATINGS_TSV_URL` a parameter (currently a constant import) | Low |
| 1.3 | Create `competitions/euro/config.py` — 24 teams, 6 groups A–F, no Annex C, no 3rd place playoff, `K_FACTOR`, `EXPECTED_GOALS_BASE_RATE`, league_id for BSD | Low |
| 1.4 | Create `competitions/euro/simulation.py` — 6 groups → R16 (top 2 + 4 best 3rd) → QF → SF → FINAL. No Annex C resolution needed (fewer groups). No 3rd place playoff match | Medium |
| 1.5 | Create `competitions/euro/display.py` — Euro-specific header, probability table, shutdown banner | Low |
| 1.6 | Create `competitions/euro/main.py` — thin Euro orchestrator; imports `state`, `elo`, `blender`, `predictors.*`, `fetcher`, `enrichment` from `worldcup_predictor.src.*` | Medium |
| 1.7 | Create `competitions/euro/data/` — teams.json, groups.json, bracket.json, historical data | Low |
| 1.8 | Add `euro_predictor` entry point / CLI alias | Low |
| 1.9 | Verify Euro runs end-to-end (simulate, save, display) | — |
| 1.10 | Verify WC runs unchanged (regression test: all 613 tests pass) | — |

**What Euro imports from worldcup_predictor.src/ (not duplicated):**
`elo.py`, `blender.py`, `evaluation.py`, `governance.py`, `math_utils.py`, `predictors/`, `state.py`, `fetcher.py`, `enrichment.py`, core `constants.py` entries (generic subset).

**What Euro creates anew (competition-specific):**
`config.py`, `simulation.py`, `display.py`, `main.py`, `data/` files.

### Phase 2 — Observe & Document Common Patterns

| Step | Action | Risk |
|---|---|---|
| 2.1 | Compare WC `main.py` and Euro `main.py` — identify shared pipeline structure (fetch → predict → blend → simulate → display) | Low |
| 2.2 | Compare simulation engines — parameterize group count, knockout depth, group advancement rules | Low |
| 2.3 | Compare configs — distinguish competition-specific constants from generic defaults | Low |
| 2.4 | Compare `output.py` / `display.py` — identify shared display patterns | Low |
| 2.5 | Produce `COMMONALITY_REPORT.md` — documented shared abstractions with evidence from both competitors | Low |

**Expected outcome:** A precise list of modules that were imported unchanged by both competitors. These are the *proven* candidates for `football_core`.

### Phase 3 — Extract `football_core` (now proven by two implementations)

| Step | Action | Risk |
|---|---|---|
| 3.1 | Create `football_core/` package with `pyproject.toml`, `__init__.py`, sub-package structure | Low |
| 3.2 | Move proven generic modules from `worldcup_predictor/src/` to `football_core/compute/`, `signals/`, `bsd/`, `state/` | Low |
| 3.3 | Create `football_core/exceptions.py` for core-specific error types | Low |
| 3.4 | Update `worldcup_predictor/` imports to use `football_core` package | Medium |
| 3.5 | Update `competitions/euro/main.py` imports to use `football_core` package | Low |
| 3.6 | Move shared generic constants from `constants.py` into `football_core` | Low |
| 3.7 | Verify all 613 WC tests + any Euro tests pass | — |

**Key difference from pre-Rule-of-Two extraction:** The list of modules in `football_core` is now an *empirical fact* (both competitors used them unchanged) rather than a design guess.

### Phase 4 — Extract Shared Tournament Simulation (if patterns from Phase 2 warrant it)

| Step | Action | Risk |
|---|---|---|
| 4.1 | Extract tournament-generic simulation into `football_core/compute/tournament.py` | Medium |
| 4.2 | WC and Euro `simulation.py` both call the shared function with different config | Low |
| 4.3 | Verify both competitions produce identical results to pre-extraction | — |

This phase is **optional** — only extract if Phase 2.2 reveals a clean shared abstraction. The WC R32→R16 and Euro R16→QF patterns differ in depth and advancement rules; the commonality may be too shallow to justify extraction.

### Phase 5 — League Abstraction + La Liga (future)

| Step | Action | Risk |
|---|---|---|
| 5.1 | Build `competitions/laliga/config.py`, `simulation.py` (38-matchday double round-robin), `display.py` | High |
| 5.2 | Extract shared round-robin pattern into `football_core/compute/league.py` (only after 2+ leagues exist) | Medium |

---

## 8. Estimates

### Work packages

| # | Phase | Description | Commits | Effort |
|---|---|---|---|---|
| WP-1 | Phase 1 | Build Euro predictor (fix leaks first, then Euro-specific code + data, import generic modules from WC) | ~12 | 3–4 days |
| WP-2 | Phase 2 | Observe and document common patterns between WC and Euro | ~2 | 1 day |
| WP-3 | Phase 3 | Extract `football_core` from proven commonalities, migrate both competitors | ~12 | 2–3 days |
| WP-4 | Phase 4 | Extract shared tournament simulation (if warranted by Phase 2 findings) | ~5 | 1 day |
| WP-5 | Phase 5 | League abstraction + La Liga | ~15 | 3–5 days |

**Total: 5 work packages, ~46 commits**

**Comparison with original plan:** The Rule of Two shifts the extraction (formerly WP-1) to Phase 3 (WP-3), after the Euro implementation has proven which abstractions are real. Total effort is roughly similar, but risk is lower because every extraction decision is empirically validated.

### Technical risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| R1 | `worldcup_predictor/src/` changes during Phase 1.1 (I/O leak fixes) break WC tests | Medium | High | Fix leaks with backward-compatible signatures; run full test suite after each change |
| R2 | Euro `simulation.py` reveals the WC groups/knockout split was actually clean and shareable — but we're not extracting yet (by design) | Low | Low | Accept duplication; document patterns in Phase 2; extract in Phase 3 |
| R3 | BSD API key / league_id differences between WC and Euro require nontrivial changes to generic fetcher modules | Medium | Medium | Fix in `worldcup_predictor/src/` before Euro uses it; both benefit |
| R4 | `evaluation.py` I/O leak has callers depending on side effects | Medium | Medium | Audit all callers; add data parameter with backward-compat default |
| R5 | `governance.py` display leak hard to untangle | Medium | Medium | Return structured dict; migrate callers one at a time |
| R6 | UCL 2024+ Swiss-system format doesn't fit tournament or league pattern | Medium | High | Design `simulation.py` protocol to accept arbitrary stage graph (deferred until UCL phase) |
| R7 | BSD API contract changes break shared modules | Low | High | Version the API surface; integration tests with mock data |
| R8 | Team name normalization is per-competition, creates friction | Low | Low | Each competition provides its own `alias_lookup` dict |
