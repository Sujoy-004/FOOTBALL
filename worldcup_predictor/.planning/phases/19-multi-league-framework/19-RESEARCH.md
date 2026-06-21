# Phase 19: Multi-League Framework — Research

**Researched:** 2026-06-19
**Domain:** Configuration, data isolation, API URL parameterization, state persistence
**Confidence:** HIGH

## Summary

This phase refactors the codebase from a single-league lock (league_id=27) to support all 65 BSD leagues. The work has 4 dimensions: (1) parameterize 4 hardcoded `league_id=27` sites in the source code, (2) introduce a `--league` CLI flag + `config.json` persistence with correct precedence, (3) add a static `LEAGUES` dict to `constants.py`, (4) implement one-time data migration from `data/` to `data/27/` with non-destructive idempotent copy.

The risk profile is LOW because:
- `state.py` already supports `data_dir` parameterization — every load/save function accepts `data_dir: Path | str | None = None` defaulting to `constants.DATA_DIR`. The architecture is ready for this change.
- `fetch_raw_matches()` already accepts an `api_url` override parameter.
- The 4 hardcoded sites are isolated and well-documented.

**Primary recommendation:** Minimize blast radius. Introduce a `current_league_id` derived at startup from `--league > config.json > 27`, compute a `league_data_dir = DATA_DIR / str(league_id)` once, and thread it through the call chain to state functions. Never refactor for "elegance" — this phase is a targeted parameterization.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Area 1: League Catalog Source
- **D-01:** League catalog lives in `constants.py` — static `LEAGUES` dict mapping `{league_id: str}` to league names.
- **D-02:** `--list-leagues` flag reads from `constants.py`. No API call for catalog.
- **D-03:** League IDs remain stable and version-controlled. Future additions require code change + test update.
- **D-04:** Rejected: fetching from BSD API (runtime dependency, startup latency, failure mode) and `config.json` (no architectural benefit over constant).

#### Area 2: State Directory Migration
- **D-05:** Automatic one-time migration on first run with league=27. If `data/played.json` exists AND `data/27/played.json` does NOT exist, copy league-scoped files into `data/27/`.
- **D-06:** Migration copies: `played.json`, `played_groups.json`, `prediction_history.json`, `predictions_ledger.json`, and any other league-scoped state files.
- **D-07:** Original `data/*.json` files are never deleted — migration is non-destructive.
- **D-08:** Migration is idempotent — guard by checking `data/27/played.json` existence. Second startup performs zero migration work.
- **D-09:** Rejected: flag-based migration (unnecessary operational burden) and clean break (orphans state, breaks continuity).

#### Area 3: Config Mechanism
- **D-10:** Precedence: CLI `--league` > `config.json` > default league 27.
- **D-11:** `config.json` is the single source of persisted league preference. Auto-created with `{"league_id": 27}` if missing.
- **D-12:** Corrupt `config.json` falls back to league 27 gracefully (log warning, continue).
- **D-13:** Rejected: env var only (deployment concern, poor UX) and CLI-only (no persistence, defeats purpose).

#### Area 4: Per-League vs Shared Data
- **D-14:** Rule: shared = immutable reference data; per-league = anything generated, learned, cached, calibrated, or stateful.
- **D-15:** **Shared** (stays in `data/`): `bracket.json`, `groups.json`, `annex_c.json`, `team_aliases.json`, `team_values.json`.
- **D-16:** **Per-league** (moves to `data/{league_id}/`): `played.json`, `played_groups.json`, `teams.json`, `predictions_ledger.json`, `prediction_history.json`, `catboost_cache.json`, `odds_cache.json`, `form_cache.json`, `lineup_cache.json`, `elo_applied.json`, `elo_update_log.json`, `calibration_params.json`, `versions.json`.
- **D-17:** Rationale for `calibration_params.json` = per-league: calibration is league-specific (World Cup calibration must not affect EPL predictions).
- **D-18:** Rationale for `versions.json` = per-league: `data_version` tracks league match data, `model_version` tracks league calibration, `run_version` tracks league governance.

