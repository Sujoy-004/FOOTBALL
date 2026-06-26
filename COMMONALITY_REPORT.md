# COMMONALITY REPORT — Phase 2

**Rule of Two Audit**: Compare World Cup and Euro implementations to identify empirically proven candidates for `football_core`.

---

## 1. Modules Imported Unchanged by Both Competitions

These modules are imported with identical call signatures. Zero WC assumptions leak into them.

| Module | WC uses | Euro uses | Verdict |
|---|---|---|---|
| `src/elo.py` | `expected_score`, `apply_elo_update`, `update_ratings` | same 3 functions, same sigs | **dual-proven** |
| `src/fetcher.py` | `fetch_raw_matches`, `process_matches`, `process_group_matches` | same 3 functions, same sigs | **dual-proven** |
| `src/predictors/odds.py` | `fetch_and_cache_odds` | same sig | **dual-proven** |
| `src/predictors/catboost.py` | `fetch_and_cache_catboost` | same sig | **dual-proven** |
| `src/math_utils.py` | `sigmoid` | not imported yet (Euro has no blending) | single-proven (generic) |

Euro does NOT yet use: `blender.py`, `evaluation.py`, `governance.py`, `predictors/form.py`, `predictors/lineup.py`. These remain single-proven — not eligible for extraction yet.

---

## 2. Modules Requiring Only Configuration Differences

These modules are structurally identical — only parameter values differ between competitions.

### `src/elo_sync.py`
- World Cup calls: `sync_elo_from_eloratings(teams, data_dir)` → defaults to `ELORATINGS_TSV_URL` ("World.tsv")
- Euro calls: `sync_elo_from_eloratings(teams, data_dir, url="https://www.eloratings.net/Europe.tsv")`
- **Difference**: TSV URL only. Everything else (fetch→parse→validate→resolve→correct→persist) is identical.
- **Verdict**: Already parameterized. The hardcoded team code mapping (`ELORATINGS_TEAM_CODES` — 48 WC teams) is the remaining WC assumption. A parameterized team-code map makes this generic.

### `src/constants.py` (shared subset)
Both competitions reference these constants identically:
- `K_FACTOR`, `DEFAULT_ELO`, `MAX_EXPECTED_GOALS`, `HOME_ADVANTAGE_MULTIPLIER`
- `POISSON_TABLE_BITS`, `POISSON_TABLE_SIZE`
- `ELO_DRIFT_TOLERANCE`, `ELO_BLEND_THRESHOLD`, `ELO_BLEND_FACTOR`, `ELO_STALENESS_WARN_HOURS`
- `ELO_SYNC_RETRY_BACKOFFS`, `ELO_SYNC_TIMEOUT`, `API_TIMEOUT`
- `ODDS_CACHE_TTL_HOURS`, `CATBOOST_CACHE_TTL_HOURS`
- `TREND_THRESHOLD`

**Competition-specific constants in `src/constants.py`:**
- `GROUP_COUNT=12`, `ANNEX_C_ENTRIES=495`, `ANNEX_C_WINNER_GROUPS` — World Cup only
- `ELORATINGS_TEAM_CODES` — 48 WC teams; Euro needs European codes
- `GOV_BACKTEST_TOURNAMENTS=[2018, 2022]` — World Cup only
- `LEAGUES={27: "World Cup 2026"}` — World Cup only
- `WC_START_DATE` — World Cup only
- `DEFAULT_LEAGUE_ID=27` — World Cup only

---

## 3. Modules That Still Contain Hidden World-Cup Assumptions

### `src/state.py`
**Generic functions** (used identically by both): `load_teams`, `save_teams`, `load_played`, `save_played`, `load_played_groups`, `save_played_groups`, `load_signal_cache`, `save_signal_cache`, `load_prediction_history`, `append_prediction_history`, `load_prediction_ledger`, `save_prediction_ledger`, `load_eloratings_cache`, `save_eloratings_cache`, `load_elo_update_log`, `save_elo_update_log`, `load_team_values`, `load_calibration_params`, `save_calibration_params`, `load_probability_log`, `append_probability_log`, `is_cache_valid`, `_atomic_write_json`, `_resolve_data_dir`, `save_prediction_history`, `save_eval_baseline_report`.

