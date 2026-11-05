<!-- generated-by: gsd-doc-writer -->
# Configuration

This document outlines the environment variables, configuration files, default values, and operational modes used across the FOOTBALL simulation and prediction platform.

---

## Environment Variables

The application reads configuration from environment variables at runtime via `os.environ` / `os.getenv` and automatically loads `.env` files via `python-dotenv` during server initialization (`web/server.py`, `web/startup.py`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATA_PROVIDER` | Optional | `football-data` | Primary fixture and match results provider. Options: `football-data`, `auto`, or empty. |
| `FOOTBALL_DATA_ORG_KEY` | Optional | `""` | API key for `football-data.org`. Free tier available. Read lazily at call time. |
| `ODDS_PROVIDER` | Optional | `auto` | Bookmaker odds provider. Options: `the-odds-api`, `auto`, or `none` (explicitly disables odds enrichment). |
| `THE_ODDS_API_KEY` | Optional | `""` | API key for The Odds API (`the-odds-api.com`). Required when `ODDS_PROVIDER=the-odds-api` or `auto`. |
| `FOOTBALL_SNAPSHOT` | Optional | `""` (unset) | Set to `1`, `true`, `yes`, or `on` to force an explicit offline session (zero network calls, serves stored snapshots). |
| `FOOTBALL_PRELOAD_ALL` | Optional | `""` (unset) | Set to `1` to enable eager preloading/refreshing of all registered competitions during server lifespan boot (default unset is lazy acquisition on first request). |
| `POLL_INTERVAL` | Optional | `60` | Polling interval in seconds for World Cup live-ingestion background loop. |
| `FOOTBALL_LIVE` | Optional | `""` (unset) | Safety guard for UCL CLI live-ingestion scripts (`competitions/ucl/main.py`). Must be set to `1` to permit writes into canonical repository data directories. |
| `DATABASE_URL` | Optional | `""` (unset) | SQLAlchemy database connection string (e.g., `postgresql://...` or `sqlite:///...`). Automatically normalized (Neon pooler host rewrite, sslmode enforcement). Falls back to JSON stores when unset. |
| `PORT` | Optional | `8080` | Port to bind the web server. Read by `web.server:build_arg_parser`. |
| `HOST` | Optional | `127.0.0.1` (`0.0.0.0` if `PORT` set) | Host IP address to bind the web server. Read by `web.server:build_arg_parser`. |
| `ENVIRONMENT` | Optional | `""` | Deployment environment name (e.g., `production`). Enables production security guards (strict admin auth and CORS). |
| `RENDER` | Optional | `""` | Flag indicating hosting on Render (`true`). Treated as production environment. |
| `ADMIN_KEY` | Optional | `""` | Secret key for privileged operator endpoints (e.g. `/api/admin/sync`). In production, matching header `X-Admin-Key` or query param `admin_key` is strictly enforced. |
| `ALLOWED_ORIGINS` | Optional | `""` | Comma-separated list of allowed CORS origins. Appended to local loopback defaults (`http://localhost:8080`, `http://localhost:3000`, `http://127.0.0.1:8080`, `http://127.0.0.1:3000`). |
| `SHADOW_VERBOSE` | Optional | `""` (unset) | UCL shadow evaluation debug output toggle. When truthy, enables verbose shadow evaluation logging. |

---

## Config File Format

Configuration primarily resides in environment variables and local JSON files.

### `.env` File Example

Create a local `.env` file at the repository root based on `.env.example`:

```bash
# Data provider configuration
DATA_PROVIDER=football-data
FOOTBALL_DATA_ORG_KEY=your_football_data_org_key_here

# Odds provider configuration
ODDS_PROVIDER=auto
THE_ODDS_API_KEY=your_the_odds_api_key_here

# Operational execution flags
FOOTBALL_SNAPSHOT=
FOOTBALL_PRELOAD_ALL=
FOOTBALL_LIVE=

# Polling and networking
POLL_INTERVAL=60
PORT=8080
HOST=127.0.0.1

# Optional database storage (falls back to local JSON files when empty)
DATABASE_URL=

# Security and access controls
ENVIRONMENT=development
ADMIN_KEY=
ALLOWED_ORIGINS=http://localhost:8080,http://localhost:3000
```

### Signal Weights Configuration (`competitions/<competition>/config/signal_weights.json`)

The blender module (`football_core/blender.py`) resolves ensemble weights according to:
1. Explicit in-memory weights dict passed to `EnsembleEngine`.
2. A JSON configuration file (such as `competitions/worldcup/config/signal_weights.json` or `competitions/laliga/config/signal_weights.json`) containing calibrated weights.
3. Uniform weight fallback over registered signals.

Example `signal_weights.json` structure (e.g., from `competitions/laliga/config/signal_weights.json`):

```json
{
  "weights": {
    "refined_elo": 0.40,
    "market_odds": 0.25,
    "rolling_form": 0.15,
    "squad_value": 0.10,
    "rest_days": 0.10
  }
}
```

### Tooling Configuration (`pyproject.toml`)

Project linting, typing, and testing defaults are declared in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]

