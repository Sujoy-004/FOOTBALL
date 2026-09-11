# PHASE 7A — LIVE SHADOW / DATA INTEGRITY VERIFICATION

- **Season audited:** `2026/27` (path key `2026_27`)
- **Audit date:** 2026-09-11
- **Scope:** inventory audit, invariant audit, CLI idempotency verification, correctness-bug sweep
- **Disposition:** OBSERVATIONAL — no code changes, no commits, no data mutation beyond deterministic regeneration of `report.json` / `SHADOW_EVALUATION.md` by the existing `report` CLI.
- **Result:** **ALL INVARIANTS PASS. NO CORRECTNESS BUGS FOUND.** One source-data provenance observation (Section 9).

---

## 1. Frozen Prediction Inventory

| Metric | Expected | Actual | Status |
|---|---:|---:|---|
| Total prediction records | 357 | 357 | PASS |
| `production` records | 119 | 119 | PASS |
| `market_elo_equal` records | 119 | 119 | PASS |
| `market_elo_prior` records | 119 | 119 | PASS |
| Distinct predicted `match_id`s | 119 | 119 | PASS |

## 2. Timestamp Ordering Invariant (freeze < kickoff)

| Metric | Value |
|---|---|
| Freeze timestamp | `2026-09-11T01:47:19.912141+00:00` |
| Earliest frozen kickoff | `2026-10-13T16:45:00+00:00` |
| Latest frozen kickoff | `2027-01-27T20:00:00+00:00` |
| Records where freeze ≥ kickoff | **0** |

**PASS** — every frozen prediction was made strictly before its fixture kickoff.

## 3. Odds Availability

- `odds_available: false` → **357 / 357** (100%).
- **PASS** — 2026/27 season carries no odds; `odds_unavailable` segment is the correct label for the entire cohort.

## 4. Phase-6 Recomputed Signature

| Metric | Expected | Actual | Status |
|---|---:|---:|---|
| `production` with `recomputed` block | 74 | 74 | PASS |
| `production` without `recomputed` | 45 | 45 | PASS |
| Candidate records (`market_elo_*`) | 238 | 238 | PASS |

`refreeze_manifest.json` corroborates:

| Manifest field | Value |
|---|---|
| changed | 74 |
| unchanged | 45 |
| skipped_fixture_changed | 0 |
| skipped_result_now_known | 0 |
| not_found | 0 |
| `candidate_records_hash_before == after` | True |

## 5. Attached Results Inventory (`results.jsonl`)

| Metric | Value |
|---|---|
| Rows | 11 |
| Distinct `match_id`s | 11 |
| Duplicates | 0 |
| Result rows missing scores | 0 |
| Outcome vs score mismatch | 0 |
| `results.json` ↔ `results.jsonl` sync (16) | bi-directionally identical |

**PASS** — no duplicate attaches, no fabricated 0-0 rows, no outcome inconsistencies.

## 6. Cross-Reference: Predicted vs Played

| Metric | Value |
|---|---|
| Attached result `match_id`s present in `fixtures.json` | 11 / 11 |
| Overlap — attached results ∩ frozen predictions | **0** |
| Overlap — `results.json` fixtures ∩ frozen predictions | **0** |

**PASS** — the 11 finished, scored fixtures all kicked off **before** the 2026-09-11 freeze and were therefore never predicted; no frozen prediction is contaminated by a known result. This is the correct state for `n_pending_fixtures = 119`.

## 7. Source Data Cross-Checks

- All 11 attached results match their identities (teams, kickoff) in `fixtures.json`.
- `results.json` and `results.jsonl` contain the identical 11 `match_id`s.

## 8. CLI Idempotency Verification

Commands executed with `PYTHONPATH=<repo root>` via `python -m competitions.ucl.src.shadow_eval <cmd> --season "2026/27"`.

### `attach`

| Run | Output | File impact |
|---|---|---|
| 1 (real) | `attached=0 missing_scores=0 duplicate_skipped=11` | `results.jsonl` stays at 11 rows |
| 2 (real) | `attached=0 missing_scores=0 duplicate_skipped=11` | unchanged |
| 3 (dry-run) | `attached=0 missing_scores=0 duplicate_skipped=11` | unchanged |

**PASS** — attach is idempotent per `match_id`; re-runs add no rows.

### `report`

| Run | Output | File impact |
|---|---|---|
| 1 | `predictions=357 results=11` writes `report.json` + `SHADOW_EVALUATION.md` | written |
| 2 | same | `report.json` **byte-identical** (SHA-256 match) |

**PASS** — report generation is deterministic (no embedded timestamps).

### `report.json` content (post-run)

- Segments: `all` / `odds_available` / `odds_unavailable` → all `n=0`, `status: insufficient`
- `honesty`: `n_prediction_records=357`, `n_unique_fixtures_frozen=119`, `n_scored_fixtures=0`, `n_pending_fixtures=119`, `n_attached_results=11`
- Comparisons: all three pairs → `insufficient_evidence (n=0)`
- Bootstrap config: `n_boot=2000`, `seed=20260601`

All `n=0` is **expected and correct**: the 11 attached results are pre-freeze fixtures, so no frozen prediction can be scored yet. The shadow system is correctly waiting for the first frozen fixture (min kickoff `2026-10-13`) to finish.

## 9. Observations (non-blocking)

1. **12-finished-vs-11-results gap — resolved.**
   `fixtures.json` contains 12 `status: finished` fixtures; 11 have results. The 12th is `gen-5dec7b8731a863ee` (Liverpool vs Atlético Madrid, kickoff `2026-09-09T19:00:00Z`).
   - Its `fixtures.json` entry is marked `status: finished` but carries **no scores** and has **no entry in `results.json`**.
   - Kickoff precedes the freeze, so it was never predicted → **no shadow-data integrity impact**.
   - **Root cause:** a pre-existing source-data provenance gap in the season store (simulation marked the fixture finished without recording a result). Flagged for the data-pipeline owner; outside the shadow subsystem.
2. `market_elo_equal` records report `weights_file: None` while carrying a `weights_hash` identical to `market_elo_prior`. Consistent with the strategy using market-ELO defaults without a named weights file — informational only, not a defect.

## 10. Test Verification

- `python -m pytest competitions/ucl/tests/test_shadow_eval.py -q` → **51 passed**.
- No regressions in the shadow/evaluation subsystem after the audit runs.

## 11. Conclusion

The shadow dataset for **2026/27** is internally consistent and correctly isolated from actual results. All inventory counts, ordering invariants, odds flags, Phase-6 recomputed signature, attach idempotency, and report determinism checks pass. The system is healthy and correctly idle until the first frozen fixture kicks off on **2026-10-13**. No further action required for Phase 7A.