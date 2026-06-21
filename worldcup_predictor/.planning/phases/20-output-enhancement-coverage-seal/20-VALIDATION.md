---
phase: 20
slug: output-enhancement-coverage-seal
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-21
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x |
| **Config file** | `pytest.ini` (root) |
| **Quick run command** | `pytest tests/test_output.py tests/test_enrichment.py tests/test_state.py -x -q` |
| **Full suite command** | `pytest -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_output.py tests/test_enrichment.py tests/test_state.py -x -q`
- **After every plan wave:** Run `pytest -x -q` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 20-XX-01 | 01 | 1 | V2-30 | — | N/A — pure extraction | unit | `pytest tests/test_enrichment.py::TestExtractStats -x -q` | ✅ existing | ⬜ pending |
| 20-XX-02 | 01 | 1 | V2-30 | — | N/A — pure computation | unit | `pytest tests/test_output.py::TestCoverageAudit -x -q` | ❌ W0 | ⬜ pending |
| 20-XX-03 | 02 | 1 | V2-27 | — | N/A — display only | unit | `pytest tests/test_output.py::TestMatchDetailTable -x -q` | ❌ W0 | ⬜ pending |
| 20-XX-04 | 02 | 1 | V2-27 | — | N/A — display only | unit | `pytest tests/test_output.py::TestFocusCard -x -q` | ❌ W0 | ⬜ pending |
| 20-XX-05 | 02 | 1 | V2-28 | — | N/A — pure math | unit | `pytest tests/test_output.py::TestWilsonCI -x -q` | ❌ W0 | ⬜ pending |
| 20-XX-06 | 03 | 2 | V2-29 | — | N/A — JSON persistence | unit | `pytest tests/test_state.py::TestProbabilityLog -x -q` | ❌ W0 | ⬜ pending |
| 20-XX-07 | 03 | 2 | V2-29 | — | N/A — display only | unit | `pytest tests/test_output.py::TestTrendColumn -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_output.py` — Add TestMatchDetailTable, TestFocusCard, TestWilsonCI, TestTrendColumn, TestCoverageAudit classes
- [ ] `tests/test_state.py` — Add TestProbabilityLog class (load, append, format)
- [ ] `tests/test_enrichment.py` — Add new field extraction tests (fouls, corners, shots_off_target)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Per-match signal table renders within 85-char terminal width | V2-27 | Visual layout validation | Run `python main.py --match-detail` and verify no line wrapping |
| Focus card matches D-20 layout (signals → Δ/CI → context → stats) | V2-27 | Visual layout validation | Run `python main.py --match-detail M73` and verify section order |
| Trend arrow updates correctly across multiple iterations | V2-29 | Requires observing live runs | Let script poll for 3+ cycles, verify arrows change plausibly |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
