# FOOTBALL Repository — Stage 1 Audit

> Generated: 2026-06-26  
> Mode: Read-only — no files were modified, moved, or deleted during this audit.

---

## 1. Repository Tree

```
FOOTBALL/
├── .gitignore                          # Root-level gitignore (11 lines)
├── AGENTS.md                           # (deleted from index per git log)
├── README.md
├── worldcup_predictor/                 # 🟢 Full-stack project — LIVE
│   ├── .coverage                       # (untracked, runtime artifact)
│   ├── .env.example
│   ├── .gitignore                      # 51 lines — comprehensive
│   ├── .planning/                      # (gitignored) GSD research artifacts
│   ├── config.json                     # {"league_id": 27}
│   ├── main.py                         # ~2200+ lines — entry point
│   ├── requirements.txt
│   ├── benchmarks/
│   │   └── BENCHMARK_RESULTS_08.md     # (ignored)
│   ├── data/
│   │   ├── annex_c.json                # SOURCE — FIFA Annex C routing
│   │   ├── bracket.json                # SOURCE — 32-match bracket
│   │   ├── eloratings_cache.json       # GENERATED — Elo sync cache (dirty)
│   │   ├── groups.json                 # SOURCE — 12 groups A-L
│   │   ├── team_aliases.json           # SOURCE — name canonicalization
│   │   ├── team_values.json            # SOURCE — team metadata
│   │   ├── teams.json                  # SOURCE — 48 teams
│   │   ├── calibration_params.json     # GENERATED — (dirty)
│   │   ├── catboost_cache.json         # GENERATED — (dirty)
│   │   ├── eval_backtest_report.json   # GENERATED — (dirty)
│   │   ├── form_cache.json             # GENERATED — (dirty)
│   │   ├── lineup_cache.json           # GENERATED — (dirty)
│   │   ├── odds_cache.json             # GENERATED — (dirty)
│   │   ├── prediction_history.json     # GENERATED — (dirty)
│   │   ├── predictions_ledger.json     # GENERATED — (dirty)
│   │   ├── probability_log.json        # GENERATED — (dirty)
│   │   ├── versions.json               # GENERATED — (dirty)
│   │   ├── elo_applied.json            # GENERATED
│   │   ├── elo_update_log.json         # GENERATED
│   │   ├── played_groups.json          # GENERATED
│   │   ├── played.json                 # GENERATED
│   │   ├── 27/                         # (gitignored) variant run data
│   │   └── runs/                       # (gitignored) prediction run outputs
│   ├── src/
│   │   ├── __init__.py
│   │   ├── blender.py                  # Multi-signal blending
│   │   ├── constants.py                # URLs, config, magic numbers
│   │   ├── elo.py                      # Elo rating engine
│   │   ├── elo_sync.py                 # Auto-sync from eloratings.net
│   │   ├── enrichment.py               # Match context enrichment
│   │   ├── evaluation.py               # Model evaluation (Brier, log loss)
│   │   ├── fetcher.py                  # BSD API fetch layer
│   │   ├── governance.py               # Model governance (versioning, drift)
│   │   ├── groups.py                   # Group stage simulation
│   │   ├── knockout.py                 # Knockout bracket simulation
│   │   ├── output.py                   # Console formatting
│   │   ├── state.py                    # State management, persistence
│   │   └── predictors/
│   │       ├── __init__.py
│   │       ├── catboost.py             # CatBoost ML predictor
│   │       ├── form.py                 # Recent form predictor
│   │       ├── lineup.py               # Lineup strength predictor
│   │       └── odds.py                 # Betting odds predictor
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_blender.py
│       ├── test_catboost.py
│       ├── test_cli.py
│       ├── test_config.py
│       ├── test_elo.py
│       ├── test_elo_sync.py
│       ├── test_enrichment.py
│       ├── test_evaluation.py
│       ├── test_fetcher.py
│       ├── test_form.py
│       ├── test_governance.py
│       ├── test_group_integration.py
│       ├── test_groups.py
│       ├── test_integration.py
│       ├── test_knockout.py
│       ├── test_lineup.py
│       ├── test_live_smoke.py
│       ├── test_main_loop.py
│       ├── test_migration.py
│       ├── test_odds.py
│       ├── test_output.py
│       ├── test_scaffold.py
│       ├── test_state.py
│       └── test_state_load.py
├── euro_predictor/                     # 🔴 Placeholder only
│   └── README.md                       # "Coming soon."
└── ucl_predictor/                      # 🔴 Placeholder only
    └── README.md                       # "Coming soon."
```

---

## 2. Root Directory Audit

