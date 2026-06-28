# Codebase Concerns

**Analysis Date:** 2026-06-27

## Tech Debt

### Euro's sys.path Hack for Cross-Package Import

**Issue:** `competitions/euro/__init__.py` inserts both the repo root and the `worldcup` package directory into `sys.path` at import time:

```python
# competitions/euro/__init__.py (line 5-11)
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_wc_pkg = str(Path(__file__).resolve().parent.parent / "worldcup")
if _wc_pkg not in sys.path:
    sys.path.insert(0, _wc_pkg)
```

**Files:** `competitions/euro/__init__.py`

**Impact:** Makes the Euro package dependent on the worldcup directory being present. The `from src.groups import ...` in `competitions/euro/simulation.py` line 8 will fail silently or at import time if the worldcup directory is missing or restructured. This is a fragile runtime dependency on another competition's internal structure.

**Fix approach:** Refactor the shared group/tournament logic into `football_core/` so both competitions import from there. Remove `sys.path` mutation entirely. The worldcup's own `competitions/worldcup/__init__.py` has the same pattern (line 5-11).

### Duplicated Tournament Logic (Euro vs Worldcup)

**Issue:** `competitions/euro/simulation.py` contains near-verbatim copies of group standing computation, third-place ranking, and advancer selection logic from `competitions/worldcup/src/groups.py`. The functions are:
- `compute_euro_standings` (euro) vs `compute_standings` (worldcup) — same logic, different hardcoded group letters
- `rank_euro_third_placed` (euro) vs `rank_third_placed` (worldcup) — identical logic except group range
- `select_euro_advancers` (euro) vs `select_advancers` (worldcup) — same logic except top4 vs top8

**Files:**
- `competitions/euro/simulation.py` (lines 27-66, 69-99, 102-114)
- `competitions/worldcup/src/groups.py` (lines 21-91, 94-130, 133-152)

**Impact:** Any bug fix or enhancement to the tournament logic must be applied in two places. The two implementations have already diverged — the worldcup version uses `_tiebreak_group()` for proper tiebreaker resolution, while the Euro version just uses `sorted(..., key=lambda t: t["pts"], reverse=True)` (line 62), which means Euro does not properly handle tiebreakers (goal difference, head-to-head, etc.).

**Fix approach:** Make the `football_core/groups.py` logic generic with configurable group count/advancer rules. Delete the duplicated functions from `competitions/euro/simulation.py` and import the parameterized versions from `football_core`.

### Flat football_core vs Aspirational Subpackage Structure

**Issue:** `football_core/` has a flat module structure while there's an aspirational `predictors/` subpackage that is underutilized. The `predictors/` subpackage in `football_core/` only contains re-export-style modules (`odds.py`, `catboost.py`) that are actually thin wrappers around worldcup-specific code. Meanwhile, core modules like `groups.py`, `knockout.py`, `state.py` sit flat in `football_core/`.

**Files:**
- `football_core/predictors/odds.py` (121 lines)
- `football_core/predictors/catboost.py` (182 lines)
- `football_core/predictors/__init__.py` (empty)
- `football_core/__init__.py` (empty)

**Impact:** Confusing architecture. New developers won't know where to add new prediction signals — should it go in `football_core/predictors/` or in `competitions/worldcup/src/predictors/`? The current answer is both: generic logic in `football_core/predictors/` and competition-specific logic in `worldcup/src/predictors/`.

**Fix approach:** Document clear boundaries in `football_core/__init__.py`. Either use `football_core/predictors/` as the single source of truth and remove `worldcup/src/predictors/`, or accept the split and document the convention.

### Re-Export Boilerplate in worldcup/src/*.py

**Issue:** `competitions/worldcup/src/groups.py` (lines 3-15) and `competitions/worldcup/src/knockout.py` (lines 14-22) and `competitions/worldcup/src/state.py` (lines 10-31) make extensive use of re-exports from `football_core`:

```python
# competitions/worldcup/src/groups.py
from football_core.groups import (
    expected_goals,
    _build_poisson_table,
    _poisson_sample,
    ...
)
```

**Files:** `competitions/worldcup/src/groups.py` (lines 3-15), `competitions/worldcup/src/knockout.py` (lines 14-22), `competitions/worldcup/src/state.py` (lines 10-31)

