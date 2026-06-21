# Phase 20: Output Enhancement & Coverage Seal — Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 8 (5 modified, 3 test modifications)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/output.py` | controller | request-response | `src/output.py::print_probability_table()` (lines 54-94) + `print_ai_previews()` (lines 284-325) | exact (same file, same role) |
| `src/enrichment.py` | utility | transform | `src/enrichment.py::_STATS_FIELD_MAP` (lines 17-26) + `extract_stats()` (lines 34-64) | exact (same file, same pattern) |
| `src/main.py` | controller | request-response | `src/main.py::_ai_preview_enabled` (lines 43-44, 250-254, 933-934) | exact (same flag-gate pattern) |
| `src/state.py` | service | CRUD (JSON file I/O) | `src/state.py::load_prediction_history()` (lines 682-696) + `append_prediction_history()` (lines 699-714) | exact (same append-pattern) |
| `src/constants.py` | config | N/A | `src/constants.py::PREDICTION_LEDGER_FILE` (line 165) | exact (same file constant pattern) |
| `tests/test_output.py` | test | request-response | `tests/test_output.py::TestGovernanceDashlet` (lines 368-466) | role-match (test class for output functions) |
| `tests/test_state.py` | test | CRUD | `tests/test_state.py::test_save_prediction_history` (line 615) + `TestMigratePredictionHistory` (line 644) | exact (same persistence test pattern) |
| `tests/test_enrichment.py` | test | transform | `tests/test_enrichment.py::TestExtractStats` (lines 62-93) + `TestExtractContext` (lines 95-121) | exact (same module, same test pattern) |

## Pattern Assignments

### `src/output.py` — Add `print_match_detail_table()`, `print_focus_card()`, `wilson_ci()`, `print_coverage_audit()`, trend column in `print_probability_table()` (controller, request-response)

**Analog 1: `print_probability_table()` — existing championship table with delta column (lines 54-94)**

**Imports pattern** (lines 6-12):
```python
import logging
import sys
import time
from typing import Callable

from src.constants import GROUP_COUNT, MATCHES_PER_GROUP, POLL_INTERVAL
from src.elo_sync import get_staleness_level
```

**Core table pattern** (lines 54-94):
```python
def print_probability_table(probs: dict, prev_probs: dict | None = None) -> None:
    """Print the top-5 probability table with optional delta column."""
    sorted_names = sorted(probs, key=lambda n: probs[n]["champion"], reverse=True)
    top5 = sorted_names[:5]
    remaining = sorted_names[5:]

    label = "Initial probabilities:" if prev_probs is None else "UPDATED PROBABILITIES:"
    print(f"{_timestamp()} {_bold_cyan(label)}")

    has_delta = prev_probs is not None

    header = f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}"
    if has_delta:
        header += f"  {'Delta':>8}"
    print(_bold_cyan(header))

    sep_len = 51 + (9 if has_delta else 0)
    print(_bold_cyan("-" * sep_len))

    for rank, name in enumerate(top5, 1):
        p = probs[name]
        row = f"{rank:>2}. {name:<18} {p['qf']:.3f} {p['sf']:.3f} {p['final']:.3f} {p['champion']:.3f}"
        if has_delta and name in prev_probs:
            delta = probs[name]["champion"] - prev_probs[name]["champion"]
            if delta > 0:
                delta_str = _green(f"▲ {delta:+.3f}")
            elif delta < 0:
                delta_str = _red(f"▼ {delta:+.3f}")
            else:
                delta_str = f" {'=':>6} "
            row += f"  {delta_str:>8}"
        elif has_delta:
            row += f"  {'—':>8}"
        print(row)
    ...
```

**KEY: Trend column addition — analog for adding a column to `print_probability_table()`** (lines 65-86):
Add Trend column following same pattern as Delta column. After the existing Delta column conditional block at line 67:
```python
# Current header (line 65):
header = f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}"
if has_delta:
    header += f"  {'Delta':>8}"
# Add (NEW): Trend column
if has_trend:
    header += f"  {'Trend':>6}"
```

**Analog 2: `print_ai_previews()` — flag-gated display function (lines 284-325)**

