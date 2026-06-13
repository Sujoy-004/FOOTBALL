# External Integrations

**Analysis Date:** 2026-06-13

## APIs & External Services

**Live Match Results (Primary External Integration):**
- **Service:** Football-Data.org (free tier)
- **Purpose:** Poll for finished World Cup knockout matches in real time
- **SDK/Client:** `requests` library (Python)
- **Endpoint:** `GET https://api.football-data.org/v4/matches?competition=WC&status=FINISHED`
- **Auth:** `X-Auth-Token` header with API key
- **Rate Limit:** 10 requests/minute (free tier); MVP polls at 1 req/60s — well within limit (`SOTs/TRD.md` §6)
- **Response Format:** JSON with `matches[]` array containing `id`, `homeTeam.name`, `awayTeam.name`, `score.fullTime.{home,away}`, `winner`, `status`
- **Error Handling:** Retry up to 3 times with exponential backoff (1s, 2s, 4s). On persistent failure, log error and continue with cached data (`SOTs/TRD.md` §5.1)
- **Match Latency:** API provides results ~30–60 seconds after match ends — acceptable for MVP
- **Failover:** Mock data fallback for testing; no secondary API provider planned for MVP

**Alternatives Considered (noted in `SOTs/MVP.md`):**
- ESPN public API (reverse-engineered, no key) — discarded in favor of Football-Data.org with documented contract

## Data Storage

**Databases:**
- None — MVP uses only local JSON files for persistence

**File Storage:**
- Local filesystem only:
  - `data/teams.json` — Elo ratings and team metadata
  - `data/bracket.json` — Knockout bracket tree
  - `data/played.json` — Completed match records (persisted state)
  - `data/api_id_mapping.json` — External API ID to internal match ID bridge
- Atomic writes: write to temp file then rename to prevent corruption (`SOTs/TRD.md` §5.4)

**Caching:**
- None — no Redis, Memcached, or in-memory cache. The `played_set` and `teams` dict are held in memory during runtime and re-loaded from JSON on restart.

## Authentication & Identity

**Auth Provider:**
- None — MVP has no user accounts, no login, no session management (`SOTs/PRD.md` §4 Won't Have)

**API Key Handling:**
- Football-Data.org API key read from environment variable `FOOTBALL_API_KEY`
- Key loaded in `main.py` via `os.environ.get("FOOTBALL_API_KEY")`
- **Never** stored in JSON files or committed to git (`SOTs/Backend_Schema.md` §9)
- `.env` file existence noted but contents not read; recommended to add to `.gitignore`

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, DataDog, or equivalent. All errors logged to console.

**Logs:**
- Console output with ISO 8601 timestamps (e.g., `[2026-06-15 22:00:01] Polling... no new matches.`)
- No persistent log files for MVP (post-MVP: `--log predictions.log` option per `SOTs/UI_UX_Design.md`)
- ANSI color coding for severity: green (success), red (error), yellow (warnings), dim gray (timestamps)

## CI/CD & Deployment

**Hosting:**
- None — MVP runs locally on user's machine. No cloud deployment planned for MVP.
- Post-MVP: potential Docker containerization (`SOTs/Implementation_plan.md` §10)

**CI Pipeline:**
- None for MVP — tests run manually via `pytest`
- Future: GitHub Actions for automated test runs on push

## Environment Configuration

**Required env vars:**
- `FOOTBALL_API_KEY` — API key for Football-Data.org (mandatory, checked on startup)

**Constants (hardcoded in `src/constants.py` as example defaults):**
- `K_FACTOR = 60` — Elo K-factor (range 20–100)
- `POLL_INTERVAL_SECONDS = 60` — API polling interval
- `SIMULATION_COUNT = 50000` — Monte Carlo iterations
- `API_URL = "https://api.football-data.org/v4/matches?competition=WC&status=FINISHED"`
- `DEFAULT_ELO_START = 2000` — default Elo for new teams

**Secrets location:**
- Environment variable `FOOTBALL_API_KEY` only
- No secrets file, no encrypted vault
- `.env` file recommended but not created or tracked in MVP

## Webhooks & Callbacks

**Incoming:**
- None — MVP uses polling (not push) model

**Outgoing:**
- None — MVP does not push data to any external service

## External Data Files

**Static Data (checked in to repo):**
- `data/bracket.json` — predefined knockout bracket structure (Round of 16 → Quarterfinals → Semifinals → Final)
- `data/teams.json` — initial Elo ratings for all teams (sourced from eloratings.net)
- `data/api_id_mapping.json` — static mapping from Football-Data.org numeric match IDs to internal bracket match IDs

**Runtime Data (not checked in, created during execution):**
- `data/played.json` — dynamically appended as matches are detected

## Post-MVP Integration Roadmap

| Version | Integration | Details |
|---------|-------------|---------|
| v1.1 | Group stage data | Extended bracket schema for group phase |
| v1.2 | Flask web dashboard + Chart.js | HTTP server exposing JSON probabilities |
| v1.2 | WebSocket/SSE | Real-time browser updates (`SOTs/UI_UX_Design.md` §7) |
| v1.3 | XGBoost model | Replace Elo with ML model using xG, possession, injuries |
| v2.0 | Push notifications | Webhooks for probability shifts (`SOTs/PRD.md` §13) |
| v2.0 | Redis | Real-time state sharing for web frontend (`SOTs/TRD.md` §11) |
| v2.0 | PostgreSQL | Store historical probability snapshots (`SOTs/TRD.md` §11) |

---

*Integration audit: 2026-06-13*
