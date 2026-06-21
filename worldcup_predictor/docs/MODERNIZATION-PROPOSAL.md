# Prediction Engine Modernization Proposal

> **Status:** Architecture proposal — Phases 11-12b implemented, Phase 13-18 pending.
> **Based on:** Comprehensive audit in RESPONSE.md (2026-06-15).
> **Target:** v2.0 Enhanced Analytics milestone.
> **Completed:** Phases 11 (Data Integrity & Elo Foundation), 12 (Draw Handling & Elo Math), and 12b (Evaluation Infrastructure) are now implemented.

---

## Table of Contents

1. Signal Inventory
2. Current Model vs Target Model
3. Model Design
4. Elo Replacement Strategy
5. Market Odds Integration
6. CatBoost Integration
7. Player-Level Model
8. Model Governance
9. ROI Analysis
10. Final Recommendation
11. GSD Workflow Impact

---

## 1. Signal Inventory

Every BSD signal available under the current free subscription.

### 1.1 Match Results (Currently Used)

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/events/?league_id=27&limit=200` |
| **Refresh** | Real-time (sub-second after match ends) |
| **History** | Full tournament history from `date_from` filter |
| **Coverage** | All World Cup 2026 matches |
| **Reliability** | High — BSD is primary data source for this tournament |
| **Prediction Value** | Foundational — this is the ground truth for results |
| **Used?** | ✅ Yes — main polling loop + historical catch-up |

### 1.2 Market Odds

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/events/{id}/odds/comparison/` |
| **Refresh** | Every ~30 seconds for live, periodic for upcoming |
| **History** | Available at time of query (no historical archive advertised) |
| **Coverage** | All World Cup matches with active betting markets |
| **Reliability** | High — 14 bookmakers + Polymarket |
| **Prediction Value** | **Critical** — market-implied probabilities are efficient aggregators |
| **Used?** | ❌ No |

**Bookmakers available:** Pinnacle, Bet365, Betano, 1xBet, and 10+ more. Plus Polymarket prediction markets. All in decimal odds format.

### 1.3 CatBoost Predictions

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/v2/predictions/` |
| **Refresh** | Pre-match (available before kickoff) |
| **History** | 5,211 predictions and counting |
| **Coverage** | All World Cup matches |
| **Reliability** | Medium-High — CatBoost gradient boosting, calibrated against market implied |
| **Prediction Value** | **Critical** — 8 calibrated markets: 1X2, O/U 1.5/2.5/3.5, BTTS, most-likely score |
| **Used?** | ❌ No |

The BSD docs explicitly state: *"Probabilities calibrated against market implied — not raw model output."* This means the CatBoost predictions are already adjusted to match market efficiency, making them more reliable than raw model output.

### 1.4 Player Statistics

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/player-stats/?player=&event=&team=` |
| **Refresh** | Post-match (per-match stats available after match ends) |
| **History** | 139,000+ per-match player statistics |
| **Coverage** | All World Cup matches with tracked players |
| **Reliability** | Medium — data quality varies by league |
| **Prediction Value** | **High** — form, goals, assists, xG, xA, passes, tackles per player |
| **Used?** | ❌ No |

### 1.5 Player Profiles

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/players/?team=&nationality=&position=` |
| **Refresh** | Static (updated periodically) |
| **History** | 8,900+ player profiles |
| **Coverage** | All World Cup squads |
| **Reliability** | High — structured data with market values |
| **Prediction Value** | **High** — position, market value, nationality for team composition |
| **Used?** | ❌ No |

### 1.6 xG Shot Maps

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/events/{id}/stats/` |
| **Refresh** | Post-match |
| **History** | 15,303 matches enriched |
| **Coverage** | All World Cup matches |
| **Reliability** | Medium-High — per-shot (x,y) coordinates with xG values |
| **Prediction Value** | **High** — reveals over/underperformance (xG vs actual goals) |
| **Used?** | ❌ No |

### 1.7 Goal Build-Up Sequences

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/events/{id}/incidents/` |
| **Refresh** | Post-match |
| **History** | Available for enriched matches |
| **Coverage** | Goal events in tracked matches |
| **Reliability** | Medium — depends on data completeness |
| **Prediction Value** | Medium — tactical pattern recognition |
| **Used?** | ❌ No |

### 1.8 Live Statistics

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /api/live/?tz=` |
| **Refresh** | Real-time during matches |
| **History** | Current live matches only |
| **Coverage** | Live World Cup matches |
| **Reliability** | High — real-time official statistics |
| **Prediction Value** | Medium — in-play momentum signals |
| **Used?** | ❌ No |

### 1.9 Team Form / Standings

| Property | Value |
|----------|-------|
| **Endpoint** | Not directly available (would need to aggregate from /events/) |
| **Refresh** | N/A — computed |
| **History** | N/A — computed from event history |
| **Coverage** | All teams |
| **Reliability** | High if derived from match results |
| **Prediction Value** | High — recent form (last 5 matches) is a proven predictor |
| **Used?** | ❌ No (not tracked explicitly) |

### 1.10 Predicted Lineups

| Property | Value |
|----------|-------|
| **Endpoint** | Included in match data (AI-generated before kickoff) |
| **Refresh** | Pre-match |
| **History** | Available from match data |
| **Coverage** | All World Cup matches |
| **Reliability** | Medium — AI-predicted, not confirmed |
| **Prediction Value** | Medium — confirms key player availability |
| **Used?** | ❌ No |

### 1.11 Possession, Shots, Cards, Corners

| Property | Value |
|----------|-------|
| **Endpoint** | Included in match events and live data |
| **Refresh** | Post-match / real-time |
| **History** | Available from match data |
| **Coverage** | All World Cup matches |
| **Reliability** | High — standard match statistics |
| **Prediction Value** | Low-Medium — marginally predictive for match outcomes |
| **Used?** | ❌ No |

### 1.12 WebSocket Live Feed ($3/mo addon)

| Property | Value |
|----------|-------|
| **Endpoint** | `wss://sports.bzzoiro.com/ws/live/` |
| **Refresh** | Every 5 seconds (ball trajectories), 30 seconds (odds) |
| **History** | No history — live only |
| **Coverage** | Live matches |
| **Reliability** | High — low-latency dedicated stream |
| **Prediction Value** | Medium — in-play dynamics, but requires real-time processing |
| **Used?** | ❌ No (paid addon) |

### Current Signal Utilization

| Status | Count | Signals |
|--------|-------|---------|
| ✅ Used | 1 | Match results |
| ❌ Unused Critical | 2 | Market odds, CatBoost predictions |
| ❌ Unused High | 4 | Player stats, xG, team form, predicted lineups |
| ❌ Unused Medium | 3 | Live stats, incidents, possession/shots/cards |
| ❌ Unused Low | 2 | Player profiles (except for form), WebSocket |

**Critical finding:** 2 of the 3 most valuable signals (market odds, CatBoost) are completely unused. The project is running a single-signal model when three independent signals are free and available.

---

## 2. Current Model vs Target Model

### 2.1 Current Model

