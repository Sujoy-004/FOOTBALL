---
phase: 02-truthful-availability-explicit-verified-ingestion
plan: 05
subsystem: truthfulness/freshness
tags: [single-writer-ledger, swallow-ratchet, staleness, threading-lock, unreadable]
tech-stack: [python, pytest, threading, fastapi-testclient]
key-files:
  created:
    - football_core/freshness.py
  modified:
    - competitions/worldcup/src/pipeline.py
    - competitions/ucl/src/pipeline.py
    - web/wc_app.py
    - web/ucl_app.py
    - web/laliga_app.py
    - tests/test_hard03_staleness.py
    - tests/test_hard02_swallow_sites.py
    - tests/fixtures/deferred_non_atomic_writes.json
decisions:
  - "one module (football_core/freshness.py) owns every ledger read and write under a single module threading.Lock + atomic_write_text"
  - "unreadable ledger returns the sentinel {\"ledger\": \"unreadable\", \"detail\": <exception class name only>} - never {}, never a logged-and-swallowed failure, never the exception message"
  - "update_ledger accepts a competition key path (str | Sequence[str]) so UCL/LaLiga keep their nested (ucl_seasons, 2026/27) schema"
  - "D-12 staleness is served, not stored: served_stale() upgrades the in-memory refresh report, the ledger file itself is never rewritten by readers"
  - "store-path knowledge stays in the apps (_freshness_store_paths): played*/results/fixtures only - snapshot.json (simulated) and odds.json (refetched on demand) are excluded"
  - "the shared served-stale rule uses last_success_at OR last_refresh as the recorded instant, because the UCL/LaLiga ledger schema has no last_success_at and the strict rule would mark every report stale"
patterns-established:
  - "Single-writer file owner: readers call read_ledger(), writers call update_ledger(path, competition, report) - no other code touches the freshness ledger"
  - "Loud-failure vocabulary: an unreadable ledger is data (ledger: unreadable + detail), and the marker is never persisted back"
  - "Served-truth rule: _current_refresh_report/_refresh_report_for wrap ledger content in _freshness(entry, store_paths) before serving it"
requirements-completed: [HARD-02, HARD-03]
metrics:
  duration: ~80min
  completed_date: 2026-10-08
  tasks_completed: 3/3
---

# Phase 02 Plan 05: Single-Writer Freshness Ledger & D-12 Staleness Summary

## One-liner

`web/last_refresh.json` now has exactly one writer (`football_core/freshness.py` under one lock, atomic write, loud failure), every swallow on the ingestion/freshness path either reports `ledger: "unreadable"` or is on an explicitly sanctioned list, and every served refresh report re-evaluates D-12 staleness against the real store so a stale store can never read fresh.

## Performance

- **Duration:** ~80 min
- **Started:** 2026-10-08T12:18:00+05:30
- **Completed:** 2026-10-08T13:45:00+05:30
- **Tasks:** 3/3
- **Files modified:** 9 (1 created)

## Task Breakdown

| task | name | commit | files |
|---|---|---|---|
| 1 | single-writer ledger owner + D-12 staleness rule (TDD) | `2a73954` (RED) → `02047c3` (GREEN) | `football_core/freshness.py`, `tests/test_hard03_staleness.py`, `tests/fixtures/deferred_non_atomic_writes.json`, `competitions/worldcup/src/pipeline.py`, `web/ucl_app.py`, `web/laliga_app.py` |
| 2 | HARD-02 swallow-site ratchet + loud readers (TDD) | `fb545ea` (RED) → `f4da146` (GREEN) | `tests/test_hard02_swallow_sites.py`, `web/wc_app.py`, `web/ucl_app.py`, `web/laliga_app.py`, `competitions/worldcup/src/pipeline.py`, `competitions/ucl/src/pipeline.py` |
| 3 | wire staleness + loudness through served reports, sweep | `1d959fb` | `football_core/freshness.py`, `web/wc_app.py`, `web/ucl_app.py`, `web/laliga_app.py`, `tests/test_hard03_staleness.py`, `tests/test_hard02_swallow_sites.py` |

