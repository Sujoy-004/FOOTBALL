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
| `state.py` | Atomic JSON persistence helpers |
| `provider.py` | Protocols: `DataProvider`, `FixtureProvider`, `MatchResultProvider`, `ResultHistoryProvider` |

## Simulation contract (Exchange 3)

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
- `web/wc_app.py`, `web/ucl_app.py` — thin adapters over each brain's
  compute functions.

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

**Current status:** insufficient labeled history exists, so the runtime runs
on the uniform fallback. No validated-weight claims are made.

## Reproducibility & performance

Simulations accept an optional seed; when omitted the engine generates one
and returns it in the run metadata, so any run can be replayed exactly.
Identical code + data + seed + count ⇒ identical aggregates. UCL runs add
bootstrap/Wilson confidence intervals on championship probabilities.

Measured on a mid-range laptop (single thread): World Cup ~5.7 s and UCL
~9.3 s at the 10,000/5,000 default run counts respectively; WC sustains
~1,500 iterations/s and has been executed end-to-end at the full maximum of
1,000,000 runs (~11 minutes). Higher counts remain available for deeper
runs.

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