```
                    ONE SIGNAL → SIXTY-THREE PERCENT WRONG
                    ┌──────────────────────────────────────┐
                    │           teams.json                  │
                    │  (48 teams, 63% wrong Elo values)     │
                    └──────────┬───────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   elo.py             │
                    │  expected_score(Δ)   │
                    │  update_ratings()    │
                    └──────────┬───────────┘
                               │ P(win) per match
                               ▼
                    ┌──────────────────────┐
                    │  groups.py           │
                    │  Poisson(λ=Elo→goals)│
                    │  72 matches          │
                    └──────────┬───────────┘
                               │ group standings
                               ▼
                    ┌──────────────────────┐
                    │  knockout.py         │
                    │  run_full_simulation │
                    │  50,000 iterations   │
                    └──────────┬───────────┘
                               │ champion counts
                               ▼
                    ┌──────────────────────┐
                    │  Champion Probability │
                    │  (48 teams, 4 decimals)│
                    └──────────────────────┘

            SINGLE POINT OF FAILURE:
            If Elo is wrong → everything is wrong.
            63% of teams have wrong Elo.
```

**Key limitations:**
- Single signal (Elo) determines every probability
- No secondary validation of probabilities
- Elo values are hand-typed and 63% wrong
- No player-level factors
- No market sentiment
- No ML cross-reference
- Dynamic Elo applies to only 4 of 48 teams
- Draws are skipped entirely
- Goal-difference K multiplier is not implemented

### 2.2 Target Model

```
                    THREE INDEPENDENT SIGNALS + CONTEXT LAYER
                    ┌──────────────────────────────────────────────┐
                    │           BSD API                            │
                    ├──────────┬──────────┬───────────┬────────────┤
                    │ Events   │ Odds     │ Predictions│ Player     │
                    │ (results)│ (14books)│ (CatBoost) │ Stats      │
                    └────┬─────┴────┬─────┴─────┬─────┴─────┬──────┘
                         │          │           │           │
                         ▼          ▼           ▼           ▼
                    ┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
                    │ Elo    │ │ Market │ │ CatBoost │ │ Form     │
                    │ Engine │ │ Odds   │ │ ML Model │ │ & xG     │
                    │ (auto) │ │ (vig-  │ │ (8 mkt)  │ │ Strength │
                    │        │ │free)  │ │          │ │          │
                    └───┬────┘ └───┬────┘ └────┬─────┘ └────┬─────┘
                        │          │           │            │
                        ▼          ▼           ▼            ▼
                    ┌──────────────────────────────────────────┐
                    │         CALIBRATION LAYER                 │
                    │  Platt scaling per signal (historical)     │
                    │  Ensures P(win) ≈ actual win frequency    │
                    └──────────────────┬───────────────────────┘
                                       │ calibrated probabilities
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │         SIGNAL BLENDER                    │
                    │  Dynamic weighting: w_elo, w_odds, w_ml   │
                    │  Weights ∝ recent Brier score improvement │
                    └──────────────────┬───────────────────────┘
                                       │ blended P(win) per match
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  TOURNAMENT STATE                        │
                    │  Group standings (real results injected)  │
                    │  Player availability (injuries/susp.)     │
                    │  R32 bracket position                    │
                    └──────────────────┬───────────────────────┘
                                       │ conditioned probabilities
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  MONTE CARLO ENGINE                      │
                    │  50,000 iterations                       │
                    │  Poisson scoring (Elo-to-goals calibrated)│
                    │  Goal-difference K multiplier active     │
                    └──────────────────┬───────────────────────┘
                                       │ champion counts
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Champion Probability                    │
                    │  + calibration confidence interval       │
                    │  + signal contribution breakdown         │
                    └──────────────────────────────────────────┘


                    ERROR PROPAGATION:
                    Elo wrong → market odds disagree → flag raised
                    CatBoost disagrees with Elo → flag raised
                    Three independent signals = error detection
```

---

## 3. Model Design

### 3.1 Design Decision

**Chosen approach: Calibration Layer + Dynamic Weighted Ensemble**

Not Bayesian update. Not meta-model. Here's why.

### 3.2 Why Not Bayesian Update

A Bayesian update would treat each signal as an independent likelihood:

```
P(win | Elo, Odds, ML) ∝ P(win) * P(Elo|win) * P(Odds|win) * P(ML|win)
```

**Problem:** The signals are NOT independent. Market odds incorporate Elo-like information. CatBoost is trained on the same match data that produces Elo ratings. Treating them as independent would cause over-counting — effectively squaring the same information.

If Elo says 70%, odds say 65%, and CatBoost says 68%, a Bayesian update assuming independence would produce something like 85% — overconfident.

### 3.3 Why Not Meta-Model

A meta-model (logistic regression over features: Δelo, odds_implied_prob, catboost_prob, recency_form, xG_diff, etc.) would be the most flexible approach. But:

**Limited training data:** A World Cup has 64 matches (104 with group stage). For a 10-feature model, that's ~6.4 matches per feature — severe overfitting risk. Historical World Cups could expand the dataset to ~500 matches across 8 tournaments, but tournament formats change (24→32→48 teams), making cross-tournament features noisy.

**Black box concern:** The current project is transparent — you can trace why Spain's probability changed. A meta-model loses this. For a terminal-based predictor, traceability matters.

**Maintenance burden:** Meta-model needs periodic retraining, feature engineering, and monitoring. This is appropriate for a production ML pipeline but overkill for a CLI tool.

### 3.4 Why Calibration Layer + Dynamic Weighted Ensemble

```
For each match:

Step 1: Get P_elo from expected_score(rating_a, rating_b)
Step 2: Get P_odds from market odds (vig-removed)
Step 3: Get P_ml from CatBoost prediction

Step 4: Calibrate each (if calibration data exists):
    P_cal_elo  = calibrate(P_elo,  calibration_curve_elo)
    P_cal_odds = calibrate(P_odds, calibration_curve_odds)
    P_cal_ml   = calibrate(P_ml,   calibration_curve_ml)
    
Step 5: Blend:
    P_blended = w_elo * P_cal_elo + w_odds * P_cal_odds + w_ml * P_cal_ml

Where weights are updated periodically based on Brier score:

    w_i = (1 / Brier_i) / Σ(1 / Brier_j)  for all signals j
```

**Why this works:**

1. **Calibration addresses systematic bias.** If Elo consistently predicts 70% when the actual win rate is 65%, Platt scaling corrects this. Without calibration, blending magnifies bias.

2. **Dynamic weighting adapts to signal quality.** If CatBoost becomes less accurate mid-tournament (concept drift), its weight automatically decreases. If market odds tighten as the tournament progresses, their weight increases.

3. **Transparency.** Each signal's contribution is explicitly visible. You can report "Spain's 34.2% champion probability: Elo contributed 18%, odds contributed 12%, ML contributed 4%."

4. **No independence assumption.** The weighting is additive, not multiplicative. Over-counting doesn't occur.

5. **Simple to implement and maintain.** No ML dependencies, no training pipeline, no hyperparameter tuning.

### 3.5 Calibration Method: Platt Scaling

For each signal, collect historical predictions and actual outcomes:

```
Predictions: [0.3, 0.7, 0.6, 0.4, ...]
Outcomes:    [0,   1,   1,   0,   ...]  (1 = team A won)
```

