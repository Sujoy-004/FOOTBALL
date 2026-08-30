# EXCHANGE 9 — INTEGRATOR FINAL REPORT

Subagent D (Integrator) — FOOTBALL repo, Exchange 9.
Date: 2026-08-30 (server run; no real browser in this agentic environment — web verification was performed over HTTP).

---

## 1. Root causes + fixes (Agents A and B)

### A — Per-season refresh metadata (`web/ucl_app.py`)
Root cause: the freshness ledger was a single global `ucl` entry. One season's deferred/stale outcome leaked onto every season's API view, and a season that had never been refreshed inherited another season's report (wrongly deferred, or wrongly "live").

Fix (per-season, additive, backward-compatible):
- `web/ucl_app.py:116` — `_refresh_report: dict` plus a season-scoped store `_refresh_reports: dict[str, dict]` and a seed flag.
- `web/ucl_app.py:124` — `_season_refresh_reports()` lazily hydrates the per-season store from the persisted ledger once, folding in both the legacy single `"ucl"` entry (attached under its recorded `active_season`) and the newer `"ucl_seasons"` map; in-process reports win over file state.
- `web/ucl_app.py:147` — `_active_season_token()` canonical season token (current.json pointer when present, else the shipped local historical season).
- `web/ucl_app.py:166` — `_synthesize_season_report(season)` store-truthful standby report for a season nobody refreshed this process — `attempted=False / success=True / stale=False / deferred=False / status="ok"` with a real `n_matches` from `_match_counts()`, **not written to the store**.
- `web/ucl_app.py:192` — `_refresh_report_for(season)` serves the snapshot-skipped umbrella as-is, else the active season's own entry, else a synthesized entry.
- `web/ucl_app.py:208` — `_store_refresh_report(...)` now records + persists BOTH the umbrella `ucl` slot and `ucl_seasons[season]` (`deferred`/`reason`/`status` are threaded in).
- `web/ucl_app.py:490` — `/api/data` serves `_refresh_report_for(_active_season_token())` (per-season scoping).
- New test file `tests/test_ucl_refresh_season_scoped.py` (8 tests).

### B — UTF-8 decode for accented team/alias reads
Root cause: several JSON reads used `open(...)` with the platform default text encoding (cp1252 on Windows), which corrupted accented ClubElo names (`ü`, `ø`, `ç`, ...) in memory.

Fix: explicit `encoding="utf-8"` added to:
- `football_core/elo_fetcher.py:46` — `_load_aliases`.
- `competitions/ucl/src/provider.py:57` — `RepoFixtureProvider.load`.
- `competitions/ucl/src/provider.py:247` — `BSDFixtureProvider._load_cache`.
- `competitions/ucl/src/orchestrator.py:513` — live-mode `team_aliases` read.
- Regression tests: `competitions/ucl/tests/test_provider.py::TestRepoFixtureProvider::test_loads_accented_team_names_as_utf8`, and `competitions/ucl/tests/test_simulation.py::TestClubEloFetcher::test_load_aliases_preserves_accented_entries` (both force cp1252 via a `builtins.open` monkeypatch so they FAIL without the fix).

---

## 2. ClubElo coverage — before / after + "Refined Elo" truthfulness

Measured against the LIVE ClubElo snapshot (`api.clubelo.com/{YYYY-MM-DD}`, network reachable), resolving Team → ClubElo name → ranking key, counting `DEFAULT_ELO=1500` misses.

| Season | Before fix (Agent C) | After fix (Agent D) |
|---|---|---|
| 2025/26 | 36/36 resolved, 0 → 1500 | 36/36 resolved, 0 → 1500 |
| 2026/27 | **21/36** resolved, **15/36** → 1500 | **22/36** resolved, **14/36** → 1500 |

