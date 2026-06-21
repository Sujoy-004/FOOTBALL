# Phase 18: xG & AI Prediction Signals — Context

**Gathered:** 2026-06-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Integrate BSD's xG predictions as Poisson simulation lambda overrides, and BSD AI pre-match analysis as display-only enrichment. xG is NOT a blender signal — it replaces Elo-derived expected_goals in the Poisson match simulator for more accurate scoreline distribution and tiebreaker resolution. AI preview is stored inline on played match entries and displayed via `--ai-preview` CLI flag.

Scope: V2-23 (xG-assisted simulation), V2-24 (AI preview ingestion and display).

This phase does NOT create new blender signals, modify calibration, add xG caches, change governance, or backfill historical data.
</domain>

<spec_lock>
## Requirement Revision

### V2-23 — Revised

**Original:** "BSD xG predictions ingested as independent prediction signal"

**Revised:** "BSD xG predictions (`expected_home_goals`, `expected_away_goals`) ingested as optional Poisson simulation lambda overrides — replacing Elo-derived expected_goals in `precompute_matchup_lambdas()` for more accurate scoreline distribution."

**Rationale:** BSD probe confirmed that `expected_home_goals`, `expected_away_goals`, `prob_home_win`, `prob_draw`, and `prob_away_win` are sibling fields in the same BSD prediction object (model_version `v5.0`). Registering xG as an independent signal would double-count the same underlying model. xG as simulation input instead improves tiebreaker accuracy without architecturally duplicating the CatBoost signal.

**V2-24 unchanged:** "BSD AI preview / pre-match analysis ingested and displayed"
</spec_lock>

<decisions>
## Implementation Decisions

### A. xG as Simulation Input (V2-23)
- **D-01:** xG is NOT a blender signal. No `signal_keys` addition, no xg cache, no xg ledger entries, no calibration changes, no governance changes.
- **D-02:** `expected_home_goals` and `expected_away_goals` (from BSD predictions endpoint) become optional lambda overrides in `precompute_matchup_lambdas()`.
- **D-03:** New signature:
  ```python
  def precompute_matchup_lambdas(
      groups: dict,
      elo_ratings: dict[str, float],
      xg_overrides: dict[str, tuple[float, float]] | None = None,
  ) -> dict[str, tuple[float, float]]:
  ```
- **D-04:** When `xg_overrides` and `mid in xg_overrides`, use the xG values as (lambda_a, lambda_b). Otherwise fall back to Elo-derived `expected_goals()`.
- **D-05:** `xg_overrides` dict is populated from the predictions endpoint response — `expected_home_goals` → lambda_a, `expected_away_goals` → lambda_b, keyed by match_id. Match_id resolution uses the same team-pair matching logic as catboost.py (event → match via team name + group lookup).
- **D-06:** xG values are extracted during the existing catboost predictions fetch. No separate API call.
- **D-07:** `_simulate_single_match()` already accepts optional precomputed lambdas (line 123) — no change needed. `simulate_group_matches()` passes `matchup_lambdas` through — no change needed.

### B. AI Preview Storage & Display (V2-24)
- **D-08:** Storage — `ai_preview` stored inline on played.json / played_groups.json entries, following Phase 17 enrichment pattern. No separate `ai_previews.json` file.
- **D-09:** Display — default console output unchanged. AI preview shown only when `--ai-preview` CLI flag is passed.
- **D-10:** Source — `ai_preview` field from BSD events endpoint. Extracted in the same enrichment step as Phase 17 (in `process_matches()` / `process_group_matches()`).
- **D-11:** Graceful degradation — missing `ai_preview` = no display. No warnings. No errors.

### C. Historical Backfill
- **D-12:** No backfill of xG or AI preview for already-played matches.
- **D-13:** xG overrides are only useful pre-match. Predictions endpoint does not serve predictions for past matches.
- **D-14:** AI preview for played matches could be backfilled but Phase 18 skips it — display-only feature with no prediction or simulation impact.
- **D-15:** xG collected for all future/upcoming matches from the predictions endpoint going forward.

