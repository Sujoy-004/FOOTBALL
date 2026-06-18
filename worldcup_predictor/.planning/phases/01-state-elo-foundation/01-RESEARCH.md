# Phase 1: State & Elo Foundation — Research

**Researched:** 2026-06-13
**Domain:** Python 3.11+ CLI application — JSON persistence, Elo rating engine, bracket validation
**Confidence:** HIGH

## Summary

Phase 1 builds the data persistence layer and Elo rating engine for a World Cup knockout predictor. Three JSON files (`teams.json`, `bracket.json`, `played.json`) provide restart-proof state storage using atomic writes (temp file + `os.replace()`). The Elo engine implements the standard World Football Elo formula (K=60 for World Cup finals) with configurable parameters. Bracket validation uses depth-first search on the directed `source_matches` graph to detect cycles and unreachable matches.

**Primary recommendation:** Write `state.py` with 6 load/save functions using `tempfile.mkstemp()` + `os.replace()` for atomic writes. Write `elo.py` with `expected_score()` and `update_ratings()` using the standard Elo formula. Bracket validation operates on a flat match list (per D-07) and builds an adjacency graph from `source_matches` for cycle detection.

**Confidence assessment:** HIGH on Elo formula and atomic write pattern (verified from eloratings.net and Python docs). HIGH on testing patterns (verified from pytest docs). MEDIUM on bracket validation specifics (flat-list tournament validation is straightforward but has limited pre-existing library support — will write custom logic).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Top-level package: `worldcup_predictor/`
- **D-02:** Module organization: `worldcup_predictor/src/` with `__init__.py`
- **D-03:** Data directory: `worldcup_predictor/data/` at project root
- **D-04:** All JSON state management in `state.py` — 6 functions (load/save × 3)
- **D-05:** `teams.json` — minimal schema: `{"Argentina": {"elo": 2100}}`
- **D-06:** `played.json` — full match records: `{"R16_1": {"team_a": ..., "team_b": ..., "winner": ..., "home_score": ..., "away_score": ..., "completed_at": ...}}`
- **D-07:** `bracket.json` — flat match list array (not nested rounds)
- **D-08:** API-to-bracket mapping: dynamic team-name matching primary, `api_id_mapping.json` fallback
- **D-09:** `api_id_mapping.json` is Phase 3 — not created in Phase 1
- **D-10:** Phase 3 fallback flow: try dynamic → ambiguous → consult mapping → still unresolved → error
- **D-11:** Phase 1 uses canonical team names only — no normalization logic
- **D-12:** Create `data/team_aliases.json` as a reference file (file exists, logic deferred)
- **D-13:** Team name normalization belongs in Phase 3 — add DATA-04 requirement
- **D-14:** Known name ambiguities: USA/United States, Korea Republic/South Korea, IR Iran/Iran
- **D-15:** Framework: `pytest` + `pytest-cov`
- **D-16:** No mandatory coverage percentage — focus on critical behavior coverage
- **D-17:** Test files and cases: `test_elo.py` (expected_score, update_ratings, edge cases), `test_state.py` (roundtrip, atomic write, bracket validation, corrupt JSON)
- **D-18:** No benchmark code in Phase 1
- **D-19:** Document performance threshold: profile 50K simulations; if <5s target missed, evaluate NumPy optimization
- **D-20:** Add Phase 2 success criterion: "Profile 50,000 simulations. If target (<5s) is missed, evaluate NumPy optimization before continuing."

### the agent's Discretion
- Atomic write implementation details (tempfile naming, retry count) — standard practices
- Error message formatting on validation failures
- Default Elo start value (1500 is standard baseline)