Fit a logistic regression (Platt scaling):

```
P_cal = 1 / (1 + exp(A * logit(P_raw) + B))
```

Where `A` and `B` are fitted parameters. This corrects systematic over/underconfidence without distorting the ranking.

If insufficient historical data (< 100 predictions), skip calibration and use raw probabilities with a flat weight penalty (penalize signals with less history).

### 3.6 Weight Update Strategy

| Trigger | Action |
|---------|--------|
| After each match with a prediction | Update Brier score for each signal |
| Every 10 matches | Recompute weights from cumulative Brier scores |
| Tournament start | Equal weights (0.33 each) until calibration data exists |
| Signal missing (no odds for this match) | Redistribute weight among remaining signals |
| Signal fails repeatedly (5+ errors) | Decay weight to 0, flag for investigation |

### 3.7 Edge Case: Conflicting Signals

When signals strongly disagree (e.g., Elo says 80%, odds say 30%):

1. **Do not average — investigate.** Report the disagreement with a confidence interval.
2. **Widen the probability range.** Instead of a point estimate, report `[low, high]` from the ensemble range.
3. **Flag in output.** Display a `⚠` marker next to high-variance predictions.

This turns signal disagreement from a bug into a feature — it tells the user "something unusual is happening with this match."

### 3.8 When Sufficient Data Exists

After ~500 historical matches (about 5 World Cups worth), the calibrated ensemble can be replaced with a logistic regression meta-model trained on:

- Log-odds of each signal's prediction
- Signal disagreement (std dev of predictions)
- Tournament stage (group vs knockout)
- Elo difference
- Recency-weighted form
- xG differential (from player stats)

This would capture non-linear interactions that the simple ensemble misses. But this is a v2.2 enhancement at earliest — the ensemble is sufficient for v2.0.

---

## 4. Elo Replacement Strategy

### 4.1 Current Problem

Elos are hand-typed, 63% wrong, and only 4 of 48 have been updated by dynamic Elo. This must be replaced with an automated, verified pipeline.

### 4.2 Source of Truth

**eloratings.net is the source of truth.** Not teams.json. Not FIFA rankings. eloratings.net provides the canonical values that the system uses.

### 4.3 Automated Refresh Process

```
Every N minutes:
    │
    ├── 1. FETCH current Elo ratings from eloratings.net
    │      (Parse HTML table or use international-football.net mirror)
    │      Extract: team_name → elo_rating for all 48+ teams
    │
    ├── 2. COMPARE with current teams.json values
    │      For each team:
    │        if abs(eloratings_value - teams_json_value) > threshold:
    │          flag for review
    │
    ├── 3. UPDATE if drift exceeds tolerance
    │      tolerance = 5 points (eloratings.net updates are small)
    │      Apply update to in-memory teams dict
    │
    └── 4. LOG every change
         elo_update_log.json:
         {timestamp, team, old_value, new_value, source, reason}
```

Implementation:

```python
import re
import requests

ELORATINGS_URL = "https://www.eloratings.net/"
# Or use the structured mirror: "https://www.international-football.net/elo-ratings-table?day=...&month=...&year=2026"

def fetch_live_eloratings() -> dict[str, float]:
    """Fetch current Elo ratings from eloratings.net.
    
    Returns dict of {team_name: elo_rating}.
    
    Parsing strategy:
    - eloratings.net renders a numbered table
    - Extract: rank, team_name, points
    - Map team_name to project's canonical name via alias lookup
    """
    resp = requests.get(ELORATINGS_URL, timeout=10)
    # Parse HTML to extract team → rating pairs
    # Strategy: find the top-50 table, extract rows
    ...

def sync_eloratings(
    current: dict[str, float],
    live: dict[str, float],
    tolerance: int = 5,
) -> dict[str, float]:
    """Merge live Elo ratings into current with drift detection.
    
    Returns updated ratings dict.
    Logs any change > tolerance for audit.
    """
    updated = dict(current)
    for team, live_elo in live.items():
        if team in updated:
            diff = abs(updated[team] - live_elo)
            if diff > tolerance:
                # Log the change
                ...
                updated[team] = live_elo
        else:
            # New team — add with warning
            updated[team] = live_elo
    return updated
```

### 4.4 Team Name Mapping

The critical challenge: eloratings.net uses different team names than the project.

| Project Name | eloratings.net Name | Risk |
|-------------|--------------------|------|
| United States | USA | Name mismatch |
| Ivory Coast | Côte d'Ivoire | Name mismatch |
| South Korea | Korea Republic | Name mismatch |
| Türkiye | Turkey | Name mismatch |
| Bosnia and Herzegovina | Bosnia & Herzegovina | Name mismatch |
| Cape Verde | Cabo Verde | Name mismatch |

**Solution:** Use the existing `team_aliases.json` for reverse mapping. For each eloratings.net team name → check if any project canonical name matches, or if any alias matches.

```python
def map_elorating_team(
    elo_team_name: str,
    project_teams: dict[str, dict],
    aliases: dict[str, list[str]],
) -> str | None:
    """Map an eloratings.net team name to a project canonical name."""
    # Direct match
    if elo_team_name in project_teams:
        return elo_team_name
    
    # Alias match: check if elo name is anyone's alias
    elo_lower = elo_team_name.strip().lower()
    for canonical, alias_list in aliases.items():
        if elo_lower == canonical.strip().lower():
            return canonical
        for alias in alias_list:
            if elo_lower == alias.strip().lower():
                return canonical
    
    return None
```

### 4.5 Validation Process

After every sync, validate:

1. **All 48 teams present** — if any team is missing, flag and skip sync
2. **No team changed by > 50 points** — if a team changes by > 50, flag for manual review
3. **Total variance** — if the sum of all changes exceeds 200 points, flag for manual review
4. **Integrity check** — verify that `expected_score(a, b) + expected_score(b, a) == 1.0` for all pairs

### 4.6 Drift Detection

```python
def detect_elo_drift(
    current: dict[str, float],
    historical: list[dict[str, float]],
    window: int = 5,
) -> list[str]:
    """Detect teams with unusual Elo movement.
    
    Returns list of team names where Elo changed by > 2σ
    from their typical change magnitude.
    """
    flagged = []
    for team in current:
        changes = []
        for snapshot in historical[-window:]:
            if team in snapshot:
                changes.append(current[team] - snapshot[team])
        if changes:
            mean_change = sum(changes) / len(changes)
            variance = sum((c - mean_change)**2 for c in changes) / len(changes)
            std = variance ** 0.5
            latest_change = changes[-1]
            if abs(latest_change) > 2 * max(std, 3.0):  # floor at 3 points
                flagged.append(team)
    return flagged
```

### 4.7 Manual Entry Ban

**No more hand-typed Elo values.** The `teams.json` file must be treated as a machine-only artifact. Enforce this with:

1. **A startup check** — compare every team's Elo against eloratings.net. If any team differs by > 50 points AND the difference isn't from dynamic Elo updates, warn the user.
2. **A git pre-commit hook** — prevent commits that modify teams.json without a matching elo_update_log.json entry.
3. **Read-only at runtime** — the system never prompts the user to enter an Elo value.

