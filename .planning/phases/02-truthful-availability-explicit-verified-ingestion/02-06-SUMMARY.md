---
phase: 02-truthful-availability-explicit-verified-ingestion
plan: 06
subsystem: acquisition/ingestion
tags: [lazy-read-path-removal, refresh-endpoints, ingest-report-contract, stage-rows, preload, registry-delegation]
tech-stack: [python, fastapi, pytest, fastapi-testclient, ruff]
key-files:
  created:
    - tests/test_refresh_endpoint_contract.py
  modified:
    - web/competitions.py
    - web/wc_app.py
    - web/ucl_app.py
    - web/laliga_app.py
    - web/common.py
    - web/server.py
    - web/startup.py
    - competitions/worldcup/src/pipeline.py
    - competitions/laliga/src/pipeline.py
    - tests/test_scoped_acquisition.py
    - tests/test_ucl_refresh_season_scoped.py
    - tests/test_hard02_swallow_sites.py
    - tests/test_hard03_staleness.py
decisions:
  - "All three refresh endpoints answer HTTP 200 for both success and failure: the report body carries success/error, HTTP status stays transport (plan allowed either; no test or consumer in the repo relied on 503)"
  - "Endpoint bodies are derived BY refresh_response_body() FROM the IngestReport - status, refreshed, deferred and last_success_at are computed from the report's own fields, never a parallel ad-hoc shape, and body['deferred'] is forced to agree with the derived status"
  - "Endpoints delegate through REGISTRY.get(id).refresh() with function-level imports, never a direct private _fetch_live_data import from another app module (per-competition scoping stays with the adapter; matches the plan's key-link pattern REGISTRY\\.get\\()"
  - "written_files stays [] at the endpoint layer - passing through brain-written file lists would disclose absolute paths to untrusted clients, so the endpoint fills the key and 02-09/02-10 wire real values if a consumer needs them"
  - "No endpoint-level snapshot short-circuit: the wrappers already self-gate, so the plan's sketch branch was redundant (single source of truth beats a second gate)"
  - "Status derivation: not attempted -> skipped; success -> ok; attempted+failed+deferred -> deferred; else error. A brain-supplied transport 'status' is intentionally NOT preserved because it can contradict success (D-13)"
  - "Stage-row builders added to the WC and LaLiga pipelines only; UCL's existing stages (teams/league/playoff/knockout/champion) are untouched per OQ7 - so the contract test asserts a 'results' row for WC/LaLiga only"
  - "Contract-test success-path scoping: genuine UCL/LaLiga success needs gitignored runtime stores this environment lacks, so success is proven end-to-end for WC over HTTP plus a refresh_response_body unit test, while snapshot/attempt/raising/read-purity cover all three apps"
patterns-established:
  - "Single refresh contract: every /api/refresh response is refresh_response_body(report) - the IngestReport key set, always, in every mode"
  - "Registry delegation: HTTP triggers call REGISTRY.get(id).refresh(); the adapter is the only thing allowed to know a competition's provider"
  - "Throwaway data dirs in tests: any test that refreshes copies the app's DATA_DIR to tmp and monkeypatches it - a refresh test must never rewrite tracked stores"
requirements-completed: [INGEST-01, INGEST-02]
metrics:
  duration: ~175min
  completed_date: 2026-10-08
  tasks_completed: 3/3
---

# Phase 02 Plan 06: D-03 Read-Path Removal & Refresh Contract Summary

## One-liner

D-03's lazy read path is deleted (boot and every plain read make zero provider calls, proven by counting providers on all three apps), World Cup gained its first `POST /worldcup/api/refresh`, and all three refresh endpoints now answer with the brain's full IngestReport body instead of `{"status":"ok"}` — with `FOOTBALL_PRELOAD_ALL=1` preload still the sanctioned boot exception.

## Performance

- **Duration:** ~175 min
- **Started:** 2026-10-08T08:20:34Z
- **Completed:** 2026-10-08T11:19:01Z
- **Tasks:** 3/3
- **Files modified:** 14 (1 created)

## Task Breakdown

