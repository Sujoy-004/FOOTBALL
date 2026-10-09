---
phase: 02-truthful-availability-explicit-verified-ingestion
plan: 09
subsystem: acquisition
tags: [signal-caches, ingest, odds, rolling-form, squad-value, rest-days, d-02, d-08, d-10, d-20, ttl, offline]

# Dependency graph
requires:
  - phase: 02-truthful-availability-explicit-verified-ingestion
    provides: 02-06 OQ7 results stage row + IngestReport serving (one stages list per report), 02-02 counter contract + derive_success (D-13), 02-04 atomic-writer hardening, 02-07 truthful availability semantics, 01-06 deleted-worldcup-predictors parity recipe (tests/test_predictors_removal_parity.py:_write_deleted_stage_caches)
provides:
  - competitions/worldcup/src/signal_caches.py — four producer functions (produce_odds_cache / produce_rolling_form_cache / produce_squad_value_cache / produce_rest_days_cache) + produce_signal_caches orchestrator, each returning a truthful {key,label,state,count,detail} stage row
  - One WC fetch_live_data pass now appends four signal-cache rows after the results row (live) or four not-attempted rows (snapshot), and records actually-written cache paths in report.written_files
  - Engine-consumable caches written in the exact parity recipe shape so build_engine_from_caches blends real per-match probabilities (D-10)
affects:
  - Any future writer/reader of the four WC signal caches; 02-10's endpoint-side written_files/freshness surfacing; the WC engine's blend inputs

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-producer fail-soft: every producer folds exceptions into an error row and never aborts the refresh; the engine's fail-fast contract is untouched (D-13: stages never feed success)"
    - "Call-time credentials: os.environ (ODDS_PROVIDER) is read ONLY inside the odds producer's live branch, never at import (14-rule zero-boot-call policy)"
    - "Injected fetch seam: fetch_fn lets tests drive the odds producer with BSD-shaped events without any network/API key"
    - "Snapshot branch publishes four truthful not-attempted rows and touches neither disk nor network"

key-files:
  created:
    - competitions/worldcup/src/signal_caches.py
    - tests/test_signal_cache_producers.py
  modified:
    - competitions/worldcup/src/pipeline.py
    - tests/test_refresh_endpoint_contract.py

key-decisions:
  - "produce_signal_caches is the single brain-owned orchestrator invoked inside fetch_live_data; it runs the four producers in fixed order (odds, rolling_form, squad_value, rest_days) with per-producer try/except, collecting written paths into an optional out-list (D-02 single pass, D-08 boundary)"
  - "The odds producer reads ODDS_PROVIDER at call time via resolve_odds_provider; an unset/empty mode yields provider=None -> row state 'unavailable' detail 'no odds provider configured' and NO cache write (never an ok row over an empty result)"
  - "A cache is only saved when its parsed matches dict is non-empty, so an empty provider response can never clobber a valid cache (T-09-T); TTL-fresh caches are skipped with count:None and a 'fresh' detail (T-09-R)"
  - "report.written_files is now populated from the paths the producers actually wrote this pass; the endpoint layer stays untouched (02-06 deferred the pass-through to 02-09/02-10)"
  - "web/wc_app.py was NOT modified: 02-06 placed the results stage builder in the brain pipeline, so the four cache rows are appended to the same stages list there (one stages list per report)"

patterns-established:
  - "Truthful multi-row acquisition report: results row first, then one row per derived cache, each naming what it did"
  - "Offline-testable producer with injected transport (fetch_fn) and caller-supplied now for deterministic TTL checks"

requirements-completed:
  - INGEST-01
  - INGEST-02

# Metrics
duration: ~35min active
completed: 2026-10-09
---

# Phase 02: Truthful Availability & Explicit Verified Ingestion — Plan 09 Summary

**World Cup refresh now writes its four engine signal caches (odds, rolling form, squad value, rest days) in the SAME explicit acquisition pass that ingests results, each emitting a truthful stage row, with snapshot mode reporting four not-attempted rows and writing nothing — demonstrated to change the ensemble's blended probabilities (D-10).**

## Performance

