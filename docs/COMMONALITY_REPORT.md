# COMMONALITY REPORT

**Rule of Two Audit**: Compare World Cup and Euro implementations to identify empirically proven candidates for `football_core`.

---

## 1. Modules Imported Unchanged by Both Competitions

These modules are imported with identical call signatures. Zero WC assumptions leak into them.

| Module | WC uses | Euro uses | Verdict |
|---|---|---|---|
| `elo.py` | `expected_score`, `apply_elo_update`, `update_ratings` | same 3 functions, same sigs | **dual-proven** |
| `fetcher.py` | `fetch_raw_matches`, `process_matches`, `process_group_matches` | same 3 functions, same sigs | **dual-proven** |
| `predictors/odds.py` | `fetch_and_cache_odds` | same sig | **dual-proven** |
| `predictors/catboost.py` | `fetch_and_cache_catboost` | same sig | **dual-proven** |
| `math_utils.py` | `sigmoid` | not imported yet (Euro has no blending) | single-proven (generic) |

Euro does NOT yet use: `blender.py`, `evaluation.py`, `governance.py`, `predictors/form.py`, `predictors/lineup.py`. These remain single-proven — not eligible for extraction.

---

## 2. Modules Requiring Only Configuration Differences

These modules are structurally identical — only parameter values differ between competitions.

### `elo_sync.py`
- World Cup calls: `sync_elo_from_eloratings(teams, data_dir)` → defaults to `ELORATINGS_TSV_URL` ("World.tsv")
- Euro calls: `sync_elo_from_eloratings(teams, data_dir, url="https://www.eloratings.net/Europe.tsv")`
- **Difference**: TSV URL only. Everything else (fetch→parse→validate→resolve→correct→persist) is identical.
- **Verdict**: Already parameterized. The hardcoded team code mapping (`ELORATINGS_TEAM_CODES` — 48 WC teams) is the remaining WC assumption. A parameterized team-code map makes this generic.

### `constants.py` (shared subset)
Both competitions reference these constants identically:
- `K_FACTOR`, `DEFAULT_ELO`, `MAX_EXPECTED_GOALS`, `HOME_ADVANTAGE_MULTIPLIER`
- `POISSON_TABLE_BITS`, `POISSON_TABLE_SIZE`
- `ELO_DRIFT_TOLERANCE`, `ELO_BLEND_THRESHOLD`, `ELO_BLEND_FACTOR`, `ELO_STALENESS_WARN_HOURS`
- `ELO_SYNC_RETRY_BACKOFFS`, `ELO_SYNC_TIMEOUT`, `API_TIMEOUT`
- `ODDS_CACHE_TTL_HOURS`, `CATBOOST_CACHE_TTL_HOURS`
- `TREND_THRESHOLD`

**Competition-specific constants in `competitions/worldcup/src/constants.py`:**
- `GROUP_COUNT=12`, `ANNEX_C_ENTRIES=495`, `ANNEX_C_WINNER_GROUPS` — World Cup only
- `ELORATINGS_TEAM_CODES` — 48 WC teams; Euro needs European codes
- `GOV_BACKTEST_TOURNAMENTS=[2018, 2022]` — World Cup only
- `LEAGUES={27: "World Cup 2026"}` — World Cup only
- `WC_START_DATE` — World Cup only
- `DEFAULT_LEAGUE_ID=27` — World Cup only

The generic subset was extracted into `football_core/constants.py`.

---

## 3. Modules That Still Contain Hidden World-Cup Assumptions

### `state.py`
**Generic functions** (used identically by both): `load_teams`, `save_teams`, `load_played`, `save_played`, `load_played_groups`, `save_played_groups`, `load_signal_cache`, `save_signal_cache`, `load_prediction_history`, `append_prediction_history`, `load_prediction_ledger`, `save_prediction_ledger`, `load_eloratings_cache`, `save_eloratings_cache`, `load_elo_update_log`, `save_elo_update_log`, `load_team_values`, `load_calibration_params`, `save_calibration_params`, `load_probability_log`, `append_probability_log`, `is_cache_valid`, `_atomic_write_json`, `_resolve_data_dir`, `save_prediction_history`, `save_eval_baseline_report`.

