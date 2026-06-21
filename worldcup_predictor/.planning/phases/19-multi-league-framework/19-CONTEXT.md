# Phase 19: Multi-League Framework — Context

**Gathered:** 2026-06-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Refactor from single-league lock (`league_id=27`) to support all 65 BSD leagues. Users select any league via `--league` CLI flag or `config.json`, with per-league state isolation (`data/{league_id}/`).

Scope: V2-25 (CLI league selection), V2-26 (per-league state file namespacing).

This phase does NOT implement any per-league feature differences (all leagues treated identically), does NOT change simulation/prediction logic, and does NOT add league-specific calibration — those are future concerns.
</domain>

<decisions>
## Implementation Decisions

### Area 1: League Catalog Source
- **D-01:** League catalog lives in `constants.py` — static `LEAGUES` dict mapping `{league_id: str}` to league names.
- **D-02:** `--list-leagues` flag reads from `constants.py`. No API call for catalog.
- **D-03:** League IDs remain stable and version-controlled. Future additions require code change + test update.
- **D-04:** Rejected: fetching from BSD API (runtime dependency, startup latency, failure mode) and `config.json` (no architectural benefit over constant).

### Area 2: State Directory Migration
- **D-05:** Automatic one-time migration on first run with league=27. If `data/played.json` exists AND `data/27/played.json` does NOT exist, copy league-scoped files into `data/27/`.
- **D-06:** Migration copies: `played.json`, `played_groups.json`, `prediction_history.json`, `predictions_ledger.json`, and any other league-scoped state files.
- **D-07:** Original `data/*.json` files are never deleted — migration is non-destructive.
- **D-08:** Migration is idempotent — guard by checking `data/27/played.json` existence. Second startup performs zero migration work.
- **D-09:** Rejected: flag-based migration (unnecessary operational burden) and clean break (orphans state, breaks continuity).

### Area 3: Config Mechanism
- **D-10:** Precedence: CLI `--league` > `config.json` > default league 27.
- **D-11:** `config.json` is the single source of persisted league preference. Auto-created with `{"league_id": 27}` if missing.
- **D-12:** Corrupt `config.json` falls back to league 27 gracefully (log warning, continue).
- **D-13:** Rejected: env var only (deployment concern, poor UX) and CLI-only (no persistence, defeats purpose).

### Area 4: Per-League vs Shared Data
- **D-14:** Rule: shared = immutable reference data; per-league = anything generated, learned, cached, calibrated, or stateful.
- **D-15:** **Shared** (stays in `data/`): `bracket.json`, `groups.json`, `annex_c.json`, `team_aliases.json`, `team_values.json`.
- **D-16:** **Per-league** (moves to `data/{league_id}/`): `played.json`, `played_groups.json`, `teams.json`, `predictions_ledger.json`, `prediction_history.json`, `catboost_cache.json`, `odds_cache.json`, `form_cache.json`, `lineup_cache.json`, `elo_applied.json`, `elo_update_log.json`, `calibration_params.json`, `versions.json`.
- **D-17:** Rationale for `calibration_params.json` = per-league: calibration is league-specific (World Cup calibration must not affect EPL predictions).
- **D-18:** Rationale for `versions.json` = per-league: `data_version` tracks league match data, `model_version` tracks league calibration, `run_version` tracks league governance.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §V2-25 (line 85) — League selection via CLI flag
- `.planning/REQUIREMENTS.md` §V2-26 (line 86) — Multi-league data isolation

### Roadmap & State
- `.planning/ROADMAP.md` §Phase 19 (line 597) — Goal, success criteria, plan list
- `.planning/STATE.md` — Current project state and session continuity
- `.planning/PROJECT.md` — Project overview, constraints, key decisions

### Source Files (hardcoded league_id=27 sites)
- `src/constants.py:15` — `API_URL` constant
- `src/fetcher.py:20` — `build_historic_url()` date-range URL
- `src/predictors/catboost.py:266` — predictions endpoint URL
- `tests/test_fetcher.py:60` — test assertion checking `league_id=27`

### Config & Data Pattern
- `src/state.py` — All load/save functions (need league-scoped data_dir)
- `src/output.py` — League display functions (governance dashlet, etc.)
- `src/governance.py` — Version tracking (needs per-league versions.json)
</canonical_refs>

<code_context>
## Existing Code Insights

### Established Patterns
- CLI args parsed via `argparse` in `main.py` (established: `--once`, `--no-color`, `--seed`, `--ai-preview`)
- Config via env vars + hardcoded defaults (no `config.json` currently — this phase introduces it)
- State persistence via `state.py` load/save functions with `Path`-based `data_dir`
- Atomic writes via `tmp+rename` in `state.py`
- API URLs constructed in `fetcher.py` and `predictors/catboost.py` as string templates with hardcoded `league=27`

### Reusable Assets
- `state.py` load/save functions can accept dynamic `data_dir` — current default is `constants.DATA_DIR`
- `fetcher.py` `fetch_raw_matches()` accepts `api_url` param (already overridable)

### Integration Points
- `main.py` — Entry point for CLI flag parsing + config.json loading + data_dir resolution
- `state.py` — All persistence functions need league-scoped `data_dir` (or default to shared `data/`)
- `fetcher.py` — `build_historic_url()` and `fetch_raw_matches()` call sites need league-aware URL construction
- `predictors/catboost.py` — Predictions endpoint URL needs league parameter
- `constants.py` — `API_URL` needs `league_id` parameterized; `DATA_DIR` needs league subdirectory support
- `governance.py` — `load_versions`/`save_versions` need league-scoped `data_dir`
- `tests/test_fetcher.py:60` — Assertion needs to accept dynamic league_id
</code_context>

<specifics>
## Specific Ideas

No specific implementation-level requirements — standard approach expected. Key architectural constraint: the change should be minimal and focused on the 4 hardcoded sites.
</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.
</deferred>

---

*Phase: 19-Multi-League Framework*
*Context gathered: 2026-06-19*
