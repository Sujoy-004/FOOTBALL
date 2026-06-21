# Phase 18 Discussion Log — xG & AI Prediction Signals

**Date:** 2026-06-19
**Status:** Context captured

## Discussion Flow

### Pre-Discussion: BSD Probe
- User requested BSD API evidence before any architecture discussion
- Probe confirmed: xG fields exist on both predictions endpoint (`expected_home_goals`, `expected_away_goals`) and events endpoint (`actual_home_xg`, `actual_away_xg`, `home_xg_live`, `away_xg_live`)
- AI preview found on events endpoint only (`ai_preview` dict with `text` key) — no separate `/api/ai-previews/` endpoint
- No finished matches exist yet (can't confirm actual xG values for post-match)

### Area 1: xG → Probability Conversion
- **Key discovery:** `expected_home_goals`, `expected_away_goals` and `prob_home_win`, `prob_draw`, `prob_away_win` are sibling fields in the same BSD prediction object (model_version `v5.0`)
- **Implication:** Registering xG as an independent blender signal would double-count the same BSD model alongside the existing catboost signal
- **Decision:** Reject xG as blender signal

### V2-23 Requirement Revision
- **Decision:** Revise V2-23 from "independent prediction signal" to "simulation input"
- `expected_home_goals` / `expected_away_goals` become optional Poisson lambda overrides in `precompute_matchup_lambdas()`
- Fall back to Elo-derived `expected_goals()` when xG unavailable
- No signal_keys changes, no xg cache, no xg ledger, no calibration/governance changes

### Area 4: AI Preview Storage & Display
- **Option chosen:** Inline enrichment (Phase 17 pattern) + `--ai-preview` CLI flag
- Storage on played.json/played_groups.json entries
- Default console unchanged
- Graceful degradation: missing = no display, no warnings, no errors

### Area 5: Historical xG Backfill
- **Decision:** No backfill for already-played matches
- xG overrides only useful pre-match; predictions endpoint doesn't serve past predictions
- Future matches only

## Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D-01 | xG is NOT a blender signal | Same model as catboost — would double-count |
| D-02 | xG overrides in precompute_matchup_lambdas() | Minimal code change, clean integration |
| D-03 | Optional xg_overrides param | Seamless fallback to Elo when xG unavailable |
| D-04 | xG extracted from existing predictions fetch | No new API call |
| D-05 | AI preview inline on played entries | Follows Phase 17 enrichment pattern |
| D-06 | --ai-preview CLI flag | Default console unchanged |
| D-07 | No historical backfill | xG only useful pre-match |
| D-08 | V2-23 requirement revised | Architectural inconsistency resolved |

## Deferred Ideas

- Actual xG as evaluation metric (post-match xG analysis)
- xG display in console (Phase 20)
- AI preview in backtest reports
