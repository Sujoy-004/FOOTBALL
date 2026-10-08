---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 02-05-PLAN.md (3 tasks, 5 commits 2a73954..1d959fb; gates green except 1 stash-proved pre-existing data-drift failure)
last_updated: "2026-10-08T08:14:52.785Z"
last_activity: 2026-10-08
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 17
  completed_plans: 12
  percent: 71
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-05) · .planning/REQUIREMENTS.md · .planning/ROADMAP.md

**Core value:** Real results ingested explicitly and verified, simulations on genuinely
unplayed matches, simulated answers automatically retired the moment real results land —
and the engine's accuracy **measured** against naive baselines instead of claimed.
**Current focus:** Phase 02 — truthful-availability-explicit-verified-ingestion

## Current Position

Phase: 02 (truthful-availability-explicit-verified-ingestion) — EXECUTING
Plan: 6 of 10
Status: Ready to execute
Last activity: 2026-10-08

Phase 01 is complete and verified (PASS_WITH_CAVEATS, `01-layering-inversion-deprecated-path-removal/VERIFICATION.md`).
Brain->web imports are ZERO; `competitions/worldcup/src/predictors/` is deleted with parity
proven; one `atomic_write_text` in `football_core/state.py`; `web/wc_app.py` reduced
961 -> 673 lines; `tests/test_layering_architecture.py` enforces both forbidden directions.
Gate held at 105 -> 105 node ids against `01-01-BASELINE.md` in every one of the 7 plans.

Progress: [███████░░░] 71%

## Performance Metrics

**Velocity:**

- Total plans completed: 7
- Average duration: 53min
- Total execution time: 6.2 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Layering Inversion & Deprecated-Path Removal | 7 | 369min | 53min |
| 2. Truthful Availability & Explicit Verified Ingestion | 2 | TBD | - |
| 3. Measured Skill — All Three Competitions | 0 | TBD | - |
| 4. Race-Free Derived State & Simulation Lifecycle | 0 | TBD | - |
| 5. Real↔Simulated Reconciliation | 0 | TBD | - |
| 6. Per-Competition Format Correctness | 0 | TBD | - |
| 7. Quality Gate — Coverage Floor & CI | 0 | TBD | - |
| 01 | 7 | - | - |

**Recent Trend:**

- Last 5 plans: 01-01 (42min), 01-02 (61min), 01-03 (70min), 01-04 (40min), 01-05 (60min)
- Trend: flat (5 data points; 01-04 was the cheap docs-only plan, 01-05 the expensive code move)

*Per-plan, updated after each plan completion:*

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 1 P01 | 42min | 4 tasks | 9 files |
| Phase 1 P02 | 61min | 2 tasks | 9 files |
| Phase 01 P03 | 70min | 3 tasks | 33 files |
| Phase 01 P04 | 40min | 2 tasks | 3 files |
| Phase 01 P05 | 60min | 3 tasks | 8 files |
| Phase 01-layering-inversion-deprecated-path-removal P01-06 | 57m | 3 tasks | 11 files |
| Phase 01 P07 | 39min | 2 tasks | 1 files |
| Phase 02 P02 | 500min | 3 tasks | 12 files |
| Phase 02-truthful-availability-explicit-verified-ingestion P03 | 45min | 3 tasks | 5 files |
| Phase 02-truthful-availability-explicit-verified-ingestion P04 | 45 | 3 tasks | 6 files |
| Phase 02 P05 | 80min | 3 tasks | 9 files |

## Accumulated Context

### Decisions

Decisions are logged in the PROJECT.md Key Decisions table. Roadmap-specific:

- **Phase 1 is the hard prerequisite for Phase 5.** `competitions/worldcup/src/pipeline.py:471`
  imports `web.wc_app`; a pipeline cannot cleanly signal a layer it imports from. RECON work
  does not begin until LAYR lands.

- **Phase 3 is extend-and-apply, not build-from-scratch.** `evaluation.py` (log-loss, Brier,
  ECE, calibration curve) and `historical_backfill.py` (leak-free replay, `elo_only` +
  `frequency_baseline` baselines, 70/30 split, ablations) already exist. Do not re-derive them.

- **Measurement runs before the reconciliation build.** It needs no API keys, uses committed
  history, and tells us whether the signals are worth building around.

- **Phase 4 before Phase 5**, for attribution: reconciliation adds concurrent writers, and
  landing it on the known-racy base (`ucl_app.py:941-949`) would make bugs unattributable.

