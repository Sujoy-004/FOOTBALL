# FOOTBALL

A shared football prediction and Monte Carlo simulation engine with
competition-specific brains — currently World Cup 2026 and UEFA Champions
League 2025/26 — where real played matches are immutable facts and every
simulated number is explicitly labeled as simulated.

## What it does

- **Ingests real football data** from external providers (football-data.org
  or BSD) into per-competition result stores, or runs entirely offline on a
  committed snapshot.
- **Produces match probabilities** from a five-signal ensemble
  (`refined_elo · market_odds · rolling_form · squad_value · rest_days`)
  blended by one canonical `EnsembleEngine`, plus a Poisson score model
  driven by Elo rating differences.
- **Simulates tournaments** through a generic Monte Carlo engine. Each
  competition supplies its own rules (groups, tiebreakers, knockout
  progression) behind a `SimulationRules` boundary; the shared engine owns
  validation, seeded repetition, aggregation, and provenance.
- **Keeps truth explicit**: played matches are immutable facts that are
  never sampled; unplayed matches stay unknown until you request a
  simulation; simulated output is quarantined from factual data and labeled
  everywhere it appears.

## Architecture

```text
                football_core            (shared kernel)
                  |        domain truth model - signals/ensemble -
                  |        Poisson model - MonteCarloEngine - insight
                  |
        CompetitionRegistry (web/competitions.py)
                  |
      +-----------+-----------+
      |                       |
 World Cup brain          UCL brain          (competitions/*)
 FIFA rules/format        UEFA rules/format
 SimulationRules adapter  SimulationRules adapter
      |                       |
      +-----------+-----------+
                  |
     SimulationTaskService   (web/simulation_service.py)
                  |
             FastAPI sub-apps + vanilla-JS dashboard
```

- **`football_core`** owns reusable football intelligence: the canonical
  truth vocabulary (`MatchStatus`, `ResultProvenance`,
  `DataAvailability`), signals and blending, the Poisson model, Elo math,
  the generic `MonteCarloEngine`, shared match-insight kernels, evaluation
  metrics, provider protocols, and atomic persistence. It imports nothing
  from the competition packages or the web layer.
- **Each competition brain** owns its format: World Cup has 12 groups,
  third-place qualification via the Annex-C table, and an R32-to-FINAL
  knockout with a third-place playoff; UCL has a 36-team Swiss league with
  the ten-step UEFA tiebreaker chain, a playoff round, and a
  data-driven knockout bracket. Each ships a `SimulationRules`
  adapter that realizes one tournament per call.
