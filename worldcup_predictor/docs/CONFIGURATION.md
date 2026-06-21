<!-- generated-by: gsd-doc-writer -->
# Configuration

World Cup Dynamic Prediction CLI tool configuration reference.

---

## Environment Variables

- **`BSD_API_KEY`** (Required) — Token for sports.bzzoiro.com API
  - Set in `.env` file
  - Get free key at `https://sports.bzzoiro.com/register/`

- **`POLL_INTERVAL`** (Optional) — Seconds between API fetch cycles
  - Default: `60`

**Setup:**
```bash
cp .env.example .env
# Edit .env: add your BSD API key
```

---

## CLI Arguments

Parsed in `main.py` `_parse_args()`:

```
wc-predict [--once] [--no-color] [--seed N]
```

**Available Flags:**
- `--once`: Single fetch→simulate→print cycle, then exit
- `--no-color`: Disable ANSI color output
- `--seed N`: Random seed for reproducible simulation

---

## Constants

Defined in `src/constants.py`:

### Tournament Structure

```
WC_START_DATE = "2026-06-11"
GROUP_COUNT   = 12
TEAMS_PER_GROUP = 4
MATCHES_PER_GROUP = 6
```

### Elo Engine

```
K_FACTOR       = 60   — K-factor for World Cup finals
DEFAULT_ELO    = 1500 — starting rating for new teams
ELO_DRIFT_TOLERANCE  = 10 — drift below this is ignored
ELO_BLEND_THRESHOLD  = 30 — drift above this → overwrite+flag
ELO_BLEND_FACTOR     = 0.5
```

### Elo Sync

```
ELORATINGS_TSV_URL       = https://www.eloratings.net/World.tsv
ELO_SYNC_INTERVAL_HOURS  = 24
ELO_SYNC_CATCHUP_HOURS    = 36
ELO_SYNC_RETRY_BACKOFFS  = (1.0, 2.0, 4.0)
ELO_STALENESS_WARN_HOURS = (24, 48, 72, 168)
```

### API (Events)

```
API_URL      = https://sports.bzzoiro.com/api/events/?league_id=27&limit=200
API_TIMEOUT  = 10
```

## BSD Predictions API

```
PREDICTIONS_API_URL = https://sports.bzzoiro.com/api/predictions/?league=27
```

**Note:** Hardcoded in `src/predictors/catboost.py:235` (not in `src/constants.py`). Used to fetch CatBoost ML probabilities with confidence scores. 3-attempt exponential backoff (1s, 2s, 4s). On failure returns empty matches dict (graceful degradation).

## Team Codes

`ELORATINGS_TEAM_CODES` — 48 entries mapping 2-letter codes (e.g. `"AR" → "Argentina"`) to canonical team names.

### Signal Ingestion (Phase 13)

```
ODDS_CACHE_TTL_HOURS              = 12    — Cache TTL for market odds
CATBOOST_CACHE_TTL_HOURS          = 24    — Cache TTL for CatBoost predictions
ODDS_CACHE_FILE                   = "odds_cache.json"   — Market odds cache filename
CATBOOST_CACHE_FILE               = "catboost_cache.json" — CatBoost cache filename
PREDICTION_HISTORY_SCHEMA_VERSION = 2     — Schema version for prediction_history.json
```

### Signal Evaluation

`evaluate_all_matches()` in `src/evaluation.py` accepts a `signal_name` parameter:

- **`None` (default)**: Multi-signal report — evaluates all available signal keys in `prediction_history.json` compound entries
- **`"elo"`**: Replay through Elo pipeline, produce compound entries
- **`"market_odds"`**: Read market odds probabilities from compound entries
- **`"catboost"`**: Read CatBoost ML probabilities from compound entries

Returns Brier score, log loss, accuracy, and calibration ECE per signal. Requires `prediction_history.json` at schema v2. Migration from v1 is automatic via `migrate_prediction_history_v1()` in `src/state.py`.

---

## Requirements

Declared in `requirements.txt`:

- **`python-dotenv`** (≥1.0) — Runtime (`.env` loader)
- **`pytest`** (≥9.0) — Dev
- **`pytest-cov`** (≥7.1) — Dev

**Note:** `requests` is a transitive dependency (pulled via `python-dotenv` or pip's dependency resolver) — not declared directly in `requirements.txt`.

**Install:**
```bash
pip install -r requirements.txt
```

---

## Data Files

All files in `data/` — auto-created and updated at runtime:

```
data/
├── teams.json
├── bracket.json
├── groups.json
├── annex_c.json
├── played.json
├── played_groups.json
├── eloratings_cache.json
├── elo_update_log.json
├── elo_applied.json
├── prediction_history.json
├── team_aliases.json
├── eval_baseline.json
├── eval_baseline_report.json
├── odds_cache.json              — Market odds cache (Phase 13, TTL=12h)
└── catboost_cache.json          — CatBoost ML cache (Phase 13, TTL=24h)
```
