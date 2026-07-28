<!-- generated-by: gsd-doc-writer -->
# Configuration

This project uses **environment variables** for configuration. There are no YAML, TOML, or INI configuration files — settings are sourced from the environment, loaded via `python-dotenv` from a `.env` file.

---

## Configuration Mechanisms

| Mechanism | Scope | Persistence |
|-----------|-------|-------------|
| Environment variables | Per-session | Optional `.env` file (loaded via `python-dotenv`) |
| File-based config | Runtime | JSON state files under competition `data/` directories |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BSD_API_KEY` | **Required** for live data refresh | — | API key for the BSD (Bzzoiro Sports Data) API. Used to fetch live match data, odds, and CatBoost predictions. |
| `POLL_INTERVAL` | Optional | `60` | Polling interval in seconds between API fetch cycles (World Cup predictor only). |

### BSD_API_KEY

The BSD API provides live match events, market odds, and CatBoost predictions. Without it, the dashboard falls back to cached data and Elo-only mode.

To obtain a key, register at <https://sports.bzzoiro.com/register/>.

**Setting via `.env` file:**

Create a file named `.env` in the project root with the following content:

```
BSD_API_KEY=your_api_key_here
```

The `.env` file is listed in `.gitignore` and must never be committed.

**Setting via shell environment (PowerShell):**

```powershell
$env:BSD_API_KEY = "your_api_key_here"
```

**Setting via shell environment (bash):**

```bash
export BSD_API_KEY="your_api_key_here"
```

### POLL_INTERVAL

Controls how frequently the World Cup predictor polls the BSD API for new matches. Only consumed by `competitions/worldcup/src/constants.py`.

```python
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
```

---

## Web Server

The web dashboard is a FastAPI application served via uvicorn on `127.0.0.1:8080`.

### Startup

```bash
python -m web.server
```

Mount points:

| Mount Point | Sub-app | Source |
|-------------|---------|--------|
| `/` | Landing page (SPA shell) | `web/static/index.html` |
| `/worldcup` | World Cup predictor | `web/wc_app.py` |
| `/worldcup/api/*` | World Cup REST API | `web/wc_app.py` |
| `/ucl` | UCL predictor | `web/ucl_app.py` |
| `/ucl/api/*` | UCL REST API | `web/ucl_app.py` |
| `/euro` | Euro placeholder (stub) | `web/server.py` `/euro` route |
| `/static` | Static assets | `web/static/` directory |

### Configuration

The server host (`127.0.0.1`), port (`8080`), and live reload (`False`) are hardcoded in `server.py`. To change them, edit the `uvicorn.run()` call directly.

For development with hot reload:

```bash
uvicorn web.server:asgi_app --reload --host 127.0.0.1 --port 8080
```

### Caching

On startup (`lifespan` event), the server pre-computes all prediction data and caches it entirely in memory — there are no persistent cache files written by the web server. The server adds `Cache-Control: no-cache` headers to all `/static/` responses to prevent stale asset serving during development.

To force full re-computation, restart the server.

---

## Required vs Optional Settings

| Setting | Behaviour When Missing |
|---------|-----------------------|
| `BSD_API_KEY` | Dashboard runs in Elo-only mode using cached data. Live refresh (`POST /api/refresh`) and BSD-dependent signals (market odds, CatBoost) are unavailable. |

---

## Defaults (Source-Code Values)

| Variable | Default Value | Set In |
|----------|---------------|--------|
| `API_TIMEOUT` | `10` (seconds) | `football_core/constants.py` |
| `POLL_INTERVAL` | `60` | `competitions/worldcup/src/constants.py` |
| `--iterations` (simulation) | `10000` | `web/ucl_app.py` |
| `host` (web server) | `127.0.0.1` | `web/server.py` |
| `port` (web server) | `8080` | `web/server.py` |
| `reload` (web server) | `False` | `web/server.py` |

---

## Per-Environment Overrides

The project does **not** use environment-specific config files (`.env.development`, `.env.production`, etc.). All configuration is supplied at invocation time.

**Development:** Use `uvicorn --reload` for hot-reload during frontend/backend edits.

**Production:** Run with `python -m web.server`. Ensure `BSD_API_KEY` is set for live data. The server auto-computes all data on startup.
