# Requirements: FOOTBALL — Truthful Match Prediction & Simulation

**Defined:** 2026-10-05
**Core Value:** Every competition's real results get ingested explicitly and verified, simulations run on genuinely unplayed matches from real signals, and simulated answers are automatically retired the moment real results land — so no view ever shows stale or fabricated numbers, and the engine's accuracy is measured against a naive baseline instead of claimed.

**Milestone type:** Subsequent (brownfield). Validated requirements already exist — see `.planning/PROJECT.md`.

## v1 Requirements

### Truthful Data Availability

- [ ] **TRUTH-01**: Every competition view reports explicit `DataAvailability` (`AVAILABLE` / `EMPTY` / `MISSING` / `UNAVAILABLE`); absent data never renders as an empty table, zero, or "nothing has happened yet"
- [ ] **TRUTH-02**: The World Cup web path stops defaulting a missing `played.json` / `played_groups.json` to `{}` (`web/wc_app.py:356-357`) and instead reports the store as unavailable
- [ ] **TRUTH-03**: A view with no data states the reason together with provider and last-refresh context, rather than showing blanks

### Layering Prerequisite

- [x] **LAYR-01**: `compute_full_bracket` moves out of `web/wc_app.py` into `competitions/worldcup/src/`, removing the brain→web import at `competitions/worldcup/src/pipeline.py:471`
- [x] **LAYR-02**: No module under `competitions/*/src/` imports from `web/*`; enforced by an automated architecture test
- [x] **LAYR-03**: Bracket output is identical before and after the move (characterised by test)

### Explicit Verified Ingestion

- [ ] **INGEST-01**: A user can trigger a per-competition results refresh explicitly; no ingestion occurs at boot or on page load
- [x] **INGEST-02**: A completed refresh reports the provider, the match counts actually ingested, and a timestamp
- [x] **INGEST-03**: A provider returning HTTP 200 with zero matches reports `deferred/provider-empty` — never success
- [ ] **INGEST-04**: World Cup 2026 real results are ingested into the canonical World Cup stores as the validation corpus

### Real↔Simulated Reconciliation

- [ ] **RECON-01**: Ingesting real results automatically invalidates and quarantines any simulation covering those matches
- [ ] **RECON-02**: Exactly one component owns the invalidation decision, and no competition pipeline calls into the web layer to perform it
- [ ] **RECON-03**: The store exposes a monotonic epoch/generation stamp so a request handler can detect a stale cache without re-reading and diffing
- [ ] **RECON-04**: `sim_cache` / `_mode` / `cache` are mutated race-free while background simulation threads run

### Simulation Lifecycle

- [ ] **SIM-01**: Monte Carlo samples only genuinely unplayed matches; played matches are substituted verbatim and never resampled
- [ ] **SIM-02**: A user can resimulate on demand, and every run returns its seed and provenance
- [ ] **SIM-03**: Simulated output never persists into canonical factual stores
- [ ] **SIM-04**: A simulated answer covering a now-real match is shown as retired/superseded, not silently overwritten

### Measured Skill

- [ ] **EVAL-01**: The existing replay harness in `football_core/historical_backfill.py` is applied to UCL 2025/26 and World Cup 2026 (LaLiga history is already covered)
- [ ] **EVAL-02**: A published report gives multiclass log-loss, Brier and ECE per competition, plus tournament-level TRPS where it is meaningful
- [ ] **EVAL-03**: A match-level ordered score is added under a name that does not collide with the existing tournament `trps()` (`football_core/evaluation.py:101`)
- [ ] **EVAL-04**: Evaluation uses leakage-free chronological / rolling-origin splits; random `KFold` is not used
- [ ] **EVAL-05**: The ensemble is compared against uniform-thirds, frequency and Elo-only baselines
- [ ] **EVAL-06**: Skill is declared only if the ensemble beats all three baselines on both log-loss and Brier
- [ ] **EVAL-07**: The report documents that `multi_class_brier` divides by 3 (sklearn uses `[0,2]`), so published numbers are comparable to literature

### Per-Competition Format Correctness

- [ ] **FMT-01**: World Cup renders as a real World Cup — 12 groups, Annex-C third-place routing, R32→Final plus the third-place playoff
- [ ] **FMT-02**: UCL renders as a 36-team Swiss league with the 10-step UEFA tiebreaker chain, playoff round and seeded bracket
- [ ] **FMT-03**: LaLiga holds a complete 380-fixture double round-robin schedule (currently 7) with correct qualification and relegation bands
- [ ] **FMT-04**: Each competition's standings reflect only real ingested results, never simulated ones

### Hardening & Quality Gate

- [x] **HARD-01**: The deprecated `competitions/worldcup/src/predictors/` (485 LOC, still on the live ingest path) is removed with no change to any canonical computed number
- [ ] **HARD-02**: The five bare `pass` branches that swallow errors become loud and reported
- [x] **HARD-03**: The freshness ledger never reports stale data as fresh
- [ ] **HARD-04**: A coverage floor is enforced and `pytest` runs in CI

