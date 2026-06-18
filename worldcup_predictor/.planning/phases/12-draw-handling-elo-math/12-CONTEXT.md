# Phase 12: Draw Handling & Elo Math — Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the draw pipeline — stop skipping draws in both live and historical processing, apply correct Elo updates for draws, implement the goal-difference K-multiplier per eloratings.net step-function spec, and backfill Elo for all historical draws to restore rating consistency.

Scope: V2-03 (draw ingestion + Elo update) and V2-04 (goal-diff K-multiplier).

This phase does NOT build evaluation infrastructure (Brier, log loss, calibration — that's Phase 12b). It records a baseline Brier/log-loss by replaying historical draws, but leaves the measurement framework to 12b.

</domain>

<decisions>
## Implementation Decisions

### Draw Entry Format
- **D-01:** Draw match entries stored with both `winner: null` and `is_draw: true` in played.json and played_groups.json. Explicit dual-flag to avoid ambiguity vs. missing-key interpretation.
- **D-02:** Existing non-draw entries unchanged (keep current `winner: "TeamA"` format, no `is_draw` flag needed).

### Draw Ingest Flow
- **D-03:** Three code sites to fix:
  - `fetcher.py:126-127` (knockout, live `process_matches()`) — include draw entry instead of `continue`
  - `fetcher.py:314-315` (group, live `process_group_matches()`) — include draw entry instead of `continue`
  - `main.py:251-253` (knockout, historic `_run_historical_catch_up()`) — include draw entry instead of `continue`
- **D-04:** All three sites produce the same entry shape: `{match_id, team_a, team_b, winner: null, is_draw: true, home_score, away_score, completed_at}`.
- **D-05:** `apply_elo_update` (elo.py:89) already handles `winner=None` for draws. No change needed there.

### Penalty Shootout Elo Rule
- **D-06:** PK-decided matches detected via `home_score == away_score AND winner is not None` (BSD API reports winner for PK wins but scores reflect 120' result).
- **D-07:** Use eloratings.net PK rule: result = 0.75 for the team that wins on PKs, 0.25 for the loser (not 1.0/0.0 as in regulation wins). This is implemented as a new parameter or separate code path in `update_ratings()` — the function already supports `winner=None` for draws; PK wins add a `pk_winner` concept or a `result_a` override.
- **D-08:** PK outcome does NOT affect the goal-difference K-multiplier — G is based on 120' score difference (GD=0 for PK-decided matches → G=1).

### Goal-Difference K-Multiplier
- **D-09:** Implement as standalone `compute_k_factor(goal_diff: int, base_K: int = 60) -> float` helper. Do not bloat `update_ratings()` signature.
- **D-10:** Formula = eloratings.net step-function (per Wikipedia/eloratings.net about page):
  - G = 1 for draws and one-goal wins (GD = 0 or 1)
  - G = 1.5 for two-goal wins (GD = 2)
  - G = (11 + N) / 8 for three+ goal wins (where N = goal difference, N ≥ 3)
  - Cap: None needed — the formula is self-limiting for typical margins
- **D-11:** Goal difference = abs(home_score - away_score). Always positive.
- **D-12:** Apply K-multiplier to ALL matches (wins, losses, draws). For draws GD=0 → G=1 always (no K reduction).
- **D-13:** Integration: `update_ratings()` caller (e.g., `apply_elo_update`) computes `k_factor = compute_k_factor(goal_diff, K)` and passes the adjusted K value into `update_ratings()`.

### Historical Draw Backfill
- **D-14:** Yes, backfill all historical draws already stored in played.json and played_groups.json. Old draws should not remain wrong while future draws are correct — that creates a permanent inconsistency in the rating history.
- **D-15:** Backfill runs once as part of this phase's implementation. Detect historical draw matches (entries missing or skipped) and replay through the fixed Elo pipeline.
- **D-16:** Backfill scope: all matches where `home_score == away_score` in played.json and played_groups.json that either have no entry or have a skipped draw.
- **D-17:** Log all backfilled Elo changes to `elo_update_log.json` with reason "historical draw backfill" for audit trail.

### Baseline Metrics
- **D-18:** After draw fix and backfill, replay all historical matches through the fixed Elo and record Brier score / log loss as a baseline. Store as a one-shot measurement in `data/eval_baseline.json` for Phase 12b to consume. This is a light recording, not the full evaluation framework — Phase 12b builds the proper infrastructure.

### the agent's Discretion
- Exact implementation of PK detection (comparing `home_score == away_score` is the heuristic, but BSD API field names should be verified)
- Whether `compute_k_factor` lives in `elo.py` or `utils.py` (prefer `elo.py` for cohesion)
- Test fixture design for draw match scenarios
- Whether backfill produces one atomic Elo pass or per-match sequential updates (prefer atomic pass to avoid partial-update issues)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Proposal
- `worldcup_predictor/MODERNIZATION-PROPOSAL.md` — Full modernization architecture, signal inventory, phase definitions. Section 4 (Elo Replacement Strategy) and Section 11 (Phase definitions) are primary references.
- `https://www.eloratings.net/about` — Source of truth for K-multiplier step-function specification.
- `https://en.wikipedia.org/wiki/World_Football_Elo_Ratings` — Wikipedia article confirming step-function formula and PK rule.
- `https://www.eloratings.net/World.tsv` — Canonical Elo values source (World.tsv format).

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 12 definition: V2-03 and V2-04 requirements, success criteria, dependencies on Phase 11.
- `.planning/REQUIREMENTS.md` — V2-03 (draw ingestion), V2-04 (K-multiplier), and V2-18/V2-19 (evaluation — Phase 12b).

### Prior Phase Context
- `.planning/phases/11-data-integrity-elo-foundation/11-CONTEXT.md` — Phase 11 decisions (sync interval, graduated drift thresholds, caching, startup behavior). Phase 11 D-09 establishes eloratings.net as sole Elo source of truth.
- `.planning/phases/10-integration-tests-bsd-verification/10-CONTEXT.md` — D-06 (draw skip in group matches), D-04 (match entry structure).

### Codebase
- `worldcup_predictor/src/fetcher.py:126-127` — Draw skip site #1 (knockout, live)
- `worldcup_predictor/src/fetcher.py:314-315` — Draw skip site #2 (group, live)
- `worldcup_predictor/main.py:251-253` — Draw skip site #3 (knockout, historic)
- `worldcup_predictor/src/elo.py:37-86` — `update_ratings()` already handles `winner=None` for draws
- `worldcup_predictor/src/elo.py:89-112` — `apply_elo_update()` — caller that passes winner to update_ratings
- `worldcup_predictor/src/elo.py:115` — Existing TODO for goal-difference K-multiplier
- `worldcup_predictor/src/constants.py:6-7` — `K_FACTOR = 60` (base K for World Cup finals)
- `worldcup_predictor/src/constants.py:48+` — Elo sync constants from Phase 11
- `worldcup_predictor/src/constants.py:75-124` — `ELORATINGS_TEAM_CODES` mapping (48 teams)

### External Source (for reference, not checked in)
- `https://www.eloratings.net/about` — K-multiplier step-function and PK rule documentation

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/elo.py:update_ratings()` — Already handles `winner=None` for draws with 0.5/0.5 result split. Only needs PK-mode (0.75/0.25) addition.
- `src/elo.py:apply_elo_update()` — Caller that reads match dict and invokes `update_ratings()`. This is where draw detection and K-multiplier compute will be wired.
- `src/fetcher.py:process_matches()` — Knockout match processing. Currently skips draws at line 126.
- `src/fetcher.py:process_group_matches()` — Group match processing. Currently skips draws at line 314.
- `src/constants.py` — Centralized constants; `compute_k_factor()` constant params (e.g., K=60) go here.
- `src/state.py` — `save_teams()` / `load_teams()` — persistence for teams.json with atomic writes.

### Established Patterns
- Match entry dict: `{match_id, team_a, team_b, winner, home_score, away_score, completed_at}` — draw entries add `is_draw: true, winner: null`.
- Atomic JSON writes (write to temp, rename) — used by `save_teams()`, should be used for any new cache/persist files.
- `elo_update_log.json` from Phase 11 — backfill audit entries append to this.
- BSD event `id` used for dedup (Phase 10 D-05) — draw detection via score equality is compatible since BSD reports equal scores + winner for PK-decided matches.

### Integration Points
- `main.py:_run_iteration()` (line 293) — Periodic loop that calls fetcher and applies Elo. Draw-fixed entries flow through existing Elo application path.
- `main.py:_run_historical_catch_up()` (line 220+) — Historical catch-up that currently skips knockout draws at line 251.
- `main.py:_run_iteration()` periodic Elo sync check (line 314+) — After Phase 12, draws apply Elo normally.

</code_context>

<specifics>
## Specific Ideas

- Phase 11 established eloratings.net as the canonical Elo source (D-09). Phase 12 mirrors its treatment of all match outcomes as closely as practical — PK rule (0.75/0.25) and step-function K-multiplier both come from the eloratings.net spec.
- "Avoid ambiguity" was the guiding principle for the draw entry format — `winner: null + is_draw: true` is explicit.
- "If the source of truth says G=1 for draws, we use G=1" — the step-function (not the continuous approximation) was chosen because the step-function IS what eloratings.net publishes.
- The only decision that required evidence before locking was the draw K-multiplier (D-12/D-10). Research confirmed draws use G=1 per eloratings.net.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 12-Draw-Handling-Elo-Math*
*Context gathered: 2026-06-15*