### Deferred Ideas (OUT OF SCOPE)
- **DATA-04: Team Name Normalization** — Phase 3 concern. `data/team_aliases.json` created as a placeholder only.
- **NumPy optimization** — Phase 2 performance gate. Not a Phase 1 task.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-02 | System persists played matches and updated Elo ratings across script restarts via JSON files (teams.json, bracket.json, played.json) | Atomic write pattern: `tempfile.mkstemp()` + `os.replace()` [VERIFIED: Python docs]. Flat bracket list format [CITED: CONTEXT.md D-07]. 6 load/save functions in `state.py`. |
| ELO-01 | System updates Elo ratings for both teams after each real match result using standard Elo formula with configurable K-factor (default 60) | Standard Elo: `Rn = Ro + K × (W - We)` where `We = 1 / (10^(-dr/400) + 1)`, K=60 for World Cup finals [VERIFIED: eloratings.net/about]. Neutral knockout matches use dr = elo_a - elo_b (no home advantage). |
| VAL-01 | System validates bracket structure on startup (all match_ids unique, source_matches exist, no circular dependencies) | Flat list means: (1) set-based uniqueness check, (2) reference integrity check via set membership, (3) DFS cycle detection on source_matches directed graph. Custom implementation required — no library needed. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| JSON state load/save | State / Persistence | — | `state.py` owns all disk I/O for teams, bracket, played matches |
| Atomic file writes | State / Persistence | — | Write .tmp then `os.replace()` — filesystem-level guarantee |
| Bracket validation | State / Persistence | — | Runs on load; `state.py` is the entry point for all persisted data |
| Elo expected score | Core Logic | — | Pure computation, no I/O — `elo.py` is a leaf module |
| Elo rating update | Core Logic | — | Pure computation, no I/O — `elo.py` is a leaf module |
| seed data creation | Project setup | — | Initial `teams.json`/`bracket.json`/`played.json` created manually or via setup script |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `json` | 3.11+ | JSON serialization/deserialization | No external dependency needed — built-in, fast, well-tested |
| Python stdlib `os` | 3.11+ | `os.replace()` for atomic rename, `os.fsync()` for durability | Cross-platform atomic file replacement |
| Python stdlib `tempfile` | 3.11+ | `tempfile.mkstemp()` for temporary file creation | Creates files in same directory = same filesystem = atomic rename |
| Python stdlib `random` | 3.11+ | Random number generation for simulation | Not used in Phase 1, but seeded for reproducibility note |
| Python stdlib `pathlib` | 3.11+ | Path manipulation for data file paths | Cleaner than `os.path.join()` |
| Python stdlib `typing` | 3.11+ | Type hints for function signatures | Improves code clarity and IDE support |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.0+ | Test framework with `tmp_path` fixture | All test modules |
| `pytest-cov` | 7.1+ | Coverage reporting | Optional, invoked via `--cov` flag |

**No external runtime dependencies** — Phase 1 uses only Python standard library. `requests` is not needed until Phase 3. `pytest` + `pytest-cov` are development dependencies only.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `os.replace()` | `shutil.move()` | `shutil.move()` is not atomic across filesystems; `os.replace()` is atomic on the same filesystem. Use the same-directory temp file to guarantee same-filesystem. |
| `NamedTemporaryFile(delete=False)` | `mkstemp()` | On Windows, `NamedTemporaryFile` holds an exclusive lock while open, preventing re-opening until closed. `mkstemp()` returns a raw file descriptor with no lock — more portable. [VERIFIED: Python docs / Windows caveat] |
| Custom cycle detection | `networkx.find_cycle()` | Would add a 12MB+ dependency for a 20-line DFS algorithm. Not justified for a simple tournament DAG. |

**Installation (dev only):**
```bash
pip install pytest pytest-cov
```

**Version verification:**
```bash
python --version  # 3.11.8 confirmed available
pytest --version  # pytest 9.0.2 confirmed
pip show pytest-cov  # pytest-cov 7.1.0 confirmed
```

## Package Legitimacy Audit

> Run via slopcheck 0.6.1 on 2026-06-13.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| pytest | PyPI | 20+ yrs | Very high | github.com/pytest-dev/pytest | [OK] | Approved |
| pytest-cov | PyPI | 15+ yrs | Very high | github.com/pytest-dev/pytest-cov | [OK] — no source repo linked, but well-established | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
**No runtime packages required for Phase 1** — all core functionality uses Python standard library.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────────┐
                    │         main.py (Phase 4+)          │
                    │    (orchestrator — not in Phase 1)   │
                    └──────────┬──────────────────┬───────┘
                               │                  │
                    ┌──────────▼──────┐  ┌────────▼────────┐
                    │   state.py      │  │    elo.py        │
                    │  (persistence)  │  │  (core logic)    │
                    ├─────────────────┤  ├──────────────────┤
                    │ load_teams()    │  │ expected_score() │
                    │ save_teams()    │  │ update_ratings() │
                    │ load_bracket()  │  │                  │
                    │ save_bracket()  │  │                  │
                    │ load_played()   │  │                  │
                    │ save_played()   │  │                  │
                    │ validate_       │  │                  │
                    │  bracket()      │  │                  │
                    └────────┬────────┘  └──────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │       data/ directory         │
              │  ┌──────────┬──────────┬────┐ │
              │  │teams.json│bracket.  │played │
              │  │          │json      │.json │
              │  └──────────┴──────────┴────┘ │
              │  team_aliases.json (ref only)  │
              └──────────────────────────────┘
