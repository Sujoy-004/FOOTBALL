# Context Notes

## Architecture Validation Report
- **source:** competitions/worldcup/docs/archive/refactor/ARCHITECTURE_VALIDATION.md
- **type:** DOC (high confidence)

Validates 14 architecture audit findings with source-level code evidence. Confirms or partially confirms each finding related to refactoring outcomes across main.py, groups.py, blender.py, output.py, evaluation.py, governance.py, state.py, and fetcher.py.

---

## BASE_RATING Investigation
- **source:** competitions/worldcup/docs/archive/refactor/BASE_RATING_INVESTIGATION.md
- **type:** DOC (high confidence)

Investigation into whether BASE_RATING constant exists in the codebase. Documents duplicated constants found: COLD_START_THRESHOLD, BRIER_WINDOW_SIZE, MAX_EXPECTED_GOALS — some were duplicated across blender.py and constants.py. This investigation informed WP-4 (duplicate code consolidation).

---

## Changelog (root)
- **source:** competitions/worldcup/CHANGELOG.md
- **type:** DOC (high confidence)

Documents v1.2.0-refactor with 6 work packages. Covers: WP-1 Constants Centralization, WP-2 Private API Promotion, WP-3 Dead Code Removal, WP-4 Duplicate Code Consolidation, WP-5 Module Boundary Enforcement, WP-6 Hidden State Encapsulation. 613 tests passed, 1 skipped, 1 flaky. Deferred items: WP-7 God Object Decomposition, WP-8 CLI Evaluation Entry Point.

**Duplicate note:** An identical copy of this changelog exists at `competitions/worldcup/docs/archive/refactor/CHANGELOG.md`. Both documents have identical content. Users should treat the root-level copy as canonical and the archive copy as a historical snapshot.

---

## Changelog (archive refactor)
- **source:** competitions/worldcup/docs/archive/refactor/CHANGELOG.md
- **type:** DOC (high confidence)

Identical content to the root CHANGELOG.md. Lists v1.2.0-refactor across 6 work packages with same details. This is a duplicate copy — see the root changelog entry above for full content.

---

## Commonality Report
- **source:** docs/COMMONALITY_REPORT.md
- **type:** DOC (high confidence)

Rule-of-Two audit comparing World Cup and Euro implementations to identify empirically proven candidates for `football_core` extraction.
- **Dual-proven (extracted):** `elo.py`, `fetcher.py`, `predictors/odds.py`, `predictors/catboost.py`, `math_utils.py`
- **Config-difference only:** `elo_sync.py` (URL parameterized), `constants.py` (generic subset extracted to `football_core/constants.py`)
- **Partially shared:** `state.py` (generic I/O extracted), `groups.py` (poisson core + tiebreaker chain extracted), `knockout.py` (generic round simulation extracted)
- **Single-proven (remain in WC):** `blender.py`, `evaluation.py`, `governance.py`, `predictors/form.py`, `predictors/lineup.py`, `enrichment.py`
- **Euro sys.path hack:** Remains because `simulation.py` imports from `src.groups` (WC) for `resolve_knockout_slot_teams`

---

## Final Refactor Audit
- **source:** competitions/worldcup/docs/archive/refactor/FINAL_REFACTOR_AUDIT.md
- **type:** DOC (high confidence)

Comprehensive audit of WP-1 through WP-6 refactoring covering 6 work packages across ~25 commits. Documents:
- **Architecture:** Constants centralized, private API promoted, dead code (7 functions) removed, 3 instances of duplicated code resolved, module boundaries cleaned (groups.py→blender.py dependency removed), hidden state encapsulated (8 main.py globals → RunState, _POISSON_TABLES → lru_cache)
- **Remaining violations:** evaluation.py imports from state.py (I/O leak), governance.py imports from output.py (display leak), main.py at 1531 LOC (god object)
- **Test health:** 613 passed, 1 skipped (live smoke requires BSD_API_KEY), 1 flaky (test_main_loop_clean_shutdown — timing race)
- **Production readiness:** "Yes, with follow-up items" — zero behavioral regressions, zero breaking API changes
- **Remaining issues:** H1-H4 high priority (god object, computation→I/O, governance→display, large output module), M1-M4 medium, L1-L3 low

---

## Flaky Test Remediation
- **source:** competitions/worldcup/docs/archive/refactor/FLAKY_TEST_REMEDIATION.md
- **type:** DOC (medium confidence)

Root cause analysis and remediation for `test_main_loop_clean_shutdown`, a flaky subprocess shutdown test. Multiple candidate fixes evaluated with pros/cons/risk assessment. Has ADR-like qualities (options analysis, recommendation) but lacks formal decision status — classified as supporting context.