[tool.ruff]
target-version = "py311"

[tool.mypy]
python_version = "3.11"
explicit_package_bases = true
ignore_missing_imports = true

[tool.coverage.report]
fail_under = 70
```

---

## Required vs Optional

### Startup Requirements
- **No environment variable is strictly required for server boot.** The platform is designed to boot cleanly without any external services or API keys configured.
- When `FOOTBALL_DATA_ORG_KEY` is omitted or contains a template placeholder (e.g. `your_...`), the server starts in `auto` mode: acquisition is attempted on refresh triggers, but missing credentials report a clean informational fallback rather than crashing.
- When `DATABASE_URL` is omitted, the storage layer automatically falls back to local JSON file stores under each competition's directory (`competitions/<name>/data/`).

### Production Safety Requirements
- **`ADMIN_KEY`**: Required in production environments (`ENVIRONMENT=production` or `RENDER=true`) when invoking protected operator/sync endpoints. Missing or mismatched keys return HTTP 403.
- **`FOOTBALL_LIVE`**: Required (`FOOTBALL_LIVE=1`) when executing UCL CLI live-ingestion scripts targeting repository data paths to avoid accidental data overwrites during testing.

---

## Defaults

| Setting | Default Value | Defined In | Notes |
|---|---|---|---|
| Server Port | `8080` | `web/server.py` | Overridden by CLI `--port` or `$PORT`. |
| Server Host | `127.0.0.1` (`0.0.0.0` if `$PORT` set) | `web/server.py` | Overridden by CLI `--host` or `$HOST`. |
| Polling Interval | `60` seconds | `competitions/worldcup/src/constants.py` | Configurable via `$POLL_INTERVAL`. |
| Data Provider | `football-data` | `football_core/runtime_support.py` | Configurable via `$DATA_PROVIDER`. |
| Odds Provider | `auto` | `football_core/odds.py` | Resolves to The Odds API if `$THE_ODDS_API_KEY` present. |
| Storage Backend | `fallback_json` | `football_core/persistence/engine.py` | Active when `$DATABASE_URL` is empty. |
| CORS Origins | Localhost / 127.0.0.1 on 8080 & 3000 | `web/security.py` | Extended by `$ALLOWED_ORIGINS`. |

---

## Per-Environment Overrides

The application supports multiple execution modes controlled via environment variables and CLI flags:

### 1. Offline Snapshot Mode
- **Activation**: Set `FOOTBALL_SNAPSHOT=1` (or run with `python -m web.server --offline`).
- **Behavior**: All external network calls and scrapers self-gate and make zero HTTP requests. The server serves historical snapshot files committed in the repository.

### 2. Lazy Acquisition Mode (Default)
- **Activation**: Default mode (no extra flags).
- **Behavior**: Server startup makes zero provider calls. Each competition lazily fetches and refreshes its data on the first incoming request or explicit `POST /api/refresh`.

### 3. Eager Preload Mode
- **Activation**: Set `FOOTBALL_PRELOAD_ALL=1` (or run `python -m web.server` without `--no-preload`).
- **Behavior**: The server lifespan warms and refreshes caches for all registered competitions in a worker thread at startup.

### 4. Production Security Mode
- **Activation**: Set `ENVIRONMENT=production` or `RENDER=true`.
- **Behavior**: Enforces constant-time `ADMIN_KEY` validation on operator endpoints, shields internal tracebacks, and scrubs secret credentials from error messages and logs using `football_core.domain.redact_secrets`.