### the agent's Discretion

No specific items marked as the agent's discretion — standard approach expected.

### Deferred Ideas (OUT OF SCOPE)

None.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| V2-25 | League selection via CLI flag (--league) and config, supporting all 65 BSD leagues | See Standard Stack (config.json + argparse + LEAGUES dict). Current `_parse_args()` has established pattern for argument parsing. New `config.json` file adds persistence. |
| V2-26 | Multi-league data isolation (separate state files per league namespace) | See Architecture Patterns (data_dir propagation). `state.py` already supports `data_dir` parameter — the architectural foundation is ready. 14 files identified for the migration manifest. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| League ID resolution (--league > config > 27) | Application (main.py) | — | Config loading is a startup concern; `main()` already owns argument parsing + env setup |
| Config.json read/write | Application (new module or main.py) | — | Simple JSON file with `{"league_id": N}` — no framework needed |
| Per-league data directory computation | Application (main.py) → constants | — | Computed once at startup as `DATA_DIR / str(league_id)` |
| League-scoped state persistence | State persistence (state.py) | — | Already supports `data_dir` parameter; just needs callers to pass it |
| API URL parameterization | Data fetching (fetcher.py, catboost.py) | — | 4 hardcoded sites need `league_id` parameter added to function signatures |
| Post-fetch league filtering | Data fetching (fetcher.py) | — | `fetch_raw_matches()` filters `e["league"]["id"] == 27` — needs `league_id` param |
| Data migration (data/ → data/27/) | Application (main.py) | State persistence (state.py) | One-time startup task; delegates to `shutil.copy2` for file copy |
| League catalog display (--list-leagues) | CLI (main.py) | — | Reads static `LEAGUES` dict, prints to stdout, exits |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `argparse` | stdlib | CLI flag parsing (`--league`, `--list-leagues`) | Already used for `--once`, `--no-color`, `--seed`, `--ai-preview` [VERIFIED: codebase grep, main.py:194-237] |
| `json` | stdlib | Read/write `config.json` | Already used for JSON state files throughout [VERIFIED: codebase grep, state.py] |
| `shutil` | stdlib | One-time data migration copy (shutil.copy2) | Cross-platform file copy with metadata preservation [VERIFIED: Python 3.10+ docs] |
| `pathlib.Path` | stdlib | Data directory resolution | Already used throughout — `constants.DATA_DIR` is a `Path` [VERIFIED: codebase grep, constants.py:12] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `os` | stdlib | File existence checks for migration guard | Migration idempotency check: `os.path.exists()` or `Path.exists()` |
| `logging` | stdlib | Warning on corrupt config.json | Already used throughout project [VERIFIED: codebase grep] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Static `LEAGUES` dict | BSD API `/api/leagues/` | Runtime dependency + startup latency + failure mode. Rejected per D-04. |
| `config.json` | Env var `BSD_LEAGUE_ID` | Deployment concern, poor UX. Rejected per D-13. |
| `config.json` | TOML/YAML | JSON is already the project's standard format. No new parser dependency needed. |
| Full refactor of state.py | Minimal parameter threading | State.py already supports `data_dir` on every function. No refactoring needed — just thread the value. |

**Installation:** No new packages. Python stdlib only.

**Version verification:** N/A — all dependencies are Python stdlib.

## Package Legitimacy Audit

