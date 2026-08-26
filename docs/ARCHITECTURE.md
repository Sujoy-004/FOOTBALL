# ARCHITECTURE

## Overview

```text
Elo ratings (ClubElo API + eloratings.net sync)
        ↓
5-signal refinement ensemble          refined_elo · market_odds ·
(EnsembleEngine, weighted blend)      rolling_form · squad_value · rest_days
        ↓
Match probabilities  (Poisson score model driven by rating difference)
        ↓
MonteCarloEngine (football_core)      ← validation · seeded RNG · N runs ·
        ↓                                aggregation · SIMULATED provenance
SimulationRules (one adapter per competition brain)
        ↙                          ↘
World Cup 2026                 UCL 2025/26
12 groups + Annex-C + TPP     Swiss league + playoff + seeded R16
        ↘                          ↙
CompetitionRegistry ── FastAPI shell ── dashboard
```

## Layer responsibilities

| Layer | Owns | Must never do |
|---|---|---|
| `football_core` | signals, blending, Poisson model, generic MC engine, canonical domain/truth vocabulary, shared insight | import competitions/* or web/*; know any format |
| Competition brains (`competitions/<id>/`) | rules, standings, tiebreakers, fixture interpretation, progression, champion determination, phase derivation | be imported by football_core |
| Web layer (`web/`) | registry/adapter discovery, simulation task orchestration, truthful API payloads, static shell | encode tournament logic; fabricate state |

## football_core (shared kernel)

| Module | Responsibility |
|---|---|
| `domain.py` | Canonical truth vocabulary: `MatchStatus`, `ResultProvenance`, `DataAvailability`; `CanonicalMatch`; store-availability loader |
| `simulation.py` | `MonteCarloEngine` (run-count validation 1..1,000,000, isolated seeded RNG, repetition via `SimulationRules.simulate_one`, declared aggregations, fail-fast), `SimulationRequest`/`SimulationResult`, provenance guards |
| `insight.py` | Shared match intelligence: form trend, head-to-head, outcome distribution, insight text, KO signal ratio blend |
| `signal.py` | `Signal` protocol, registry, `PredictionContext` |
| `blender.py` | **The** ensemble: `EnsembleEngine`, `compute_log_loss_weights`, `compute_signal_contributions`. Nothing else. |
| `signals/` | The five signal implementations (+ `cached.py` cache-backed signal honoring stored draw probabilities) |
| `groups.py` | Poisson match model: expected goals from rating diff, cached CDF sampling, played-result injection, league-format sampler, tiebreaker chains |
| `knockout.py` | Knockout primitives: single match (+ET/pens), two-legged ties, blended-prob resolution with matchup-aware Elo fallback |
| `elo.py` / `elo_fetcher.py` / `elo_sync.py` | Elo math; ClubElo fetch; eloratings.net TSV sync with graduated correction |
| `predictors/odds.py` | Market-odds ingestion from BSD event payloads (vig removal) |
| `data_providers/` | BSD + football-data.org result/event providers (`fetch_matches` only) |
| `evaluation.py` | Brier, log-loss, ECE, calibration curve, TRPS (numpy only here) |
| `state.py` | Atomic JSON persistence helpers; bracket DAG validation (`validate_bracket`) |
| `provider.py` | Protocols: `DataProvider`, `FixtureProvider`, `MatchResultProvider`, `ResultHistoryProvider` |
| `fetcher.py` | Alias normalization, ingestion-stat counters/invariant, `IngestReport` (competition-agnostic refresh report shape) |

## Data acquisition & competition ingestors (Exchange 6)

Acquisition policy (Exchange 3): fresh-first, snapshot-fallback. Every
normal `python -m web.server` startup attempts each selected competition's
provider/ingestor before rendering; a failed attempt falls back to the last
validated on-disk stores and the UI says FALLBACK with the error. Explicit
offline execution (`FOOTBALL_SNAPSHOT=1`, interactive menu choice [2],
tests forcing the snapshot decision) performs zero network. Placeholder
credentials select no provider at all. A failed scrape never mutates
factual stores.

Transport selection is shared (`web/common.get_data_provider`: BSD or
football-data.org, chosen by keys/`DATA_PROVIDER`); everything after the raw
events is competition-owned. Each brain exposes one authoritative ingestor —
World Cup: `competitions/worldcup/src/pipeline.fetch_live_data`; UCL:
`competitions/ucl/src/ingest.ingest_ucl_events` (wrapped by
`pipeline.fetch_live_data`). The web layer never parses competition events;
it selects the provider, hands it to the brain, and is the SINGLE writer of
its freshness entry in `web/last_refresh.json` from the returned
`IngestReport`.

The UCL ingestor can CREATE knockout records, not only update them: with an
empty store it derives tie skeletons deterministically from final Swiss
standings + `playoff_pairings.json` + `bracket_rules.json`, persists
individual legs plus ET/penalty detail, cascades winners into downstream
slots via `source_matches`, and resolves the champion. It is idempotent and
writes stores atomically. `competitions/ucl/backfill.py` is an explicit
one-shot command that bootstraps the verified historical 2025/26 knockout
dataset (tracked at `data/bootstrap/2025_26_knockout_results.json`,
extracted byte-identically from git history; provenance `manual`) — it is
never executed by server startup.

Live feed status: football-data.org/BSD coverage of finished 2025/26 UCL
knockout matches could NOT be verified (placeholder credentials); the
provider interface is implemented against the documented API shapes and the
historical bootstrap guarantees factual completeness offline.

## CompetitionState & shared bracket contract

Each brain emits one structural state object that both factual and simulated
views share:

```text
CompetitionState = {competition, season, mode, phase, availability,
                    champion, stage_order, stages}
stage  = {id, label, layout: tree|list, matches|matchdays}
UCL tie= {id (canonical, from bracket_rules.json), round, team_a/b,
          legs[], aggregate_a/b, et_*, penalties_*, winner,
          status (MatchStatus), provenance (ResultProvenance),
          slot_sources, source_matches}
```

- UCL builder: `competitions/ucl/src/state.py::build_competition_state`
  (`mode="results"` reads canonical stores; `mode="simulation"` flattens a
  simulation payload onto the identical shape with `provenance="simulated"`).
- WC serves its validated DAG skeleton ⊕ results overlay per node with
  status/provenance and declares `stage_order`/`stage_labels`.
- Structural integrity is checked by `football_core.state.validate_bracket`
  (unique ids, resolvable parent refs, acyclic).

Frontend: `shared.js::renderBracketTree(container, bracketState, adapter)`
is the single generic renderer (columns, leaf-order spacers, SVG connectors
via parameterized `drawBracketConnectors`, SIM/MAN provenance badges). It
contains no competition vocabulary — labels, ordering, two-leg formatting
and click behavior come from thin per-app adapters (`wc.js`, `ucl.js`). UCL
two-legged ties render LEG 1 / LEG 2 / AGGREGATE (+ET/PENS notes); the
playoff stage stays a list layout ahead of the R16→FINAL tree.

## Simulation contract

- The user chooses whether to simulate and how many runs (1 .. 1,000,000;
  validated, never clamped).
- A seed may be supplied; when omitted the engine generates one and returns
  it in metadata, so every run is reproducible.
- Each competition implements `SimulationRules`: `simulate_one(context)`
  realizes one complete tournament from an engine-owned isolated RNG,
  treating real results as immutable facts. Real matches are substituted
  verbatim — never sampled.
- Aggregation is schema-free: rules declare counter objects; the engine
  aggregates summaries without storing tournament states.
- Every output carries SIMULATED provenance; a failure aborts the whole run
  (no partial results).

## Truth model

Played matches are immutable facts. Unplayed matches stay unknown until the
user explicitly requests a simulation. Simulated output is labeled as such
and lives in separate stores (`sim_cache`, `snapshot.json`) — it can never
overwrite canonical data. Missing required data is reported unavailable;
it is never represented as 0.0 or fabricated fixtures.

Season lifecycle (Exchange 3) is discovered per competition, never
hardcoded: each brain derives `stage` (completed / active / future /
unknown), progress and historical seasons from on-disk evidence (UCL:
`src/lifecycle.py::discover`; WC: `season_lifecycle`), optionally
cross-checked against a provider-declared current season (mismatch is
surfaced, never silently adopted). Lifecycle drives UX: completed seasons
render facts only — no season-wide Monte Carlo controls; per-match/tie
What-If remains available through Match Intelligence and is always labeled
SIMULATED with the factual history unchanged. Active seasons expose
"X played / Y remaining" and simulate only unresolved matches. Overview
probability tables are labeled "Monte Carlo aggregate over N runs"; any
sampled realization shown in a bracket is labeled "example simulated
bracket (one sampled run)".

Lifecycle states exposed by both competitions: `not_requested`,
`running`, `completed`, `not_needed`, `unavailable`, `failed`,
`validation_error`.

## Web layer

- `web/competitions.py` — explicit `CompetitionRegistry`. Each adapter
  exposes id/metadata, its FastAPI sub-app, `get_status()` and
  `simulation_support()`. Adding a competition = adding one adapter here.
- `web/simulation_service.py` — one task registry/thread lifecycle for all
  simulations and calibrations, plus the shared status vocabulary and
  completed-run metadata block.
- `web/wc_app.py`, `web/ucl_app.py` — HTTP + presentation-compute adapters
  over each brain's compute functions (format rules stay in the brains).

## Signals

| Signal | Data source | Degradation |
|---|---|---|
| `refined_elo` | context Elo ratings (ClubElo) | defaults to 1500 |
| `market_odds` | odds on BSD event payloads, devigged | uniform thirds |
| `rolling_form` | recent results via a result-history provider | neutral form |
| `squad_value` | committed squad-value JSON (log-ratio sigmoid); path injected by the owning competition | uniform thirds |
| `rest_days` | fixture schedule gaps | assumes 7 days rest |

World Cup additionally carries its own live-synced `elo` signal as base;
UCL's base rating enters through `refined_elo`.

## Weight resolution & calibration

Precedence everywhere: explicit weights dict → committed
`config/signal_weights.json` → **uniform fallback** (logged).

Fitting uses one method only: inverse multiclass log-loss
(`compute_log_loss_weights`, floored at 0.05, normalized). Entry points:
`POST /worldcup/api/calibrate` (fits on recorded prediction history) and
`POST /ucl/api/calibrate` (fits on replay/results data). Both write provenance
(`method`, `source`, `n_matches`) and refuse to fit below the per-signal
sample threshold.

**Current status:** World Cup ships and runs the uniform fallback. UCL fits
calibrated inverse-log-loss weights from its results history at runtime when
`competitions/ucl/config/signal_weights.json` is present (gitignored runtime
output of `POST /ucl/api/calibrate`; regenerate it any time). Out of the box
both competitions start uniform. No *validated accuracy* claims are made —
only that the fitting procedure and its provenance exist.

## Reproducibility & performance

Simulations accept an optional seed; when omitted the engine generates one
and returns it in the run metadata, so any run can be replayed exactly.
Identical code + data + seed + count ⇒ identical aggregates. UCL runs add
bootstrap/Wilson confidence intervals on championship probabilities.

Measured on a mid-range laptop (single thread): World Cup ~5.7 s at 10,000
runs (~26 s at its 50,000 default preset) and UCL ~9.3 s engine time at its
5,000 default (~12 s served including polling). WC sustains ~1,500
iterations/s and has been executed end-to-end at the full maximum of
1,000,000 runs (~11 minutes); that 1M datapoint predates the shipped
benchmark harness, which caps at 100K. Higher counts remain available for
deeper runs.

## Known limitations

- WC knockout win probabilities come from matchup-aware Elo rather than the
  full ensemble (bracket slots have no team identity until resolved).
- Mid-tournament, WC bracket slot occupants for unplayed group positions
  are projections from a deterministic seed-0 re-simulation; they are not
  labeled per-node in the UI yet.
- Snapshot mode is fully offline except that it never refreshes live data;
  UCL Elo falls back to UEFA-coefficient-derived ratings offline.
- No cancellation of running simulations; polling is one-shot after a
  terminal state by design.
