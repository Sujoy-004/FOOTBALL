# SIMULATION ARCHITECTURE AUDIT (Phase 12C)

Read-only audit of the *actual* simulation machinery of the FOOTBALL app.
Source of truth for the canonical simulation architecture. Every claim is
cited `file:line` against the shipped code.

---

## 1. Shared simulation contract (all three competitions)

### 1.1 Canonical status vocabulary

One status field, shipped with a matching frontend, defined in
`web/simulation_service.py:10-22`:

> ```
> not_requested     no simulation has been requested this session
> running           accepted and executing in a background thread
> completed         simulation finished successfully
> not_needed        competition fully determined by real results
> unavailable       required fixtures/data genuinely missing
> failed            runner raised; diagnostics in ``error``
> validation_error  invalid count/seed (HTTP 400)
> ```
>
> Legacy strings (none/starting/started/complete/error/no_unplayed_matches/
> no_outstanding_outcomes/invalid_request) were retired together with the
> frontend consumers in the same commit.

A `not_found` state is added by polling for an unknown task id
(`web/simulation_service.py:185-186`).

### 1.2 One task registry, one thread lifecycle

`SimulationTaskService` (`web/simulation_service.py:44-202`):

- **`start()`** (`:55-178`) — validates count first (`validate_n_simulations`,
  mirrored in both directions; `None` falls back to the per-competition
  default but a literal `0` is rejected, never silently defaulted); resolves
  seed (None lets the engine generate + return one); runs `eligibility_fn()`
  — not eligible ⇒ HTTP 200 `{"status":"not_needed","reason","message"}`;
  eligible ⇒ registers a `running` task and spawns a daemon worker thread.
  Any runner exception marks the task `failed` with the error string
  ("fail fast; no partial results emitted", `:158-163`).
- **`poll()`** (`:180-202`) — unified progress shape `{task_id, status,
  progress, iteration, total_iterations, stage, elapsed, error, result}`;
  terminal states are deleted on read (fixes the historical
  leak-on-missing-result).
- **Progress protocol** `ProgressCB = Callable[[int, int, str], None]`
  (iteration, total_iterations, stage), `Runner`, `EligibilityFn`, `OnResult`
  (`:37-41`).

### 1.3 Completed-run metadata block

`build_simulation_meta` (`web/simulation_service.py:205-231`) — the shared
COMPLETED block every competition surfaces:

```python
meta = {
    "requested": True,
    "status": "completed",
    "requested_count": requested_count,
    "count": actual_count if actual_count is not None else requested_count,
    "seed": seed,
    "provenance": {"real_results_preserved": True,
                   "simulated_matches_only": True, **(provenance_extra or {})},
}
```

plus `engine_version` and competition `extra` (WC adds `weights`, `show_ci`,
`n_top_teams`, `n_signals_evaluated`, `unplayed_matches`).

### 1.4 Engine-pure core (`football_core/simulation.py`)

`MonteCarloEngine.run` (`:409-474`) owns: count validation (1..1,000,000,
never clamped, `:50-72`); seed resolution or generation (`generate_seed`,
`:404-406`); an isolated `random.Random(seed)` per request (`:431`) never
touching global state; N repetitions of `rules.simulate_one` feeding
declared `Aggregation` objects; fail-fast (any rules exception aborts the
whole run); provenance metadata with `ensure_simulated` guard (`:154-160`) —
every output carries `ResultProvenance.SIMULATED.value` and consumers must
surface it as projection data. Hard rules documented at `:15-25`: played
matches are immutable facts, never sampled or altered; one invalid state
fails the whole run; partial results are never emitted. `SimulationRules`
protocol: `declare_aggregations` / `simulate_one` / `provenance_attestation`
(`:384-401`).

Aggregators: `ValueCounter`, `TeamListCounter`, `PositionHistogram`,
`TeamStatsAverages`, `LadderCounter` (`:217-381`).

### 1.5 Refresh isolation rule (frontend)

`web/static/refresh.js:8-19` — the quoted policy contract:

> ```
> * A competition's live data is polled ONLY while it is (a) the active
>   competition, (b) enabled, and (c) the document is visible. Polling a
>   hidden tab is wasted work; returning to the tab triggers a refresh.
> * One timer + one in-flight refresh per competition. A refresh
>   requested while another is in flight coalesces into exactly one
>   follow-up run — overlapping fetches never happen.
> * The reload hook (owned by each module) decides WHAT to refetch and
>   HOW to commit; the manager never touches DOM or appState. Modules
>   keep their own generation-token guard so a live refresh can never
>   commit over a newer full load (activateRefresh/requestRefresh only
>   schedule; correctness of commit is the module's job).
> ```

`createRefreshManager` (`:21-138`): `registerRefresh`, `activateRefresh`
(clears every prior timer so at most one interval exists),
`deactivateRefresh`, `stopAllRefresh`, `requestRefresh`, `notifyVisible`;
browser primitives injectable for a fake-clock test suite.

### 1.6 Competition registry / adapter boundary

`web/competitions.py`. `CompetitionAdapter` (`:67-116`) exposes `get_status`,
`simulation_support`, `run_simulation`, and a competition-scoped `refresh`
garment ("never raises", `:92-116`). `CompetitionRegistry` (`:119-139`) is an
explicit opt-in list. Lazy competition-scoped acquisition:
`try_lazy_refresh` fires each competition's provider at most once per
process on first data request; boot makes zero provider calls
(`:151-204`). Status contract (`:27-43`) and `simulation_support` shape
(`:39-43`) are shared.

---

## 2. UCL (`/ucl`)

### 2.1 Front-end data flow (`web/static/ucl.js`)

- `API="/ucl/api"` (`:10`); `appState` sim keys: `simProjections, simMeta,
  simRunCount, simBracket, simChampion` (`:11`).
- `init()` calls `configureCompetitionRefresh("ucl", { reload: refreshLive })`
  then the initial `loadAll`.
- **Simulation run** `startUclSimulation` (`:629-687`): client-validates runs
  in `[1, 1_000_000]` (`:636`), optional seed input, `POST /simulate`,
  polls `/simulation/progress/{taskId}` at 250 ms (renders
  stage/iteration/count/elapsed), then `GET /simulation` →
  `_applySimulationPayload` (`:618-627`) → `simProjections` (odds sorted by
  champion_prob), `simMeta`, `simRunCount`, `simBracket` (canonical
  bracket-shaped projection), `simChampion`; refetches `/data` so the tab
  gate sees the fresh `request_state` (`:675-678`); re-renders Simulation +
  Bracket.
- **Sim header** (`:858-863`): "… · N runs" + `(SIMULATED)` champion banner.
- **What-If** — per-tie button → `window.__sendModalWhatIf` (`:1484`) →
  `POST /what-if`.

### 2.2 Endpoints (`web/ucl_app.py`)

| Route | Lines | Contract |
|---|---|---|
| `GET /api/simulation` | `:593` | `odds, standings, signals, elo_ratings, champion, mode, n_iterations, snapshot_date, status, simulation_meta` + `bracket` (built by `_simulation_bracket_state` `:634`, `mode="simulation"`) |
| `POST /api/simulate` | `:696` | body `iterations`/`n_iterations`, `seed`, `weights`, `show_ci`. `eligibility` always `(True, None, "")` — completed seasons stay simulatable as explicitly-labeled what-if; `default_count=5000`; `extra_ack` carries `mode:"simulation"`, `n_unplayed`, `what_if` flag; runner `_ucl_sim_runner` (`:785`), on_result `_store_ucl_sim_result` (`:812`) |
| `GET /api/simulation/progress/{task_id}` | `:978` | `service.poll(task_id)` |
| `POST /api/what-if` | `:1190` | `match_id`, `elo_delta` (±600, ≠0, default +50 to team_a/−50 to team_b), `iterations` clamped [1000, 50000] default 10000; **seed=42 deterministic**; baseline vs adjusted via `build_simulation_result`, played league results injected as facts; returns `{mode:"structured", teams:{baseline,adjusted,delta}, top5_baseline, top5_adjusted}` |

### 2.3 Simulation-support block

