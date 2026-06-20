# Phase 20: Output Enhancement & Coverage Seal — Context

**Gathered:** 2026-06-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Four requirements delivered:

| ID | Requirement | Status |
|----|------------|--------|
| V2-27 | Per-match signal breakdown display (blended + per-signal) in console | Define |
| V2-28 | Confidence intervals (Clopper-Pearson) alongside probabilities | Define |
| V2-29 | Historical probability log across tournament duration with trend tracking | Define |
| V2-30 | ≥60% BSD API meaningful field coverage with automated auditor script | Define |

Plus: Phase 17/18 deferred display work (coach, fouls, corner_kicks, shots_off_target, xG) surfaces in the focus card.

This phase does NOT implement championship probability signal decomposition (deferred to v2.x), does NOT add CI to the championship table or per-match table (only focus card), does NOT add per-signal delta to the main per-match table (only focus card), and does NOT create a separate match-context section.

</domain>

<rejected>
## Rejected Designs

Recorded to prevent future re-litigation:

| Rejected Decision | Rationale |
|------------------|-----------|
| Championship probability signal decomposition | V2-27 explicitly says "per-match". Championship explanation is a new requirement (V2-31+), not Phase 20 scope. |
| CI in championship table | Breaks 80-col terminal width. Marginal utility — Monte Carlo uncertainty already in the full distribution. |
| CI in per-match table | Destroys 85-col table width. Each cell doubles from 6 to 16 chars (~150 cols total). |
| Per-signal Δ in main table | Triples table width from 85 to ~140 chars. The Δ column answers "did anything change?" — a triage gate. Per-signal Δ belongs in focus card (deeper explanation). |
| Dedicated match-context section separate from focus card | Creates discovery friction (user must know the flag exists). Context belongs inside the focus card which is the natural inspection point. |
| Mockup 2 (filtered tightest matches) as primary V2-27 | Not a "per-match" breakdown — it's a filtered summary. User cannot inspect a specific match's signals in detail. |
</rejected>

<decisions>
## Implementation Decisions

### V2-27: Per-Match Signal Breakdown

