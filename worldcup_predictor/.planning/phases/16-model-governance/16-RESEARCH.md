# Phase 16: Model Governance — Research

**Researched:** 2026-06-17
**Domain:** Model governance — version tracking, drift detection, backtesting
**Confidence:** HIGH (decisions locked in CONTEXT.md, all integration points read and verified)

## Summary

Phase 16 adds the three pillars of model governance to the existing World Cup predictor pipeline: (1) three-version tracking (data/model/run), (2) per-signal Brier monitoring with drift detection, and (3) backtesting against historical World Cups (2018 + 2022). This phase is a **wrapping layer** — it does not change how calibration or blending works. Everything in CONTEXT.md D-01 through D-25 is the authoritative design contract.

**Primary recommendation:** The governance system is read-mostly: it reads prediction_history + calibration_params + prediction ledger, computes metrics, and writes versions + run snapshots + backtest reports. It never modifies upstream data. Hook into `_run_iteration()` **after** signal warnings (line ~690) and **before** simulation (line ~700). Separate pure-computation (`evaluation.py`-style) from output (`output.py`-style).

## Requirements Traceability

| ID | Requirement | Status | Implementation Pattern |
|----|-------------|--------|----------------------|
| V2-12 | Model version, data version, run version tracked | 🔲 | `data/versions.json` + per-entry version IDs in `prediction_history.json` |
| V2-13 | Per-signal Brier scoring with drift detection | 🔲 | Compute rolling Brier → compare vs reference baseline → alert if > 2σ |
| V2-14 | Backtesting framework against historical World Cups | 🔲 | Static tournament files → replay through evaluation pipeline → report |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Version tracking (read/write) | **State** (`state.py`) | **Orchestrator** (`main.py`) | Atomic JSON persistence via existing `_atomic_write_json()` — task is file I/O, not computation |
| Version increment logic | **Governance** (`governance.py`) | — | Pure logic: detect what changed, compute new versions. No I/O. |
| Rolling Brier computation | **Blender** (`blender.py`) | — | `compute_rolling_brier()` already exists — reuse directly |
| Drift detection | **Governance** (`governance.py`) | — | New pure function: `check_drift(per_signal_briers, reference_baselines, rolling_sigma)` |
| Backtesting computation | **Evaluation** (`evaluation.py`) | **Governance** (`governance.py`) | Follows `evaluate_all_matches()` pattern — iterate over historical matches, collect predictions, compute metrics |
| Governance dashlet display | **Output** (`output.py`) | — | `print_governance_dashlet()` + `print_drift_alert()`, following existing ANSI patterns |
| Run snapshot persistence | **State** (`state.py`) | — | `save_run_snapshot()` — atomic JSON write following `save_signal_cache()` pattern |

## Integration Point Analysis

### Integration 1: `main.py:_run_iteration()` (lines 500–715)

**What it does:** The main pipeline loop: fetch → process matches → signal refresh → merge → calibrate/blend → simulate → print.

**Key hook locations:**

| Line | Existing Code | Governance Hook |
|------|--------------|-----------------|
| 648 | `_merge_signals_into_history()` | Pre-condition for governance — prediction_history must be current |
| 651 | `_run_calibrate_and_blend()` | Produces `blend_params` with calibration data; governance reads calibration_params.json after this |
| 689 | Signal warnings aggregated/printed | **PRIMARY HOOK POINT**: Governance dashlet inserts here — after all signal refresh + blending, before simulation |
| 700 | `sim_start = time.time()` | Simulation begins — governance must execute before this |

**Specific hook insertion (line ~690):**

```python
# ── Model Governance (Phase 16) ──
_run_governance(state.load_prediction_history())
```

Where `_run_governance()` is a new orchestrator that:
1. Loads/determines current versions (D-01 through D-07)
2. Computes per-signal rolling Brier (reuses `blender.compute_rolling_brier()`)
3. Checks drift against reference baselines (D-08, D-09)
4. Saves run snapshot (D-06)
5. Prints governance dashlet (D-16 through D-19)

**Call frequency:** Startup + hourly + on drift detection (D-16), NOT every heartbeat.

**How to determine if governance should run:**
```python
_last_gov_time: float = 0.0
GOV_INTERVAL: int = 3600  # hourly

def _should_run_gov() -> bool:
    global _last_gov_time
    now = time.time()
    if _last_gov_time == 0.0:  # startup
        return True
    if now - _last_gov_time >= GOV_INTERVAL:  # hourly
        return True
    # Also triggered if drift detected — this flows through
    return False
```