`_simulation_state_block` (`:751-782`): `_season_outcome_undecided` (`:726`)
= league unplayed OR knockout store missing/empty/unavailable OR no champion
on file. When undecided ⇒ `availability:"available"`, `what_if:false`;
decided ⇒ `availability:"not_needed"`, `what_if:true` (the UI labels a run
on a complete season as alternate-history). Server-side eligibility keeps
allowing runs either way.

### 2.4 Engine (`competitions/ucl/src/`)

- **`UCLRules`** (`rules.py:43-146`) — `SimulationRules` adapter.
  `declare_aggregations` (`:88`): `positions` (PositionHistogram), `stats`
  (TeamStatsAverages), `champion` (ValueCounter), `ladder` (LadderCounter
  over `STAGE_ORDER`). `simulate_one` (`:96-136`): Swiss league phase
  (`simulate_league_phase`, `simulation.py:249`) → playoff round →
  seeded R16 bracket → knockout tree → `track_knockout_stages`; plays real
  league matches as immutable pair-keyed facts. `provenance_attestation`
  (`:138-146`).
- **`simulation.py`** — `run_monte_carlo` (`:404-551`) reassembles the
  D-06/D-07/D-09 payload from engine aggregates (stages via STAGE_ORDER,
  `:37-240`), optional bootstrap + Wilson-single-match CIs on
  `champion_prob`. `simulate_league_phase` (`:249-298`):
  precomputed Poisson lambdas once, `simulate_swiss_matches`, Swiss
  tie-break standings.
- **`orchestrator.py`** — `build_simulation_result` (`:434-509`): runs the
  MC league phase **plus one representative seed-fixed bracket realization**
  (playoff → R16 → …→ FINAL), assembles `sim_state_payload`
  (`build_sim_state_payload` `:197-237`) shaped for the canonical state
  layer. `compute_competition_phase` (`:712-786`): `completed` requires all
  of 144 league rows, playoff 8/8, R16 8/8, QF 4/4, SF 2/2 decided winners,
  decided FINAL, and champion == FINAL winner; failures surface stable
  `ucl.*` diagnostics + `inconsistent`.
- **`pipeline.py`** — `run_mc_simulation` (`:869-1064`): the web runner's
  full parity dict incl. `sim_state_payload`, deterministic output, and
  `_meta` `{n_simulations, seed (engine-resolved), engine_version, provenance
  with `league_matches_conditioned`}` (`:1052-1063`). Offline-safe via
  `elo_ratings_override` (web caches boot Elo; snapshot mode skips ClubElo).
- **Mode resolution** (`orchestrator.resolve_compute_mode` `:789-838`):
  `results` iff a readable non-empty `results.json` (season-dir first);
  knockout availability is reported separately and never flips the mode;
  otherwise `simulation`.

### 2.5 Sim vs What-If split

- **Season MC** = `/simulate` (tasked, polled, snapshot written to
  `DATA_DIR/snapshot.json` with `provenance:"simulated"`, `:826-851`).
- **Per-tie counterfactual** = `/what-if` (synchronous, two seeded 42 runs,
  no snapshot, no store mutation).

---

## 3. World Cup (`/worldcup`)

### 3.1 Front-end data flow (`web/static/wc.js`)

- `API="/worldcup/api"`; `appState` holds `simMeta` (`:10`). Simulation-tab
  DOM (`simBracket` overlay) is intentionally thin (`:95-98`).
- **`window.__simulateAllRemaining`** (`:412-432`): `showSimPopup(API, {
  min:1, max:1000000, onComplete })` — bounds override the shared popup
  (1..1,000,000, matching `validate_n_simulations`). On completion: `loadAll`
  (generation-token guarded), then `GET /simulation` → `appState.simBracket =
  simResp.full_bracket`, `appState.simMeta = simresp.simulation_meta`;
  renders Bracket + Simulation.
- **Match-level What-If is a separate concept** (never merged with the
  tournament MC — `:407-411` comment): per-card `↻ What-If` button →
  `__openWhatIf` → `openMatchModal`; `__sendWhatIf` (`:571-587`) posts
  `/match/what-if`.