## v2 Requirements

Deferred to a future release. Tracked but not in the current roadmap.

### Calibration & Tuning

- **EVAL-08**: Refit signal weights using the validated harness, with the evaluation split strictly isolated from the fitting split
- **EVAL-09**: Per-competition weight calibration beyond the current UCL / LaLiga state
- **EVAL-10**: Explore beating de-vigged market odds as the benchmark (currently not attempted)

### Product Surface

- **EVAL-11**: Expose the published skill report through the dashboard as a view
- **SIM-05**: Allow a background simulation run to be cancelled (currently non-cancellable)

### Coverage

- **FMT-05**: Wire the existing WC bracket-slot projection into the full ensemble once slots carry team identity
- **FMT-06**: Close the UCL offline Elo gap so coefficient-fallback ratings are no longer needed

## Out of Scope

| Feature | Reason |
|---------|--------|
| Refitting signal weights this milestone | Measure first — tuning before a trustworthy harness exists makes the measurement meaningless |
| Promoting `market_only` to a production strategy | Must stay an explicitly labelled candidate, per README |
| Rewriting the vanilla-JS frontend | Value is in data and backend correctness; frontend structure (`web/static/*.js`, `index.html`) is left alone |
| Beating the bookmaker market as the bar | De-vigged market odds are a very high bar; naive baselines are honest and falsifiable |
| Adding new competitions (Serie A, Premier League) | The registry supports them, but this milestone hardens the three that exist |
| Introducing a database | File-based JSON persistence works; the problems are truthfulness and reconciliation, not storage |
| Replacing numpy/pytest/FastAPI | Existing stack is fixed and out of scope (see `.planning/research/STACK.md`) |
| `netcal`, `mlfinlab`, `penaltyblog`, `scikit-bsm` | Rejected with evidence in `.planning/research/STACK.md` (torch/numpy≥2 deps, paid, duplicate source of truth, 404) |
| Unifying the three `derive_fixture_id` signatures | Now in scope as a Phase 1 *characterisation test only* — UCL/LaLiga behaviour is pinned and recorded, not unified. Actual unification is deferred |
| Refitting weights for the bracket-slot projection | FMT-05 stays v2; Phase 1 only proves the deprecated predictors' removal changes no canonical number |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| LAYR-01 | Phase 1 | Complete |
| LAYR-02 | Phase 1 | Complete |
| LAYR-03 | Phase 1 | Complete |
| HARD-01 | Phase 1 | Complete |
| TRUTH-01 | Phase 2 | Pending |
| TRUTH-02 | Phase 2 | Pending |
| TRUTH-03 | Phase 2 | Pending |
| INGEST-01 | Phase 2 | Pending |
| INGEST-02 | Phase 2 | Complete |
| INGEST-03 | Phase 2 | Complete |
| INGEST-04 | Phase 2 | Pending |
| HARD-02 | Phase 2 | Pending |
| HARD-03 | Phase 2 | Complete |
| EVAL-01 | Phase 3 | Pending |
| EVAL-02 | Phase 3 | Pending |
| EVAL-03 | Phase 3 | Pending |
| EVAL-04 | Phase 3 | Pending |
| EVAL-05 | Phase 3 | Pending |
| EVAL-06 | Phase 3 | Pending |
| EVAL-07 | Phase 3 | Pending |
| RECON-03 | Phase 4 | Pending |
| RECON-04 | Phase 4 | Pending |
| SIM-01 | Phase 4 | Pending |
| SIM-02 | Phase 4 | Pending |
| SIM-03 | Phase 4 | Pending |
| RECON-01 | Phase 5 | Pending |
| RECON-02 | Phase 5 | Pending |
| SIM-04 | Phase 5 | Pending |
| FMT-01 | Phase 6 | Pending |
| FMT-02 | Phase 6 | Pending |
| FMT-03 | Phase 6 | Pending |
| FMT-04 | Phase 6 | Pending |
| HARD-04 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 33 (100%)
- Unmapped: 0
- Double-mapped: 0

**Per-phase counts:** P1 = 4 · P2 = 9 · P3 = 7 · P4 = 5 · P5 = 3 · P6 = 4 · P7 = 1

**Sequencing constraint:** Phase 1 (LAYR) is a hard prerequisite for Phase 5 (RECON) —
`competitions/worldcup/src/pipeline.py:471` imports `web.wc_app`, and a pipeline cannot
cleanly signal a layer it imports from. Phase 4 (race-free derived state) precedes Phase 5
for attribution. Phases 3 and 6 depend only on Phases 1–2 and are parallelisable.

---
*Requirements defined: 2026-10-05*
*Last updated: 2026-10-06 after roadmap creation*