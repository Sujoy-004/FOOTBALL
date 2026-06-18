# Phase 17: Output Enhancement - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a new Upcoming Match Predictions section to the console output showing per-signal prediction breakdown for upcoming matches, and add optional confidence intervals to the championship probability table. The championship table itself remains unchanged. Per-signal breakdown applies exclusively to match-level predictions, not championship odds.

Scope: V2-15 (Probability delta since last run displayed with signal breakdown).

This phase does NOT modify the championship table's format or content (beyond optional CI columns). Per-signal breakdown does NOT require running Monte Carlo simulation N+1 times — data is sourced from existing signal caches and calibration params.

</domain>

<decisions>
## Implementation Decisions

### Output Structure
- **D-01:** Two-section output model:
  - **Section 1: Championship Probability Table** (unchanged from Phase 5/6) — shows top-5 teams with QF/SF/FINAL/CHAMPION/Delta columns. No per-signal columns.
  - **Section 2: Upcoming Match Predictions** (NEW) — shows next round's matches with per-signal prediction breakdown.

### Section 2 — Default Display
- **D-02:** Section 2 is ALWAYS shown (not hidden behind a flag). It appears every poll cycle.
- **D-03:** Scope: **Next round only** — only matches in the next scheduled round (R32, then R16, then QF, etc.). Not all upcoming matches. Rationale: most relevant to user, avoids overwhelming output, fits CLI constraints.
- **D-04:** Condensed format per match:
  ```
  Argentina vs Nigeria — 0.723 (5 sigs) [0.698–0.745]
  ```
  Blended probability + available signal count + min–max range across all available signals.
- **D-05:** The signal range `[min–max]` serves as the uncertainty metric for match predictions. No Clopper-Pearson CI — the range captures model disagreement between signals, which is more informative than MC sampling error (which is tiny at 50K runs).

### Section 2 — Expanded Display (--signals flag)
- **D-06:** `--signals` / `-s` CLI flag controls the **detail level** of Section 2, not its visibility.
- **D-07:** With `--signals`, each match expands to multi-line per-signal breakdown:
  ```
  Argentina vs Nigeria

  Blended : 0.723
  Elo     : 0.710
  Odds    : 0.745
  CatBoost: 0.718
  Form    : 0.698
  Lineup  : 0.701
  ```
  Signals shown in a consistent order. Only signals with `available: true` for that match are shown.

### --confidence Flag
- **D-08:** NEW `--confidence` / `-c` CLI flag, independent from `--signals`.
- **D-09:** Without flag: championship table shows probabilities without CI (current behavior).
- **D-10:** With `--confidence`: adds Clopper-Pearson 95% CI columns to the championship probability table for champion probability only. CI computed from MC trial counts (n_wins / 50,000).
- **D-11:** Flags are composable and independent:
  - Default: clean champ table + condensed match predictions
  - `--signals`: clean champ table + expanded per-signal match predictions
  - `--confidence`: champ table with CI + condensed match predictions
  - `--confidence --signals`: everything

### Output Flow Order
- **D-12:** The enhanced output flow (per poll cycle):
  1. Simulation duration
  2. Group standings (on new group matches)
  3. **Championship probability table** (Section 1)
  4. **Upcoming Match Predictions** (Section 2) — NEW
  5. Delta summary (risers/fallers)
  6. Governance dashlet (when triggered)

### Data Source for Match Predictions
- **D-13:** Per-signal match probabilities are sourced from existing data — no extra MC runs required:
  - **Blended probability**: from simulation's blend_params (already computed)
  - **Elo probability**: from `elo.expected_score()` for the match pairing
  - **Market odds**: from `odds_cache` (if available)
  - **CatBoost**: from `cb_cache` (if available)
  - **Form**: from `form_cache` (if available)
  - **Lineup strength**: from `lineup_cache` (if available)
  - All per-signal probabilities are calibrated via existing calibration params from `calibrate_and_blend()`

### First-Run Behavior
- **D-14:** Historical deltas not shown on first run (no baseline to diff against) — existing Phase 5/6 behavior preserved.
- **D-15:** Section 2 shows "No upcoming matches" empty state when all matches have been played (end of tournament).

### the agent's Discretion
- Exact per-signal display order in expanded view
- Column width / alignment in the expanded per-signal block
- Whether "available signals" count includes or excludes the blended signal
- Threshold for considering a match "upcoming" (not yet played, not currently in-progress)
- Whether the `--confidence` CI format is e.g., `[17.8–18.6]` or `±0.4` or as a separate column
- Empty state text for end of tournament

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 17 definition: V2-15 requirement, success criteria, dependencies on Phase 16.
- `.planning/REQUIREMENTS.md` — V2-15 (probability delta since last run with signal breakdown).

### Prior Phase Context
- `.planning/phases/05-console-output-formatting/05-CONTEXT.md` — Console output patterns, ANSI color conventions, table formatting decisions.
- `.planning/phases/06-cli-interface/06-CONTEXT.md` — CLI flag conventions (--once, --no-color, --seed), arg parsing patterns.
- `.planning/phases/14-signal-blending/14-CONTEXT.md` — Blender: signal calibration, Brier-weighted blending, cold-start threshold 30.
- `.planning/phases/14a-prediction-retention/14a-01-PLAN.md` — Permanent prediction ledger for signal data.
- `.planning/phases/15-context-signals/15-CONTEXT.md` — Form and lineup_strength signal keys and data sources.
- `.planning/phases/16-model-governance/16-CONTEXT.md` — Governance dashlet format, D-20 (pure Python), D-22 (console-only), D-23 (cold-start 30), D-24 (Brier window 50).