- **The web layer** owns discovery and orchestration only: an explicit
  `CompetitionRegistry` (the server's mounts derive from it), one
  `SimulationTaskService` for every background run, canonical lifecycle
  statuses, and truthful API payloads.

## Supported competitions

Implemented today:

| Competition | Format | Dashboard |
|---|---|---|
| World Cup 2026 | 48 teams, 12 groups, Annex-C third-place routing, R32..FINAL + third-place playoff | `/worldcup` |
| UEFA Champions League 2025/26 | 36-team Swiss league, playoff round, seeded R16 bracket | `/ucl` |

The registry/adapter boundary is designed so future competitions (for
example a league format) plug in by adding one brain package and one
registry entry — no changes to `football_core`. No other competition is
implemented yet.

## Prediction & signals

Every match probability comes from the same pipeline: a `PredictionContext`
(Elo ratings, fixtures, played results) is evaluated by five signals whose
outputs are blended per outcome by `EnsembleEngine`.

| Signal | Source | Degrades to |
|---|---|---|
| `refined_elo` | context Elo ratings (ClubElo) | 1500 default |
| `market_odds` | devigged bookmaker odds on ingested events | uniform thirds |
| `rolling_form` | recent results via a history provider | neutral form |
| `squad_value` | squad-value JSON (log-ratio transform) | median imputation |
| `rest_days` | fixture schedule gaps | assumes 7 days |

Cache-backed entries honor their own stored draw probability instead of any
hardcoded constant. Weights resolve as: explicit dict → committed
`config/signal_weights.json` → uniform fallback. Fitting uses inverse
multiclass log-loss only; UCL can fit calibrated weights from its results
history via `POST /ucl/api/calibrate` (output is gitignored runtime state),
while WC still ships uniform 0.2×5. No accuracy or ML claims are made —
evaluation metrics (Brier, log-loss, ECE, TRPS) exist but validated skill
claims do not.

## Simulation

Simulation is always user-triggered. Nothing runs automatically.

- Real played matches are immutable facts substituted verbatim in every
  iteration — never resampled, never overwritten.
- Only genuinely unresolved outcomes are eligible. A completed competition
  answers `not_needed`; missing required data fails honestly.
- Run count is validated between **1 and 1,000,000** (rejected, never
  clamped). Practical defaults: **WC 50,000** (bracket popup presets
  10K–500K; measured ≈26 s at 50K, ~5.7 s at 10K) and **UCL 5,000**
  (presets 1K/5K/10K/100K; measured ≈9 s engine time). Defaults were chosen
  for interactive response time; higher counts are available for deeper
  runs.
- An optional seed makes any run exactly reproducible; when omitted the
  engine generates one and returns it in the run metadata.
- Runs execute asynchronously with live progress polling and complete with
  a metadata block: `{status, count, seed, provenance}` where provenance
  asserts `real_results_preserved` and `simulated_matches_only`.
- Simulated output lives in separate stores (`sim_cache`,
  `snapshot.json`) and is rendered under explicit "SIMULATION" labeling;
  factual requests keep returning factual data afterwards.

## Data modes

At startup the server offers live mode (requires a
`FOOTBALL_DATA_ORG_KEY`; optional `BSD_API_KEY`, `DATA_PROVIDER=bsd|football-data`)
or snapshot mode. Snapshot mode performs **zero** live requests — including
Elo lookups, which fall back to UEFA-coefficient-derived ratings for UCL —
and both dashboards disclose that stored data is being shown. A refresh
endpoint re-ingests live results into the canonical stores without touching
simulation state.

## Performance

Measured on a mid-range laptop, single-threaded, current code:

| Competition | Count | Wall time | Where |
|---|---|---|---|
| World Cup | 10,000 | ~5.7 s | engine |
| World Cup | 1,000,000 | ~682 s (~11 min) | engine, executed end-to-end |
| UCL | 5,000 (default) | ~9.3 s engine / ~12 s served | served incl. polling |
| UCL | 10,000 | ~18.6 s engine / ~20.5 s served | served incl. polling |

Stability observation at fixed seed: UCL top-5 membership and order are
identical between 5,000 and 10,000 runs (max champion-probability delta
0.0047). This is a sampling-stability observation, not a convergence proof.

## Setup

```bash
pip install -r requirements.txt

cp .env.example .env    # optional: add FOOTBALL_DATA_ORG_KEY for live mode

python -m web.server    # http://127.0.0.1:8080  (choose [2] for snapshot)

python -m pytest        # run the test suite
```

Without API keys the server runs in snapshot mode on committed seed data;
both dashboards render, simulations work, and no network call is made.

## Fresh checkout (bootstrap)

The repo commits **seed data only** — no runtime stores. On a fresh clone:

```bash
# 1. Materialize the UCL runtime stores from tracked bootstraps
python -m competitions.ucl.backfill        # writes knockout_results.json (KO history)
python -m competitions.ucl.backfill --league  # writes results.json (league results)
```

The bootstrap files in `competitions/ucl/data/bootstrap/` are tracked:
- `2025_26_knockout_results.json` — v1 historical aggregates (git 7cbc0f6)
- `league_results_2025_26.json` — full 144-match league ledger

Runtime stores (`results.json`, `knockout_results.json`, `snapshot.json`,
and future `seasons/` directories) are **gitignored** — they are generated
artifacts, not source of truth. Tests that need complete stores use
`tests/ucl_bootstrap.make_ucl_runtime_dir(tmp_path)` or the
`ucl_runtime_dir` pytest fixture in `competitions/ucl/tests/conftest.py`.

## Testing

Current suite: **904 collected — 899 passed, 4 failed, 1 skipped**. The 4
persistent failures are long-standing environment-dependent tests (one UCL
replay-injection assertion and three WC fetcher tests that monkeypatch
`requests.get` while the code uses a `requests.Session`) — they predate the
architecture work and are tracked, not hidden. A minority of integration
tests additionally require local match-result files produced by a live
refresh; see `docs/GETTING-STARTED.md`.

## Known limitations

- WC knockout win probabilities use matchup-aware Elo rather than the full
  ensemble (bracket slots have no team identity until resolved).
- Mid-tournament WC bracket slot occupants come from a deterministic
  projection and are not labeled per-node yet.
- Simulations cannot be cancelled; progress polling is one-shot after a
  terminal state.
- UCL offline Elo falls back to UEFA-coefficient-derived ratings.
- No accuracy/skill claims: labeled history is still accumulating.

## Project structure

```text
football_core/            shared kernel: domain truth model, signals +
                          ensemble, Poisson model, MonteCarloEngine,
                          shared insight, Elo infra, providers, persistence
competitions/worldcup/    WC brain: groups/Annex-C/knockout rules,
                          SimulationRules adapter, engine/pipeline,
                          signal caches, benchmark, tests
competitions/ucl/         UCL brain: Swiss/playoff/bracket rules,
                          SimulationRules adapter, orchestrator/pipeline,
                          calibration, bootstrap CIs, tests
web/                      CompetitionRegistry, SimulationTaskService,
                          startup flow, FastAPI sub-apps, vanilla-JS SPA
tests/                    cross-cutting regression suites (truth model,
                          engine contract, immutability, product contract)
docs/                     ARCHITECTURE.md, GETTING-STARTED.md, TESTING.md
```

`study_guide/` is local-only interview material and is not part of the
repository.

## Interview value

The technically interesting parts, all verifiable in the tree:

- **One engine, many formats.** `MonteCarloEngine` knows nothing about
  groups or brackets; each competition realizes one tournament per call
  behind `SimulationRules.simulate_one(context)` and declares its own
  aggregations.
- **A real truth model.** `MatchStatus` / `ResultProvenance` /
  `DataAvailability` replace empty-array guesswork; stores distinguish
  missing vs empty vs unreadable; the UI renders those states instead of
  inferring them.
- **Played-match conditioning at scale.** Real results are injected as
  immutable facts into every iteration — verified by a test asserting the
  simulated league table reproduces the actual season table exactly.
- **Correctness found by measurement.** Knockout probabilities once keyed
  by bracket slot inverted strength rankings; the fix (matchup-aware
  fallback) is regression-tested by proving poisoned slot probabilities
  cannot change outcomes.
- **Deliberate deletion.** Speculative protocols designed during the build
  were later removed when unused — the engine boundary that shipped is the
  smaller one.
