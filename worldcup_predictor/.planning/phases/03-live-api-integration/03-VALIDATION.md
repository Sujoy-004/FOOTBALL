---
phase: 3
slug: live-api-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7+ |
| **Config file** | none — pytest defaults |
| **Quick run command** | `pytest -x tests/test_fetcher.py -v` |
| **Full suite command** | `pytest -x -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest -x tests/test_fetcher.py -v`
- **After every plan wave:** Run `pytest -x -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | DATA-01 | T-03-01 / — | N/A | unit | `pytest tests/test_fetcher.py::test_fetch_success -x -v` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | DATA-01 | T-03-02 / — | N/A | unit | `pytest tests/test_fetcher.py::test_fetch_empty_response -x -v` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | DATA-03 | T-03-03 / — | API key never logged | unit | `pytest tests/test_fetcher.py::test_fetch_all_retries_exhausted -x -v` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | DATA-03 | T-03-04 / — | N/A | unit | `pytest tests/test_fetcher.py::test_fetch_429_retry_after -x -v` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | DATA-01 | — / — | N/A | unit | `pytest tests/test_fetcher.py::test_fetch_timeout_retry -x -v` | ❌ W0 | ⬜ pending |
| 03-01-06 | 01 | 1 | DATA-03 | — / — | N/A | unit | `pytest tests/test_fetcher.py::test_fetch_malformed_json -x -v` | ❌ W0 | ⬜ pending |
| 03-01-07 | 01 | 1 | DATA-01 | — / — | N/A | unit | `pytest tests/test_fetcher.py::test_process_matches_normalizes -x -v` | ❌ W0 | ⬜ pending |
| 03-01-08 | 01 | 1 | DATA-01 | — / — | N/A | unit | `pytest tests/test_fetcher.py::test_process_matches_unmatchable -x -v` | ❌ W0 | ⬜ pending |
| 03-01-09 | 01 | 1 | DATA-01 | — / — | N/A | unit | `pytest tests/test_fetcher.py::test_process_matches_filters_played -x -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_fetcher.py` — 9 test cases for fetch + process
- [ ] `tests/conftest.py` — optional: shared MockResponse fixture if reused

*Existing infrastructure covers most phase requirements. Only test file stubs needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live API call with real API key | DATA-01 | Requires real API key + internet; not suitable for automated CI | Set FOOTBALL_API_KEY, run `python -c "from src.fetcher import fetch_raw_matches; print(fetch_raw_matches('key'))"` |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
