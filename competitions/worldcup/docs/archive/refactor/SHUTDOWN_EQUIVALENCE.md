# Shutdown Equivalence Proof: Is `prev_probs` ≡ Re-computation?

## 1. Execution Path from `_run_iteration()` Return to `print_shutdown_banner()`

```
_run_iteration() returns (last_sim_time, last_request_time, prev_probs)   ← line 1513/1517
        │
        ▼
  while _running:                     ← line 1509
        │
        ├── YES → _next_poll_sleep()  ← line 1510 (sleeps in 0.5s chunks, checks _running)
        │         │
        │         └── if not _running: break   ← line 1511-1512
        │
        └── NO  → [exit loop]
                    │
                    ▼
         Shutdown path (lines 1519-1527):
           1. load_signal_cache(ODDS_CACHE_FILE)    ← disk read
           2. load_signal_cache(CATBOOST_CACHE_FILE) ← disk read
           3. _run_calibrate_and_blend(odds, cb)     ← disk read + CPU
           4. run_full_simulation(50000, blend)      ← CPU
           5. print_shutdown_banner(final_probs)     ← print
```

### Between iteration return and shutdown execution

The only code between the last `_run_iteration()` return and the shutdown path is `_next_poll_sleep()` (line 1510) and the `if not _running: break` check (line 1511). `_signal_handler` (lines 285-291) sets the global `_running = False` and prints one line. No state mutation occurs.

## 2. State Immutability During the Interval

Every input to calibration, blending, and simulation is enumerated below along with proof it cannot change:

### 2.1 Teams

| Access Path | Mutated by `_run_iteration()`? | Mutated between iteration & shutdown? |
|---|---|---|
| `teams` dict (in-memory) | Yes — Elo updated for new matches (lines 815, 838) | No — `_signal_handler` doesn't touch teams. `_next_poll_sleep` doesn't touch teams. No code runs between loop exit and shutdown. |
| Disk (`teams.json`) | Yes — saved after every new match (lines 818, 842) | No — no code runs between loop exit and shutdown. |

**Verdict:** Immutable.

### 2.2 Groups, Bracket, Annex C, Aliases

These are loaded once at startup (lines 1392-1399) and never reassigned. `_run_iteration()` reads them but never mutates them. No code between loop exit and shutdown touches them.

**Verdict:** Immutable.

### 2.3 Played / Played Groups

| Path | Mutated by `_run_iteration()`? | Between iteration & shutdown? |
|---|---|---|
| `played` dict (in-memory) | Yes — new knockout matches appended (line 817) | No |
| `played_groups` dict (in-memory) | Yes — new group matches appended (line 840) | No |
| Disk (`played.json`, `played_groups.json`) | Yes — saved after mutation (lines 819, 841) | No |

**Verdict:** Immutable.

### 2.4 Prediction History

| Path | Mutated by `_run_iteration()`? | Between iteration & shutdown? |
|---|---|---|
| Disk (`prediction_history.json`) | Yes — entries appended for new matches (line 886), signals merged (line 958), versions attached (lines 1003-1011), governance may append (line 1068) | No — no code runs between loop exit and shutdown |

But critically: the shutdown path calls `_run_calibrate_and_blend()` which READS `prediction_history` from disk (line 146). Since no writes occur between iteration and shutdown, the disk copy is identical to what the iteration's `_run_calibrate_and_blend()` read (after all iteration mutations were completed).

**Verdict:** Disk state is identical. No new data arrives.

### 2.5 Odds Cache

| Path | Mutated by `_run_iteration()`? | Between iteration & shutdown? |
|---|---|---|
| `odds_cache` in-memory (line 894) | Loaded from disk, possibly refreshed from API (lines 895-901), saved back (line 900) | No |
| Disk (`odds_cache.json`) | Saved after refresh (line 900) | No |

Shutdown path loads from disk (line 1520) → reads same data as the iteration's final save.

**Verdict:** Identical to last iteration's in-memory cache.

### 2.6 CatBoost Cache

Same pattern as odds cache (lines 907-914).

**Verdict:** Identical to last iteration's in-memory cache.

### 2.7 Form Cache

| Path | Mutated by `_run_iteration()`? | Between iteration & shutdown? |
|---|---|---|
| `form_cache` in-memory (line 932) | Computed by `compute_form_signal()` (lines 931-935), saved to disk (line 936) | No |
| Disk (`form_cache.json`) | Saved (line 936) | No |

**Critical difference:** The shutdown path calls `_run_calibrate_and_blend(odds, cb)` — **without** `form_cache` and `lineup_cache`. The function defaults them to `None` → `{}` (lines 373-374 of `blender.py`). The iteration's call passes the real computed caches.