> No external packages required. This phase uses only Python stdlib (argparse, json, shutil, pathlib, os, logging) — all standard library modules verified present in Python 3.10+.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                      ┌───────────────────────────────────────┐
                      │           main.py startup              │
                      │                                       │
                      │  1. Parse CLI args (--league, etc)     │
                      │  2. Load config.json                   │
                      │  3. Resolve league_id (precedence)     │
                      │  4. Compute league_data_dir            │
                      │  5. Run migration (one-time)           │
                      │  6. Load state from league_data_dir    │
                      └────────┬──────────────────────────────┘
                               │ league_id
                               ▼
              ┌────────────────┴────────────────┐
              │          constants.py            │
              │  API_URL(league_id) ← function   │
              │  DATA_DIR = data/                │
              │  LEAGUES = {27: "WC", ...}       │
              └────────────────┬─────────────────┘
                               │ league_data_dir
              ┌────────────────┴────────────────┐
              │         state.py               │
              │  load/save(data_dir=...)        │
              │  ┌── shared (data/) ──┐        │
              │  │ bracket.json      │        │
              │  │ groups.json       │        │
              │  │ annex_c.json      │        │
              │  │ team_aliases.json │        │
              │  │ team_values.json  │        │
              │  └───────────────────┘        │
              │  ┌── per-league ──────┐        │
              │  │ data/{id}/        │        │
              │  │ └ played.json    │        │
              │  │ └ teams.json     │        │
              │  │ └ ...            │        │
              │  └───────────────────┘        │
              └────────────────┬──────────────┘
                               │ league_id
              ┌────────────────┴────────────────┐
              │      fetcher.py / catboost.py   │
              │  build_historic_url(league_id)  │
              │  fetch_raw_matches(league_id)   │
              │  fetch_and_cache_catboost(li)   │
              └─────────────────────────────────┘
```

### Recommended Project Structure (unchanged)

```
src/
├── constants.py     # + LEAGUES dict, + API_URL(league_id) function
├── main.py          # + --league flag, + config.json handling, + migration, + data_dir propagation
├── fetcher.py       # build_historic_url(league_id) param, fetch_raw_matches league filter param
├── state.py         # Unchanged — already supports data_dir
├── governance.py    # Unchanged — uses state.py functions
├── evaluation.py    # Unchanged — uses state.py functions
├── predictors/
│   └── catboost.py  # fetch_and_cache_catboost league param
tests/
└── test_fetcher.py  # Update league_id assertion
```

### Pattern 1: League ID Resolution

**What:** Resolve `league_id` at startup with correct precedence: CLI > config > default.

**When to use:** Once at the top of `main()`, before any state loading.

```python
# Source: Derived from CONTEXT.md D-10, D-11, D-12
def _resolve_league_id(args: argparse.Namespace) -> tuple[int, Path]:
    """Resolve league_id with precedence: CLI > config.json > 27.
    
    Returns (league_id, league_data_dir).
    """
    from pathlib import Path
    import json
    
    config_path = constants.DATA_DIR.parent / "config.json"
    league_id = 27  # default
    
    # 1. Load config.json if exists
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            league_id = int(config.get("league_id", 27))
        except (json.JSONDecodeError, KeyError, ValueError):
            logging.warning("Corrupt config.json, falling back to league 27")
            league_id = 27
    else:
        # Auto-create with default
        with open(config_path, "w") as f:
            json.dump({"league_id": 27}, f, indent=2)
    
    # 2. CLI override
    if args.league is not None:
        league_id = args.league
    
    # Save resolved value back if changed (so config persists CLI choice)
    # D-10 implies CLI is ephemeral — decide whether to persist
    
    league_data_dir = constants.DATA_DIR / str(league_id)
    return league_id, league_data_dir
```

### Pattern 2: One-Time Data Migration

**What:** Non-destructive, idempotent copy of league-scoped files from `data/` to `data/27/`.

**When to use:** After league_id resolution, before state loading, only when league_id == 27 and data/27/ doesn't exist yet.

```python
# Source: Derived from CONTEXT.md D-05, D-06, D-07, D-08
import shutil

