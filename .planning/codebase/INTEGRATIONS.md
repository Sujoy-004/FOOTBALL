# External Integrations

**Analysis Date:** 2026-06-27

## APIs & External Services

### Bzzoiro Sports Data (BSD) API

**Purpose:** Primary live match data source for all competitions. Provides match events, predictions, odds, and league metadata.

**Endpoints:**
| Endpoint | Usage | Location |
|----------|-------|----------|
| `GET /api/events/?league_id={id}&limit=200` | Fetch live and historical match events (scores, status, team names, odds, stats) | `competitions/worldcup/src/constants.py:39`, `football_core/fetcher.py:15` |
| `GET /api/events/?league_id={id}&date_from={start}&date_to={today}&limit=200` | Historical catch-up from tournament start | `competitions/worldcup/src/fetcher.py:23` |
| `GET /api/predictions/?league={id}` | CatBoost ML predictions (home/draw/away probabilities, xG, model version, confidence) | `football_core/predictors/catboost.py:22` |
| `GET /api/leagues/` | API key validation and league listing | `competitions/worldcup/main.py:1176` |

**SDK/Client:**
- Custom HTTP client via `requests` library. No official BSD SDK exists.
- Fetch implementation: `football_core/fetcher.py:15-74` — 3-retry with exponential backoff (1s/2s/4s), pagination support via `next` URL, league_id filtering.
- Timeout: 10 seconds (`football_core/constants.py:11`).

**Auth:**
- Token-based: `Authorization: Token {BSD_API_KEY}`
- Key sourced from `BSD_API_KEY` environment variable.
- Validated at startup via `validate_api_key()` (`competitions/worldcup/main.py:1160-1188`).
- HTTP 401 detected and surfaces clear error message.

**Rate Limiting:**
- Self-imposed: minimum 60-second interval between API calls (`POLL_INTERVAL`).
- On failure: 3 retries with backoff, then graceful degradation (uses cached data).

**Data consumed from BSD API response fields:**
- Match results: `status`, `home_team`, `away_team`, `home_score`, `away_score`, `winner`, `event_date`
- Group stage info: `group_name`, `round_number`
- Market odds: `odds_home`, `odds_draw`, `odds_away` — extracted via `football_core/predictors/odds.py`, vig-removed via `remove_vig()`
- CatBoost predictions: via `/api/predictions/` endpoint, parsed in `football_core/predictors/catboost.py`
- Match enrichment: `live_stats` (cards, shots, possession), `venue`, `referee`, `home_coach`, `away_coach` via `competitions/worldcup/src/enrichment.py`
- AI previews: `ai_preview.text` field from events endpoint
- League ID filtering: BSD events include a `league` dict with `id` field — results are filtered server-side by query param and client-side by `football_core/fetcher.py:42-46`

### eloratings.net

**Purpose:** External Elo rating source for periodic cross-validation and correction of the internal Elo ratings.

**Endpoints:**
| Endpoint | Usage | Location |
|----------|-------|----------|
| `https://www.eloratings.net/World.tsv` | World Cup 2026 team Elo ratings (TSV format) | `football_core/constants.py:19` |
| `https://www.eloratings.net/Europe.tsv` | Euro 2024 team Elo ratings | `competitions/euro/main.py:62` |

**SDK/Client:**
- Custom HTTP via `requests` library. No SDK.
- TSV parsing using `csv.reader` with tab delimiter (`football_core/elo_sync.py:55-56`).
- Data structure: rows with columns `[rank, team_name, code, rating, ...]`. Code (col 2) and rating (col 3) extracted.

**Auth:**
- None. Public TSV endpoint.

**Rate Limiting:**
- 3 retries with exponential backoff (1s/2s/4s), 15-second timeout per attempt (`football_core/constants.py:13-14`).
- Sync frequency: every 24 hours (`ELO_SYNC_INTERVAL_HOURS`).
- Catch-up window: 36 hours — if last sync is older, syncs immediately on next cycle.

