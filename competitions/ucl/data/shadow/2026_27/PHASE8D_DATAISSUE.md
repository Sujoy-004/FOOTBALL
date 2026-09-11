# PHASE 8D — DATA ISSUE RESOLUTION: `gen-5dec7b8731a863ee` (Liverpool vs Atlético Madrid)

- **Season:** `2026/27`
- **Date:** 2026-09-11
- **Status:** Documented — **NOT reconciled**, **NOT scored**, no fabricated result

---

## 1. The Issue

`competitions/ucl/data/seasons/2026_27/fixtures.json` contains **12** fixtures
with `status: finished`, but only **11** have a scored result. The unmatched
fixture is:

| Field | Value |
|---|---|
| `match_id` | `gen-5dec7b8731a863ee` |
| `team_a` / `team_b` | Liverpool / Atlético Madrid |
| `event_date` | 2026-09-09T19:00:00Z |
| `official_matchday` | 1 |
| `simulation_matchday` | 4 |
| `status` | `finished` |
| `provenance` | `{fixture: authoritative, schedule: derived}` |

There is **no `results.json` row** for this `match_id` and **no
`results.jsonl` attachment** in the shadow system.

---

## 2. Why It Cannot Be Reconciled Through the Existing Ingestion Path

### 2.1 UCL ingestion is PUSH-based (no fetch in the ingest path)

`competitions/ucl/src/ingest.py::ingest_ucl_events(events, data_dir, provider_name, api_key_unused=None)`
- Signature takes a caller-supplied `events` list (`ingest.py:761-766`)
- `api_key_unused` is explicitly documented as **unused** (`ingest.py:783-784`)
- The function performs **no network I/O** — grep for `requests|urlopen|httpx|aiohttp|urllib` in `competitions/ucl/src/ingest.py` returns nothing

Scores can only enter the data stores when a caller pushes finished events into
`ingest_ucl_events`. Nothing pushed an event for `gen-5dec7b8731a863ee`.

### 2.2 No live payload / feed for this match exists in-repo

| Candidate source | Finding |
|---|---|
| `data/current.json` | Activation marker only (season, basis `draw`) — **no events** |
| `data/seasons/2026_27/results.json` | 11 matches; **no** `gen-5dec7b8731a863ee` |
| `data/seasons/2026_27/fixtures.json` | Fixture exists, `status: finished`, **no scores** |
| Repo-wide grep for `gen-5dec7b8731a863ee` | Only `fixtures.json` + `PHASE7A_AUDIT.md` (this issue's prior documentation). **No event provider references it** |
| `data/snapshot.json` | `mode: simulation`, `provenance: simulated`, champion Bayern Munich — **no `2026-09-0[89]` events** |
| `data/results.json` / `data/fixtures.json` (legacy root) | `MD01_11` "Liverpool vs Atletico Madrid" 3-2 exists, but is the **2025/26 legacy simulation store** (root fixtures has no `season`, no event dates, `MD01_11` is a different `match_id` from a different draw cycle). It is not keyed to the 2026/27 canonical `gen-*` id and never flows into the shadow stores (`shadow_eval` reads `data/seasons/<season>/results.json`) |
| Local/legacy historical (`bootstrap/`, `historical/`) | All 2025/26 and earlier — no 2026-09-08/09 UCL events |
| Environment | `BSD_API_KEY` and `FOOTBALL_DATA_ORG_API_KEY` are **not set**; the only live source (`fetcher.py:fetch_ucl_matches`, BSD API at `sports.bzzoiro.com`) is unreachable without credentials |

### 2.3 Root cause (unchanged from Phase 7A finding)

The `status: finished` marker for this fixture originates from the **simulation**
pipeline (`simulation_matchday: 4`), which marked the fixture finished without
recording a real result in the season store. This is a source-data provenance gap,
outside the shadow subsystem.

---

## 3. Decision

1. **Do not invent a score.** The `attach` CLI already guarantees this: result
   rows lacking either score are never attached and never turned into a
   fabricated 0-0 (`shadow_eval.py::attach_results`, `n_missing`/skipped path).
2. **Leave the fixture unscored.** No authoritative score is available through
   the existing ingestion path.
3. **Shadow impact is nil.** This match kicked off 2026-09-09, strictly **before**
   the 2026-09-11 freeze (`2026-09-11T01:47:19.912141+00:00`). It is therefore
   **not a frozen match**, never enters the shadow scored pool, and cannot affect
   `n_pending_fixtures = 119` or any strategy metric.
4. **Documented, not silently repaired.** The decision is recorded here and in
   PHASE8A_MATCHDAY_ACCUMULATION.md; downstream phases must not assume a result
   for `gen-5dec7b8731a863ee`.

---

## 4. Candidate Reconciliation Paths (not applied)

If a trustworthy score is ever needed, the following paths exist — **none should
be applied unilaterally without the data-pipeline owner's sign-off**:

1. **Live BSD fetch** (`competitions/ucl/src/fetcher.py::fetch_ucl_matches`) —
   would pull finished events for `league_id=7` from `sports.bzzoiro.com` when a
   valid `BSD_API_KEY` is configured, then feed them into `ingest_ucl_events`.
   Requires credentials not present in this environment.
2. **Manual authoritative result** from an official/UEFA source for the exact
   pairing (Liverpool vs Atlético Madrid, 2026-09-09) as a pushed event with a
   scored `home_score`/`away_score` and `status: finished`.

If either mechanism becomes available with the exact teams+date for
`gen-5dec7b8731a863ee`, it should be reported as a candidate reconciliation path
and pursued deliberately — never applied silently.