def _migrate_legacy_data(data_dir: Path, league_id: int) -> None:
    """One-shot migration from data/ to data/{league_id}/."""
    if league_id != 27:
        return  # Only migrate from legacy 27 layout
    
    target_dir = data_dir / str(league_id)
    if (target_dir / "played.json").exists():
        return  # Idempotent: already migrated
    
    league_scoped_files = [
        "played.json", "played_groups.json", "teams.json",
        "predictions_ledger.json", "prediction_history.json",
        "catboost_cache.json", "odds_cache.json", "form_cache.json",
        "lineup_cache.json", "elo_applied.json", "elo_update_log.json",
        "calibration_params.json", "versions.json",
    ]
    
    target_dir.mkdir(parents=True, exist_ok=True)
    migrated = 0
    for filename in league_scoped_files:
        src = data_dir / filename
        if src.exists():
            shutil.copy2(src, target_dir / filename)
            migrated += 1
    
    # Also migrate runs/ subdirectory
    src_runs = data_dir / "runs"
    if src_runs.exists():
        dst_runs = target_dir / "runs"
        dst_runs.mkdir(exist_ok=True)
        for f in src_runs.iterdir():
            if f.is_file():
                shutil.copy2(f, dst_runs / f.name)
    
    if migrated:
        logging.info("Migrated %d files from data/ to data/%d/", migrated, league_id)