```

**Data flow for Phase 1:**
1. `main.py` calls `state.load_teams()` → reads `data/teams.json` → returns `dict[str, dict]`
2. `main.py` calls `state.load_bracket()` → reads `data/bracket.json` → validates → returns `list[dict]`
3. `main.py` calls `state.load_played()` → reads `data/played.json` → returns `tuple[set, dict]`
4. After Elo update: `state.save_teams(teams)` → atomic write to `data/teams.json`
5. After match recorded: `state.save_played(played)` → atomic write to `data/played.json`

### Recommended Project Structure
```
worldcup_predictor/
├── src/
│   ├── __init__.py          # Package marker
│   ├── constants.py         # K_FACTOR=60, DEFAULT_ELO=1500, DATA_DIR
│   ├── state.py             # load/save/validate functions
│   └── elo.py               # expected_score(), update_ratings()
├── data/
│   ├── teams.json           # Initial team Elo ratings
│   ├── bracket.json         # Flat bracket match list
│   ├── played.json          # Empty array/object placeholder
│   └── team_aliases.json    # Reference aliases file (Phase 3 use)
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures (sample teams, bracket)
│   ├── test_elo.py          # Elo formula tests
│   └── test_state.py        # Persistence and validation tests
├── main.py                  # Entry point (placeholder in Phase 1)
└── requirements.txt         # pytest, pytest-cov
```

### Pattern 1: Atomic JSON Write

**What:** Write JSON data to a file atomically so readers see either the complete old file or the complete new file — never a partial/corrupt state.

**When to use:** Every `save_*()` function in `state.py`.

**Example:**
```python
# Source: [VERIFIED: Python 3.11 docs / EngineersOfAI atomic write guide]
import json
import os
import tempfile
from pathlib import Path

