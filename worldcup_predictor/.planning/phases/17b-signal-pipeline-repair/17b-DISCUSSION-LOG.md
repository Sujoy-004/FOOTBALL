# Phase 17b: Signal Pipeline Repair — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-19
**Phase:** 17b-Signal-Pipeline-Repair
**Areas discussed:** Defect B approach, V6 criterion

---

## Defect B Approach (market odds merge)

| Option | Description | Selected |
|--------|-------------|----------|
| B1 | Rebuild prediction_history to align with ledger | |
| B2 | Create missing history entries dynamically during merge | |
| Combined fix | Add ledger_upsert for odds + ensure per-iteration prediction_history creation | ✓ |

**User's choice:** Combined fix — both Gap 1 (missing ledger_upsert) and Gap 2 (static prediction_history) must be fixed. Neither B1 nor B2 alone solves the root cause.

**Root cause evidence:**
1. `fetch_and_cache_odds()` returns cache dict but never calls `ledger_upsert()` — no code path writes `"market_odds"` into the ledger for the match_ids that overlap with prediction_history.
2. `_run_iteration()` never creates prediction_history entries for newly-finished matches — `_record_eval_baseline()` only runs at startup.
3. Form and lineup_strength DO merge correctly (they call `ledger_upsert`), proving the merge architecture is sound.
4. The 8 existing prediction_history entries are for matches finished before prediction collection began — they will never have market_odds.

---

## V6 Verification Criterion

| Option | Description | Selected |
|--------|-------------|----------|
| Original V6 | "Simulation output differs from Elo-only baseline" | |
| Strengthened V6 | Seed-controlled champion probability comparison | |
| New V6 | Blended probabilities consumed by simulation — 5-part evidence chain | ✓ |

**User's choice:** Replacement V6 with 5-part evidence:
1. calibrate_and_blend() produces non-empty match_probs
2. For at least one real match: blended_probability != expected_score()
3. _get_blended_prob() returns the blended_probability
4. Simulation consumes that blended_probability
5. Runtime trace shows Elo fallback NOT taken

---

## the agent's Discretion

- Exact mechanism for D-06: per-iteration prediction_history creation
- Whether CatBoost ledger_upsert is grouped with Defect A or noted in Defect B
- Test fixture design for all four fix areas

## Deferred Ideas

None — discussion stayed within scope. Concepts: ✅, classification: ✅, scope: ✅, B approach: ✅, V6: ✅.