## What Is Now True

- **One writer, one lock (T-05-T).** `football_core/freshness.py` owns `update_ledger()` / `read_ledger()`; the four former read-modify-write sites (`competitions/worldcup/src/pipeline.py::_build_report`, `web/ucl_app.py::_store_refresh_report`, `web/laliga_app.py::_store_refresh_report`, plus the WC pipeline failure branch) all go through it. A single module-level `threading.Lock` guards read-modify-write, `atomic_write_text` writes the file, and any failure is `logger.exception(...)` then re-raise. 200 interleaved updates lose nothing.
- **Failures are loud (T-05-R).** The AST ratchet in `tests/test_hard02_swallow_sites.py` fails the build if a bare `except: pass` / `return {}` appears on the ingestion-ledger surface outside an exact, size-checked sanctioned list (8 entries, >30-char reasons: default-shape readers that are not on the ingestion path). The four former swallow readers (`wc_app::_read_unlocked`, `wc_app::_current_refresh_report`, `worldcup/src/pipeline.py::_read_prev_ledger`, `ucl_app`/`laliga_app::_load_refresh_ledger`) now return `read_ledger()`; `competitions/ucl/src/pipeline.py`'s bare `pass` on `fixtures.json` unreadable now logs a warning with the exception class name.
- **Unreadable is data, not silence.** A corrupt/non-dict ledger yields `{"ledger": "unreadable", "detail": "<exception class name only>"}` (T-05-I: class name, no message, so tokens/URLs cannot leak), served verbatim at `/api/data` and `/api/boot`; `update_ledger` never persists the marker. Missing file stays `{}` (a genuine empty ledger is not an error).
- **A stale store can never read fresh (T-05-S).** `served_stale(entry, store_mtimes)` implements D-12: missing/absent-or-unparseable recorded instant → stale; recorded instant older than `store_mtime - 1.0s` → stale; empty store list skips the mtime clause. `_freshness()` in `web/wc_app.py`, `web/ucl_app.py`, `web/laliga_app.py` wraps every served refresh block (`_current_refresh_report`, `_refresh_report_for`, `api_boot`) so the ledger file is never rewritten, only the served copy is upgraded to `stale: true`. Covering tests: 4 rule tests, 2 served-payload tests (WC store touched ahead of the ledger; UCL store moved on), 1 TestClient `/api/data` test.
- **Fixture integrity.** `tests/fixtures/deferred_non_atomic_writes.json` still exists with exactly 5 entries, all `Phase 3` (the four ledger entries were legitimately removed as they were converted).

## Verification Results

| gate | command | result |
|---|---|---|
| plan verification | `python -m pytest tests/test_hard02_swallow_sites.py tests/test_hard03_staleness.py tests/test_atomic_store_writes.py -q` | **28 passed** |
| task 3 verify + lint | `pytest .../test_architecture_resilience.py -q --tb=short && ruff check football_core web competitions tests` | 22 plan tests pass; **1 pre-existing failure** (see below); `ruff: All checks passed!` |
| reconciliation sweep | 6-file `--tb=line` run | `2 failed, 51 passed, 4 skipped` — 1 in `02-01-BASELINE.md`, 1 pre-existing data-drift |
| fixture | `assert len(d)==5 and all Phase 3` | passes |
| swallow proof | AST ratchet test `test_no_unsanctioned_swallow_on_the_ingestion_surface` | passes (no unsanctioned `except: pass` in the six scanned files) |

The two sweep failures are both out of scope and documented in `deferred-items.md` (items 3 and 5):