Only **Atlético Madrid → "Atletico"** was recovered (was 1500, now a real rating, Elo 1827.7). The 14 that still resolve to 1500, and why they cannot be fixed within constraints:
- **Bodø/Glimt** — `ø` (U+00F8) has NO NFKD decomposition, so the diacritic-strip fallback can't turn it into ASCII "Bodo/Glimt"; no invented alias / transliteration allowed.
- **Fenerbahçe** — no alias key exists at all (structural mismatch); no alias entry may be invented.
- 12 structural full-display-name-vs-short-ASCII-key mismatches, e.g.: Paris Saint-Germain→"PSG", Bayern Munich→"Bayern", Manchester City→"Man City", Manchester United→"Man United", Inter Milan→"Inter", Borussia Dortmund→"Dortmund", Sporting CP→"Sporting", Real Betis, PSV Eindhoven→"PSV", Shakhtar Donetsk, VfB Stuttgart, AEK Athens. These have no alias mapping; adding one is forbidden (no invented aliases, no identity-data edits).

**"Refined Elo" truthfulness verdict (2026/27): NOT fully truthful.** `competitions/ucl/src/orchestrator.py:912-917` hardcodes `refined_elo` as `n_matches=144 / available=144 / available_pct=100.0`. While there are indeed 144 scheduled league fixtures, 14 of the 36 teams feed exactly `1500.0` (DEFAULT_ELO floor) at runtime — so claiming 100% availability overstates the real Elo-derived signal completeness. The exact-match count (144) is correct; the "100%" is not truly representative. This hardcoded block was NOT part of the sanctioned fix (no arch redesign); the coverage reality is the 22/36 (14 floor) numbers above. Fixing the "100%" label would require a separate sanctioned change.

---

## 3. Files changed