| task | name | commit | files |
|---|---|---|---|
| 1 | remove D-03's read path + rewrite the tests that encode it | `a95f122` | `web/competitions.py`, `web/ucl_app.py`, `web/laliga_app.py`, `web/wc_app.py`, `web/common.py`, `web/server.py`, `web/startup.py`, `tests/test_scoped_acquisition.py`, `tests/test_ucl_refresh_season_scoped.py`, `tests/test_hard02_swallow_sites.py`, `tests/test_hard03_staleness.py` |
| 2 | WC refresh endpoint + full-report contract on all three apps | `0274c32` | `web/wc_app.py`, `web/ucl_app.py`, `web/laliga_app.py`, `web/common.py`, `web/competitions.py`, `competitions/worldcup/src/pipeline.py`, `competitions/laliga/src/pipeline.py`, `tests/test_refresh_endpoint_contract.py` (new) |
| 3 | read-path removal regression sweep + preload coverage | `58dbec5` | `tests/test_scoped_acquisition.py` |

**Plan metadata:** docs commit at the end of this file's execution.

## What Is Now True

- **Roadmap criterion 2 is fully true (INGEST-01).** `try_lazy_refresh`, the `@subapp.middleware("http")` shim and both direct `api_data` call sites are gone — `Select-String try_lazy_refresh web\*.py tests\*.py` returns zero hits. `tests/test_scoped_acquisition.py::test_boot_makes_zero_provider_calls_without_preload` boots the real lifespan with both counting providers armed → `calls == 0`, and `test_plain_reads_make_zero_provider_calls` drives `GET /{worldcup,ucl,laliga}/api/data` → `calls == 0`, then an explicit `REGISTRY.get("ucl").refresh()` → `ucl_prov.calls >= 1, wc_prov.calls == 0` (scope isolation preserved).
- **The only ingest trigger is an explicit per-competition refresh.** Endpoint (`POST /{comp}/api/refresh`), `FOOTBALL_PRELOAD_ALL=1` preload, or a test — nothing else reaches a provider. `tests/test_scoped_acquisition.py::test_preload_all_refreshes_each_adapter_once_and_consumes_gates` wraps the frozen adapters at class level and proves `_preload_registered_competitions()` refreshes each registered competition exactly once and calls `consume_lazy_gate` for each (mirroring `web/server.py:86-99`, which is untouched).
- **World Cup has its first HTTP refresh route (CS-2).** `web/wc_app.py::api_refresh` → `REGISTRY.get("worldcup").refresh()`, then recompute the served cache. Verified end-to-end over TestClient: 200, full report, `finished` counters, `stages[0].key == "results"`, `last_success_at` ISO-8601 with `Z`.
- **Roadmap criterion 3's response clause is true for every competition (INGEST-02).** One shape, one function: `web/common.py::refresh_response_body(report, mode=...)` guarantees the full IngestReport key set (`provider, attempted, success, error, stale, last_success_at, finished, stages, written_files, deferred, reason, mode, refreshed, status, last_refresh`) and derives `status/refreshed/deferred/last_success_at` from the report itself. Snapshot mode answers the same schema with `attempted: false` and a snapshot reason — never `{"status":"skipped"}`. The opaque `{"status":"ok","refreshed":true}` bodies are gone from all three apps.
- **Results stage rows exist on every report (OQ7).** `_results_stage_row` in `competitions/worldcup/src/pipeline.py` (success → `ok` with ingested count, `_fail` → `error` with the reason) and `competitions/laliga/src/pipeline.py` (success/fail → `ok`/`error`, no provider → `unavailable`, fetch error → `error`); UCL's existing stages untouched. Unit tests pin row vocabulary (`key/label/state/count/detail`, `state` in `ok|pending|error|unavailable`), not exact counts.
- **Read purity after the removal is pinned both ways.** `tests/test_refresh_endpoint_contract.py` (15 tests) drives snapshot / canned-payload / raising-provider / plain-read for each of the three apps over HTTP; `tests/test_scoped_acquisition.py` keeps boot + read + scope + never-raises + offline coverage.

## Verification Results

