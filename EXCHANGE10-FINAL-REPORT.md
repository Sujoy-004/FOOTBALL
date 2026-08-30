# EXCHANGE 10 — FINAL REPORT (Integrator D)

Scope: Exchange 10 of the FOOTBALL repo — replace the hardcoded shell `refined_elo`
per-team coverage claim with a real, measured, provenance-gated value, and surface it
honestly in the API + UI. This report is the integrator's conflict/quality review,
end-to-end validation, full pytest run, HTTP/API verification (incl. season switching),
and acceptance mapping. **No commits, adds, pushes, or archives were made.** Only this
report file was written.

---

## 1. Root cause

`competitions/ucl/src/orchestrator.py` (shell branch, pre-Exchange-10 block around
lines 915–920 / original 912–922) hardcoded:

```python
signal_stats["refined_elo"] = {
    "n_matches": 144, "available": 144, "available_pct": 100.0,
    "weight": round(engine.weights.get("refined_elo", 0), 4),
}
```

For the zero-results 2026/27 shell this read, in the UI's signal-availability table,
as a bare green "Yes" — an implied *full data coverage* claim for the refined Elo
signal. In fact those keys encode **per-match prediction availability** (the engine can
emit a probability for all 144 drawn fixtures), which is `available`/`available_pct`
semantics — NOT per-team ClubElo data coverage. The two concepts were conflated, and no
per-team coverage number existed at all.

## 2. Exact before/after coverage (measured for real, not assumed)

Method: in-process `web.server.app` boot via FastAPI `TestClient` against the repo's
real runtime data, LIVE mode (`FOOTBALL_SNAPSHOT` unset, usable provider key present —
`startup` decided `live-configured`). ClubElo DNS/HTTP probe returned `HTTP 200` for
`http://api.clubelo.com/2026-08-30` before the run, so the **live fetch path was
exercised** (not the fallback).

| Season | Exchange 9 (before) | Exchange 10 (after — observed runtime) |
|---|---|---|
| 2025/26 (completed) | 36/36 resolved, 0 teams at 1500.0 | **36/36, 0 at 1500.0, provenance `clubelo`** — served `coverage:36 / coverage_total:36 / coverage_pct:100.0` |
| 2026/27 (draw shell) | 22/36 resolved, 14 at 1500.0 | **22/36, 14 at 1500.0, provenance `clubelo`** — served `coverage:22 / coverage_total:36 / coverage_pct:61.1` |

Observed served payload for 2026/27 (`GET /ucl/api/signals`, 2026-08-30T11:23:24Z):

```json
"refined_elo": {
  "n_matches": 144, "available": 144, "available_pct": 100.0, "weight": 0.1912,
  "coverage": 22, "coverage_total": 36, "coverage_pct": 61.1, "provenance": "clubelo"
}
```

Observed served payload for 2025/26 (after `POST /ucl/api/season {"season":"2025/26"}`,
2026-08-30T11:23:26Z):

```json
"refined_elo": {
  "n_matches": 144, "available": 144, "available_pct": 100.0,
  "avg_probability": 0.3333, "weight": 0.1912, "brier": 0.5427, "accuracy": 0.5833,
  "coverage": 36, "coverage_total": 36, "coverage_pct": 100.0, "provenance": "clubelo"
}
```

**Live-vs-offline discrepancy resolved.** Both Agent A's (ClubElo timeout →
`coefficient_derived`/0) and Agent C's (TestClient observed 22/36 `clubelo`) reports
were serial observations of a date/network-dependent fetch, not a contradiction.
**At my runtime, ClubElo was reachable and the live `clubelo` path genuinely produced
22/36 (2026/27) and 36/36 (2025/26).** The offline variant (`coefficient_derived`, 0
coverage, 0.0%) was verified **only at unit level** (test_orchestrator.py
`test_coefficient_fallback_reports_zero_clubelo_coverage` and the
`compute_signal_eval` coefficient test); it is what the same request would serve if the
ClubElo fetch raises/times out.

