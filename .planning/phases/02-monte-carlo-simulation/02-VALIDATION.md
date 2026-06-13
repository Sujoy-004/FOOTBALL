---
phase: 2
slug: monte-carlo-simulation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | worldcup_predictor/pyproject.toml or pytest.ini (from Phase 1) |
| **Quick run command** | `python -m pytest tests/ -x` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~2s |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x`
- **After every plan wave:** Run `python -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5s

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 1 | 1 | SIM-01 | T-02-01 / — | N/A — pure computation, no side effects | unit | `pytest tests/test_simulation.py -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 1 | 1 | SIM-01 | — | N/A | unit | `pytest tests/test_simulation.py -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 1 | 1 | SIM-01 | — | N/A | unit | `pytest tests/test_simulation.py -x` | ❌ W0 | ⬜ pending |
| 02-02-01 | 2 | 2 | SIM-01 | — | N/A | integration | `pytest tests/test_integration.py -x` | ✅ | ⬜ pending |
| 02-02-02 | 2 | 2 | SIM-01 | — | N/A | bench | `python scripts/benchmark_simulation.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_simulation.py` — stubs for SIM-01
- [ ] `scripts/benchmark_simulation.py` — performance benchmark stub

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Performance benchmark | SIM-01 | Performance varies by machine; benchmark must be run manually by developer | Run `python scripts/benchmark_simulation.py` and verify <5s for 50K iterations |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