| gate | command | result |
|---|---|---|
| Task 1 gate | `pytest tests/test_scoped_acquisition.py tests/test_always_on_acquisition.py tests/test_ucl_refresh_season_scoped.py tests/test_ucl_presentation_contract.py -q` | 31 passed, 4 failed — all 4 already in `fails_current_full.txt` |
| Task 1 grep gate | `Select-String -Path web\*.py,tests\*.py -Pattern try_lazy_refresh` | 0 hits ("try_lazy_refresh fully removed") |
| Task 2 gate | `pytest tests/test_refresh_endpoint_contract.py tests/test_scoped_acquisition.py tests/test_architecture_isolation.py -q` | 27 passed, 2 skipped |
| Task 3 sweep (plan action) | `pytest tests/ -k "acquisition or refresh or scoped or presentation or boot or preload or truth or resilience or isolation" -q` | 116 passed, 11 failed + 1 error — all 12 in baseline |
| Task 3 verify gate (plan verify) | `pytest tests/ -k "acquisition or refresh or scoped or presentation or truth" -q` | 93 passed, 8 failed + 1 error — all in baseline |
| Task 3 full-gate check 1 | `pytest tests/test_refresh_endpoint_contract.py tests/test_always_on_acquisition.py tests/test_architecture_resilience.py tests/test_architecture_idempotency.py -q` | 29 passed, 3 failed — all in baseline |
| Task 3 full-gate check 2 (preload) | `$env:FOOTBALL_PRELOAD_ALL='1'; pytest tests/test_always_on_acquisition.py -q` | 10 passed, 1 failed — baseline failure, flag adds none |
| Full suite (final) | `python -m pytest -q --tb=no -p no:cacheprovider` (capture script → temp output) | 1829 passed, 82 failed + 2 error = **84 — set identical to baseline: 0 new, 0 gone** |
| Lint | `ruff check web competitions tests` | clean |
| Contract tests | `pytest tests/test_refresh_endpoint_contract.py -q` | 15 passed, working tree clean afterwards |

## Decisions Made

1. **HTTP 200 always.** The plan offered "200 with truthful body, unless a failure currently returns 503 and consumers rely on it". Nothing in the repo does (grep for 503 found no test/consumer), so every mode returns 200 and the body carries `success`/`error` — truthful failure is data, not a transport error. 503 remains reserved for `error_response` (unexpected exceptions).
2. **Derivation, not decoration.** `refresh_response_body` fills the entire key set from the report (`_zero_finished_counters` for the `finished` shape), converts `last_success_at` to `Z` and derives it from `last_refresh` on success, and computes `status` from `attempted/success/deferred`. `body["deferred"]` is overwritten to match the derived status so the flag and status can never disagree.
3. **Registry delegation with function-level imports.** `from web.competitions import REGISTRY` inside each `api_refresh` avoids cross-app private imports and satisfies the plan's key-link pattern while `tests/test_architecture_isolation.py` stays green.
4. **`written_files: []` at the edge.** Documented under Known Stubs.
5. **No endpoint snapshot branch.** The adapter wrappers already self-gate, so the plan's sketch short-circuit would have been a second source of truth.
6. **`status` is derived, never forwarded.** A brain-supplied transport `status` is discarded because it could contradict `success` (D-13); `test_refresh_response_body_is_self_consistent` pins agreement.
7. **`tests/test_ucl_refresh_season_scoped.py::_explicit_refresh()` stays on `REGISTRY.get("ucl").refresh()`** — the plan explicitly allows either it or `POST /ucl/api/refresh`, so no switch was needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] LaLiga adapter served `{}` instead of its report**
- **Found during:** task 2 (endpoint normalization)
- **Issue:** `laliga_refresh()` returned `dict(laliga_app._fetch_live_data() or {})`, but `_fetch_live_data` records into `laliga_app._refresh_report` and returns `None` → the endpoint would have answered an empty body.
- **Fix:** call the app's ingest path and read back `_refresh_report`.
- **Files modified:** `web/competitions.py`
- **Verification:** contract tests for LaLiga snapshot/attempt/raising all green
- **Committed in:** `0274c32`

**2. [Rule 1 - Bug] Refresh tests rewrote tracked LaLiga stores**
- **Found during:** task 2 (contract test), task 3 (preload test)
- **Issue:** an empty-payload ingest still re-serializes `competitions/laliga/data/seasons/2026_27/{fixtures,results}.json`, dirtying the working tree and failing 16 `test_laliga_parity` cases. A contract test must never mutate the data it inspects.
- **Fix:** `_sandbox_data_dir()` copies each app's `DATA_DIR` to `tmp_path` and monkeypatches the module global (plus the LaLiga ledger path); the two dirty files were restored with `git checkout -- <specific paths>`.
- **Files modified:** `tests/test_refresh_endpoint_contract.py`, `tests/test_scoped_acquisition.py`
- **Verification:** `git status --short -- competitions web` clean after the contract/scoped/preload runs; `tests/test_laliga_parity.py` 29/29 again
- **Committed in:** `0274c32`, `58dbec5`

