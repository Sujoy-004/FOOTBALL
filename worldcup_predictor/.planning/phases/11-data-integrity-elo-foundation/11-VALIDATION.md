---
phase: 11
slug: data-integrity-elo-foundation
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-15
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | implicit (pytest.ini) |
| **Quick run command** | `pytest tests/test_elo_sync.py -x` |
| **Full suite command** | `pytest` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_elo_sync.py -x`
- **After every plan wave:** `pytest` (full suite to avoid regressions)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|--------|
| 11-01-01 | 01 | 1 | V2-01 | T-11-01,T-11-02 | mitigate | inline | `cd worldcup_predictor && python -c "from src.constants import ELORATINGS_TEAM_CODES; assert len(ELORATINGS_TEAM_CODES) == 48"` | ⬜ pending |
| 11-01-02 | 01 | 1 | V2-01 | — | N/A | inline | `cd worldcup_predictor && python -c "from src.state import load_eloratings_cache, save_eloratings_cache, load_elo_update_log, save_elo_update_log"` | ⬜ pending |
| 11-01-03 | 01 | 1 | V2-01 | T-11-01,T-11-02 | mitigate | inline | `cd worldcup_predictor && python -c "from src.elo_sync import ..."` with inline test suite | ⬜ pending |
| 11-02-01 | 02 | 2 | V2-01 | — | N/A | inline | `cd worldcup_predictor && python -c "from src.output import print_sync_results, print_staleness_warning, print_drift_flags"` | ⬜ pending |
| 11-02-02 | 02 | 2 | V2-02 | T-11-03,T-11-04 | mitigate | inline | `cd worldcup_predictor && python -c "import ast; ... assert '_run_elo_sync' in names"` | ⬜ pending |
| 11-03-01 | 03 | 2 | V2-01 | — | N/A | unit | `pytest tests/test_elo_sync.py::TestParse -x` | ⬜ pending |
| 11-03-02 | 03 | 2 | V2-01,V2-02 | T-11-05,T-11-06 | mitigate | unit | `pytest tests/test_elo_sync.py -x` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_elo_sync.py` — created in Plan 03 (Wave 2)
- [x] `tests/fixtures/eloratings_world.tsv` — created in Plan 03 Task 1
- [x] `tests/fixtures/eloratings_en_teams.tsv` — created in Plan 03 Task 1
- [x] Inline verification built into Plan 01 (3 tasks) and Plan 02 (2 tasks) — not Wave 0 dependent

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| N/A — All phase behaviors have automated verification. | | | |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved
