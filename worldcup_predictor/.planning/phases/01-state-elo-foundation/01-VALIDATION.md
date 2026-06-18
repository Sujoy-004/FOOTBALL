---
phase: 1
slug: state-elo-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | none — pytest defaults for Phase 1 |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | VAL-01 | unit | `pytest tests/test_state.py::test_duplicate_match_id -x` | ❌ W0 | ⬜ pending |
| 01-01-01 | 01 | 1 | VAL-01 | unit | `pytest tests/test_state.py::test_missing_source_match -x` | ❌ W0 | ⬜ pending |
| 01-01-01 | 01 | 1 | VAL-01 | unit | `pytest tests/test_state.py::test_circular_dependency -x` | ❌ W0 | ⬜ pending |
| 01-01-01 | 01 | 1 | VAL-01 | unit | `pytest tests/test_state.py::test_valid_bracket_passes -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | ELO-01 | unit | `pytest tests/test_elo.py::test_expected_score_equal -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | ELO-01 | unit | `pytest tests/test_elo.py::test_expected_score_table -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | ELO-01 | unit | `pytest tests/test_elo.py::test_update_ratings_standard -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | ELO-01 | unit | `pytest tests/test_elo.py::test_update_ratings_custom_k -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | ELO-01 | unit | `pytest tests/test_elo.py::test_update_ratings_large_gap -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 2 | DATA-02 | unit | `pytest tests/test_state.py::test_teams_roundtrip -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 2 | DATA-02 | unit | `pytest tests/test_state.py::test_bracket_roundtrip -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 2 | DATA-02 | unit | `pytest tests/test_state.py::test_atomic_write_safety -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 2 | DATA-02 | unit | `pytest tests/test_state.py::test_corrupt_json_error -x` | ❌ W0 | ⬜ pending |
| 01-02-03 | 02 | 2 | DATA-02, ELO-01 | integration | `pytest tests/test_integration.py::test_elo_update_persistence_roundtrip -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_elo.py` — covers ELO-01 (5 test cases)
- [ ] `tests/test_state.py` — covers DATA-02, VAL-01 (8 test cases)
- [ ] `tests/test_integration.py` — covers DATA-02 + ELO-01 end-to-end
- [ ] `tests/__init__.py` — package marker
- [ ] `tests/conftest.py` — shared fixtures (sample teams dict, sample bracket list)
- [ ] `pip install pytest pytest-cov` — install test framework

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Atomic write crash safety | DATA-02 | Simulating crash mid-write requires process control | Review state.py: verify `tempfile.mkstemp` + `os.fsync` + `os.replace` pattern is used |
| main.py startup output | VAL-01 | File I/O on real seed data (not tmp_path) | Run `python main.py` from `worldcup_predictor/` — verify "Loaded 32 teams", "Validated bracket: 23 matches", exits 0 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