- `tests/test_architecture_resilience.py::test_wc_stale_undecided_provider_cannot_wipe_penalty_decisions` — the only node not in `02-01-BASELINE.md`. It asserts on the **gitignored live store** `competitions/worldcup/data/played.json`, which has drifted out-of-band (mtime 11:40, before this session started; 10 entries now lack `match_id`). Reproduced identically with this plan's uncommitted changes stashed; the assertion is reached before any application code runs.
- `tests/test_always_on_acquisition.py::test_auto_succeeding_provider_ingests_into_tmp_store` — already in `02-01-BASELINE.md` (line 82).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TestClient tests silently fired a real provider refresh into the repo store**
- **Found during:** task 3
- **Issue:** Starting `wc_app` in a `TestClient` while the lazy-acquisition middleware was live caused `try_lazy_refresh("worldcup")` to run a *real* `FootballDataOrgProvider` refresh (API keys present in `.env`) against the unpatched repo paths during a read-only test — observed rewriting `competitions/worldcup/data/played.json`, `played_groups.json` and `web/last_refresh.json`.
- **Fix:** Both TestClient tests now `monkeypatch.setattr(competitions, "try_lazy_refresh", lambda _cid: None)` before entering the client, and import `web.competitions` *before* the app first starts (Starlette freezes the middleware stack on first start). Re-run confirmed zero mtime movement on those three files.
- **Files modified:** `tests/test_hard03_staleness.py`, `tests/test_hard02_swallow_sites.py`
- **Commit:** `1d959fb`

