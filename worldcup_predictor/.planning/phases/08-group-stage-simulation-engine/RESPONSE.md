# RESPONSE: Phase 8 Plan Review

**Reviewer:** Technical Architect
**Verdict:** Clarifications provided, no plan changes needed.

---

## Clarification 1 — Conduct Score Ordering

**The plan's D-05 and D-16 are inconsistent as written.** I confirm the bug exists in the CONTEXT.md document, not just the plan. Correction:

### The Fix

Store **conduct_score as a POSITIVE penalty count**, not as negative deductions:

| Card Event | Penalty Points (positive) |
|-----------|--------------------------|
| YC | +1 |
| 2YC→RC (indirect red) | +3 |
| Straight RC | +4 |
| YC→RC | +5 |

**Sort: ASCENDING** (lower penalty points = better discipline = wins tiebreak).

### Worked Example

| Team | Cards | Penalty Points | Rank |
|------|-------|---------------|------|
| **A** | 2 YC | 2 | **1st** (wins tiebreak) |
| **B** | 1 YC + 1 RC | 1 + 4 = 5 | 2nd |
| **C** | 2 YC→RC (one player) | 5 | 2nd (tied with B, falls to FIFA ranking) |

- Team A: 2 yellow cards → 2 points. Lowest score → least penalized → advances.
- Team B: 1 yellow + 1 straight red → 1 + 4 = 5 points.
- Team C: Two yellows to same player in one match → indirect red → 3 points.
  - In penalty-point semantics: this counts as one event worth 3 points, NOT 1+1+3.
  - But wait — the 2 yellows happen first, then the RC replaces them. The net deduction is −3.
  - As positive penalty points: +3. Team C scores 3 < Team B's 5, so Team C wins.
  - Correct: one match-level indirect red = 3 points (not 1+1).

**Clarification to add to D-16:**
> `conduct_score` is a **positive integer** (penalty points). Lower = better. Sort **ascending**.

### Why not store negative deductions?

FIFA regulations describe deductions as negative values (−1, −3, −4, −5). That is the **accounting representation**. But the **sorting** uses FIFA's phrase "highest team conduct score," which means "closest to zero." If stored as negatives, sorting must be DESCENDING. This creates a code-level inconsistency risk (easy to accidentally sort ASC like everything else). Storing as positive penalty points makes the ASCENDING sort the natural correct default.

### The Fix in the Plan

Update `08-02-PLAN.md` task 2 (`_tiebreak_group`):
- `CONDUCT_SORT_ASC = True` (constant, alongside `-- DEDUCTION_VALUES` mapping)
- `_compute_penalty_points()` returns positive int
- Sort key: `(pts DESC, gd DESC, gs DESC, penalty_points ASC, ranking ASC)`

No logic change — only representation convention.

---

## Clarification 2 — FIFA Ranking Proxy

### Why Elo is the chosen fallback

- **Already exists in every team's data** — `teams.json` has `elo` for all 48 teams.
- **Correlated with FIFA ranking** — top Elo teams ≈ top FIFA teams.
- **Stable during a match iteration** — Elo doesn't change during a single simulation pass. Sorting by it is deterministic.
- **Higher Elo = better team = wins tiebreak** — same semantics as "lower FIFA rank number = better team."

### Why not alphabetical / team-name ordering

- **Deterministic but meaningless** — alphabetical ordering has no connection to team strength. It would produce "Switzerland advances over Sweden" purely because of the letter 'i', which is wrong.
- **Team-name ordering** — teams with shorter names would have no predictive value.

### The design

During Phase 8's group simulation, when tiebreaker step 7 is reached:

```python
# Tiebreaker step 7: FIFA ranking (proxied by Elo during Phase 8)
# Higher Elo = better team = wins tiebreak.
# Sort key uses -elo to produce descending sort.
teams.sort(key=lambda t: (-t["pts"], -t["gd"], -t["gs"], t["penalty_points"], -t["elo"]))
```

This is explicitly a **Phase 8 proxy**, not the final design.

### Phase 10 replacement

**Yes, Phase 10 is expected to replace this** with one of:

1. **Real FIFA ranking data** — add a `fifa_rank` field to each team in `teams.json`, sort ascending by rank.
2. **Live FIFA ranking API** — fetch the most recent published FIFA/Coca-Cola Men's World Ranking (if an API is available).
3. **Fallback to drawing of lots** — if FIFA ranking is unavailable, the rules specify drawing lots. For simulation, this means random tiebreak.

The Phase 8 plan's `RESOLVE.md` (or its equivalent documentation) should flag this as `TODO: Replace Elo proxy with real FIFA ranking data in Phase 10`.

---

## Summary of Required Corrections

| Item | What to change | In which artifact |
|------|---------------|-------------------|
| D-16 in CONTEXT.md | `ascending for fair play (lower card count = better)` → clarify penalty points are positive, sort ASC | `08-CONTEXT.md` |
| Tiebreaker sort key in 08-02 | Use `penalty_points ASC` not `conduct_score DESC` | `08-02-PLAN.md` |
| Tiebreaker sort key in 08-03 | Use `penalty_points ASC` for third-place ranking step 4 | `08-03-PLAN.md` |
| FIFA ranking proxy | Document Elo proxy as Phase 8 fallback, Phase 10 replacement expected | `08-02-PLAN.md`, `08-03-PLAN.md` |

None of these affect plan structure or wave ordering. All are clarifications that can be applied before execution begins.