- Banner reads `appState.simMeta.status` `completed`/`failed` (`:226-234`).

### 3.2 Endpoints (`web/wc_app.py`)

| Route | Lines | Contract |
|---|---|---|
| `GET /api/overview` | `:459` | refresh ledger, standings, teams, n_teams, n_played, signals_meta, phase, `has_simulation`, n_unplayed, lifecycle |
| `GET /api/simulation` | `:477` | `top_teams, signal_eval, simulation_meta, status, message, n_unplayed, full_bracket` |
| `POST /api/simulate` | `:605` | `iterations`, `seed`, `weights`, `show_ci`; validated BEFORE the eligibility short-circuit; `default_count=50000`; runner `_run_wc_simulation` (`:557`) → `run_simulation_compute`; on_result `_store_wc_sim_result` (`:567`) |
| `GET /api/simulation/progress/{task_id}` | `:929` | `service.poll` |
| `POST /api/simulate-from-match` | `:673` | `match_id` + validated iterations; synchronous full-tournament sim sliced to a target match + downstream reachability |
| `POST /api/match/what-if` | `:720` | single-match ensemble re-evaluation (base Elo + cache-backed signals), **no Monte Carlo**, no persisted state, allowed regardless of completion |
| `POST /api/what-if` | `:809` | tournament counterfactual: `run_full_simulation` baseline vs Elo-shifted, seed=42 |
| `POST /api/calibrate` | `:912` | inverse log-loss weight fit via `run_calibration_compute` (`pipeline.py:830`) |

### 3.3 Sim-support block & eligibility

`_simulation_state_block` (`:433-446`); `simulation_eligibility` (`:543-550`):
`unplayed_match_count() == 0` ⇒ **`(False, "no_unplayed_matches", …)`** —
the only competition that actually gates `/simulate` on real undecided
outcomes.

### 3.4 Engine (`competitions/worldcup/src/`)

- **`WorldCupRules`** (`rules.py:42-204`) — `declare_aggregations`
  (`:75-81`): `champion` (ValueCounter), `qf`/`sf`/`final` (TeamListCounter).
  `simulate_one` (`:83-129`): one full tournament = group matches
  (`simulate_group_matches`) → standings → third-placed ranking → Annex-C
  advancers → R32 matchups → R16 → QF/SF (generic `_simulate_knockout_round`)
  → TPP loser routing → FINAL; real played group + knockout matches override
  sampling. Expensive `matchup_lambdas` computed once per request (`:66-71`).
  `provenance_attestation` (`:131-139`).
- **`knockout.run_full_simulation`** (`:167-229`): Exchange-3 compatibility
  wrapper over `MonteCarloEngine` + `WorldCupRules`; converts aggregates back
  to the legacy `{team: {qf, sf, final, champion}}` proportions and appends
  `_meta` `{n_simulations, seed, engine_version, provenance}`.
- **`pipeline.run_simulation_compute`** (`:644-824`): ensemble predicts every
  match → `build_blend_params` (`:74-96`) → MC via `run_full_simulation` →
  `top_teams` → `compute_signal_eval` → `compute_full_bracket` (+
  `simulate_single_match` predicted scores on unresolved slots, `:776-784`)
  → snapshot. No signal store mutation during a run (`:663-665`).
- **Phase** — `compute_competition_phase` (`:1034-1106`): completed requires
  72 group matches played AND every bracket node R32(16)/R16(8)/QF(4)/SF(2)/
  TPP(1)/FINAL(1) decided with winner == FINAL winner; stable `wc.*`
  diagnostics. `season_lifecycle` (`:1134-1214`) maps onto
  completed/active/future/inconsistent.

### 3.5 Sim vs What-If split

- **Tournament MC** = `/simulate` (tasked/polled; snapshot overwrites
  `snapshot.json` with provenance, `:596-601`).
- **Per-match probability shift** = `/match/what-if` (deterministic
  single-match blend, no MC).
- **Tournament counterfactual** = `/what-if` (two seeded-42 full sims).
- **Per-match slash** = `/simulate-from-match` (target + downstream, sync).