| Item | Status | Notes |
|------|--------|-------|
| `.gitignore` | ✅ Present | 11 lines — ignores `.planning/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.env` |
| `README.md` | ✅ Present | Top-level project README |
| `AGENTS.md` | ❌ Deleted | Removed from tracking in commit `43d23db` ("chore: remove AGENTS.md") |
| `worldcup_predictor/` | 🟢 Active | Fully built prediction engine |
| `euro_predictor/` | 🔴 Stub | Single-line README placeholder |
| `ucl_predictor/` | 🔴 Stub | Single-line README placeholder |

**Finding:** The repo has two completely empty sub-projects (`euro_predictor/`, `ucl_predictor/`) that exist only as placeholder READMEs. They contribute nothing to the current codebase.

---

## 3. Documentation Audit

### Planning Docs (`.planning/` — all gitignored)

| File | Purpose | Status |
|------|---------|--------|
| `PROJECT.md` | Project charter, architecture diagram, milestones | ✅ Comprehensive (249 lines) |
| `REQUIREMENTS.md` | Full requirement specification | ✅ Present |
| `ROADMAP.md` | Milestone/phase roadmap | ✅ Present |
| `STATE.md` | Current milestone state (v2.0: 20/20 phases, 57/57 plans — 100%) | ✅ Present |
| `codebase/` (7 files) | ARCHITECTURE, CONCERNS, CONVENTIONS, FEATURES, INTEGRATIONS, STACK, STRUCTURE, TESTING | ✅ Comprehensive |
| `milestones/` | v1.0 requirements + roadmap | ✅ Present |
| `phases/` (20 phases) | Phase plans, summaries, contexts, discussion logs, research, validation | ✅ 20 phases, 57 plans |
| `research/` (5 files) | ARCHITECTURE, FEATURES, PITFALLS, STACK, SUMMARY | ✅ Present |

**State assertion:** "601 passed, 1 skipped (live smoke needs BSD_API_KEY)" — per STATE.md

### Source README (implied)
- `worldcup_predictor/requirements.txt` lists all Python dependencies.
- No separate README exists within `worldcup_predictor/`; the root `README.md` serves as project documentation.

---

## 4. Source Structure Audit

### Module Inventory (`src/`)

| Module | LOC (approx) | Responsibility |
|--------|-------------|---------------|
| `main.py` | 2200+ | Entry point, continuous polling loop, CLI wiring |
| `state.py` | ~500 | State persistence (JSON read/write), data directory management, migration |
| `constants.py` | ~250 | BSD API URLs, Elo constants, league definitions (48-team code map), default league ID |
| `elo.py` | ~150 | Elo rating formula (expected score, K-factor, update) |
| `elo_sync.py` | ~367 | Auto-sync from eloratings.net (fetch → parse → validate → resolve → persist) |
| `groups.py` | ~300 | Group stage simulation (Poisson, H2H tiebreaker, Annex C R32 resolution) |
| `knockout.py` | ~300 | Knockout bracket simulation, 104-match tournament tree |
| `output.py` | ~300 | Console formatting (colored tables, deltas, standings) |
| `fetcher.py` | ~200 | BSD API HTTP fetch layer (retries, caching, error handling) |
| `blender.py` | ~200 | Multi-signal probability blending (odds, Elo, CatBoost, form, lineup) |
| `evaluation.py` | ~200 | Model evaluation (Brier score, log loss, backtesting) |
| `governance.py` | ~200 | Version tracking, drift detection, governance dashlet |
| `enrichment.py` | ~150 | Match context extraction (stats extraction, context enrichment) |
| `predictors/__init__.py` | ~20 | Predictor registry |
| `predictors/odds.py` | ~100 | Betting odds signal ingestion |
| `predictors/catboost.py` | ~100 | CatBoost ML model inference |
| `predictors/form.py` | ~80 | Recent form signal computation |
| `predictors/lineup.py` | ~80 | Lineup strength estimation |

**Total:** ~5300 LOC Python (excluding tests)

### Dead / Commented-Out Code
- Search needed — not obvious from file listing alone. The `predictors/__init__.py` should be inspected for unused registrations.

### Module Coupling (architectural)
```
main.py ──► state.py, fetcher.py, elo_sync.py, groups.py, knockout.py,
             output.py, evaluation.py, governance.py, enrichment.py, blender.py
                │
                ├──► predictors/odds.py
                ├──► predictors/catboost.py
                ├──► predictors/form.py
                └──► predictors/lineup.py
                    elo.py (used by elo_sync.py, elo.py)
```

---

## 5. Test Audit

### Test Inventory

