# External Integrations

**Analysis Date:** 2026-06-13

## APIs & External Services

**Live Match Results (Primary External Integration):**
- **Service:** BSD (Bzzoiro Sports Data, free tier)
- **Purpose:** Poll for finished World Cup matches (both group and knockout) in real time
- **SDK/Client:** `requests` library (Python)
- **Endpoint:** `GET https://sports.bzzoiro.com/api/events/?status=finished&league_id=27`
- **Auth:** `Authorization: Token {api_key}` header
- **Rate Limit:** 10 requests/minute (free tier); polls at 1 req/60s — well within limit
- **Response Format:** Paginated JSON with `results[]` array containing `id`, `home_team`, `away_team`, `home_score`, `away_score`, `event_date`, `group_name`, `round_number`, `round_name`, `status`
- **Route Discrimination:** The `group_name` field determines match type:
  - Non-null (e.g., `"Group A"`) → group match → routed to `process_group_matches()`
  - Null → knockout match → routed to existing `process_matches()`
- **Group Match Processing:** `process_group_matches()` in `src/fetcher.py`:
  - Extracts group letter from `group_name` field
  - Normalizes team names via `team_aliases.json` plus group team names from `groups.json`
  - Resolves match slot via team pair + group letter against `groups.json`
  - Dedup via BSD event `id` (in-memory per-poll) and `match_id` (persisted `played_groups.json`)
  - Results stored in `data/played_groups.json` (separate from knockout `played.json`)
- **Knockout Match Processing:** Uses existing `api_id_mapping.json` to map BSD event `id` to internal `match_id` (e.g., `R16_1`)
- **Pagination:** BSD API uses cursor-based pagination (`next`/`previous` fields). Single-page fetch sufficient for polling at 60s intervals.
- **Error Handling:** Retry up to 3 times with exponential backoff (1s, 2s, 4s). On persistent failure, log error and continue with cached data
- **Match Latency:** API provides results ~30–60 seconds after match ends — acceptable for MVP
- **Failover:** Mock data fallback for testing; no secondary API provider planned for MVP

**Alternatives (historical):**
- Football-Data.org (used in v1.0) — replaced by BSD API in v1.1 Phase 10

## Data Storage

**Databases:**
- None — MVP uses only local JSON files for persistence

**File Storage:**
- Local filesystem only:
  - `data/teams.json` — Elo ratings and team metadata
  - `data/bracket.json` — Knockout bracket tree
  - `data/played.json` — Completed match records (persisted state)
  - `data/api_id_mapping.json` — External API ID to internal match ID bridge (knockout matches only)
- `data/played_groups.json` — Completed group match records (separate persistence, added Phase 10)
- `data/groups.json` — 12 group definitions with match slots
- `data/annex_c.json` — 495-entry third-place routing lookup table
- `data/team_aliases.json` — BSD API team name variations for all 48 teams
- Atomic writes: write to temp file then rename to prevent corruption (`SOTs/TRD.md` §5.4)

**Caching:**
- None — no Redis, Memcached, or in-memory cache. The `played_set` and `teams` dict are held in memory during runtime and re-loaded from JSON on restart.

## Authentication & Identity

**Auth Provider:**
- None — MVP has no user accounts, no login, no session management (`SOTs/PRD.md` §4 Won't Have)

**API Key Handling:**
- BSD API key read from environment variable `BSD_API_KEY`
- Key loaded in `main.py` via `os.environ.get("BSD_API_KEY")`
- **Never** stored in JSON files or committed to git
- `.env` file recommended (add to `.gitignore`)

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
- `BSD_API_KEY` — API key for BSD (Bzzoiro Sports Data), mandatory, checked on startup

**Constants (hardcoded in `src/constants.py`):**
- `K_FACTOR = 60` — Elo K-factor (range 20–100)
- `POLL_INTERVAL_SECONDS = 60` — API polling interval
- `SIMULATION_COUNT = 50000` — Monte Carlo iterations
- `API_URL = "https://sports.bzzoiro.com/api/events/?status=finished&league_id=27"`
- `DEFAULT_ELO_START = 2000` — default Elo for new teams
- `GROUP_COUNT = 12`
- `MATCHES_PER_GROUP = 6`

**Secrets location:**
- Environment variable `BSD_API_KEY` only
- No secrets file, no encrypted vault
- `.env` file recommended but not created or tracked

## Webhooks & Callbacks

**Incoming:**
- None — MVP uses polling (not push) model

**Outgoing:**
- None — MVP does not push data to any external service

## External Data Files

**Static Data (checked in to repo):**
- `data/bracket.json` — 40-match knockout bracket (R32 → R16 → QF → SF → TPP → FINAL) with slot descriptors
- `data/teams.json` — initial Elo ratings for all 48 teams (sourced from eloratings.net)
- `data/groups.json` — 12 group definitions (A\u2013L, 4 teams each, 72 match slots)
- `data/annex_c.json` — 495-entry Annex C third-place routing lookup table
- `data/team_aliases.json` — BSD API team name variations for all 48 teams
- `data/api_id_mapping.json` — static mapping from BSD event IDs to internal bracket match IDs

**Runtime Data (not checked in, created during execution):**
- `data/played.json` — dynamically appended as knockout matches are detected
- `data/played_groups.json` — dynamically appended as group matches are detected

## Post-MVP Integration Roadmap

| Version | Integration | Details | Status |
|---------|-------------|---------|--------|
| v1.1 | Group stage data + BSD API | Group match ingestion, standings display, 48-team format | ✅ Complete |
| v1.2 | Flask web dashboard + Chart.js | HTTP server exposing JSON probabilities | 📋 Planned |
| v1.2 | WebSocket/SSE | Real-time browser updates | 📋 Planned |
| v1.3 | XGBoost model | Replace Elo with ML model using xG, possession, injuries | 📋 Planned |
| v2.0 | Push notifications | Webhooks for probability shifts | 📋 Planned |
| v2.0 | Redis | Real-time state sharing for web frontend | 📋 Planned |
| v2.0 | PostgreSQL | Store historical probability snapshots | 📋 Planned |

---

*Integration audit: 2026-06-13*