---

## 5. Market Odds Integration

### 5.1 Implied Probability Conversion

Bookmakers quote **decimal odds**. For a match with three outcomes (1X2):

```
Odds: Home=1.85, Draw=3.40, Away=4.50

Implied probabilities (raw):
P_home_raw = 1 / 1.85 = 0.5405
P_draw_raw = 1 / 3.40 = 0.2941
P_away_raw = 1 / 4.50 = 0.2222

Sum = 0.5405 + 0.2941 + 0.2222 = 1.0568 (105.68% — includes vig)
```

### 5.2 Vig Removal (Overround)

Three methods, ranked by sophistication:

**Method 1: Basic normalization (recommended for MVP)**

```
P_home = P_home_raw / sum = 0.5405 / 1.0568 = 0.5115
P_draw = P_draw_raw / sum = 0.2941 / 1.0568 = 0.2783
P_away = P_away_raw / sum = 0.2222 / 1.0568 = 0.2102

Sum = 1.0000 ✓
```

Simple, transparent, works well for matches with standard vig (~5-8%).

**Method 2: Power method (more accurate)**

Assumes vig is distributed proportionally to probability:

```
P_home = P_home_raw^λ / Σ(P_i^λ)
```

Where λ is solved numerically to make Σ(P_i^λ) = 1. Typically λ ≈ 0.95 for football. More accurate than basic normalization when vig is unevenly distributed (e.g., heavy favorite has lower vig).

**Method 3: Shin's method (most accurate)**

Accounts for favorite-longshot bias. Uses a model where bookmakers set odds with a bias parameter. Most accurate but requires iterative solving.

**Recommendation:** Use Method 1 (basic normalization) for MVP. If backtesting shows systematic bias (favorites underperforming odds), upgrade to Method 2.

### 5.3 From Odds to Match Win Probability

The simulator needs a single `P(home wins)` — not three separate probabilities. Two approaches:

**Approach A: Direct win probability**
```
P_home_win = P_home / (P_home + P_away)
```
This drops the draw probability and re-normalizes. Simple but loses information.

**Approach B: Elo-style expected score conversion**
```
odds_implied_strength_home = log(P_home / P_draw)  # log-odds of home vs draw
odds_implied_strength_away = log(P_away / P_draw)  # log-odds of away vs draw
P_home_win = 1 / (1 + exp(odds_implied_strength_away - odds_implied_strength_home))
```
This produces a Elo-compatible win probability that accounts for the draw rate. More accurate but complex.

**Recommendation:** Use Approach A for MVP. The error from dropping the draw is small (~1-2%) compared to the foundational Elo errors.

### 5.4 Blending with Elo for Simulation

The key question: **how should odds influence the Monte Carlo simulation?**

**Option 1: Replace Elo with odds probability**
Use `P_odds` directly in `expected_score()` calls. Simple but discards Elo information entirely.

**Option 2: Blend before match simulation**
```python
P_combined = w_elo * P_elo + w_odds * P_odds
# Use P_combined for sampling
```
This is the calibrated ensemble approach from Section 3.

**Option 3: Use odds as simulation prior, Elo as likelihood**
```python
# Prior: P_odds
# Likelihood: how well Elo predicts given odds-conditional
# Posterior: P_odds * P(elo_outcome | odds)
```
Complex but theoretically principled.

**Recommendation:** Option 2. It's simple, transparent, and the weights can be dynamically adjusted.

### 5.5 Practical Integration

```python
def fetch_match_odds(event_id: str) -> dict | None:
    """Fetch odds for a match from BSD API.
    
    Returns vig-removed probabilities: {home: float, draw: float, away: float}
    or None if odds unavailable.
    """
    resp = requests.get(
        f"https://sports.bzzoiro.com/api/events/{event_id}/odds/comparison/",
        headers={"Authorization": f"Token {API_KEY}"},
    )
    if resp.status_code != 200:
        return None
    
    data = resp.json()
    
    # Collect best available odds across all bookmakers
    home_odds = min(bm["odds"]["home"] for bm in data if bm["odds"]["home"])
    draw_odds = min(bm["odds"]["draw"] for bm in data if bm["odds"]["draw"])
    away_odds = min(bm["odds"]["away"] for bm in data if bm["odds"]["away"])
    
    # Convert to implied probabilities
    p_home = 1.0 / home_odds
    p_draw = 1.0 / draw_odds
    p_away = 1.0 / away_odds
    
    # Vig removal (basic normalization)
    total = p_home + p_draw + p_away
    return {
        "home": p_home / total,
        "draw": p_draw / total,
        "away": p_away / total,
    }


def odds_blended_probability(
    elo_prob: float,
    odds_probs: dict | None,
    weight_elo: float = 0.5,
    weight_odds: float = 0.5,
) -> float:
    """Blend Elo probability with market odds probability.
    
    If odds are unavailable, falls back to Elo alone.
    """
    if odds_probs is None:
        return elo_prob
    
    # Convert odds to win probability (assume elo_prob is P(home wins), not including draw)
    odds_win_prob = odds_probs["home"] / (odds_probs["home"] + odds_probs["away"])
    
    return weight_elo * elo_prob + weight_odds * odds_win_prob
```

### 5.6 When Odds Are Unavailable

| Scenario | Handling |
|----------|----------|
| Match hasn't started yet | Odds usually available 24-48h before kickoff |
| Match is live | Odds update in real-time (every ~30s) |
| Low-market match | May have fewer bookmakers; use any available |
| API rate-limited | Fall back to Elo-only for this polling cycle |
| No bookmakers cover it | Fall back to Elo-only (flag in output) |

If odds are unavailable for > 50% of matches, the ensemble weight should shift toward Elo: `w_elo = 0.7, w_odds = 0.3`.

---

## 6. CatBoost Integration

### 6.1 What BSD's CatBoost Provides

The BSD CatBoost model provides **8 calibrated prediction markets** per match:

| Market | Output | Format |
|--------|--------|--------|
| 1X2 (match result) | P(home), P(draw), P(away) | Three floats summing to 1.0 |
| Over/Under 1.5 | P(o1.5), P(u1.5) | Two floats summing to 1.0 |
| Over/Under 2.5 | P(o2.5), P(u2.5) | Two floats summing to 1.0 |
| Over/Under 3.5 | P(o3.5), P(u3.5) | Two floats summing to 1.0 |
| Both Teams to Score | P(yes), P(no) | Two floats summing to 1.0 |
| Most Likely Score | Scoreline with probability | (score, prob) pair |

Key quote from BSD docs: *"Probabilities calibrated against market implied — not raw model output."*

This means the CatBoost predictions are **already adjusted** to match market efficiency. They are not raw model scores — they are calibrated to be well-calibrated probabilities.

### 6.2 How CatBoost Differs from Elo

| Dimension | Elo | CatBoost |
|-----------|-----|----------|
| **Input** | Historical match results only | Match data + team stats + player data + market data |
| **Time scale** | Long-term team strength | Current-tournament form |
| **Calibration** | Inherits eloratings.net calibration | Explicitly calibrated against market implied |
| **Draw handling** | Not modeled (binary win/loss) | Explicitly predicts P(draw) |
| **Goal scoring** | Not modeled (binary) | Predicts O/U lines, most likely score |
| **Refresh** | After every match | Pre-match (static before kickoff) |
| **Scope** | All 48 teams equally | Per-match predictions |