### 2.8 Lineup Cache

Identical pattern to form cache. Computed in iteration (lines 942-945), saved to disk. Shutdown path passes `None`.

### 2.9 Calibration Params (Disk)

| Path | Mutated by `_run_iteration()`? | Between iteration & shutdown? |
|---|---|---|
| Disk (`calibration_params.json`) | Written by `_run_calibrate_and_blend` (line 163) | No |

**Verdict:** Immutable.

### 2.10 Random Seed

`run_full_simulation` uses `random.Random(args.seed)` where `args.seed` is CLI argument.

If `args.seed is None`:
- Iteration: seed from `os.urandom` → unique per call
- Shutdown: seed from `os.urandom` → **different** from iteration

If `args.seed` is an integer:
- Both use the identical seed → identical simulation output for identical inputs

## 3. `prev_probs` Initialization Guarantee

### 3.1 Only reachable shutdown path

The shutdown path (lines 1519-1527) is inside the `try` block (lines 1383-1532). It is reached ONLY when:

1. Signal handlers are registered (lines 1492-1495) — only skipped if `args.once` (which calls `sys.exit(0)` at line 1489 before reaching the shutdown path).
2. The polling loop exits via `_running = False` (set by `_signal_handler`).
3. No exception was raised during the loop.

### 3.2 `prev_probs` is assigned at two points

```python
# Line 1499
prev_probs = None

# Line 1502-1506 — first iteration (BEFORE the while loop)
last_sim_time, last_request_time, prev_probs = _run_iteration(...)
#     ↑ prev_probs is now a dict (or could be None if iteration returns None probs)
```

```python
# Line 1513-1517 — each subsequent iteration inside the while loop
last_sim_time, last_request_time, prev_probs = _run_iteration(...)
```

### 3.3 Can the shutdown path be reached with `prev_probs is None`?

**Scenario A: Signal arrives during the first `_run_iteration()` (line 1502)**

Signal handlers are registered at lines 1492-1495. The first `_run_iteration()` runs at line 1502, AFTER signal registration. The signal handler only sets `_running = False` — it does NOT raise an exception or interrupt execution. Python's `signal.signal` on CPython does not interrupt the current opcode — the signal is delivered between bytecode instructions. Even if SIGINT arrives during `_run_iteration()`, the iteration completes normally, `prev_probs` is assigned its return value, and then `while _running:` sees `False` and exits.

**Verdict: `prev_probs` is guaranteed initialized.** The signal handler is non-interrupting (sets a flag, no `raise`), and both the first iteration (line 1502) and loop iterations (line 1513) assign the return value before the `while` condition or shutdown path is reached.

### 3.4 Can `_run_iteration()` return `None` for `probs`?

Looking at `_run_iteration` returns:

- Hourly re-sim path (line 797): `return now, last_request_time, probs` where `probs = run_full_simulation(...)`. `run_full_simulation` always returns a `dict` (line 347).
- Normal path (line 1147): `return time.time(), last_request_time, probs` where `probs = run_full_simulation(...)`. Same reasoning.

`run_full_simulation` always returns `dict[str, dict[str, float]]` — it has no early `None` return. There is no code path where `_run_iteration` returns a `None` third element.

**Verdict: `probs` is always a `dict`, never `None`. So `prev_probs` is always a `dict`.**

### 3.5 Edge case: startup interruption before signal registration

If SIGINT arrives before line 1492, the default handler raises `KeyboardInterrupt`, which is NOT caught by the `try/except ValueError/FileNotFoundError/JSONDecodeError` block (lines 1533-1541). The program would crash before reaching the shutdown path. This is pre-existing behavior and not affected by any Candidate A change.

## 4. Identified Edge Cases

### 4.1 Startup Interruption

Signal before line 1492 → `KeyboardInterrupt` → program exits. Shutdown path not reached. `prev_probs` not needed.

**Impact on Candidate A:** None. This path is unchanged.

### 4.2 Exceptions During Loop

Any unhandled exception inside the `try` block (lines 1383-1532) jumps to the exception handlers (lines 1533-1541), which call `sys.exit(1)`. The shutdown path is skipped entirely.

**Impact on Candidate A:** None. The shutdown path is never reached.

### 4.3 Partial Iteration (Exception in `_run_iteration`)

If `_run_iteration` raises an exception, it propagates up to the exception handlers. But note: `_run_iteration` contains many `try/except` blocks for individual operations (lines 807-809, 832-833, 901-902, 910-912, 937-940, 946-949, 1012-1013, 1076-1077, 1104-1109, 1143-1145, 886-888). Non-critical failures are caught and logged. A truly unhandled exception in `_run_iteration` would crash the loop.

