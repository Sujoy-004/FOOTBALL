# Phase 12: Draw Handling & Elo Math — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 12-Draw-Handling-Elo-Math
**Areas discussed:** Draw entry format, Penalty shootout Elo rule, K-multiplier for draws, Historical draw backfill, K-multiplier integration, K-multiplier formula

---

## Draw Entry Format

| Option | Description | Selected |
|--------|-------------|----------|
| winner: null only | Minimal change, but relies on missing key inference | |
| winner: null + is_draw: true | Explicit dual-flag, no ambiguity | ✓ |

**User's choice:** `winner: null + is_draw: true`
**Notes:** "Avoid ambiguity. {winner: null, is_draw: true} is clearer than relying on missing keys."

---

## Penalty Shootout Elo Rule

| Option | Description | Selected |
|--------|-------------|----------|
| PK win = full win (1.0/0.0) | Simpler, but inconsistent with eloratings.net | |
| PK win = 0.75/0.25 split | Matches eloratings.net PK rule | ✓ |

**User's choice:** 0.75/0.25 split per eloratings.net
**Notes:** "If Phase 11 established eloratings.net = canonical Elo source, then Phase 12 should mirror its treatment of PK wins as closely as practical."

---

## K-Multiplier for Draws

| Option | Description | Selected |
|--------|-------------|----------|
| Apply K/2 to draws | Continuous formula gives K/2 for GD=0 | |
| Use base K (G=1) | Draws same as 1-goal wins in step-function | ✓ |

**User's choice:** G=1 for draws (same as 1-goal win)
**Notes:** The user wanted evidence before locking. Web search confirmed eloratings.net spec: "If the game is a draw or is won by one goal: G = 1". The step-function (not the continuous approximation from MODERNIZATION-PROPOSAL.md) is the actual eloratings.net formula.

---

## K-Multiplier Formula

| Option | Description | Selected |
|--------|-------------|----------|
| Step-function per eloratings.net | G=1 (draw/1-goal), G=1.5 (2-goal), G=(11+N)/8 (3+) | ✓ |
| Continuous approximation | K × (GD+1)^0.8 ÷ (GD+1 + 1) | |

**User's choice:** Step-function per eloratings.net
**Notes:** Confirmed against Wikipedia and eloratings.net/about as the published formula.

---

## Historical Draw Backfill

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, backfill | Replay all historical draws through fixed Elo | ✓ |
| No, only future | Old draws remain wrong, rating history inconsistent | |

**User's choice:** Yes, backfill
**Notes:** "Otherwise old draws = wrong, future draws = correct, and the rating history becomes inconsistent. Backfill once while the number of stored matches is still manageable."

---

## K-Multiplier Integration

| Option | Description | Selected |
|--------|-------------|----------|
| New helper function | `compute_k_factor(goal_diff)` → call before `update_ratings` | ✓ |
| Modified update_ratings | Add goal_diff parameter to existing function | |

**User's choice:** New helper function
**Notes:** "Keep separation of concerns. compute_k_factor(...) → update_ratings(...) is cleaner than continuously expanding the update_ratings signature."

---

## the agent's Discretion

- Exact PK detection heuristic (BSD `home_score == away_score` + winner check)
- Location of `compute_k_factor()` in the module (elo.py preferred)
- Test fixture design for draw scenarios
- Atomic vs per-match backfill approach

## Deferred Ideas

None — discussion stayed within phase scope.
