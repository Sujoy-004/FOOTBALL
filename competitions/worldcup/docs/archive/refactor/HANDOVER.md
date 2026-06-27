# Handover

## Current Repository State

The codebase has undergone a systematic 6-work-package refactor (`v1.2.0-refactor`). All planned refactoring is complete. The repository is production-ready with 613 passing tests (1 skipped, 1 flaky).

### What was done

- **Constants** centralized in `src/constants.py` — no inline magic numbers
- **Private API** promoted to public in `src/fetcher.py`
- **Dead code** removed — 7 functions eliminated
- **Duplicates** consolidated — sigmoid extracted, display blend fixed, blender constants deduplicated
- **Module boundaries** enforced — `groups.py` no longer imports `blender.py`, `base_rate` is explicit at every boundary
- **Hidden state** encapsulated — 8 globals → `RunState` dataclass, `_POISSON_TABLES` → `lru_cache`, zero `global` keywords

### Key metrics

| Metric | Before | After |
|---|---|---|
| `global` keywords | 5 | 0 |
| Module-level mutable vars (main.py) | 8 | 1 (encapsulated) |
| Module-level mutable collections (groups.py) | 2 | 0 |
| Cross-module boundary violations (groups.py) | 1 | 0 |
| Dead functions | 7 | 0 |

## Remaining High-Priority Follow-ups

| Priority | Item | Location | Description |
|---|---|---|---|
| H1 | God Object | `main.py` (1531 LOC, 21 funcs) | main.py is still the largest module. WP-7 deferred. |
| H2 | I/O at computation layer | `src/evaluation.py` | Imports `append_prediction_history`, `load_prediction_history` from `state`. Should receive data as parameter. |
| H3 | Display at governance layer | `src/governance.py` | Imports `print_governance_dashlet` from `output`. Should return data, let caller display. |
| H4 | Large mixed module | `src/output.py` (952 LOC) | Contains `wilson_score_ci`, `coverage_audit`, `_compute_trend_arrow` mixed with display formatting. |

## Recommended Next Milestone

**WP-8: CLI Evaluation Entry Point** — add `--eval` and `--backtest` flags.

This delivers the most visible improvement for the least engineering cost:
- New code paths only (zero risk to existing behavior)
- Enables CI, regression testing, and offline analysis
- Builds on the already-cleaned `evaluation.py` interface
- Approximately 2-3 commits, purely additive

**Alternative:** If not WP-8, the next feature milestone could be:
- Historical simulation replay (useful for what-if analysis)
- Interactive group stage exploration mode
- Multi-league support improvements

## Archived Documents

All refactor planning documents have been moved to `docs/archive/refactor/`:
- `REFACTORING_ROADMAP.md` — marked as completed
- `IMPLEMENTATION_PLAN.md` — full plan with per-commit details
- `WP5_ARCHITECTURE_SUMMARY.md` — module boundary enforcement summary
- `WP6_ARCHITECTURE_SUMMARY.md` — hidden state encapsulation summary
- `FINAL_REFACTOR_AUDIT.md` — comprehensive audit with remaining issues
- `RELEASE_READINESS.md` — release readiness assessment
- Supporting docs: `ARCHITECTURE_VALIDATION.md`, `BASE_RATING_INVESTIGATION.md`, `FLAKY_TEST_REMEDIATION.md`, `LIVE_VALIDATION_REPORT.md`, `SHUTDOWN_EQUIVALENCE.md`

## Git Tag

```
v1.2.0-refactor  (HEAD, commit 8d44d5f)
```

## Principles to Preserve

The following architectural rules should be maintained in future development:
1. **Callers-first, signature-last** — when changing an API, update all callers first while backward compatibility exists, then remove the default
2. **No hidden mutable state** — prefer dataclasses and dependency injection over module-level globals
3. **No I/O in computation modules** — pass data as parameters, don't load from disk
4. **Green after every commit** — each commit must leave the test suite passing
5. **One concern per module** — computation, I/O, display, and orchestration should be in separate modules