---

### Integration 2: `main.py:main()` (lines 749–887)

**What it does:** Startup sequence: load state → historical catch-up → backfill → baseline → migrate → seed CatBoost → merge → sync Elo → print header → enter poll loop.

**Key hook location — after header (line 828), once mode check (line 831):**

```python
output.print_header(teams, bracket, played, aliases, groups, annex_c)

# ── Governance startup: versions initialize, backtest runs, dashlet prints ──
if _should_run_gov():  # always True at startup
    _run_governance(startup=True)
```

**One-shot backtesting:** `_run_backtest()` call should happen at startup, before `--once` mode check, so backtest results appear before first simulation output.

Where `_run_backtest()`:
1. Loads historical tournament files from `data/historical/`
2. Iterates each tournament via `evaluation.evaluate_all_matches()` pattern (but over historical data, not prediction_history)
3. Produces per-tournament + aggregate report
4. Saves to `data/eval_backtest_report.json` (new file)
5. Prints summary in governance dashlet

---

### Integration 3: `worldcup_predictor/src/evaluation.py` (314 lines)

**What it does:** Pure-computation metrics suite — `brier_score()`, `log_loss()`, `compute_metrics()`, `calibration_curve()`, `evaluate_all_matches()`, `compare_baselines()`.

**What's reusable for backtesting:**

| Function | Reuse | How |
|----------|-------|-----|
| `brier_score(p, actual)` | **Direct** | Compute per-match Brier in backtest loop |
| `log_loss(p, actual)` | **Direct** | Compute per-match log loss in backtest loop |
| `compute_metrics(preds, actuals)` | **Direct** | Aggregate Brier, log loss, accuracy for tournament |
| `calibration_curve(preds, actuals)` | **Direct** | Calibration + ECE for each tournament |
| `calibration_curve()` return shape | **Direct** | `{"bins": [...], "ece": float}` — same format |
| `evaluate_all_matches()` loop pattern | **Pattern** | Iterates prediction_history by signal key — backtesting iterates historical match files instead |

**What to add (new functions, extending evaluation.py):**

```python
def backtest_tournament(tournament_matches: list[dict], signal_funcs: dict[str, callable]) -> dict:
    """Replay a historical tournament through current signal pipeline.
    
    Args:
        tournament_matches: List of historical match dicts with teams, actual outcomes.
        signal_funcs: Dict mapping signal_name -> callable(match) -> probability.
    
    Returns per-tournament report dict with same shape as evaluate_all_matches() output.
    """
```

**How `evaluate_all_matches()` iterates (reusable pattern for backtesting):**
```python
# Lines 96-165: loads prediction_history, groups by signal key,
# collects (prediction, actual) pairs per signal, computes metrics per signal.
# Backtesting replaces "load prediction_history" with "load tournament file"
# and "read from entry['signals'][key]" with "call signal_funcs[key](match)".
```

**Data shape expected by evaluate_all_matches() signal iteration:**
```python
# Each entry in prediction_history has:
entry = {
    "match_id": str,
    "team_a": str,
    "team_b": str,
    "actual": float,           # 0.0, 0.5, or 1.0
    "signals": {
        "elo": {
            "probability": float,
            "version": str,     # Phase 16 adds data_version/model_version/run_version
            "available": bool,
            ...
        },
        "market_odds": { ... },
        "catboost": { ... },
        "form": { ... },
        "lineup_strength": { ... },
    }
}
```

---

### Integration 4: `worldcup_predictor/src/blender.py` (460 lines)

**What it does:** Platt scaling, Brier-weighted blending, rolling Brier computation, Poisson base rate.

**Key reusable function — `compute_rolling_brier()` (lines 164-200):**

```python
def compute_rolling_brier(entries: list[dict], signal_key: str, window: int = BRIER_WINDOW_SIZE) -> float:
```

Accepts `prediction_history` entries directly as parameter — **no file I/O**. This is the exact function drift detection needs.

**How to use for drift detection:**
```python
# Extract per-match Brier scores for rolling sigma computation
def _per_match_briers(entries: list[dict], signal_key: str) -> list[float]:
    """Get list of per-match Brier scores for a signal, ordered chronologically."""
    pairs = []
    for entry in entries:
        signals = entry.get("signals", {})
        sig = signals.get(signal_key, {})
        if not sig.get("available", False):
            continue
        prob = sig.get("probability")
        actual = entry.get("actual")
        if prob is None or actual is None:
            continue
        pairs.append((prob, actual))
    return [(p - a) ** 2 for p, a in pairs]
```