### Codebase Architecture
- `worldcup_predictor/src/output.py` — Existing print functions. Phase 17 adds `print_match_predictions()` and extends `print_probability_table()` for optional CI.
- `worldcup_predictor/src/blender.py` — `calibrate_and_blend()` returns blend_weights and calibration_params. Per-signal match probabilities computed from signal caches.
- `worldcup_predictor/src/constants.py` — CLI flag constants, signal cache filenames.
- `worldcup_predictor/main.py` — `_run_iteration()` output flow. Phase 17 inserts match predictions section after championship table.
- `worldcup_predictor/main.py:_parse_args()` — CLI arg parsing. Phase 17 adds `--signals` and `--confidence` flags.
- `worldcup_predictor/src/predictors/odds.py` — Reference pattern for signal module (cache format, available/reason fields).
- `worldcup_predictor/src/predictors/catboost.py` — Reference pattern for external signal fetching.
- `worldcup_predictor/src/predictors/form.py` — Form signal cache format.
- `worldcup_predictor/src/predictors/lineup.py` — Lineup signal cache format.
- `worldcup_predictor/src/state.py` — `load_signal_cache()`, `load_calibration_params()` for signal data access.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `worldcup_predictor/src/output.py:print_probability_table()` — Existing championship table. Phase 17 may add optional CI columns via parameter.
- `worldcup_predictor/src/output.py:print_governance_dashlet()` — Pattern for conditional/optional output blocks with cold-start vs active states.
- `worldcup_predictor/src/output.py:print_delta_summary()` — Pattern for supplementary output sections after the main table.
- `worldcup_predictor/src/blender.py:calibrate_and_blend()` — Returns calibration_params and blend_weights for per-signal match predictions.
- `worldcup_predictor/src/evaluation.py` — `brier_score()` utility (not needed for display but useful for signal weight computation reference).

### Established Patterns
- **Print-function pattern** (output.py): Each output block is a separate `print_*()` function. Phase 17 adds `print_match_predictions()`.
- **CLI flag pattern** (main.py:_parse_args()): `--flag` with `action="store_true"` and `dest="flag_name"`. Stored in `args.namespace`.
- **Signal cache format**: Each cache has `matches: {match_id: {probability, available, reason}}`. Phase 17 reads from these for per-signal breakdown.
- **Cold-start awareness** (governance.py, blender.py): Systems distinguish <30 matches from >=30. Phase 17's Section 2 shows whatever signals are available regardless of cold-start status.
- **ANSI color conventions** (output.py): `_bold_cyan` for headers, `_green`/`_red` for delta values, `_dim` for timestamps. Phase 17 follows these conventions.

### Integration Points
- `worldcup_predictor/main.py:_run_iteration()` (~line 740-755) — Output flow. Insert `print_match_predictions()` call after `print_probability_table()` and before `print_delta_summary()`.
- `worldcup_predictor/main.py:_parse_args()` (~line 164-200) — Add `--signals` and `--confidence` flags.
- `worldcup_predictor/main.py:865-868` — Flag application for `NO_COLOR`. Phase 17 reads `args.signals` and `args.confidence` in `_run_iteration()`.
- `worldcup_predictor/src/state.py` — `load_signal_cache()` for each signal cache. Phase 17 reads odds, cb, form, lineup caches in `_run_iteration()`.
- `worldcup_predictor/src/blender.py` — Calibration params loaded from `calibration_params.json` for per-signal calibration of match probabilities.

### Data Flow
1. `_run_iteration()` fetches/refreshes all signal caches (existing)
2. `_run_calibrate_and_blend()` produces calibration_params + blend_weights (existing)
3. `run_full_simulation()` uses blend_params, produces championship probs (existing)
4. NEW: `_compute_match_predictions()` reads signal caches, applies calibration, produces per-signal match probs
5. `print_match_predictions()` displays Section 2 (condensed or expanded)
6. `print_probability_table()` optionally extended with CI columns

</code_context>

<specifics>
## Specific Ideas

- "Phase 17 is primarily an explanation layer." The signal range for match predictions captures model disagreement (Elo vs Odds vs CatBoost vs Form vs Lineup), which is what users care about — not the tiny MC sampling error from 50K simulations.
- The user explicitly distinguished: "Not CI everywhere. Not range everywhere. Use the uncertainty measure that matches the quantity being displayed." Match predictions get signal range; championship probabilities get optional Clopper-Pearson CI.
- The `--confidence` flag was a late addition to the CLI — it was not in the original ROADMAP.md but emerged during discussion as the natural way to control CI visibility without conflating it with signal breakdown.
- The user validated `k_form=1.0` and `k_lineup=0.35` empirically from Phase 15. These constants feed into per-signal match probability computation for form and lineup signals.

</specifics>

<deferred>
## Deferred Ideas

### Terminal Layout (from original gray area) — deferred until data model locked
- How to handle terminal width when terminal is narrow (wrapping, truncation, or --no-color mode).
- Whether the match predictions section should use box-drawing characters like group standings or plain text like the championship table.
- Revisit after initial implementation proves the data model.

### Delta Presentation (from original gray area) — deferred until data model locked
- Per-signal delta tracking ("champ prob changed +0.010; elo +0.004, odds +0.003...").
- Per-round (QF/SF/FINAL) deltas in addition to champion delta.
- Revisit after the per-signal data model is proven in Section 2.

</deferred>

---

*Phase: 17-Output-Enhancement*
*Context gathered: 2026-06-17*