**Core display pattern** (lines 284-325):
```python
def print_ai_previews(played: dict, played_groups: dict) -> None:
    """Print AI preview text for all played matches.

    Default console output unchanged. AI preview shown only when --ai-preview
    CLI flag is passed (D-09). Missing ai_preview produces no warnings or errors (D-11).
    """
    has_any = False
    for group_letter in "ABCDEFGHIJKL"[:GROUP_COUNT]:
        group_matches = [
            m for m in played_groups.values()
            if m.get("match_id", "").startswith(f"GS_{group_letter}_")
        ]
        if not group_matches:
            continue
        for match in sorted(group_matches, key=lambda m: m.get("match_id", "")):
            preview = match.get("ai_preview")
            if preview:
                if not has_any:
                    print(_bold_white("\n─── AI Previews ───"))
                    has_any = True
                print(f"\n{_bold_white(match['team_a'])} vs {_bold_white(match['team_b'])}:")
                print(preview)
    if not has_any:
        print(_dim("No AI previews available."))
```

**Analog 3: Header separator/box-drawing patterns** — for focus card sections (lines 258-268):
```python
def print_header(...) -> None:
    print()
    print(_bold_cyan("=" * 60))
    print(_bold_cyan("  WORLD CUP DYNAMIC PREDICTOR — v1.1"))
    print(_bold_cyan(f"  Polling API every {POLL_INTERVAL} seconds. Press Ctrl+C to stop."))
    ...
    print(_bold_cyan("=" * 60))
    print()
```

**ANSI color helpers** (lines 30-46) — reusable for all new display functions:
```python
def _ansi(code: str) -> Callable[[str], str]:
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper

_dim = _ansi("2")
_bold_cyan = _ansi("1;36")
_green = _ansi("32")
_red = _ansi("31")
_bold_green = _ansi("1;32")
_bold_white = _ansi("1;37")
_bold_yellow = _ansi("1;33")
_bold_red = _ansi("1;31")
```

**Capture helper for tests** (lines 62-71):
```python
def _capture(func, *args, **kwargs):
    """Run func(*args, **kwargs) and return captured stdout string."""
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = real
    return buf.getvalue()
```

---

### `src/enrichment.py` — Add 3 new _STATS_FIELD_MAP entries + coach and venue.city in _CONTEXT_SOURCE_MAP (utility, transform)

**Analog: Existing `_STATS_FIELD_MAP` pattern** (lines 17-26):
```python
_STATS_FIELD_MAP: dict[str, str] = {
    "yellow_cards_home": "yellow_cards",
    "yellow_cards_away": "yellow_cards",
    "red_cards_home": "red_cards",
    "red_cards_away": "red_cards",
    "shots_on_target_home": "shots_on_target",
    "shots_on_target_away": "shots_on_target",
    "possession_home": "ball_possession",
    "possession_away": "ball_possession",
}
```

**Add 3 new fields** (6 lines appended after line 26):
```python
    "fouls_home": "fouls",
    "fouls_away": "fouls",
    "corner_kicks_home": "corner_kicks",
    "corner_kicks_away": "corner_kicks",
    "shots_off_target_home": "shots_off_target",
    "shots_off_target_away": "shots_off_target",
```

**Analog: Existing `_CONTEXT_SOURCE_MAP` pattern** (lines 28-31):
```python
_CONTEXT_SOURCE_MAP: dict[str, tuple[str, str]] = {
    "venue": ("venue", "name"),
    "referee": ("referee", "name"),
}
```

**Add 3 new context entries:**
```python
    "venue_city": ("venue", "city"),
    "home_coach": ("home_coach", "name"),
    "away_coach": ("away_coach", "name"),
```

**Analog: `extract_stats()` — existing extraction loop pattern** (lines 34-64):
```python
def extract_stats(raw_event: dict) -> dict | None:
    live_stats = raw_event.get("live_stats")
    if not live_stats or not isinstance(live_stats, dict):
        return None

    home = live_stats.get("home")
    away = live_stats.get("away")
    if not home or not away:
        return None

    result: dict = {}

    for internal_name, bsd_leaf in _STATS_FIELD_MAP.items():
        source = home if internal_name.endswith("_home") else away
        val = source.get(bsd_leaf)
        if val is not None:
            result[internal_name] = int(val) if isinstance(val, (int, float)) else val

    return result if result else None
```

**No changes needed to extract_stats() — existing loop automatically picks up new _STATS_FIELD_MAP entries. Same for extract_context().**

---