**What `calibrate_and_blend()` (line 368) stores in calibration_params.json:**
```python
# Current shape (calibration_params.json):
{
    "elo": {"A": 1.0, "B": 0.0, "n_matches": 0, "brier": 1.0, "fitted_at": "cold_start"},
    "market_odds": { ... },
    "catboost": { ... },
    "form": { ... },
    "lineup_strength": { ... },
}
```

Per-signal `brier` is already stored here after each blend cycle — governance can read calibration_params.json directly without recomputing rolling Brier (though it should recompute for drift detection to ensure current state).

---

### Integration 5: `worldcup_predictor/data/prediction_history.json`

**Current structure (lines 1-50 show representative entries):**
```json
{
    "match_id": "GS_A_01",
    "timestamp": "2026-06-17T06:53:30.223939+00:00",
    "team_a": "Mexico",
    "team_b": "South Africa",
    "actual": 1.0,
    "signals": {
        "elo": {
            "probability": 0.8938,
            "version": "v1",
            "timestamp": "2026-06-17T06:53:30.223939+00:00",
            "available": true,
            "team_a_elo": 1881.0,
            "team_b_elo": 1511.0
        },
        "form": { "probability": 0.5529, "timestamp": "...", "available": true },
        "lineup_strength": { "probability": 0.6681, "timestamp": "...", "available": true }
    }
}
```

**Phase 16 additions (D-05):**
- Each entry gets `data_version: str`, `model_version: str`, `run_version: str` at the top level
- Not buried inside each signal dict — one version triplet per entry because all signals in one entry share the same data/model/run context

**Where to insert version IDs:** During `_merge_signals_into_history()` and/or after calibration+blend in `_run_iteration()`. The version IDs should be set on each entry at the time it's written or merged.

**D-02 increment condition:** `data_version` increments on:
- (A) new completed match enters prediction_history, OR
- (B) existing entry gains a new signal not previously present
- NOT on merge execution, cache refresh, ledger update, governance run, or simulation run

**D-03 increment condition:** `model_version` increments when:
- Active signal lineup changes (signals added/removed)
- Calibration parameters are refitted (non-identity params)

**File size check:** Currently ~2900 lines, ~50 entries (10 real + duplicates). `versions.json` will be ~20 lines, run snapshots ~25 lines each. No performance concern.

---

### Integration 6: `worldcup_predictor/data/calibration_params.json`

**Current shape (full file, 37 lines):**
```json
{
    "elo": {"A": 1.0, "B": 0.0, "n_matches": 0, "brier": 1.0, "fitted_at": "cold_start"},
    "market_odds": {"A": 1.0, "B": 0.0, "n_matches": 0, "brier": 1.0, "fitted_at": "cold_start"},
    "catboost": {"A": 1.0, "B": 0.0, "n_matches": 0, "brier": 1.0, "fitted_at": "cold_start"},
    "form": {"A": 1.0, "B": 0.0, "n_matches": 0, "brier": 1.0, "fitted_at": "cold_start"},
    "lineup_strength": {"A": 1.0, "B": 0.0, "n_matches": 0, "brier": 1.0, "fitted_at": "cold_start"}
}
```

**What Phase 16 reads from it:**
- Per-signal `brier` values for run snapshot (D-06: per_signal_brier in run snapshot)
- But governance should **recompute** rolling Brier from prediction_history for drift detection, not trust stale calibration_params brier values (calibrate_and_blend() may run less frequently)

**What Phase 16 does NOT write to it:**
- D-06 explicitly: "Calibration params NOT duplicated per run"
- cal_params stay as current source of truth, managed by blender.py

---

### Integration 7: `worldcup_predictor/src/state.py` (992 lines)

**What it does:** All JSON persistence with `_atomic_write_json()` (tempfile.mkstemp + os.replace). Load/save for every data type.

**Existing patterns to follow:**

| Function | Pattern | Phase 16 Reuse |
|----------|---------|----------------|
| `_atomic_write_json(data, path)` | mkstemp → fdopen → json.dump → fsync → os.replace | **Direct** — use for all new files |
| `load_calibration_params()` | Empty dict -> graceful bootstrap | **Pattern** — same for `load_versions()` |
| `save_calibration_params(params)` | Atomic write | **Pattern** — same for `save_versions()`, `save_run_snapshot()` |
| `save_signal_cache(cache, filename)` | Atomic write to data/ | **Pattern** — same for run snapshots to `data/runs/{run_id}.json` |
| `load_prediction_ledger()` | Empty dict → graceful bootstrap | **Pattern** — same for `load_versions()` |