| File | Type | Notes |
|------|------|-------|
| `conftest.py` | Fixtures | Shared test fixtures and mocks |
| `test_blender.py` | Unit | Signal blending tests |
| `test_catboost.py` | Unit | CatBoost predictor tests |
| `test_cli.py` | Unit | CLI argument parsing tests |
| `test_config.py` | Unit | Config file loading tests |
| `test_elo.py` | Unit | Elo formula tests |
| `test_elo_sync.py` | Unit | Elo sync tests |
| `test_enrichment.py` | Unit | Match enrichment tests |
| `test_evaluation.py` | Unit | Evaluation metric tests |
| `test_fetcher.py` | Unit | BSD API fetch tests |
| `test_form.py` | Unit | Form predictor tests |
| `test_governance.py` | Unit | Governance/drift tests |
| `test_group_integration.py` | Integration | Group stage integration |
| `test_groups.py` | Unit | Group simulation tests |
| `test_integration.py` | Integration | Full pipeline integration |
| `test_knockout.py` | Unit | Bracket simulation tests |
| `test_lineup.py` | Unit | Lineup predictor tests |
| `test_live_smoke.py` | Smoke | Live API smoke test (skipped without BSD_API_KEY) |
| `test_main_loop.py` | Integration | Main loop integration |
| `test_migration.py` | Unit | Data migration tests |
| `test_odds.py` | Unit | Odds predictor tests |
| `test_output.py` | Unit | Console output tests |
| `test_scaffold.py` | Unit | Scaffold tests |
| `test_state.py` | Unit | State management tests |
| `test_state_load.py` | Unit | State loading tests |

**Total test modules:** 25  
**Total tests (per STATE.md):** 601 passed, 1 skipped  
**Coverage:** `.coverage` file present (untracked)

### Test Quality Observations
- Strong unit test coverage across all modules.
- Integration tests for group stage, main loop, full pipeline.
- Live smoke test exists but requires `BSD_API_KEY` environment variable.
- Test fixtures in `conftest.py` use mocks for BSD API and eloratings.net.

---

## 6. Data Audit

### Source Data (tracked, human-authored)

| File | Records | Purpose |
|------|---------|---------|
| `teams.json` | 48 teams | FIFA 2026 qualified teams with Elo ratings |
| `groups.json` | 12 groups | Groups A–L with 72 round-robin match definitions |
| `annex_c.json` | ~495 entries | FIFA Annex C R32 routing table |
| `team_aliases.json` | 48 entries | Name canonicalization map |
| `team_values.json` | 48 entries | Team metadata (FIFA code, confederation, etc.) |
| `bracket.json` | 32 slots | Knockout bracket with slot descriptors |

### Generated Data (git-tracked but gitignored)

**Critical finding:** The following files are listed in `worldcup_predictor/.gitignore` (lines 28–45) but were **previously tracked** and remain in the index. Gitignore does not apply to tracked files, so they appear as "modified" in `git status`:

| File | Status | Lines Changed |
|------|--------|-------------|
| `prediction_history.json` | MODIFIED | +3674 lines |
| `predictions_ledger.json` | MODIFIED | +352 / -205 |
| `probability_log.json` | MODIFIED | +340 lines |
| `calibration_params.json` | MODIFIED | ±32 lines |
| `eval_backtest_report.json` | MODIFIED | ±6 lines |
| `form_cache.json` | MODIFIED | ±4 lines |
| `lineup_cache.json` | MODIFIED | ±4 lines |
| `versions.json` | MODIFIED | ±12 lines |

**Total unstaged diff:** +4219 / -205 lines across 8 generated files.

### Gitignored + Tracked (should be untracked)
The following patterns in `.gitignore` need `git rm --cached` to take effect:
- `eloratings_cache.json`, `elo_update_log.json`, `catboost_cache.json`
- `form_cache.json`, `lineup_cache.json`, `odds_cache.json`
- `elo_applied.json`, `prediction_history.json`, `predictions_ledger.json`
- `probability_log.json`, `eval_backtest_report.json`, `eval_baseline_report.json`
- `calibration_params.json`, `versions.json`

---

## 7. Configuration Audit

| File | Contents | Status |
|------|----------|--------|
| `worldcup_predictor/config.json` | `{"league_id": 27}` | ✅ Minimal, functional |
| `worldcup_predictor/.env.example` | BSD_API_KEY template | ✅ Present |
| `worldcup_predictor/requirements.txt` | Dependencies listed | ✅ Present |
| `worldcup_predictor/.gitignore` | 51 lines (comprehensive) | ⚠️ Gitignore patterns don't apply to already-tracked files |
| Root `.gitignore` | 11 lines (generic Python) | ✅ Adequate |

### Dependency List (from `requirements.txt` expected)
- `requests` — HTTP client for BSD API
- `catboost` — ML model library
- `numpy` — Numerical computations
- `pytest`, `pytest-mock` — Testing
- `coverage` — Code coverage
- `pyyaml` — (expected from codebase map)

---

## 8. Git Hygiene

### Branch State
- **Branch:** `main`
- **Ahead of origin/main:** 2 commits
- **Last commit:** `60414bc` — "fix: handle live API string-based event.home_team (not dict)" — 2026-06-22