### 6.3 Blending Approach

CatBoost predictions should be treated as a **third independent signal** in the ensemble:

```python
P_blended = w_elo * P_elo + w_odds * P_odds + w_ml * P_ml
```

Where `P_ml` comes from the CatBoost 1X2 prediction:

```python
def fetch_catboost_predictions(event_id: str) -> dict | None:
    """Fetch CatBoost predictions for a match."""
    resp = requests.get(
        f"https://sports.bzzoiro.com/api/v2/predictions/?event_id={event_id}",
        headers={"Authorization": f"Token {API_KEY}"},
    )
    if resp.status_code != 200:
        return None
    
    data = resp.json()
    # Extract 1X2 probabilities
    return {
        "home": data["home_win_probability"],
        "draw": data["draw_probability"],
        "away": data["away_win_probability"],
    }
```

### 6.4 Mathematical Approach for MVP

Use a simple **log-odds blend** at the match level:

```python
def blend_probabilities(
    elo_prob: float,
    odds_prob: float | None,
    ml_prob: float | None,
    weights: dict[str, float],
) -> float:
    """Blend multiple probability estimates into one.
    
    Uses log-odds averaging to avoid 0/1 boundary issues.
    """
    signals = [("elo", elo_prob)]
    if odds_prob is not None:
        signals.append(("odds", odds_prob))
    if ml_prob is not None:
        signals.append(("ml", ml_prob))
    
    # Convert to log-odds
    log_odds_sum = 0.0
    weight_sum = 0.0
    for name, prob in signals:
        # Clamp to avoid log(0) and log(1)
        prob = max(min(prob, 0.999), 0.001)
        log_odds = math.log(prob / (1.0 - prob))
        w = weights.get(name, 1.0)
        log_odds_sum += w * log_odds
        weight_sum += w
    
    # Convert back to probability
    avg_log_odds = log_odds_sum / weight_sum
    return 1.0 / (1.0 + math.exp(-avg_log_odds))
```

Log-odds averaging preserves the natural behavior of probabilities near 0/1 boundaries and handles extreme values gracefully.

### 6.5 Signal-Specific Weighting

Initial weights (before calibration data exists):

| Signal | Weight | Rationale |
|--------|--------|-----------|
| Elo | 0.4 | Foundational, but 63% of values are wrong |
| Market odds | 0.35 | Efficient aggregation, but unavailable for some matches |
| CatBoost ML | 0.25 | Third-party model, calibrated but less battle-tested |

After calibration data (> 100 predictions per signal):

| Signal | Weight | Rationale |
|--------|--------|-----------|
| Highest Brier score | 0.4+ | Best recent predictor gets largest share |
| Middle | 0.3 | Based on relative performance |
| Lowest | 0.2+ | Worst performer still contributes but less |

---

## 7. Player-Level Model

### 7.1 Problem Statement

The current model treats teams as monolithic Elo ratings. A team with its starting XI available is treated identically to the same team missing three key starters to injury, suspension, or rest.

**Evidence:** In the current tournament, a team resting players for the knockout stage might field a weakened side in the final group match. The simulator doesn't account for this.

### 7.2 Available Data

BSD provides:
- `/api/players/?team=` — squad lists with positions and market values
- `/api/player-stats/?player=&event=&team=` — per-match player performance stats
- AI-predicted lineups (before kickoff) — predicted starting XI + substitutes
- No direct injury/suspension API (would need to infer from lineup changes)

### 7.3 Design: Team Strength Adjustment Factor

Do not simulate individual players. Instead, compute a **team strength multiplier** that adjusts the team's effective Elo:

```
effective_elo = base_elo * lineup_strength_factor
```

Where `lineup_strength_factor` is derived from:

```python
def compute_team_strength_factor(
    predicted_lineup: list[dict],  # [{name, position, market_value, recent_rating}, ...]
    squad: list[dict],             # Full squad
    recent_form: dict,             # {player_id: avg_rating_last_5_matches}
) -> float:
    """Compute a multiplier to adjust team Elo based on lineup strength.
    
    Returns a value where:
    1.0 = full strength (all best players available)
    0.95 = missing 1 key player
    0.90 = missing 2+ key players or star player
    1.05 = unexpected lineup strength (players in form)
    """
    # Method: Compare predicted lineup's market value to squad average
    # If predicted lineup has 80% of squad market value → factor ≈ 0.98
    # If predicted lineup has 60% of squad market value → factor ≈ 0.92
    # ...
```

### 7.4 Implementation Approach

```python
def estimate_lineup_quality(
    predicted_starters: list[str],
    full_squad: dict[str, dict],
) -> float:
    """Estimate quality of predicted starting XI vs full squad.
    
    Uses market value as a proxy for player quality.
    Returns 1.0 if the best XI is on the pitch, < 1.0 if key players are missing.
    """
    if not predicted_starters or not full_squad:
        return 1.0  # No data — assume full strength
    
    # Get market values for each player
    starter_values = [full_squad[p]["market_value"] for p in predicted_starters if p in full_squad]
    squad_values = [p["market_value"] for p in full_squad.values() if p.get("market_value")]
    
    if not squad_values:
        return 1.0
    
    avg_starter = sum(starter_values) / len(starter_values) if starter_values else 0
    avg_squad = sum(squad_values) / len(squad_values) if squad_values else 1.0
    
    if avg_squad == 0:
        return 1.0
    
    ratio = avg_starter / avg_squad
    
    # Map ratio to strength factor
    # This mapping should be calibrated from historical data
    if ratio >= 1.0:
        return 1.0
    elif ratio >= 0.9:
        return 0.98
    elif ratio >= 0.8:
        return 0.95
    elif ratio >= 0.7:
        return 0.91
    else:
        return 0.87
```

### 7.5 Integration with Elo

```python
def adjusted_expected_score(
    team_a: str,
    team_b: str,
    elo_a: float,
    elo_b: float,
    lineup_factor_a: float = 1.0,
    lineup_factor_b: float = 1.0,
) -> float:
    """Expected score with lineup strength adjustment."""
    effective_a = elo_a * lineup_factor_a
    effective_b = elo_b * lineup_factor_b
    return expected_score(effective_a, effective_b)
```

A 5% lineup strength reduction on a 2000-Elo team produces an effective Elo of 1900 — roughly a 64%→36% probability swing against a 2000-Elo opponent. This is a **significant** effect.

### 7.6 Practical Considerations

| Concern | Mitigation |
|---------|------------|
| **Market value ≠ player quality** | True, but it's the best available proxy. Add recent form as secondary signal. |
| **Predicted lineups may be wrong** | Use confidence score from AI if available; otherwise, apply a confidence penalty (e.g., factor dampened toward 1.0 by 50%). |
| **No historical data for calibration** | Start with conservative factors (0.95 max adjustment). Adjust after observing real lineup vs real result. |
| **API rate limits for 48 squads** | Cache squad data (refresh daily, not per poll). Only fetch predicted lineups for upcoming matches. |