**Impact:** Import chains are convoluted. Euro's `simulation.py` imports `compute_standings` from `src.groups` (which is worldcup), but the actual implementation depends on which `src` is on `sys.path`. This creates a tight coupling where Euro imports worldcup-specific code, then overrides parts of it with Euro-specific versions.

**Fix approach:** Use direct imports from `football_core` throughout, avoiding the re-export layer from `worldcup/src/`.

### worldcup/main.py Size and Complexity

**Issue:** `competitions/worldcup/main.py` is 1568 lines — far too large for an entry-point module. It contains:

- CLI argument parsing (lines 214-278)
- Data loading (lines 1369-1408)
- Historical catch-up logic (lines 328-484)
- Draw backfill (lines 487-558)
- Signal blending orchestration (lines 119-169)
- Signal data gathering (lines 646-740)
- Main polling loop (lines 743-1157)
- Data migration (lines 1191-1243)
- Probability log merging (lines 1246-1308)
- League ID resolution (lines 1311-1366)

**Files:** `competitions/worldcup/main.py`

**Impact:** Poor testability, high cognitive load, merge conflicts. The file mixes concerns across many areas.

**Fix approach:** Split into `cli.py`, `orchestrator.py`, `migration.py`, and `signals.py` modules.

### Bare `except Exception:` Patterns

**Issue:** 23 instances of `except Exception:` (bare catch-all) across the codebase. These silently swallow all errors, including programming errors like `NameError`, `TypeError`, etc.

**Files:**
- `competitions/euro/main.py` — 5 instances (lines 85, 105, 152, 162, 178)
- `competitions/worldcup/main.py` — 8 instances (lines 168, 884, 1117, 1153, 1185, 1298, 1351, 1459)
- `football_core/state.py` — 1 instance (line 31)
- `competitions/worldcup/src/evaluation.py` — 2 instances (lines 215, 363)
- `competitions/worldcup/src/blender.py` — 1 instance (line 439)
- `competitions/worldcup/src/predictors/catboost.py` — 1 instance (line 36)
- `competitions/worldcup/src/predictors/odds.py` — 1 instance (line 34)
- `competitions/worldcup/src/predictors/form.py` — 2 instances (lines 291, 335)
- `competitions/worldcup/src/predictors/lineup.py` — 2 instances (lines 142, 182)

**Impact:** Real errors are silently hidden. For example, a programming bug in `_run_iteration` in Euro's main.py (line 85) would be silently swallowed during match processing. This makes debugging extremely difficult in production.

**Fix approach:** Replace with specific exception types (e.g., `except requests.exceptions.RequestException:`) or at minimum add `logger.exception(...)` to preserve traceback.

### No Tests for Euro Package

**Issue:** `competitions/euro/` has no `tests/` directory and zero test files. Zero test coverage for the Euro 2024 predictor.

**Files:** (absence of) `competitions/euro/tests/`

**Impact:** Any change to the Euro code runs the risk of regressions. There is no CI safety net for the Euro competition module.

**Fix approach:** Add at minimum unit tests for `simulation.py` functions (`compute_euro_standings`, `rank_euro_third_placed`, `resolve_r16_matchups`, `run_full_simulation`).

### Missing pyproject.toml / Project Metadata

**Issue:** The repo has no `pyproject.toml`, no `setup.py`, no `setup.cfg`. The only dependency specification is a minimal `competitions/worldcup/requirements.txt` with 3 packages (`pytest`, `pytest-cov`, `python-dotenv`). The actual runtime dependencies (`requests`, `python-dotenv`) are not listed as top-level requirements.

**Files:** `competitions/worldcup/requirements.txt`

**Impact:** Non-reproducible installations. No pinned versions. No way to install the project as a package with `pip install -e .`. No lockfile.

**Fix approach:** Create a project-level `pyproject.toml` with all dependencies listed.

## Known Bugs

### Euro Tiebreakers Not Properly Resolved

**Symptoms:** `compute_euro_standings` in `competitions/euro/simulation.py` sorts teams by points only (`sorted(team_stats.values(), key=lambda t: t["pts"], reverse=True)`, line 62). Unlike the worldcup version which calls `_tiebreak_group()` for proper FIFA tiebreaker chain (head-to-head, goal difference, goals scored, conduct, Elo), the Euro version just sorts by points. Teams tied on points will be ordered arbitrarily (dict iteration order), which can produce incorrect advancement outcomes.