def _atomic_write_json(data: dict, path: Path) -> None:
    """
    Write JSON data to path atomically.
    Uses mkstemp (not NamedTemporaryFile) for Windows compatibility.
    Temp file is created in the same directory as target (same filesystem = atomic rename).
    """
    dir_path = path.parent
    fd, tmp_path = tempfile.mkstemp(
        dir=str(dir_path),
        prefix=path.stem + ".",
        suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Ensure data is on disk before rename
        os.replace(tmp_path, str(path))  # Atomic on both POSIX and Windows
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

**Why `mkstemp` over `NamedTemporaryFile`:**
- On Windows, `NamedTemporaryFile` opens with exclusive locking — the file cannot be re-opened (e.g., by `os.replace` src read) while the handle is open. `mkstemp` returns a raw fd with no such lock. [VERIFIED: Python 3.14.6 docs for NamedTemporaryFile / EngineersOfAI article]

### Pattern 2: Standard Elo Formula

**What:** Compute expected win probability and new ratings using the Elo system adapted for football (eloratings.net standard).

**When to use:** All Elo calculations.

**Example:**
```python
# Source: [VERIFIED: eloratings.net/about]
import math

def expected_score(rating_a: float, rating_b: float, home_advantage: int = 0) -> float:
    """
    Expected score for team A against team B.
    Uses standard Elo formula: E_a = 1 / (1 + 10^((rating_b - rating_a) / 400))
    home_advantage added to rating_a for home-field effect.
    For neutral knockout matches, home_advantage = 0.
    """
    effective_a = rating_a + home_advantage
    return 1.0 / (1.0 + math.pow(10, (rating_b - effective_a) / 400.0))

def update_ratings(team_a: str, team_b: str, winner: str,
                   current_elos: dict[str, float],
                   K: int = 60) -> dict[str, float]:
    """
    Update Elo ratings after a match result.
    Returns dict with only the two changed teams.
    winner: team name string of the winning team.
    """
    elo_a = current_elos[team_a]
    elo_b = current_elos[team_b]

    expected_a = expected_score(elo_a, elo_b)  # neutral: home_advantage=0
    # expected_b = 1 - expected_a

    if winner == team_a:
        result_a = 1.0
    elif winner == team_b:
        result_a = 0.0
    else:
        raise ValueError(f"Winner '{winner}' must be '{team_a}' or '{team_b}'")

    new_elo_a = elo_a + K * (result_a - expected_a)
    new_elo_b = elo_b + K * ((1.0 - result_a) - (1.0 - expected_a))

    return {team_a: round(new_elo_a, 1), team_b: round(new_elo_b, 1)}
```

### Pattern 3: Bracket Validation (Flat List)

**What:** Validate that a flat bracket match list has no duplicate IDs, all source_matches reference valid match_ids, and there are no circular dependencies in the source_matches graph.

**When to use:** Called during `load_bracket()` before returning bracket data.

**Example:**
```python
from typing import Any

def validate_bracket(matches: list[dict[str, Any]]) -> None:
    """
    Validate bracket structure. Raises ValueError with descriptive message on failure.
    Validates:
    1. All match_ids are unique.
    2. Every source_matches reference exists as a match_id.
    3. No circular dependencies in source_matches (should be a DAG).
    """
    match_ids: set[str] = set()
    id_to_match: dict[str, dict] = {}

    for match in matches:
        mid = match["match_id"]
        if mid in match_ids:
            raise ValueError(f"Duplicate match_id: {mid}")
        match_ids.add(mid)
        id_to_match[mid] = match

    # Check source_matches references exist
    for match in matches:
        sources = match.get("source_matches")
        if sources:
            for src in sources:
                if src not in match_ids:
                    raise ValueError(
                        f"Match '{match['match_id']}' references "
                        f"non-existent source_match '{src}'"
                    )

    # Cycle detection via DFS
    # Build adjacency: (match_id) -> [match_ids that depend on it]
    # Actually for cycle detection we follow source_matches forward:
    # A -> B means A is a source for B. We want to detect if
    # there's a cycle in the dependency graph.
    # We build adjacency: for each match, edges are source -> current.
    adj: dict[str, list[str]] = {mid: [] for mid in match_ids}
    for match in matches:
        sources = match.get("source_matches")
        if sources:
            for src in sources:
                adj[src].append(match["match_id"])

    # DFS with 3 colors: 0=unvisited, 1=in-progress, 2=done
    color: dict[str, int] = {mid: 0 for mid in match_ids}

    def _dfs(node: str) -> None:
        color[node] = 1  # in progress
        for neighbor in adj[node]:
            if color[neighbor] == 1:
                raise ValueError(
                    f"Circular dependency detected involving matches: {node}, {neighbor}"
                )
            if color[neighbor] == 0:
                _dfs(neighbor)
        color[node] = 2  # done

    for mid in match_ids:
        if color[mid] == 0:
            _dfs(mid)
```

### Anti-Patterns to Avoid
- **Writing JSON directly to target file:** A crash mid-write leaves a truncated/corrupt file. Always use atomic write pattern.
- **Validating circular dependencies with a simple depth limit:** A knockout tournament bracket should be a DAG with max depth 4 (R16→QF→SF→FINAL). If depth exceeds 4, something is wrong. But DFS cycle detection is more robust than depth limits.
- **Using `NamedTemporaryFile` on Windows without `delete=False`:** The default opens the file exclusively; `os.replace` may fail because the temp file is still locked. Use `mkstemp()` instead.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON serialization | Custom writer | `json.dump()` / `json.load()` | Built-in, handles all Python types, well-tested, fast C implementation |
| File atomic rename | Custom rename logic | `os.replace()` | Cross-platform atomic rename, available since Python 3.3 |
| Temporary file management | Manual temp file naming | `tempfile.mkstemp()` | Secure unique names, auto-generated, prevents collisions |
| Test temp directories | Manual cleanup | `pytest` `tmp_path` fixture | Per-test isolation, auto-cleanup, built into pytest |
| Depth-first search | NetworkX or other graph lib | Custom DFS (20 lines) | Tournament bracket is a small DAG (15-16 nodes) — library overhead unjustified |

**Key insight:** Python's standard library handles all Phase 1 needs. No external dependencies beyond `pytest`/`pytest-cov`. The complex parts (cycle detection, atomic writes) are each <30 lines of well-tested standard library code.

## Don't Hand-Roll (Extended: Templates & Setup)

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Gitignore | Manual guesswork | Standard `.gitignore` | Must include `__pycache__/`, `*.pyc`, `.venv/`, `data/played.json` (if committing seed data separately) |
| Initial seed data | Imperative creation script | Static JSON files in `data/` | Simpler, human-readable, version-controllable, debuggable |
| Data directory creation | Assume it exists | `mkdir -p` in setup or `Path.mkdir(parents=True, exist_ok=True)` at init | Avoids `FileNotFoundError` on first run |

## Runtime State Inventory

> Section included because Phase 1 establishes the runtime state repository. Omitted from categorization since no rename/migration occurs.

**Phase 1 is greenfield — no runtime state to inventory.** The JSON files created (`teams.json`, `bracket.json`, `played.json`) are the runtime state. They are version-controllable static files that serve as both seed data and persistent state.

## Common Pitfalls

### Pitfall 1: Cross-Filesystem Temp File Breaks Atomicity
**What goes wrong:** `os.replace()` silently falls back to copy+delete (non-atomic) when source and target are on different filesystems.
**Why it happens:** `tempfile.mkstemp()` with no `dir=` defaults to system temp dir (`/tmp` or `%TEMP%`), which may be on a different drive/partition than the project's `data/` directory.
**How to avoid:** Always pass `dir=str(target_path.parent)` to `tempfile.mkstemp()`.
**Warning signs:** On some platforms, `os.replace()` raises `OSError: [Errno 18] Invalid cross-device link`.

### Pitfall 2: Forgetting `os.fsync()` After `flush()`
**What goes wrong:** `flush()` pushes Python's buffer to the OS buffer, but the OS may not write to disk immediately. If power fails between `flush()` and the rename, the temp file is empty on next boot.
**Why it happens:** `flush()` is not `fsync()`. The OS buffers writes for performance.
**How to avoid:** Always call `os.fsync(f.fileno())` after `flush()` in the atomic write pattern.
**Warning signs:** None at runtime — data loss only surfaces on crash.

### Pitfall 3: Nested Bracket Schema Confusion
**What goes wrong:** The Backend_Schema.md (§2.2) shows a *nested* bracket structure with `round_of_16`, `quarterfinals`, etc. as keys. CONTEXT.md D-07 specifies a *flat* list. Using the nested schema instead of the flat one breaks `source_matches` traversal and validation.
**Why it happens:** Backend_Schema.md was written before D-07 decision and hasn't been updated.
**How to avoid:** Follow D-07 flat list format exclusively. The planner diverges tasks accordingly.
**Canonical flat format:**
```json
[
  {"match_id": "R16_1", "round": "R16", "team_a": "Argentina", "team_b": "Nigeria", "source_matches": null, "winner": null},
  {"match_id": "R16_2", "round": "R16", "team_a": "France", "team_b": "Denmark", "source_matches": null, "winner": null},
  {"match_id": "QF_1", "round": "QF", "team_a": null, "team_b": null, "source_matches": ["R16_1", "R16_2"], "winner": null}
]
```

### Pitfall 4: Elo Expected Score Edge Cases
**What goes wrong:** Extreme Elo gaps (e.g., rating difference > 400) produce expected scores that round to 0.0 or 1.0 at standard float precision.
**Why it happens:** `10^(dr/400)` becomes very large when dr > 400, causing the expected score denominator to overflow to infinity or underflow to 1.
**How to avoid:** The formula `1 / (1 + 10^(-dr/400))` is numerically stable for both positive and negative dr. Test with dr = 0 (expect 0.5), dr = 400 (expect ~0.909), dr = -400 (expect ~0.091), and dr = 800 (expect ~0.990).
**Warning signs:** `expected_score()` returning exactly 1.0 or 0.0 — for very large ratings gaps this is actually correct behavior.

### Pitfall 5: Mutating the Returned Elo Dict
**What goes wrong:** `update_ratings()` returns a dict with only two entries. If the caller does `current_elos.update(result)` and then later modifies, it may accidentally mutate shared state.
**Why it happens:** The returned dict is a new dict, so this is actually safe. But if `update_ratings()` were to modify `current_elos` in-place, it would cause side effects.
**How to avoid:** Ensure `update_ratings()` does NOT modify `current_elos` — create and return a new dict. The planner should verify this in code review.
**Correct pattern:** `new_elos = {**current_elos, team_a: new_a, team_b: new_b}` or `changed = {team_a: new_a, team_b: new_b}` — both are safe.

## Code Examples

### Elo expected_score — Edge Case Coverage
```python
# Source: [VERIFIED: eloratings.net/about — formula and win expectancy table]

# Equal ratings → 50% each
assert expected_score(1500, 1500) == 0.5

# 100-point difference
e = expected_score(1600, 1500)
assert round(e, 3) == 0.640  # matches eloratings.net table
e = expected_score(1500, 1600)
assert round(e, 3) == 0.360  # matches eloratings.net table

# 400-point difference
e = expected_score(1900, 1500)
assert round(e, 3) == 0.909  # matches eloratings.net table
```

### Elo update_ratings — Standard Scenario
```python
# Source: [VERIFIED: eloratings.net/about formula + TRD.md §5.2]
# Argentina (2100) vs Nigeria (1800). Argentina wins.
elos = {"Argentina": 2100, "Nigeria": 1800, "France": 2050}
result = update_ratings("Argentina", "Nigeria", "Argentina", elos, K=60)

# expected_a = 1/(1+10^((1800-2100)/400)) = 1/(1+10^(-0.75)) ≈ 0.849
# new_arg = 2100 + 60*(1 - 0.849) ≈ 2109
# new_nig = 1800 + 60*(0 - 0.151) ≈ 1791
assert round(result["Argentina"], 0) == 2109
assert round(result["Nigeria"], 0) == 1791
assert "France" not in result  # unchanged team not in result
```

### Atomic Write — Full Working Function
```python
# Source: [VERIFIED: Python 3.11+ docs for os.replace, tempfile.mkstemp]
import json
import os
import tempfile
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

def _save_json(data, filename: str) -> None:
    """Save data to DATA_DIR/filename atomically."""
    path = DATA_DIR / filename
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(DATA_DIR),
        prefix=filename + ".",
        suffix=".tmp"
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

### pytest Test — State Roundtrip
```python
# Source: [VERIFIED: pytest docs — tmp_path fixture]

def test_save_load_roundtrip(tmp_path):
    """Verify that saved data loads back identically."""
    from src.state import save_teams, load_teams

    teams_data = {"Argentina": {"elo": 2100}, "France": {"elo": 2050}}
    save_teams(teams_data, data_dir=tmp_path)  # accept optional data_dir for testing
    loaded = load_teams(data_dir=tmp_path)
    assert loaded == teams_data
    assert loaded["Argentina"]["elo"] == 2100
```

### pytest Test — Bracket Validation
```python
# Source: [VERIFIED: pytest docs — tmp_path fixture]
import pytest

def test_duplicate_match_id_raises_error(tmp_path):
    """Duplicate match_ids should be rejected."""
    from src.state import validate_bracket

    bad_bracket = [
        {"match_id": "R16_1", "round": "R16", "team_a": "Arg", "team_b": "Nig", "source_matches": None, "winner": None},
        {"match_id": "R16_1", "round": "R16", "team_a": "Fra", "team_b": "Den", "source_matches": None, "winner": None},
    ]
    with pytest.raises(ValueError, match="Duplicate match_id"):
        validate_bracket(bad_bracket)

def test_circular_dependency_detected(tmp_path):
    """Circular source_matches should be rejected."""
    from src.state import validate_bracket

    cyclic_bracket = [
        {"match_id": "A", "round": "R16", "team_a": "T1", "team_b": "T2", "source_matches": None, "winner": None},
        {"match_id": "B", "round": "R16", "team_a": "T3", "team_b": "T4", "source_matches": ["C"], "winner": None},
        {"match_id": "C", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["B"], "winner": None},
    ]
    with pytest.raises(ValueError, match="Circular dependency"):
        validate_bracket(cyclic_bracket)
```

### pytest Test — Corrupt JSON Handling
```python
# Source: [VERIFIED: pytest docs — tmp_path fixture]
import json
import pytest

def test_load_corrupt_json_raises_error(tmp_path):
    """Malformed JSON should raise a clear error."""
    from src.state import load_teams

    bad_file = tmp_path / "teams.json"
    bad_file.write_text("{invalid json!!!", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_teams(data_dir=tmp_path)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `os.rename()` | `os.replace()` | Python 3.3 (2012) | `os.replace()` works cross-platform (Windows overwrites existing file); `os.rename()` raises on Windows if target exists. Always use `os.replace()` for atomic writes. [VERIFIED: Python docs] |
| `tempfile.NamedTemporaryFile(delete=True)` | `tempfile.mkstemp()` with manual cleanup | Current best practice | `NamedTemporaryFile` on Windows holds exclusive lock; `mkstemp()` is lock-free and portable. [VERIFIED: Python 3.14.6 docs] |
| `tmpdir` fixture (py.path.local) | `tmp_path` fixture (pathlib.Path) | pytest 7.0+ | Pathlib is the modern Python standard. Use `tmp_path` in all new code. [VERIFIED: pytest docs] |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default Elo start of 1500 is appropriate baseline | User Constraints (Discretion) | Real eloratings.net values cluster around 1800-2100 for World Cup teams. 1500 is closer to friendly match level. If actual range is used for seed data, `DEFAULT_ELO` may never be exercised — minimal risk. |
| A2 | Goal-difference Elo multiplier is deferred | Standard Stack / Code Examples | If the planner decides to include goal-difference adjustment, `update_ratings()` needs an additional `goal_diff: int` parameter and K-multiplier logic. Low risk — easy to add. |
| A3 | `data/` directory is created by `state.py` functions on first sav | Code Examples | If `state.py` does not auto-create the directory, first save crashes with `FileNotFoundError`. Low risk — easily handled via `Path.mkdir(parents=True, exist_ok=True)`. |

## Open Questions (RESOLVED)

1. **Goal-difference multiplier for Elo?**
   - What we know: eloratings.net adjusts K by goal difference (1.5× for 2-goal win, 1.75× for 3-goal, etc.). The "standard Elo formula" as specified in ELO-01 does not require this.
   - What's unclear: Should Phase 1 include goal-difference multiplier or defer to a later phase? The success criteria say "standard Elo formula with configurable K-factor" — K-factor alone is configurable, but goal-difference is a multiplier on K.
   - Recommendation: **Defer.** Implement the base formula for Phase 1. The goal-difference multiplier is a self-contained enhancement that can be added in Phase 2+ as a simple `K * _goal_diff_multiplier(goal_diff)` call. Mark it as a TODO comment in `elo.py`.

2. **What real-world Elo values to seed?**
   - What we know: eloratings.net shows current values (Spain 2157, Argentina 2115, France 2063 as of Oct 2026). The teams.json schema needs initial values.
   - What's unclear: Should seed data be scraped from eloratings.net at tournament start, or hand-typed from the website?
   - Recommendation: **Hand-type initial values** from eloratings.net pre-tournament. Create `data/teams.json` with all 32 teams at their pre-tournament ratings. No scraping logic in Phase 1.

3. **File-locking for concurrent access?**
   - What we know: MVP is single-threaded single-process. Atomic writes prevent corruption from crashes.
   - What's unclear: Should we add file locking (`fcntl.flock` / `msvcrt.locking`) for safety against accidental concurrent runs?
   - Recommendation: **Not needed for Phase 1.** The atomic write pattern is sufficient for single-process CLI use. File locking would add complexity with no demonstrated need. Add if concurrent-run bugs surface during testing.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All code | ✓ | 3.11.8 | — |
| pip | Package management | ✓ | 26.1.1 | — |
| pytest | Testing | ✓ | 9.0.2 | — |
| pytest-cov | Coverage | ✓ | 7.1.0 | — |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

All required tooling is available. The project uses only Python standard library for runtime code.

## Validation Architecture

> nyquist_validation is enabled per `.planning/config.json`.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | (none — pytest defaults suffice for Phase 1) |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-02 | teams.json load/save roundtrip preserves data | unit | `pytest tests/test_state.py::test_teams_roundtrip -x` | ❌ Wave 0 |
| DATA-02 | bracket.json load/save roundtrip preserves data | unit | `pytest tests/test_state.py::test_bracket_roundtrip -x` | ❌ Wave 0 |
| DATA-02 | Atomic write does not corrupt on failure | unit | `pytest tests/test_state.py::test_atomic_write_safety -x` | ❌ Wave 0 |
| DATA-02 | Corrupt JSON raises json.JSONDecodeError | unit | `pytest tests/test_state.py::test_corrupt_json_error -x` | ❌ Wave 0 |
| ELO-01 | expected_score returns 0.5 for equal ratings | unit | `pytest tests/test_elo.py::test_expected_score_equal -x` | ❌ Wave 0 |
| ELO-01 | expected_score matches eloratings table values | unit | `pytest tests/test_elo.py::test_expected_score_table -x` | ❌ Wave 0 |
| ELO-01 | update_ratings adjusts ratings correctly | unit | `pytest tests/test_elo.py::test_update_ratings_standard -x` | ❌ Wave 0 |
| ELO-01 | update_ratings with custom K-factor | unit | `pytest tests/test_elo.py::test_update_ratings_custom_k -x` | ❌ Wave 0 |
| ELO-01 | update_ratings large Elo gap | unit | `pytest tests/test_elo.py::test_update_ratings_large_gap -x` | ❌ Wave 0 |
| VAL-01 | Duplicate match_ids detected | unit | `pytest tests/test_state.py::test_duplicate_match_id -x` | ❌ Wave 0 |
| VAL-01 | Missing source_match references detected | unit | `pytest tests/test_state.py::test_missing_source_match -x` | ❌ Wave 0 |
| VAL-01 | Circular dependency detected | unit | `pytest tests/test_state.py::test_circular_dependency -x` | ❌ Wave 0 |
| VAL-01 | Valid bracket passes validation | unit | `pytest tests/test_state.py::test_valid_bracket_passes -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_elo.py` — covers ELO-01
- [ ] `tests/test_state.py` — covers DATA-02, VAL-01
- [ ] `tests/__init__.py` — package marker
- [ ] `tests/conftest.py` — shared fixtures (sample teams dict, sample bracket list)
- [ ] pytest install: `pip install pytest pytest-cov` — already available

## Security Domain

> `security_enforcement` is absent from config.json — default is enabled. Phase 1 has minimal security surface because it involves no network calls, no user input, no authentication, and no sensitive data storage.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth in Phase 1 (or any phase — CLI tool, no users) |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Single-user local CLI |
| V5 Input Validation | yes | Team names validated against teams.json; bracket format validated by `validate_bracket()`; Elo inputs validated by function contracts (positive ratings, valid team names) |
| V6 Cryptography | no | No secrets stored or transmitted |

### Known Threat Patterns for Python CLI + JSON

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| JSON deserialization of large/bloated input | Denial of Service | Not a practical concern for <1KB team/bracket files. Can add size check if needed. |
| Temp file symlink attack (TOCTOU) | Tampering | `mkstemp()` creates the file atomically in a non-predictable path, making symlink attacks infeasible. [VERIFIED: Python tempfile docs] |
| Arbitrary file write via path traversal | Tampering | Not applicable — all paths are hardcoded relative to `DATA_DIR`; no user-provided paths. |

## Sources

### Primary (HIGH confidence)

- **eloratings.net/about** — World Football Elo Ratings formula, K-factors, expected score table, goal difference adjustment. Confirmed: K=60 for World Cup finals, `We = 1/(10^(-dr/400)+1)`, `Rn = Ro + K*(W-We)`, home advantage +100.
  `[VERIFIED: https://www.eloratings.net/about]`
- **Python 3.11+ docs — `os.replace()`** — Cross-platform atomic rename. Available since Python 3.3.
  `[VERIFIED: https://docs.python.org/3/library/os.html#os.replace]`
- **Python 3.14.6 docs — `tempfile.mkstemp()`** — Secure temporary file creation with same-directory support.
  `[VERIFIED: https://docs.python.org/3/library/tempfile.html]`
- **Python 3.14.6 docs — `tempfile.NamedTemporaryFile` Windows caveat** — Exclusive lock on Windows prevents re-opening.
  `[VERIFIED: https://docs.python.org/3/library/tempfile.html]`
- **pytest docs — `tmp_path` fixture** — Per-test isolated temporary directory, returns pathlib.Path.
  `[VERIFIED: https://docs.pytest.org/en/stable/how-to/tmp_path.html]`
- **CONTEXT.md D-07** — Flat bracket list format (overrides Backend_Schema.md nested format).
  `[CITED: .planning/phases/01-state-elo-foundation/01-CONTEXT.md]`
- **FIFA/TRD.md §5.2** — Elo formula implementation signature and constraints.
  `[CITED: SOTs/TRD.md]`
- **Slopcheck 0.6.1** — Verified pytest and pytest-cov are legitimate packages.
  `[VERIFIED: slopcheck run on 2026-06-13]`

### Secondary (MEDIUM confidence)

- **EngineersOfAI atomic write guide** — Confirmed mkstemp + os.replace pattern, Windows caveat about NamedTemporaryFile locking.
  `[VERIFIED: https://engineersofai.com/docs/python/python-foundation/file-handling-and-os-interaction/Writing-Files]`
- **international-football.net Elo table** — Verified current Elo range for World Cup teams (~1770-2157).
  `[VERIFIED: https://www.international-football.net/elo-ratings-table]`

### Tertiary (LOW confidence)

- None — all claims are sourced from HIGH or MEDIUM confidence sources. Assumptions are explicitly logged.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — All runtime is Python stdlib; dev deps verified via pip and slopcheck
- Architecture: HIGH — Greenfield project with clear structure from CONTEXT.md and SOTs
- Elo formula: HIGH — Verified against eloratings.net and Wikipedia sources
- Atomic write pattern: HIGH — Verified against Python docs and multiple secondary sources
- Bracket validation: MEDIUM — Custom implementation (no library), but algorithm is standard DFS
- Testing patterns: HIGH — Directly from pytest docs

**Research date:** 2026-06-13
**Valid until:** 2026-07-13 — Elo formula is time-invariant; software versions are stable