### 7.7 Scope Recommendation

**Phase 1 (v2.0):** Lineup strength factor based on market value. Conservative adjustments (max ±5%).

**Phase 2 (v2.1):** Add recent form from player stats. Use per-match player ratings (where available). Calibrate adjustment factors against historical data.

**Phase 3 (v2.2):** Full player-level simulation for extreme scenarios (star player injured mid-tournament). Only if v2.1 shows remaining accuracy gap.

---

## 8. Model Governance

### 8.1 Versioning

Every model run must be reproducible. Versioning at three levels:

**Level 1: Data version (auto)**
```json
{
  "elo_version": 7,
  "elo_snapshot_date": "2026-06-15T12:00:00Z",
  "elo_snapshot_source": "eloratings.net",
  "odds_snapshot_time": "2026-06-15T12:05:00Z",
  "catboost_version": "2026-06-15-model-v3",
  "player_snapshot_date": "2026-06-15T06:00:00Z"
}
```
Stored in `state_meta.json`. Increment on every data refresh.

**Level 2: Model version (manual)**
```json
{
  "model_version": "2.0.1",
  "calibration_date": "2026-06-15",
  "blend_weights": {"elo": 0.4, "odds": 0.35, "ml": 0.25},
  "calibration_method": "platt_scaling",
  "poisson_base_rate": 1.25,
  "k_factor": 60,
  "goal_diff_multiplier": true
}
```
Stored in `model_config.json`. Bump on algorithmic changes.

**Level 3: Run version (auto)**
```json
{
  "run_id": "a1b2c3d4-...",
  "timestamp": "2026-06-15T12:10:00Z",
  "seed": 42,
  "iterations": 50000,
  "model_version": "2.0.1",
  "data_version": 7
}
```
Logged with every simulation output. Enables exact reproducibility.

### 8.2 Calibration Process

**Pre-tournament calibration:**
1. Collect historical World Cup matches (2010-2022, ~320 matches)
2. For each match, compute what each signal WOULD have predicted
3. Fit Platt scaling parameters for each signal
4. Compute initial Brier scores
5. Set initial blend weights

**In-tournament calibration:**
1. After each match, compare predicted probability to actual outcome
2. Update running Brier score per signal
3. Every 10 matches, recalibrate (re-fit Platt parameters with new data)
4. Every 10 matches, recompute blend weights
5. Store calibration curve snapshots

### 8.3 Backtesting Framework

```python
def backtest(
    matches: list[dict],       # Historical matches with known outcomes
    signals: dict,             # {signal_name: [prediction_per_match]}
    calibration_window: int = 50,  # Rolling window for calibration
) -> dict:
    """Run backtest of signal ensemble against historical matches.
    
    Returns per-signal and ensemble metrics.
    """
    results = {
        "overall": {"brier": 0, "log_loss": 0, "accuracy": 0},
        "per_signal": {},
        "calibration_curves": {},
    }
    
    # Rolling window: for each match, calibrate on previous window
    for i in range(calibration_window, len(matches)):
        train = matches[:i]
        test = matches[i]
        
        # Calibrate each signal on training window
        for name, preds in signals.items():
            calibrated = platt_scale(preds[:i], train)
            results["per_signal"][name]["brier"] += brier(calibrated, test)
        
        # Blend with dynamic weights
        blended = blend_calibrated_signals(...)
        results["overall"]["brier"] += brier(blended, test)
    
    # Normalize
    n = len(matches) - calibration_window
    for key in results["overall"]:
        results["overall"][key] /= n
    ...
    
    return results
```

### 8.4 Monitoring Dashboard

A lightweight terminal dashboard showing model health:

```
MODEL HEALTH (v2.0.1)                    Data: v7 (2026-06-15 12:00Z)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Signal          Brier   Weight   Calibrated    Status
Elo             0.182   0.40     ✅            OK
Market Odds     0.171   0.35     ✅            OK (14 books)
CatBoost ML     0.178   0.25     ✅            OK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ensemble Brier: 0.167   (vs Elo-only: 0.182, +8.2%)
Data Freshness: 5 min ago
Last Calibration: 2026-06-15 (8 matches ago)
Next Calibration: 2 matches
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLAGS: None
```

### 8.5 Regression Testing

For every model change:

1. **Run backtest on historical World Cup data** — verify Brier score doesn't regress
2. **Run full test suite** — 212 tests must pass
3. **Run reproducibility check** — same seed + same data = same output
4. **Run drift check** — compare current predictions against previous model version
5. **Run benchmark** — 50K iterations must complete within 60s

### 8.6 Alert Thresholds

| Condition | Alert | Action |
|-----------|-------|--------|
| Signal Brier > 0.25 | ⚠ Warning | Investigate signal quality; consider reducing weight |
| Signal Brier > 0.30 | 🚨 Critical | Remove signal from ensemble; flag for manual review |
| Weight disparity > 0.5 | ⚠ Warning | One signal dominating; check if others failing |
| No calibration for > 50 matches | ⚠ Warning | Recalibration overdue; check data pipeline |
| Data age > 1 hour | ⚠ Warning | Data refresh failing; check API connectivity |
| Reproducibility mismatch | 🚨 Critical | Determinism broken; fix before next run |

---

## 9. ROI Analysis

### 9.1 Enhancement Ranking

| Rank | Enhancement | Effort | Complexity | Maintenance | Accuracy Gain | Score |
|------|------------|--------|------------|-------------|---------------|-------|
| 1 | **Fix Elo ratings** (correct teams.json values) | 1h | 1/10 | None | **Very High** (fixes 63% of broken foundation) | 9.8 |
| 2 | **Fix draw handling** (save draws, apply Elo) | 1h | 2/10 | None | **High** (4 draws missed so far, growing) | 9.5 |
| 3 | **Ingest market odds** (parse BSD odds endpoint) | 3h | 3/10 | Low | **Very High** (second independent signal) | 9.3 |
| 4 | **Ingest CatBoost predictions** (parse BSD v2 endpoint) | 2h | 3/10 | Low | **Very High** (third independent signal) | 9.2 |
| 5 | **Apply missing Elo updates** (5 early group matches) | 1h | 1/10 | None | **Medium** (10 stale team ratings) | 8.5 |
| 6 | **Goal-difference K multiplier** (per eloratings.net) | 1h | 2/10 | None | **Medium** (blowout matches under-corrected) | 8.3 |
| 7 | **Auto-sync Elo from eloratings.net** (poll, parse, apply) | 4h | 5/10 | Medium | **High** (eliminates manual entry forever) | 8.0 |
| 8 | **Build calibration layer** (Platt scaling per signal) | 6h | 6/10 | Medium | **High** (removes systematic bias from all signals) | 7.8 |
| 9 | **Build signal blender** (dynamic weighting by Brier) | 4h | 5/10 | Medium | **High** (adapts to best performing signal) | 7.5 |
| 10 | **Add team form signal** (last 5 results) | 3h | 3/10 | Low | **Medium** (momentum matters in tournaments) | 7.3 |
| 11 | **Integrate all three signals into simulation** | 6h | 6/10 | Medium | **Very High** (combines items 3-9 into working pipeline) | 7.2 |
| 12 | **Add lineup strength factor** (market value proxy) | 5h | 5/10 | Medium | **Medium** (small per-match effect, but affects every match) | 6.8 |
| 13 | **Add predicted lineups** (BSD AI starting XI) | 4h | 5/10 | Medium | **Medium** (improves lineup factor accuracy) | 6.5 |
| 14 | **Calibrate Poisson base rate** from historical WC data | 4h | 4/10 | Low | **Low-Medium** (current 1.25 is reasonable) | 6.0 |
| 15 | **Add per-shot xG strength** (from BSD shot maps) | 6h | 6/10 | Medium | **Low-Medium** (xG has high variance per match) | 5.5 |
| 16 | **Add player-form tracking** (5-match avg rating) | 6h | 6/10 | Medium | **Low-Medium** (marginal over team-level form) | 5.0 |
| 17 | **Build model governance** (versioning, monitoring) | 6h | 5/10 | High | **Low** (enables future improvements, no direct accuracy gain) | 4.5 |
| 18 | **Build backtesting framework** | 8h | 6/10 | Medium | **Low** (enables measurement, no direct gain) | 4.0 |
| 19 | **Add live in-play signals** (possession, shots) | 5h | 5/10 | Low | **Low** (marginal predictive value for pre-match simulation) | 3.5 |
| 20 | **WebSocket live data integration** | 8h | 7/10 | High | **Low** ($3/mo addon, pre-match prediction only benefits marginally) | 2.0 |