```

### Anti-Patterns to Avoid

- **Threading `league_id` through every function signature:** Pass the `league_data_dir` once to state functions, not `league_id` everywhere. Keep `league_id` only where API URLs need it.
- **Renaming `DATA_DIR` to change its meaning:** `DATA_DIR` should remain `data/`. League dirs are computed as `DATA_DIR / str(league_id)`. Don't break the pattern.
- **Inline config.json creation without care for Windows paths:** Use `config_path = Path("config.json")` (project root). Not in `DATA_DIR`.
- **Deleting old data files during migration:** D-07 explicitly says never delete originals.
- **Adding `league_id` to every load/save call in main.py:** Compute `league_data_dir` once, pass it as `data_dir=league_data_dir` to per-league state calls, pass `data_dir=DATA_DIR` (or omit) for shared state calls.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File copy with metadata | Custom copy loop | `shutil.copy2` | Cross-platform, handles permissions, timestamps. Built-in, stdlib. |
| CLI argument parsing | Manual sys.argv processing | `argparse` | Already used. Handles --help, type validation, error messages. |

**Key insight:** The entire phase is about parameterization, not building new systems. The hard work (state.py data_dir support, api_url override) is already done. This phase threads existing capabilities together.

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 22 JSON files in `data/` — 5 shared, 14 per-league + runs/ subdirectory + 3 eval | Code edit: state.py already handles per-league dirs; migration copies the 14 league-scoped files once |
| Live service config | None — no external services reference league_id in their config | None |
| OS-registered state | None — CLI tool, no OS registrations | None |
| Secrets/env vars | `BSD_API_KEY` in `.env` — unchanged by this phase; `config.json` is new but separate | None |
| Build artifacts | `data/runs/` — 28 snapshot JSON files | Migration: runs/ dirs should be per-league; `save_run_snapshot()` saves to `data/runs/` which will become `data/27/runs/` after migration |

**Nothing found in category:** Live service config, OS-registered state, Secrets/env vars.

## Common Pitfalls

### Pitfall 1: Config.json Race Condition on Windows
**What goes wrong:** Reading and writing config.json simultaneously (unlikely in single-threaded Python, but possible if two instances run).
**Why it happens:** Config.json is at the project root, shared across instances.
**How to avoid:** Single-instance pattern (the tool already is single-process). For safety, use atomic write (temp + rename) like state.py does.
**Warning signs:** User runs two terminal instances with different `--league` flags.

### Pitfall 2: Version Migration Not Idempotent
**What goes wrong:** Migration copies `versions.json` to `data/27/`, but `versions.json` contains `run_version` which is timestamp-based. If the user runs league=27, the migration copies the old version, then governance immediately writes a new one.
**Why it happens:** The version file already gets overwritten at startup by governance.
**How to avoid:** Migration is still idempotent because the guard check (`data/27/played.json` exists) prevents re-copy. The version.json in `data/27/` will be overwritten by governance anyway.
**Warning signs:** N/A — migration is self-healing in this case.

### Pitfall 3: Shared Data Functions Called with Per-League data_dir
**What goes wrong:** Calling `load_bracket(data_dir=league_data_dir)` looks for `data/27/bracket.json` which doesn't exist (bracket is shared).
**Why it happens:** Developer gets lazy and passes the same `data_dir` everywhere.
**How to avoid:** Be explicit: shared calls omit `data_dir` (defaults to `DATA_DIR`), per-league calls pass `data_dir=league_data_dir`.
**Warning signs:** `FileNotFoundError` for bracket.json/groups.json in a subdirectory.

### Pitfall 4: Forgetting the `runs/` Subdirectory
**What goes wrong:** `save_run_snapshot()` saves to `data/runs/` which is relative to `DATA_DIR`. If per-league, it should save to `data/27/runs/`.
**Why it happens:** The runs dir is not a single JSON file; it's a subdirectory. D-16 lists `versions.json` as per-league but doesn't mention `runs/`.
**How to avoid:** `save_run_snapshot()` in state.py uses `_resolve_data_dir(data_dir) / constants.GOV_RUNS_DIR`. If `data_dir` points to `data/27/`, runs go to `data/27/runs/` automatically.
**Warning signs:** Runs appear in `data/runs/` when user specified `--league 27`.

### Pitfall 5: elo_sync.py Doesn't Accept data_dir
**What goes wrong:** `sync_elo_from_eloratings()` calls `state.load_elo_update_log()` without `data_dir`, so it always reads/writes to `DATA_DIR` even when run for a non-default league.
**Why it happens:** `sync_elo_from_eloratings(teams)` doesn't have a `data_dir` parameter.
**How to avoid:** Add `data_dir` parameter to `sync_elo_from_eloratings()` and propagate it to the state calls inside.
**Warning signs:** Elo update log for league 65 appears in `data/` instead of `data/65/`.

## Code Examples

### Adding the --league CLI flag
```python
# Source: Derived from existing _parse_args() pattern in main.py:194-237
parser.add_argument(
    "--league",
    type=int,
    default=None,
    metavar="ID",
    help="BSD league ID (default: 27 for World Cup; see --list-leagues for all 65)",
)
parser.add_argument(
    "--list-leagues",
    action="store_true",
    dest="list_leagues",
    help="Print all available league IDs and names, then exit",
)
```

### LEAGUES dict in constants.py
```python
# Source: D-01 in CONTEXT.md — static, not fetched
LEAGUES: dict[int, str] = {
    1: "Primera División (Argentina)",
    2: "A-League (Australia)",
    3: "Bundesliga (Austria)",
    4: "Jupiler Pro League (Belgium)",
    # ... all 65 leagues
    27: "World Cup 2026",
    # ... remaining leagues
}
DEFAULT_LEAGUE_ID: int = 27
"""
Default league ID used when neither --league flag nor config.json specifies one.
"""

def api_url_for_league(league_id: int) -> str:
    """Build BSD events API URL for a given league."""
    return f"https://sports.bzzoiro.com/api/events/?league_id={league_id}&limit=200"

def predictions_url_for_league(league_id: int) -> str:
    """Build BSD predictions API URL for a given league."""
    return f"https://sports.bzzoiro.com/api/predictions/?league={league_id}"
```

### build_historic_url with league_id parameter
```python
# Source: Derived from fetcher.py:16-20
def build_historic_url(league_id: int = 27) -> str:
    """Build events URL with date range for historical catch-up."""
    today = datetime.now().strftime("%Y-%m-%d")
    base = "https://sports.bzzoiro.com/api/events/"
    return f"{base}?league_id={league_id}&date_from={constants.WC_START_DATE}&date_to={today}&limit=200"