**Data Flow:**
1. TSV fetched → parsed → validated (min 48 teams, rating range [1000, 2500]).
2. Team codes mapped to canonical project names via `ELORATINGS_TEAM_CODES` dict (`competitions/worldcup/src/constants.py:82-131`).
3. Graduated correction applied:
   - Drift <= 10: ignored (tolerance threshold)
   - Drift 11-30: 50% blend toward eloratings value
   - Drift > 30: full overwrite (triggers drift flag alert)
4. Corrections persisted in `elo_update_log.json` and applied to in-memory teams dict.

## Data Storage

**Databases:**
- None. All state stored as JSON files on the local filesystem.

**File Storage:**
- Local filesystem only. No cloud storage (S3, GCS, etc.).
- Base directory: `competitions/worldcup/data/` (configured in `competitions/worldcup/src/constants.py:44`).
- Per-league subdirectories: `data/<league_id>/` (e.g., `data/27/` for World Cup 2026).

**JSON State Files:**

| File | Purpose | Load/Save Location |
|------|---------|-------------------|
| `teams.json` | Team names + current Elo ratings | `football_core/state.py:39-47` |
| `groups.json` | Group definitions (teams, match schedule) | `competitions/worldcup/src/state.py:165-173` |
| `bracket.json` | Knockout bracket structure with DAG dependencies | `football_core/state.py:193-198` |
| `annex_c.json` | Third-place advancement lookup (495 entries, C(12,8)) | `competitions/worldcup/src/state.py:228-233` |
| `team_aliases.json` | API name → canonical name mapping | `competitions/worldcup/src/state.py:47-50` |
| `team_values.json` | Squad market values (EUR) for lineup strength signal | `competitions/worldcup/src/state.py:53-59` |
| `played.json` | Completed knockout matches | `football_core/state.py:50-57` |
| `played_groups.json` | Completed group matches | `football_core/state.py:61-71` |
| `prediction_history.json` | Compound prediction history with per-signal data (schema v2) | `football_core/state.py:74-95` |
| `predictions_ledger.json` | Permanent ledger of all fetched predictions (never pruned) | `competitions/worldcup/src/state.py:285-310` |
| `odds_cache.json` | Market odds cache (12h TTL) | `football_core/state.py:124-134` |
| `catboost_cache.json` | CatBoost prediction cache (24h TTL) | `football_core/state.py:124-134` |
| `form_cache.json` | Form signal cache (computed locally) | `football_core/state.py:124-134` |
| `lineup_cache.json` | Lineup strength cache (computed locally) | `football_core/state.py:124-134` |
| `eloratings_cache.json` | Last fetched eloratings values (for offline fallback) | `football_core/state.py:98-108` |
| `elo_applied.json` | Set of match IDs already processed for Elo | `competitions/worldcup/src/state.py:67-78` |
| `elo_update_log.json` | Chronological log of all Elo corrections | `football_core/state.py:111-121` |
| `eval_baseline_report.json` | Startup evaluation metrics snapshot | `competitions/worldcup/src/state.py:315-320` |
| `eval_backtest_report.json` | Historical backtest results | `competitions/worldcup/src/state.py:382-384` |
| `calibration_params.json` | Fitted Platt scaling parameters per signal | `competitions/worldcup/src/state.py:323-333` |
| `versions.json` | Data/model/run version tracking | `competitions/worldcup/src/state.py:338-355` |
| `probability_log.json` | Rolling snapshot of all probability outputs | `football_core/state.py:201-213` |
| `config.json` | League ID configuration | `competitions/worldcup/main.py:1320-1356` |

**Persistence pattern:** Atomic writes via `tempfile.mkstemp` + `os.replace` (`football_core/state.py:17-36`).

**Caching:**
- No Redis, Memcached, or external cache. Cache is TTL-based JSON files with `is_cache_valid()` checking `expires_at` timestamps.
- Cache TTLs: odds=12h, CatBoost=24h, Elo sync=24h.
- Form and lineup strength signals computed locally (no API calls), cached to JSON.