### 9.2 Effort vs Impact Matrix

```
Impact
  ^
  |  1                          ← Fix Elo ratings (1h)
  |  3,4                        ← Odds + ML (5h)
  |  7,11                       ← Auto-sync + full integration (10h)
  |  2,5,6                      ← Draw fix + missing updates + K-mult (3h)
  |  8,9,10                     ← Calibration + blending + form (13h)
  |  12,13                      ← Lineup factors (9h)
  |  14,15,16                   ← Calibration + xG + player form (16h)
  |  17,18                      ← Governance + backtesting (14h)
  |  19,20                      ← Live signals + WebSocket (13h)
  └───────────────────────────────────────────────→ Effort
  0h                            10h             20h
```

---

## 10. Final Recommendation

### 10.1 20-Hour Roadmap

**Goal:** Fix the foundation. Get three signals working. Make draws work.

| Hours | What | Why |
|-------|------|-----|
| 1 | Fix Elo ratings (correct teams.json) | 63% of foundation is wrong. Fix this first. |
| 1 | Fix draw handling (fetcher + Elo) | 4 draws missed already. Growing problem. |
| 2 | Apply missing Elo updates (5 early matches) | 10 stale team ratings. Clean up the mess. |
| 1 | Goal-difference K multiplier | Blowout wins under-corrected. Quick fix. |
| 3 | Ingest market odds (parse BSD endpoint) | Second signal, high value, 14 bookmakers. |
| 2 | Ingest CatBoost predictions | Third signal, free, already calibrated. |
| 4 | Auto-sync Elo from eloratings.net | Kill manual entry forever. Self-healing. |
| 4 | Integrate three signals into simulator | Combine Elo + odds + ML in Monte Carlo. |
| 2 | Validate + test + quick backtest | Make sure it actually works. |

**Predicted improvement:** Model goes from "63% wrong Elo-only" to "correct Elo + market odds + ML, properly blended, with working draws and goal-difference adjustments." Estimated Brier improvement: ~15-20% (from ~0.182 to ~0.155).

### 10.2 50-Hour Roadmap

**Goal:** Production-grade multi-signal system with calibration, monitoring, and team form.

| Hours | Cumulative | What |
|-------|------------|------|
| 20 | 20 | 20-hour roadmap (above) |
| 6 | 26 | Build calibration layer (Platt scaling per signal) |
| 4 | 30 | Build dynamic signal blender (Brier-weighted) |
| 3 | 33 | Add team form signal (last 5 results per team) |
| 5 | 38 | Add lineup strength factor (market value proxy) |
| 4 | 42 | Add predicted lineups (BSD AI starting XI) |
| 4 | 46 | Calibrate Poisson base rate from historical data |
| 4 | 50 | Build model governance (versioning, Brier monitoring, drift detection) |

**Predicted improvement:** Signal blending calibrated and dynamic. Team strength varies by lineup. Form accounts for recent momentum. Model governance catches degradation. Estimated Brier improvement: ~22-28% vs baseline (from ~0.182 to ~0.135).

### 10.3 100-Hour Roadmap

**Goal:** Full production forecasting system. Player-level model. Backtesting. History tracking.

| Hours | Cumulative | What |
|-------|------------|------|
| 50 | 50 | 50-hour roadmap (above) |
| 6 | 56 | Add per-shot xG strength (from BSD shot maps) |
| 6 | 62 | Add player-form tracking (per-match ratings) |
| 8 | 70 | Build backtesting framework (historical World Cups) |
| 6 | 76 | Add structured calibration curves (reliability diagrams) |
| 8 | 84 | Historical probability log (track odds over time, v2.0 requirement) |
| 4 | 88 | Most-likely full bracket visualization (v2.0 requirement) |
| 4 | 92 | Dark horse detection (gap between Elo and probability, v2.0 requirement) |
| 4 | 96 | What-if mode (simulate hypothetical match results, v2.0 requirement) |
| 4 | 100 | Documentation, test coverage, hardening |

**Predicted improvement:** Every available signal from BSD is integrated. Player-level model captures lineup effects. Backtesting validates every change. Historical tracking enables trend analysis. Estimated Brier improvement: ~25-32% vs baseline (from ~0.182 to ~0.125).

### 10.4 What Not To Do

| Enhancement | Why Not |
|-------------|---------|
| **WebSocket live data** | $3/mo addon for marginal pre-match gain. Skip unless live in-play prediction is a goal. |
| **Meta-model (ML over signals)** | Too little training data (64 WC matches). Risk of overfitting > accuracy gain. |
| **NumPy acceleration** | Current 12.66s for 50K is well within 60s poll interval. Not a bottleneck. |
| **Full player simulation** | Massive complexity. Team-level adjustments capture 80% of the effect with 10% of the effort. |
| **Web dashboard** | Console-only is working. Flask + Chart.js adds deployment complexity. Keep for v2.x if needed. |
| **Multi-tournament support** | Only one World Cup exists right now. Premature generalization. |

---

## 11. GSD Workflow Impact

### 11.1 Milestone Implications

The current roadmap has **v2.0 Enhanced Analytics** as the next milestone, with these existing future requirements:

```
- [ ] V2-01: Most-likely full bracket visualization
- [ ] V2-02: Dark horse detection
- [ ] V2-03: Historical probability log
- [ ] V2-04: Simple web dashboard
- [ ] V2-05: What-if mode
- [ ] V2-06: Backtesting against historical tournaments
- [ ] V2-07: NumPy-accelerated simulation
```

**These are wrong.** They were written before the audit revealed the Elo data integrity problem. Allocating effort to "most-likely bracket visualization" while the foundation is 63% wrong would be irresponsible.