## Verification Criteria
- **V1:** `precompute_matchup_lambdas()` accepts `xg_overrides` param. When provided, xG values override Elo lambdas for matching match_ids.
- **V2:** When `xg_overrides` is None or the match_id is absent, falls back to Elo-derived `expected_goals()`.
- **V3:** No new signal_keys, no xg cache, no xg ledger entries, no blender changes.
- **V4:** `ai_preview` stored inline on played.json/played_groups.json entries.
- **V5:` `--ai-preview` CLI flag displays stored AI preview text.
- **V6:** Missing ai_preview produces no warnings or errors.
- **V7:** Zero regression on existing test suite.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 18 definition: V2-23 (revised), V2-24 requirements.
- `.planning/REQUIREMENTS.md` — V2-23 (revised: xG as simulation input), V2-24 (AI preview).

### BSD Probe Evidence
- `bsd_probe.py` (temp: `C:\Users\KIIT0001\AppData\Local\Temp\opencode\bsd_probe.py`) — Raw payload dump confirming xG and AI preview field names, endpoints, and availability from live BSD API.

### Prior Phase Context
- `.planning/phases/17-enriched-match-context/17-CONTEXT.md` — Enrichment pattern (D-01 through D-18): inline storage, field-name fallback chains, P0 scope, backfill deferral.
- `.planning/phases/17b-signal-pipeline-repair/17b-CONTEXT.md` — Signal pipeline architecture: ledger_upsert pattern, compound entry model, graceful degradation.
- `.planning/phases/13-signal-ingestion/13-CONTEXT.md` — BSD predictions endpoint integration, team-pair match_id resolution (used by xG extraction).
- `.planning/phases/15-context-signals/15-CONTEXT.md` — Context signal patterns.

### Codebase Architecture
- `src/groups.py:181-205` — `precompute_matchup_lambdas()` — replacement point for xG overrides.
- `src/groups.py:26-60` — `expected_goals()` — Elo-to-goals formula (fallback).
- `src/groups.py:121-148` — `_simulate_single_match()` — already accepts optional lambdas.
- `src/predictors/catboost.py` — Predictions endpoint fetch + team-pair match_id resolution pattern (reused for xG extraction).
- `src/fetcher.py:86-159` — `process_matches()` — enrichment integration point (AI preview extraction).
- `src/fetcher.py:236-353` — `process_group_matches()` — group enrichment integration point.
- `main.py:133, 996` — `signal_keys` list (unchanged — xG not added).
- `src/enrichment.py` — Phase 17 enrichment module (pattern reference for AI preview storage).

### Established Patterns
- **Phase 17 enrichment pattern**: stats/context stored inline on entry, optional keys, sparse dict convention.
- **Graceful degradation (signal modules)**: available=false with reason for missing data. AI preview uses simpler "absent = no display" convention.
- **Team-pair match_id resolution** (catboost.py): BSD event → match via home/away team names + group letter → internal match_id.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/predictors/catboost.py:201-260` — `fetch_and_cache_catboost()` — Already fetches from `/api/predictions/`. xG values (`expected_home_goals`, `expected_away_goals`) can be extracted in the same parse step — no new HTTP call.
- `src/groups.py:181-205` — `precompute_matchup_lambdas()` — Single function to modify for xG override support. ~5 lines changed.
- `src/fetcher.py:process_matches()` / `process_group_matches()` — Enrichment insertion point for AI preview. ~2 lines changed (add `ai_preview` extraction).
- `src/enrichment.py` — Field-name fallback chain pattern (D-11) reusable for extracting `ai_preview` from events response.

### Integration Points
- `src/groups.py:204` — Lambda computation: `lambdas[mid] = ...` — replace with xG-checking conditional.
- `src/predictors/catboost.py:parse_catboost_response()` — xG extraction alongside probability parsing.
- `src/fetcher.py:148-157` — Knockout match entry construction — add `ai_preview` extraction here.
- `src/fetcher.py:342-351` — Group match entry construction — add `ai_preview` extraction here.
- `main.py:CLI` — Add `--ai-preview` flag.
- `main.py` — Wire xG overrides from catboost response into simulation call chain.

### No Changes Needed
- `src/blender.py` — No changes. xG is not a signal.
- `src/evaluation.py` — No changes. xG not evaluated.
- `src/governance.py` — No changes. xG has no governance impact.
- `src/state.py` — No changes. No new cache, ledger, or persistence surface.
- `src/knockout.py` — No changes. xG only affects group simulation (Poisson scorelines).
</code_context>

<specifics>
## Specific Ideas

- The catboost predictions fetch returns a list of prediction objects, each with an `event` dict containing `id` and `league` info. The same event ID → match_id resolution used for probabilities also works for xG values — `expected_home_goals` and `expected_away_goals` are alongside the probability fields in the same JSON object.
- xG override vs Elo lambda: xG values from BSD are likely more accurate than Elo-derived expected_goals because BSD's model uses 163 features. But xG may only be available for a subset of matches — the fallback design handles this seamlessly.
- AI preview text is markdown-formatted. Display should render as plain text (strip markdown or display raw — CLI constraint).
- The `--ai-preview` flag should print AI previews for all matches that have them in a single block, not interrupt the normal output flow.

</specifics>

<deferred>
## Deferred Ideas

- **Actual xG as evaluation metric** — `actual_home_xg` / `actual_away_xg` from events endpoint for finished matches could be used to evaluate prediction accuracy vs actual xG. Not needed for Phase 18 scope.
- **xG display in console** — Showing xG values alongside match probabilities. Deferred to Phase 20 (Output Enhancement).
- **AI preview in backtest reports** — AI previews for historical matches could be backfilled but no consumer exists yet. Deferred indefinitely.
</deferred>

---

*Phase: 18-xG-AI-Prediction-Signals*
*Context gathered: 2026-06-19*
