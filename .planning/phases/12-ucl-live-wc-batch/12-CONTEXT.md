# Phase 12: UCL Live Monitor + WC Batch Research - Context

**Gathered:** 2026-07-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Two parallel workstreams cross-pollinating features between competition modules. UCL gets the continuous polling, state persistence, and incremental Elo that WorldCup already has. WorldCup gets the offline simulation, counterfactual analysis, structured reports, and signal breakdown that UCL already has.

Workstream A (UCL Live Monitor) — 19 tasks: state persistence, incremental Elo, polling loop, historical catch-up, signal cache, delta display, mode routing, tests.

Workstream B (WC Batch Research) — 15 tasks: offline simulation, counterfactual analysis, JSON report, signal breakdown, confidence intervals, calibrated validation, weight override, benchmarks, tests.

Zero modifications to `football_core`. Both workstreams operate entirely within their respective `competitions/<name>/` directory.
</domain>

<decisions>
## Implementation Decisions

### D-01: State Persistence Format (UCL Live Monitor)
- **Multiple separate files** matching WC's pattern (`ucl_played.json`, `ucl_prediction_history.json`, `ucl_elo_applied.json`), not a single consolidated file.
- **UCL-prefixed names** to avoid ambiguity if both monitors run in the same directory.
- **Directory:** `competitions/ucl/data/live/` — subdirectory separate from static data.
- **Write strategy:** Atomic write every cycle via `tempfile.mkstemp` + `os.replace` (matching WC's existing pattern in `football_core.state`).
- Reuses `football_core.state` for persistence primitives (already dual-proven by WC + UCL via Phase 4 validation fetcher).

### D-02: Live Display Style (UCL Live Monitor)
- **In-place re-render** using ANSI cursor-up sequences (like `top`/`htop`), not streaming lines or compact heartbeat.
- **ANSI cursor-up on Windows** — acceptable on modern Windows Terminal and PowerShell 7. Phase 11's ASCII-only constraint was about Unicode glyphs, not ANSI control sequences. ANSI escape codes are pure ASCII.
- **Full display** per poll iteration: probability table + league table standings + bracket probabilities (same layout as `--mode simulate`).
- **Delta display:** Compact dedicated delta column in probability table: `Team | Prob | Delta`, showing `+/-` percentage change from previous poll.

### D-03: Historical Catch-Up (UCL Live Monitor)
- **Current season 2025/26 only** — MD 1-7 (125/144 matches played, MD 8 on Jan 29). Not all available BSD history.
- **Sequential per-match processing** — replay each past match through `elo_updater.apply_elo_update()` and signal refresh, replicating live behavior exactly.
- **Catch-up detection:** Compare latest BSD fetch against last entry in `ucl_played.json`. If latest match matches, catch-up is complete.
- **Error handling:** Retry with exponential backoff (up to 3 times, matching WC pattern). If all retries fail, abort with clear error message. User re-runs command to retry.

### D-04: Signal Cache Configuration (UCL Live Monitor)
- **Configurable per-signal TTLs** via config JSON (`config/cache_ttls.json`), not hardcoded. Allows tuning and adding new signals without code changes.
- **Cache refresh trigger:** TTL expiry OR new match event detected (whichever comes first). More responsive than TTL-only.
- **Cache file location:** Alongside state files in `competitions/ucl/data/live/`.
- **Naming:** Prefix-based: `ucl_odds_cache.json`, `ucl_catboost_cache.json` — consistent with `ucl_` prefix pattern for state files.

### D-05: Counterfactual Parameter Scope (WC Batch Research)
- **Everything mutable:** Elo, blend weights, xG overrides, calibration temperature — not just Elo.
- **CLI syntax:** JSON config override file (`--what-if path/to/override.json`). Single file describes all overrides. Cleaner than multi-flag syntax for complex scenarios.
- **Comparison display:** Side-by-side table showing baseline vs combined-with-overrides in a single compact table with delta column.
- **No file export for comparisons** — CLI-only display.

### D-06: Signal Breakdown Format (WC Batch Research)
- **Agent discretion:** Start with UCL's format template, customize per signal where practical.
- **Detail level:** Summary + context — not just contribution percentage, include brief explanation (e.g., "Odds: +15% (implied 22% from Pinnacle)").
- **Breakdown scope:** `--show-breakdown match` shows per-match signal contributions (each group match). Not just tournament-level.
- **Always-on display** (matching UCL's always-on pattern) — signal breakdown printed every simulation cycle.

### D-07: Calibrated Validation Comparison (WC Batch Research)
- **Baseline strategy:** Always compute both uncalibrated and calibrated dynamically. Cache baseline-only results (they don't change between runs). Fast after first run, always has comparison.
- **Metrics:** Full suite — Brier, Log Loss, ECE, TRPS, champion accuracy.
- **Display format:** Side-by-side table: `Metric | Before | After | Delta`.
- **Export:** CLI-only display. Not appended to `--report` output.

### Locked from Prior Phases
- Two independent workstreams, zero file overlap, parallel execution (ADR-003, Phase 12 D-01 in STATE.md).
- UCL reuses `football_core.state` for persistence — no new persistence primitives (Phase 12 D-02).
- WC reuses `run_full_simulation()` — no engine changes (Phase 12 D-03).
- WC signal breakdown reuses `_gather_signal_data()` (Phase 12 D-04).
- WC CI display reuses `wilson_score_ci` (Phase 12 D-05).
- WC `--weights` skips Brier optimization, passes static weights directly (Phase 12 D-06).
- ASCII-only output convention (no Unicode arrows) per Phase 11 D-04. ANSI escape sequences (cursor-up) are pure ASCII and permitted.
- No modifications to `football_core` (ADR-003).

</decisions>

<canonical_refs>
## Canonical References

Downstream agents MUST read these before planning or implementing.

### Architecture & Decisions
- `.planning/decisions/ADR-003-parallel-workstreams.md` — Two-workstream architecture with zero file contention, no football_core changes.
- `.planning/PROJECT.md` — Architecture constraints, competition boundary rules, sys.path bootstrap.
- `.planning/STATE.md` — Phase 12 D-01 through D-06 (locked prior decisions), blockers/concerns.
- `.planning/REQUIREMENTS.md` — UCL-LIVE-01 through UCL-LIVE-12, WC-BATCH-01 through WC-BATCH-15.

### Prior Phase Context
- `.planning/phases/11-explainability-production/11-CONTEXT.md` — Windows ASCII-only convention, signal breakdown format pattern.
- `.planning/phases/10-probability-calibration-uncertainty/10-CONTEXT.md` — Calibration pipeline, confidence intervals, Bayesian Elo.
- `.planning/phases/09-tournament-validation/09-CONTEXT.md` — Three-tier validation framework, baseline recording, TRPS metrics.

### Codebase Maps
- `.planning/codebase/STACK.md` — Python 3.11+, JSON persistence, argparse CLI, signal handlers, atomic file writes.
- `.planning/codebase/ARCHITECTURE.md` — Modular monolith, UCL vs WC architectural differences, data flow diagrams.
- `.planning/codebase/INTEGRATIONS.md` — BSD API endpoints, eloratings.net TSV sync, rate limiting, JSON state file patterns.

### Existing Code (implied by architecture maps)
- `competitions/worldcup/src/state.py` — Pattern for live_state.py (wraps football_core.state with competition paths).
- `competitions/worldcup/main.py` — Polling loop pattern for UCL `--watch` mode.
- `competitions/ucl/main.py` — Existing CLI entry point, signal breakdown format pattern for WC.
- `football_core/state.py` — JSON load/save with atomic writes (reused by UCL monitor).
- `football_core/math_utils.py` — `wilson_score_ci` (reused by WC CI display).
- `football_core/blender.py` — `blend_predictions` (reused by WC `--weights`).
- `competitions/ucl/src/simulation.py` — `run_full_simulation` (reused by WC batch mode).
- `competitions/ucl/src/display.py` — Signal breakdown display format (template for WC).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `football_core.state` — JSON persistence with atomic writes (tempfile + os.replace). Proven by both WC and UCL Phase 4 validation fetcher. UCL live monitor wraps it in `live_state.py` with competition-specific paths and ucl_ prefix.
- `competitions/worldcup/main.py` — Polling loop with SIGINT handler, `_run_iteration()`, heartbeat. UCL monitor reuses the same loop pattern, adapted for UCL's simulation flow.
- `competitions/worldcup/src/state.py` — Competition-specific state wrapper (WC paths). UCL's `live_state.py` follows the same wrapper pattern.
- `football_core.elo_sync` — Graduated correction logic (<10 ignore, 11-30 blend, >30 overwrite). UCL `elo_updater.py` reuses this pattern.
- `competitions/ucl/src/display.py` — Signal contribution breakdown formatting. WC reuses format template, adapts per-signal.
- `football_core.math_utils.wilson_score_ci` — Wilson score CI function. Already imported by WC `output.py`. WC batch mode just needs formatting.

### Established Patterns
- **Competition boundary:** All new files go in `competitions/<name>/src/` or `competitions/<name>/tests/`. Zero changes to `competitions/<other>/` or `football_core/`.
- **Atomic file writes:** `tempfile.mkstemp` + `os.replace` for all JSON persistence. No direct `open()` + `write()` + `close()`.
- **CLI flag pattern:** `argparse`, flags in `main.py`, descriptive help text, case-insensitive enum choices, centralized validation.
- **Test pattern:** `pytest` with `test_` prefix, one file per module, `conftest.py` for fixtures.
- **Graceful shutdown:** `signal.signal(signal.SIGINT, handler)` setting `running = False`. Final state save in signal handler.

### Integration Points
- Workstream A (UCL): `competitions/ucl/main.py` — add `--watch`, `--poll-interval`, `--once`, `--mode live` flags. `competitions/ucl/src/live_state.py` — new file. `competitions/ucl/src/elo_updater.py` — new file.
- Workstream B (WC): `competitions/worldcup/main.py` — add `--simulate`, `--iterations`, `--what-if`, `--report`, `--show-breakdown`, `--show-ci`, `--validate-calibrated`, `--weights` flags.
</code_context>

<specifics>
No specific references or "I want it like X" moments during discussion. Standard implementation approaches for all areas.
</specifics>

<deferred>
None — discussion stayed within phase scope.
</deferred>

---

*Phase: 12-UCL Live Monitor + WC Batch Research*
*Context gathered: 2026-07-07*