## 3. API/UI behavior

### Payload schema (additive — existing keys untouched)

`compute_elo_coverage()` (`pipeline.py:222`) adds exactly the spec-card keys to the
`refined_elo` entry only — for both the shell branch (via `compute_elo_coverage` call at
`orchestrator.py:926–928`) and the completed-season branch (via `compute_signal_eval`,
`pipeline.py:215–216`, new `elo_provenance` kwarg at `pipeline.py:149/153`):

- `coverage` (int) — teams whose rating is genuine ClubElo data
  (present in `elo_ratings` **and** `!= DEFAULT_ELO`, membership not `.get`),
- `coverage_total` (int, 36),
- `coverage_pct` (float, 1 dp),
- `provenance` — `"clubelo"` | `"coefficient_derived"` | `"unavailable"`.

Provenance **gates** the count: `coverage=0` whenever provenance is
`coefficient_derived` or `unavailable` (coefficient values 1400–1800 are never ClubElo).
`rolling_form` and the simulation branch (`orchestrator.py:1193+`) are intentionally
untouched — no coverage keys. Per-match `n_matches`/`available`/`available_pct`
semantics unchanged.

### API surface

- `GET /api/signals` (`ucl_app.py:680–682`) serves `cache.get("signals", {})`
  **verbatim** — no stripping. Verified live for both seasons.
- `GET /api/data` (`ucl_app.py:478–506`) carries refresh/teams/phase/season metadata
  and does **not** embed a `signals` dict. ⚠️ **Report correction:** Agent C's write-up
  stated `/api/data` passes `cache["signals"]` through verbatim — that is not accurate.
  No behavioral defect (the UI sources signals from `/api/signals`; see below), flagged
  for accuracy only.
- Overview "Signal Availability" table (`ucl.js:334–340`) renders each signal in
  `sigOrder` (incl. `refined_elo`, `ucl.js:22`) through `_signalStatusCell(s)`. The
  rendered cell derives from the **same** dict `/api/signals` serves
  (`reloadData`/`loadAll` → `appState.signals = sig.signals`, `ucl.js:142/200` →
  `renderOverview` → `_signalStatusCell(signals[sk])`).

### Render logic — `_signalStatusCell` (`ucl.js:258–277`)

| Case | Rendered cell |
|---|---|
| signal `undefined`/`null` | red dot "No" |
| provenance `coefficient_derived` | green "Yes" + "Offline coefficient estimates — no ClubElo ratings" |
| coverage fields present, `coverage_pct < 100` | green "Yes" + "`22/36 teams rated (61.1%); remaining use a neutral baseline (1500), not ClubElo data`" |
| coverage present, pct == 100 (full) | clean green "Yes" |
| no coverage fields (legacy / other signals) | prior behavior: clean green "Yes" |

Edge cases driven in Node against a faithful copy of the helper (7/7 correct):
`coverage:0` + `provenance:"clubelo"` → "0/36 teams rated (0.0%)…" (honest, no
fabrication); pct `100` → clean "Yes"; legacy dict → clean "Yes"; `undefined` → "No".

No case renders 1500.0 or coefficient-derived values as ClubElo, and no case prints a
bare misleading "100%".

## 4. Tests

Focused (C10 + affected + Exchange-9 web-refresh files):

- `python -m pytest competitions/ucl/tests/test_orchestrator.py -q` → **11 passed**
  (8 new Exchange-10 tests + 3 pre-existing).
- `python -m pytest competitions/ucl/tests/test_provider.py competitions/ucl/tests/test_simulation.py competitions/ucl/tests/test_season_draw.py tests/test_ucl_refresh_season_scoped.py tests/test_ucl_future_season_empty_provider.py -q` → **83 passed, 1 skipped** (Exchange-9 refresh files keep passing).
- `python -m pytest competitions/ucl/tests/ tests/ -q` (remaining) → **732 passed**.

Full suite: `python -m pytest -q` → **1230 passed, 1 skipped** (95.59s). **0 new
failures.**

Delta attribution: **+8** from Agent A's new test functions in `test_orchestrator.py`
(2 shell coverage + 2 completed-season coverage + 4 boundary/provenance). Agent C's
`ucl.js` render change adds **+0** pytest tests (verified separately via the Node drive
above); the pytest-delta baseline of 1222 passed / 1 skipped is Agent A's measured
pre-change count and is consistent with 1230 = 1222 + 8.

## 5. HTTP/API verification (strict timeouts, all steps completed)

Timestamps UTC; TestClient runs in-process (no bound server, no lingering processes);
runtime files restored byte-exact afterwards.

1. **Preflight** — `http://api.clubelo.com/2026-08-30` → `HTTP 200` (ClubElo reachable;
   snapshot data present). Runtime files `competitions/ucl/data/current.json`,
   `web/last_refresh.json`, `competitions/ucl/data/seasons/2026_27/results.json`
   backed up to temp (gitignored runtime state).
2. **2026/27 live** (11:23:24Z) — `GET /ucl/api/signals` served the exact payload above:
   `coverage:22, coverage_total:36, coverage_pct:61.1, provenance:"clubelo"`. In-process
   `cache["elo_ratings"]`: 36 teams, **14 at exactly 1500.0, 22 resolved** (matches the
   Exchange-9 baseline 22/36). `refresh` was `deferred` / `provider_empty`.
3. **Season switch → 2025/26** (11:23:26Z) — `POST /ucl/api/season {"season":"2025/26"}`
   → 200; `GET /ucl/api/signals` served `coverage:36, coverage_total:36,
   coverage_pct:100.0, provenance:"clubelo"`; `cache["elo_ratings"]` 36 teams, **0 at
   1500.0**; `/api/data` n_played=144. UI cell for this payload (Node-driven) = clean
   "Yes".
4. **Switch back → 2026/27** (11:23:26Z) — `POST /ucl/api/season {"season":"2026/27"}`
   → 200; `GET /ucl/api/data` refresh block unchanged-in-spirit from Exchange 9:
   `{attempted:true, success:true, stale:false, deferred:true, reason:"provider_empty",
   status:"deferred", active_season:"2026/27", n_matches:0}` and `/api/signals` again
   served 22/36 clubelo. **Per-season refresh scoping regression: none.**
5. **Cleanup** — `current.json`, `last_refresh.json`, `seasons/2026_27/results.json`
   restored from backup; SHA-256 **byte-exact before/after for each**. `git status --short`
   identical to the pre-verification state.

## 6. Remaining legitimate coverage gaps

1. **14/36 at the 1500.0 DEFAULT_ELO floor in 2026/27** (observed in the fetch log;
   all 14 have no alias entry and their exact full display names are not valid ClubElo
   CSV keys / history hits): AEK Athens, Bayern Munich, Bodø/Glimt, Borussia Dortmund,
   Fenerbahçe, Inter Milan, Manchester City, Manchester United, Paris Saint-Germain,
   PSV Eindhoven, Real Betis, Shakhtar Donetsk, Sporting CP, VfB Stuttgart. Reasons,
   within the no-invented-aliases constraint: (a) **Bodø/Glimt** — `ø` (U+00F8) has no
   NFKD decomposition, so the accent-insensitive fallback cannot match it; (b)
   **Fenerbahçe** — no reachable alias key to the ASCII form; (c) **~12 structural
   full-name-vs-short-key mismatches** (e.g. "Bayern Munich" vs ClubElo "Bayern",
   "Manchester City" vs "Man City", "Inter Milan" vs "Inter", "Paris Saint-Germain" vs
   "Paris SG", "Real Betis" vs "Betis", "Brugge" handled, etc.). This is why the
   per-team coverage is 22/36 while the per-match `available_pct` is 100.0.