**New state.py functions needed:**

```python
# ─── Governance (Phase 16) ──────────────────────────────────────────────

GOV_VERSION_FILE = "versions.json"
GOV_RUNS_DIR = "runs"

def load_versions(data_dir=None) -> dict:
    """Load version state. Returns default dict if file doesn't exist."""
    path = _resolve_data_dir(data_dir) / GOV_VERSION_FILE
    if not path.exists():
        return {
            "data_version": "D0",
            "model_version": "M0",
            "run_version": "R0",
            "last_data_change": None,
            "last_model_change": None,
            "last_run_timestamp": None,
        }
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))

def save_versions(versions: dict, data_dir=None) -> None:
    """Save version state atomically."""
    path = _resolve_data_dir(data_dir) / GOV_VERSION_FILE
    _atomic_write_json(versions, path)

def save_run_snapshot(snapshot: dict, data_dir=None) -> None:
    """Save a single run snapshot to data/runs/{run_id}.json."""
    runs_dir = _resolve_data_dir(data_dir) / GOV_RUNS_DIR
    run_id = snapshot["run_version"]  # timestamp-based
    path = runs_dir / f"{run_id}.json"
    _atomic_write_json(snapshot, path)

def load_run_snapshot(run_id: str, data_dir=None) -> dict | None:
    """Load a specific run snapshot by run_version."""
    path = _resolve_data_dir(data_dir) / GOV_RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))

def load_backtest_report(data_dir=None) -> dict | None:
    """Load backtest evaluation report. Returns None if not yet run."""
    path = _resolve_data_dir(data_dir) / "eval_backtest_report.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_backtest_report(report: dict, data_dir=None) -> None:
    """Save backtest evaluation report atomically."""
    path = _resolve_data_dir(data_dir) / "eval_backtest_report.json"
    _atomic_write_json(report, path)
```

---

### Integration 8: `worldcup_predictor/src/output.py` (413 lines)

**Current patterns to follow:**

| Function | Pattern | Governance Reuse |
|----------|---------|-----------------|
| `print_probability_table()` | Bold cyan header + formatted table | Same for dashlet header |
| `print_delta_summary()` | Conditional section (only if data exists) | Same for drift section (only on drift) |
| `print_shutdown_banner()` | Full-width bordered block | Same for governance dashlet block |
| ANSI helpers | `_green()`, `_red()`, `_bold_yellow()`, `_bold_cyan()` | **Direct** — reuse all |
| `_ansi(code)` | Factory pattern | Reuse directly |
| `_timestamp()` | Dim gray timestamp prefix | Reuse directly |

**New output.py functions needed:**

```python
def print_governance_dashlet(
    versions: dict,
    status: str,              # "COLD START" or "HEALTHY" or "DRIFT"
    n_matches: int,
    per_signal_brier: dict,   # {signal_name: float}
    blend_weights: dict,      # {signal_name: float}
    drift_results: dict | None = None,  # only when drift exists
    backtest_summary: str | None = None,
) -> None:
    """Print the governance dashlet block.
    
    Cold-start mode (< 30 matches): D-17 format
    Active mode (>= 30 matches): D-18 format
    """

def print_drift_alert(drift_info: dict) -> None:
    """Print the expanded drift detection block (D-18, drift variant).
    
    Args:
        drift_info: {
            "signal": str,
            "reference_brier": float,
            "rolling_brier": float,
            "threshold": float,
            "delta": float,
        }
    """
```

---

### Integration 9: `worldcup_predictor/src/constants.py` (220 lines)

**New constants to add:**

```python
# ─── Governance Constants (Phase 16) ────────────────────────────────────

GOV_DATA_FILE = "versions.json"
"""Filename for version tracking state in data/ directory."""

GOV_RUNS_DIR = "runs"
"""Directory for run snapshots relative to data/."""

GOV_INTERVAL_HOURS: int = 1
"""How often to run governance checks (startup + hourly + on drift)."""

GOV_DRIFT_SIGMA_THRESHOLD: float = 2.0
"""Number of standard deviations above reference baseline that triggers drift alert (D-09)."""

GOV_BACKTEST_TOURNAMENTS: list[str] = ["2018", "2022"]
"""Historical World Cups to backtest against (D-13)."""

GOV_RUN_SNAPSHOT_RETENTION: int = 1000
"""Maximum number of run snapshots to retain (the agent's discretion)."""
```

---

### Integration 10: `worldcup_predictor/src/predictors/` — Context signal functions

