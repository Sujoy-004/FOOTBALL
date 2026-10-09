# Roadmap: FOOTBALL — Truthful Match Prediction & Simulation

## Overview

This milestone does not add features. It makes the existing pipeline produce **truthful,
live, end-to-end data**, and replaces the claim "the engine is good" with a **measurement**.
Seven phases, in a strict order driven by one hard dependency and one de-risking argument:
the layering inversion (`competitions/worldcup/src/pipeline.py:471` importing
`web.wc_app`) must be removed **before** any reconciliation work, and the skill measurement
runs **before** the reconciliation track is built so we know the signals are worth
reconciling around.

**Root cause worth stating once.** The "bracket is not filled with proper data" symptom and
the "simulated answers never get retired" gap are *the same defect*: bracket logic lives in
the web layer, so a competition pipeline must import the web layer to get it — and a
component cannot cleanly signal a layer it imports from. Phase 1 removes the inversion;
Phase 5 then reconciles cleanly.

**What already exists (do not rebuild).** `football_core/evaluation.py` already implements
`multi_class_log_loss`, `multi_class_brier`, `multi_class_ece` and `calibration_curve`;
`football_core/historical_backfill.py` already has a leak-free chronological replay harness
with `elo_only` and `frequency_baseline` baselines, a within-season 70/30 split and
leave-one-signal-out ablations. Phase 3 is **extend-and-apply** — copy the LaLiga driver,
add the four genuinely-new metric pieces, publish numbers. A phase described as "build a
backtest harness" would be 2–3× over-scoped.

**Honest state of the data (verified, not assumed).** `worldcup/data/played.json` and
`played_groups.json` do not exist; `ucl/.../2026_27/results.json` and
`laliga/.../2026_27/results.json` are `"matches": []`; LaLiga holds 7 of 380 fixtures. The
views are empty because the inputs are empty — the code is correct on empty input. Two
phases fix the *input* (Phase 2, Phase 6); two fix the *reporting and retirement* so an
empty input can never again read as "nothing has happened yet" (Phase 2, Phase 5).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Layering Inversion & Deprecated-Path Removal** - The competition brains stop importing the web layer and the 485-LOC duplicate predictor path is deleted, with provably identical output
- [x] **Phase 2: Truthful Availability & Explicit Verified Ingestion** - A user refreshes on demand and sees exactly what landed, when, and why a store is empty (completed 2026-10-09)
- [ ] **Phase 3: Measured Skill — All Three Competitions** - A published, leak-free report says whether the ensemble beats naive baselines, market-only loss included
- [ ] **Phase 4: Race-Free Derived State & Simulation Lifecycle** - Cached state is a frozen snapshot with a store stamp; simulations sample only unplayed matches and declare their seed
- [ ] **Phase 5: Real↔Simulated Reconciliation** - The moment real results land, every covering simulated answer is retired automatically and visibly
- [ ] **Phase 6: Per-Competition Format Correctness** - World Cup, UCL and LaLiga each render in their own format, from real ingested results only
- [ ] **Phase 7: Quality Gate — Coverage Floor & CI** - The milestone's truthfulness invariants become executable build gates

## Phase Dependencies

```text
        ┌──────────────────────────────┐
        │ Phase 1  Layering Inversion  │  ← hard prerequisite (pipeline.py:471)
        └───────┬──────────────┬───────┘
                │              │
        ┌───────▼────────┐     │
        │ Phase 2        │     │      Truthful Availability &
        │ Availability & │     │      Explicit Verified Ingestion
        │ Verified       │     │
        │ Ingestion      │     │
        └───┬────────┬───┘     │
            │        │         │
   ┌────────▼──┐  ┌──▼─────────▼──┐  ┌──────────────┐
   │ Phase 3   │  │ Phase 4       │  │ Phase 6      │
   │ Measured  │  │ Race-free     │  │ Format       │
   │ Skill     │  │ state + sim   │  │ Correctness  │
   └───────────┘  └───┬───────────┘  └──────────────┘
                      │  (before, for attribution)
                ┌─────▼───────────┐
                │ Phase 5         │  Real↔Simulated Reconciliation
                │ Reconciliation  │
                └─────────────────┘
                     all phases ──► Phase 7 (CI gate)
```

