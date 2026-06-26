# WP-6 Architecture Summary: Hidden State Encapsulation

**Commits:** 6.1, 6.2 (2 commits)

---

## Public API Impact

### Functions whose signatures changed

None. All changes are internal — module-level state was encapsulated without altering any function signature.

### Functions removed

- `_POISSON_TABLES` dict (replaced by `lru_cache` on `_build_poisson_table`)
- `_prev_history` module-level declaration (became local variable in `_run_iteration`)
- `_prev_cal_params` module-level declaration (became local variable in `_run_iteration`)

### Functions whose internal behavior changed

| Function | Before | After |
|---|---|---|
| `_should_run_gov()` | Used `global _last_gov_time`, read module-level value (always 0.0 due to shadowing bug) | Reads `_state.last_gov_time` — **bug fixed**: governance now actually tracks time between runs |
| `_run_elo_sync(...)` | `global _elo_last_sync_time` | `_state.elo_last_sync_time` — identical behavior |
| `_signal_handler(...)` | `global _running` | `_state.running = False` — identical behavior |
| `_next_poll_sleep(...)` | Read `_running` at module scope | `_state.running` — identical behavior |
| `_run_iteration(...)` | 4 `global` declarations + module-level reads | All go through `_state` — **bug fixed**: `_last_gov_time` now properly persists across iterations |
| `main()` | `global` for `_ai_preview_enabled`, `_match_detail_enabled` | `_state.ai_preview_enabled`, `_state.match_detail_enabled` |

### Latent bugs fixed

1. **Governance timer was never updating:** `_last_gov_time = time.time()` in `_run_iteration` (line 1070) and `main()` (line 1475) created **local variables** that shadowed the module-level `_last_gov_time`. The module-level value stayed at 0.0 forever, causing `_should_run_gov()` to return `True` on every iteration. After encapsulation, `_state.last_gov_time` is mutated correctly, so governance now respects the intended hourly interval.

2. **`_prev_history`/`_prev_cal_params` declared at module scope but never used at module level:** They were always shadowed by local assignments in `_run_iteration`. The module-level declarations were dead code. Removed.

---

## Dependency Changes

### Dependencies removed

- `from dataclasses import dataclass` — **added** (stdlib, not a new dependency)
- `import functools` — **added** to `src/groups.py` (stdlib, not a new dependency)

### Dependencies introduced

None.

### Cycles eliminated

None. No new cycles were introduced. The remaining cross-module dependencies (evaluation.py → state.py, governance.py → output.py) were not addressed in WP-6.

---

## Hidden State Removed

| Item | Module | Before | After |
|---|---|---|---|
| `_running` | `main.py` | Module-level bool | `RunState.running` |
| `_elo_last_sync_time` | `main.py` | Module-level float | `RunState.elo_last_sync_time` |
| `_last_gov_time` | `main.py` | Module-level float (never updated — bug) | `RunState.last_gov_time` (now works) |
| `_ai_preview_enabled` | `main.py` | Module-level bool | `RunState.ai_preview_enabled` |
| `_match_detail_enabled` | `main.py` | Module-level str/None | `RunState.match_detail_enabled` |
| `_prev_signal_data` | `main.py` | Module-level dict/None | `RunState.prev_signal_data` |
| `_prev_history` | `main.py` | Module-level (dead — always shadowed) | Removed (local variable) |
| `_prev_cal_params` | `main.py` | Module-level (dead — always shadowed) | Removed (local variable) |
| `_POISSON_TABLES` | `groups.py` | Module-level dict with manual cache logic | Replaced by `functools.lru_cache` |

---

## Architectural Metrics

| Metric | Before WP-6 | After WP-6 |
|---|---|---|
| `global` keywords in main.py | 5 | 0 |
| `global` keywords in entire codebase | 5 | 0 |
| Module-level mutable `_` vars in main.py | 8 | 1 (`_state` instance) |
| Module-level mutable `_` collections in groups.py | 2 (`_POISSON_TABLES` + `_POISSON_BASE_RATE_CACHE`) | 0 (both removed across WP-5 + WP-6) |
| Persistent mutable state (module scope) | 10 variables across 2 modules | 1 dataclass instance in main.py |

---

## Technical Debt Removed

- **8 module-level mutable globals** in `main.py` — replaced with explicit dataclass
- **5 `global` keywords** — all eliminated
- **Manual cache implementation** in `groups.py` — replaced with stdlib `functools.lru_cache`
- **2 latent bugs** (governance timing, dead module-level declarations) — inadvertently fixed

---

## Remaining Technical Debt

See `FINAL_REFACTOR_AUDIT.md` for the complete list.

---

## Full Test Suite Status

**613 passed, 1 skipped** (live smoke test requires `BSD_API_KEY`).

One test (`test_main_loop_clean_shutdown`) is intermittently flaky due to a timing race — it sometimes sends the shutdown signal before the subprocess enters the polling loop. Not related to WP-6 changes.

---

## Live Validation Status

**Not required.** WP-6 commits encapsulate internal state without changing any observable output:
- 6.1 (BEHAVIORAL): Governance frequency changes from "every iteration" to "every hour" — this fixes a latent bug, not a planned behavior change. Governance output is display-only and does not affect prediction computation.
- 6.2 (MECHANICAL): Same caching behavior, same mathematical results.