These were extracted into `football_core/state.py`.

**WC-only functions** (remain in `competitions/worldcup/src/state.py`):
- `validate_groups()` — hardcodes `GROUP_COUNT=12`, `"ABCDEFGHIJKL"`, `"GS_{letter}_"` prefix. Euro bypasses this by loading JSON directly.
- `load_groups()` — calls `validate_groups()`. Euro bypasses.
- `validate_annex_c()` — hardcodes 12-group Annex C structure. Euro has no Annex C.
- `load_annex_c()` — calls `validate_annex_c()`. Euro doesn't use.
- `migrate_prediction_history()`, `ledger_upsert()`, `save_run_snapshot()`, `load_run_snapshot()`, `save_eval_baseline_report()` — Euro doesn't use governance/version features.

### `groups.py`
**Generic functions** (extracted into `football_core/groups.py`):
- `expected_goals()`, `_build_poisson_table()`, `_poisson_sample()`, `_simulate_single_match()` — pure math, no WC assumptions
- `precompute_matchup_lambdas()` — iterates whatever groups dict is given
- `simulate_group_matches()` — iterates whatever groups dict is given
- `_compute_conduct_score()` — generic fair-play penalty
- `_compute_h2h()` — generic head-to-head computation on results dict
- `_resolve_by_values()`, `_resolve_tied_cluster()`, `_tiebreak_group()` — generic 7-step FIFA tiebreaker

**WC-only functions** (remain in `competitions/worldcup/src/groups.py`):
- `compute_standings()` — hardcodes `"ABCDEFGHIJKL"` and assumes 4 teams per group, iterates positions 1-4
- `rank_third_placed()` — hardcodes `"ABCDEFGHIJKL"`, assumes 12 third-placed teams, picks top 8
- `select_advancers()` — hardcodes `top8_groups`, `"ABCDEFGHIJKL"`
- `resolve_r32_matchups()` — full Annex C R32 logic (WC-specific knockout structure)

**How Euro works around this**: Euro defines `compute_euro_standings()`, `rank_euro_third_placed()`, `select_euro_advancers()` in `competitions/euro/simulation.py` — all hardcode `"ABCDEF"` and Euro-specific advancement counts (top 4 third-placed instead of top 8). These are copies of the WC functions with different constants. Additionally, Euro imports `compute_standings`, `rank_third_placed`, `select_advancers` from `src.groups` (WC) for `resolve_knockout_slot_teams` (historical catch-up, not simulation) — this import works via the sys.path hack in `competitions/euro/__init__.py`.

**Verdict**: The poisson core and tiebreaker chain are dual-proven and now extracted. The group iteration functions are competition-specific wrappers that differ only in format constants (6 vs 12 groups, 4 vs 8 third-placed advancers). These could be generalized by accepting group letters and advancement counts as parameters — but this is speculative until a third competition proves it. **Keep competition-specific for now.**

### `knockout.py`
**Generic primitives** (extracted into `football_core/knockout.py`):
- `_simulate_knockout_round()` — identical to Euro's version
- `_get_blended_prob()`

**WC-specific** (remain in `competitions/worldcup/src/knockout.py`):
- `ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]` with implicit R32 and TPP rounds
- `_simulate_r32_resolved()` — Annex C R32 resolution
- `_simulate_tpp()` — third-place playoff
- `_build_round_map()`, `resolve_knockout_slot_teams()`
- `run_full_simulation()` — WC-specific orchestrator (includes R32, TPP, uses `select_advancers`/`rank_third_placed`/`compute_standings` from groups)

**Verdict**: The `_simulate_knockout_round()` primitive is now shared via `football_core/knockout.py`. The wrapping structure (which rounds exist, what advancement logic runs) is competition-specific. The simulation orchestrator remains in each competition.

### `competitions/worldcup/src/output.py`
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
| `competitions/worldcup/src/knockout.py` | R32 via Annex C, TPP, 12-group iteration. WC-specific orchestration. |
| `competitions/worldcup/src/output.py` | WC-specific display (12-group standings, Annex C, trend arrows, signal detail). |
| `competitions/worldcup/main.py` | WC-specific CLI, live loop, governance, blending, signal fusion. |
| Data files (`data/*.json`) | Teams, groups, bracket per competition. |
| `competitions/euro/data/*.json` | Euro teams, groups, bracket. |

