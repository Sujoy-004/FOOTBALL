# Phase 4: Validation & Production Readiness — Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Prove the UCL module is correct and production-ready. Fetch live BSD API match results for UCL, cross-check predictions against real outcomes with accuracy metrics (Brier, Log Loss, calibration curve), benchmark simulation performance, verify WC/Euro regression is unaffected, and write documentation covering architecture, known limitations, and release notes.

This phase consumes Phase 3's `SimulationResult` contract for prediction export and extends `ucl-predict` with validation capabilities. BSD integration uses `football_core.fetcher.fetch_raw_matches()` (already shared by WC) with UCL-specific normalization.
</domain>

<canonical_refs>
- `.planning/REQUIREMENTS.md` — UCLV-01 through UCLV-06
- `.planning/ROADMAP.md` — Phase 4 goal, success criteria, plan list
- `.planning/phases/03-ucl-orchestration-display/03-CONTEXT.md` — D-15 to D-20 (SimulationResult contract ownership, JSON schema stability)
- `football_core/evaluation.py` — (NEW) extracted accuracy metrics
- `football_core/fetcher.py` — `fetch_raw_matches()` shared BSD entry point
- `competitions/worldcup/src/evaluation.py` — existing (will be updated to use football_core)
- `competitions/worldcup/src/fetcher.py` — existing BSD integration pattern
- `competitions/worldcup/benchmarks/benchmark_groups.py` — existing benchmark pattern
</canonical_refs>

<code_context>
## Existing Patterns and Assets

### BSD Data Fetching (WC pattern)
- `football_core.fetcher.fetch_raw_matches(api_key, api_url, league_id, timeout)` — shared BSD API entry point
- `competitions/worldcup/src/fetcher.py` — WC-specific normalization, alias resolution, bracket matching
- BSD URL format: `https://sports.bzzoiro.com/api/events/?league_id={id}&limit=200`
- UCL params: league_id=7, season_id=268 (established Phase 2)

### Evaluation (WC)
- `competitions/worldcup/src/evaluation.py` — `brier_score()`, `log_loss()`, `calibration_curve()`, `evaluate_all_matches()`
- Will be extracted to `football_core/evaluation.py` and re-imported by WC

### Benchmarking (WC)
- `competitions/worldcup/benchmarks/benchmark_groups.py` — standalone script, measures wall-clock time at 1K/10K/50K iterations
- Outputs to `BENCHMARK_RESULTS.md` in the benchmarks directory
- Uses `time.time()`, prints results table

### Test Suite Baseline
- WC: 613 passed, 1 skipped
- UCL: 129 passed, 1 skipped
- Euro sim: identical results after every change (must remain unchanged)
</code_context>

<decisions>
## Implementation Decisions

### BSD API Integration Strategy
- **D-01:** CLI `--validate` flag on `ucl-predict` — not a standalone script. The existing `ucl-predict` entry point gains validation capability. No new entry points.
- **D-02:** Validation output is dual: a concise accuracy summary table printed to stdout (games played, Brier, Log Loss) AND the existing `--output` JSON enriched with validation results section.
- **D-03:** Validation compares against both actual match outcomes (home win/draw/away win) AND pre-match market odds from BSD API.

### Accuracy Metrics — Extraction to football_core
- **D-04:** Extract `brier_score()`, `log_loss()`, `calibration_curve()` to `football_core/evaluation.py`. The Rule of Two is satisfied — UCL is the second competition needing these functions.
- **D-05:** Update `competitions/worldcup/src/evaluation.py` to import from `football_core.evaluation` instead of defining its own copies. Proves the extraction works with a second consumer.

### Performance Benchmark Format
- **D-06:** Standalone benchmark script at `competitions/ucl/benchmarks/benchmark_simulation.py` — matches WC pattern (`competitions/worldcup/benchmarks/`).
- **D-07:** Measure wall-clock time only at 1K, 10K, and 50K iterations. No memory or iteration variance measurement (Phase 4 enhancements if needed later). Output to `BENCHMARK_RESULTS.md`.

### Fixture Schedule
- **D-08:** Proceed with synthetic fixture schedule for Phase 4 validation. The engine architecture is correct and the synthetic schedule exercises all code paths. Document the limitation: "Validation performed with synthetic fixtures — re-run with official UCL 25/26 schedule when available."

### agent's Discretion
- BSD fetcher file name and location within `competitions/ucl/` (matching WC's fetcher.py pattern)
- Validation result JSON schema (structure of enriched output)
- Benchmark script structure, iteration timing loops, result markdown format
- `football_core/evaluation.py` function signatures — must match WC's current signatures exactly for backward compatibility
- WC import migration in `competitions/worldcup/src/evaluation.py` — change import source, remove duplicate definitions
- Whether `validate_all_matches()` needs new calibration/plotting or just metric computation
</decisions>

<scope_boundary>
## Phase Boundary — What's NOT in this phase

- **What-if scenario analysis** (UCLD-01) — Phase 5 differentiator
- **Competition differentiators** (player form, lineup optimization, signal blending) — Phase 5
- **Euro sys.path hack removal** (ENG-02) — separate refactoring phase
- **football_core API stabilization** (ENG-03) — separate refactoring phase  
- **Web UI / dashboard** — explicitly out of scope (PROJECT.md)
- **pip-installable package** — deferred until 3 competitions proven
</scope_boundary>

<deferred>
## Deferred Ideas

- Memory profiling and iteration variance in benchmarks — enhancement if wall-clock benchmarks show no issues
</deferred>