**WC-only functions** (cannot be used by Euro without change):
- `validate_groups()` — hardcodes `GROUP_COUNT=12`, `"ABCDEFGHIJKL"`, `"GS_{letter}_"` prefix. Euro bypasses this by loading JSON directly.
- `load_groups()` — calls `validate_groups()`. Euro bypasses.
- `validate_annex_c()` — hardcodes 12-group Annex C structure. Euro has no Annex C.
- `load_annex_c()` — calls `validate_annex_c()`. Euro doesn't use.
- `load_bracket()` — calls `validate_bracket()` which is **generic** (pure DAG validation). The module-level bracket validation is OK.
- Governance/version functions: Euro doesn't run governance.

**Verdict**: The I/O core is proven generic. The group/annex validation functions remain WC-specific and should NOT be extracted.

### `src/groups.py`
**Generic functions** (used identically by both):
- `expected_goals()`, `_build_poisson_table()`, `_poisson_sample()`, `_simulate_single_match()` — pure math, no WC assumptions
- `precompute_matchup_lambdas()` — iterates whatever groups dict is given
- `simulate_group_matches()` — iterates whatever groups dict is given
- `_compute_conduct_score()` — generic fair-play penalty
- `_compute_h2h()` — generic head-to-head computation on results dict
- `_resolve_by_values()`, `_resolve_tied_cluster()`, `_tiebreak_group()` — generic 7-step FIFA tiebreaker

**WC-only functions**:
- `compute_standings()` — hardcodes `"ABCDEFGHIJKL"` and assumes 4 teams per group, iterates positions 1-4
- `rank_third_placed()` — hardcodes `"ABCDEFGHIJKL"`, assumes 12 third-placed teams, picks top 8
- `select_advancers()` — hardcodes `top8_groups`, `"ABCDEFGHIJKL"`
- `resolve_r32_matchups()` — full Annex C R32 logic (WC-specific knockout structure)

**How Euro works around this**: Euro defines `compute_euro_standings()`, `rank_euro_third_placed()`, `select_euro_advancers()` — all hardcode `"ABCDEF"` and Euro-specific advancement counts (top 4 third-placed instead of top 8). These are **copies** of the WC functions with different constants.

**Verdict**: The poisson core and tiebreaker chain are dual-proven. The group iteration functions (`compute_standings`, `rank_third_placed`, `select_advancers`) are competition-specific wrappers that differ only in format constants (6 vs 12 groups, 4 vs 8 third-placed advancers). These could be generalized by accepting group letters and advancement counts as parameters — but this is speculative until a third competition proves it. **Keep competition-specific for now.**

### `src/knockout.py`
Entirely World-Cup-specific. Contains:
- `ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]` with implicit R32 and TPP rounds
- `_simulate_r32_resolved()` — Annex C R32 resolution
- `_simulate_tpp()` — third-place playoff
- `_build_round_map()` — skips R32 (generic at core, but tied to WC-specific structure)
- `_simulate_r16()` — same as Euro's `_simulate_r16_resolved` but with different round structure
- `_simulate_knockout_round()` — **identical** to Euro's version
- `resolve_knockout_slot_teams()` — resolves teams for bracket slots (WC: includes R32, Annex C, TPP)
- `run_full_simulation()` — WC-specific orchestrator (includes R32, TPP, uses `select_advancers`/`rank_third_placed`/`compute_standings` from groups)

**Verdict**: The `_simulate_knockout_round()` and `_get_blended_prob()` functions are **identical** to their Euro counterparts — code-duplicated across competitions. The wrapping structure (which rounds exist, what advancement logic runs) is competition-specific. The simulation orchestrator should remain competition-specific; the round simulation primitives could be extracted.

### `src/output.py`
- World Cup display: WC header, group standings (12 groups), third-place bubble, Annex C references, probability table with trend arrows, AI previews, signal detail tables.
- Euro has its own `display.py` with a simpler probability table, no trends, no signal detail.

**Verdict**: Competition-specific. Display is inherently tied to competition branding, round names, and feature set.

---

## 4. Modules That Should Remain Competition-Specific

| Module | Reason |
|---|---|
| `competitions/euro/simulation.py` | Euro R16 resolution (precomputed third-place from bracket JSON), no R32, no TPP. Different orchestration. |
| `competitions/euro/main.py` | Different CLI, different data directory, different entry point. |
| `competitions/euro/display.py` | Different header, no ANSI color, no trend arrows, no signal detail tables |
| `competitions/euro/config.py` | Competition constants (6 groups, 4 third-placed, Euro league ID) |
| `worldcup_predictor/src/knockout.py` | R32 via Annex C, TPP, 12-group iteration. WC-specific orchestration. |
| `worldcup_predictor/src/output.py` | WC-specific display (12-group standings, Annex C, trend arrows, signal detail). |
| `worldcup_predictor/main.py` | WC-specific CLI, live loop, governance, blending, signal fusion. |
| Data files (`data/*.json`) | Teams, groups, bracket per competition. |
| `competitions/euro/data/*.json` | Euro teams, groups, bracket. |