---

## 4. LaLiga (`/laliga`) — "Latent sim backend"

The web surface is full UCL parity (league-only, no bracket); the brain is
implemented as a self-contained 20-team round-robin simulation.

### 4.1 Front-end data flow (`web/static/laliga.js`)

- `API="/laliga/api"`, `DI="laliga"`; `appState` sim keys: `sim, simMeta,
  validation` and read model `mode, phase, season, n_played, n_unplayed`
  (`:15-20`).
- `bindSimulation` (`:606-633`): `simRunBtn` → `showSimPopup(API, {
  onComplete })` — uses shared defaults (presets 10K..500K, bounds
  [1000, 500000], initial 50000) with `bodyBuilder = iters => ({iterations:
  iters})`. On completion: `GET /simulation` → `applySimulation` (guarded by
  `_stale(_transitionGen)`), `setUpRefreshBtn`, re-render the Simulation tab.
- `refreshLive` (`:655-672`): parallel `GET /data` + `GET /simulation` →
  `applySimulation(sim)` → render.
- **What-If** has two call sites: an in-tab selector (`:429`) and a
  match-level one (`:579`), both `POST /what-if`.

### 4.2 Endpoints (`web/laliga_app.py`)

| Route | Lines | Contract |
|---|---|---|
| `GET /api/data` | `:307` | refresh ledger, teams/standings, `simulation` state block (`:326`), `n_unplayed`/`n_played`, mode/phase/season |
| `GET /api/simulation` | `:377` | `odds, standings, signals, elo_ratings, champion, mode, n_iterations, snapshot_date, status, simulation_meta` |
| `POST /api/simulate` | `:454` | `iterations`/`n_iterations`, `seed`, `weights`, `show_ci`; eligibility always `(True,None,"")`; `default_count=5000`; runner `_laliga_sim_runner` (`:476`) → `run_mc_simulation`; on_result `_store_laliga_sim_result` (`:494`); extra_ack `mode` + `what_if` |
| `GET /api/simulation/progress/{task_id}` | `:615` | `service.poll` |
| `POST /api/what-if` | `:738` | match-level Elo-shift counterfactual, two seeded-42 `run_mc_simulation` calls, `elo_delta`/`iterations` clamping |
| `POST /api/reset` | `:532` | recompute deterministic cache |
| `POST /api/refresh` | `:542` | live acquisition + recompute |
| `GET /api/validation` | `:557` | pure-Elo Brier/log-loss/accuracy vs real results (no calibration curve; `calibration_available:false`) |
| `GET /api/report` | `:603` | latest `snapshot.json` |
| `GET /api/match/insight` | `:639` | ensemble + Elo + form/h2h + insight text |

### 4.3 Sim-support block

`_simulation_state_block` (`:442-451`): `_season_outcome_undecided` =
`_unplayed_match_count() > 0` (`:438`); decided ⇒ `availability:"not_needed"`
+ `what_if:true`.

### 4.4 Engine (`competitions/laliga/src/`)

