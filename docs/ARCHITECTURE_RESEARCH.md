# UCL Prediction Engine — Architectural Research Study

**Date:** 2026-06-29
**Purpose:** Research the best engineering approach for each architectural decision in the next major milestone. No implementation plans. No phase numbers. No code modifications.

---

## Table of Contents

- [R-01: Official Fixture Ingestion](#r-01-official-fixture-ingestion)
- [R-02: Simulation Modes](#r-02-simulation-modes)
- [R-03: Predictive Signals](#r-03-predictive-signals)
- [R-04: Signal Blending](#r-04-signal-blending)
- [R-05: Probability Calibration](#r-05-probability-calibration)
- [R-06: Uncertainty Modelling](#r-06-uncertainty-modelling)
- [R-07: Tournament Validation](#r-07-tournament-validation)
- [R-08: Evaluation Metrics](#r-08-evaluation-metrics)
- [R-09: Market Integration](#r-09-market-integration)
- [R-10: Explainability](#r-10-explainability)
- [R-11: Production Architecture](#r-11-production-architecture)
- [Conclusion](#conclusion)

---

## R-01: Official Fixture Ingestion

### Current State

The UCL simulator loads fixtures exclusively from `competitions/ucl/data/fixtures.json` — a static, hand-curated synthetic schedule. The BSD API is called only when `--validate` is passed, and its fixtures are used solely for post-hoc match-level scoring, never for simulation.

### Industry Practice

Professional sports analytics platforms (e.g., Sportmonks, Sportradar, Genius Sports) maintain multi-layered ingestion architectures:

1. **Collection layer** — adapters per provider (REST polling, WebSocket, webhook) publishing raw events to a unified bus (Kafka/Pulsar)
2. **Normalization layer** — maps provider-specific schemas to canonical fields; resolves entity IDs via in-memory caches
3. **Validation layer** — state machine (PENDING → CONFIRMED → SETTLED) with deduplication via sliding window
4. **Storage layer** — columnar store (Iceberg/Delta) for analytics; Redis hot cache for live reads

Sportmonks' architecture (published 2026) uses a 5-layer design: external data → odds calculation → event state machine → bet acceptance → settlement, with explicit circuit breakers and Redis-backed failover.

### Open-Source Implementations

- **sportsbook-odds-streaming-api** (rustchainer, GitHub) — normalised WebSocket/API service consolidating multiple sportsbooks into one contract. Layers: Recon (discovery) → Ingest → Normalize → API (WebSocket + REST) → Validation.
- **worldcup-oracle** (ruhan-sahasi, Rust) — `DataProvider` trait with three adapters: `SimProvider`, `ReplayProvider`, `LiveProvider`. Single trait behind which any source plugs in. Deterministic simulator + replay engine for offline use.
- **tournamental** (0800tim) — spec-driven streaming architecture. Producers (mock, video→AI, tracking feed, StatsBomb replay) emit a canonical JSON spec stream. Renderer does not know the source.

### Advantages

| Approach | Pros | Cons |
|----------|------|------|
| BSD as primary, repo as fallback | Real fixtures → real calibration; rerun with actual bracket | Requires API key; BSD may not return full fixture list; network dependency |
| Repo as primary, BSD as enrichment | No API dependency; deterministic | Any fixture update requires repo change; comparison against real outcomes is apples-to-oranges |
| Dual-source with sync verification | Both sources kept consistent; can detect drift | Engineering complexity; conflict resolution |

### Recommendation

**Adopt BSD as primary, repo JSON as fallback.** Implement a `FixtureProvider` trait (interface) with two implementations:
- `BSDFixtureProvider` — fetches from BSD API, caches with TTL, validates schema
- `RepoFixtureProvider` — loads from repo JSON, used when BSD is unreachable or API key absent

The existing `fixtures.json` format already matches the BSD schema (teams + matchdays). The `BSDFixtureProvider` would return the same structure. This means zero changes to the simulation engine — only the fixture loading point changes.

### Computational Cost

Negligible. Fixtures are loaded once at startup (~30KB JSON). API call is single `GET /events?league_id=7&limit=200`.

### Engineering Complexity

Low-Medium. The `DataProvider` trait pattern is well-established (worldcup-oracle uses it). Requires:
- One abstract base class / protocol
- Two concrete implementations
- Cache layer (TTL-based, Redis or local file)
- Schema validation (Pydantic model)

### Risk

- BSD API may require paid tier for 2025/26 UCL fixtures (league_id=7 may not return future fixtures)
- BSD fixture schema may differ from repo JSON structure (normalization needed)
- If BSD does not serve future fixtures, the architecture is moot → repo fixtures remain primary

### References

- Sportmonks Sportsbook Backend Design (2026)
- rustchainer/sportsbook-odds-streaming-api (GitHub)
- ruhan-sahasi/worldcup-oracle (GitHub)
- 0800tim/tournamental (GitHub)

---

## R-02: Simulation Modes

### Current State

Single mode: full synthetic simulation from start to finish, always. (Now outdated: codebase supports 3 modes — simulate, replay, live — via --mode flag.)

### Industry Practice

Modern sports simulators (FootySim.io, worldcup-oracle, F1-PREDICT) support multiple modes:

1. **Free Simulation** — hypothetical tournament from scratch (current UCL mode)
2. **Replay Mode** — exact reproduction of a completed tournament (used for backtesting)
3. **Live Conditioning** — start from today's real results, simulate forward from current state
4. **Branching/Timeline** — "what-if" at any match node (FootySim.io's timeline thumb)

FootySim.io (2026) implements: "Reality Toggle — turn OFF to simulate a fresh tournament. Turn ON to jump back to reality." Their engine runs 10,000 full-season simulations nightly for every tournament.

worldcup-oracle's replay engine: "It ships a deterministic simulator and a replay engine, so it runs fully offline with zero keys and zero network." Their `DataProvider` trait swaps between sim / replay / live.

F1-PREDICT's architecture: separates `Simulation Engine` (deterministic + rigorous pipeline) from `Replay Engine` (frame-aligned telemetry playback).

### Recommendation

**Three-mode architecture:**

1. **Simulation Mode** (existing) — full hypothetical tournament from repo/BSD fixtures. `predict --mode simulate`

2. **Replay Mode** — given a set of completed match results, inject them into the league phase before simulating forward. Used for:
   - Historical backtesting against known UCL outcomes
   - "What if Arsenal had drawn with PSG instead of losing" scenarios
   - Calibrating champion probabilities against known tournament results

3. **Live Conditioning Mode** — fetch real results from BSD (completed matches only), inject into standings, simulate the remaining fixture list. Used for:
   - Mid-tournament predictions
   - Real-time probability updates as matchdays complete

### Architecture

```
FixtureProvider → MatchResultProvider → ConditionedStandings → Monte Carlo Engine
                                          ↑
                                Replay/Live results injected here
```

The `simulate_league_phase` function already accepts fixtures. Adding a `played_matches` parameter (matching the WC pattern in `simulate_group_matches`) would allow overriding specific match results while simulating the rest.

### Computational Cost

Same as current (50K iterations in ~44s). No additional cost for live conditioning (same engine, different input data).

### Engineering Complexity

Medium. The core change is adding a `played_matches` dict to `simulate_league_phase()` that overrides synthetic results. The WC engine already implements this exact pattern.

### Risk

- Replay mode requires reliable historical match data for UCL (BSD or manual entry)
- Live conditioning during a tournament requires timely BSD API responses
- Mode routing logic must be clean (not leaky conditionals throughout the codebase)

### References

- FootySim.io — timeline simulation engine
- ruhan-sahasi/worldcup-oracle — DataProvider trait pattern
- XVX-016/F1-PREDICT — replay engine architecture

---

## R-03: Predictive Signals

### Current State

One active signal: **Elo** (ClubElo API). All others inactive.

### Research Findings

Based on published studies and production systems (2025-2026):

#### Ranked by Expected Predictive Value

| Rank | Signal | Expected Δ Log-Loss | Evidence |
|------|--------|---------------------|----------|
| 1 | **Market odds (Pinnacle/closing)** | ~0.05 improvement over model-only | jdgoated1/football-predictor: XGBoost alone RPS 0.203 → with odds 0.198. Bookmaker baseline RPS 0.195. |
| 2 | **xG (expected goals)** | ~0.01-0.02 | Bundesliga study (Sage, 2026): xG-based Skellam yielded ROI ~10-15%. xG pre-match RPS 0.199. |
| 3 | **Squad market value** | Top-5 feature | WM_2026 (XGBoost): Transfermarkt values rank top-5 after Elo. Log-transform used. |
| 4 | **Rolling form (decayed)** | ~0.01 | Every production system uses multi-window form features (3-20 match windows, exponential decay). |
| 5 | **Elo (refined)** | Baseline | Current system uses raw ClubElo. Improvements: goal-difference weighted K, competition-aware K, home/away split Elo. |
| 6 | **Home advantage** | Small but consistent | Already active. HOME_ADVANTAGE_MULTIPLIER=1.05. But this is applied uniformly — should be team/league-specific. |
| 7 | **Rest days** | Marginal | WM_2026: `rest_diff` feature. Effect size small but measurable. Typical value: 0-7 days. |
| 8 | **Injuries / Lineups** | Event-dependent | Major impact when star players miss. Hard to quantify as a continuous feature. Best as binary flag or lineup-strength index. |
| 9 | **Manager effects** | Marginal | Difficult to isolate from squad quality. Long-tenure managers show small positive effect. |
| 10 | **Set-piece threat** | Niche | FootballGPT uses "set piece threat index." Marginal for match outcome but relevant for specific markets. |

#### Notes from Key Studies

- **jdgoated1/football-predictor** compared Dixon-Coles, CatBoost, stacked ensemble, and bookmaker odds. Stacked ensemble (no odds): RPS 0.203. Stacked + odds: RPS 0.198. Bookmaker alone: RPS 0.195. The key finding: even the best model cannot beat the market, but a model + market blend approaches market accuracy.

- **Bayesian study (ScienceDirect, 2026)** on Polish Ekstraklasa embedded bookmaker odds + xG, xT, OBV, VAEP in a single Bayesian framework. Concluded: "betting odds are the most reliable source of information for predicting sports performances."

- **EPV vs xG study (PMC, 2025)** compared expected possession value vs expected goals. EPV outperformed xG in pre-match scenarios (RPS 0.194 vs 0.199). xG outperformed EPV post-match.

### Recommendation

**Immediate (low-effort, high-impact):**
1. **Refine Elo** — add goal-difference-weighted K-factors and competition-aware K. ClubElo already provides the base; refine locally.
2. **Market odds** — integrate BSD odds as a secondary signal (see R-04 and R-09).

**Medium-term:**
3. **Rolling form** — add form decay features (weighted recent results over 3/5/10 match windows).
4. **Squad market value** — periodic scrape or static dataset (Transfermarkt). Log-transform.

**Long-term:**
5. **xG model** — build or integrate with an expected goals model.
6. **Injury/lineup flags** — requires live data feed.
7. **Rest day calculation** — computed from fixture schedule (free, no API needed).

### Computational Cost

- Elo refinement: zero (same computation, different K)
- Market odds: one API call per matchday
- Form features: O(n) per iteration, negligible
- Squad value: static file read
- Rest days: computed from schedule, zero

### Engineering Complexity

Low-Medium per signal. Each signal can be developed independently as a pure function: `(team, match_context) → float`.

### Risk

- Market odds require consistent API access (BSD or The Odds API)
- Squad values stale quickly (transfer windows)
- Form features must be leakage-proof (computed with shift(1) before the match date)

### References

- jdgoated1/football-predictor (GitHub)
- vincent-rgb-cpu/WM_2026 (GitHub)
- FootballGPT/football-model (GitHub)
- "Can simple models predict football?" — Sage Journals, 2026
- "AI in Bundesliga match analysis — EPV vs xG" — PMC, 2025

---

## R-04: Signal Blending

### Current State

No blending. Single signal (Elo) → single probability.

### Research Findings

#### Methods Comparison

| Method | Description | Pros | Cons | Football-specific evidence |
|--------|-------------|------|------|---------------------------|
| **Simple averaging** | Equal weighted mean of signal outputs | Zero tuning; robust; hard to overfit | Ignores relative accuracy | SportSignals: "Averaging is simple and effective" |
| **Weighted averaging** | Weights proportional to historical accuracy or inverse log-loss | Simple; adaptive; interpretable | Weight decay needs periodic recalibration | Most common in production ensembles |
| **Stacking (meta-learner)** | Train a logistic regression / XGBoost on base model outputs | Best accuracy (1-2% improvement over averaging) | Risk of overfitting; needs careful validation | jdgoated1: stacked ensemble achieved RPS 0.203 (vs bookmaker 0.195). Best with proper validation folds. |
| **Bayesian model averaging** | Weight by posterior model probability | Principled uncertainty | Assumes true model is in the set; can fail catastrophically in M-open setting | Yao, Vehtari, Simpson, Gelman (2018): "BMA can fail catastrophically" in M-open setting |
| **Bayesian stacking** | Optimize log-score over predictive distributions via Gibbs posterior | Combines strengths of stacking + Bayesian uncertainty; regularization via prior | Computational overhead; complex implementation | Wadsworth & Niemi (2025): Gibbs posterior stacking outperformed BMA in FluSight competition |
| **Logistic regression meta-learner** | Train logistic regression on base model probabilities | Simple; well-understood; calibrated outputs | Assumes linear combination | Bailey81/MatchOracle: 5-layer ensemble with meta-LR, meta-MLP, meta-HGB, meta-XGB |
| **Isotonic-calibrated meta-learner** | Fit isotonic regression on base model outputs | Non-parametric; corrects any monotonic distortion | Needs sufficient calibration data; overfits with <500 samples | jdgoated1: "Isotonic-calibrated logistic regression meta-learner" blends Elo, Pi-rating, Dixon-Coles, XGBoost |

#### Key Insights from Production Systems

- **jdgoated1/football-predictor**: Stacked ensemble (4 base models → calibrated logistic regression). Accuracy 0.531, RPS 0.198. "Without odds as a feature, CatBoost alone is within noise of the full stacked ensemble" — the stacking layer's marginal contribution over the best single model is small.

- **Bailey81/MatchOracle**: 5-layer stacking: Dixon-Coles → 13 base learners → 4 meta-learners → binary classifier boosting → best ensemble selection. Achieves 60.2% accuracy (+4.6% over market). But this complexity is justified by 20 seasons of training data.

- **SportSignals**: Uses weighted ensemble combining Poisson-xG, gradient boosting, neural network, and Elo models. "Weighted averaging because it's simple and effective."

- **Yao et al. (2018)**: "Stacking of predictive distributions" recommended over BMA for M-open settings. Use proper scoring rule optimization.

### Recommendation

**For the current project (limited historical tournament data):** Start with **weighted averaging** with weights proportional to each signal's historical log-loss on a validation set. This is the most robust approach for small-data regimes.

**Architecture:**
```
Signals (Elo, MarketOdds, Form, SquadValue)
    → SignalProbability(signal, match) → p_home, p_draw, p_away
    → WeightedAverage(weights=[w1, w2, ...])
    → CalibratedProbability(calibrator)
    → MonteCarloSimulation
```

**Weight calibration:**
1. Hold out one tournament season
2. Compute per-signal log-loss on that season
3. Set weights proportional to inverse log-loss: `w_i = (1/ll_i) / sum(1/ll_j)`
4. Recalibrate per season or per validation window

**Future upgrade path:** Replace weighted average with stacked meta-learner once enough historical data is accumulated (>5 tournaments or >1000 matches).

### Computational Cost

Negligible. A weighted average of 5 floats per match.

### Engineering Complexity

Low. Weighted average is a single function: `sum(p_i * w_i for i in signals) / sum(w_i)`.

### Risk

- Weighted averaging assumes linear independence of signals
- If signals are correlated (e.g., market odds already incorporate Elo), weights become unstable
- Recalibration cadence must be defined (seasonal? tournament-based?)

### References

- Yuling Yao et al. (2018) — "Using Stacking to Average Bayesian Predictive Distributions" (Bayesian Analysis)
- jdgoated1/football-predictor (GitHub)
- Bailey81/MatchOracle (GitHub)
- SportSignals — Ensemble methodology page
- Wadsworth & Niemi (2025) — "Bayesian Stacking via Proper Scoring Rule Optimization"

---

## R-05: Probability Calibration

### Current State

No calibration. Champion probabilities are raw MC counts divided by total iterations. This produces overconfident estimates (68.8% for Arsenal in a 36-team tournament).

### Research Findings

#### Methods Comparison

| Method | Parameters | Data Required | Pros | Cons | Football Use |
|--------|-----------|---------------|------|------|-------------|
| **Platt scaling** | 2 (a, b) | 100-500 samples | Parametric; robust with small data; simple logistic fit | Too rigid for complex miscalibration patterns; single global transform | Most common baseline |
| **Isotonic regression** | Non-parametric (n+1 step thresholds) | 500+ samples | Corrects any monotonic distortion; powerful | Overfits with small data; step function is discontinuous at bin edges | jdgoated1, ZenHodl, Diegogrebate |
| **Temperature scaling** | 1 (T) | 100-500 samples | Simplest; preserves accuracy; natural multiclass extension | Assumes uniform miscalibration; cannot fix non-monotonic errors | Diegogrebate: "Best for small data" |
| **Beta calibration** | 3 (a, b, c) | 200-500 samples | More flexible than Platt; bounded to [0,1] naturally | Slightly more complex than Platt | Manokhin & Grønhaug (2026): "Beta calibration improved log-loss most frequently across tasks" |
| **Venn-Abers** | Non-parametric (2 isotonic fits) | 500+ samples | Distribution-free validity guarantees; best avg log-loss reduction | Computational overhead; two isotonic fits | Manokhin & Grønhaug (2026): "Venn-Abers achieved largest average log-loss reductions" |

#### Key Empirical Findings

- **Diegogrebate (2025)**: Temperature scaling (T=1.42) reduced ECE from 0.182 to 0.031. Isotonic regression on <200 samples overfit badly (val ECE=0.01, test ECE=0.19). Temperature on 250-300 samples: val ECE=0.04, test ECE=0.042. Conclusion: "Use temperature scaling when you have 100-500 validation samples."

- **Manokhin & Grønhaug (2026)** — "Classifier Calibration at Scale": Benchmark of 21 classifiers × 5 calibrators. Venn-Abers achieved largest average log-loss reductions. Beta calibration improved log-loss most frequently. Platt scaling was weakest. "No method dominates uniformly."

- **scikit-learn docs**: Isotonic regression is "more powerful" but "more prone to overfitting, especially on small datasets." Temperature scaling "does not affect accuracy" (preserves rankings).

- **ZenHodl (2026)**: "ECE below 0.03 means your probabilities are within 3pp of reality. Above 0.05, your edge calculations are systematically wrong." Their pipeline: train on 2020-2024, validate on early 2025, fit isotonic calibrator, apply to live, monitor ECE weekly.

### Recommendation

**Temperature scaling** as the primary calibrator for three reasons:

1. **Single parameter** — robust with limited calibration data (current: 1 UCL tournament season, ~144 matches)
2. **Preserves rankings** — if Arsenal has the highest raw probability, it stays the highest after calibration
3. **Multiclass-friendly** — naturally extends to champion probabilities across 36 teams (single T parameter for all)

**Implementation:**
```
Given raw probabilities p_i across all 36 teams:
  logit_i = log(p_i / (1 - p_i))
  calibrated_i = softmax(logit_i / T)
  where T is learned by minimizing log-loss on held-out calibration data
```

**Calibration data source:** Held-out historical UCL season(s). Use the existing `--validate` output to construct a calibration set: for each matchday, compare predicted probabilities against actual results.

**Backup:** If calibration data grows to >500 matches, consider isotonic regression or Beta calibration.

### Computational Cost

Minimal. Temperature scaling is a single-parameter optimization (gradient descent on 1 parameter).

### Engineering Complexity

Low. Temperature scaling is ~20 lines of Python. Integration point: between the MC aggregation and the display layer.

### Risk

- Temperature scaling assumes uniform miscalibration. If the model has different overconfidence in different probability ranges, isotonic would be better.
- Calibration requires held-out data. The project currently has exactly one UCL season of validation data.
- Calibration on match-level probabilities may not transfer to tournament-level champion probabilities.

### References

- Diegogrebate (2025) — "Temperature Scaling vs Isotonic Regression"
- Manokhin & Grønhaug (2026) — "Classifier Calibration at Scale" (arXiv)
- scikit-learn Probability Calibration documentation
- ZenHodl (2026) — "Why Your Sports Betting Model Loses Money"

---

## R-06: Uncertainty Modelling

### Current State

No uncertainty modelling. Point-estimate Elo ratings, point-estimate champion probabilities. The MC simulation captures aleatoric uncertainty (Poisson randomness) but not epistemic uncertainty (model parameter uncertainty).

### Research Findings

#### Techniques Comparison

| Technique | Description | Data | Pros | Cons |
|-----------|-------------|------|------|------|
| **Bayesian Elo (Glicko)** | Rating as Gaussian (μ, σ²). Update both after each match. | Sequential match results | Closed-form update; no MCMC; natural credible intervals | Requires match-level data per team; ClubElo doesn't expose σ |
| **Parameter sampling** | MC over K-factor, base_rate, HFA from distributions | Historical validation | Captures model uncertainty; flexible | Requires defining priors; multiple MC loops |
| **Bootstrap** | Resample match results with replacement, retrain each bootstrap | Historical match data | Non-parametric; simple | Computational cost; doesn't capture structural uncertainty |
| **Bayesian Poisson (MCMC)** | Full hierarchical model: atk_i, def_j ~ Normal with partial pooling | Full historical dataset | Most principled; partial pooling shrinks sparse data | MCMC is slow; complex implementation; requires PyMC/Stan |
| **Conformal prediction** | Distribution-free prediction intervals | Calibration set | Any model; coverage guarantees | Prediction sets not probabilities; intervals are conservative |
| **Ensemble variance** | Standard deviation across ensemble member probabilities | Multiple models | Free (if ensemble already exists); interpretable | Doesn't capture all uncertainty sources |

#### Key Implementations

- **Glicko/Glicko-2**: The standard for uncertainty-aware ratings. Closed-form Bayesian update. Rating Deviation (RD) tracks confidence. g(RD) factor compresses win probabilities when uncertainty is high. Used by chess, NBA (MatchOracle includes Glicko-2 features), and MLB (AspireVenom/EloSystem).

- **AspireVenom/EloSystem (MLB)**: Implements Bayesian Elo with: `bayesian_elo_update(team_mu, team_sigma2, result, expected, K, T)`. Updates both μ and σ². Probability clamping prevents overconfidence when σ is small. Minimum variance prevents uncertainty collapse.

- **Stochastic Football (Justinus Kho, 2026)**: Team strength modeled as distribution (Structural Elo with Sigma). Sigma tightens for predictable teams, expands after shock results. K-factor is dynamic (increases when sustained outperformance signals structural shift).

- **playmobil/worldcup-forecast**: Hierarchical Bayesian Poisson with partial pooling. Each simulated tournament draws a fresh posterior sample → champion probabilities marginalise both parameter uncertainty and match randomness. Non-centred parametrisation avoids funnel (0 divergences, r̂≈1.0).

### Recommendation

**Start with Bayesian Elo (Glicko-style)** as the foundation:

1. Replace point-estimate Elo with (μ, σ²) per team
2. Update both after each simulated or real match
3. Use g(RD) factor to compress probabilities when opponent uncertainty is high
4. Carry σ² through the MC simulation (higher σ → greater match outcome variance)

**Architecture:**
```
BayesianElo(team) → (μ, σ²)
    → g(RD) = 1 / sqrt(1 + 3 * σ²_opponent / π²)
    → Expected score with g(RD) deflation: E = 1 / (1 + 10^((μ_b - μ_a * g(RD))/400))
    → Poisson(lambda) from deflated Elo difference
```

This prevents the overconfidence seen in the current system (Arsenal 68.8% champion) by naturally deflating probabilities when uncertainty is high.

**Future upgrade:** Once a historical match database exists, switch to hierarchical Bayesian Poisson (PyMC/Stan) for full posterior sampling.

### Computational Cost

- Bayesian Elo update: O(1) per match (closed form, no MCMC)
- g(RD) calculation: O(1) per match
- Negligible compared to the 50K MC iterations

### Engineering Complexity

Low-Medium. Glicko update is ~5 lines of math. The harder part is tracking per-team μ, σ² across matches and integrating g(RD) into the existing `expected_score()` function.

### Risk

- ClubElo does not expose rating deviation. A local Bayesian Elo must be maintained separately.
- Without real match results to update Elo against, the uncertainty will not converge.
- g(RD) factor changes the expected score formula — requires retuning of K, base_rate, and HFA.

### References

- Mark Glickman (1995) — Glicko rating system
- AspireVenom/EloSystem (GitHub)
- Justinus Kho — "Stochastic Football" (Medium, 2026)
- playmobil/worldcup-forecast (GitHub)
- MetricGate — "Bayesian Elo Uncertainty Propagation"

---

## R-07: Tournament Validation

### Current State

Match-level validation only (Brier, LogLoss, ECE via `--validate`). No tournament-level validation. No replay validation. No cross-tournament backtesting.

### Research Findings

#### Validation Approaches

| Approach | Description | Best For | Example |
|----------|-------------|----------|---------|
| **Temporal train/test split** | Train on pre-cutoff data, test on post-cutoff | League-style continuous data | SoccerPredictAI: matches before `test_start` are train, after are test |
| **Walk-forward (rolling origin)** | Expanding window: train fold 1 on [t₀, t₁], test on [t₁+1, t₂]; expand for fold 2 | Streaming match data, ongoing seasons | Wager Theorem: "closest to real betting workflow" |
| **Cross-tournament backtest** | Hold out entire tournament Y, train on all pre-Y data | Tournament prediction | Diego Sarceño (2026): "the correct evaluation protocol for this domain" |
| **Replay validation** | Inject real results, simulate forward from each matchday | Mid-tournament accuracy | worldcup-oracle: replay mode with locked fixtures |
| **Pre-registration** | Hash and timestamp all predictions before tournament starts | Scientific integrity | kedarvyas/WorldCupPredictor: SHA256-receipted forecasts |
| **Bootstrap confidence** | Resample historical tournaments with replacement | Small sample sizes | "paired bootstrap on per-match log-loss differences" (playmobil) |

#### Key Findings from Literature

- **Diego Sarceño (2026)** — "The Champion List Is a Liar": Central insight — cross-tournament, leakage-free backtesting is the only valid protocol for tournament prediction. Train on all matches with year < Y, evaluate on tournament Y. As-of join guarantees test features use only pre-Y data.

- **SoccerPredictAI (2026)** — Rigorous temporal validation with property-based tests: "No features derived from post-match information. Rolling aggregations respect the prediction cutoff (shift(1)). Elo ratings are pre-match only. Split is time-based, not random."

- **The Wager Theorem (2026)** — Walk-forward validation guidelines: 1) Sort by timestamp, 2) Build features from pre-timestamp data only, 3) Add gap parameter if feature pipeline risks lookahead, 4) All tuning inside training fold.

- **Wheatcroft (2021)** — Argues Ignorance score (log-loss) is the best scoring rule for identifying the correct forecast, outperforming RPS and Brier in simulation experiments.

### Recommendation

**Implement three-tier validation:**

**Tier 1 — Cross-Tournament Backtest (primary)**
```
For each historical UCL season Y:
    Train all components on matches with year < Y
    Predict tournament Y outcomes
    Score: tournament-level metrics (TRPS, champion accuracy, stage probabilities)
```

**Tier 2 — Walk-Forward Match-Level (ongoing)**
```
Window: train on 3 prior seasons → test on current season
    Features recomputed with shift(1) per match
    Update window by sliding 1 season forward
```

**Tier 3 — Replay Validation (diagnostic)**
```
For each completed tournament:
    Step through matchdays:
        At matchday d, inject real results from days 1..d-1
        Simulate remaining fixtures
        Score: how well did probabilities at matchday d predict final outcome?
    Evaluate probability calibration over all simulation states
```

### Computational Cost

- Cross-tournament: N full training runs (one per held-out year). With current engine (no ML training), this is fast (~44s × N seasons = minutes).
- Walk-forward: Same training as standard.
- Replay: M full simulations per tournament (one per matchday). 8 matchdays × 44s = ~6 min per tournament.

### Engineering Complexity

Medium. Requires:
- Clean temporal split logic
- As-of feature computation (ensuring no lookahead)
- Test harness that processes historical data
- Automated reporting pipeline (Quarto/Jupyter)

### Risk

- Only ~1 UCL season of data in the project (2025/26). More seasons needed for meaningful backtesting.
- Historical UCL data requires sourcing (BSD historical data or public datasets).
- the cross-tournament approach needs the orchestration of multi-season data, which is not currently collected.

### References

- Diego Sarceño — "The Champion List Is a Liar" (Medium, 2026)
- SoccerPredictAI — Validation Strategy docs (2026)
- The Wager Theorem — Walk-Forward Validation (2026)
- Ekstrøm et al. — "Evaluating one-shot tournament predictions" (JSA, 2021)

---

## R-08: Evaluation Metrics

### Current State

Accuracy, Brier, Log Loss, ECE — all computed for match-level predictions only.

### Research Findings

#### Metrics for Tournament Prediction

| Metric | Level | Description | Pros | Cons |
|--------|-------|-------------|------|------|
| **Log Loss (Ignorance)** | Match | -sum(y * log(p)) | Strictly proper; local; best for discriminating forecasts (Wheatcroft 2021) | Infinite penalty for p=0 on true outcome |
| **Brier Score** | Match | Mean squared error (p - y)² | Strictly proper; bounded [0,1]; intuitive | Insensitive to distance; treats all incorrect outcomes equally |
| **Ranked Probability Score (RPS)** | Match | Sum of squared differences in cumulative distributions | Ordinal-aware; "close" wrong better than "far" wrong | Non-local; can reward worse forecasts at small sample sizes (Wheatcroft 2021) |
| **Tournament RPS (TRPS)** | Tournament | RPS over final tournament ranking | Only tournament-level metric; handles partial rankings; weightable | Requires full ranking as target; new metric (2021) |
| **ECE (Expected Calibration Error)** | Match | Weighted avg |abs(mean_pred - frac_pos)| over bins | Direct calibration measure | Requires binning choices |
| **Stage probability accuracy** | Tournament | % of correct stage assignments per team | Intuitive | Binary (correct/wrong at each stage) |
| **Champion rank** | Tournament | Rank of champion in predicted probability list | Simple | Loses probability information |
| **Top-K accuracy** | Tournament | % of actual top-K teams in predicted top-K | Practical | Threshold-dependent |
| **ROI (Return on Investment)** | Betting | Model-based betting vs market odds | Directly measurable value | Requires market odds; sensitive to stake sizing |

#### Key Debates

- **RPS vs Log Loss**: Wheatcroft (2021) demonstrates RPS underperforms Log Loss at small sample sizes (<200 matches) and argues the "sensitivity to distance" property adds nothing. Log Loss (Ignorance score) is consistently best at identifying the correct forecast. Penaltyblog (2025) confirms Log Loss is more consistent.

- **TRPS**: Ekstrøm et al. (2021) propose TRPS specifically for tournament predictions. It operates on the final ranking (not individual matches) and can apply weights (e.g., weight champion position more heavily than 9th place).

- **CRPS (Continuous RPS)**: Used for continuous predictions (e.g., goal totals). L² distance between CDFs. Not directly applicable to tournament outcomes but useful for xG validation.

### Recommendation

**Primary metrics:**
- **Match-level:** Log Loss (Ignorance score) — most sensitive discriminator
- **Tournament-level:** TRPS (Tournament RPS) — the only true tournament prediction metric
- **Calibration:** ECE — required for trust in probability outputs

**Secondary metrics:**
- **Brier Score** — for comparability with published benchmarks
- **Champion probability accuracy** — how often does the top-probability team actually win?
- **Stage probability accuracy** — how well do stage probabilities match actual progression?

**Reporting structure:**
```
Validation Report:
  ┌─ Match-level
  │   ├── Log Loss: 0.871 (vs baseline 0.895)
  │   ├── Brier: 0.198
  │   └── ECE: 0.042 (threshold: <0.03 = good, <0.05 = acceptable)
  │
  ├─ Tournament-level
  │   ├── TRPS: 0.234
  │   ├── Champion rank: 2 (predicted #2, actual champion)
  │   └── Stage accuracy: 68% (teams whose stage prediction was within 1 round)
  │
  └─ Calibration
      └── Reliability diagram (10-bin plot)
```

### Computational Cost

Negligible. All metrics are O(n) or O(n²) on the team count (36).

### Engineering Complexity

Low. All metrics are already partially implemented (evaluation.py has Brier, LogLoss, ECE). TRPS and stage metrics are new but straightforward.

### Risk

- TRPS requires ground-truth tournament rankings (available for completed seasons but not for live predictions)
- Log Loss can be numerically unstable when p → 0 on actual outcomes (clipping needed)
- No single metric captures both match-level and tournament-level accuracy

### References

- Ekstrøm et al. (2021) — "Evaluating one-shot tournament predictions" (JSA)
- Wheatcroft (2021) — "Evaluating probabilistic forecasts... the case against RPS" (JQAS)
- Penaltyblog — "Better Metrics for Football Forecasts" (2025)
- Waghmare & Ziegel (2026) — "Proper Scoring Rules for Estimation and Forecast Evaluation"

---

## R-09: Market Integration

### Current State

Market odds are fetched in `--validate` mode (BSD odds with vig removal) and compared against Elo predictions. They are never used as a signal or calibration baseline.

### Research Findings

#### Integration Strategies

| Strategy | Description | Pros | Cons | Used By |
|----------|-------------|------|------|---------|
| **Independent comparison** | Model predictions shown alongside market odds | Simple; transparent | No synergy | Current system |
| **Calibration baseline** | Market odds as target for Platt/isotonic calibration | Calibrates to market efficiency; simple | Defers to market; may miss model-only edge | SportSignals, most pro systems |
| **Blended signal** | Model probability + market odds as weighted feature | Captures both model and market information | Weights must be calibrated; correlation issues | jdgoated1 (stacked), MatchOracle |
| **Primary predictor** | Market odds as the main prediction, model adds edge | Market is the most efficient single source | Model becomes noise-finder; may not add value | Some betting systems |
| **Bayesian fusion** | Market odds as prior, model as likelihood | Principled uncertainty integration | Complex; requires Bayesian framework | Academic approach |

#### Key Findings

- **jdgoated1/football-predictor**: Stacked ensemble without odds: RPS 0.203. Stacked + odds: RPS 0.198. Market alone: RPS 0.195. The model + odds blended is close to the market but does not beat it.

- **SportSignals methodology (2026)**: "Market odds used as a calibration signal, not a substitute for the model's own view." Their engine: ensemble model → recalibrated against current market odds → output. "This step does not blindly defer to bookmakers. It anchors the model's output to the live betting market."

- **ImpliedScore.com (2026)**: Analysis of 19,381 matches across 5 leagues found maximum calibration gap is 6.0pp (La Liga heavy favourites: 81.1% actual vs 75.0% implied). Most leagues: 2-3pp gaps. Conclusion: market odds are remarkably well-calibrated but not perfect.

- **Bayesian study (ScienceDirect, 2026)**: "Betting odds are the most reliable source of information for predicting sports performances."

### Recommendation

**Three-tier market integration:**

1. **Calibration baseline (immediate):** Use Pinnacle/Best-available closing odds as calibration target for Platt/temperature scaling. This anchors model probabilities to market efficiency.

2. **Blended signal (medium-term):** Add market-implied probability as one input to the weighted ensemble (R-04). Initial weight: ~30-40% based on published results (market odds have ~2-3x the predictive power of single-feature Elo).

3. **Value detection (long-term):** Compute model minus market probability. Positive value → model identifies mispriced outcome. This is the most actionable output for betting applications.

**Implementation for calibration baseline:**
```
For each match in validation set:
    market_implied = remove_vig(odds_home, odds_draw, odds_away)
    model_prob = predict(match)
    calibrator.fit(model_prob, market_implied)
    calibrated_prob = calibrator.transform(model_prob)
```

### Computational Cost

Negligible. Vig removal is O(1). Calibration fitting is O(n) on validation set size.

### Engineering Complexity

Low. `remove_vig` already exists in `football_core.predictors.odds`. A calibration fit step already exists conceptually in R-05.

### Risk

- Market odds are not available for all competitions or in real-time without an active API subscription
- Calibrating to market odds makes the model a market-follower, which is fine for prediction but poor for edge detection
- Different bookmakers have different margins; Pinnacle is the sharpest but may not be available via BSD
- Odds move significantly between opening and closing; which timestamp to use matters

### References

- jdgoated1/football-predictor (GitHub)
- SportSignals — Methodology page
- ImpliedScore.com — Market Calibration study (2026)
- FootballGPT/football-model — betting layer architecture

---

## R-10: Explainability

### Current State

The system outputs probabilities with zero explanation. "Arsenal 68.8%" appears without context about which signals contributed.

### Research Findings

#### Explainability Methods

| Method | Level | Description | Pros | Cons |
|--------|-------|-------------|------|------|
| **SHAP** | Local + Global | Shapley values from game theory per feature per prediction | Theoretically grounded; model-agnostic; additive | Computationally expensive for tree models; XGBoost-optimized |
| **LIME** | Local | Local linear approximation around each prediction | Simple; fast | Unstable; linear approximation may be poor in high dimensions |
| **Feature importance (permutation)** | Global | Drop in accuracy when feature is permuted | Simple; model-agnostic | Global only; no per-prediction breakdown |
| **Partial dependence plots** | Global | Model output vs single feature, marginalised | Visual; intuitive | Ignores feature interactions; 2D only |
| **Accumulated Local Effects (ALE)** | Global | Feature effect with reduced bias from correlated features | Unbiased when features are correlated | Less intuitive than PDP |
| **Counterfactual explanations** | Local | "What would change if Elo were 50 points lower?" | Highly intuitive; actionable | Requires multiple model evaluations |
| **Contribution breakdown** | Local | Simple additive breakdown: "Elo contributed +12%, Market odds −5%, Form +3%" | Easy to implement; no external lib | Only valid if model is linear/weighted |

#### Key Implementations

- **Cavidan-oss/XAI-Soccer (2025)**: Replicates live win-probability mechanism. Explains using SHAP and LIME per match per minute. Streamlit dashboard with what-if simulations.

- **Chaudhary521/Football_Match_Outcome_Prediction (2026)**: 10 European leagues, 150+ features, XGBoost. SHAP and LIME analysis revealing key predictive factors.

- **SoccerPredictAI**: Quarterly Quarto reports with SHAP feature importance, calibration curves, and ROI simulations integrated into the pipeline.

- **MatchOracle**: Full SHAP integration as part of feature analysis pipeline. Feature breakdown by group (Elo, Pi-ratings, rolling form, market intelligence, momentum).

### Recommendation

**Tiered explainability based on audience:**

**Tier 1 — Signal Contribution (end users, always-on):**
For a given prediction "Arsenal 68.8% champion":
```
Signal breakdown:
  Elo rating:        +31%  (2064, highest in competition)
  Market odds:       +22%  (implied 25% from Pinnacle)
  Synthetic fixtures:  +12%  (5 of 8 matches against weak opponents)
  Form (recent):     +3%   (W4 D1 L1 in last 6)
  Uncertainty:       -6%   (model uncertainty: ±12% at 95% CI)
  ─────────────────────────────────
  Final probability: 68.8%
```

Implementation: simple additive breakdown from the weighted ensemble. No SHAP needed — the ensemble weights already provide this decomposition.

**Tier 2 — Feature-Level (analysts, on-demand):**
- SHAP summary plot showing which features drive predictions globally
- Per-match breakdown: "Why is Arsenal favored over PSG in this match?"
- Calibration reliability diagram: "How often do 70% predictions actually happen?"

**Tier 3 — Counterfactual (advanced, what-if):**
- "What if Arsenal's Elo were 1960 (equal to PSG)?" → probability drops to ~12%
- "What if Arsenal had actual fixtures instead of synthetic?" → probability drops to ~25%
- "What if Saka is injured?" → probability drops ~5%

### Engineering Complexity

- Tier 1: Low (already computed — ensemble weights are the explanation)
- Tier 2: Medium (SHAP requires the full model pipeline to generate feature vectors)
- Tier 3: Medium (counterfactuals require re-running the simulation with modified inputs)

### Risk

- SHAP requires access to the model's internal feature representation. With a weighted ensemble of signals (not a single ML model), SHAP may not be directly applicable.
- Counterfactuals are computationally expensive (each what-if requires a full MC simulation).
- Over-explaining may erode user trust if explanations highlight model weaknesses.

### References

- Cavidan-oss/XAI-Soccer (GitHub)
- Chaudhary521/Football_Match_Outcome_Prediction (GitHub)
- SHAP (Lundberg & Lee, 2017)
- LIME (Ribeiro et al., 2016)

---

## R-11: Production Architecture

### Current State

Monolithic module: CLI entry point → Monte Carlo loop → display. No separation between data, model, or serving layers.

### Research Findings

#### Reference Architectures

**SoccerPredictAI (2026)** — End-to-end MLOps system:
```
Raw scrape (Airflow + Selenoid)
    → PostgreSQL
    → DVC pipeline (DVC-tracked artifacts)
        → Preprocessing (Great Expectations validation gates)
        → Feature engineering (deterministic, parameterized)
        → Temporal split
        → Training (XGBoost, hyperparameter tuning)
        → Calibration
    → MLflow Registry (smoke → candidate → champion)
    → FastAPI + Celery serving (K8s)
    → Redis cache
    → Prometheus metrics + Evidently drift monitoring (daily)
    → 2 Grafana dashboards
```

**Sportsbook Platform (BetForge, 2026):**
```
Modular monolith:
    - User/session management
    - Bet management
    - Live odds and market management
    - Risk/fraud monitoring
PostgreSQL (business data)
ClickHouse (analytical data)
RabbitMQ (async events)
```

**Streaming Architecture (Freerdps, 2026; Data Fabric, 2026):**
```
Kafka (event bus)
    → Flink/Spark Streaming (real-time features)
        → Feature Store (Feast: Redis online + Delta offline)
            → Model serving (KServe/BentoML)
                → WebSocket push to clients
```

#### Layering Pattern (industry consensus)

```
┌─────────────────────────────────────────────────┐
│                 API / CLI Layer                    │
├─────────────────────────────────────────────────┤
│              Orchestration Layer                   │
├─────────────────────────────────────────────────┤
│  Ingestion  │  Features  │  Prediction  │  Eval  │
├─────────────────────────────────────────────────┤
│              Storage / Cache Layer                │
├─────────────────────────────────────────────────┤
│           External Data Providers                 │
└─────────────────────────────────────────────────┘
```

### Recommendation

**For this project's scale (personal/small-team, not sportsbook):** A **modular monolith** with clear internal boundaries, NOT microservices.

#### Proposed Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     CLI (click/typer)                     │
│   ucl-predict, wc-predict, euro-predict                   │
├─────────────────────────────────────────────────────────┤
│                 Orchestration (orchestrator.py)            │
│   Mode routing, data flow, result assembly                │
├──────────┬──────────┬──────────┬──────────┬──────────────┤
│ Fixture  │ Signal   │ Ensemble │ Monte    │ Validation   │
│ Provider │ Registry │ Engine   │ Carlo    │ & Metrics    │
│          │          │          │ Engine   │              │
├──────────┴──────────┴──────────┴──────────┴──────────────┤
│                    football_core (existing)                │
│   elo, groups, knockout, constants, evaluation             │
├──────────────────────────────────────────────────────────┤
│                    Storage Layer                           │
│   fixtures.json (repo), cache.db (SQLite/Redis),           │
│   prediction_history.json, calibration_params.json         │
└──────────────────────────────────────────────────────────┘
```

**Key design decisions:**

1. **FixtureProvider interface** — abstracts fixture source (BSD, repo, replay). Returns canonical `FixtureSchedule` dataclass.

2. **SignalRegistry** — plugin architecture for signals. Each signal is a class with `predict(match, context) → Probability` method. New signals added as new classes, not modifications to existing code.

3. **EnsembleEngine** — takes list of (signal, weight), computes weighted probability. Configurable via JSON/YAML.

4. **CalibrationPipeline** — separates calibration fitting from inference. Fitted on historical data, stored as params, applied during inference.

5. **ValidationSuite** — runs all three validation tiers (cross-tournament, walk-forward, replay) on demand. Produces structured report (JSON + HTML).

6. **Storage abstraction** — cache layer behind a simple interface. Currently file-based, replaceable with Redis/SQLite without changing business logic.

### Engineering Complexity

Medium-High. The modular monolith is achievable for a single developer. The key is disciplined interface design — each module depends on abstractions, not concrete implementations.

### Risk

- Over-engineering for a project that may not need streaming infrastructure or MLOps tooling
- Abstraction overhead before the requirements are stable
- Feature store and streaming architecture are premature at this scale

### References

- SoccerPredictAI — End-to-end MLOps architecture docs (2026)
- BetForge — Sportsbook Platform Architecture (2026)
- Data Fabric — Streaming Sports Predictions architecture (2026)
- smart-labs.cloud — Reproducible Sports AI Pipelines (2026)
- Honeybadger-139/sports-analytics-intelligence (GitHub)

---

## Conclusion

### Priority Ranking

| Priority | Topic | Why | Dependencies | Est. Complexity |
|----------|-------|-----|-------------|-----------------|
| 1 | **R-05: Probability Calibration** | Biggest quality impact per unit effort. Temperature scaling fixes the overconfidence problem directly. | None (works with existing Elo-only output) | Low |
| 2 | **R-01: Official Fixture Ingestion** | Remove the single biggest source of invalidity. BSD fixtures as primary input. | None (BSD already integrated for validate) | Low-Medium |
| 3 | **R-02: Simulation Modes** | Enables replay and live conditioning. Unlocks validation and calibration. | R-01 (needs fixture source abstraction) | Medium |
| 4 | **R-07: Tournament Validation** | Without proper validation, all improvements are untested. Cross-tournament backtest is the only valid protocol. | R-02 (needs replay mode for historical backtest) | Medium |
| 5 | **R-03: Predictive Signals (immediate)** | Market odds + refined Elo + form features. Addresses the single-signal bottleneck. | None (each signal is independent) | Low-Medium per signal |
| 6 | **R-04: Signal Blending** | Required once multiple signals exist. Weighted averaging is sufficient. | R-03 (needs signals to blend) | Low |
| 7 | **R-06: Uncertainty Modelling** | Bayesian Elo propagates uncertainty through the pipeline. Prevents overconfidence structurally. | R-03 (Bayesian Elo replaces point Elo) | Low-Medium |
| 8 | **R-09: Market Integration** | Calibration baseline and blended signal. High value if BSD odds are reliable. | R-04 (blending), R-05 (calibration) | Low |
| 9 | **R-08: Evaluation Metrics** | TRPS and tiered validation improve measurement but don't change outputs. | R-07 (needs validation framework to compute TRPS) | Low |
| 10 | **R-10: Explainability** | User-facing feature. Important for trust but no impact on accuracy. | R-04 (ensemble weights are the explanation) | Low-Medium |
| 11 | **R-11: Production Architecture** | Long-term maintainability. Premature at this stage — modular monolith is sufficient. | All others (architecture should reflect actual needs) | Medium-High |

### Dependencies Between Topics

```
R-01 (Fixtures) → R-02 (Modes) → R-07 (Validation)
                                     ↓
R-03 (Signals) → R-04 (Blending) → R-09 (Market)
     ↓               ↓                ↓
R-06 (Uncertainty)  R-05 (Calibration)
                      ↓
                    R-08 (Metrics)

R-10 (Explainability) → depends on R-04 (blending weights)

R-11 (Architecture) → orchestrates all others
```

### Topics that Should Become Separate Implementation Phases

| Topic | Phase Type | Why Separate? |
|-------|-----------|---------------|
| R-01 + R-02 | Single phase | Fixture ingestion and modes share the FixtureProvider interface |
| R-03 (signals) | Multi-signal phase (sub-phases per signal) | Each signal is independently developable and testable |
| R-04 + R-05 + R-06 | Single calibration phase | Blending, calibration, and uncertainty are tightly coupled |
| R-07 + R-08 | Single validation phase | Metrics and validation framework share the evaluation pipeline |
| R-09 | Separate phase | Market integration has external API dependencies |
| R-10 | Separate phase | Pure UI/UX — no prediction quality impact |
| R-11 | Infrastructure phase | Should be the last phase, wrapping existing components |

### Estimated Implementation Complexity (Cumulative)

| Phase Set | Complexity | Person-Weeks (est.) | Dependencies |
|-----------|-----------|-------------------|--------------|
| Fixtures + Modes | Medium | 2-3 | None |
| Signals (3 signals) | Low-Medium per signal | 1-2 per signal | None |
| Blending + Calibration + Uncertainty | Medium | 3-4 | Signals |
| Validation + Metrics | Medium | 2-3 | Replay mode |
| Market Integration | Low-Medium | 1-2 | Blending, Calibration |
| Explainability | Low-Medium | 1-2 | Blending |
| Architecture | Medium-High | 2-4 | All others |
| **Total** | | **~15-25 person-weeks** | |

### Expected Impact on Prediction Quality

| Change | Expected Δ Log-Loss | Expected Δ ECE | Expected Δ Champion Accuracy |
|--------|---------------------|----------------|------------------------------|
| Temperature calibration alone | −0.02 to −0.05 | −0.10 to −0.15 | +5-10% (less overconfident) |
| Real BSD fixtures | −0.01 to −0.02 | −0.02 to −0.05 | +5-15% (valid comparison) |
| Market odds as signal | −0.03 to −0.05 | −0.03 to −0.05 | +10-20% |
| Refined Elo + form | −0.01 to −0.02 | −0.01 to −0.02 | +2-5% |
| Bayesian Elo (uncertainty) | −0.01 | −0.03 to −0.08 | +3-8% |
| Replay validation + metrics | N/A (measurement) | N/A | Improved visibility |
| **Cumulative (all changes)** | **−0.08 to −0.15** | **−0.15 to −0.30** | **+15-40%** |

*Baseline: current Elo-only model with ~1.0 log-loss and ~0.20 ECE (estimated). Target: <0.85 log-loss and <0.05 ECE.*

### Risks If Skipped

| Topic | Risk of Skipping |
|-------|-----------------|
| R-01 | Predictions remain invalidly compared against real outcomes; synthetic fixtures compound all other errors |
| R-02 | Cannot validate against history; cannot run mid-tournament; fixture provider abstraction is half-built |
| R-03 | Single-signal model remains fragile and overconfident |
| R-04 | Multiple signals produce contradictory probabilities with no resolution |
| R-05 | Probabilities remain systematically overconfident; all downstream users (human or automated) are misled |
| R-06 | Model cannot express uncertainty about its own estimates; false precision erodes trust |
| R-07 | Cannot measure whether the system actually improves; no scientific basis for claiming accuracy |
| R-08 | Improvements are invisible; wrong metrics lead to wrong optimization targets |
| R-09 | Model ignores the most informative single signal (market odds); misses edge detection capability |
| R-10 | Users see numbers with zero context; "why 68.8%?" is unanswerable |
| R-11 | Technical debt accumulates; each feature becomes harder to add; module boundaries blur |

---

*Research completed 2026-06-29. This document does not contain implementation plans, phase numbers, or code modifications. All conclusions are recommendations requiring further design validation.*