### `src/main.py` — Add `--match-detail` CLI flag + probability log snapshot in `_run_iteration()` (controller, request-response)

**Analog: `_ai_preview_enabled` flag-gate pattern** (lines 43-44, 250-254, 933-934):

**Module-level flag** (line 43-44):
```python
_ai_preview_enabled: bool = False
"""Module-level flag for --ai-preview CLI flag. Set in main() after parse_args (Phase 18)."""
```

**→ Copy for `_match_detail_enabled`:**
```python
_match_detail_enabled: bool = False
"""Module-level flag for --match-detail CLI flag (Phase 20)."""
```

**CLI arg definition** (lines 249-254):
```python
parser.add_argument(
    "--ai-preview",
    action="store_true",
    dest="ai_preview",
    help="Display BSD AI prediction previews after simulation output (Phase 18)",
)
```

**→ Copy for `--match-detail`:**
```python
parser.add_argument(
    "--match-detail",
    action="store_true",
    dest="match_detail",
    help="Display per-match signal breakdown table (Phase 20)",
)
```

**Flag wiring in main()** (lines 1088-1089):
```python
global _ai_preview_enabled
_ai_preview_enabled = args.ai_preview
```

**→ Copy for `_match_detail_enabled`:**
```python
global _match_detail_enabled
_match_detail_enabled = args.match_detail
```

**Conditional display in _run_iteration()** (lines 933-934):
```python
if _ai_preview_enabled:
    output.print_ai_previews(played, played_groups)
```

**→ Copy for `--match-detail` (same location in _run_iteration):**
```python
if _match_detail_enabled:
    output.print_match_detail_table(matches_data, prev_matches_data)
```

**Analog: `_prev_history` / `_prev_cal_params` — module-level state snapshots** (lines 46-50):
```python
_prev_history: list[dict] | None = None
"""Snapshot of prediction_history BEFORE merge. Captured for data_version detection."""

_prev_cal_params: dict | None = None
"""Snapshot of calibration_params BEFORE calibrate_and_blend. Captured for model_version detection."""
```

**→ Analog for `_prev_signal_data`:**
```python
_prev_signal_data: dict | None = None
"""Snapshot of per-match signal data from previous iteration for Δ computation (Phase 20)."""
```

**Analog: Probability snapshot after simulation** — add at end of `_run_iteration()` (after line 936):
```python
# In _run_iteration(), after output is printed (analogous position to line 932):
# Capture probability snapshot for probability_log
try:
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "probabilities": probs,
    }
    state.append_probability_log(snapshot, data_dir=data_dir)
except Exception:
    print("Warning: Failed to save probability log snapshot", file=sys.stderr)
```

---

### `src/state.py` — Add `load_probability_log()`, `append_probability_log()` (service, CRUD)

**Analog: `load_prediction_history()` pattern** (lines 682-696):
```python
def load_prediction_history(data_dir: Path | str | None = None) -> list[dict]:
    """Load prediction history entries.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        List of prediction history entries, empty list if file doesn't exist.
    """
    path = _resolve_data_dir(data_dir) / "prediction_history.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    return data
```

**→ Copy for `load_probability_log()`:**
```python
def load_probability_log(data_dir: Path | str | None = None) -> list[dict]:
    """Load probability log entries.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        List of probability snapshot dicts, empty list if file doesn't exist.
    """
    from src.constants import PROBABILITY_LOG_FILE
    path = _resolve_data_dir(data_dir) / PROBABILITY_LOG_FILE
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    return data
```

**Analog: `append_prediction_history()` pattern** (lines 699-714):
```python
def append_prediction_history(
    entry: dict,
    data_dir: Path | str | None = None,
) -> None:
    """Append a single prediction history entry.

    Loads existing history, appends new entry, saves all. Atomic write.

    Args:
        entry: Prediction history entry dict.
        data_dir: Directory for the JSON files. Defaults to constants.DATA_DIR.
    """
    history = load_prediction_history(data_dir)
    history.append(entry)
    path = _resolve_data_dir(data_dir) / "prediction_history.json"
    _atomic_write_json(history, path)
```