- **`LeagueSimulationRules`** (`simulation.py:51-89`): `declare_aggregations`
  `champion` (ValueCounter) + `positions` (PositionHistogram).
  `simulate_one` (`:67-81`): copies real `played` facts (keyed by `match_id`),
  samples only `playable` fixtures via `sample_match_score` (`:39-48`,
  shared Poisson kernel `expected_goals` + cached CDF table — "identical to
  the other brains"). Why not `simulate_league_matches`: it keys played by team
  *pair* and synthesizes reverse orientations, wrong for a double
  round-robin (`:8-12`).
- **`run_mc_simulation`** (`:104-237`): loads fixtures/played/Elo, builds
  rules, `MonteCarloEngine().run`, reassembles the parity dict (`mode,
  teams, all_teams, n_iterations, seed, champion, odds, signals,
  elo_ratings, show_ci, _meta`); signal engine built for display only.
  Explicitly "does NOT write to disk or the web cache" (`:124`) — snapshot
  writes are the web layer's job (`_store_laliga_sim_result` `:507-527`).
- **Phase** is the league's own `phase` block from `compute_deterministic`
  (`pipeline.py`) surfaced in `/api/data`.

### 4.5 Sim vs What-If split

- Season MC = `/simulate` (tasked/polled, snapshot).
- Counterfactual = `/what-if` (two seeded-42 runs; used from two UI call
  sites). `api_what_if` does **not** go through the task service and never
  touches `sim_cache`.

---

## 5. State machine (compact)

### 5.1 Simulation task lifecycle (all three, `web/simulation_service.py`)

| State | Trigger / source | Payload |
|---|---|---|
| `validation_error` | `start()` count/seed `validate_n_simulations`/`int()` failure | HTTP 400, `{status, state, error}` (`:81-104`) |
| `not_needed` | `eligibility_fn()` not eligible (WC: 0 unplayed; UCL/LaLiga: always eligible) | HTTP 200 `{status, state, reason, message, requested:false}` + extra_ack (`:106-116`) |
| `running` | accepted; `{task_id, status, requested, requested_count, count, seed}` + options/extra_ack (`:167-178`) | worker updates progress/iteration/stage/elapsed via `progress_cb` |
| `completed` | runner returns, `on_result` runs, terminal snapshot deleted on poll (`:150-157`, `:200-202`) | poll returns `result:{status:"completed", champion, count}` |
| `failed` | runner raises — "no partial results emitted" (`:158-163`) | poll returns `error` string |
| `not_found` | poll on unknown/cleaned-up id | `{status, state, error}` (`:185-187`) |

### 5.2 Per-competition availability block (`simulation_support`, adapter)

| Competition | Eligibility gate | `availability` | `what_if` flag |
|---|---|---|---|
| UCL `ucl_app.py:751` | always eligible | `available` while `_season_outcome_undecided`; else `not_needed` | true when season decided |
| WC `wc_app.py:433` | `simulation_eligibility` — 0 unplayed ⇒ not needed | `available` \| `not_needed` (+ reason) | n/a (absent) |
| LaLiga `laliga_app.py:442` | always eligible | `available` while unplayed; else `not_needed` | true when season decided |

`request_state` is always derived from `sim_cache["status"]` with map
`running→running, completed→completed, failed→failed`, else
`not_requested` (each app's `_simulation_state_block`).

---

## 6. Provenance & truth guarantees (shared)

- Played matches are immutable facts in every engine; only unresolved
  fixtures are sampled each iteration (`football_core/simulation.py:15-25`,
  `UCLRules` `:96-136`, `WorldCupRules` `:83-129`, `LeagueSimulationRules`
  `:67-81`).
- Every simulation result carries SIMULATED provenance; `ensure_simulated`
  refuses to emit anything that does not (`football_core/simulation.py:154-160`).
- A simulation never mutates canonical stores — snapshot/sim_cache only
  (`wc_app.py:663-665`, `ucl_app.py:835-837`, `laliga_app.py:124`).
- Web runners reuse cached boot Elo (`elu_ratings_override`) so runs are
  offline-safe and reproducible; `seed=None` lets the engine generate one,
  recorded in `_meta.seed`/`simulation_meta.seed` for exact replay.
- One shared progress protocol and one status vocabulary across every
  competition (Section 1).

## 7. Key file map

| Concern | Files |
|---|---|
| Shared task service + meta | `web/simulation_service.py` |
| Registry/adapters/lazy acquisition | `web/competitions.py` |
| Generic engine + provenance | `football_core/simulation.py` |
| Refresh isolation | `web/static/refresh.js` |
| Shared sim popup + polling | `web/static/shared.js:695-849` |
| UCL | `web/ucl_app.py`, `web/static/ucl.js`, `competitions/ucl/src/{rules,simulation,orchestrator,pipeline}.py`, `competitions/ucl/src/knockout.py` |
| World Cup | `web/wc_app.py`, `web/static/wc.js`, `competitions/worldcup/src/{rules,knockout,pipeline}.py`, `competitions/worldcup/src/engine.py` |
| LaLiga (latent sim) | `web/laliga_app.py`, `web/static/laliga.js`, `competitions/laliga/src/{simulation,pipeline}.py` |