### Recent Commit History (last 50 commits summary)
- **Phase 20** (3 commits): Coverage seal, probability log, signal table + focus card
- **Phase 19** (5 commits): Multi-league framework (`--league`, `--list-leagues`, migration)
- **Phase 18** (3 commits): xG extraction, AI preview, CLI wiring
- **Phase 17b** (4+ commits): Signal pipeline repair
- **Phase 17** (3 commits): Enriched match context (stats extraction, context)
- **Phase 16** (13 commits): Model governance (version tracking, drift detection, backtesting)
- **Earlier phases** (1-15): Elo foundation, Monte Carlo, API, console output, 48-team dataset, group simulation, knockout, integration tests, data integrity, draw handling, evaluation, signal ingestion, blending, retention, context signals
- **Cleanup commits** (6): `AGENTS.md` removal, `.planning/` removal from tracking, `docs/` and `SOTs/` removal, gitignore hygiene

### Unstaged Changes
- **8 modified files** — all are generated data files listed in gitignore but still tracked
- **1 untracked file** — `.coverage` (rightfully untracked)
- **0 staged changes**

### Gitignore Issue
The `.gitignore` in `worldcup_predictor/` lists patterns for generated data files, but these files were tracked before the patterns were added. Gitignore only prevents **untracked** files from being added — it does not stop tracking of already-tracked files. To actually stop tracking them, one would need:

```
git rm --cached worldcup_predictor/data/prediction_history.json
# ... (repeat for all 14 generated files)
```

---

## 9. Architecture Snapshot

### Pipeline Flow
```
[BSD API] ──► fetcher.py ──► [Match Results]
                                      │
[eloratings.net] ──► elo_sync.py ──► [Elo Cache]
                                      │
                                      ▼
                                 state.py ──► [JSON Store]
                                      │
                  ┌───────────────────┼────────────────────┐
                  ▼                   ▼                    ▼
           groups.py            knockout.py          blender.py
      (group stage sim)    (knockout bracket sim)  (signal fusion)
                  │                   │                    │
                  │                   │      ┌─────────────┼─────────────┐
                  │                   │      ▼             ▼             ▼
                  │                   │  odds.py    catboost.py    form.py
                  │                   │                                      │
                  │                   │  lineup.py ──────────────────────────┘
                  ▼                   ▼                    ▼
         evaluation.py ◄──── prediction_history.json ◄─────┘
                  │
                  ▼
             output.py ──► [Console: colored tables, deltas, standings]
```

### Key Design Decisions
1. **50K Monte Carlo iterations** — configurable, benchmarked at ~12.66s for full tournament
2. **Multi-signal blending** — 5 signals (odds, Elo, CatBoost, form, lineup) weighted and combined
3. **BSD API polling** — 60s interval, auto-detect new matches, auto-re-simulate
4. **Elo auto-sync** — 24h periodic sync from eloratings.net, with 36h wake catch-up
5. **Model governance** — Version tracking (semver), drift detection, backtesting framework
6. **Multi-league** — `--league` flag, league_id parameterization, currently live on league 27 (World Cup)
7. **H2H tiebreaker** — 7-step head-to-head tiebreaker for group standings
8. **Annex C routing** — FIFA's official 3rd-place qualification logic for R32

### Current Configuration
- **League ID:** 27 (World Cup)
- **Live data directory:** `data/27/`
- **Run data:** ~40 run snapshots in `data/27/runs/`
- **Tests:** 601 passed / 1 skipped

---

## 10. Questions for the Team

1. **Gitignore enforcement:** Should we `git rm --cached` the 14 generated data files listed in `.gitignore` (lines 28–45) so the ignore patterns actually take effect? There are currently 8 modified files with +4219 lines of unstaged changes that are noise in every `git status`.

2. **Stub projects:** What is the timeline for `euro_predictor/` and `ucl_predictor/`? Should they remain as empty placeholders, be removed from the repo, or get their own `.planning/` skeletons?

3. **Merge status:** The branch is ahead of `origin/main` by 2 commits. Are these pending a PR review, or ready to push?

4. **Coverage target:** `.coverage` is present (untracked). Is there a coverage threshold goal (e.g., 80%+)? Current state: ~5300 LOC Python, 601 tests.

5. **Post-v2.0 roadmap:** STATE.md shows 20/20 phases at 100% for v2.0. Is v2.0 considered "shipped and done," or are there unplanned v2.x phases? What is the next milestone?

6. **Benchmark results:** `benchmarks/BENCHMARK_RESULTS_08.md` exists (gitignored). Are benchmarks run regularly? Is there a regression alert mechanism?

7. **BSD API key management:** The live smoke test is skipped without `BSD_API_KEY`. Is there a CI pipeline or is this purely local? Should we add a CI config (GitHub Actions, etc.)?
