# External Integrations

**Analysis Date:** 2026-06-16

## APIs & External Services

### BSD (Bzzoiro Sports Data) — Primary Live Match Source
- **Service:** BSD (Bzzoiro Sports Data, free tier)
- **Purpose:** Poll for finished World Cup matches (group and knockout) in real time
- **SDK/Client:** `requests` library (Python)
- **Endpoint:** `GET https://sports.bzzoiro.com/api/events/?league_id=27&limit=200`
- **Status filtering:** Post-filtered for `status == "finished"` in `fetcher.py`
- **Auth:** `Authorization: Token {api_key}` header
- **Rate Limit:** 10 requests/minute (free tier); polls at 1 req/60s — well within limit
- **Response Format:** Paginated JSON with `results[]` containing `id`, `home_team`, `away_team`, `home_score`, `away_score`, `event_date`, `group_name`, `status`
- **Route Discrimination:** `group_name` field determines match type:
  - Non-null → group match → `process_group_matches()`
  - Null → knockout match → `process_matches()`
- **Group Match Processing:** `process_group_matches()` in `src/fetcher.py`:
  - Extracts group letter from `group_name` field
  - Normalizes team names via `team_aliases.json` + group team names from `groups.json`
  - Resolves match slot via team pair + group letter against `groups.json`
  - Dedup via BSD event `id` (in-memory per-poll) and `match_id` (persisted `played_groups.json`)
  - Results stored in `data/played_groups.json`
- **Knockout Match Processing:** Matches by team pair against bracket. No `api_id_mapping.json` (removed in v2.0)
- **Error Handling:** Retry up to 3 times with exponential backoff (1s, 2s, 4s). On persistent failure, log error and continue with cached data
- **Match Latency:** API provides results ~30–60 seconds after match ends
- **Failover:** Mock data fallback for testing; no secondary API provider for MVP

### Eloratings.net — Rating Sync (Phase 11, D-10 through D-13)
- **Service:** eloratings.net (canonical World Football Elo ratings)
- **Purpose:** Periodically reconcile our dynamic Elo ratings with the canonical source
- **Endpoint:** Direct TSV download (`World.tsv`) — no HTML parsing needed
- **Frequency:** On-demand via `python -m src.elo_sync`
- **Mechanism:** Graduated correction approach handles systematic formula differences without creating audit noise
- **Output:** `elo_applied.json` (changes applied) + `elo_update_log.json` (audit trail) + `eloratings_cache.json` (cached TSV data)

## Data Storage

**Databases:** None — MVP/local-only uses JSON files for persistence

**File Storage (14 data files):**
| File | Purpose | Type |
|---|---|---|
| `data/teams.json` | Elo ratings, group assignments, FIFA rank for 48 teams | Static (initial), rewritten on Elo update |
| `data/bracket.json` | 40-match knockout bracket structure | Static |
| `data/groups.json` | 12 group definitions (A–L), 72 match slots | Static |
| `data/annex_c.json` | 495-entry third-place routing lookup table | Static |
| `data/team_aliases.json` | BSD API name variations for all 48 teams | Static |
| `data/played.json` | Completed knockout match records | Runtime (grows) |
| `data/played_groups.json` | Completed group match records | Runtime (grows) |
| `data/prediction_history.json` | Probability snapshots for evaluation | Runtime |
| `data/elo_applied.json` | Elo sync changes applied | Runtime |
| `data/elo_update_log.json` | Elo sync audit trail | Runtime |
| `data/eloratings_cache.json` | Cached eloratings.net TSV data | Runtime |
| `data/eval_baseline.json` | Evaluation baseline data | Runtime |
| `data/eval_baseline_report.json` | Evaluation baseline report | Runtime |

**Atomic writes:** Write to `.tmp` file → `os.replace()` to target path

## Authentication & Identity

**Auth Provider:** None — no user accounts, no login, no session management

**API Key Handling:**
- BSD API key read from environment variable `BSD_API_KEY`
- Key loaded in `main.py` via `os.environ.get("BSD_API_KEY")`
- `ValueError` raised if missing on startup
- **Never** stored in JSON files or committed to git
- `.env.example` provided (`.env` in `.gitignore`)

## Monitoring & Observability

**Error Tracking:** None — no Sentry, DataDog, etc. All errors logged to console.

**Logs:** Console output with ISO 8601 timestamps. No persistent log files. ANSI color coding for severity.

## CI/CD & Deployment

**Hosting:** None — runs locally on user's machine. No cloud deployment.

**CI Pipeline:** None — tests run manually via `pytest`. 329 tests in 16 test files.

## Environment Configuration

**Required env vars:**
- `BSD_API_KEY` — API key for BSD Sports Data, mandatory, checked on startup

**Constants (hardcoded in `src/constants.py`):**
- `K_FACTOR = 60`
- `POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))` — env-overridable
- `SIMULATION_COUNT = 50000`
- `API_URL = "https://sports.bzzoiro.com/api/events/?league_id=27&limit=200"`
- `DEFAULT_ELO = 1500`
- `GROUP_COUNT = 12`, `MATCHES_PER_GROUP = 6`, `ANNEX_C_ENTRIES = 495`

## Post-MVP Integration Roadmap

| Version | Integration | Status |
|---|---|---|
| v1.0 | Football-Data.org API (knockout) | ✅ Complete (migrated to BSD) |
| v1.1 → v2.0 | BSD Sports Data API | ✅ Complete |
| v2.0 | Group stage data + BSD API | ✅ Complete |
| v2.0 | Elo sync from eloratings.net | ✅ Complete |
| v2.0 | Evaluation metrics pipeline | ✅ Complete |
| v2.0 | Prediction history persistence | ✅ Complete |
| Future | Flask web dashboard + Chart.js | 📋 Planned |
| Future | WebSocket/SSE real-time updates | 📋 Planned |
| Future | XGBoost model replacement | 📋 Planned |
| Future | Redis / PostgreSQL for scaling | 📋 Planned |

---

*Integration audit: 2026-06-16*