**Form signal** `compute_form_signal()` is called at line 629 (main.py). It produces a cache dict with match predictions. For backtesting, the form signal needs to be computed per-match using historical data only.

**Key insight for backtesting:** Elo-based signals can be replayed from initial Elo ratings for each tournament. Market odds and CatBoost cannot — they require live API data from 2018/2022. Therefore:

- **Elo backtesting**: Full replay possible — start with tournament Elo ratings, simulate all matches applying Elo updates
- **Form backtesting**: Possible with Elo replay + form residual computation
- **Market odds / CatBoost backtesting**: NOT possible without historical API data (rejected per D-12 — no external API for backtesting)

The backtest report (D-14) must work within these constraints.

---

## Recommended Plan Structure

Based on the integration analysis, Phase 16 should be split into **4 plans**:

### Plan 16-01: Version Tracking (V2-12)
**Files:** `constants.py`, `state.py`, `governance.py` (new), `main.py`

- Add governance constants to `constants.py`
- Add `load_versions()`, `save_versions()` to `state.py`
- Create `governance.py` with `_compute_data_version()`, `_compute_model_version()`, `_compute_run_version()` pure functions
- Wire version initialization into `main.py` startup
- Wire version increment logic into `_run_iteration()` after new match ingestion and after calibration refit
- Add `data_version`, `model_version`, `run_version` fields to prediction_history entries in `_merge_signals_into_history()`

**No new data files created** (beyond `data/versions.json`). Existing `_atomic_write_json()` used directly.

### Plan 16-02: Run Snapshots & Governance Orchestrator (V2-12 scaffolding)
**Files:** `state.py`, `governance.py` (new), `main.py`

- Add `save_run_snapshot()` to `state.py`
- Create `_run_governance()` orchestrator in `main.py` (or `governance.py`) that:
  1. Loads prediction_history and current versions
  2. Computes per-signal rolling Brier
  3. Populates run snapshot payload (D-06)
  4. Saves snapshot
- Wire `_run_governance()` into `_run_iteration()` at line ~690
- Wire startup governance display into `main()` at line ~830

**Run snapshot schema** (D-06):
```python
{
    "run_version": str,           # timestamp-based ISO 8601
    "data_version": str,          # e.g., "D14"
    "model_version": str,         # e.g., "M7"
    "timestamp": str,             # ISO 8601
    "signal_counts": {str: int},  # per-signal match counts
    "blend_weights": {str: float},
    "per_signal_brier": {str: float},
    "blended_brier": float,
    "drift_status": str,          # "HEALTHY" | "DRIFT" | "COLD_START"
    "drift_details": list | None, # only if drift detected
}
```

### Plan 16-03: Drift Detection (V2-13)
**Files:** `governance.py` (new), `evaluation.py` (extension), `output.py`

- Create `compute_drift()` in `governance.py`:
  - Extract per-match Brier scores per signal
  - Compute rolling sigma (std of last 50 per-match Briers)
  - Compare rolling mean vs reference baseline
  - Return drift status per signal
- Create `compute_reference_baselines()` — fixed baseline after cold-start
- Add `print_governance_dashlet()` and `print_drift_alert()` to `output.py`
- Cold-start vs active display modes (D-17, D-18, D-19)

**Key decision:** Reuses `blender.compute_rolling_brier()` for the rolling mean. Needs new `_per_match_briers()` helper for sigma computation.

**Drift formula** (D-09):
```python
def check_drift(entries, signal_key, reference_baseline, window=50, sigma_threshold=2.0):
    per_match = _per_match_briers(entries, signal_key)
    if len(per_match) < COLD_START_THRESHOLD:
        return None  # insufficient data
    rolling = per_match[-window:]  # last 50
    rolling_mean = sum(rolling) / len(rolling)
    if len(rolling) >= 2:
        sigma = std(rolling)  # per-signal sigma
    else:
        sigma = 0.0
    threshold = reference_baseline + sigma_threshold * sigma
    return {
        "signal": signal_key,
        "rolling_mean": rolling_mean,
        "reference_baseline": reference_baseline,
        "sigma": sigma,
        "threshold": threshold,
        "drifted": rolling_mean > threshold,
    }
```

### Plan 16-04: Backtesting Framework (V2-14)
**Files:** `evaluation.py` (extension), `state.py`, `governance.py`, `main.py`, `data/historical/` (new directory)