- **D-01:** Primary display is a **per-match table** showing all remaining/upcoming matches with 7 signal columns (Blended, Elo, Odds, CatBoost, Form, Lineup, xG) plus a blended Δ column. Mockup 1, ~85 chars wide.
- **D-02:** Table gated behind `--match-detail` CLI flag (same pattern as `--ai-preview`).
- **D-03:** Δ column in the table is **blended probability delta only** (not per-signal). Answers "did anything change for this match?" — a triage gate.
- **D-04:** **Focus card** (Mockup 3, ~84 chars) opened by selecting a row from the table. Contains:
  - All 7 signals with provenance labels (source of each signal)
  - Per-signal Δ (each signal's change since last run)
  - CI column (Clopper-Pearson 95%)
  - Match context section (venue, referee, coach names)
  - Match stats section (fouls, corner_kicks, shots_off_target, shots_on_target, possession, yellow/red cards, xG)
- **D-05:** Focus card is a **child of V2-27** — only accessible from the per-match table. Not directly reachable from championship table.
- **D-06:** Flow: default output (championship table + standings) → `--match-detail` → per-match signal table → focus row → focus card.

### V2-28: Confidence Intervals

- **D-07:** Clopper-Pearson 95% CI displayed **only in the focus card** (one column per signal row). NOT in championship table, NOT in per-match table.
- **D-08:** Format: `[.452 — .516]` — lower and upper bound alongside the point estimate.

### V2-29: Probability Log & Trend

- **D-09:** **Single rolling JSON file** (`probability_log.json`) — array of snapshot dicts appended after every `_run_iteration()`. Same pattern as `prediction_history.json`.
- **D-10:** Snapshot content: full probability dictionary (all teams, all stages: qf, sf, final, champion). Timestamped.
- **D-11:** Cadence: every `_run_iteration()` — same as simulation cycle. No separate timer.
- **D-12:** **Trend arrow** (↑ / ↓ / →) added to championship table as a new column. Compares current champion probability vs. rolling window mean of last 5 snapshots.
  - ↑ : current > window mean + threshold
  - ↓ : current < window mean - threshold
  - → : within threshold
- **D-13:** Trend column hidden on first run (no window to compare against).
- **D-14:** Trend is championship-table only — NOT in per-match table, NOT in focus card.

### V2-30: Coverage Auditor

- **D-15:** Target: ≥60% BSD API meaningful field coverage (counts Prediction + Display + Operational fields only; excludes No-Value noise). Denominator = 47 meaningful fields.
- **D-16:** Automated auditor script reports:
  - Total meaningful fields (47)
  - Fields currently extracted
  - Specific missing fields by value category
  - Coverage percentage
- **D-17:** No counter — the value-based coverage is the only metric. Raw field count (61.8%) is not reported.
- **D-18:** Prioritized extraction for the 3 high-value fields: fouls, corner_kicks, shots_off_target (immediate, 6 lines in `_STATS_FIELD_MAP`).

### Deferred Display Work (Phase 17/18 fields)

- **D-19:** Coach names, fouls, corner_kicks, shots_off_target, xG all appear **inside the focus card only** — NOT as a separate section, NOT in any table.
- **D-20:** Focus card layout: signal breakdown (top) → per-signal Δ + CI (middle) → match context (venue, referee, coaches) → match stats (fouls, corners, shots, possession, cards, xG).

### the agent's Discretion

- Exact field-name fallback chains for newly extracted fields (fouls, corners, shots_off_target) — determined from existing BSD probe data.
- Whether the focus card is triggered by match ID input or interactive row selection — researcher/planner to propose.
- Trend threshold value — should be small enough to detect meaningful changes (recommend: 0.005) but planner to validate.
- Whether `--match-detail` also shows the focus card inline or requires a separate interaction step.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap

- `.planning/REQUIREMENTS.md` lines 87-90 — V2-27, V2-28, V2-29, V2-30 definitions.
- `.planning/ROADMAP.md` lines 626-659 — Phase 20 goal, success criteria, requirement traceability.
- `.planning/PROJECT.md` — Project constraints: JSON-only storage, console-only output, BSD API.
- `MODERNIZATION-PROPOSAL.md` — Full v2.0 architecture (signal blender design, simulation pipeline).

### Prior Phase Context

- `.planning/phases/17-enriched-match-context/17-CONTEXT.md` — D-14 (display deferred to Phase 20), P1-P3 field table (coach, shots_off_target, corners, fouls, weather deferred to Phase 20).
- `.planning/phases/18-xg-ai-prediction-signals/18-CONTEXT.md` — xG display deferred to Phase 20 (deferred ideas section).
- `.planning/phases/13-signal-ingestion/13-CONTEXT.md` — Signal ingestion patterns: field-name fallback chains, graceful degradation.
- `.planning/phases/15-context-signals/15-CONTEXT.md` — Context signal patterns.

### Codebase Architecture

- `src/output.py` — All console display functions (`print_probability_table`, `print_delta_summary`, etc.) — the primary modification target.
- `src/enrichment.py:17-26` — `_STATS_FIELD_MAP` — target for new field extraction (fouls, corners, shots_off_target).
- `src/fetcher.py:86-159` — `process_matches()` — enrichment integration point.
- `src/main.py` — CLI flag parsing, `_run_iteration()` flow, snapshot cadence.
- `src/state.py` — Load/save patterns for new probability_log.json persistence.

### Prior Analysis

- `RESPONSE.md` — Value-based BSD field classification (47 meaningful fields, No-Value elimination, prioritized extraction).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `output.py:54-94` — `print_probability_table()` — championship table with Δ column. Add Trend column here. ~90 chars after change.
- `output.py` — ANSI color functions, box-drawing characters, timestamp formatting — all reusable for the per-match table and focus card.
- `enrichment.py:17-26` — `_STATS_FIELD_MAP` — 14 field-name fallback chain entries. Add 3 new fields (fouls, corners, shots_off_target) in 6 lines.
- `main.py` — `--ai-preview` flag pattern (CLI arg → module flag → conditional display) — reusable for `--match-detail`.
- `state.py` — `append_prediction_history()` pattern — reusable for probability log snapshots.

### Established Patterns

- **Flag-gated display** (`--ai-preview`): CLI arg → boolean flag → `if flag: print(...)`. Pattern for `--match-detail`.
- **Inline enrichment** (Phase 17): stats/context stored on match entry during `process_matches()`/`process_group_matches()`. Focus card reads these from existing storage.
- **JSON array append** (`prediction_ledger.json`): Append-only log pattern. Reusable for `probability_log.json`.
- **Terminal-friendly tables** (`print_probability_table`): 80-char width, sorted, rank-numbered, delta column.

### Integration Points

- `output.py` — Add `print_match_detail_table()` (per-match signal table) and `print_focus_card()` (single match card).
- `main.py` — Add `--match-detail` CLI flag. Wire probability snapshot after simulation.
- `state.py` — Add `load_probability_log()`, `append_probability_log()`, `save_probability_log()`.
- `enrichment.py` — Add 3 field entries to `_STATS_FIELD_MAP`.
- `main.py:_run_iteration()` — Add probability snapshot capture at the end of each iteration loop.

### No Changes Needed

- `src/blender.py` — No display logic changes.
- `src/evaluation.py` — No display logic changes.
- `src/governance.py` — No display logic changes.
- `src/groups.py` — No display logic changes.
- `src/knockout.py` — No display logic changes.

</code_context>

<specifics>
## Specific Ideas

- The focus card is the single expansion point for all display detail: signals, CI, stats, context, xG, coach. This keeps the surface area small — one new function in `output.py` for the card, one for the table.
- `--match-detail` inverts the expected pattern: most flags add information to existing views. This flag replaces the match-results section with the signal breakdown table.
- Trend threshold should be small. Recommend 0.005 (0.5 percentage points) — small enough that meaningful drift is visible, large enough that Monte Carlo noise doesn't flip arrows every iteration.
- The probability_log.json is never pruned. Tournament is finite (104 matches, ~30 days). Even at one snapshot per minute, that's ~43,000 entries — trivially small for JSON.
- CI (Clopper-Pearson) formula: `beta.ppf(0.025, k+1, n-k+1)` to `beta.ppf(0.975, k+1, n-k+1)` where k = champion_count, n = total_iterations. Available from `scipy.stats` or manual computation (the project avoids scipy — may need a pure-Python implementation).

</specifics>

<deferred>
## Deferred Ideas

- **Championship probability signal decomposition** — answer "why is Argentina 23.4%?" by showing which signals drive their title odds. Requires a new requirement ID (V2-31+). Not in Phase 20 scope.
- **Historical backfill of stats/context/xG** for already-played matches. No consumer exists yet for historical enriched data.
- **Interactive row selection** for the focus card — currently the card is triggered by match ID. Interactive selection (arrow keys + enter) would be a UX enhancement post-MVP.
- **Probability log export / analysis** — the log is stored but not analyzed. Future phase could compute trend analysis, volatility metrics, or comparison to pre-tournament predictions.

</deferred>

---

*Phase: 20-Output Enhancement & Coverage Seal*
*Context gathered: 2026-06-21*