**Critical path:** 1 → 2 → 4 → 5.
**Parallelisable (`parallelization: true`):** Phases 3 and 6 both depend only on Phases 1–2
and can be executed concurrently with each other and with Phase 4.

## Phase Details

### Phase 1: Layering Inversion & Deprecated-Path Removal
**Goal**: No competition brain reaches up into the web layer, and the deprecated duplicate
predictor path is gone — with every canonical computed number provably unchanged.
**Depends on**: Nothing (first phase)
**Requirements**: LAYR-01, LAYR-02, LAYR-03, HARD-01
**Success Criteria** (what must be TRUE):
  1. [verified 2026-10-06] An automated architecture test **fails** if any non-test module
     under `competitions/*/src/` imports `web.*`. It failed on the pre-phase tree (9 such
     imports, headline `pipeline.py:471`) and passes now — 0 remain.
     `tests/test_layering_architecture.py` scans both forbidden directions, and its
     non-vacuity is reproduced by injecting a synthetic import and watching it fail.
     *Literal clause corrected:* the original wording — "no `# noqa: PLC0415`
     deferred-import suppression remains in a competition brain" — is unachievable and was
     reworded. Two suppressions remain at `pipeline.py:499` and `:650`, both intra-brain
     `src.engine` lazy imports, neither crossing a layer. The guard pins that count at
     exactly two, so growth, shrinkage and file moves all fail.
  2. [verified 2026-10-06] The regression gate holds: the 105 failing/error node ids in
     `01-01-BASELINE.md` did not grow in any of the seven plans (measured 105 → 105, 0 new,
     0 fixed; passing rose 1,711 → 1,749 as the phase's own tests landed). A new
     characterisation test asserts the World Cup full-bracket output is **byte-identical** to
     the pre-move output for a fixed fixture + played set — `compute_full_bracket` now lives
     in `competitions/worldcup/src/bracket.py` and `web/wc_app.py` imports it, never the
     reverse. *(The original text here cited "the same 1,751 tests passing", a figure that
     was already stale before this phase began.)*
  3. `competitions/worldcup/src/predictors/` (485 LOC) is deleted and a parity test runs
     the ingest path before and after the deletion over the same inputs, asserting every
     canonical number (standings, probabilities, bracket) is equal. Any weights file the
     deletion implies ships in the same phase.
  4. No module writes `competitions/*/data/` with `Path.write_text`; a regression test fails
     if one appears, and the five `_atomic_write_json` copies have collapsed to the one
     implementation in `football_core/state.py`. A crash therefore cannot leave a
     half-written store.
  5. The canonical fixture-identity decision (the three incompatible `derive_fixture_id`
     signatures) is written down and pinned by a test — UCL and LaLiga's behaviour is
     recorded, not left emergent, because Phase 5's retirement granularity depends on it.
**Plans**: 7/7 plans executed
- [x] `01-01-PLAN.md` — Capture the pre-phase baseline (1,830 collected / 105 failing-error node ids: 103 failed + 2 errors; both the old 1,751 and a transient "117 failures" were stale) and freeze a committed World Cup bracket golden
- [x] `01-02-PLAN.md` — Collapse three atomic-write copies onto one public text primitive in `football_core/state.py`; ship the ratcheting write-ban test that publishes Phase 2's worklist
- [x] `01-03-PLAN.md` — Move `ts`/`boot_step`/`get_data_provider`/`is_snapshot_mode` into `football_core/runtime_support.py`; repoint ~24 test patch sites onto one authoritative target
- [x] `01-04-PLAN.md` — Pin all three `derive_fixture_id` signatures with exact-value tests and write the contract down; change no production code
- [x] `01-05-PLAN.md` — Move `compute_full_bracket` and `compute_overview` into World Cup brain modules; prove the bracket payload unchanged against the 01-01 golden
- [x] `01-06-PLAN.md` — Delete `predictors/` and its signal-fetch stage, point the pipeline at the brain's `compute_signal_eval`, prove live before/after parity, and declare the cache-production gap
- [x] `01-07-PLAN.md` — Enforce both forbidden layering directions with an AST test; reproduce the pre-move failure to prove the guard is not vacuous
**Landmines**:
- `compute_full_bracket` and `compute_signal_eval` are the two headline moves; the other
  brain→web imports (`web.startup.is_snapshot_mode`, `web.common.get_data_provider`,
  `web.common.ts` / `boot_step`) need a small pure module both layers may import.
  — **Resolved by 01-03**: that module is `football_core/runtime_support.py`, and the
  `web/*` names are call-time delegating shims onto it. Remaining after 01-03: three
  `web.wc_app` imports at `competitions/worldcup/src/pipeline.py:471,747,758`.
  — **Reduced by 01-05 to one**: `pipeline.py:747` (`compute_signal_eval`), which 01-06
  removes together with `predictors/`. `compute_full_bracket` and `compute_overview` now
  live in `competitions/worldcup/src/{bracket,overview}.py` with `web/wc_app.py`
  re-exporting them; the 01-01 golden passed unmodified.
- This phase must change **no behaviour**. If a test fails, the fix is in the test or the
  move — not a behaviour edit. The exit gate is the 105-node-id set in
  `01-01-BASELINE.md` holding at 105 (it did, in all seven plans).
- "Competition logic in web layer" is a documented anti-pattern
  (`.planning/codebase/ARCHITECTURE.md`); the architecture test is the machine-checkable form
  of that rule and Phase 7 makes it a CI gate.

### Phase 2: Truthful Availability & Explicit Verified Ingestion
**Goal**: A user can trigger a refresh, see exactly what landed and when, and never sees
"empty" where the truth is "missing" or "failed".
**Depends on**: Phase 1 (ledger durability depends on the collapsed atomic writer)
**Scope addendum (D-08):** In addition to the requirements above, Phase 2 includes the four World Cup signal-cache producers (odds, rolling form, squad value, rest days) rebuilt during the explicit refresh — see plan 02-09.
**Requirements**: TRUTH-01, TRUTH-02, TRUTH-03, INGEST-01, INGEST-02, INGEST-03, INGEST-04, HARD-02, HARD-03
**Success Criteria** (what must be TRUE):
  1. With `worldcup/data/played.json` deleted, the World Cup view states that the store is
     **unavailable** together with the provider and the last-refresh context — it does not
     render an empty table, a zero, or "nothing has happened yet". Every competition view
     reports an explicit `DataAvailability` (`AVAILABLE` / `EMPTY` / `MISSING` /
     `UNAVAILABLE`); `web/wc_app.py:356-357` no longer defaults a missing store to `{}`.
  2. A user triggers a per-competition results refresh explicitly (endpoint or UI action).
     **Nothing is ingested at boot or on page load** — a test asserts zero provider calls
     during boot and during a plain data read.
  3. A completed refresh reports the **provider, the match counts actually ingested**
     (ingested / skipped / not-finished — every fetched event in exactly one bucket), and a
     wall-clock timestamp. `success` is *derived from those counters*: a provider returning
     HTTP 200 with zero matches reports `deferred/provider-empty`, never success.
  4. World Cup 2026 real results are in the canonical World Cup stores and drive the
     standings and bracket. **Honest-failure path:** if the provider does not serve the 2026
     tournament, the report names the provider and the shortfall, the ledger marks the store
     stale, and no view claims the tournament is up to date. No synthetic corpus.
  5. A swallowed failure is no longer invisible: no bare `except: pass` remains on the
     ingestion / freshness-ledger path, a failed write or ledger update is logged loudly,
     and the freshness ledger never reports a stale store as fresh — a missing or
     non-advancing `last_success_at` reads as stale.
**UI hint**: yes
**Plans**: 6/10 plans executed
- [x] `02-01-PLAN.md` — Freeze the Phase 2 failing-node-id baseline and answer the runnable open questions (provider probes, twelve success-site classification, ledger home, caption decision)
- [x] `02-02-PLAN.md` — Make `success` a derived fact (`derive_success()`), convert all twelve hardcoded `success=True` sites, rewrite the empty-provider landmine test
- [x] `02-03-PLAN.md` — Raise the knockout ingest pass cap to 8 with counter-integrity tests and make failure/success reports the same shape
- [x] `02-04-PLAN.md` — Re-key the write ratchet `path:line` → `path::symbol` and convert the five non-atomic snapshot/result writers (fixture 14 → 9)
- [x] `02-05-PLAN.md` — Build the freshness ledger (`football_core/freshness.py`), convert the four lock-less RMW sites to single-writer, wire the D-12 staleness rule (fixture → 5 Phase 3 entries)
- [x] `02-06-PLAN.md` — Delete the auto-refresh middleware/direct calls, add `POST /worldcup/api/refresh`, normalize all three refresh endpoints onto the IngestReport shape with OQ7 stage rows
- [ ] `02-07-PLAN.md` — Truthful availability payloads: live four-state block, key omission instead of `0`/`{}` defaults, MISSING guards on sim/what-if reads
- [ ] `02-08-PLAN.md` — UI: shared refresh button, availability banner/panel, counter caption, notice parity, Node tests — ends in a human-verify checkpoint (execution blocks on approval)
- [ ] `02-09-PLAN.md` — Four World Cup signal-cache producers (odds, rolling form, squad value, rest days) wired into the single explicit refresh pass with truthful stage rows
- [ ] `02-10-PLAN.md` — Apply the D-08 scope correction through the roadmap handlers, run live INGEST-04 with the `season=2026` pin, and close the phase gate (suite diff, lint, JS tests, requirement completion)
**Landmines**:
- `success=True` is currently constructed **before** the counters are known, at three call
  sites, and `tests/test_ucl_future_season_empty_provider.py` codifies the defect as
  intended behaviour. That test must be rewritten to assert `success=False, stale=True`.
- `web/last_refresh.json` is a lock-less file-level read-modify-write by three independent
  writers. One owner, one lock, `logger.exception` on failure.
- Signals abstain vs. uniform is *adjacent but out of scope here*: the registry substitutes
  `[1/3,1/3,1/3]` at full weight when odds are absent (30% of the ensemble voting uniform).
  Flag it in the phase notes; do not smuggle it in as scope.

### Phase 02.1: Frontend Restyle and UX Coherence (INSERTED)

**Goal:** Ship a premium, dark-first, broadcast-grade interface built on ONE shared presentation
architecture reused by all three competitions — with self-hosted fonts, skeleton loaders, an
asymmetric editorial shell, and a broadcast lower-third — while keeping the vanilla-JS stack,
module contracts, hash routing, refresh semantics, and every canonical number unchanged.
**Requirements**: None (INSERTED phase — coverage via decisions D-01..D-12 in `02.1-CONTEXT.md`)
**Depends on:** Phase 2
**Plans:** 4 plans

Plans:
- [ ] 02.1-01-PLAN.md — Token foundation + six self-hosted woff2 fonts + app-shell regions
- [ ] 02.1-02-PLAN.md — Shared archetype CSS + app-shell/asymmetric-hero CSS + full token migration
- [ ] 02.1-03-PLAN.md — JS restyle: skeleton loaders, asymmetric hero/chooser DOM, sidebar drawer + topbar
- [ ] 02.1-04-PLAN.md — Verification gates: real baseline diff, font resolution, pinned suites, visual

### Phase 3: Measured Skill — All Three Competitions
**Goal**: A reader can see, per competition, whether the ensemble actually beats naive
baselines — with intervals, a declared sample, and the market-only loss printed.
**Depends on**: Phases 1, 2 (World Cup 2026 results are the held-out validation corpus)
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05, EVAL-06, EVAL-07
**Success Criteria** (what must be TRUE):
  1. A published report gives multiclass **log-loss, Brier and ECE per competition** in three
     separate blocks, plus tournament-level TRPS in its own clearly-labelled block. There is
     no single cross-competition pooled headline; any roll-up is declared match-weighted.
  2. Each block prints the ensemble next to **uniform-thirds, frequency, Elo-only and
     market-only**, each with a paired bootstrap CI and the recorded seed. The market-only
     column is present and the ensemble's loss to it is printed.
  3. Evaluation uses leakage-free **chronological / rolling-origin** splits: a test asserts
     that for every fold, all training dates precede all test dates. `KFold`,
     `StratifiedKFold` and `TimeSeriesSplit`-as-the-reported-CV appear nowhere in the
     evaluation path. A per-match runtime leakage invariant fails the whole run if any match
     sees its own result.
  4. A **match-level ordered score** (`ranked_probability_score`, plus
     `ordered_brier = rps/2` for K=3) is available alongside the others and is named so it
     does not collide with the existing tournament `trps()` — `football_core.evaluation`
     exposes `tournament_trps` and `ranked_probability_score` as distinct names. It is
     reported as secondary and is not a gate.
  5. The verdict is one line: **"skill declared" only if the ensemble beats all three naive
     baselines on both log-loss and Brier**; otherwise it reads "not declared" and names the
     baseline that won. Every result carries its MDE and sample size, and the report
     documents that `multi_class_brier` divides by 3 (sklearn uses `[0,2]`) with the
     conversion, so the numbers are comparable to the literature.
**Plans**: TBD
**Landmines**:
- **Extend-and-apply, not build.** `evaluation.py` and `historical_backfill.py` already
  supply log-loss / Brier / ECE / calibration curves, the `elo_only` and `frequency_baseline`
  baselines, the chronological split and the ablations. Copy
  `competitions/laliga/historical_backfill/evaluate.py` for UCL and World Cup. The genuinely
  new code is four items: the match-level ordered score, classwise ECE + calibration
  slope/intercept, the date-aware rolling-origin splitter, and paired bootstrap + MDE/Holm.
- **Empty-input guards come first** (~6 lines). Every current metric returns `0.0` — which
  reads as *perfect* — on empty input. A mis-filtered population would report spectacular
  false skill. Highest severity-per-line item in the milestone.
- The backtest measures a **4-signal surrogate** (`squad_value` renormalized away) on **100%
  closing-odds coverage**, while live LaLiga has 7 fixtures, `book_selection: "none"` and no
  odds at all. `odds_absent_n = 0` — the result **does not transfer** and the report must
  say so. Knockout shootouts are coded `W = 0.75 / 0.25` in `elo.py:37`; the H/D/A mapping
  must be **declared** before any WC/UCL 1X2 number is published.
- n=144 (UCL) has MDE ≈ 0.058 and n=104 (WC) MDE ≈ 0.069. Neither can support a
  match-level significance claim — they are held-out **direction confirmation**. No
  "significantly" or "demonstrably" anywhere; there is a CI, not a p-value.
- **Honest-failure path:** if INGEST-04 did not land, the World Cup block is reported as
  `deferred/provider-empty` and the gate is evaluated on the competitions that did, with
  the exclusion stated. Inventing 104 WC matches is forbidden.
- Small-n ECE is mostly estimator bias. Withhold or down-bin when observations/bin < 20;
  always attach a bootstrap CI.

### Phase 4: Race-Free Derived State & Simulation Lifecycle
**Goal**: Cached derived state is an immutable snapshot that cannot be published half-built
or half-stamped, and every simulation declares its seed and provenance.
**Depends on**: Phase 1
**Requirements**: RECON-03, RECON-04, SIM-01, SIM-02, SIM-03
**Success Criteria** (what must be TRUE):
  1. An N-thread hammer test — concurrent `GET /api/data`, `/api/simulation` and
     `/api/overview` while a simulation completes and a refresh writes stores — never
     returns a response whose `sim_cache` lacks `status`, never mixes a stamp from
     generation *n* with a cache from *n+1*, and never returns a 500. The three-statement
     publish (`sim_cache = result` then mutate) is now unrepresentable: state is a frozen
     `DerivedState` behind a `MappingProxyType`, rebound atomically in one assignment, and
     the module globals `cache` / `sim_cache` / `_mode` / `boot_log` are gone.
  2. A request handler decides "my cache is fresh" from **one atomic stamp comparison** over
     `(role, mtime_ns, size)` — no re-reading and diffing of store contents. An out-of-band
     write by a CLI backfill or a `git checkout` of the partly-gitignored data dir is
     detected on the next request.
  3. A simulation samples **only genuinely unplayed matches**: a test asserts that every
     played match in the output equals the ingested result verbatim and that no played
     match ever appears in the resampled set.
  4. A user can trigger a fresh run on demand, and every run response carries its `seed`,
     `n_simulations` and `provenance = SIMULATED`. Running the same seed twice produces
     identical results.
  5. After any simulation run, **no file under `competitions/*/data/` has changed** — a
     before/after snapshot test proves simulated output never reaches a canonical factual
     store.
**Plans**: TBD
**Landmines**:
- The stamp must key on logical **role** (`"results"`, `"fixtures"`, `"groups"`), never on
  filename or contents — keys get rekeyed during canonicalisation, roles survive. Stamp
  paths, never contents.
- **Deliberately before Phase 5.** Reconciliation adds new concurrent writers; landing it on
  a known-racy base (`ucl_app.py:941-949`) makes any resulting bug unattributable.
- No `epoch += 1` (the Python FAQ lists `i = i+1` as non-atomic) and no read lock across
  `compute_overview()`, which calls `boot_step` under a non-reentrant `threading.Lock`. The
  honest caveat — atomic rebind relies on documented CPython GIL behaviour and does not hold
  under PEP 703 free-threading — ships with the phase.
- `_rebuild_lock` guards the rebuild only; the read path stays lock-free.

### Phase 5: Real↔Simulated Reconciliation
**Goal**: The moment real results land, every simulated answer covering them is retired
automatically and visibly — never deleted, never silently overwritten.
**Depends on**: Phase 1 (the inversion must be gone), Phase 2 (ingestion writes the stores), Phase 4 (race-free base, for attribution)
**Requirements**: RECON-01, RECON-02, SIM-04
**Success Criteria** (what must be TRUE):
  1. Ingesting a real World Cup result automatically invalidates and quarantines every
     simulation covering that match. The next `/api/data` response lists it under `retired`
     with `retired_at`, `reason` and the real `match_id` — no refresh click, no page reload,
     no manual step.
  2. A retired answer **shows as retired/superseded, not silently overwritten**: it renders
     through `effective_status()` as `scheduled` (never `played`) while its stored
     `provenance` stays `SIMULATED` forever. A test asserts a retired simulated answer is
     unreachable through the normal played path, and the retirement ledger survives a
     process restart.
  3. **Exactly one component owns the invalidation decision.** No module under
     `competitions/*/src/` imports `web.*` or calls the invalidation hook — the pipeline only
     *reports* `changed` / `changed_match_ids` on its `IngestReport` (fields it already
     computes and discards today) and never invalidates anything itself. An architecture
     test enforces it.
  4. A store that is present but empty retires **nothing** and is reported `EMPTY` — it must
     not read as "0 retired = up to date". An absent store is `MISSING` and a torn store is
     `UNAVAILABLE`; in both cases the simulation is never claimed to be current.
**Plans**: TBD
**Landmines**:
- **This is the phase Phase 1 exists for.** A pipeline that imports web cannot cleanly signal
  the layer it imports from; adding another edge would make the cycle load-bearing for
  correctness. Reconciliation runs `pipeline reports → web reconciles → store invalidates`.
  Option A (pipeline calls an invalidation hook) is rejected: it deepens the inversion and
  silently skips CLI backfill callers.
- **Retire, never delete.** Deleting `sim_cache` destroys the provenance trail — which
  simulated answers were wrong, and when did we learn it — which is exactly the evidence a
  backtest needs.
- World Cup reconciles **per match** (both sides share the fixture vocabulary). UCL and
  LaLiga ship **whole-snapshot** retirement until fixture identity is unified — coarse but
  never mis-retiring, because an empty intersection means "nothing to retire" and fabricated
  answers stay on screen silently. That asymmetry is documented, not emergent.
- "A reconciliation nobody can observe has not been proven" — `retired_count`, `retired[]`,
  `still_simulated[]` and per-store `DataAvailability` must be in the API payload.

### Phase 6: Per-Competition Format Correctness
**Goal**: World Cup, UCL and LaLiga each render in their own format, computed from real
ingested results only.
**Depends on**: Phase 2 (real results and the full fixture list land through verified ingestion)
**Requirements**: FMT-01, FMT-02, FMT-03, FMT-04
**Success Criteria** (what must be TRUE):
  1. The World Cup renders as a real World Cup: **12 groups**, **Annex-C** third-place
     routing, and the full **R32 → R16 → QF → SF → Final** chain plus the third-place
     playoff. No stage is missing and no team is routed into a bracket slot it cannot reach.
  2. The UCL renders as a **36-team Swiss league** ranked by the **10-step UEFA tiebreaker
     chain in order**, with the playoff round and the seeded bracket shown.
  3. LaLiga holds a complete **380-fixture** double round-robin schedule with correct
     qualification and relegation bands. **Honest-failure path:** if the provider returns
     fewer than 380, the view reports the shortfall with provider and counts and labels the
     schedule incomplete — it must not present 7 fixtures as the season. If a rules-derived
     schedule is used to fill the gap, it is labelled `derived_fixtures` and kept distinct
     from provider fixtures.
  4. A test asserts standings for all three competitions are **identical with the
     simulation toggled on and off** — simulated matches never enter a standings table.
**UI hint**: yes
**Plans**: TBD
**Landmines**:
- Tiebreak chains need rule-sourced verification per competition (WC head-to-head + fair
  play; UCL 10-step UEFA chain; Annex-C best-third placement). The current `(-pts, -gd, -gs)`
  shortcut is not the real rule.
- A **club** Elo feed applied to a **national-team** competition (World Cup) produces
  uniformly compressed ~50/50 output indistinguishable from "a weak model".
  `draw_prob = 0.35` is a hardcoded heuristic. Disclose or calibrate — do not quietly tune.
- Knockout-slot probabilities use matchup-aware Elo, not the five-signal ensemble, because
  slots lack team identity until resolved. Label the model path wherever a WC figure is shown.

### Phase 7: Quality Gate — Coverage Floor & CI
**Goal**: The milestone's truthfulness claims are enforced by the build, not by convention.
**Depends on**: Phases 1–6
**Requirements**: HARD-04
**Success Criteria** (what must be TRUE):
  1. `pytest` runs in CI on every push and the run is **required** — a red run blocks merge.
  2. A coverage floor is a number in config, not a convention: a commit that drops below it
     fails CI with the actual number printed.
  3. CI fails on the invariants this milestone established: a non-test `web` import inside
     `competitions/*/src/`; a `Path.write_text` on `competitions/*/data/`; an
     `IngestReport` claiming `success=True` with zero ingested matches; an orphan or
     duplicate fixture id; a bare `except: pass` in a non-test module.
**Plans**: TBD
**Landmines**:
- The checklist these gates encode is currently prose in
  `.planning/research/PITFALLS.md` §J. Converting it to executable assertions is mechanical;
  the judgement is the floor value, which must not be lowered later to make a run green.
- LaLiga is the least-tested competition (`pipeline.py` 493 LOC, `simulation.py` 238 LOC with
  no dedicated coverage). The floor should surface that rather than hide it.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Layering Inversion & Deprecated-Path Removal | 7/7 | Complete | 2026-10-06 |
| 2. Truthful Availability & Explicit Verified Ingestion | 10/10 | Complete   | 2026-10-09 |
| 3. Measured Skill — All Three Competitions | 0/TBD | Not started | - |
| 4. Race-Free Derived State & Simulation Lifecycle | 0/TBD | Not started | - |
| 5. Real↔Simulated Reconciliation | 0/TBD | Not started | - |
| 6. Per-Competition Format Correctness | 0/TBD | Not started | - |
| 7. Quality Gate — Coverage Floor & CI | 0/TBD | Not started | - |

---

*Roadmap created: 2026-10-06 · 7 phases · 33/33 v1 requirements mapped*