- **Duration:** ~35 min active (first RED commit 08:11:18 → final commit 08:36:06, all 2026-10-09 +05:30)
- **Started:** 2026-10-09T08:11:18+05:30 (task 1 RED commit)
- **Completed:** 2026-10-09T08:36:06+05:30
- **Tasks:** 3 (all auto; tasks 1–2 TDD, task 3 verification)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- **Four producers implemented** in the WC brain (`competitions/worldcup/src/signal_caches.py`) using the parity recipe as ground truth: `RollingFormSignal(windows=[5], decay_factor=0.9)` over a promoted `_FixtureResultsProvider`, `SquadValueSignal` over `team_values.json`, `RestDaysSignal`, and the kernel odds layer (`fetch_and_cache_odds`) — all writing the exact `{fetched_at, expires_at, matches}` shape `build_engine_from_caches` consumes.
- **Single-pass wiring (D-02/D-08):** `fetch_live_data` live success path prepends the 02-06 results row and appends the four cache rows to ONE stages list; the snapshot early-return appends four truthful not-attempted rows. `_build_report` gained an optional `written_files` argument so the report records what was actually written.
- **Truthful degradation:** no odds provider → `unavailable` + short reason, no write; a parsed-empty odds result → no clobber; a TTL-fresh cache → `count: None` with a freshness detail; any producer exception → an `error` row (proven by a dedicated failure-isolation test) and results ingestion is never aborted (T-09-D).
- **D-10 pickup proof:** a test builds the engine from an empty-cache dir (base Elo only), runs the three local producers, rebuilds, and asserts the blended vector for the same fixture CHANGES; a second assertion shows the odds signal participates only once an injected odds cache exists.
- **No-network guarantees:** snapshot mode writes zero files and reads no env (asserted); a structural AST test asserts no module-level `os.environ`/transport access in `signal_caches.py` (credentials are call-time only).
- **Parity untouched:** `tests/test_predictors_removal_parity.py` remains the independent cross-check and passed unmodified (13 tests).
- **Architecture guards green:** layering (no `football_core` additions) and the atomic-write ban (all writes go through `save_signal_cache` → `_atomic_write_json`) both pass; `ruff check competitions/worldcup/src tests` clean.

## task Commits

Each task was committed atomically:

1. **task 1: the four producers in signal_caches.py (RED)** — `3ceb0af` (test) — 7 failing producer tests
2. **task 1: the four producers in signal_caches.py (GREEN)** — `5caa39a` (feat) — `signal_caches.py`
3. **task 2: wire producers into the WC acquisition pass (RED)** — `f2afff5` (test) — fetch-level cache-row tests + contract-test additions
4. **task 2: wire producers into the WC acquisition pass (GREEN)** — `bf5c36b` (feat) — `pipeline.py` wiring
5. **task 3: engine pickup proof + D-10 gate sweep** — `105f9bc` (test) — D-10 pickup proof
6. **task 3 (coverage): producer failure isolation (T-09-D)** — `dc7c9f7` (test)

**Plan metadata commit:** `docs(02-09): add plan summary` (this SUMMARY only)

## Files Created/Modified

- `competitions/worldcup/src/signal_caches.py` (created) — module docstring (D-08/D-20 boundary, no import-time network); `_load/_clamp/_match_date/_wrap/_available/_unavailable/_signal_matches` helpers; promoted `_FixtureResultsProvider`; `_produce_odds_cache`/`_produce_rolling_form_cache`/`_produce_squad_value_cache`/`_produce_rest_days_cache` (each returns `(row, written_path|None)`) with thin public wrappers; `_snapshot_rows()`; `produce_signal_caches(data_dir, *, now, mode, fetch_fn=None, written_files=None)`.
- `competitions/worldcup/src/pipeline.py` (modified) — `_build_report(..., written_files=None)`; snapshot branch appends `produce_signal_caches(..., mode="snapshot")` rows; live success branch calls `produce_signal_caches(..., mode="live", written_files=[...])` and builds `stages=[_results_stage_row(...), *cache_rows]`; lazy `from src.signal_caches import produce_signal_caches` in both branches (no new `noqa: PLC0415`; ratchet stays 2).
- `tests/test_signal_cache_producers.py` (created) — 11 tests: local producer shape; squad-value missing-team unavailable; TTL skip/recompute; odds no-provider writes nothing; odds injected events (finished skipped); snapshot four not-attempted rows; no import-time credential/network access (AST); fetch-level live rows + written files; snapshot fetch rows + zero writes; D-10 engine pickup; producer failure isolation (T-09-D).
- `tests/test_refresh_endpoint_contract.py` (modified) — `_assert_report_shape` count check relaxed to `int | None` (rows must be able to carry `count: None`); WC snapshot-mode test extended to assert the four `signals.*` keys are present and all rows are `unavailable`/`count is None`.

## Decisions Made

See key-decisions frontmatter. Notable: per-producer fail-soft with an out-list for written paths; the odds provider resolved at call time with a truthful `unavailable` row (never an empty ok); save-only-when-non-empty; `report.written_files` populated from real writes; `web/wc_app.py` deliberately untouched because 02-06 sited the stage builder in the pipeline.

## Deviations from Plan

**None** — the plan executed as written. Two in-mandate test adjustments (not deviations) are noted for the record:

