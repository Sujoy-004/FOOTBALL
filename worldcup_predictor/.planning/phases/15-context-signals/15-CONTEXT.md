# Phase 15: Context Signals — Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Add two new team-level context signals — recent form and lineup strength — as independent prediction signals that feed into the existing blender pipeline from Phase 14. Both follow the same compound entry model as market_odds and catboost.

Scope: V2-10 (team form signal), V2-11 (lineup strength factor / market value proxy).

This phase does NOT create the squad/player data source for lineup strength — that depends on BSD API research (deferred to gsd-phase-researcher). The mathematical formulation is locked; the data source is not.

</domain>

<decisions>
## Implementation Decisions

### Form Signal — Computation
- **D-01:** Form is computed as Elo-based residual: `form_residual = sum(actual - expected_score)` over a rolling window. Not points-based, not goal-difference-based. Elo residual captures over/under-performance relative to opponent strength.
- **D-02:** Configurable window size (constant `FORM_WINDOW_SIZE = 5`), minimum 1 match required. If a team has N < window matches, use N. If 0, signal is `available: false`.
- **D-03:** Form includes ALL available match results (WC group stage + knockout + any historical data in played_groups / played). Not limited to WC-only.

### Form Signal — Match-Level Probability
- **D-04:** Match-level formulation (not single-team probability):
  ```
  form_delta = home_form_residual - away_form_residual
  p_form = sigmoid(k * form_delta)
  ```
- **D-05:** `k` is NOT locked. The planner must determine expected range of `form_delta`, typical observed values, and choose a justified default `k`. Cold-start uses this default; Platt calibration refines as data accumulates.
- **D-05a:** Empirically validated from 19 played matches: every team has exactly 1 match (cold tournament), form_delta range [-1.01, +1.01], 95th percentile ±0.78. k_form=1.0 chosen after audit — k=0.6 suppressed an already-small signal. k_form=0.6 was based on incorrect range assumption ([-5,+5] vs actual [-2,+2] theoretical, [-1,+1] empirical).

### Form Signal — Integration
- **D-06:** Form is an independent 4th signal in the compound `signals` dict (key: `"form"`). NOT a modifier to Elo. Goes through Platt calibration + Brier-weighted blending like odds/catboost. This allows per-signal Brier computation.
- **D-07:** Module placement: `src/predictors/form.py`. Follows same pattern as `odds.py` and `catboost.py` — predict module per signal.

### Lineup Strength Signal — Formulation
- **D-08:** Match-level formulation using log-ratio of squad market values:
  ```
  strength_delta = ln(home_value / away_value)
  p_strength = sigmoid(k * strength_delta)
  ```
- **D-09:** Log-ratio was explicitly chosen over z-score. Rationale: z-score depends on current population (add/remove teams shifts probabilities). Log-ratio is interpretable, scale-independent, and stable.
- **D-10:** `k` is NOT locked (same as form). Planner determines justified default. Cold-start then Platt calibration.
- **D-10a:** k_lineup=0.35 chosen from empirical value range (€7.5M–€1.52B, ln ratios [-5.31, +5.31]). Produces p=0.86 for extreme mismatch (Panama@France), p=0.62 for typical 4x mismatch. Avoids saturation.
- **D-11:** Z-score approach rejected.

### Lineup Strength — Data Source
- **D-12:** Data source is NOT locked. Researcher MUST check BSD API for squad/player/team endpoints first. If BSD has available data, use it (trivial API call). If not, fallback options are: manual file (`data/team_values.json`) or FIFA ranking proxy. Planner selects based on research outcome.

### Lineup Strength — Integration
- **D-13:** Lineup strength is an independent 5th signal in the compound `signals` dict (key: `"lineup_strength"`). Same pipeline as form, odds, catboost.
- **D-14:** Module placement: `src/predictors/lineup.py` (if a data source justifies a standalone module), or inline if data source is trivial.

### Shared Architecture
- **D-15:** Both signals write to the permanent prediction ledger (Phase 14a) at fetch time. Same pattern as odds and catboost.
- **D-16:** Both signals use `available: false` with `reason` for graceful degradation (D-07 from Phase 13). Zero matches played → no form signal. No BSD squad data → no lineup strength signal.
- **D-17:** Cold-start: identity calibration (p_calibrated = p_raw) until ≥30 multi-signal entries exist. Same threshold as Phase 14 (D-03/D-04).

### the agent's Discretion
- Default value of `k` for both form and lineup strength (planner determines from observed data ranges)
- Implementation of `form_residual` window (list / deque / rolling sum)
- Whether lineup strength fetches from API or loads from static file
- Test fixture design for both signals

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 15 definition: V2-10, V2-11 requirements, success criteria, dependencies on Phase 14.
- `.planning/REQUIREMENTS.md` — V2-10 (team form), V2-11 (lineup strength factor).