**→ Copy for `append_probability_log()`** (lines 179-186 of RESEARCH.md):
```python
def append_probability_log(
    snapshot: dict,
    data_dir: Path | str | None = None,
) -> None:
    """Append a single probability log snapshot.

    Loads existing log, appends new snapshot, saves all. Atomic write.

    Args:
        snapshot: Probability snapshot dict with timestamp and probs.
        data_dir: Directory for the JSON files. Defaults to constants.DATA_DIR.
    """
    log = load_probability_log(data_dir)
    log.append(snapshot)
    from src.constants import PROBABILITY_LOG_FILE
    path = _resolve_data_dir(data_dir) / PROBABILITY_LOG_FILE
    _atomic_write_json(log, path)
```

---

### `src/constants.py` — Add `PROBABILITY_LOG_FILE` constant (config, N/A)

**Analog: Existing file-name constants pattern** (lines 159-168):
```python
ODDS_CACHE_FILE: str = "odds_cache.json"
"""Filename for market odds cache in data/ directory (D-04)."""

CATBOOST_CACHE_FILE: str = "catboost_cache.json"
"""Filename for CatBoost prediction cache in data/ directory (D-04)."""

PREDICTION_LEDGER_FILE: str = "predictions_ledger.json"
"""Filename for permanent prediction ledger in data/ directory (Phase 14a).
Unlike TTL caches, the ledger accumulates all predictions ever fetched,
keyed by match_id, and is never deleted."""

PREDICTION_HISTORY_SCHEMA_VERSION: int = 2
"""Schema version for prediction_history.json. v1=flat (Phase 12b), v2=compound (Phase 13+)."""
```

**→ Add after line 171 (after PREDICTION_HISTORY_SCHEMA_VERSION):**
```python
PROBABILITY_LOG_FILE: str = "probability_log.json"
"""Filename for rolling probability log in data/ directory (Phase 20).
Array of snapshot dicts appended after every _run_iteration(), keyed by
timestamp. Never pruned — tournament is finite (~43K entries at worst)."""
```

---

### `tests/test_output.py` — Add test classes for new display functions (test, request-response)

**Analog: `TestGovernanceDashlet` — test class pattern for complex output functions** (lines 368-466):
```python
class TestGovernanceDashlet:
    """Tests for print_governance_dashlet()."""

    def _sample_versions(self):
        return {
            "data_version": "D3",
            "model_version": "M2",
            "run_version": "R47",
            ...
        }

    def test_dashlet_cold_start_format(self):
        """Cold-start: shows COLD START, PENDING, DISABLED, READY, version strings, match count."""
        output = _capture(
            print_governance_dashlet,
            self._sample_versions(),
            "COLD START",
            19,
            self._sample_brier(),
            self._sample_weights(),
        )
        assert "MODEL GOVERNANCE" in output
        assert "COLD START" in output
        assert "Data Version" in output
```

**Test class label convention:**
- `TestMatchDetailTable` — per-match signal table tests
- `TestFocusCard` — focus card display tests (signals, CI, stats, context)
- `TestWilsonCI` — Wilson score CI computation tests
- `TestTrendColumn` — trend arrow computation & column render tests
- `TestCoverageAudit` — coverage auditor tests

**Test data fixture pattern** (lines 28-47):
```python
@pytest.fixture
def full_probs():
    """Returns a 32-team probs dict for table tests."""
    names = [...]
    probs = {}
    for i, name in enumerate(names):
        champion = max(0.001, round(1.0 / (32 + i * 0.5), 4))
        probs[name] = {
            "qf": round(champion * (32 - i) / 16, 4),
            "sf": round(champion * (32 - i) / 24, 4),
            "final": round(champion * (32 - i) / 28, 4),
            "champion": champion,
        }
    return probs
```

**Existing `_capture` helper** already at lines 62-71 of test_output.py — reusable for all new tests.

---

### `tests/test_state.py` — Add TestProbabilityLog class (test, CRUD)

**Analog: `test_save_prediction_history` pattern** (lines 615-638):
```python
def test_save_prediction_history(tmp_path):
    """save_prediction_history persists a complete history list."""
    history = [
        {"match_id": "GS_A_01", "actual": 1, "signals": {}},
        {"match_id": "GS_A_02", "actual": 0, "signals": {}},
        {"match_id": "GS_B_01", "actual": 1, "signals": {}},
    ]
    save_prediction_history(history, data_dir=tmp_path)
    loaded = load_prediction_history(data_dir=tmp_path)
    assert loaded == history


def test_save_prediction_history_overwrite(tmp_path):
    """save_prediction_history replaces the entire history (not append)."""
    history_a = [{"match_id": "GS_A_01", "actual": 1, "signals": {}}]
    history_b = [{"match_id": "GS_B_01", "actual": 0, "signals": {}}]
    save_prediction_history(history_a, data_dir=tmp_path)
    save_prediction_history(history_b, data_dir=tmp_path)
    loaded = load_prediction_history(data_dir=tmp_path)
    assert loaded == history_b, "Expected second save to replace, not append"
```

