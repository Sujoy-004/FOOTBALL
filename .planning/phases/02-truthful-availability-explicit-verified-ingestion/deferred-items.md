# Deferred Items — Phase 02

Discovered during execution, explicitly NOT fixed here (out of scope per executor rules).

## 1. `tests/test_snapshot_isolation.py` leaks a session decision (pre-existing, order-dependent)

- **Found during:** 02-03 task 1 guard batch
- **Issue:** Running `tests/test_snapshot_isolation.py` BEFORE `tests/test_freshness_visibility.py` in a custom pytest batch leaks a `snapshot` session decision into the freshness tests (`test_wc_failed_refresh_is_visible_and_marked_stale`, `test_ucl_empty_fetch_marks_stale` fail with `attempted is False`). The fixture sets the snapshot decision but does not reset it in teardown; in the full suite (alphabetical order, freshness before snapshot) the leak never manifests.
- **Impact:** Test-order-dependent false failures when executing ad-hoc batches. Not a regression of 02-03 code.
- **Suggested fix (future):** Reset the session decision in the snapshot fixture's teardown (mirror of `test_always_on_acquisition`'s `set_session_decision(None)` teardown), or set it via monkeypatch-scoped fixture.
- **Deferred to:** planner/executor discretion (a small test-hygiene plan or as part of a later test-infrastructure plan).

## 2. `tests/test_atomic_store_writes.py` line-keyed entries may need re-key after 02-03's line shifts

- **Found during:** 02-03 verification
- **Issue:** The write-ratchet fixture keys on `path:line`; this plan shifted many `pipeline.py`/`fetcher.py` line numbers. In the gate run the test did NOT go red (0 new failures vs GATE-PRE), so no action needed now — but 02-04's `path:line` → `path::symbol` re-key is the sanctioned fix if any pointer drifts.
- **Deferred to:** 02-04 (explicitly planned).

## 3. `tests/test_architecture_resilience.py::test_wc_stale_undecided_provider_cannot_wipe_penalty_decisions` fails on drifted repo data (pre-existing, out-of-band)

- **Found during:** 02-05 task 3 sweep
- **Issue:** The test reads the gitignored live store `competitions/worldcup/data/played.json` and asserts `len(pk) == 4` and `entry["match_id"]` for every penalty-draw entry. As of 2026-10-08 the store holds 35 entries of which 10 lack `match_id` (`M73`–`M79`…), so it dies with `KeyError: 'match_id'` at line 87.
- **Evidence it is NOT this plan's fault:** (a) the file's mtime was already 11:40 today, before this execution session started (~12:15); (b) the test itself is unmodified and asserts on repo data *before* any application code runs; (c) the same failure reproduces with all uncommitted 02-05 changes stashed (identical `KeyError` at line 87). Note the assertion drifted between runs today (`assert 1 == 4` at 12:40 → `KeyError` at 13:21), i.e. the store content is being rewritten out-of-band.
- **Impact:** The plan's `tests/test_architecture_resilience.py` verify gate exits non-zero; every other gate (28 freshness/ratchet tests, sweep, ruff) is green. Appears in the failure list as the only node not in `02-01-BASELINE.md` (baseline passed it with the pre-drift store).
- **Suggested fix (future):** Make the test seed its own store via `tests/arch_util.seed_wc_dir` instead of reading the repo store, or restore/normalize `played.json` so every entry carries `match_id`.
- **Deferred to:** a test-hygiene/availability plan (not part of 02-05).

## 4. `web/competitions.py::install_lazy_acquisition_hook` raises if a sub-app already started (latent, ordering hazard)

- **Found during:** 02-05 task 3 (TestClient tests)
- **Issue:** The hook is installed at import of `web.competitions` (which also builds `REGISTRY` at line 364). Starting any mounted sub-app via `TestClient` first freezes that app's Starlette middleware stack, so a *later* install raises `RuntimeError: Cannot add middleware after an application has started` — silently skipping the lazy-acquisition hook for that app.
- **Impact:** Any test that does `with TestClient(sub_app)` before `import web.competitions` gets an app with no lazy gate (and conversely, importing first makes TestClient tests fire a real provider refresh unless `try_lazy_refresh` is disarmed). 02-05's two TestClient tests now import the module before starting the app and monkeypatch `try_lazy_refresh` to a no-op; other TestClient tests in the suite have not been audited.
- **Suggested fix (future):** Install the hook defensively (catch/ignore the post-start RuntimeError, or install via `app.router.on_startup`), and audit existing TestClient tests for accidental real refreshes (the suite has API keys in `.env`, so a fired refresh makes live network calls).
- **Deferred to:** a web-layer/test-infrastructure plan (not part of 02-05).

## 5. Baseline failures still red in the 02-05 sweep (tracked, not caused here)

- **Found during:** 02-05 task 3 sweep
- **Issue:** `tests/test_always_on_acquisition.py::test_auto_succeeding_provider_ingests_into_tmp_store` (IN `02-01-BASELINE.md`, fails at line 82: missing temp `ucldata/results.json`) and `tests/test_scoped_acquisition.py::test_lazy_acquisition_is_per_competition_and_once` (IN baseline; order-dependent — fails alone, passes in the plan sweep) remain red/green exactly as recorded in the baseline.
- **Impact:** None on this plan's gates; recorded so a future sweep can compare against the same reference set.
- **Deferred to:** the phase's baseline-reduction work (plan 02-01 owns the failure list).