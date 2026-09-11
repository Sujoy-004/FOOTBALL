# PHASE 8A — MATCHDAY ACCUMULATION + DATA INTEGRITY

- **Season:** `2026/27` (path key `2026_27`)
- **Execution date:** 2026-09-11
- **Mode:** observational (no commits, no data mutation)
- **Accumulation since Phase 7:** 0 matchdays

---

## 1. Matchday Processing

| Metric | Value |
|---|---|
| Matchdays processed since Phase 7 freeze | **0** |
| First frozen kickoff | 2026-10-13T16:45:00Z (MD2) |
| System state | **idle — waiting on real match results** |

No real matchday has completed since the Phase 7 freeze (freeze timestamp
`2026-09-11T01:47:19.912141+00:00`). All MD1 matches with results were
pre-freeze events and are tracked only as context rows, not scored observations.

---

## 2. Accumulation Loop Execution Trace

### 2.1 attach (run 1)

```
$ env:PYTHONPATH=<repo> python -m competitions.ucl.src.shadow_eval attach --season "2026/27"
[attach] season=2026/27 attached=0 missing_scores=0 duplicate_skipped=11 out=.../results.jsonl
```

- `attached=0`: all 11 result rows were already present
- `missing_scores=0`: no results in `results.json` have null scores
- `duplicate_skipped=11`: each `match_id` already exists in `results.jsonl`
- **File impact:** `results.jsonl` unchanged (11 rows, same SHA-256)

### 2.2 attach (run 2 — idempotency proof)

```
[attach] season=2026/27 attached=0 missing_scores=0 duplicate_skipped=11 out=.../results.jsonl
```

Same output, same row count (11), no byte change. **Attach is idempotent.**

### 2.3 report

```
[report] season=2026/27 predictions=357 results=11 wrote=.../report.json md=.../SHADOW_EVALUATION.md
```

- `report.json` and `SHADOW_EVALUATION.md` written deterministically
- All segments: `n=0`, `status: insufficient` (no frozen prediction has a known result yet)

### 2.4 Immutability proof

| File | Before SHA-256 | After SHA-256 | Changed |
|---|---|---|---|
| `predictions.jsonl` | `53F9BD08...D422` | `53F9BD08...D422` | **NO** |
| `results.jsonl` | `2CF760A...BEFD` | `2CF760A...BEFD` | **NO** |

Frozen predictions are byte-immutable after freeze. Attach/report do not touch them.

---

## 3. Inventory

| Metric | Value | Status |
|---|---|---|
| Total prediction records | 357 | PASS |
| `production` records | 119 | PASS |
| `market_elo_equal` records | 119 | PASS |
| `market_elo_prior` records | 119 | PASS |
| Unique frozen `match_id`s | 119 | PASS |
| Scored per strategy | 0 / 0 / 0 | PASS |
| Pending (un-scored) | 119 | PASS |
| Odds-present | 0 | PASS |
| Odds-absent | 357 | PASS |
| Fixture coverage (exactly 3 per frozen `match_id`) | 119/119 | PASS |
| Per-match strategy set | `{production, market_elo_equal, market_elo_prior}` | PASS |

**Fixture pool breakdown (144 total fixtures.json entries):**

| Bucket | Count |
|---|---|
| Frozen (real MD2-MD8) | 119 |
| Unfrozen MD1 (pre-freeze, 11 with result) | 11 |
| Unfrozen MD1 (pre-freeze, 1 without result = `gen-5dec7b8731a863ee`) | 1 |
| Simulation-only (no `official_matchday`) | 8 |
| Total | 144 |

---

## 4. Integrity Audit

| Check | Result |
|---|---|
| Each attached `match_id` exists in `fixtures.json` with matching teams | PASS (11/11) |
| Exactly one attachment per `match_id` in `results.jsonl` | PASS |
| No `(match_id, outcome)` duplicates | PASS |
| All attached rows `source=results.json` (no `simulation_matchday` artifact) | PASS (11/11) |
| Attached results ∩ frozen predictions = ∅ | PASS (overlap: 0) |
| `prediction_timestamp` < every frozen kickoff | PASS (0 violations; ts=`2026-09-11T01:47:19.912141+00:00` < min kickoff `2026-10-13T16:45:00Z`) |
| Frozen fixtures all carry `official_matchday` (none are simulation-only) | PASS |
| Frozen fixtures `status` is never `finished` | PASS |
| Report honesty counters match inventory | PASS |
| All segments `n=0, status: insufficient` | PASS (expected: no scored frozen fixtures) |

---

## 5. Conclusion

The shadow system is correctly idle. Zero new matchdays have completed since
the Phase 7 freeze. The accumulation loop runs cleanly (attach is idempotent,
report is deterministic, frozen predictions are immutable). All invariants hold.
The system is waiting on real match results starting 2026-10-13 (MD2, first
frozen kickoff) to begin producing scored observations. No geometric sentence
changes mean no phase advancement is warranted until real match outcomes arrive.

**No correctness or operational issue blocks continued accumulation.**
