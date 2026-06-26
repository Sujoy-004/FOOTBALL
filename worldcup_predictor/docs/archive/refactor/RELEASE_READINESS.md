# Release Readiness

---

## 1. Repository Version / Tag Recommendation

```
v1.2.0-refactor
```

---

## 2. Final Repository Status

**Production Ready** — with follow-up items (see §6).

The repository has undergone a systematic 6-work-package refactor: constants centralization, private API promotion, dead code removal, duplicate code consolidation, module boundary enforcement, and hidden state encapsulation. Every commit was independently reviewable and the test suite never broke (except one intentional revert).

No regressions in prediction behavior. All existing capabilities preserved.

---

## 3. Final Test Summary

| Metric | Value |
|---|---|
| **Total tests** | 614 |
| **Passed** | 613 |
| **Skipped** | 1 (`test_live_smoke` — requires `BSD_API_KEY`) |
| **Failed** | 0 |
| **Flaky** | 1 (`test_main_loop_clean_shutdown` — timing race, ~10%) |
| **Last run** | 613 passed, 1 skipped, 49s |

---

## 4. Live Validation Summary

Live validation was **not required** for this refactor.

All behavioral changes were verified to produce identical prediction output:
- WP-4 blend change: display-only, simulation results unaffected
- WP-5 base_rate migration: every call site passes `constants.EXPECTED_GOALS_BASE_RATE` (1.25) — same value the old cache resolved
- WP-6 state encapsulation: zero changes to any function signature or simulation logic

---

## 5. Remaining Blockers (Critical)

**None.** No critical issues exist.

---

## 6. Follow-up Items

### High

| # | Item | Location |
|---|---|---|
| H1 | Decompose main.py (1531 LOC, 21 functions, 20 lazy imports) | `main.py` |
| H2 | Extract I/O from evaluation.py | `src/evaluation.py` → `src/state.py` |
| H3 | Extract display from governance.py | `src/governance.py` → `src/output.py` |
| H4 | Extract math functions from output.py | `src/output.py` (wilson_score_ci, coverage_audit, _compute_trend_arrow) |

### Medium

| # | Item | Location |
|---|---|---|
| M1 | Extract I/O from governance.py | `src/governance.py` → `src/state.py` |
| M2 | Fix flaky `test_main_loop_clean_shutdown` | `tests/test_main_loop.py` |
| M3 | Add coverage tooling and threshold | Project root |

### Low

| # | Item | Location |
|---|---|---|
| L1 | Remove dead `base_rate=1.25` default on `_simulate_single_match` | `src/groups.py` |
| L2 | Rename `_normalize` in main.py to match `fetcher.py` naming | `main.py` |
| L3 | Ignore `.coverage` artifact | `.gitignore` |

---

## 7. Recommended Next Milestone

**Feature work** — the next milestone should deliver user-visible value.

The refactoring roadmap's remaining packages (WP-7: God Object Decomposition, WP-8: CLI Evaluation Entry Point) are structural improvements that should be deferred. The codebase is clean enough to support feature development safely. Suggested next milestone:

> **Add `--eval` and `--backtest` CLI flags** (WP-8)
>
> Enables running evaluation independently of the live polling loop. High user value (CI, regression testing, offline analysis), low risk (new code path, doesn't touch existing behavior), and delivers the most visible upgrade for the least engineering cost.

Alternatives if WP-8 is not desired:
- **Historical simulation replay** — allow replaying a past tournament with current Elo ratings
- **What-if scenario mode** — interactive group stage outcome exploration
- **API key rotation** — support multiple BSD API keys for reliability

---

## 8. Recommended Git Tag

```
v1.2.0-refactor
```

Tag HEAD after the final refactor commit (8d44d5f — 6.2: lru_cache).

---

## 9. Recommended Release Branch

```
release/v1.2-refactor
```

If the intent is to merge the refactor into a mainline branch, use a release branch for final validation before merging. If working directly on `main`, no branch is needed.

---

## Final Verification Results

| Check | Status |
|---|---|
| Working tree clean | **Pass** — no modified tracked files |
| No unintended generated files tracked | **Pass** — data/ files restored to committed state |
| No secrets/API keys tracked | **Pass** — no credential patterns in .py files |
| No temporary debug code | **Pass** — no `TODO`, `FIXME`, `HACK`, `XXX`, `breakpoint()`, or debug prints |
| No TODO/FIXME introduced during refactor | **Pass** — zero new annotations |
| Documentation updated | **Pass** — WP5, WP6, audit, and this document produced |
| Test suite green | **Pass** — 613 passed, 1 skipped |