- **Retire, never delete** a simulated answer; `provenance` stays `SIMULATED` forever.
  Retirement changes validity, not origin.

- Phases 3 and 6 depend only on 1–2 and are parallelisable with Phase 4.
- **Phase 1 gate is the 105 unique failing/error node ids** in
  `01-01-BASELINE.md`, not a pass/fail total. Measured pre-change: 103 failed +
  2 errors, 1711 passed. The plan's `117 failed` predates the `6efbe5c` LaLiga
  store restore and is stale; so is `README.md`'s "1,751 passing".

- **The bracket golden imports `web.wc_app` on purpose.** That path is stable on
  both sides of the 01-05 extraction, so a failure afterwards means the
  computed output actually changed, not just that an import moved. Do not
  repoint it at `src/bracket.py`.

- **Plan 01-07 must expect TWO `noqa: PLC0415`, not five.** Two ride on a
  brain->web import (01-05 removed the `:471` and `:758` pair, leaving `:747`,
  which 01-06 removed); two are
  unrelated intra-brain `src.engine` lazy imports at `competitions/worldcup/src/pipeline.py:499`
  and `:650`. Do not delete those two, and do not widen 01-07's mandate without a decision.
  **[Post-01-06 the total is TWO, not five — see the matching note in Blockers.]**

- **Layering scans use an AST walk, not regex.** Regex misses multi-line import
  blocks (e.g. `pipeline.py:758`) and yields a wrong count. The 9 brain->web
  violations are listed in `01-01-import-manifest.json`.

- **`.planning/` is gitignored** (`.gitignore:1`) and `commit_docs` is `false`,
  so plan 1's baseline, manifest, summaries and `deferred-items.md` are on disk but
  uncommitted. If 01-07 needs a CI-enforced baseline, one of those two must change first.
  Note the code and tests this plan produced ARE committed, so the repo carries the
  ratchet even though it does not carry the fixture's rationale in history.

- [Phase 1]: There is exactly ONE atomic-write implementation repo-wide, and it is public: atomic_write_text in football_core/state.py. _atomic_write_json survives only as a serialiser that delegates to it. A fifth implementation the plan's audit missed (historical_backfill.write_json, which lacked fsync) was folded in too - machine-checked by tests/test_atomic_store_writes.py case 5. — Phase 2's ledger durability and Phase 4's atomic rebind both rest on this. Grep for def atomic_write_text must return 1 and for _atomic_write_text must return 0.
- [Phase 1]: The non-atomic-store-write ban is an EXACT-MATCH RATCHET against tests/fixtures/deferred_non_atomic_writes.json, not a blanket ban and not an empty allowlist. A NEW offender fails AND a FIXED one fails; the FIXED set is the progress signal that tells Phase 2 to update the list. — D-25/D-26. An empty allowlist is unreachable this phase and an unbounded one rots silently. Asserting discovered == committed is the only shape that catches both a new write and a silently abandoned promise.
- [Phase 1]: Deferred entries carry PER-ARTIFACT phase ownership: nine canonical runtime stores are Phase 2's (web/last_refresh.json x4, snapshot.json x3, played.json, played_groups.json); five measurement/calibration artifacts are Phase 3's (eval_results.json, UCL validation baseline, baseline_uncalibrated.json, config/signal_weights.json, the shadow predictions.jsonl append). — Assigning all 14 to Phase 2 would demand it know Phase 3's scope. Phase 2 cannot be expected to fix a calibration artifact.
- [Phase 1]: The sanctioned writer is exempted from the write ban as a WHOLE FILE, never by line number, and its internals are asserted separately. Test modules inside the audited roots (football_core/tests, competitions/*/tests) are excluded - consistent with D-25 already excluding the main tests/ tree's ~55 legitimate tmp_path writes. — A line-number exemption rots on the next edit. A pytest fixture has no reader to protect and no durability requirement, so listing one would be an entry that fails its own 'actionable' test.
- [Phase 1]: web/last_refresh.json has FOUR lock-less read-modify-write sites across three modules, not the three D-25 states: competitions/worldcup/src/pipeline.py:136 (failure branch), :329 (success branch), web/ucl_app.py:263, web/laliga_app.py:177. — Phase 2 owns the single-writer rework and needs the true scope. Correcting D-25 upward, never downward.
- [Phase 1]: 01-02's must_haves.truths #3 ('no file under football_core/ or competitions/*/src/ writes a store with bare open(...,'w') or Path.write_text') is NOT satisfied and cannot be in this phase. The ratchet is its intended partial satisfaction; football_core/ is now clean except historical_backfill.py:650, deferred to Phase 3. — D-26 explicitly states those call sites are deliberately not converted. Do not treat truth #3 as a gate for 01-02's completeness.
- [Phase 1]: A shared helper that must cross a layer boundary gets a CALL-TIME DELEGATING SHIM, never a bare re-export. The real body lives in `football_core/runtime_support.py`; `web/common.py` and `web/startup.py` keep the public name but look the implementation up on the kernel INSIDE the function body. — D-02's promise holds for import statements and cannot hold for monkeypatch targets: `monkeypatch.setattr(web.common, "get_data_provider", ...)` rebinds an attribute on the `web.common` module object, invisible to a brain calling `runtime_support.get_data_provider`. Two independent bindings cannot both be the patch target. This is the pattern for any future brain->web shim (LAYR-02's remaining `web.wc_app` imports).
- [Phase 1]: `web.startup._last_decision` STAYS (D-03) but is written only through the new `set_session_decision()`, which also calls `runtime_support.set_snapshot_session()`. — About 40 test sites forced snapshot mode by assigning that global directly; once `is_snapshot_mode()` moved to the kernel those assignments became silently inert and the tests would have run in auto/live mode behind green assertions. A desync here means an "offline" session actually reaches the network (T-03-S). The explicit setter is the only sanctioned writer; do NOT add a module `__getattr__` or `__class__` interception to intercept assignment.
- [Phase 1]: 01-03's plan frontmatter claims `requirements: [PHASE1-C2]`, but no such id exists in REQUIREMENTS.md (Phase 1 tracks LAYR-01/02/03). Nothing was force-marked. This plan is prerequisite infrastructure for LAYR-02, not a separately tracked requirement. — Correcting the id in 01-03-PLAN.md is left to the planner rather than inventing a requirement to satisfy a field.
- [Phase 01]: D-27 executed literally: all three derive_fixture_id signatures are pinned and documented, nothing is unified, and production code changed by zero lines — fixture ids key the persisted UCL and LaLiga stores, so a signature change orphans records silently instead of raising; Phase 5's per-competition retirement granularity (D-28) rests on identity staying per-competition. tests/test_fixture_identity.py asserts hardcoded golden vectors, and docs/FIXTURE-IDENTITY.md carries the same vectors, the excluded-date rationale and the store-migration consequence
- [Phase 01]: 01-04 task 1 was marked tdd=true but had no RED commit, deliberately — the plan forbids any production change, so a genuine failing test would have required breaking production code to get to GREEN. Non-vacuity was proved instead by mutating all three implementations in the working tree (4 of 7 tests failed), restoring, and re-running (7 of 7 pass) -- evidence recorded in 01-04-SUMMARY.md, with no mutation ever committed
- [Phase 01]: `compute_bracket_display` went to `bracket.py`, not `overview.py`, although `compute_overview` is its only caller — `_build_match_score` is shared with `compute_full_bracket`, so the literal task-2 placement would force either a private cross-module import (`bracket._build_match_score`) or a `bracket -> overview` dependency. `overview.py` imports the two public names at module scope, `bracket.py` never imports `overview.py`, and all three import orders were verified. — 01-05 task 2; recorded because a verifier reading the plan's "compute_overview plus its helpers" will look for it in overview.py first
- [Phase 01]: A brain module may not import `web.common`, so `overview.py` carries its own 6-line `load_json` and takes `boot_step` from `football_core.runtime_support` (the 01-03 single authority, not `web.common`'s alias). The freshness banner reads `web/last_refresh.json` through `pipeline._last_refresh_report_path()` — reusing the brain's existing reader rather than adding a second hard-coded path to a web-layer file the brain already writes at `:136`/`:329`.
- [Phase 01]: 01-05's must_haves #2 and #5 over-reach relative to the plan's own task-3 text. `:747` stays (01-06's), so `pipeline.py` keeps exactly one web import after this plan — which is precisely what the plan's verify block asserts (AST `== [(747, 'compute_signal_eval')]`). And `noqa: PLC0415` now occurs **THREE** times (`pipeline.py:536, :687, :747`), not five: the "expect FIVE" note below is stale by the two this plan removed, while its "do not delete the `src.engine` pair" half still stands. Must_have #5 can never become true without a decision on 536/687.
- [Phase 01]: The write-ratchet hazard flagged in Blockers happened in its weakest form — line pointers only (`web/wc_app.py` 628→472→340, `pipeline.py` 914→912), `path`/`symbol`/`owner` untouched, offender count unchanged, and the flagged `_store_wc_sim_result` write proven AST-identical to `5369db1` before each re-key. Line drift is the safe case; a `path` or `symbol` change is the one that would need a real decision. Still the decision, not a fix: the `path:line` → `path:symbol` re-key remains Phase 2's.
- [Phase 01]: State handlers mutate STATE.md around you: state.advance-plan rewrote the body's `Status:` line to "Ready to execute" (orphaning its continuation lines) and truncated the body `Last activity:` line; state.update-progress's frontmatter sync set `status: completed` while 2 of 7 plans remain. Both were restored by hand. Anyone scripting this phase must re-read STATE.md after every handler call rather than trusting `updated: true`.
- [Phase ?]: 01-06 removed the last brain-to-web import (pipeline.py:747). The noqa: PLC0415 total in the World Cup brain is now TWO, not three: the intra-brain .engine lazy imports sit at pipeline.py:499 and :650 and must not be deleted without a decision. 01-07's expectations should be updated to TWO.
- [Phase 01]: D-29 layering guard scans production modules only: test modules excluded structurally (tests/ path component or test_* file name, the predicate test_atomic_store_writes already uses) and the brain scope is exactly competitions/*/src/** per the 01-01 import manifest, so competitions/ucl/main.py:57 is out of scope by the manifest rather than by a skip list.
- [Phase 01]: D-30 the noqa: PLC0415 ratchet is pinned at exactly two (competitions/worldcup/src/pipeline.py:499 and :650, the D-14 intra-brain src.engine lazy imports), not zero as plan 01-07's literal case 3 and must_have #3 state; growth, shrinkage and a file move all fail and force a decision.
- [Phase 01]: D-31 the layering guard matches import roots on segment boundaries (mod == root or mod.startswith(root + '.')) so stdlib webbrowser/websocket can never false-positive against a startsWith('web') rule.
- [Phase 01]: D-32 D-09 non-vacuity was demonstrated with two byte-wise synthetic injections (pipeline.py:14, orchestrator.py:12) each reverted with an empty git diff, and the evidence lives in the committed test's own docstring because .planning/ is gitignored with commit_docs=false.
- [Phase 02]: Decision A: report.finished keeps the 5-key display set; derive_success reads a separate 6-key view with skipped_missing_score from stats — test_report_counters_invariant pins the display shape; derivation must never read a partial view. competitions/ucl/tests/test_ingest.py untouched and passing.
- [Phase 02]: Decision B: WC fetcher count_finished-before-no-op defect accepted in 02-02 as a NAMED follow-up for 02-03 — fetcher.py:227,240-252,261-281,331,381-404 bump counters before no-op exits, so a second idempotent run derives counter_inconsistent; would flip test_architecture_idempotency.py:32,44,45 and test_architecture_resilience.py:106 RED in a complete env (SKIP here).
- [Phase 02]: site #9 _synthesize_season_report derives success from the store's own counts (settled store True, empty store deferred) instead of an unconditional placeholder — a blanket False would misreport the shipped canonical dataset as failed; stale stays False because the shipped store IS the evidence and no provider was asked (attempted=False).
- [Phase 02]: web freshness-ledger verdicts read the report's derived success (ok or deferred no longer stored as success) — completes threat T-02-S: a completed run that ingested nothing or was deferred can no longer be recorded as success in web/last_refresh.json.
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-03: D-14 counter contract — received counts provider-side events (incl. re-offers), ingested counts store-side changes, skipped_no_change bridges the difference; invariant holds on idempotent runs
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-03: Knockout retry loop uses per-event index accounting (matched_once terminal, unresolved retried, payload dedupe first-wins) with a scratch fold refunding exactly len(batch) skipped_no_target receipts — stronger than the delta-copy option
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-03: Applied score corrections count as ingested (store-side change) in both WC processors
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-03: skipped_no_change is an optional 7th counter key added via .get() increments; derive_success honors it only when present — legacy 6-key vocabulary and KeyError fail-closed stay intact
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-03: _build_report is the single report schema for all four fetch_live_data exits; skipped_reason only when provider never reached; ledger written only on attempted runs
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-05: football_core/freshness.py is the ONLY writer of web/last_refresh.json - update_ledger()/read_ledger() under one module threading.Lock + atomic_write_text, logger.exception then re-raise; all four former lock-less RMW sites route through it
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-05: an unreadable ledger is DATA, not silence - the served report carries {ledger: "unreadable", detail: <exception class name only>} (no message, no tokens), the marker is never persisted, and a missing file stays {} because an empty ledger is not an error
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-05: D-12 staleness is served, not stored - served_stale(entry, store_mtimes) uses last_success_at OR last_refresh (UCL/LaLiga schema has no last_success_at) and is applied by each app at _current_refresh_report/_refresh_report_for/api_boot; store-path knowledge stays in the apps: played*/results/fixtures only, snapshot.json (simulated) and odds.json (refetched on demand) excluded
- [Phase 02-truthful-availability-explicit-verified-ingestion]: 02-05: a TestClient test that starts a mounted sub-app must import web.competitions BEFORE first start (middleware stack freezes) and monkeypatch try_lazy_refresh to a no-op - otherwise a read-only test fires a real FootballDataOrgProvider refresh into the gitignored repo store (deferred-items.md item 4 covers the defensive install)

### Pending Todos

None yet.

### Blockers/Concerns

- **Phase 01→02 (2026-10-06): the baseline SHRANK — 105 → 100 node ids, 0 new.**
  Ingesting the 18 real UCL matchday-1 results (`FootballDataOrgProvider`, via the app's
  own `POST /ucl/api/refresh` path) fixed 5 baseline failures:
  `test_ucl_ingestion_diagnostics.py` x2, `test_ucl_phase9a_regression.py::
  test_persisted_2026_27_store_has_complete_finished_md1`,
  `test_ucl_presentation_contract.py` x2.
  `01-01-BASELINE.md` stays frozen at 105 — it is a historical record, not a live target.
  Future gates must treat it as an UPPER BOUND: the set may only shrink, and 100 is now
  the real count. Do not "restore" the 5 to make 105.
  Gate command: `python -m pytest -q --tb=no -p no:cacheprovider 2>&1 | Select-String "^(FAILED|ERROR)"`
  → 98 failed + 2 errors, 1754 passed, 14 skipped (1868 collected).

- ~~**Phase 1: fixture identity is undecided**~~ — **RESOLVED by 01-04.** The three
  signatures are pinned, not unified (D-27), and the decision is written down in
  `docs/FIXTURE-IDENTITY.md` with the exact vectors asserted by
  `tests/test_fixture_identity.py`. Phase 5's retirement granularity can now be
  chosen from that document. Actual unification stays out of scope per
  `REQUIREMENTS.md` "Out of Scope". Note the accurate line refs are
  `football_core/seasons.py:44` and `competitions/ucl/src/seasons.py:289` — the
  `:62` / `:299` cited earlier in this file were never correct.

- **Phase 1 (bookkeeping, from 01-03 and 01-04):** both plans declare a
  `requirements: [PHASE1-C*]` frontmatter id, and **neither exists** in
  `REQUIREMENTS.md` (Phase 1 tracks `LAYR-01/02/03`, `HARD-01`). `PHASE1-C2` and
  `PHASE1-C5` read as *Phase 1's Success Criteria 2 and 5* in `ROADMAP.md`, which
  both plans do discharge, but `requirements mark-complete` reported
  `not_found: ["PHASE1-C5"]` and marked nothing. Correcting the ids is a planner
  call; inventing a requirement row to satisfy the field would be worse.

- **Phase 1 (open, needs a decision):** `.planning/` is gitignored (`.gitignore:1`) and
  `commit_docs` is `false`, so plan 1's `01-01-BASELINE.md`, `01-01-import-manifest.json`,
  the two summaries and `deferred-items.md` are on disk but uncommitted. If 01-07 wants a
  CI-enforced architecture test with a committed baseline, one of those two must change first.
  Not force-added — that would fight the repo's stated policy on every write.

- **Phase 2 (from 01-02):** the write-ban ratchet keys on `path:lineno` per D-26, so any
  unrelated edit to the eight audited source files fails `tests/test_atomic_store_writes.py`.
  Phase 2 hits this on its first conversion; it may re-key on `path` + `symbol` deliberately,
  keeping the "a FIXED entry also fails" behaviour. Full reasoning in `deferred-items.md` item 1.

- **Phase 1 (correction to 01-01's plan):** `noqa: PLC0415` occurs **five** times, not
  three. Three ride on a brain->web import; two are unrelated intra-brain `src.engine`
  lazy imports at `competitions/worldcup/src/pipeline.py:536` and `:687`. 01-07's
  verification must expect five and must not delete the `src.engine` pair without a call.
  **Post-01-05 update:** the count is now **three** (`:536`, `:687`, `:747`) — 01-05
  removed the `:471` and `:758` suppressions as planned, so 01-07 must expect three, not
  five. The `:536`/`:687` half of this warning is unchanged: do not delete them without a
  call, and 01-05's must_have #5 ("no `noqa: PLC0415` anywhere in the World Cup brain")
  is unreachable without it.

- **Phase 1 (from 01-05):** `tests/fixtures/deferred_non_atomic_writes.json` keys on
  `path:line`, so *this* plan's own line deletions forced three pointer re-keys
  (`web/wc_app.py` 628→472→340, `pipeline.py` 914→912). Each was a pure line shift —
  `symbol`, `path` and `owner` untouched, offender count unchanged, flagged write
  AST-identical to `5369db1`. Verified harmless, but it means the ratchet fails on
  *any* edit above the flagged line in the eight audited files, not just on a new
  write. A `path`-level or `symbol`-level change is the case that needs the Phase 2
  re-key decision; a line shift does not.

- **Phase 1 (from 01-04):** a `-k` filtered run is NOT a reliable gate. The plan's own
  `pytest tests/ -q -k "fixture or season or parity or draw"` surfaces
  `tests/test_exchange7_ui_transitions.py::TestSeasonSwitchAPI::test_seasons_list_contains_both_seasons`
  as an ERROR, which is **not** one of the 105 baseline node ids. It passes in
  isolation and does not appear in the unfiltered full suite; it is order-dependent
  on the same missing `competitions/ucl/data/results.json` store. Always diff the
  **full** run against `01-01-BASELINE.md`; treat `-k` output as advisory only.

- **Phase 2:** WC 2026 provider coverage is unverified. If it fails, INGEST-04 reports
  `deferred/provider-empty` and Phase 3's WC block is deferred too. Never fabricate a corpus.

- **Phase 3:** empty-input metric guards (~6 LOC) must land before any number is published —
  every metric currently returns `0.0`, which reads as *perfect*, on empty input.

- **Phase 3:** whether ClubElo exposes a historical date-indexed feed is unverified; if not,
  `surrogate_elo: true` stays on every derived metric. Closing-vs-decision-time odds gap is
  unquantified — disclose qualitatively, do not argue.

- **Phase 5:** the `socceR` row-sum contract is MEDIUM confidence (doc mirror). Verify in R
  against the `m1` fixture (expect 0.125) before comparing to any published number.

- **Phase 6:** tiebreak chains need rule-sourced verification per competition.
- Phase 1 (bookkeeping, 3rd occurrence): 01-05's frontmatter lists `requirements: [LAYR-01, LAYR-03, PHASE1-C3]` and `PHASE1-C3` does not exist in REQUIREMENTS.md — same class of error as PHASE1-C2 (01-03) and PHASE1-C5 (01-04). LAYR-01 and LAYR-03 were marked complete; PHASE1-C3 was not invented to satisfy the field. The planner should fix the frontmatter id in all three plans.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Calibration & Tuning | EVAL-08/09/10 — refit weights, per-competition calibration, beat the market | v2 | Roadmap creation 2026-10-06 |
| Product Surface | EVAL-11 dashboard skill view; SIM-05 cancellable runs | v2 | Roadmap creation 2026-10-06 |
| Coverage | FMT-05 ensemble WC bracket slots; FMT-06 UCL offline Elo gap | v2 | Roadmap creation 2026-10-06 |
| Adjacent debt | Abstention-vs-uniform signal weights; `DEFAULT_ELO` laundering; `draw_prob = 0.35` heuristic; undeclared `pandas` dependency | flagged, not in this milestone | Roadmap creation 2026-10-06 |

## Session Continuity

Last session: 2026-10-08T08:14:52.763Z
Stopped at: Completed 02-05-PLAN.md (3 tasks, 5 commits 2a73954..1d959fb; gates green except 1 stash-proved pre-existing data-drift failure)
Resume file: None
