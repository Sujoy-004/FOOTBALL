# Phase 1: UCL League Table Engine — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-27
**Phase:** 1-UCL League Table Engine
**Areas discussed:** Elo initialization for UCL teams, Monte Carlo output granularity

---

## Elo Initialization for UCL Teams

| Option | Description | Selected |
|--------|-------------|----------|
| Use clubelo.com API | Pull club Elo ratings from clubelo.com API — provides pre-computed Elo for all major clubs | ✓ (after BSD check) |
| Flat baseline (1500 for all) | Assign flat starting value to all 36 teams | |
| Seed from UEFA coefficients | Transform UEFA coefficient scale to approximate Elo | |
| Check BSD API first | Priority order: BSD → ClubElo → UEFA coefficients | ✓ |

**User's choice:** Check BSD API first. BSD has no club strength metric, so use ClubElo.
**Notes:** User specified decision principle: prefer one authoritative data provider over maintaining multiple independent rating systems. ClubElo confirmed as the source. Fetch-once with caching, same snapshot for entire run, record date for reproducibility, configurable refresh policy.

## Monte Carlo Output Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Zone probabilities only | Per-team probabilities for top-8, playoff, eliminated | |
| Zone + champion + averages | Zone probs + champion probability + average points/goals | ✓ |
| Full distribution | Position histogram per team, points distribution, zone probs | |

**User's choice:** Zone + champion + averages
**Notes:** Averages should include all stats from the tiebreaker chain: average position, average points, average GD, average GS, average away GS, average wins, average away wins.

---

## the agent's Discretion

- Fixture schedule file format (JSON vs CSV) — agent to propose in PLAN.md
- Data directory structure under `competitions/ucl/data/`
- Whether to use a dedicated `compute_swiss_standings()` function or class-based orchestrator

## Deferred Ideas

None.