**2. [Rule 1 - Bug] Middleware install order hazard (`RuntimeError: Cannot add middleware after an application has started`)**
- **Found during:** task 3
- **Issue:** `web/competitions.py` installs the lazy-acquisition hook at import (`REGISTRY = build_default_registry()` at line 364); if a sub-app has already been started once, the install raises and the hook is silently skipped — and importing it first flips every TestClient test into "real refresh" mode.
- **Fix:** in-scope half applied (import-before-start + disarm in this plan's tests); the defensive install itself is out of scope → logged as `deferred-items.md` item 4.
- **Commit:** `1d959fb`

**3. [Rule 2 - Correctness] Plan's `is_stale` wiring would have marked every UCL/LaLiga report stale**
- **Found during:** task 3
- **Issue:** The plan specifies `is_stale` keyed on `last_success_at`, but the UCL/LaLiga ledger schema only carries `last_refresh`; the strict rule would report stale for every healthy competition (a truthfulness regression in the opposite direction).
- **Fix:** shared `served_stale()` accepts `entry["last_success_at"] or entry["last_refresh"]`; absent/unparseable → stale; store list empty → mtime clause skipped.
- **Files modified:** `football_core/freshness.py`
- **Commit:** `1d959fb`

**4. [Rule 2 - Test Setup] Two TestClient tests had to build the registry before the app starts**
- **Found during:** task 3 (same ordering hazard, test side)
- **Fix:** `import web.competitions` placed before `with TestClient(...)` in both tests, mirroring `tests/test_architecture_resilience.py`'s established pattern.
- **Commit:** `1d959fb`

**5. [Rule 1 - Test Expectation] HARD-02 control test now legitimately reads as stale**
- **Found during:** task 3
- **Issue:** `test_hard02_swallow_sites.py::test_healthy_ledger_still_serves_the_worldcup_entry` served an entry with no `last_success_at` and expected `stale` absent/false; with D-12 wired that entry is now genuinely stale (an entry that never recorded success cannot be fresh).
- **Fix:** entry given `last_success_at`, `DATA_DIR` monkeypatched to an empty tmp dir so the mtime clause stays skipped; module docstring updated to state the RED phase ended in task 2 and the file now runs as a ratchet.
- **Files modified:** `tests/test_hard02_swallow_sites.py`
- **Commit:** `1d959fb`

### Plan-Text Adjustments (documented, not bugs)

- **Fixture reduced to exactly 5 Phase-3 entries** (plan text said "four"); all 5 verified `Phase 3`.
- **`update_ledger(path, competition, report)` accepts `str | Sequence[str]`** for UCL/LaLiga's nested `(ucl_seasons, "2026/27")` key.
- **Read-only-directory failure test substituted** with a parent-is-a-file OS failure (Windows ignores the directory write bit).
- **`competitions/ucl/src/pipeline.py` added to task 2's file list** — it held the sixth bare `pass` on the ingestion surface (must-have #2).
- **Task 3 tests live in `tests/test_hard03_staleness.py`** (the plan's `<files>` list) rather than a new `test_freshness_visibility.py`.
- **Real-data sanity check before wiring:** WC ledger already `stale: true` (no visible change), UCL store mtime == `last_refresh`, LaLiga store 12s older → no false staleness flips were introduced.

## Auth Gates

None — all external providers were already optional/offline-capable, and the one accidental live refresh (issue 1 above) was eliminated rather than gated.

## TDD Gate Compliance

Tasks 1 and 2 are `tdd="true"` and both show the required RED → GREEN pair in history:

```
2a73954 test(02-05): add failing tests for single-writer ledger and D-12 staleness rule   (RED)
02047c3 feat(02-05): single-writer freshness ledger owner with lock, atomic write...       (GREEN)
fb545ea test(02-05): add failing HARD-02 swallow-site ratchet and unreadable reader tests  (RED)
f4da146 feat(02-05): make every ledger reader loud and eliminate bare pass...              (GREEN)
1d959fb feat(02-05): wire D-12 staleness into every served refresh report                  (task 3)
```

Both RED commits were produced with the tests failing before implementation existed; both GREEN commits pass. No refactor commit needed.

## Known Stubs

None. The eight sanctioned `return {}` swallow sites are a checked, size-commented allowlist of *default-shape readers off the ingestion path* (each carries a `# SANCTIONED` line with a >30-character reason and is asserted against the exact set in `test_sanctioned_list_is_exact`), not unwired placeholders; every data source the new `_freshness()` helpers read is wired to a real ledger entry and real store paths.

## Threat Flags

None — no new endpoints, auth paths, file-access patterns, or schema changes were introduced. `/api/data`, `/api/overview` and `/api/boot` previously existed; they now serve one extra computed boolean (`stale`) derived from already-trusted inputs. All five `02-05` threats are dispositioned in the plan's register: T-05-T, T-05-R, T-05-I, T-05-S mitigated; T-05-D accepted (lock held only for file IO).

## Deferred Items

Appended to `.planning/phases/02-truthful-availability-explicit-verified-ingestion/deferred-items.md`:

- **Item 3:** `test_wc_stale_undecided_provider_cannot_wipe_penalty_decisions` fails on out-of-band gitignored repo data (stash-proved pre-existing; store rewritten by a prior session's refresh).
- **Item 4:** `install_lazy_acquisition_hook` raises `RuntimeError` if the sub-app already started, silently skipping the hook; other TestClient tests unaudited for accidental live refreshes.
- **Item 5:** baseline failures still red (`test_auto_succeeding_provider_ingests_into_tmp_store` in `02-01-BASELINE`; order-dependent `test_lazy_acquisition_is_per_competition_and_once` passes in the sweep).

## Success Criteria

- [x] One writer, one lock, one unreadable-state vocabulary — roadmap criterion 5's "swallowed failure" clause is true.
- [x] D-12 staleness is a tested, wired behavior, not a comment.
- [x] HARD-02's ratchet and HARD-03's ledger halves are both enforced by named tests.
- [x] Fixture still exists and is non-empty (5 Phase-3 entries).
- [x] `ruff check football_core web competitions tests` clean.
- [x] Sweep shows no failure outside `02-01-BASELINE.md` **except** one stash-proved data-drift failure (documented as deferred item 3).

## Self-Check: PASSED

- `FOUND: football_core/freshness.py`
- `FOUND: tests/test_hard02_swallow_sites.py`
- `FOUND: tests/test_hard03_staleness.py`
- `FOUND: .planning/phases/02-truthful-availability-explicit-verified-ingestion/02-05-SUMMARY.md`
- `FOUND: .planning/phases/02-truthful-availability-explicit-verified-ingestion/deferred-items.md`
- `FOUND: 2a73954`, `FOUND: 02047c3`, `FOUND: fb545ea`, `FOUND: f4da146`, `FOUND: 1d959fb`
- Fixture: 5 entries, all Phase 3
