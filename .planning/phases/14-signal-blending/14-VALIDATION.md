---
phase: 14
slug: signal-blending
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-16
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x |
| **Config file** | none — worldcup_predictor/pyproject.toml or pytest.ini not present |
| **Quick run command** | `pytest -v tests/test_blender.py` |
| **Full suite command** | `pytest -v` |
| **Estimated runtime** | ~5-10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest -v tests/test_blender.py`
- **After every plan wave:** Run `pytest -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | V2-07 | T-14-01 / — | Platt fit never crashes on edge case data | unit | `pytest tests/test_blender.py::TestPlattCalibration -v` | ❌ W0 | ⬜ pending |
| 14-01-02 | 01 | 1 | V2-07 | T-14-02 / — | Identity calibration returned when data insufficient | unit | `pytest tests/test_blender.py::TestColdStart -v` | ❌ W0 | ⬜ pending |
| 14-01-03 | 01 | 1 | V2-07 | — / — | Calibrated prob in [0,1] for all valid inputs | unit | `pytest tests/test_blender.py::TestCalibrationEdgeCases -v` | ❌ W0 | ⬜ pending |
| 14-02-01 | 02 | 1 | V2-08 | T-14-03 / — | Weight function handles all-equal Brier, zero Brier | unit | `pytest tests/test_blender.py::TestBlendWeights -v` | ❌ W0 | ⬜ pending |
| 14-02-02 | 02 | 1 | V2-08 | T-14-04 / — | Blender re-normalizes when signals missing | unit | `pytest tests/test_blender.py::TestGracefulDegradation -v` | ❌ W0 | ⬜ pending |
| 14-02-03 | 02 | 1 | V2-08 | — / — | Blended prob fed to simulation correctly | integration | `pytest tests/test_main_loop.py -v` | ✅ exist | ⬜ pending |
| 14-03-01 | 03 | 2 | V2-09 | — / — | Poisson base rate computed from data | unit | `pytest tests/test_groups.py -v` | ✅ exist | ⬜ pending |
| 14-03-02 | 03 | 2 | V2-09 | — / — | Fallback to 1.25 when no historical data | unit | `pytest tests/test_groups.py::TestPoissonBaseRate -v` | ❌ W0 | ⬜ pending |
| 14-04-01 | 04 | 2 | V2-07, V2-08 | T-14-05 / — | LOO-CV reports blended < best single Brier correctly | integration | `pytest tests/test_evaluation.py -v` | ✅ exist | ⬜ pending |

---

## Wave 0 Requirements

- [ ] `tests/test_blender.py` — complete test file with classes: TestPlattCalibration, TestColdStart, TestCalibrationEdgeCases, TestBlendWeights, TestGracefulDegradation, TestRollingBrier, TestPoissonBaseRate
- [ ] `tests/conftest.py` — add blender fixtures: sample_signal_briers, sample_prediction_history with multi-signal entries
- [ ] Existing infrastructure covers all phase requirements

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| LOO-CV Brier comparison | V2-08 | Requires running full evaluate pipeline | Run `python -c "from src.blender import evaluate_blender; ..."` or check eval_baseline_report.json |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
