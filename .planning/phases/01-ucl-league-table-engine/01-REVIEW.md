---
phase: 01-ucl-league-table-engine
reviewed: 2026-06-27T12:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - competitions/ucl/__init__.py
  - competitions/ucl/src/__init__.py
  - competitions/ucl/src/validation.py
  - competitions/ucl/src/elo_fetcher.py
  - competitions/ucl/src/groups.py
  - competitions/ucl/src/simulation.py
  - competitions/ucl/tests/conftest.py
  - competitions/ucl/tests/test_fixture_validation.py
  - competitions/ucl/tests/test_simulation.py
  - competitions/ucl/tests/test_swiss_tiebreakers.py
  - competitions/ucl/tests/test_monte_carlo.py
findings:
  critical: 0
  warning: 8
  info: 4
  total: 12
status: issues_found
---

# Phase 01: Code Review Report — UCL League Table Engine

**Reviewed:** 2026-06-27T12:00:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the UCL League Table Engine implementation across 11 source and test files. The code correctly implements the 36-team Swiss league phase, Poisson-based match simulation, 10-step UCL tiebreaker chain, and Monte Carlo aggregation. The architecture cleanly reuses `football_core` primitives (`_build_poisson_table`, `_compute_conduct_score`, `expected_goals`) without modifying core — satisfying UCLT-06.

**8 warnings** and **4 info items** were found. No critical/blocker issues. The main concerns are:

1. **HTTP instead of HTTPS** for the ClubElo API — potential MITM vector for data integrity
2. **Missing encoding** in JSON file reads — crash risk on Windows with non-ASCII data
3. **No error handling** for network failures in Elo fetching — simulation crashes on API unavailability
4. **`HOME_ADVANTAGE_MULTIPLIER` incorrectly applied** to UCL neutral-venue matches — inflates goal expectations by ~5%
5. **Several test quality gaps** — docstring/behavior mismatch, weak assertions, unused code

## Warnings

### WR-01: HTTP instead of HTTPS for ClubElo API

**File:** `competitions/ucl/src/elo_fetcher.py:43`
**Issue:** The ClubElo API base URL uses `http://` instead of `https://`. All Elo ratings data is transmitted in cleartext, allowing an attacker with network access (MITM) to inject arbitrary Elo values into the simulation, corrupting results. The World Cup codebase uses `https://` for `eloratings.net` (see `football_core.constants.ELORATINGS_TSV_URL`), making this an inconsistency.

```python
_API_BASE = "http://api.clubelo.com"  # BUG: should be https://
```

**Fix:**
```python
_API_BASE = "https://api.clubelo.com"
```

---

### WR-02: Missing encoding in JSON file reads — UnicodeDecodeError risk on Windows

**Files:**
- `competitions/ucl/src/elo_fetcher.py:64`
- `competitions/ucl/tests/conftest.py:129`
- `competitions/ucl/tests/conftest.py:239`
- `competitions/ucl/tests/conftest.py:465-467`

**Issue:** `open()` without an explicit `encoding` parameter defaults to the system locale encoding (e.g., `cp1252` on US Windows, `cp1250` on Central European Windows). If `team_aliases.json` or `fixtures.json` ever contain non-ASCII characters (e.g., "Bodø/Glimt" with a slashed o), the file will raise `UnicodeDecodeError` on Windows configurations where the system encoding doesn't support those characters. The World Cup codebase follows the same pattern in some places but is less exposed since World Cup team names are ASCII.

```python
# elo_fetcher.py:64
with open(alias_path) as f:
    return json.load(f)
```

**Fix:** Add `encoding="utf-8"` to all JSON file reads:
```python
with open(alias_path, encoding="utf-8") as f:
    return json.load(f)
```
Apply the same fix in `conftest.py` at lines 129, 239, and 465-467.

---

### WR-03: No error handling for network failures in Elo fetching

**Files:**
- `competitions/ucl/src/elo_fetcher.py:94`
- `competitions/ucl/src/simulation.py:179-183`

**Issue:** When `fetch_team_elos` is called (e.g., because `run_monte_carlo` is invoked without pre-supplied `elo_ratings`), any network failure (`urllib.error.URLError`, `urllib.error.HTTPError`, timeout, DNS failure) propagates unhandled and crashes the entire simulation. There is no retry logic, no graceful degradation, and no fallback to cached data. The test at `test_simulation.py:196-197` confirms this by expecting the exception to propagate.

```python
# simulation.py:179-183
if elo_ratings is None:
    from competitions.ucl.src.elo_fetcher import fetch_team_elos
    team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
    elo_ratings = fetch_team_elos(team_names)  # Network error → crash
```

**Fix:** Wrap the fetch in a try/except with a timeout-aware retry strategy (matching the pattern in `football_core.constants.ELO_SYNC_RETRY_BACKOFFS`) or at minimum re-raise with a user-friendly message:

```python
if elo_ratings is None:
    from competitions.ucl.src.elo_fetcher import fetch_team_elos
    try:
        team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
        elo_ratings = fetch_team_elos(team_names)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise RuntimeError(
            f"Failed to fetch Elo ratings from ClubElo: {exc}. "
            "Pass `elo_ratings` directly or check network connectivity."
        ) from exc
```

---

### WR-04: `HOME_ADVANTAGE_MULTIPLIER` incorrectly applied to UCL neutral-venue matches

**File:** `competitions/ucl/src/groups.py:53-57` (via `football_core.groups.expected_goals`)

**Issue:** The UCL Swiss league phase uses neutral venues (a single-match format with no designated home team). However, `expected_goals()` from `football_core.groups` always applies `HOME_ADVANTAGE_MULTIPLIER = 1.05`, inflating expected goals for *both* teams by 5%. While this doesn't introduce bias (both sides get the same multiplier), it means the effective base rate is ~1.31 instead of the intended 1.25, causing the simulation to systematically overestimate total goals by ~5%.

```python
# football_core.groups.expected_goals (team_a side):
adj_base = base_rate * HOME_ADVANTAGE_MULTIPLIER   # = 1.3125
return min(adj_base * (10.0 ** ((rating_a - rating_b) / 400.0)), MAX_EXPECTED_GOALS)
```

**Fix:** Pass a compensated base rate to neutralize the home advantage multiplier, or document the inflation as an accepted approximation:

```python
# In precompute_swiss_matchup_lambdas and simulate_league_phase:
base_rate=EXPECTED_GOALS_BASE_RATE / 1.05  # ~1.1905 compensates HOME_ADVANTAGE_MULTIPLIER
```

---

### WR-05: Docstring mismatch in test — claims fallback but expects exception

**File:** `competitions/ucl/tests/test_simulation.py:174-176`

**Issue:** The test `test_fetch_team_elos_fallback_on_http_error` has a docstring that says "caller gets fallback Elo" but the test actually asserts that `urllib.error.HTTPError` is raised. The behavior contradicts the documented intent — there is no fallback, there is a crash. This indicates either:
- The test was written before fallback was removed (documentation rot), or
- The production code should have fallback but doesn't.

```python
def test_fetch_team_elos_fallback_on_http_error(self, monkeypatch):
    """HTTP error on ranking fetch raises, but caller gets fallback Elo."""
    ...
    with pytest.raises(urllib.error.HTTPError):
        fetch_team_elos(["Man City"])
```

**Fix:** Update the docstring to match actual behavior:
```python
def test_fetch_team_elos_fallback_on_http_error(self, monkeypatch):
    """HTTP error on ranking fetch propagates to caller (no fallback)."""
```

Or, if fallback is desired, wrap the network call in `fetch_team_elos` with a try/except that returns `DEFAULT_ELO` for all teams.

---

### WR-06: Different_seed test doesn't verify result divergence

**File:** `competitions/ucl/tests/test_monte_carlo.py:136-150`

**Issue:** The test `test_run_monte_carlo_different_seed` only checks that `result["seed"]` matches the input seed values. It does not verify that the actual simulation results differ — it only checks metadata written by the function itself. The test name claims "Different seed produces different results" but doesn't test that claim.

```python
def test_run_monte_carlo_different_seed(self, sample_fixture_schedule, sample_elo_dict):
    result1 = run_monte_carlo(..., seed=42)
    result2 = run_monte_carlo(..., seed=123)
    assert result1["seed"] == 42
    assert result2["seed"] == 123
    # Missing: assert result1["teams"] != result2["teams"]
```

**Fix:** Add an assertion that verifies at least one team's probability differs between seeds:
```python
    assert result1["seed"] == 42
    assert result2["seed"] == 123
    # Verify actual results diverge
    team1 = list(result1["teams"].keys())[0]
    assert result1["teams"][team1]["avg_position"] != result2["teams"][team1]["avg_position"], \
        "Different seeds should produce different results"
```

---

### WR-07: `sys.path` mutation at import time

**File:** `competitions/ucl/__init__.py:5-11`

**Issue:** The package's `__init__.py` mutates `sys.path` at module import time by prepending the repo root and package directory. This is a global side effect that can interfere with other packages' imports and is not done by the World Cup package (`competitions/worldcup/__init__.py` is empty). If `sys.path` already contains these paths, the inserts push them to the front, changing import resolution order.

```python
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
```

**Fix:** Remove the `sys.path` mutation and rely on proper package installation (e.g., `pip install -e .`) or `PYTHONPATH` instead. If path setup is required, defer it to a `setup.py`/`pyproject.toml` configuration rather than import-time side effects:

```python
"""UEFA Champions League 2025/26 competition package."""
# Note: Add package to PYTHONPATH or install with pip install -e . instead
```

---

### WR-08: No error handling for missing or corrupt `team_aliases.json`

**File:** `competitions/ucl/src/elo_fetcher.py:49-65`

**Issue:** The `_load_aliases` function (decorated with `@lru_cache`) opens `team_aliases.json` without error handling. If the file is missing, moved, or contains malformed JSON, it raises an unhandled `FileNotFoundError` or `json.JSONDecodeError` that propagates to the caller. Because of `@lru_cache`, any failure poisons the cache — retrying with the same arguments will re-raise the cached exception.

```python
@functools.lru_cache(maxsize=1)
def _load_aliases(alias_path: str | None = None) -> dict[str, list[str]]:
    ...
    with open(alias_path) as f:      # FileNotFoundError on missing file
        return json.load(f)           # JSONDecodeError on corrupt file
```

**Fix:** Wrap the file I/O in a try/except with a fallback and clear the cache on failure:
```python
@functools.lru_cache(maxsize=1)
def _load_aliases(alias_path: str | None = None) -> dict[str, list[str]]:
    if alias_path is None:
        alias_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "team_aliases.json",
        )
    try:
        with open(alias_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load team aliases from %s: %s", alias_path, exc)
        _load_aliases.cache_clear()
        return {}
```

## Info

### IN-01: Unused helper functions in conftest.py

**File:** `competitions/ucl/tests/conftest.py:172-201`

**Issue:** The functions `_build_sample_matchday` (lines 172-191) and `_build_team_entry` (lines 194-201) are defined but never called by any test or fixture. They appear to be scaffolding left over from an earlier design iteration. Dead code increases maintenance burden and confuses readers.

**Fix:** Remove both functions, or add a comment explaining their intended future use.

---

### IN-02: Two sources of truth for ClubElo name resolution

**Files:**
- `competitions/ucl/src/elo_fetcher.py:68-79` (uses `team_aliases.json`)
- `competitions/ucl/data/fixtures.json` (contains `clubelo_name` field per team)

**Issue:** ClubElo name resolution has two independent sources: the `team_aliases.json` file (used by `resolve_clubelo_name`) and the `clubelo_name` field embedded in `fixtures.json`. These can drift out of sync. If a team's ClubElo display name changes, it must be updated in both places. The `__init__.py` only exports `resolve_clubelo_name` (via `team_aliases.json`), yet `fixtures.json` also carries its own mapping, creating a maintainability hazard.

**Fix:** Consolidate to a single source of truth. Either:
- Remove `clubelo_name` from `fixtures.json` and use `team_aliases.json` exclusively, or
- Remove `team_aliases.json` and extract ClubElo names from the `clubelo_name` field in `fixtures.json` at runtime.

---

### IN-03: Duplicate team_names extraction in `run_monte_carlo`

**File:** `competitions/ucl/src/simulation.py:182` and `simulation.py:194`

**Issue:** The expression `[t["name"] for t in fixtures["schedule"]["teams"]]` is written twice — once for the Elo fetch (line 182) and once for collector initialization (line 194). This duplicates logic and creates a maintenance risk if the team name extraction path changes.

```python
# Line 182
team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
...
# Line 194 (duplicate)
team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
```

**Fix:** Remove the duplicate at line 194 and reuse the variable from line 182 (ensuring it's scoped before both usages):
```python
team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
if elo_ratings is None:
    elo_ratings = fetch_team_elos(team_names)

# ... then reuse team_names for collector init
positions = {t: [] for t in team_names}
```

---

### IN-04: Shallow defensive copy may not prevent all mutation

**File:** `competitions/ucl/src/groups.py:100-106`

**Issue:** The defensive copy in `simulate_swiss_matches` creates a shallow copy of the teams list and matchday lists via `list(...)`, but individual match dicts remain references to the original objects. While the current code doesn't mutate match dicts (only reads from them), any future modification to a match dict would leak through to the caller's original `fixtures` dict.

```python
fixtures = {"schedule": {
    "teams": list(fixtures.get("schedule", fixtures).get("teams", [])),
    "matchdays": [
        list(md) for md in fixtures.get("schedule", fixtures).get("matchdays", [])
    ],
}}
```

**Fix:** Either document the shallow-copy limitation, or use `copy.deepcopy(fixtures)` if full isolation is required:
```python
import copy
fixtures = copy.deepcopy(fixtures)
schedule = fixtures.get("schedule", fixtures)
```

---

## Structural Findings (fallow)

*No structural pre-pass was provided for this review.*

---

_Reviewed: 2026-06-27T12:00:00Z_
_Reviewer: gsd-code-reviewer (standard depth)_
_Depth: standard_