---

## 5. Minimal Set of Empirically Proven Candidates for `football_core`

By the Rule of Two — modules BOTH competitions use identically with zero code change:

### Tier 1: Proven Dual-Use (extract immediately)

| Module | Functions | Evidence |
|---|---|---|
| `src/elo.py` | `expected_score`, `update_ratings`, `apply_elo_update` | Both call identically. Pure Elo math. |
| `src/fetcher.py` | `fetch_raw_matches`, `process_matches`, `process_group_matches` | Both call identically. BSD API fetch+dedup pipeline. |
| `src/predictors/odds.py` | `fetch_and_cache_odds` | Both call identically. |
| `src/predictors/catboost.py` | `fetch_and_cache_catboost` | Both call identically. |
| `src/groups.py` (core subset) | `_build_poisson_table`, `_poisson_sample`, `_simulate_single_match`, `expected_goals`, `_compute_conduct_score`, `_compute_h2h`, `_resolve_by_values`, `_resolve_tied_cluster`, `_tiebreak_group`, `precompute_matchup_lambdas`, `simulate_group_matches` | Both use `precompute_matchup_lambdas` and `simulate_group_matches` identically. The poisson and tiebreaker internals have zero WC assumptions. |
| `src/state.py` (I/O subset) | `load_teams`, `save_teams`, `load_played`, `save_played`, `load_played_groups`, `save_played_groups`, `load_signal_cache`, `save_signal_cache`, `load_prediction_history`, `append_prediction_history`, `is_cache_valid`, `_atomic_write_json`, `_resolve_data_dir`, `load_eloratings_cache`, `save_eloratings_cache`, `load_elo_update_log`, `save_elo_update_log` | Both use load/save/append for state files with `data_dir` parameter. Zero WC assumptions. |
| `src/math_utils.py` | `sigmoid` | Generic utility. Euro doesn't use it yet but pure math has zero WC assumptions. |

### Tier 2: Parameterizably-Generic (extract after adding competition parameter)

| Module | What's needed |
|---|---|
| `src/elo_sync.py` | `ELORATINGS_TEAM_CODES` must become a parameter (not a module constant). Already parameterized for URL. |

### Tier 3: Not Yet Dual-Proven (do NOT extract)

| Module | Why |
|---|---|
| `src/blender.py` | Euro doesn't use blending yet. Single-proven. |
| `src/evaluation.py` | Euro doesn't evaluate yet. Single-proven. |
| `src/governance.py` | Euro doesn't run governance. Single-proven. |
| `src/predictors/form.py` | Euro doesn't compute form. Single-proven. |
| `src/predictors/lineup.py` | Euro doesn't compute lineup. Single-proven. |

---

## 6. Extraction Plan

### Step 1: Create `src/football_core/` directory
Minimal extraction of Tier 1 modules. Pure rename — no behavior changes.

```
src/football_core/
    __init__.py
    elo.py              ← from src/elo.py
    elo_sync.py         ← from src/elo_sync.py (keep WC code map, add param)
    fetcher.py          ← from src/fetcher.py
    groups.py           ← from src/groups.py (keep WC-specific functions, export)
    state.py            ← from src/state.py (keep WC-specific functions, export)
    math_utils.py       ← from src/math_utils.py
    predictors/
        __init__.py
        odds.py         ← from src/predictors/odds.py
        catboost.py     ← from src/predictors/catboost.py
```

### Step 2: Point `worldcup_predictor/src/*.py` to import from `football_core`
Each existing module re-exports from `football_core`:

```python
# src/elo.py becomes:
from football_core.elo import *  # noqa: F401,F403
```

### Step 3: Point `competitions/euro/*.py` to import from `football_core`
Same pattern.

### Step 4: Verify
- WC tests pass (613 + 1 skipped)
- Euro simulation runs identically
- No behavior change — only import paths changed

### Step 5: Commit sequence
1. Create `football_core/` with all proven modules
2. Rewire `worldcup_predictor/src/` imports → `football_core`
3. Rewire `competitions/euro/` imports → `football_core`
4. Remove `competitions/euro/__init__.py` sys.path hack (no longer needed since `football_core` is accessible)
5. Verify both competitions
