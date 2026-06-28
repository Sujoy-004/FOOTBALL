---
phase: 1
slug: ucl-league-table-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-27
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | competitions/ucl/pytest.ini or setup.cfg |
| **Quick run command** | `python -m pytest competitions/ucl/tests/ -x --tb=short` |
| **Full suite command** | `python -m pytest competitions/ucl/tests/ -v --tb=long` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest competitions/ucl/tests/ -x --tb=short`
- **After every plan wave:** Run `python -m pytest competitions/ucl/tests/ -v --tb=long`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | UCLT-00, UCLT-04 | — | N/A | unit | `pytest competitions/ucl/tests/ -k test_fixture_validation` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | UCLT-04 | — | N/A | unit | `pytest competitions/ucl/tests/ -k test_fixture_loading` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 1 | UCLT-01, UCLT-06 | — | N/A | unit | `pytest competitions/ucl/tests/ -k test_swiss_standings` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 1 | UCLT-02 | — | N/A | unit | `pytest competitions/ucl/tests/ -k test_tiebreaker` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 1 | UCLT-03 | — | N/A | unit | `pytest competitions/ucl/tests/ -k test_qualification_zones` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 2 | UCLT-05 | — | N/A | integration | `pytest competitions/ucl/tests/ -k test_monte_carlo` | ❌ W0 | ⬜ pending |
| 1-04-01 | 04 | 2 | UCLT-05 | — | N/A | integration | `pytest competitions/ucl/tests/ -k test_advancement_probs` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `competitions/ucl/tests/__init__.py` — empty init
- [ ] `competitions/ucl/tests/conftest.py` — shared fixtures (sample teams, sample fixtures, mock ClubElo data)
- [ ] `competitions/ucl/tests/test_fixtures.py` — fixture validation stubs
- [ ] `competitions/ucl/tests/test_standings.py` — standings computation stubs
- [ ] `competitions/ucl/tests/test_tiebreakers.py` — tiebreaker chain stubs
- [ ] `competitions/ucl/tests/test_monte_carlo.py` — Monte Carlo stubs

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ClubElo API connectivity | UCLT-06 | Requires live HTTP | Run `python -m pytest competitions/ucl/tests/ -k test_clubelo_api --live` |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