**→ Copy pattern for probability log tests:**
- `test_load_empty_when_no_file` — returns empty list when probability_log.json doesn't exist
- `test_append_and_load_roundtrip` — append snapshot then verify it's in log
- `test_multiple_appends` — multiple snapshots preserved in order

---

### `tests/test_enrichment.py` — Add new field extraction tests (test, transform)

**Analog: `TestExtractStats` — existing stat field test pattern** (lines 62-93):
```python
class TestExtractStats:
    def test_all_fields(self):
        stats = extract_stats(FINISHED_EVENT)
        assert stats is not None
        assert stats["yellow_cards_home"] == 2
        assert stats["yellow_cards_away"] == 1
        assert stats["shots_on_target_home"] == 6
        ...

    def test_none_live_stats(self):
        assert extract_stats(NO_STATS_EVENT) is None

    def test_partial_stats(self):
        stats = extract_stats(PARTIAL_STATS_EVENT)
        assert stats is not None
        assert "possession_home" in stats
        assert "yellow_cards_home" not in stats
```

**→ Add tests for new fields in same class:**
```python
    def test_fouls_corners_shots_off(self):
        """New Phase 20 fields extracted correctly."""
        stats = extract_stats(FINISHED_EVENT_WITH_NEW_FIELDS)
        assert stats is not None
        assert stats["fouls_home"] == 12
        assert stats["fouls_away"] == 8
        assert stats["corner_kicks_home"] == 7
        assert stats["corner_kicks_away"] == 3
        assert stats["shots_off_target_home"] == 4
        assert stats["shots_off_target_away"] == 2
```

**Analog: `TestExtractContext` — existing context field test pattern** (lines 95-121):
```python
class TestExtractContext:
    def test_both_fields(self):
        ctx = extract_context(FINISHED_EVENT)
        assert ctx is not None
        assert ctx["venue"] == "Estadio Azteca"
        assert ctx["referee"] == "Wilton Pereira Sampaio"

    def test_no_context(self):
        assert extract_context(NO_CONTEXT_EVENT) is None
```

**→ Add new context field tests:**
```python
    def test_venue_city(self):
        ctx = extract_context(FINISHED_EVENT_WITH_CITY)
        assert ctx is not None
        assert ctx.get("venue_city") == "Mexico City"

    def test_coach_names(self):
        ctx = extract_context(FINISHED_EVENT_WITH_COACHES)
        assert ctx is not None
        assert ctx.get("home_coach") == "Gerardo Martino"
        assert ctx.get("away_coach") == "Hugo Broos"
```

**Add new test event fixtures** following existing pattern at lines 8-59:
```python
FINISHED_EVENT_WITH_NEW_FIELDS = {
    **FINISHED_EVENT,
    "live_stats": {
        "home": {
            **FINISHED_EVENT["live_stats"]["home"],
            "fouls": 12, "corner_kicks": 7, "shots_off_target": 4,
        },
        "away": {
            **FINISHED_EVENT["live_stats"]["away"],
            "fouls": 8, "corner_kicks": 3, "shots_off_target": 2,
        },
    },
    "home_coach": {"name": "Gerardo Martino"},
    "away_coach": {"name": "Hugo Broos"},
}
```

---

## Shared Patterns

### Flag-Gated Display (`--match-detail`)
**Source:** `src/main.py` lines 43-44, 249-254, 933-934
**Apply to:** `main.py` (new `_match_detail_enabled`) and `output.py` (new `print_match_detail_table()`)

**Pattern:**
```python
# 1. Module-level flag (main.py:43-44)
_match_detail_enabled: bool = False

# 2. CLI arg definition (main.py:249-254)
parser.add_argument("--match-detail", action="store_true", dest="match_detail",
                    help="Display per-match signal breakdown table (Phase 20)")

# 3. Wire in main() (main.py:1088-1089)
global _match_detail_enabled
_match_detail_enabled = args.match_detail

# 4. Conditional call in _run_iteration() (main.py:933-934 pattern)
if _match_detail_enabled:
    output.print_match_detail_table(matches_data, prev_matches_data)
```