### Exchange-9 touched by this integration
Only the two sanctioned-extension files (fix + tests), on top of A/B/C work:
- `football_core/elo_fetcher.py` — added `unicodedata` import, `_normalized_key()` helper, and accent-insensitive fallback in `resolve_clubelo_name` (added by me; also contains B's `encoding="utf-8"` at line 46).
- `competitions/ucl/tests/test_simulation.py` — 3 new focused regression tests added (plus B's 1 existing test in the same file).

### Exchange-9 work by other agents (verified disjoint, none overlap with mine)
- `web/ucl_app.py` (A)
- `tests/test_ucl_refresh_season_scoped.py` (A, untracked/new)
- `competitions/ucl/src/provider.py`, `competitions/ucl/src/orchestrator.py`, `competitions/ucl/tests/test_provider.py` (B)

### Pre-existing Exchange-8 carry-over dirty files (NOT touched by me)
- `competitions/ucl/src/pipeline.py`
- `football_core/fetcher.py`
- `football_core/data_providers/bsd_provider.py`
- `football_core/data_providers/football_data_org_provider.py`
- `web/static/shared.css`, `web/static/shared.js`, `web/static/ucl.js`
- `competitions/ucl/tests/test_season_draw.py`
- `tests/test_ucl_future_season_empty_provider.py` (untracked/new carry-over)

Conflict-review: **A's and B's file sets are disjoint**; neither overlaps my two files. No merge conflicts. `_load_aliases` `lru_cache` scoping is unchanged by my fix (I only added a fallback within `resolve_clubelo_name`, which never touches the alias cache), and B's encoding edit does not invalidate Agent C's measurement (C measured on the tree with B's fix applied).

No commits, no `git add`, no ZIPs, no pushes were created (git used for inspection only).

---

## 4. Pytest results

### Focused set (exact command)
```
python -m pytest tests/test_ucl_refresh_season_scoped.py tests/test_ucl_future_season_empty_provider.py tests/test_freshness_visibility.py tests/test_always_on_acquisition.py competitions/ucl/tests/test_provider.py competitions/ucl/tests/test_simulation.py -q
```
Result: **73 passed, 1 skipped, 0 failed.**

### Full suite (exact command)
```
python -m pytest -q
```
Result: **1222 passed, 1 skipped, 0 failed.**

Neighborhood check vs earlier tallies: Agent A reported 1219 passed / 1 skipped; Agent B reported 1211 passed / 1 skipped. After merging A + B + my 3 net new tests: **1222 passed / 1 skipped**, skip count unchanged (1), no new failures. My fix caused **no** regression.

---

## 5. Browser-equivalent / HTTP verification

**Limitation (explicit):** this is an agentic CLI environment — there is no real browser available. Web behavior was verified by running the actual FastAPI server and inspecting real HTTP responses + static carriers.

Server: launched `python -m uvicorn web.server:asgi_app --host 127.0.0.1 --port <free>` (the app's normal entrypoint is `python -m web.server`, port 8080; I ran on a free port). Confirmed `GET /` → 200. Runtime state files (`competitions/ucl/data/current.json`, `web/last_refresh.json` — both gitignored) were backed up before the run and restored byte-exactly afterward.

- **(a) 2026/27 is active → GET /ucl/api/data**: refresh payload is **deferred** — `deferred: true`, `status: "deferred"`, `reason: "provider_empty"`, `n_matches: 0`, mode live. The acquisition notice **"Provider has no published match data yet"** is produced by the frontend logic ONLY for 2026/27 (confirmed derivable from the served deferred object). No score data is faked.
- **(b) POST /ucl/api/season {"season":"2025/26"} → GET /api/data**: refresh is **NOT deferred** and carries **no** 2026/27 message. It shows the synthesized historical `ok` entry: `deferred: false, status: "ok", synth: true, attempted: false, success: true, n_matches: 144, n_played: 144`. ✓
- **(c) POST /ucl/api/season {"season":"2026/27"} → GET /api/data**: **deferred again** (`deferred: true, reason: provider_empty, n_matches: 0`) — no reuse of the 2025/26 synthesized message. Per-season scoping verified (no cross-season leak). ✓
- **(d) GET /api/signals**:
  - **2025/26**: full real signal state — 5 signals (market_odds, refined_elo, rest_days, rolling_form, squad_value), each 144 matches / 100% available, with real avg_probability/brier/accuracy.
  - **2026/27**: only 2 signals (refined_elo, rolling_form), **no** published-match signals (market_odds/rest_days/squad_value absent) — it does NOT claim match-result signal availability it doesn't have. (Note: refined_elo still hardcodes n_matches=144 / 100% — see Section 2 nuance.)
- **(e) POST /api/refresh** (non-destructive while on 2025/26): returned `{"status":"ok","mode":"results","refreshed":true}`; no crash. This did record a live-fetch outcome for 2025/26 in the in-process store; subsequent 2025/26 views reflect that process refresh (stale/fallback rather than pristine synth) — expected, and all persisted state was restored after shutdown.
- **Static carriers (read-only):** `web/static/ucl.js` checks `deferred`/`provider_empty` **before** the stale branch (lines 214-219, 405-426) and sets the notice string "Provider has no published match data yet" for the deferred case (414). `_buildAcquisition(d)` consumes `d.refresh` **generically** (line 398) with no season hardcoding. `web/static/shared.js:renderAcquisitionPanel` (559-578) and `web/static/shared.css:.acq-notice-line` (755) are generic carriers of the per-season object.

All runtime files restored; the server process was stopped.

---

## 6. Remaining issues / known limits

1. **2026/27 default-Elo floor = 14/36** (down from 15/36). 14 teams still feed `1500.0` because: Bodø/Glimt `ø` is non-decomposable under NFKD, Fenerbahçe has no alias key, and 12 are full-display-name-vs-short-ASCII-key mismatches. Fixing these is out of scope (no invented aliases / no identity-data edits).
2. **Signal-availability label nuance**: `orchestrator.py:912-917` hardcodes `refined_elo` as 144 / 100% for 2026/27 even though 14 of 36 teams use the 1500 floor — the "100%" overstates real Elo completeness. Not part of this sanctioned fix.
3. **Live vs snapshot modes**: the exact ClubElo but the live snapshot is date-dependent; coverage ratios above were measured against the live snapshot on the run date and may drift with the off-season ranking window (fallback per-team history also applies for expired-rank teams).
4. **Persistence of `ucl_seasons` in `web/last_refresh.json`**: A's `_store_refresh_report` persists both `ucl` (legacy slot, always latest) and `ucl_seasons[season]` per season. On the next process run, `_season_refresh_reports()` folds both back in. Verified during the HTTP run that `ucl_seasons` gains an entry per season refreshed/visited in-process (2026/27 and 2025/26 both appeared), then the file was restored.
5. **No real browser**: visual/JS-rendering behavior was verified by static inspection + HTTP payloads, not by an actual browser.
