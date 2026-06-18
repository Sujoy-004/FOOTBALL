---
phase: 16
slug: model-governance
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-17
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` |
| **Quick run command** | `python -m pytest -x` |
| **Full suite command** | `python -m pytest` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest -x`
- **After every plan wave:** Run `python -m pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | V2-12 | — | N/A | unit | `pytest tests/test_state.py -x -k "version"` | ❌ W0 | ⬜ pending |
| 16-01-02 | 01 | 1 | V2-12 | — | N/A | unit | `pytest tests/test_governance.py -x -k "data_version"` | ❌ W0 | ⬜ pending |
| 16-01-03 | 01 | 1 | V2-12 | — | N/A | unit | `pytest tests/test_governance.py -x -k "model_version"` | ❌ W0 | ⬜ pending |
| 16-02-01 | 02 | 1 | V2-12 | — | N/A | unit | `pytest tests/test_state.py -x -k "run_snapshot"` | ❌ W0 | ⬜ pending |
| 16-03-01 | 03 | 2 | V2-13 | — | N/A | unit | `pytest tests/test_governance.py -x -k "drift"` | ❌ W0 | ⬜ pending |
| 16-03-02 | 03 | 2 | V2-13 | — | N/A | unit | `pytest tests/test_governance.py -x -k "drift_threshold"` | ❌ W0 | ⬜ pending |
| 16-03-03 | 03 | 2 | V2-13 | — | N/A | unit | `pytest tests/test_governance.py -x -k "cold_start"` | ❌ W0 | ⬜ pending |
| 16-04-01 | 04 | 2 | V2-14 | — | N/A | unit | `pytest tests/test_evaluation.py -x -k "backtest"` | ❌ W0 | ⬜ pending |
| 16-04-02 | 04 | 2 | V2-14 | — | N/A | integration | `pytest tests/test_main_loop.py -x -k "backtest"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_governance.py` — new test file covering V2-12, V2-13, V2-14 unit tests
- [ ] Fixtures: mock prediction_history with known Brier values for drift testing
- [ ] Fixtures: mock versions.json with known version state for increment testing
- [ ] Fixtures: historical tournament match data (small subset for backtest unit tests)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Governance dashlet visual layout | D-17, D-18 | Console output — format and spacing need visual inspection | Run `main.py --once` after governance implementation; verify cold-start format at <30 matches, active format at >=30 |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
