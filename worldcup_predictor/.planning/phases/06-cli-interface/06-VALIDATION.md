---
phase: 6
slug: cli-interface
status: draft
nyquist_compliant: false
wave_0_complete: true
created: 2026-06-14
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | worldcup_predictor/pyproject.toml or pytest.ini (from Phase 1) |
| **Quick run command** | `python -m pytest tests/ -x --ignore=tests/test_main_loop.py` |
| **Full suite command** | `python -m pytest tests/ -q --ignore=tests/test_main_loop.py` |
| **Estimated runtime** | ~25s |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_cli.py tests/test_output.py -x -v`
- **After every plan wave:** Run `python -m pytest tests/ -x -v --ignore=tests/test_main_loop.py`
- **Before `/gsd-verify-work`:** Full suite must be green (excluding known-flaky test_main_loop.py)
- **Max feedback latency:** 30s

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 1 | 1 | CLI-01 | T-06-01, T-06-02 | type=int rejects non-integers; argparse rejects unknown flags | unit | `pytest tests/test_cli.py -x` | ❌ W0 | ⬜ pending |
| 06-01-02 | 1 | 1 | CLI-01 | T-06-03, T-06-SC | --help prints no secrets; argparse is stdlib | unit | `pytest tests/test_cli.py tests/test_output.py::TestNoColorFlag -x -v` | ❌ W0 | ⬜ pending |
| 06-02-01 | 2 | 2 | CLI-01 | T-06-04, T-06-05, T-06-06 | seed param scoped to simulation; --once skips save | integration | `python -c "import main; a=main._parse_args(['--once','--seed','42']); assert a.once and a.seed==42"` | ❌ W0 | ⬜ pending |
| 06-02-02 | 2 | 2 | CLI-01 | T-06-04 | seed propagation verified by monkeypatch test | unit + integration | `pytest tests/test_main_loop.py -x -v -k "seed or once"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_cli.py` — TestParseArgs with 8 tests (to be created in Plan 1 Task 2)
- [x] `tests/test_output.py` — TestNoColorFlag class with 3 tests (to be added in Plan 1 Task 2)
- [x] `tests/test_main_loop.py` — test_once_flag_runs_single_cycle, test_seed_propagates_through_run_iteration (to be added in Plan 2 Task 2)

*No new Wave 0 infrastructure needed — existing pytest + subprocess patterns from prior phases are reused.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full E2E with real API key | CLI-01 | Requires FOOTBALL_API_KEY set in env | Run `python main.py --once` and verify single cycle completes |
| All flags combined | CLI-01 | Requires FOOTBALL_API_KEY set in env | Run `python main.py --once --no-color --seed 42` and verify plain text + deterministic output |
| --seed determinism | CLI-01 | Requires visual comparison | Run `python main.py --once --seed 42` twice with same data, compare probability tables |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