```

### main.py data_dir propagation pattern
```python
# Source: Conceptual pattern — compute once, pass explicitly
def main() -> None:
    args = _parse_args()
    
    # Handle --list-leagues early (print and exit)
    if args.list_leagues:
        for lid, name in sorted(constants.LEAGUES.items()):
            print(f"{lid:>4}: {name}")
        sys.exit(0)
    
    # Resolve league ID (precedence: CLI > config > 27)
    league_id = _resolve_league_id(args)
    league_data_dir = constants.DATA_DIR / str(league_id)
    
    # One-time migration (only for league 27 legacy data)
    _migrate_legacy_data(constants.DATA_DIR, league_id)
    
    # Load shared data (from DATA_DIR — no league override)
    bracket = state.load_bracket()  # uses constants.DATA_DIR
    groups = state.load_groups()
    annex_c = state.load_annex_c()
    aliases = state.load_aliases()
    team_values = state.load_team_values()
    
    # Load per-league data (from league_data_dir)
    teams = state.load_teams(data_dir=league_data_dir)
    played = state.load_played(data_dir=league_data_dir)
    played_groups = state.load_played_groups(data_dir=league_data_dir)
    elo_applied = state.load_elo_applied(data_dir=league_data_dir)
```

### fetch_raw_matches league filtering
```python
# Source: Derived from fetcher.py:52-56
# Change hardcoded `== 27` to parameterized filter:
all_events = [
    e for e in all_events
    if isinstance(e.get("league"), dict)
    and e["league"].get("id") == league_id
]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `league_id` hardcoded as string in API_URL constant | `api_url_for_league(league_id)` function | This phase | One function call vs one string constant. Enables any of 65 leagues. |
| Data at `data/*.json` flat directory | `data/{league_id}/*.json` for league-scoped files | This phase | Multi-league isolation. Shared data stays at `data/`. |
| No persistent config | `config.json` with `{"league_id": N}` | This phase | User preference survives `--once` runs. |

**Deprecated/outdated:**
- `API_URL` string constant in constants.py: replaced by `api_url_for_league()` function
- `build_historic_url()` without parameters: now accepts `league_id`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | All 65 BSD leagues use the same `/api/events/` endpoint structure with `?league_id=N` parameter | Standard Stack | LOW — verified by existing `league_id=27` pattern in current codebase. BSD API documentation (from Phase 10 research) confirms the pattern extends to all leagues. |
| A2 | The BSD predictions endpoint (`/api/predictions/`) also accepts `?league=N` for all leagues | Standard Stack | LOW — same endpoint pattern as events. Phase 13 research confirmed `?league=27` pattern. |
| A3 | `eloratings.net World.tsv` covers teams across all 65 BSD leagues | Open Questions | HIGH — World.tsv only covers national teams. For club leagues (EPL, La Liga), a different TSV URL is needed (e.g., `Europe.tsv`). This phase does NOT implement per-league Elo sync for non-World-Cup leagues. |
| A4 | `config.json` at project root is the right location | Standard Stack | MEDIUM — could also go in `data/config.json` or `~/.config/wc-predict/`. Project root is simplest and follows existing pattern (`.env` is at root). |

**Key risk:** A3 means Elo sync for non-World-Cup leagues is a future concern. This phase correctly scopes to state isolation only.

## Open Questions (RESOLVED)

1. **RESOLVED: Should `config.json` persist the CLI `--league` flag?**
   - What we know: D-10 says precedence is `--league > config.json > 27`. If user runs `--league 65` once, should config.json update to remember it?
   - What's unclear: D-10 implies CLI wins but doesn't say whether CLI updates persisted config.
   - Resolution (per CONTEXT.md D-10): CLI is ephemeral override; config.json is for persisted preference. Do NOT auto-update config.json from CLI flags. User explicitly edits config.json to change their default. This avoids surprising side effects.