### Prior Phase Context
- `.planning/phases/14-signal-blending/14-CONTEXT.md` — Phase 14 decisions: Platt scaling (D-01/D-02), cold-start threshold 30 (D-03/D-04), inverse-Brier weighting with 0.05 floor (D-07), rolling Brier window 50 (D-08), pure Python constraint (D-01), LOO-CV evaluation (D-11).
- `.planning/phases/14a-prediction-retention/14a-01-PLAN.md` — Permanent prediction ledger. Phase 15 signals write to ledger at fetch time.
- `.planning/phases/13-signal-ingestion/13-CONTEXT.md` — Compound entry model (D-01/D-02/D-03), graceful degradation (D-07/D-08), evaluate_all_matches signal_name param (D-11), signal probability format (D-13).

### Codebase Architecture
- `worldcup_predictor/src/predictors/odds.py` — Reference pattern for signal module structure. Phase 15's form.py and lineup.py follow this pattern.
- `worldcup_predictor/src/predictors/catboost.py` — Reference pattern for external API signal fetching with retry/backoff.
- `worldcup_predictor/src/evaluation.py` — `evaluate_all_matches(signal_name="form")` reads from prediction_history via D-11 framework.
- `worldcup_predictor/src/blender.py` — Blender handles N signals generically. Phase 15 adds form and lineup_strength to the signal list.
- `worldcup_predictor/src/state.py` — `ledger_upsert()`, `load_prediction_history()` for signal data access.
- `worldcup_predictor/main.py:37-70` — `_merge_signals_into_history()` injection point for new signals.
- `worldcup_predictor/src/constants.py` — Add `FORM_WINDOW_SIZE` constant.

### Established Patterns (from scout)
- `worldcup_predictor/src/predictors/odds.py` — Signal module pattern: fetch → parse → cache → ledger upsert → return cache dict.
- `worldcup_predictor/src/predictors/catboost.py` — API fetch with 3-attempt exponential backoff (1s, 2s, 4s).
- `worldcup_predictor/main.py:590-620` — Signal refresh + merge flow in `_run_iteration()` — new signals get wired here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/predictors/odds.py` — Complete signal module template. form.py and lineup.py follow this structure: parse → normalize → resolve match_id → build entry dict → cache + ledger upsert.
- `src/state.py:ledger_upsert()` — One-line call to persist any signal to the permanent ledger.
- `src/blender.py:calibrate_and_blend()` — Reads prediction_history and processes all available signals generically. No changes needed for new signals — they auto-join the blender once entries exist in history.
- `src/evaluation.py:evaluate_all_matches(signal_name=)` — Signal-name filter already supports new signal keys like `"form"` and `"lineup_strength"`.
- `src/fetcher.py:_find_group_match()`, `_find_bracket_match()` — Match resolution utilities. Form and lineup strength don't need these (they're team-level attributes, not match-level predictions), but the form compute function needs played_groups data.

### Established Patterns
- `src/predictors/odds.py` and `src/predictors/catboost.py` — Signal modules live in `src/predictors/`, each producing a cache dict with `matches: {match_id: entry}`.
- `src/state.py` — Each signal has its own cache file + ledger upsert.
- `src/main.py` — Signal refresh in `_run_iteration()` with TTL check + merge into prediction_history.
- Pure stdlib math — No numpy, no sklearn. `math.log`, `math.exp` for sigmoid.

### Integration Points
- `src/main.py:_run_iteration()` (~line 590-620) — New signals get fetched and merged here alongside odds and catboost.
- `src/main.py:startup` (~line 750) — One-shot signal seed for new signals.
- `src/evaluation.py:evaluate_all_matches()` — Automatically handles new signal_name values via D-11 framework.
- `src/blender.py` — Processes all signals in prediction_history. New signals are automatically included.

### Research Needed
- BSD API squad/player endpoint existence — determines lineup strength data source (D-12).
- Typical form_delta range across teams (for k determination).
- Squad market value distribution across 48 World Cup teams (if manual file approach).

</code_context>

<specifics>
## Specific Ideas

- Both form and lineup strength follow the same mathematical pattern: team-state attribute → match-level delta → sigmoid(× k) → match probability. This consistency was intentional.
- "Form is a team state metric, not a match prediction model" — the user emphasized this distinction when rejecting single-team probability approaches. Every signal must produce P(home beats away), not P(team is in good form).
- Log-ratio for lineup strength was explicitly chosen over z-score because z-score shifts when teams are added/removed. Log-ratio is mathematically stable regardless of population.
- The user explicitly rejected softmax for Phase 14's weighting (D-07 from 14-CONTEXT.md). Phase 15 uses same inverse-Brier weighting.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 15-Context-Signals*
*Context gathered: 2026-06-17*