- Task 2's behavior list explicitly authorizes extending `tests/test_refresh_endpoint_contract.py` with row-expectation additions; relaxing the `count` type check to `int | None` is required by the new truthful rows (count omitted on skip/unavailable) rather than a weakening of the contract.
- Task 3's STRIDE register claims T-09-D is "tested by the live-pass test with injected failure"; that test was added explicitly (`dc7c9f7`) so the declared mitigation has direct coverage.

## Issues Encountered

- **Gate reconciliation (failing set did NOT grow because of 02-09).** Full-suite gate command `python -m pytest -q --tb=no -p no:cacheprovider` → **84 failed, 1851 passed, 10 skipped, 2 errors (1947 collected)**. Diffed against `02-01-BASELINE.md` (109 nodes) the set SHRANK by 23; 17 nodes appear that the frozen 02-01 list predates. Every one of the 17 is outside 02-09's files and caused by pre-existing conditions, not this plan:
  - The three WC-relevant ones fail identically with `pipeline.py` reverted to the pre-02-09 revision (proven by temporary checkout + restore): `tests/test_architecture_idempotency.py::test_wc_end_to_end_ingestion_is_idempotent` and `tests/test_architecture_resilience.py::test_wc_stale_undecided_provider_cannot_wipe_penalty_decisions` are the 02-02 Decision B follow-up already recorded in `STATE.md`; `tests/test_truth_ingestion.py::test_wc_completed_result_completeness_104` is gitignored runtime-data drift (`competitions/worldcup/data/played_groups.json` holds 108 placeholder entries, mtime 2026-08-10).
  - The remaining 14 are UCL `test_lifecycle`/`test_state_ucl`, `test_season_transition`, and `test_ucl_future_season_empty_provider` additions from plans 02-02…02-08; none import or exercise the WC signal-cache path. The live gate reference in `STATE.md` (98 failed + 2 errors) is itself superseded downward by this run.
- **Process note:** an early attempt to prove the above checked out `pipeline.py` at `HEAD~2` while the GREEN edit was still uncommitted, which discarded it; the wiring was re-applied and committed as `bf5c36b` before any further destructive step. No production change was lost in the final tree.
- **Changed test expectations (no production pins moved):** only `tests/test_refresh_endpoint_contract.py` (count type + WC snapshot rows, `f2afff5`). No existing probability/behavior pin required updating — producers only write on an explicit fetch with no keys in env.

## User Setup Required

None — no external service configuration required. The odds producer degrades to `unavailable` without `ODDS_PROVIDER` (offline/snapshot mode is fully supported).

## Next Phase Readiness

- INGEST-01/INGEST-02's consolidated refresh report now covers results PLUS the four derived caches; `report.written_files` is populated for the endpoint layer to surface (02-06 deferred pass-through to 02-09/02-10).
- The WC engine now has real cache inputs in production shape; any future non-uniform blend simply reads what `fetch_live_data` wrote.
- Remaining phase work (02-10) can wire `written_files`/freshness through the endpoint without touching the producers.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-09-S mitigated | competitions/worldcup/src/signal_caches.py | Odds key never read at import and never placed in a row `detail`; no-provider detail is the constant "no odds provider configured"; offline tests assert no key-shaped strings |
| T-09-T mitigated | competitions/worldcup/src/signal_caches.py | `save_signal_cache` is called only when the parsed `matches` dict is non-empty — an empty provider response cannot clobber a valid cache |
| T-09-D mitigated | competitions/worldcup/src/signal_caches.py | Per-producer try/except folds a crash into an `error` row; results rows and counter-derived success are untouched; covered by `test_crashing_producer_becomes_error_row_and_never_raises` |
| T-09-R mitigated | competitions/worldcup/src/signal_caches.py | TTL freshness via `is_cache_valid` with `count: None` + "fresh" detail; snapshot rows are `unavailable`, never `ok` |
| T-09-E mitigated | competitions/worldcup/src/signal_caches.py | No module-level `os.environ`/transport access (AST test); snapshot mode touches neither disk nor env; boot paths unchanged |

## Self-Check

PASSED — Commits `3ceb0af`, `5caa39a`, `f2afff5`, `bf5c36b`, `105f9bc`, `dc7c9f7` present in `git log`; `competitions/worldcup/src/signal_caches.py` and `tests/test_signal_cache_producers.py` exist; `python -m pytest tests/test_signal_cache_producers.py tests/test_refresh_endpoint_contract.py tests/test_predictors_removal_parity.py -q` → 33 passed; `ruff check competitions/worldcup/src tests` clean; layering + atomic-write-ban + parity guards green; full-suite failing set shrank vs baseline with zero 02-09-caused growth.

---

*Phase: 02-truthful-availability-explicit-verified-ingestion*
*Completed: 2026-10-09*