---

## Handover (root)
- **source:** competitions/worldcup/HANDOVER.md
- **type:** DOC (high confidence)

Post-refactor handover document detailing repository state, remaining follow-ups, and recommended next milestones. References all refactoring documentation in `docs/archive/refactor/`. Scope includes main.py, src/constants.py, src/fetcher.py, src/evaluation.py, src/governance.py, src/output.py.

---

## Handover (archive refactor)
- **source:** competitions/worldcup/docs/archive/refactor/HANDOVER.md
- **type:** DOC (high confidence)

Handover document summarizing the completed 6-work-package refactor with remaining follow-ups and next steps. Overlaps with the root HANDOVER.md in scope. Covers main.py, evaluation.py, governance.py, output.py, codebase architecture, refactoring.

---

## Implementation Plan
- **source:** competitions/worldcup/docs/archive/refactor/IMPLEMENTATION_PLAN.md
- **type:** DOC (high confidence)

Step-by-step refactoring plan across 8 work packages with 38 commits. Covers: constants, groups, output, main, fetcher, odds, catboost, state, blender, evaluation, governance, cli, signals, math_utils, orchestrator. Defines the execution order for the v1.2.0-refactor milestone.

---

## Live Validation Report
- **source:** competitions/worldcup/docs/archive/refactor/LIVE_VALIDATION_REPORT.md
- **type:** DOC (high confidence)

Validation report verifying that display blended probability matches simulation for 72 matches after a blend fix (Commit 4.5). Covers World Cup calibration pipeline, Elo signal, and market odds signal.

---

## README — World Cup Dynamic Predictor
- **source:** competitions/worldcup/README.md
- **type:** DOC (high confidence)

Project README describing the World Cup 2026 live tournament predictor. 3-signal architecture (Elo, market odds, CatBoost), 48-team/12-group format, 50K Monte Carlo simulation, evaluation framework. Installation and usage instructions for CLI tool.

---

## README — UCL Predictor
- **source:** competitions/ucl/README.md
- **type:** DOC (low confidence — placeholder, 3 lines)

Placeholder README for the UCL Predictor project containing only "# UCL Predictor" and "Coming soon." No frontmatter, sections, decisions, requirements, or specifications.

---

## Refactoring Roadmap
- **source:** competitions/worldcup/docs/archive/refactor/REFACTORING_ROADMAP.md
- **type:** DOC (high confidence)

Archived refactoring roadmap documenting completed work packages, principles, and metrics for codebase restructuring. Marked COMPLETED.

---

## Release Readiness
- **source:** competitions/worldcup/docs/archive/refactor/RELEASE_READINESS.md
- **type:** DOC (high confidence)

Release readiness assessment for v1.2.0-refactor work package. Includes test results and follow-up items.

---

## Shutdown Equivalence Proof
- **source:** competitions/worldcup/docs/archive/refactor/SHUTDOWN_EQUIVALENCE.md
- **type:** DOC (high confidence)

Formal proof analyzing whether reusing `prev_probs` is equivalent to full re-computation at shutdown. Covers shutdown equivalence, prev_probs, simulation, calibration, cache consistency, and blending.

---

## WP-5 Architecture Summary: Module Boundary Enforcement
- **source:** competitions/worldcup/docs/archive/refactor/WP5_ARCHITECTURE_SUMMARY.md
- **type:** DOC (medium confidence — retrospective summary with lessons learned)

Documents WP-5 refactoring that enforced explicit module boundary dependencies for `base_rate` parameter. API changes: `expected_goals`, `precompute_matchup_lambdas`, `simulate_group_matches` all moved `base_rate` from "optional with default" to "required (positional)". Eliminated a hidden dependency chain (groups.py → blender.py) and a module-level cache. Contains lessons learned on callers-first migration pattern, automated caller verification, and hidden defaults vs explicit parameters.

---

## WP-6 Architecture Summary: Hidden State Encapsulation
- **source:** competitions/worldcup/docs/archive/refactor/WP6_ARCHITECTURE_SUMMARY.md
- **type:** DOC (high confidence)

Documents WP-6 refactoring that encapsulated module-level hidden state into an explicit `RunState` dataclass. Key changes:
- **8 module-level globals** in main.py → `RunState` dataclass fields
- **5 `global` keywords** eliminated across the codebase
- **Manual cache** (`_POISSON_TABLES` in groups.py) → `functools.lru_cache`
- **2 latent bugs fixed:** governance timer never updated (shadowed by local variable), dead module-level declarations removed
- **0 signature changes** — all behavioral changes are internal
- Covers main.py, groups.py, governance timer, poisson tables

*Generated by gsd-doc-synthesizer — merge mode, 2026-06-27*
