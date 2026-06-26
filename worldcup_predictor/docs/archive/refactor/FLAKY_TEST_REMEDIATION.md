# Flaky Test Remediation: `test_main_loop_clean_shutdown`

## Root Cause

Timing + resource contention race in the test-subprocess handshake.

**Sequence:**
1. Test spawns a subprocess running `main.main()` with `POLL_INTERVAL=1`.
2. Test sleeps `time.sleep(2)` — assumes this is enough for the first `_run_iteration()` to complete.
3. Test sends `CTRL_BREAK_EVENT` (or `SIGINT`).
4. Subprocess receives signal, sets `_running = False`, exits the polling loop, enters the **shutdown path**.
5. Shutdown path (`main.py:1519-1527`) re-loads disk caches, re-runs calibration, and re-runs `run_full_simulation(..., iterations=50000)`.
6. Under full-suite I/O contention, the shutdown path exceeds `proc.communicate(timeout=6)`, the test kills the subprocess, and no shutdown banner appears in the captured stdout.

**Why it's flaky:** The 2-second sleep + 6-second communicate window is usually enough, but under heavy concurrent load (full suite, disk I/O from 600+ tests), the subprocess doesn't get enough CPU to finish the shutdown path in time.

**Failure signature in full suite:** Always `test_main_loop.py` (early in the alphabet — hit before other long-running tests finish). Passes every time in isolation.

## Candidate Fixes

### Candidate A — Use `prev_probs` in Shutdown Path (Recommended)

**Change:** Replace the shutdown path's re-load + re-calibrate + re-simulate with the last computed `prev_probs`.

Current code (`main.py:1519-1527`):
```python
# Shutdown path
shutdown_odds = state.load_signal_cache(ODDS_CACHE_FILE, league_data_dir)
shutdown_cb = state.load_signal_cache(CATBOOST_CACHE_FILE, league_data_dir)
shutdown_blend = _run_calibrate_and_blend(
    teams, groups, bracket, shutdown_odds, shutdown_cb,
    data_dir=league_data_dir,
)
final_probs = run_full_simulation(teams, groups, bracket, annex_c, played,
    played_groups=played_groups, iterations=50000, seed=args.seed,
    blend_params=shutdown_blend)
output.print_shutdown_banner(final_probs)
```

Proposed:
```python
# Shutdown path — use last computed probabilities (state hasn't changed)
final_probs = prev_probs
output.print_shutdown_banner(final_probs)
```

**Rationale:** The last `_run_iteration()` already fetched fresh odds/catboost/form/lineup, saved caches to disk, ran calibration-and-blend, and ran the 50K simulation. The shutdown path re-does all of this on the same state — no new data arrives during signal handling. `prev_probs` is already populated by the time the shutdown path is reached (the first `_run_iteration()` runs before signal handlers are registered, and the signal only interrupts `_next_poll_sleep` or subsequent iterations, never the first iteration itself).

**Pros:**
- Makes shutdown instantaneous — no disk I/O, no calibration, no 50K sim
- Eliminates the flaky test deterministically (the race window vanishes)
- No observable behavior change (probabilities are from the last completed iteration, which is the freshest possible)
- Removes redundant work from production code

**Cons:**
- If `prev_probs` is `None` (edge case: signal arrives before first iteration completes), need a fallback. But signals are registered after line 1495 and the first `_run_iteration()` runs at line 1502 — the signal handler only sets a boolean flag, the iteration runs to completion.
- Very small behavioral change: shutdown banner reflects *last completed iteration* rather than a *freshly computed result*. In practice, with zero delta in state, these are identical.

**Risk:** Very low. No new data arrives between the last iteration and shutdown. The caches saved by `_run_iteration` are the same caches the shutdown path would load.

### Candidate B — Test Synchronizes on Deterministic Signal

**Change:** Replace `time.sleep(2)` with a loop that reads `proc.stdout` line-by-line until the heartbeat line `"Polling... no new matches."` appears, then sends the shutdown signal.

```python
proc = subprocess.Popen(..., stdout=subprocess.PIPE, bufsize=1, ...)
# Wait for first iteration to complete before sending signal
import queue, threading
q = queue.Queue()
def _reader(stream, q):
    for line in iter(stream.readline, ''):
        q.put(line)
    q.put(None)
t = threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True)
t.start()
start = time.time()
while time.time() - start < 10:
    try:
        line = q.get(timeout=0.5)
        if "Polling" in line:
            break
    except queue.Empty:
        continue
proc.send_signal(sig)
```

**Pros:**
- No production code changes
- Deterministic — waits for an actual output event rather than wall-clock time

**Cons:**
- Test becomes more complex (threading, queues, timeouts)
- Fragile if the heartbeat format or logging changes
- Still relies on a watchdog loop with a fallback timeout (fails if stdout pipe buffers or blocks)
- Threading introduces its own race/deadlock hazard

**Risk:** Low for test correctness, but adds maintenance overhead.

### Candidate C — Increase `communicate(timeout=6)` to `timeout=20`

**Change:** Replace `proc.communicate(timeout=6)` with `proc.communicate(timeout=20)`.

**Pros:**
- Single-character diff (6 → 20)
- Works around any I/O delay

**Cons:**
- Band-aid, not a fix — just shifts the breakpoint. Under extreme load, even 20s might fail.
- Makes the test slower when it does fail (wastes 20s before killing and reading partial output)
- Does not address the root cause

**Risk:** Low, but unsatisfactory.

## Recommended Fix

**Candidate A** — Use `prev_probs` in the shutdown path.

Rationale:
- Fixes the root cause by removing the slow code path entirely
- Improves production code (no redundant I/O + calibration + 50K sim at shutdown)
- Makes the test deterministic without making the test more complex
- The shutdown path is genuinely redundant — the last iteration already produced the freshest possible probabilities

## Risk Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Observable behavior change | None | Same state → same probabilities |
| Edge case: `prev_probs is None` | Not reachable | First `_run_iteration` runs before signals can interrupt the main loop |
| Edge case: signal during startup | Not reachable | Signal handlers registered at line 1495, first iteration at line 1502 |
| Regression scope | Local | Only touches `main()` shutdown block |
| Test determinism | Fixed | Shutdown path is now instantaneous (±10ms) vs. 50K-sim + I/O (±seconds) |

## Estimated Implementation Size

- **LOC changed:** 5 (replace 8 lines with 2)
- **Files touched:** 1 (`main.py`)
- **Classification:** **Mechanical** — no observable behavior change. The same `prev_probs` dict that was already computed is displayed. Only the redundant re-computation is removed.

## Alternative Assessment

If Candidate A is rejected:

| Candidate | Classification | LOC | Risk |
|-----------|---------------|-----|------|
| B (test sync) | Test-only | ~20 | Low — test maintenance tax |
| C (timeout bump) | Test-only | 1 | Lowest effort — band-aid |