But even if a crash occurs: `prev_probs` from the PREVIOUS successful iteration is still the last valid state. If the first `_run_iteration()` crashes, `prev_probs` would be whatever was assigned from the return — but it would have raised, so assignment wouldn't happen. However, if iteration crashes after computing probs but before returning, the program goes to the exception handler, bypassing shutdown.

**Impact on Candidate A:** None. The shutdown path is only reached after clean loop exit.

### 4.4 Failed Cache Writes

Cache save failures within `_run_iteration` are caught by individual `try/except` blocks (lines 901-902, 910-912, 937-940, 946-949). If a cache write fails:
- The in-memory cache object is still valid (it was computed before the failed save)
- The shutdown path would try to load from disk and get stale data (or empty dict if file doesn't exist)

**This is a pre-existing bug in the shutdown path:** if `_run_iteration` fails to save a cache but still uses the in-memory version for calibration, the shutdown path would load a STALE cache from disk and produce DIFFERENT results.

**Candidate A avoids this bug** by using `prev_probs` which was computed with the correct in-memory caches.

### 4.5 Interrupted Calibration

`_run_calibrate_and_blend` catches all exceptions and returns `None` (lines 171-172). If calibration fails:
- Iteration: `blend_params = None` → simulation runs with pure Elo
- Shutdown: `shutdown_blend = None` → simulation runs with pure Elo

Identical behavior. `prev_probs` was already computed with `blend_params = None`, matching the shutdown path's `shutdown_blend = None`.

## 5. Semantic Equivalence Conclusion

### 5.1 Sources of Divergence Between `prev_probs` and Shutdown Re-computation

| Factor | Does the value differ? | Effect |
|--------|----------------------|--------|
| Odds cache | No — same disk state | Identical |
| CatBoost cache | No — same disk state | Identical |
| Form cache | **YES** — iteration passes real cache, shutdown passes `{}` | `match_probs` differ for any match with form signal data |
| Lineup cache | **YES** — iteration passes real cache, shutdown passes `{}` | `match_probs` differ for any match with lineup signal data |
| Prediction history | No — same disk state | Identical |
| Calibration params | No — same disk state | Identical |
| Blend weights | No — determined by calibration params + prediction history only | Identical |
| Random seed (when `seed is None`) | **YES** — `time.time()` differs between calls | ~1/√50000 stochastic variation (~0.4% per team per round) |
| Random seed (when `seed is int`) | No — same fixed seed | Identical |
| In-memory `teams` vs disk `teams` | No — identical value (last write was in the iteration) | Identical |

### 5.2 Verdict

> **Replacing shutdown re-computation with `prev_probs` is a BEHAVIORAL change.**

The change is NOT semantically equivalent because:

1. **Form and lineup caches are dropped** in the shutdown path but included in the iteration. `prev_probs` includes their contribution; the shutdown recomputation does not. These differ.

2. **Random seed differs** when `args.seed is None` (the default). `prev_probs` reflects the iteration's seed; the shutdown recomputation uses a fresh seed.

Both differences mean the shutdown banner would display slightly different numbers. In practice, the old behavior is *less* correct (drops form/lineup signals), and neither seed is meaningfully "more correct" with `seed=None`, but the change is technically behavioral.

### 5.3 Recommendation

Candidate A is still the right fix, but it should be classified as **Behavioral** (not Mechanical). The behavior change is:

- **Improvement:** `prev_probs` includes form and lineup signals; the old shutdown path silently dropped them
- **Negligible:** The seed difference is ~0.4% per team per round at 50K iterations — indistinguishable to a user
- **Removes redundant work:** No disk I/O, no calibration recomputation, no 50K simulation at shutdown

If strict equivalence is required, Candidate A can be modified to preserve the old behavior: pass form/lineup caches loaded from disk in the shutdown path. But this would re-introduce the disk I/O that causes the flaky test, defeating the purpose. The better approach is to accept the behavioral change as a net improvement and proceed.

### 5.4 Alternative: Behavioral-but-Better Candidate A

```python
# Shutdown path — use last computed probabilities
# This includes form/lineup signals (old shutdown path dropped them).
# The random seed matches the last iteration (old path used a fresh seed).
final_probs = prev_probs
output.print_shutdown_banner(final_probs)
```

If the reviewer rejects even this negligible behavioral change, the fallback is **Candidate B** (test-only fix using stdout synchronization), which preserves the existing shutdown behavior at the cost of test complexity.