- Create `data/historical/2018.json` with 64 matches
- Create `data/historical/2022.json` with 64 matches
- Each match entry follows prediction_history signal shape:
  ```json
  {
      "match_id": "wc_2018_01",
      "team_a": "France",
      "team_b": "Croatia",
      "actual": 1.0,
      "signals": {
          "elo": {"probability": 0.6432, "available": true}
      }
  }
  ```
- Create `backtest_tournament()` in `evaluation.py` following `evaluate_all_matches()` pattern
- Create `run_backtest()` orchestrator in `main.py` (one-shot at startup)
- Save `data/eval_backtest_report.json`
- Print backtest summary in governance dashlet

**Report format** (D-14):
```python
# Per-tournament:
{
    "tournament": "2018",
    "n_matches": 64,
    "per_signal": {
        "elo": {"brier": 0.127, "log_loss": 0.406, "ece": 0.233, "n": 64},
        ...
    },
    "blended": {"brier": 0.115, ...},
    "winner_prediction": {"predicted": "France", "actual": "France", "correct": True},
    "signal_ranking": ["blended", "elo", "form", ...],
}

# Aggregate:
{
    "tournaments": ["2018", "2022"],
    "n_total_matches": 128,
    "per_signal": { ... per-signal aggregate metrics ... },
    "signal_ranking": [...],
    "drift_summary": "...",
    "governance_recommendation": "...",
}
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rolling Brier computation | Custom rolling Brier | `blender.compute_rolling_brier()` | Already exists, tested, handles edge cases |
| Atomic JSON write | Open/write/close | `state._atomic_write_json()` | Already handles Windows tempfile+rename, same-filesystem atomicity, cleanup on failure |
| File path resolution | Hard-coded paths | `state._resolve_data_dir()` | Already exists, handles defaults, returns Path |
| Calibration curve | Custom calibration | `evaluation.calibration_curve()` | Already exists, decile-binned, ECE-computed |
| Brier/log loss/accuracy | Custom metrics | `evaluation.compute_metrics()` | Already exists, handles edge cases (empty lists, draw=0.5) |

**Key insight:** Phase 16's job is to **wrap and extend**, not to reimplement. Three major pure computations — Brier, log loss, calibration — are already solved in `evaluation.py`. Three persistence patterns — atomic write, load-with-fallback, graceful bootstrap — are already solved in `state.py`.

---

## Common Pitfalls

### Pitfall 1: Version ID Insertion Location
**What goes wrong:** Version IDs added in the wrong place — e.g., inside each signal dict instead of at entry top level, or set during merge instead of after calibration.
**Why it happens:** `_merge_signals_into_history()` is an attractive hook but runs before calibration params are refitted.
**How to avoid:** Set version IDs in a dedicated pass AFTER `_run_calibrate_and_blend()` (line ~652), not during merge (line ~648). The version triplet represents "which data/model/run produced THIS prediction history state" — it's an entry-level attribute, not signal-level.
**Warning signs:** Duplicate version fields across signals, version fields not matching versions.json, stale version after calibration refit.

### Pitfall 2: Per-Entry Version Field Data Bloat
**What goes wrong:** Every prediction_history entry grows by repeating the same version triplet (D14/M7/R312) for all entries in a batch.
**Why it happens:** Naively appending to every entry on every write cycle.
**How to avoid:** Only write version IDs on **entry creation** (first time the entry enters prediction_history). Already-versioned entries are skipped. This stops data bloat from repeated governance runs.
**Warning signs:** `prediction_history.json` file size growing on every governance cycle, entries with multiple version timestamps.

### Pitfall 3: Drift Detection on Cold-Start Data
**What goes wrong:** σ is 0 or near-0 for the first 30+ matches (insufficient data), causing false drift alerts.
**Why it happens:** `std()` on a small sample produces unreliable estimates. With < 2 matches, math domain error.
**How to avoid:** Guard with `COLD_START_THRESHOLD` (30 matches). Before threshold, return `None` from drift check. Display `"DISABLED"` in dashlet. After threshold, require at least `window_size` entries before computing σ.
**Warning signs:** Division by zero in drift computation, σ = 0.0, every signal flagged as drifted.

### Pitfall 4: Run Snapshot Archive Bloat
**What goes wrong:** Every poll cycle creates a new run snapshot (60s interval → 1440 files/day).
**Why it happens:** Governance runs every hour (D-16), but if `_should_run_gov()` check is missing, it runs every `_run_iteration()`.
**How to avoid:** D-16 frequency: startup + hourly + on drift detection. Implement `_last_gov_time` check. Snapshots only on actual governance runs. Also implement retention limit (`GOV_RUN_SNAPSHOT_RETENTION` = 1000).
**Warning signs:** Thousands of files in `data/runs/`, disk usage growing, file listing slows.

### Pitfall 5: Duplicate Brier Re-computation
**What goes wrong:** Governance recomputes rolling Brier at the same time as `calibrate_and_blend()`, doubling the computation.
**Why it happens:** Both governance and blender need per-signal Brier but don't coordinate.
**How to avoid:** Governance reads `calibration_params` after `_run_calibrate_and_blend()` for the most recent Brier values. Only recomputes from prediction_history directly when calibration_params is stale or for drift sigma (which needs per-match scores, not just mean).
**Warning signs:** CPU profiling shows governance using same compute as blender, ~2x expected runtime.

### Pitfall 6: Backtest Elo State Contamination
**What goes wrong:** Running historical backtest modifies live `teams` dict (Elo values change during replay), corrupting subsequent simulation.
**Why it happens:** `evaluate_all_matches(signal_name="elo")` modifies `replay_teams` in-place (lines 174, 212-215). If backtesting reuses `teams` directly, live Elos change.
**How to avoid:** Deep-copy teams before Elo replay. Pass `copy.deepcopy(teams)` to backtesting functions. Verify original `teams` dict unchanged after backtest.
**Warning signs:** Teams' Elo values change after backtest runs, simulation probabilities off by > 0.5%.

### Pitfall 7: `prediction_history` Duplicate Entries
**What goes wrong:** The `prediction_history.json` file has duplicate entries (same match_id with different timestamps). The current file has ~50 entries for ~15 unique matches.
**Why it matters:** Duplicates inflate match counts in drift detection, double-count Brier errors, cause wrong sigma estimates.
**How to avoid:** Governance should deduplicate on `match_id` (take last entry per match_id) when computing metrics. Do NOT modify the underlying file — just deduplicate at read time for governance purposes.
**Warning signs:** `n_matches` in governance dashlet is higher than actual played matches, drift triggers on doubled match data.

### Pitfall 8: Data Version False Increments
**What goes wrong:** `data_version` increments on every governance run or cache refresh, flooding version history.
**Why it happens:** D-02 defines narrow increment conditions (new match OR new signal), but the check is easy to miss.
**How to avoid:** Implement `_compute_data_version(old_versions, prev_history, new_history)` as a pure function that only increments when conditions (A) or (B) are true. Test separately.
**Warning signs:** Version jumps from D5 to D20 overnight, `versions.json` has skipped numbers.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `blender.compute_rolling_brier()` accepts `prediction_history` entries as parameter — confirmed by reading source | Integration 4 | LOW — source verified inline |
| A2 | `evaluate_all_matches()` loop pattern can be adapted for backtesting | Integration 3 | LOW — pattern is obvious from reading source |
| A3 | All 5 current signals (elo, market_odds, catboost, form, lineup_strength) exist in prediction_history | Integration 5 | MEDIUM — market_odds and catboost may have partial coverage |
| A4 | Historical 2018/2022 WC match data exists and can be structured as prediction_history entries | Plan 16-04 | LOW — static files, data from official sources |
| A5 | `_atomic_write_json()` handles `runs/` subdirectory creation via `mkdir(parents=True, exist_ok=True)` | Integration 7 | LOW — confirmed at line 115 of state.py |
| A6 | The `runs/` directory goes under `data/` (the agent's discretion) | D-06 | LOW — directory location is discretionary |
| A7 | Version string format is at the agent's discretion (D1/D2 vs v1/v2) | D-07 | LOW — no downstream dependency on format |
| A8 | `prediction_history` deduplication is needed for accurate governance metrics | Pitfall 7 | MEDIUM — duplicates confirmed in current file |

---

## Open Questions (RESOLVED in Plans)

1. **How to represent signal-level backtesting when some signals (market_odds, catboost) cannot be computed from historical data?** ⚡ RESOLVED
   - Plans adopt: Backtest only Elo + form signals (available). Market odds and catboost are excluded per D-12 offline constraint. Each signal's availability reported in backtest report header. Blended metric uses only available signals.

2. **Retention policy for run snapshots?** ⚡ RESOLVED
   - Plans adopt: `GOV_RUN_SNAPSHOT_RETENTION = 1000`, delete oldest when exceeding limit. ~25 lines per snapshot, 1000 = ~25KB — negligible.

3. **Should run snapshots go under `data/runs/` or at project root `runs/`?** ⚡ RESOLVED
   - Plans adopt: `data/runs/` — consistent with all existing JSON files under `data/`, follows `state._resolve_data_dir()` path resolution automatically.

4. **Backtesting winner prediction — how to determine "predicted tournament winner"?** ⚡ RESOLVED
   - Plans adopt: Highest initial Elo rating as winner prediction. Full simulation-based winner prediction explicitly noted as future enhancement (research finding: methodology simplification is not scope reduction).

---

## Environment Availability

> Step 2.6: SKIPPED (no external dependencies — Phase 16 reads existing data, no new CLI tools needed)

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, confirmed) |
| Config file | Unknown — check root directory |
| Quick run command | `python -m pytest -x` |
| Full suite command | `python -m pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| V2-12 | Version tracking: load/save versions.json | unit | `pytest tests/test_state.py -x -k "version"` | ❌ Wave 0 |
| V2-12 | Version increment: data_version on new match | unit | `pytest tests/test_governance.py -x -k "data_version"` | ❌ Wave 0 |
| V2-12 | Version increment: model_version on signal change | unit | `pytest tests/test_governance.py -x -k "model_version"` | ❌ Wave 0 |
| V2-12 | Run snapshot save/load | unit | `pytest tests/test_state.py -x -k "run_snapshot"` | ❌ Wave 0 |
| V2-13 | Rolling Brier computation | unit | `pytest tests/test_blender.py -x -k "rolling_brier"` | ✅ existing |
| V2-13 | Drift detection formula | unit | `pytest tests/test_governance.py -x -k "drift"` | ❌ Wave 0 |
| V2-13 | Drift alert threshold (2σ) | unit | `pytest tests/test_governance.py -x -k "drift_threshold"` | ❌ Wave 0 |
| V2-13 | Cold start suppresses drift | unit | `pytest tests/test_governance.py -x -k "cold_start"` | ❌ Wave 0 |
| V2-14 | Backtest tournament metrics | unit | `pytest tests/test_evaluation.py -x -k "backtest"` | ❌ Wave 0 |
| V2-14 | Backtest aggregate report | integration | `pytest tests/test_main_loop.py -x -k "backtest"` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest -x` (existing)
- **Per wave merge:** Full suite
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_governance.py` — covers V2-12, V2-13, V2-14 unit tests
- [ ] Fixtures: mock prediction_history with known Brier values for drift testing
- [ ] Fixtures: mock versions.json with known version state for increment testing
- [ ] Fixtures: historical tournament match data (small subset, not full 128 matches)

### Existing Test Coverage (Relevant)
- `tests/test_blender.py` — `compute_rolling_brier()` is already tested (40 blender tests)
- `tests/test_state.py` — all atomic write patterns tested
- `tests/test_evaluation.py` — 28 evaluation tests, `evaluate_all_matches()` tested
- `tests/test_main_loop.py` — integration tests, `test_baseline_records_brier` tests prediction history

---

## Security Domain

> Omitted — `security_enforcement` is not explicitly `false`, but Phase 16's scope (version tracking, drift detection, backtesting) touches no authentication, authorization, input sanitization, or cryptography. All data read/write is local JSON files. No applicable ASVS categories.

---

## Sources

### Primary (HIGH confidence)
- **Codebase read**: `worldcup_predictor/main.py:500-715` — `_run_iteration()` flow, hook locations
- **Codebase read**: `worldcup_predictor/src/evaluation.py` — all metric functions, `evaluate_all_matches()` pattern
- **Codebase read**: `worldcup_predictor/src/blender.py` — `compute_rolling_brier()`, calibration params structure
- **Codebase read**: `worldcup_predictor/src/state.py` — `_atomic_write_json()`, all load/save patterns
- **Codebase read**: `worldcup_predictor/src/output.py` — all print patterns, ANSI helpers
- **Codebase read**: `worldcup_predictor/src/constants.py` — existing constants, patterns for new ones
- **Codebase read**: `worldcup_predictor/data/prediction_history.json` — entry structure (verified)
- **Codebase read**: `worldcup_predictor/data/calibration_params.json` — calibration structure (verified)
- **Context document**: `.planning/phases/16-model-governance/16-CONTEXT.md` — all decisions D-01 through D-25
- **Requirements**: `.planning/REQUIREMENTS.md` — V2-12, V2-13, V2-14

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new external packages needed, pure Python stdlib
- Architecture: HIGH — all decisions locked in CONTEXT.md, integration points verified by reading source
- Pitfalls: HIGH — based on actual codebase analysis, confirmed duplicate entries in prediction_history.json

**Research date:** 2026-06-17
**Valid until:** 2026-07-17 (stable codebase, no fast-moving dependencies)