**Files:** `competitions/euro/simulation.py` (line 62)

**Trigger:** Any group where two or more teams finish with equal points.

**Impact:** Incorrect group standings and potentially wrong knockout qualification in simulations.

**Workaround:** If groups rarely have ties, the impact is minimal. But it's a correctness bug.

### Euro simulation.py Imports from worldcup's src at Runtime

**Symptoms:** `competitions/euro/simulation.py` line 8 imports `from src.groups import (compute_standings, precompute_matchup_lambdas, rank_third_placed, select_advancers, simulate_group_matches)`. This `src` refers to `competitions/worldcup/src/` via the `sys.path` manipulation in `competitions/euro/__init__.py`. However, after importing these, the file defines its own `compute_euro_standings`, `rank_euro_third_placed`, `select_euro_advancers` that shadow/replace the functionality. This leads to confusion about which functions are actually used.

**Files:** `competitions/euro/simulation.py` (lines 8-14, 27-114)

**Impact:** The imported `compute_standings` is never directly used (the file uses `compute_euro_standings` instead), but `precompute_matchup_lambdas`, `simulate_group_matches`, `rank_third_placed`, and `select_advancers` from `src.groups` are used inside `resolve_knockout_slot_teams` (line 236-244), creating a mixed dependency.

**Workaround:** Euro works only if the worldcup package is intact.

## Security Considerations

### BSD_API_KEY in Environment Variables

**Risk:** The `BSD_API_KEY` is loaded from `os.environ` in both `competitions/euro/main.py` (line 195) and `competitions/worldcup/main.py` (line 1168). The `validate_api_key()` function in worldcup makes an actual HTTP request to validate the key, sending it over the network. The key is then passed through the entire call chain as a plain string.

**Files:**
- `competitions/euro/main.py` (lines 195-198)
- `competitions/worldcup/main.py` (lines 1168-1188)

**Current mitigation:** API key is loaded from environment (not hardcoded). Validation in worldcup catches invalid keys at startup.

**Recommendations:**
- No `.env` file should ever be committed (currently not detected in repo).
- Consider loading API key only in the function scope that needs it, not passing it through deep call chains.
- The `validate_api_key()` function leaks the API key prefix in error messages (not critical but worth awareness).

### .env Usage Without .env.example

**Risk:** While `python-dotenv` is used (`load_dotenv()`) in both main.py files, there is no `.env.example` or `.env.template` file checked into the repo. Developers must discover the required `BSD_API_KEY` variable by reading source code or documentation.

**Files:** (absence of) `.env.example`

**Current mitigation:** Worldcup's `validate_api_key()` prints a clear error message with the registration URL.

**Recommendations:** Add `.env.example` with `BSD_API_KEY=` placeholder and any other configurable vars.

## Performance Bottlenecks

### Monte Carlo at 50K Fixed Iterations

**Problem:** Both Euro (`competitions/euro/config.py`, line 7) and worldcup (`competitions/worldcup/main.py`, line 788, 1097) use a fixed 50,000 simulation iterations regardless of tournament stage or team count. Early in the tournament with many teams still alive, 50K provides good precision. Late in the tournament (when few teams remain), 50K iterations are wasteful — fewer samples are needed for convergence.

**Files:**
- `competitions/euro/config.py` (line 7)
- `competitions/worldcup/main.py` (lines 788, 1097)
- `competitions/worldcup/src/knockout.py` (line 166)

**Cause:** Fixed iteration count with no dynamic adjustment.

**Improvement path:** Implement adaptive iteration count based on the variance of probabilities. When the tournament is down to 8 teams, fewer iterations are needed. A dynamic approach could use a convergence check (e.g., stop when probability estimates stabilize within ±0.5%).

### Poisson Table Precomputation Cache

**Problem:** `football_core/groups.py` `_build_poisson_table` (lines 25-47) uses `@functools.lru_cache(maxsize=None)` to cache Poisson CDF tables keyed by lambda. In a single 50K-iteration run with 72 matches per iteration (48-team format), the same lambda values are looked up repeatedly. The cache is unbounded (`maxsize=None`), which means memory grows with the number of distinct lambda values encountered.

**Files:** `football_core/groups.py` (lines 25-47)

**Cause:** `maxsize=None` on the LRU cache means no upper bound on memory usage.