## Authentication & Identity

**Auth Provider:**
- Custom API token for BSD Sports Data. No OAuth, no SSO, no user accounts.
- Token stored in `BSD_API_KEY` environment variable, loaded via `python-dotenv` from `.env` file.
- Validation: HTTP GET to `/api/leagues/` with 401 detection, clear error message on failure.

**Implementation:** `competitions/worldcup/main.py:1160-1188` (`validate_api_key()`).

## Monitoring & Observability

**Error Tracking:**
- None. No Sentry, Datadog, or similar. Errors are printed to stderr or logged via the `logging` module.

**Logs:**
- Python `logging` module with `INFO` level (`logging.basicConfig(level=logging.INFO, ...)`) — set at startup in `competitions/worldcup/main.py:1388`.
- Key modules log warnings on API failures, unmatchable teams, sync issues.
- No log aggregation or persistent log file configuration.

**CLI Output:**
- ANSI-colored console output via `competitions/worldcup/src/output.py`.
- Heartbeat polling indicator, match alerts, probability tables, delta summaries, governance dashlets.

## CI/CD & Deployment

**Hosting:**
- No hosted deployment. The application is a CLI tool intended to run on user machines or dedicated servers.

**CI Pipeline:**
- GitHub Actions workflow at `competitions/worldcup/.github/workflows/ci.yml`.
- Trigger: push/PR to `main` branch.
- Strategy: matrix build across Python 3.10, 3.11, 3.12 on `ubuntu-latest`.
- Steps: checkout, Python setup, pip install (requirements.txt + requests numpy), `python -m pytest -v --cov=src --cov-report=term-missing`.
- Working directory: `competitions/worldcup`.
- Secrets: `BSD_API_KEY` passed as `env` to test step for live smoke tests.

## Environment Configuration

**Required env vars:**
- `BSD_API_KEY` — API token for Bzzoiro Sports Data. Validated with HTTP 401 check at startup. Exit code 1 if missing or invalid.

**Optional env vars:**
- `POLL_INTERVAL` — Polling interval in seconds (default: 60). Read at `competitions/worldcup/src/constants.py:53`.

**Secrets location:**
- `.env` file (gitignored via `.gitignore` at repo root — entry `.env`). Template at `competitions/worldcup/.env.example`.
- BSD_API_KEY also passed as GitHub Actions secret for CI tests.

## Webhooks & Callbacks

**Incoming:**
- None. The system polls rather than being pushed to. No webhook endpoints implemented.

**Outgoing:**
- None. No outgoing webhooks or callbacks.

## Data Sources Summary

**External data sources consumed but not classified above:**

| Source | Data | Format | Updates |
|--------|------|--------|---------|
| BSD `/api/events/` | Live match results, odds, stats, context, AI previews | JSON (paginated) | Every 60s (polled) |
| BSD `/api/predictions/` | CatBoost ML predictions, xG | JSON | On each poll (24h cache) |
| eloratings.net `/World.tsv` | Global Elo ratings | TSV (tab-separated) | Every 24h |
| eloratings.net `/Europe.tsv` | European Elo ratings | TSV | Every 24h (Euro only) |

**Static data bundled in repo (not fetched from external sources):**
- `competitions/worldcup/data/teams.json` — Initial team Elo ratings
- `competitions/worldcup/data/groups.json` — Group assignments and match schedule
- `competitions/worldcup/data/bracket.json` — Knockout bracket structure
- `competitions/worldcup/data/annex_c.json` — Third-place advancement routing table
- `competitions/worldcup/data/team_aliases.json` — BSD API team name → canonical name mappings
- `competitions/worldcup/data/team_values.json` — Squad market values (from Transfermarkt, one-time import, not live)
- `competitions/euro/data/teams.json`, `groups.json`, `bracket.json` — Euro 2024 static tournament data

---

*Integration audit: 2026-06-27*