**3. [Rule 3 - Blocking] `CompetitionAdapter` is a frozen dataclass**
- **Found during:** task 3 (preload test)
- **Issue:** instance-level `monkeypatch.setattr(adapter, "refresh", ...)` raised `FrozenInstanceError`.
- **Fix:** patch the class method with a counting wrapper that delegates to the captured original.
- **Files modified:** `tests/test_scoped_acquisition.py`
- **Verification:** 11/11 scoped tests green, preload test proves one refresh per adapter
- **Committed in:** `58dbec5`

**4. [Rule 3 - Scope] Touched files outside the plan's `files_modified` list**
- **Found during:** task 1 / task 2
- **Issue:** `web/common.py` (shared `refresh_response_body` / `offline_refresh_report` / `not_attempted_report` helpers), `web/startup.py`, `tests/test_hard02_swallow_sites.py`, `tests/test_hard03_staleness.py` had to change to hold the enumerated contract / reference the deleted symbols.
- **Fix:** kept — all are direct consequences of the enumerated read-path removal and endpoint normalization, no behavior beyond them (D-19).
- **Committed in:** `a95f122`, `0274c32`

**5. [Rule 3 - Scope] `tests/test_always_on_acquisition.py` listed but left unmodified**
- **Found during:** task 1 (step 3)
- **Issue:** the plan listed it in `<files>` but its cases are startup-decision tests, and its snapshot zero-network test already drives the refresh response explicitly — nothing encoded the deleted read path.
- **Fix:** reviewed, deliberately unchanged (scenario preserved without a rewrite).
- **Committed in:** n/a (no change needed)

---

**Total deviations:** 5 (1 auto-fixed bug, 1 auto-fixed test-isolation bug, 3 blocking/scope adjustments)
**Impact on plan:** all were required for correctness or were plan-sanctioned flexibility; no scope creep, no new features.

## Known Stubs

| stub | file | line/area | reason |
|---|---|---|---|
| `written_files` always `[]` on all three responses | `web/common.py::refresh_response_body` | key fill | Endpoint does not pass through the brains' `written_files` (absolute-path disclosure, no consumer yet). The plan's target contract itself shows `"written_files": []`. Wire-up owner: 02-09 / 02-10. |

No stub prevents this plan's goal: every other report key is populated from real data or a truthful default.

## Threat Flags

None — no new network/auth/file surface beyond `POST /worldcup/api/refresh`, which the plan's threat model already registers (`browser → POST /api/refresh`, T-06-D) and which is pinned by the counting-provider tests.

## Issues Encountered

- **PowerShell swallowed a multi-line `git commit -m`** (escaped double quotes split the argument) → retried with single-quoted `-m` strings; commit landed intact as `0274c32`.
- **Full suite exceeds the shell timeout** → ran it through a subprocess capture script writing to `%TEMP%\opencode\fails_post_02-06.txt`, so the baseline `fails_current_full.txt` was never overwritten; reconciliation done by set comparison, not exit code.
- **84 environment-dependent baseline failures** (missing gitignored runtime stores) mask pass/fail of several plan gates → every gate was reconciled against the baseline set ("shrink only"): full suite 84 → 84, identical members, 0 new.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **02-08 (dashboard refresh button)** can wire to `POST /{worldcup,ucl,laliga}/api/refresh` — three routes, one response contract, `mode` preserved as an extra key.
- **02-10 (INGEST-04)** is unblocked: World Cup is refreshable over HTTP, the last prerequisite.
- **02-09 / 02-10** own the remaining stage-row growth (signal-cache rows appended by 02-09, final completeness verified by 02-10) and the `written_files` stub.
- **Concern for the next verifier:** gates in this environment must be reconciled against `fails_current_full.txt` (84 baseline failures from missing gitignored stores) rather than pytest exit codes.

---
*Phase: 02-truthful-availability-explicit-verified-ingestion*
*Completed: 2026-10-08*

## Self-Check: PASSED

- 15/15 key files exist (14 modified + this SUMMARY)
- 3/3 task commits found in history: `a95f122`, `0274c32`, `58dbec5`