**Improvement path:** Set a reasonable `maxsize` (e.g., 1024) since there's a limited range of reasonable lambda values (mostly between 0.5 and 3.0). Or use a simple `dict` for explicit one-time precomputation.

### Inefficient Group Simulation Loop

**Problem:** `football_core/groups.py` `simulate_group_matches` function (lines 119-201) creates new Poisson tables at runtime inside the tight simulation loop via `table = build_table(la)` and `table = build_table(lb)` for each match. While cached, the method call overhead and the table lookup using `getrandbits` is repeated for every match in every iteration.

**Files:** `football_core/groups.py` (lines 163-174)

**Cause:** Each match computes a Poisson sample via table lookup, which requires building (or retrieving from cache) and indexing into a 1024-element table.

**Improvement path:** Consider using `random.expovariate` or `numpy.random.poisson` for faster sampling. The current approach was designed to avoid numpy dependency but may be 10-50x slower than vectorized alternatives.

## Fragile Areas

### Annex C 495-Entry Table

**Files:** `competitions/worldcup/data/annex_c.json`

**Why fragile:** The Annex C table is a hand-maintained 495-entry JSON mapping of all possible third-place advancement combinations for the 48-team format. `competitions/worldcup/src/groups.py` `resolve_r32_matchups` (lines 155-224) performs a string key lookup (`key = ",".join(advancing_groups)`) and raises `ValueError` if the key is not found. Any data corruption, formatting change, or missing combination will crash the entire simulation.

**Impact:** Complete simulation failure if the 495-entry table has any error. The data file is not generated/validated programmatically — it's a static artifact.

**Safe modification:** Always validate the Annex C file with a schema check before running. Consider generating it programmatically from the tournament rules.

### Hardcoded Group Letters Across Both Competitions

**Files:**
- `competitions/euro/simulation.py` — `"ABCDEF"` hardcoded in 4 places (lines 32, 73, 108, 119)
- `competitions/worldcup/src/groups.py` — `"ABCDEFGHIJKL"` hardcoded in 3 places (lines 27, 97, 141)

**Why fragile:** If the tournament format changes (e.g., Euro expands from 6 to 8 groups), every hardcoded string must be updated. The group letters are also used as dictionary keys in JSON data files, but there is no validation that data files match the hardcoded ranges.

**Safe modification:** Derive group letters from the actual data at runtime (e.g., `sorted(results.keys())`) rather than hardcoding them.

### sys.path Reliance for Import Resolution

**Files:**
- `competitions/worldcup/__init__.py` (lines 5-11)
- `competitions/euro/__init__.py` (lines 5-11)
- `competitions/worldcup/benchmarks/benchmark_groups.py` (line 20)
- `competitions/worldcup/scripts/benchmark_simulation.py` (line 14)
- `competitions/worldcup/tests/test_scaffold.py` (lines 12-13)
- `competitions/worldcup/tests/test_main_loop.py` (lines 32-33, 76-77, 317-318)
- `competitions/worldcup/tests/test_state.py` (lines 181-182, 231-232, 267-268, 297-298)

**Why fragile:** Sixteen `sys.path.insert(0, ...)` calls across the codebase. The `src` module name is a generic name and could clash with other packages. When running tests from different working directories, the `sys.path` manipulation may not work correctly, leading to confusing `ModuleNotFoundError` errors.

**Safe modification:** Convert the project to a proper installable package with `pyproject.toml`, eliminating the need for `sys.path` manipulation entirely. Use `pip install -e .` for development.

### Duplicate `_build_poisson_table` Cache Across Boundaries

**Files:**
- `football_core/groups.py` (line 25) — `@functools.lru_cache(maxsize=None)` on `_build_poisson_table`
- `competitions/worldcup/src/groups.py` (line 3) — re-exports `_build_poisson_table` from `football_core.groups`

**Why fragile:** Because `_build_poisson_table` is decorated with `lru_cache` and imported into a different module via `from football_core.groups import`, the cache is shared across all importers. This is correct but fragile — if anyone creates a separate copy of this function in a different module, the cache won't be shared and memory usage doubles.

**Safe modification:** Centralize the cached function in `football_core` and always import it from there.

### Euro main.py Mixes Euro and Worldcup Imports Within Functions

**Files:** `competitions/euro/main.py` — `_run_elo_sync` (line 60) imports `from src import elo_sync` and `_run_iteration` (lines 71-75) imports from `src` (worldcup package) inside the function body.