### JSON Array Append (probability_log.json)
**Source:** `src/state.py` lines 699-714 (`append_prediction_history`)
**Apply to:** `state.py` (new `append_probability_log()`)

**Pattern:**
```python
def append_probability_log(snapshot, data_dir=None):
    log = load_probability_log(data_dir)
    log.append(snapshot)
    path = _resolve_data_dir(data_dir) / PROBABILITY_LOG_FILE
    _atomic_write_json(log, path)
```

### Wilson Score CI (math.sqrt only)
**Source:** RESEARCH.md lines 193-214 (well-known formula, not in codebase yet)
**Apply to:** `output.py` (new `wilson_score_ci()` and `format_ci()`)

**Pattern:**
```python
def wilson_score_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denominator
    return (center - margin, center + margin)

def format_ci(k: int, n: int) -> str:
    low, high = wilson_score_ci(k, n)
    return f"[{low:.3f} \u2014 {high:.3f}]"
```

### Trend Arrow Computation
**Source:** RESEARCH.md lines 538-566 (assumed pattern)
**Apply to:** `output.py` (new `_compute_trend_arrow()` + column in `print_probability_table()`)

**Pattern:**
```python
def _compute_trend_arrow(current_prob: float, team_name: str, prob_log: list[dict]) -> str:
    threshold = 0.005
    if len(prob_log) < 6:
        return " "
    window = prob_log[-6:-1]
    window_probs = [s.get("probabilities", {}).get(team_name, {}).get("champion", 0.0)
                    for s in window]
    window_mean = sum(window_probs) / len(window_probs)
    if current_prob > window_mean + threshold:
        return "\u2191"
    elif current_prob < window_mean - threshold:
        return "\u2193"
    return "\u2192"
```

### Sparse-Fields Convention (graceful degradation)
**Source:** `src/enrichment.py` lines 7-10 (docstring), D-07 established pattern
**Apply to:** All new focus card stats/context display — missing fields show "N/A", never crash.

**Pattern (from enrichment.py docstring lines 7-10):**
```
Each returns None when BSD returned no data, or a partial dict per
the sparse-fields convention (D-07). Only P0 fields are extracted in
this phase — deferred fields are ignored.
```

### Coverage Auditor Pattern
**Source:** RESEARCH.md lines 570-675 (assumed pattern, no codebase analog)
**Apply to:** `output.py` (new `coverage_audit()` + `print_coverage_audit()`)

**Pattern:**
```python
def coverage_audit() -> dict:
    """Audit BSD API meaningful field coverage.
    
    Returns dict with meaningful/raw/by_category breakdown.
    Meaningful denominator = 47 fields (D-15). Target >= 60%.
    """
    # Field classification lists + extracted field sets
    # ... compute coverage, return dict

def print_coverage_audit() -> None:
    """Print coverage audit report to console (D-16, D-17 format)."""
    audit = coverage_audit()
    print(f"\nCoverage Audit")
    m = audit["meaningful"]
    print(f"  Meaningful:  {m['covered']}/{m['total']} ({m['pct']}%)  "
          f"{'← target: ≥60%' if not m['target_met'] else '✓ target met'}")
    # ... by-category breakdown
```

### Atomic JSON Write
**Source:** `src/state.py` lines 99-132 (`_atomic_write_json`)
**Apply to:** All state persistence (probability_log.json follows same pattern — no new code needed, reuses `_atomic_write_json`)

**Pattern:**
```python
def _atomic_write_json(data: dict | list, path: Path) -> None:
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(dir_path),
        prefix=path.stem + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| N/A — all 8 files have close analogs | — | — | — |

All patterns have existing analogs in the codebase (or well-documented in RESEARCH.md with ASSUMED/ASSUMED confidence). No greenfield patterns needed.

## Metadata

**Analog search scope:** `src/output.py`, `src/main.py`, `src/state.py`, `src/enrichment.py`, `src/constants.py`, `tests/test_output.py`, `tests/test_state.py`, `tests/test_enrichment.py`
**Files scanned:** 8 source files + 3 test files
**Pattern extraction date:** 2026-06-21