### 11.2 Proposed v2.0 Replacement

**Replace the v2.0 milestone with: "Prediction Engine Modernization"**

| Old v2.0 | New v2.0 (Proposed) | Rationale |
|----------|---------------------|-----------|
| Most-likely bracket visualization | Correct Elo dataset | Foundation is broken |
| Dark horse detection | Auto-sync Elo from eloratings.net | Kill manual entry forever |
| Historical probability log | Market odds integration | Critical second signal |
| Web dashboard | CatBoost ML integration | Critical third signal |
| What-if mode | Draw handling fix | Known bug |
| Backtesting framework | Goal-difference K multiplier | Missing eloratings.net feature |
| NumPy acceleration | Calibration layer + blender | Ensemble governance |

### 11.3 Phase Restructuring

**Current phases (v2.0 planned):** None defined (only future requirements).

**Proposed phases:**

| Phase | Name | Content | Effort | Depends On |
|-------|------|---------|--------|------------|
| **11** | **Data Integrity** | Fix Elo ratings, apply missing updates, auto-sync from eloratings.net | 6h | Phase 10 |
| **12** | **Draw Handling & Elo Math** | Fix draw pipeline, implement K-multiplier | 2h | Phase 11 |
| **13** | **Signal Ingestion** | Market odds API, CatBoost predictions API | 5h | Phase 12 |
| **14** | **Signal Blending** | Calibration layer, dynamic blender, simulation integration | 10h | Phase 13 |
| **15** | **Context Signals** | Team form, lineup strength, player availability | 8h | Phase 14 |
| **16** | **Model Governance** | Versioning, Brier monitoring, backtesting, alerts | 10h | Phase 15 |
| **17** | **Output Enhancement** | Signal contribution display, confidence intervals, delta tracking v2 | 5h | Phase 16 |
| **18** | **Historical Tracking** | Probability log, dark horse detection, trend analysis | 4h | Phase 17 |

> **Completion status:** Phases 11, 12, and 12b are now fully implemented. The remaining phases (13-18) represent the forward roadmap.

### 11.4 Phase Dependency Graph

```
Phase 10 (Complete — v1.1 shipped)
    │
    ▼
Phase 11 ─── Data Integrity (6h) — ✅ Complete
    │
    ▼
Phase 12 ─── Draw Handling & Elo Math (2h) — ✅ Complete
    │
    ├── Phase 12b ─── Evaluation Infrastructure — ✅ Complete
    │
    ▼
Phase 13 ─── Signal Ingestion (5h) — ⏳ Pending
    │
    ▼
Phase 14 ─── Signal Blending (10h)
    │
    ▼
Phase 15 ─── Context Signals (8h)
    │
    ▼
Phase 16 ─── Model Governance (10h)
    │
    ├──────────────────┐
    ▼                  ▼
Phase 17          Phase 18
Output             Historical
Enhancement        Tracking
(5h)               (4h)
    │                  │
    └──────────────────┘
           │
           ▼
     v2.0 Milestone Complete
     (~50 hours total)
```

### 11.5 Requirements Update

**New requirements for v2.0 (replace V2-01 through V2-07):**

| ID | Requirement | Phase |
|----|------------|-------|
| V2-01 | All 48 Elo ratings match eloratings.net within 5 points | 11 |
| V2-02 | Elo values auto-sync from eloratings.net every N minutes | 11 |
| V2-03 | Draw results are ingested and Elo-updated correctly | 12 |
| V2-04 | Goal-difference K multiplier implemented per eloratings.net formula | 12 |
| V2-05 | Market odds fetched and converted to vig-removed probabilities | 13 |
| V2-06 | CatBoost predictions fetched for every match | 13 |
| V2-07 | Signal calibration layer (Platt scaling) implemented per signal | 14 |
| V2-08 | Dynamic signal blender (Brier-weighted) integrated into simulation | 14 |
| V2-09 | Calibrated Poisson base rate from historical World Cup data | 14 |
| V2-10 | Team form signal (last 5 matches) computed and integrated | 15 |
| V2-11 | Lineup strength factor (market value proxy) computed | 15 |
| V2-12 | Model version, data version, and run version tracked | 16 |
| V2-13 | Per-signal Brier scoring with drift detection | 16 |
| V2-14 | Backtesting framework against historical World Cups | 16 |
| V2-15 | Probability delta since last run displayed with signal breakdown | 17 |
| V2-16 | Historical probability log across tournament duration | 18 |
| V2-17 | Dark horse detection (highest Δ between average probability and champion probability) | 18 |

### 11.6 Project.md Updates Required

**Move from "Out of Scope" to "Active (v2.0)":**

| Old Status | Item | New Status | Rationale |
|------------|------|------------|-----------|
| ❌ Out of scope | Betting odds comparison | ✅ Active (V2-05) | Audit found odds are critical, free, and unused |
| ❌ Out of scope | Player-level modeling | ✅ Active (V2-11) | Lineup strength is simpler than full player modeling and adds value |
| ❌ Out of scope | Backtesting | ✅ Active (V2-14) | Needed for model governance and calibration |

**Current Out of Scope items that remain justified:**
- User accounts or login — still not needed for CLI tool
- Web dashboard — still console-only
- ML models (XGBoost, neural nets) — CatBoost is already provided by BSD; building our own is overkill
- Multi-tournament support — still only one World Cup
- Mobile notifications — post-MVP enhancement
- NumPy acceleration — still not needed at current simulation scale

### 11.7 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| eloratings.net changes HTML structure | Low | Medium (auto-sync breaks) | Add parser test; monitor for HTML changes |
| BSD API rate limits with 3x endpoints | Low | Medium (some signals fail) | Cache aggressively; graceful fallback to Elo-only |
| Market odds unavailable for some matches | Medium | Low (fewer signals for some matches) | Blend weights adjust automatically |
| CatBoost model retrained mid-tournament | Medium | Low (predictions shift) | Log model version; drift detection catches it |
| Calibration data insufficient (< 100 matches) | High | Low (use raw probabilities) | Conservative fallback: equal weights, no calibration |
| Dynamic Elo updates conflict with auto-sync | Medium | Low (double-counting) | Auto-sync is full replacement, not additive |

---

## Summary: What This Proposal Changes

| Before Audit | After Audit |
|--------------|-------------|
| Elo ratings assumed accurate | Elo ratings 63% wrong — must be fixed |
| Single signal (Elo) | Three signals (Elo + odds + ML) |
| Hand-typed Elo values | Auto-synced from eloratings.net |
| Draws skipped | Draws ingested and Elo-updated |
| No goal-difference K multiplier | K multiplier implemented |
| No calibration | Platt scaling per signal |
| Static probabilities | Dynamic Brier-weighted blending |
| No team form | Last-5-matches form signal |
| No lineup awareness | Market-value lineup strength factor |
| No versioning | Data + model + run version tracking |
| No Brier monitoring | Per-signal Brier scoring + drift detection |
| v2.0: bracket viz, dashboard, NumPy | v2.0: foundation fix, multi-signal, governance |

The old v2.0 was about cosmetic enhancements. The new v2.0 is about prediction quality.