---

## 5. Current State of `football_core`

The extraction followed the Rule of Two. The following modules now reside in `football_core/` at repo root, organized as a flat package:

```
FOOTBALL/
├── football_core/
│   ├── __init__.py       ← empty
│   ├── constants.py      ← generic constants only
│   ├── elo.py             ← pure Elo math
│   ├── elo_sync.py        ← eloratings sync (URL parameterized)
│   ├── fetcher.py         ← BSD API fetch+dedup pipeline
│   ├── groups.py          ← poisson engine + generic tiebreaker chain
│   ├── knockout.py        ← generic round simulation primitive
│   ├── math_utils.py      ← sigmoid
│   ├── state.py           ← generic I/O (all functions accept data_dir)
│   └── predictors/
│       ├── __init__.py
│       ├── odds.py        ← market odds fetch
│       └── catboost.py    ← CatBoost prediction fetch
│
├── competitions/
│   ├── worldcup/          ← WC-specific code
│   │   ├── main.py        ← WC orchestrator
│   │   ├── __init__.py    ← sys.path bootstrap
│   │   └── src/
│   │       ├── constants.py      ← extends football_core.constants with WC-specific values
│   │       ├── groups.py         ← extends football_core.groups with compute_standings/rank/select/resolve
│   │       ├── state.py          ← extends football_core.state with WC validate/load + governance persistence
│   │       ├── knockout.py       ← WC-only (R32, TPP, full simulation orchestrator)
│   │       ├── output.py         ← WC-only display
│   │       ├── blender.py        ← WC-only (calibrate_and_blend)
│   │       ├── evaluation.py     ← WC-only (evaluate_all_matches)
│   │       ├── governance.py     ← WC-only (_run_governance)
│   │       ├── enrichment.py     ← WC-only (stats/context extraction)
│   │       └── predictors/
│   │           ├── form.py       ← WC-only
│   │           └── lineup.py     ← WC-only
│   │
│   ├── euro/              ← Euro-specific code
│   │   ├── main.py        ← thin Euro orchestrator
│   │   ├── __init__.py    ← sys.path bootstrap (repo root + worldcup/ for src.groups)
│   │   ├── simulation.py  ← Euro simulation engine
│   │   ├── display.py     ← Euro display
│   │   ├── config.py      ← Euro constants
│   │   └── data/
│   │
│   └── ucl/               ← placeholder
│       └── README.md
│
├── docs/
│   ├── COMMONALITY_REPORT.md
│   └── FOOTBALL_ENGINE_ARCHITECTURE.md
├── .gitignore
└── RESPONSE.md
```

### Import pattern

Each `competitions/worldcup/src/*.py` that maps to a `football_core/` module is a thin re-export:

```python
# competitions/worldcup/src/elo.py
from football_core.elo import *  # noqa: F401,F403
```

For modules that extend `football_core`, the import is selective:

```python
# competitions/worldcup/src/groups.py
from football_core.groups import (
    expected_goals, _build_poisson_table, simulate_group_matches,
    _tiebreak_group, ...
)
# ... then WC-specific compute_standings(), rank_third_placed(), etc.
```

### What was NOT extracted

The following modules are single-proven (WC only) and remain in `competitions/worldcup/src/`:

| Module | Why Not Extracted |
|---|---|
| `blender.py` | Euro doesn't use blending yet |
| `evaluation.py` | Euro doesn't evaluate yet |
| `governance.py` | Euro doesn't run governance |
| `predictors/form.py` | Euro doesn't compute form |
| `predictors/lineup.py` | Euro doesn't compute lineup |
| `enrichment.py` | Euro doesn't fetch BSD stats |

---

## 6. Euro sys.path Hack

`competitions/euro/__init__.py` still adds the repo root and `competitions/worldcup/` to `sys.path`. This is necessary because `competitions/euro/simulation.py` imports `from src.groups import compute_standings, rank_third_placed, select_advancers` — these are WC-specific functions used in `resolve_knockout_slot_teams` (historical catch-up, not simulation). Until these are refactored into a shared location or Euro no longer needs them, the sys.path hack remains.
