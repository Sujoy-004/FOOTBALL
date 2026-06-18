---
phase: 13
slug: signal-ingestion
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-16
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | none — pytest default auto-discovery |
| **Quick run command** | `pytest tests/test_odds.py tests/test_catboost.py -x` |
| **Full suite command** | `pytest -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_odds.py tests/test_catboost.py -x`
- **After every plan wave:** Run `pytest -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | V2-05 | — | N/A | unit | `pytest tests/test_odds.py::TestVigRemoval -x` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | V2-05 | T-13-01 | Type-check response fields | unit | `pytest tests/test_odds.py::TestMissingOdds -x` | ❌ W0 | ⬜ pending |
| 13-01-03 | 01 | 1 | V2-05 | — | N/A | integration | `pytest tests/test_odds.py::TestOddsPersistence -x` | ❌ W0 | ⬜ pending |
| 13-02-01 | 02 | 1 | V2-06 | — | N/A | unit | `pytest tests/test_catboost.py::TestParsePredictions -x` | ❌ W0 | ⬜ pending |
| 13-02-02 | 02 | 1 | V2-06 | T-13-01 | Type-check response fields | unit | `pytest tests/test_catboost.py::TestMissingPredictions -x` | ❌ W0 | ⬜ pending |
| 13-02-03 | 02 | 1 | V2-06 | — | N/A | integration | `pytest tests/test_catboost.py::TestCatboostCache -x` | ❌ W0 | ⬜ pending |
| 13-03-01 | 03 | 2 | V2-05, V2-06 | — | N/A | integration | `pytest -x` | ❌ W0 | ⬜ pending |
| 13-04-01 | 04 | 2 | V2-05, V2-06 | — | N/A | integration | `pytest tests/test_evaluation.py -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_odds.py` — vig removal, cache TTL, missing odds, persistence
- [ ] `tests/test_catboost.py` — prediction parsing, missing predictions, cache TTL
- [ ] No framework install needed — pytest already available

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live BSD odds endpoint response | V2-05 | Requires live BSD_API_KEY | Run `python -c "from src.predictors.odds import fetch_odds; print(fetch_odds('...'))"` and verify odds_home/odds_draw/odds_away fields present |
| Live BSD predictions endpoint response | V2-06 | Requires live BSD_API_KEY | Run `python -c "from src.predictors.catboost import fetch_catboost; print(fetch_catboost('...'))"` and verify home_probability/draw_probability/away_probability fields present |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