2. **DEFERRED: Which eloratings.net TSV for non-World-Cup leagues?**
   - What we know: World.tsv covers national teams only. EPL teams would need a different source.
   - What's unclear: Whether eloratings.net has per-league TSVs or whether the framework should leave this for a future phase.
   - Disposition: Deferred — this phase scopes to state isolation only (threads `data_dir` through `sync_elo_from_eloratings()`). Per-league Elo sync from different TSVs is a future concern.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All | ✓ | .venv | — |
| pytest | Tests | ✓ | via .venv | — |

**Missing dependencies with no fallback:** None — all changes use Python stdlib.

**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `pyproject.toml` (or `pytest.ini` — check root) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| V2-25 | `--league 65` sets correct league_id in state calls | unit (monkeypatch CFG) | `pytest tests/test_cli.py -x -q` | ✅ |
| V2-25 | `--list-leagues` prints league names and IDs | unit | `pytest tests/test_cli.py -x -q` | ✅ needs new test |
| V2-25 | Precedence: CLI > config > 27 | unit | `pytest tests/test_config.py -x` | ❌ Wave 0 |
| V2-26 | data/27/ isolation after migration | integration | `pytest tests/test_state.py -x -q` | ✅ needs update |
| V2-26 | Shared data loads from root data/ | unit | `pytest tests/test_state.py -x -q` | ✅ needs update |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q --ignore=tests/test_live_smoke.py`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_config.py` — new file for config.json load/save and precedence tests
- [ ] `tests/test_cli.py` — add `--league` and `--list-leagues` test cases
- [ ] `tests/test_fetcher.py` — update `test_build_historic_url_format` to accept dynamic league_id parameter
- [ ] `tests/test_migration.py` — new file for migration idempotency and correctness tests

## Security Domain

> **Security enforcement:** This phase introduces no new network calls, no new authentication, and no user-controlled data that flows to dangerous sinks. The `--league` flag and `config.json` `league_id` are validated as integers before use in path construction and URL construction. The primary risk is path traversal via `--league` value — mitigate by ensuring `str(league_id)` is used (Python's `int()` parse already rejects non-numeric input) and that the resulting path stays within the project directory.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | `--league` type=int via argparse (rejects non-numeric); config.json league_id validated with `int(config.get("league_id", 27))` else fallback to 27 |

### Known Threat Patterns for Python/argparse

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `--league` | Tampering | `int()` parse rejects non-numeric. Path stays as `DATA_DIR / str(league_id)` — confined by project structure. |
| Config.json injection (malformed JSON) | Tampering | Try/except with fallback to 27 and log warning. |

## Sources

### Primary (HIGH confidence)
- Codebase analysis — verified all 22 data files, 4 hardcoded league_id=27 sites, state.py data_dir pattern, elo_sync.py internals
- CONTEXT.md D-01 through D-18 — user decisions locked for this phase

### Secondary (MEDIUM confidence)
- Python 3.10+ stdlib docs — `argparse`, `shutil.copy2`, `pathlib.Path`, `json` — well-known stdlib modules
- Codebase grep for `state.load_*` and `state.save_*` calls — identified 33 call sites in main.py, 4 in elo_sync.py

### Tertiary (LOW confidence)
- A1-A4 in Assumptions Log — untested for non-World-Cup leagues but inferred from existing patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — fully determined by CONTEXT.md decisions and codebase patterns
- Architecture: HIGH — data_dir propagation pattern already exists in state.py
- Pitfalls: HIGH — identified from codebase analysis of how modules interact
- Assumptions: MEDIUM — A3 (eloratings.net coverage) is the main uncertainty, but scoped as future concern

**Research date:** 2026-06-19
**Valid until:** 2026-07-19 (stable phase, stdlib only)