2. **`available_pct = 100.0` note** — per-match signal *availability* (a probability
   exists for every one of the 144 drawn fixtures) must not be read as per-team data
   *coverage*. The UI now surfaces both semantics separately (per-match count is
   `n_matches`/`available`/`available_pct`; coverage is `coverage`/`coverage_total`/
   `coverage_pct`/`provenance`), and never prints the bare "100%" as coverage.
3. **Live-snapshot date-dependence** — `get_clubelo_snapshot_date()` = today; the
   coverage count is a function of the daily ClubElo CSV (expired rankings fall out).
4. **Rare genuine-1500 collision** — a real ClubElo rating of exactly 1500.0 would be
   treated as unresolved under `clubelo` provenance. Known documented edge
   (`compute_elo_coverage` docstring and boundary tests), accepted.

## 7. Conflict & correctness review outcome

- **No file overlap between Agent A and Agent C.** A: `competitions/ucl/src/orchestrator.py`,
  `competitions/ucl/src/pipeline.py`, `competitions/ucl/tests/test_orchestrator.py`. C:
  `web/static/ucl.js`. `web/ucl_app.py` diff is entirely Exchange-9 per-season refresh
  work — **no C10 changes needed there**, confirmed. `shared.js`/`shared.css` additions
  (`.acq-notice-line`, deferred-notice rendering) are Exchange-9 deferred-UI, not C10.
  `pipeline.py` carries both an Exchange-9 hunk (provider-empty `deferred` in
  `fetch_live_data`) and the Exchange-10 coverage hunk — consistent with the task
  baseline.
- **Correctness:** `compute_elo_coverage` counts via membership + `!= DEFAULT_ELO`,
  gated by provenance (coefficient/unavailable → 0); schema matches the spec card;
  `rolling_form` and the simulation branch untouched. `_signalStatusCell` matches
  Agent B's copy guidance and has no dishonest render case.
- **Defect found (reporting-level only):** Agent C's claim that `/api/data` passes the
  signals dict verbatim is inaccurate — `/api/data` has no `signals` field; the render
  consumes `/api/signals`. No code change made; behavior unaffected.

## 8. Acceptance mapping (1–6)

1. **VERIFIED** — No hardcoded `144`/`100.0` refined_elo *coverage* claim survives in
   orchestrator.py / pipeline.py / ucl.js / shared.js / ucl_app.py. The surviving
   `n_matches=144, available_pct=100.0` (orchestrator.py:917, 933) is per-match signal
   availability (B's semantics), and the UI now shows per-team coverage separately —
   never a bare misleading "100%".
2. **VERIFIED** — 2026/27 measured coverage actually served at runtime: **22/36,
   61.1%, provenance `clubelo`** (live fetch; see §5). Also verified the rendered cell
   drives from those fields.
3. **VERIFIED** — `POST /ucl/api/season {"season":"2025/26"}` → served `coverage=36/36,
   coverage_pct=100.0, provenance=clubelo`; rendered cell = clean "Yes".
4. **VERIFIED** — Coverage counts only real values, provenance gates the count
   (coefficient path → 0), and `_signalStatusCell` never labels 1500/coefficient values
   as ClubElo (Node-driven edge cases include `coverage=0` clubelo).
5. **VERIFIED** — Full suite exact: **1230 passed, 1 skipped**, 0 new failures.
6. **VERIFIED (with correction)** — Served `refined_elo` dict and the rendered cell
   derive from the same payload (`/api/signals` → `appState.signals` →
   `_signalStatusCell`); `/api/signals` and the Overview table agree with the underlying
   signal state. (/api/data does not carry the signals dict — corrected claim, no
   defect.)

## 9. Remaining issues list

- None blocking. The non-live (coefficient-derived / 0-coverage) rendering path is
  unit-verified only; the live 22/36 clubelo path is the one observed end-to-end and
  will flip depending on ClubElo reachability at run time.
- Claimed-but-corrected: `/api/data` signals pass-through wording (Agent C).