**Why fragile:** These lazy imports inside functions obscure dependencies. They only work because `competitions/euro/__init__.py` already manipulated `sys.path` to include the worldcup directory. If import order changes or if `__init__.py` is not executed first, these imports fail at runtime rather than at module load time.

**Safe modification:** Use direct imports from `football_core` or explicitly import from `competitions.worldcup.src` (avoiding sys.path tricks).

## Scaling Limits

### Single Package Structure

**Current capacity:** The repo supports 2 competitions (Euro 2024, World Cup 2026) with 1 placeholder (UCL).

**Limit:** Adding a new competition requires: (1) new directory under `competitions/`, (2) new `__init__.py` with sys.path manipulation, (3) new main.py, simulation.py etc that re-implements or imports worldcup-specific code, (4) new data files. There is no competition registration or discovery mechanism.

**Scaling path:** Create a `competition_registry.py` in `football_core` that dynamically discovers competitions. Extract common tournament logic into parameterized functions in `football_core/`.

### UCL Is a Placeholder

**Files:** `competitions/ucl/` (only contains `README.md`)

**Problem:** The UCL competition package is an empty stub. If the project aims to support multiple competitions, UCL needs full implementation — group stage format (8 groups of 4), knockout bracket (R16→QF→SF→FINAL), and its own data files, simulation logic.

## Dependencies at Risk

### BSD API Dependency

**Risk:** Both competitions depend entirely on the BSD API (`sports.bzzoiro.com`) for live match data. The API key is provided via environment variable. If the API goes down or changes its schema, the entire live prediction capability breaks.

**Files:**
- `football_core/fetcher.py` (lines 15-74)
- `competitions/worldcup/main.py` — `validate_api_key()` makes a separate API call
- `football_core/predictors/catboost.py` — makes a dedicated API call
- `football_core/predictors/odds.py` — processes API response data

**Impact:** Complete loss of live match data, odds, and ML predictions. Simulation can still run on Elo-only mode (Euro falls back gracefully, worldcup hard-exits without key).

**Migration plan:** Abstract the data source behind a `MatchDataProvider` interface. Add a local file-based provider for development/testing.

### Eloratings.net Dependency

**Risk:** The Elo sync feature in both competitions depends on `eloratings.net/World.tsv` and `eloratings.net/Europe.tsv`. These URLs are hardcoded (`football_core/constants.py` line 19 has the World URL, Euro's `main.py` line 62 has the Europe URL). If the site goes down, Elo ratings won't sync.

**Files:**
- `football_core/constants.py` (line 19)
- `competitions/euro/main.py` (line 62)

**Impact:** Elo ratings become stale. The code has a fallback to cached values, but stale ratings degrade prediction accuracy.

## Test Coverage Gaps

### Euro Package: Zero Tests

**What's not tested:** The entire `competitions/euro/` package — simulation engine (`simulation.py`), main loop (`main.py`), display (`display.py`), and config (`config.py`). No unit tests, no integration tests, no smoke tests.

**Files:** (entire) `competitions/euro/`

**Risk:** Any code change to Euro may cause regressions in simulation correctness, group standings resolution, or knockout bracket logic. Since Euro imports worldcup code, a change in worldcup could also break Euro silently.

**Priority:** High

### worldcup: Missing Tests for Main Loop Functions

**What's not tested:** The `_run_iteration` function in `competitions/worldcup/main.py` (line 743-1157, ~414 lines) is the heart of the application but is only tested through integration tests that mock the API. Individual sub-functions like `_gather_signal_data` (line 646), `_collect_matches_from_groups` (line 594), `_collect_matches_from_bracket` (line 619), and `_merge_signals_into_history` (line 76) lack dedicated unit tests.

**Files:** `competitions/worldcup/main.py` (lines 76-1157)

**Risk:** Complex data transformation functions with multiple branching paths are only exercised through full integration tests.

**Priority:** Medium

### football_core: Missing math_utils Tests

**What's not tested:** `football_core/math_utils.py` has a `sigmoid()` function but there are no dedicated tests for edge cases (overflow, large negative values, zero).

**Files:** `football_core/math_utils.py`

**Risk:** Minor — the sigmoid function is simple but the overflow case returns 0.0 for large negative inputs, which may be incorrect.

**Priority:** Low

---

*Concerns audit: 2026-06-27*
