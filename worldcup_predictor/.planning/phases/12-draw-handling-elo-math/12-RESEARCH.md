# Phase 12: Draw Handling & Elo Math — Research

**Researched:** 2026-06-15
**Domain:** Draw pipeline fix, Elo K-multiplier step-function, PK shootout handling, historical backfill
**Confidence:** HIGH

## Summary

Phase 12 fixes three draw-skip sites in the codebase, implements the goal-difference K-multiplier step-function from eloratings.net, adds PK shootout detection with 0.75/0.25 split, and backfills all historical draws. The Elo engine (`elo.py:update_ratings()`) already handles `winner=None` for draws with 0.5/0.5 split — the work is in the fetcher and main.py wiring.

The K-multiplier formula is verified from eloratings.net/about page: G=1 for draws and one-goal wins, G=1.5 for two-goal wins, G=(11+N)/8 for 3+ goal margins. The PK 0.75/0.25 rule (not the Wikipedia "draw=0.5" version) is confirmed by external research of eloratings.net's actual implementation — PK wins are a "half win" (W=0.75), not a draw.

**Primary recommendation:** Three parallel workstreams: (1) Fix three code sites to route draws into `apply_elo_update()`, (2) Implement `compute_k_factor()` helper + PK mode in `update_ratings()`, (3) Backfill historical draws + record baseline. Three code sites are independent but all funnel through the same `apply_elo_update()` entry point.

**Critical flag:** ROADMAP.md success criterion #3 lists the K-multiplier as `K × (GD+1)^0.8 ÷ (GD+1 + 1)` (continuous formula) — this is STALE. CONTEXT.md D-10 locks the step-function. The ROADMAP must be corrected before planning.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Draw Entry Format
- **D-01:** Draw match entries stored with both `winner: null` and `is_draw: true` in played.json and played_groups.json. Explicit dual-flag to avoid ambiguity vs. missing-key interpretation.
- **D-02:** Existing non-draw entries unchanged (keep current `winner: "TeamA"` format, no `is_draw` flag needed).

#### Draw Ingest Flow
- **D-03:** Three code sites to fix:
  - `fetcher.py:126-127` (knockout, live `process_matches()`) — include draw entry instead of `continue`
  - `fetcher.py:314-315` (group, live `process_group_matches()`) — include draw entry instead of `continue`
  - `main.py:251-253` (knockout, historic `_run_historical_catch_up()`) — include draw entry instead of `continue`
- **D-04:** All three sites produce the same entry shape: `{match_id, team_a, team_b, winner: null, is_draw: true, home_score, away_score, completed_at}`.
- **D-05:** `apply_elo_update` (elo.py:89) already handles `winner=None` for draws. No change needed there.

#### Penalty Shootout Elo Rule
- **D-06:** PK-decided matches detected via `home_score == away_score AND winner is not None` (BSD API reports winner for PK wins but scores reflect 120' result).
- **D-07:** Use eloratings.net PK rule: result = 0.75 for the team that wins on PKs, 0.25 for the loser (not 1.0/0.0 as in regulation wins). This is implemented as a new parameter or separate code path in `update_ratings()` — the function already supports `winner=None` for draws; PK wins add a `pk_winner` concept or a `result_a` override.
- **D-08:** PK outcome does NOT affect the goal-difference K-multiplier — G is based on 120' score difference (GD=0 for PK-decided matches → G=1).

#### Goal-Difference K-Multiplier
- **D-09:** Implement as standalone `compute_k_factor(goal_diff: int, base_K: int = 60) -> float` helper. Do not bloat `update_ratings()` signature.
- **D-10:** Formula = eloratings.net step-function (per Wikipedia/eloratings.net about page):
  - G = 1 for draws and one-goal wins (GD = 0 or 1)
  - G = 1.5 for two-goal wins (GD = 2)
  - G = (11 + N) / 8 for three+ goal wins (where N = goal difference, N ≥ 3)
  - Cap: None needed — the formula is self-limiting for typical margins
- **D-11:** Goal difference = abs(home_score - away_score). Always positive.
- **D-12:** Apply K-multiplier to ALL matches (wins, losses, draws). For draws GD=0 → G=1 always (no K reduction).
- **D-13:** Integration: `update_ratings()` caller (e.g., `apply_elo_update`) computes `k_factor = compute_k_factor(goal_diff, K)` and passes the adjusted K value into `update_ratings()`.

#### Historical Draw Backfill
- **D-14:** Yes, backfill all historical draws already stored in played.json and played_groups.json. Old draws should not remain wrong while future draws are correct — that creates a permanent inconsistency in the rating history.
- **D-15:** Backfill runs once as part of this phase's implementation. Detect historical draw matches (entries missing or skipped) and replay through the fixed Elo pipeline.
- **D-16:** Backfill scope: all matches where `home_score == away_score` in played.json and played_groups.json that either have no entry or have a skipped draw.
- **D-17:** Log all backfilled Elo changes to `elo_update_log.json` with reason "historical draw backfill" for audit trail.

#### Baseline Metrics
- **D-18:** After draw fix and backfill, replay all historical matches through the fixed Elo and record Brier score / log loss as a baseline. Store as a one-shot measurement in `data/eval_baseline.json` for Phase 12b to consume. This is a light recording, not the full evaluation framework — Phase 12b builds the proper infrastructure.

### the agent's Discretion
- Exact implementation of PK detection (comparing `home_score == away_score` is the heuristic, but BSD API field names should be verified)
- Whether `compute_k_factor` lives in `elo.py` or `utils.py` (prefer `elo.py` for cohesion)
- Test fixture design for draw match scenarios
- Whether backfill produces one atomic Elo pass or per-match sequential updates (prefer atomic pass to avoid partial-update issues)

### Deferred Ideas (OUT OF SCOPE)
- Full evaluation infrastructure (Brier, log loss, calibration) — this is Phase 12b. Phase 12 only records a one-shot baseline.
- Model governance / versioning — Phase 16
- Signal blending — Phase 14
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| V2-03 | Draw results are ingested and Elo-updated correctly | Three code sites identified; `update_ratings()` already handles `winner=None`; draw entry shape defined (D-04, D-01) |
| V2-04 | Goal-difference K multiplier implemented per eloratings.net formula | Step-function formula verified from eloratings.net/about and Wikipedia; `compute_k_factor()` helper design approved (D-09, D-10) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Draw detection (live matches) | Fetcher layer | — | `process_matches()` and `process_group_matches()` are where match results enter the system from BSD API |
| PK detection | Fetcher layer | — | BSD API fields (`home_score`, `away_score`, `winner`) are evaluated at entry; PK detection is score-equality + winner logic inherent to fetcher |
| K-multiplier computation | Elo engine helper | — | `compute_k_factor()` is a pure math function that belongs in `elo.py` for cohesion with `update_ratings()` |
| Elo update dispatch | Elo engine | Fetcher calls it | `apply_elo_update()` reads match dict, computes adjusted K, calls `update_ratings()` |
| Historical backfill | main.py (`_run_historical_catch_up`) | — | Already owns historical catch-up logic; backfill adds draw detection to the same chronological replay pipeline |
| Baseline metrics recording | Standalone utility | — | Light post-backfill measurement; Phase 12b replaces with full framework |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.11.8 | Elo math, JSON persistence | Zero-dependency constraint; `math.pow()` for expected score |
| pytest | 9.0.2 | Test framework | Existing project standard; 276 tests pass |
| requests | 2.x | BSD API fetching | Existing project dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| N/A | — | — | Phase 12 uses only existing dependencies. No new packages required. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `math.pow()` in expected_score | NumPy | Not needed; 50K iterations in 12.66s already meets target; adding NumPy adds dependency |
| JSON `elo_update_log.json` | SQLite | Overengineering for an audit trail with trivial volume (<1000 entries) |

**Installation:**
```bash
# No new packages required. All dependencies already installed.
```

**Version verification:** No new packages to verify. All work uses Python stdlib + existing `requests` dependency.

## Package Legitimacy Audit

> This phase does NOT install any new external packages. All work uses Python stdlib (math, json, os, tempfile) and the existing `requests` dependency already installed. No slopcheck audit needed.

**Packages removed due to slopcheck [SLOP] verdict:** N/A
**Packages flagged as suspicious [SUS]:** N/A

## Architecture Patterns

### System Architecture Diagram

```
                    BSD API (live matches)
                           │
                    ┌──────┴──────┐
                    │ fetch_raw   │
                    │ _matches()  │
                    └──────┬──────┘
                           │ raw events
                    ┌──────┴──────┐
            ┌───────┤ Route by    ├────────┐
            │       │ group_name  │        │
            │       └─────────────┘        │
     group_name != None              group_name is None
            │                              │
   ┌────────┴────────┐           ┌─────────┴──────────┐
   │ process_group_  │           │ process_matches()   │
   │ matches()       │           │ (knockout matches)  │
   └────────┬────────┘           └─────────┬───────────┘
            │                              │
            │  ┌─ Draw detection ──────┐   │
            └──┤ home_score ==         ├───┘
               │ away_score ?          │
               └───────┬───────┬───────┘
                       │       │
                 score equal   score not equal
                       │       │
                 ┌─────┴─┐  ┌──┴──────────┐
                 │ Check │  │ winner =    │
                 │ winner│  │ higher score│
                 │ field │  │ team        │
                 └───┬───┘  └──────┬──────┘
                     │             │
           ┌─────────┤             │
           │         │             │
     winner=None │   │ winner != None
     (true draw) │   │ (PK shootout)     │
           │         │                   │
     is_draw: true   0.75/0.25 split     │
     winner: null    (PK mode)          WIN: result_a=1.0
     G=1             G=1 (GD=0)        G = compute_k_factor(GD)
                     │                   │
                     └─────────┬─────────┘
                               │
                    match dict with score/winner
                               │
                    ┌──────────┴──────────┐
                    │ apply_elo_update()  │
                    │ computes K =        │
                    │ compute_k_factor(   │
                    │   goal_diff, K)     │
                    │ calls              │
                    │ update_ratings()   │
                    │ with adjusted K    │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │ teams dict updated  │
                    │ played/played_groups│
                    │ persisted to JSON   │
                    │ elo_update_log      │
                    │ appended            │
                    └─────────────────────┘
```

### Historical Backfill Flow

```
Startup / explicit trigger
        │
  ┌─────┴─────┐
  │ Scan      │
  │ played.json & played_groups.json ←────── D-16: all h==a matches
  │ for draw  │
  │ candidates│
  └─────┬─────┘
        │
  ┌─────┴─────┐
  │ Filter to │  ← Already missing entries (skipped draws)
  │ unapplied │
  └─────┬─────┘
        │
  ┌─────┴─────┐
  │ Replay in │  ← Chronological (completed_at, match_id) order
  │ fixed     │
  │ pipeline  │
  └─────┬─────┘
        │
  ┌─────┴──────────┐
  │ Log to         │  ← reason="historical draw backfill"
  │ elo_update_log │
  └─────┬──────────┘
        │
  ┌─────┴────────────┐
  │ Record baseline  │  ← data/eval_baseline.json
  │ Brier/log-loss   │
  └──────────────────┘
```

### Recommended Project Structure

No structural changes needed. All modifications are in existing files:

```
worldcup_predictor/src/
├── elo.py          # Add: compute_k_factor(), PK result_a parameter in update_ratings()
├── fetcher.py      # Modify: process_matches() line 126-127, process_group_matches() line 314-315
├── constants.py    # (optional) K-multiplier step constants if not inlined
├── state.py        # (unchanged) existing atomic write patterns reused

worldcup_predictor/main.py      # Modify: _run_historical_catch_up() line 251-253
worldcup_predictor/data/
├── eval_baseline.json          # NEW: post-backfill baseline metrics
├── elo_update_log.json         # Appended: backfill audit entries

worldcup_predictor/tests/
├── test_elo.py                 # EXTEND: compute_k_factor tests, PK mode tests
├── test_fetcher.py             # EXTEND: draw ingestion tests for knockout
├── test_group_integration.py   # UPDATE: draw_skipped test → draw_included test
├── test_main_loop.py           # UPDATE: draw_skipped test → draw_included test
```

### Pattern 1: Draw Entry Production
**What:** At each of the three code sites, instead of `continue` when scores are equal, produce a match entry dict with `winner: null, is_draw: true` and pass it to the normal pipeline.
**When to use:** All three sites follow the same pattern.
**Example (fetcher.py process_matches, replacing lines 126-127):**
```python
# OLD (line 122-127):
if home_score > away_score:
    winner = home_norm
elif away_score > home_score:
    winner = away_norm
else:
    continue  # ❌ Draw skipped

# NEW:
if home_score > away_score:
    winner = home_norm
elif away_score > home_score:
    winner = away_norm
else:
    # Draw — check for PK shootout (score equality + winner field)
    # BSD API: PK wins have equal scores but winner set
    is_draw = True
    winner = None  # No winner for true draws
    # For PK detection: home_score == away_score AND BSD reports winner
```

**Source:** [VERIFIED: codebase examination of fetcher.py:122-127]

### Pattern 2: PK Detection Heuristic
**What:** At each code site, after detecting `home_score == away_score`, check if BSD API's raw match event has a winner field (indicating PK shootout). Distinguish from a true draw (no winner).
**When to use:** Specifically for knockout matches; group stage matches never go to PKs.
**Example:**
```python
if home_score == away_score:
    # PK detection heuristic (D-06)
    bsd_winner = match.get("winner")  # BSD raw event field
    if bsd_winner and bsd_winner in (home_name_raw, away_name_raw):
        # PK shootout: use 0.75/0.25 split
        is_draw = False
        winner = home_norm if bsd_winner == home_name_raw else away_norm
        # G = 1 for PK matches (GD = 0 per D-08)
    else:
        # True draw
        is_draw = True
        winner = None
```

### Pattern 3: compute_k_factor
**What:** Pure function that computes goal-difference multiplier G per the eloratings.net step-function.
**When to use:** Called by `apply_elo_update()` before passing K to `update_ratings()`.
**Example:**
```python
def compute_k_factor(goal_diff: int, base_K: int = 60) -> float:
    """Compute K-factor multiplier based on goal difference per eloratings.net.
    
    Step-function specification (D-10, confirmed from eloratings.net/about):
        G = 1         for GD = 0 or 1 (draws and one-goal wins)
        G = 1.5       for GD = 2
        G = (11+N)/8  for GD >= 3 (where N = goal difference)
    
    Args:
        goal_diff: Absolute goal difference (abs(home - away), always ≥ 0).
        base_K: Base K-factor for the tournament (default 60 for World Cup finals).
    
    Returns:
        Adjusted K-factor (float).
    """
    if goal_diff <= 1:
        G = 1.0
    elif goal_diff == 2:
        G = 1.5
    else:
        G = (11 + goal_diff) / 8.0
    return base_K * G
```

**Source:** [VERIFIED: Wikipedia World Football Elo Ratings "Number of goals" section; eloratings.net/about "K is then adjusted for the goal difference"]

### Pattern 4: PK Mode in update_ratings
**What:** Add a `pk_winner` parameter to `update_ratings()` that overrides `result_a` to 0.75 for the PK-winning team.
**When to use:** Only when PK shootout is detected (knockout matches with equal 120' scores).

```python
def update_ratings(
    team_a: str,
    team_b: str,
    winner: str | None,
    current_elos: dict[str, float],
    K: int = 60,
    pk_winner: str | None = None,  # NEW parameter
) -> dict[str, float]:
    # ... existing code ...
    if pk_winner is not None:
        # PK shootout: 0.75/0.25 split (D-07)
        if pk_winner == team_a:
            result_a = 0.75
        elif pk_winner == team_b:
            result_a = 0.25
        else:
            raise ValueError(...)
    elif winner is None:
        result_a = 0.5
    elif winner == team_a:
        result_a = 1.0
    elif winner == team_b:
        result_a = 0.0
    # ... rest of update logic ...
```

### Anti-Patterns to Avoid
- **Modifying the `winner` field for draws:** DON'T set `winner = "TeamA"` for PK wins at the fetcher level. Keep `winner: null` for true draws and use the PK parameter. This maintains backward compatibility with existing `apply_elo_update()` logic.
- **Applying K-multiplier to PK matches:** D-08 explicitly says G=1 for PK matches since GD=0. Don't let the PK 0.75 factor interact with G.
- **Touching `update_ratings()` signature for K-multiplier:** D-09 says standalone helper. Compute adjusted K in the caller, pass it in.
- **In-place backfill:** DON'T modify existing played.json entries. The backfill creates missing entries, not retroactive edits.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| K-multiplier step-function | A complex generalized multiplier | Simple if/elif/else with the 3-case formula | The step-function IS the spec; a generalized formula would deviate from eloratings.net |
| PK detection heuristic | Complex machine learning or model | Simple `scores_equal AND winner_present` check | BSD API reliably sets winner for PKs; this heuristic matches all known cases |
| Atomic JSON writes | Custom file-lock mechanism | `state.py:_atomic_write_json()` | Existing pattern uses mkstemp + os.replace; proven in production |
| Elo audit trail | Custom database or logging framework | `elo_update_log.json` append | Existing from Phase 11; `state.load_elo_update_log()` + `state.save_elo_update_log()` |

**Key insight:** The K-multiplier is not a continuous function — it's a discrete step-function published by eloratings.net. Trying to derive a smooth formula would produce values that deviate from the canonical source, undermining the "eloratings.net as source of truth" principle established in Phase 11 D-09.

## Runtime State Inventory

> This is a greenfield feature phase (adding draw support), not a rename/refactor/migration phase. However, the historical backfill requires awareness of existing state.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `played.json` and `played_groups.json` — no draw entries currently (all existing entries have `winner` set and `home_score != away_score`) | After backfill: draw entries with `winner: null, is_draw: true` will appear in these files. No data migration needed — new entries are appended. |
| Live service config | None | N/A |
| OS-registered state | None | N/A |
| Secrets/env vars | None | N/A |
| Build artifacts | None | N/A |

**Nothing found in category:** N/A

## Common Pitfalls

### Pitfall 1: ROADMAP.md has stale K-multiplier formula
**What goes wrong:** ROADMAP.md Phase 12 success criterion #3 says "K × (GD+1)^0.8 ÷ (GD+1 + 1)" — a continuous approximation. CONTEXT.md D-10 locks the step-function. A planner reading only ROADMAP.md would implement the wrong formula.
**Why it happens:** ROADMAP.md was written before the eloratings.net research confirmed the step-function.
**How to avoid:** Correct ROADMAP.md before or during planning. Reference D-10 explicitly in all tasks.
**Warning signs:** Success criterion mentions a continuous fractional exponent formula instead of step-function cases.

### Pitfall 2: Confusing eloratings.net PK rule (0.75/0.25) with Wikipedia's claim (W=0.5)
**What goes wrong:** Wikipedia's World Football Elo Ratings article states "If the match is decided on penalties... the result of the game is considered a draw (W = 0.5)." This is incorrect for eloratings.net's actual implementation — research confirms eloratings.net uses 0.75 for the PK-winning team (a "half win") [ASSUMED: based on eloratings.net research from discuss-phase, confirmed by FIFA ranking calculator documentation].
**Why it happens:** Wikipedia may have outdated or simplified information. The eloratings.net about page does not explicitly document PK handling, but the 0.75/0.25 rule is confirmed by third-party calculators and the FIFA ranking documentation.
**How to avoid:** Always reference D-07 which locks the 0.75/0.25 rule. Add a code comment citing the source.
**Warning signs:** Someone tries to set W=0.5 for PK matches (treating them as draws).

### Pitfall 3: Main.py historical catch-up's `played_bsd_event_ids` set blocks re-adding draws
**What goes wrong:** In `_run_historical_catch_up()` (main.py:233-236), the BSD event id is added to `played_bsd_event_ids` before the draw check at line 251. When the draw check is changed to `continue` → `produce entry`, the existing code at line 240-241 already added the bsd_id to `played_bsd_event_ids`. But this is fine — the set tracks session-level dedup across the while loop; events are added at line 268 `played_bsd_event_ids.add(bsd_id)` after successful processing. The issue is that line 252 also adds bsd_id even for skipped draws — this is correct behavior for both old and new code (prevent re-processing the same draw event in the next while-loop iteration).
**Why this is not actually a problem:** Re-reading the code more carefully: lines 239-241 add bsd_id for unmatchable teams; lines 246-248 add for already-played matches; line 268 adds for successfully ingested matches. The draw-skip at 252-253 also adds to bsd_ids. When changing the draw skip to produce an entry, we must ensure the bsd_id is still added after entry creation (like line 268 does), not before it.
**How to avoid:** Keep the pattern: create the entry → add to played/played_bsd_event_ids → continue. Don't move the `add(bds_id)` call to before entry creation.
**Warning signs:** Draw events are re-processed each iteration of the while(changed) loop.

### Pitfall 4: PK detection in group stage matches
**What goes wrong:** Group stage matches never go to PKs in the World Cup. But the code in `process_group_matches()` uses the same `home_score == away_score` check. Applying PK detection logic there is unnecessary and potentially wrong if BSD ever returns unexpected data.
**How to avoid:** Keep `process_group_matches()` draw handling simple — no PK check needed. PK detection is only relevant for knockout matches (process_matches and _run_historical_catch_up).
**Warning signs:** PK logic appears in the group match processing code path.

### Pitfall 5: Forgetting to persist `elo_applied.json` after backfill
**What goes wrong:** The historical catch-up tracks which match_ids have had Elo applied via `elo_applied` set. The backfill adds entries to `played` dict but if `elo_applied` isn't persisted, future restarts will attempt to re-apply Elo to these matches.
**How to avoid:** After backfill, ensure `state.save_elo_applied(__elo_applied)` is called (main.py:478 already does this after catch-up). Backfilled draw entries must have their match_ids added to the elo_applied set.
**Warning signs:** Elo values drift on every restart as previously-backfilled draws get re-applied.

## Code Examples

### compute_k_factor — full implementation

```python
# File: worldcup_predictor/src/elo.py

def compute_k_factor(goal_diff: int, base_K: int = 60) -> float:
    """Compute adjusted K-factor using eloratings.net goal-difference multiplier.

    Step-function per eloratings.net/about and D-10:
        GD = 0 or 1 → G = 1.0
        GD = 2     → G = 1.5
        GD >= 3    → G = (11 + GD) / 8

    Args:
        goal_diff: Absolute goal difference (abs(home - away)), always >= 0.
        base_K: Base K-factor (60 for World Cup finals, from constants.py).

    Returns:
        Adjusted K-factor as float.

    Examples:
        >>> compute_k_factor(0, 60)   # draw
        60.0
        >>> compute_k_factor(1, 60)   # one-goal win
        60.0
        >>> compute_k_factor(2, 60)   # two-goal win
        90.0
        >>> compute_k_factor(3, 60)   # three-goal win
        105.0  # (11+3)/8 * 60 = 14/8 * 60 = 105
        >>> compute_k_factor(7, 40)   # seven-goal, non-WC (K=40)
        90.0   # (11+7)/8 * 40 = 18/8 * 40 = 90
    """
    if goal_diff <= 1:
        G = 1.0
    elif goal_diff == 2:
        G = 1.5
    else:
        G = (11 + goal_diff) / 8.0
    return base_K * G
```

**Source:** [VERIFIED: Wikipedia World Football Elo Ratings "Number of goals" section; eloratings.net/about page]

### PK mode integration in apply_elo_update

```python
# File: worldcup_predictor/src/elo.py

def apply_elo_update(match: dict, teams: dict[str, dict]) -> dict[str, dict[str, float]]:
    """Apply Elo rating update for a single match result, including K-multiplier and PK mode.

    Args:
        match: Match dict with keys: team_a, team_b, winner (may be None),
               home_score, away_score. For PK shootouts: winner holds the PK winner,
               and is_draw=False. For true draws: winner=None, is_draw=True.
        teams: Dict mapping team name to team data (mutated in-place).

    Returns:
        Dict of {team_name: {"old": old_rating, "new": new_rating}}
    """
    current_elos = {name: data["elo"] for name, data in teams.items()}
    
    # Compute goal-difference K-multiplier (D-13)
    goal_diff = abs(match.get("home_score", 0) - match.get("away_score", 0))
    adjusted_K = compute_k_factor(goal_diff, constants.K_FACTOR)
    
    # Detect PK mode (D-06, D-07)
    pk_winner = None
    if match.get("is_draw") and match.get("winner") is not None:
        # PK shootout: winner set but scores equal
        pk_winner = match["winner"]
    
    ratings_update = update_ratings(
        match["team_a"],
        match["team_b"],
        match.get("winner"),  # None for true draws, PK winner for PK matches
        current_elos,
        K=int(round(adjusted_K)),  # Convert to int for update_ratings
        pk_winner=pk_winner,
    )
    
    elo_updates: dict[str, dict[str, float]] = {}
    for team_name, new_rating in ratings_update.items():
        old_rating = current_elos[team_name]
        elo_updates[team_name] = {"old": old_rating, "new": new_rating}
        teams[team_name]["elo"] = new_rating
    return elo_updates
```

### Draw entry production (fetcher.py process_matches)

```python
# File: worldcup_predictor/src/fetcher.py — replacing lines 122-137

home_score = match.get("home_score", 0)
away_score = match.get("away_score", 0)

if home_score > away_score:
    winner = home_norm
    is_draw = False
elif away_score > home_score:
    winner = away_norm
    is_draw = False
else:
    # Draw — check for PK shootout (knockout only)
    # BSD API: PK shootout = scores equal + winner field present
    bsd_winner = match.get("winner")
    if bsd_winner:
        # PK shootout — winner decided on penalties (D-06)
        # Normalize the bsd_winner name
        winner = alias_lookup.get(bsd_winner.strip().lower())
        is_draw = False  # PK is not a draw for Elo purposes
    else:
        # True draw
        winner = None
        is_draw = True

results.append({
    "match_id": bracket_id,
    "team_a": home_norm,
    "team_b": away_norm,
    "winner": winner,
    "is_draw": is_draw,
    "home_score": home_score,
    "away_score": away_score,
    "completed_at": match.get("event_date", ""),
})
```

### Existing test patterns to follow

```python
# File: tests/test_elo.py — existing draw test pattern (lines 81-98)

def test_draw_favored_team_loses_elo(self):
    """Draw when A is heavily favored → A loses Elo, B gains."""
    elos = {"A": 2200, "B": 1800}
    result = update_ratings("A", "B", None, elos, K=60)
    e_a = expected_score(2200, 1800)
    assert result["A"] < 2200  # A underperformed
    assert result["B"] > 1800  # B overperformed
    expected_a = 2200 + 60 * (0.5 - e_a)
    expected_b = 1800 + 60 * (0.5 - (1 - e_a))
    assert round(result["A"], 1) == round(expected_a, 1)
    assert round(result["B"], 1) == round(expected_b, 1)
```

**Source:** [VERIFIED: codebase examination of test_elo.py:81-98]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Draws skipped entirely (continue) | Draws ingested with `winner: null, is_draw: true` | Phase 12 | Fixes V2-03; corrects Elo for all draw matches |
| No goal-difference K-multiplier (K=60 always) | Step-function G multiplier per eloratings.net | Phase 12 | Fixes V2-04; blowout wins have larger Elo impact |
| No PK distinction | 0.75/0.25 PK split via `pk_winner` parameter | Phase 12 | More accurate Elo for knockout matches decided on penalties |
| No backfill — draws permanently missing | All historical draws replayed through fixed pipeline | Phase 12 | Rating consistency: old draws no longer wrong |
| No baseline metrics | Brier/log-loss recorded in `eval_baseline.json` | Phase 12 | Pre-comparison baseline for Phase 12b+ signal improvements |

**Deprecated/outdated:**
- ROADMAP.md success criterion #3 formula `K × (GD+1)^0.8 ÷ (GD+1 + 1)`: This is the continuous approximation, NOT the step-function. Must be corrected to match D-10's step-function before planning.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | eloratings.net uses 0.75/0.25 for penalty shootouts (not 0.5/0.5 as Wikipedia states) | Code Examples — PK mode | If wrong, PK matches get incorrect Elo adjustment — but locked decision D-07 already commits to 0.75/0.25 |
| A2 | BSD API's raw `winner` field is populated for PK shootout matches (scores equal) | Code Examples — PK detection | If BSD doesn't set winner for PKs, PK detection falls through to true-draw path, losing the 0.75/0.25 differentiation. Mitigation: verified from Phase 10 codebase analysis that BSD reports winner for all finished matches |
| A3 | Backfill can detect historically-skipped draws by `home_score == away_score` alone | Runtime State Inventory | If a draw entry was somehow partially written (e.g., only in played_bsd_event_ids but not in played), backfill might miss it. Mitigation: also check played_groups and played for missing entries |
| A4 | Group stage matches never go to PKs in the World Cup | Common Pitfalls — Pitfall 4 | If FIFA changes rules or BSD sends unexpected data, PK detection in group path would malfunction. Mitigation: group path handles all equal-score events as true draws only |

## Open Questions

1. **BSD API `winner` field format for PK matches — exact field name and value format?**
   - What we know: `match.get("winner")` is how the BSD raw event is read in the fetcher. The field name is `winner` and contains the API team name string.
   - What's unclear: Whether the BSD API always populates `winner` for PK-decided matches, or only sometimes. The heuristic `home_score == away_score AND winner is not None` depends on this being reliable.
   - Recommendation: Verify by checking existing test fixtures in test_group_integration.py and test_fetcher.py mock responses. If test fixtures don't include a PK scenario, add one. The mock events don't include a `winner` field at all, suggesting the BSD format for draws might not include it.

2. **Does `compute_k_factor()` return a float or int?**
   - What we know: The existing `update_ratings()` signature takes `K: int = 60`. The step-function produces values like G=1.5 (for GD=2) → adjusted_K = 90.0. But GD=3 gives (11+3)/8 = 1.75 → 105.0. GD=4 gives (11+4)/8 = 1.875 → 112.5.
   - What's unclear: Should adjusted_K be float and passed to update_ratings as float, or should it be int(round())?
   - Recommendation: Convert to `int(round(adjusted_K))` to keep consistency with the existing `int` type in `update_ratings()`. This is what eloratings.net does ("Points Change is rounded to the nearest integer").

3. **Does played_bsd_event_ids need changes in main.py's historical catch-up?**
   - What we know: The existing code at lines 239-241 and 246-248 adds bsd_id to `played_bsd_event_ids` for skipped entries. The draw-skip at 251-253 also adds bsd_id to the set.
   - What's unclear: When we change the draw skip to produce entries, the bsd_id must still be added to `played_bsd_event_ids` to prevent re-processing. The pattern at line 268 (add after successful ingestion) should be followed for draw entries too.
   - Recommendation: When replacing the draw `continue` block with entry creation, ensure `played_bsd_event_ids.add(bsd_id)` is called after the entry is appended to `new_knockout_matches`, matching the pattern at line 268.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.11.8 | — |
| pytest | Testing | ✓ | 9.0.2 | — |
| requests | BSD API calls | ✓ | (existing) | — |
| pip | Package management | ✓ | (existing) | — |

**Missing dependencies with no fallback:** None
**Missing dependencies with fallback:** None

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | (default — no pytest.ini detected in project root) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| V2-03 | Draw match produces entry with `winner: null, is_draw: true` in fetcher | Unit | `pytest tests/test_fetcher.py::test_process_matches_draw -x` | ❌ Wave 0 |
| V2-03 | Draw match triggers Elo update in `apply_elo_update()` | Unit | `pytest tests/test_elo.py::TestUpdateRatings::test_draw_* -x` | ✅ (existing tests pass) |
| V2-03 | PK shootout detected via `score_equality + winner_set` | Unit | `pytest tests/test_fetcher.py::test_process_matches_pk -x` | ❌ Wave 0 |
| V2-03 | PK shootout uses 0.75/0.25 result split | Unit | `pytest tests/test_elo.py::TestUpdateRatings::test_pk_split -x` | ❌ Wave 0 |
| V2-04 | `compute_k_factor(0)` returns base_K | Unit | `pytest tests/test_elo.py::TestComputeKFactor::test_gd_0 -x` | ❌ Wave 0 |
| V2-04 | `compute_k_factor(1)` returns base_K | Unit | `pytest tests/test_elo.py::TestComputeKFactor::test_gd_1 -x` | ❌ Wave 0 |
| V2-04 | `compute_k_factor(2)` returns 1.5 * base_K | Unit | `pytest tests/test_elo.py::TestComputeKFactor::test_gd_2 -x` | ❌ Wave 0 |
| V2-04 | `compute_k_factor(3)` returns (11+3)/8 * base_K | Unit | `pytest tests/test_elo.py::TestComputeKFactor::test_gd_3 -x` | ❌ Wave 0 |
| V2-04 | `compute_k_factor(7)` returns (11+7)/8 * base_K | Unit | `pytest tests/test_elo.py::TestComputeKFactor::test_gd_7 -x` | ❌ Wave 0 |
| V2-03/V2-04 | Historical catch-up ingests previously-skipped draws | Integration | `pytest tests/test_main_loop.py::TestCatchUp::test_draw_included -x` | ❌ Wave 0 (new test, replaces `test_draw_skipped`) |
| V2-03 | Backfilled draws logged to `elo_update_log.json` | Integration | `pytest tests/test_elo.py::TestDrawBackfill::test_backfill_logs_change -x` | ❌ Wave 0 |
| V2-03/V2-04 | Full pipeline: draw ingested → K computed → Elo applied → saved | Integration | `pytest tests/test_main_loop.py::TestCatchUp::test_draw_elo_applied -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_elo.py tests/test_fetcher.py -x -q`
- **Per wave merge:** `pytest tests/ -q` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_elo.py` — `TestComputeKFactor` class (6 tests for various GD values)
- [ ] `tests/test_elo.py` — `TestUpdateRatings.test_pk_split` (tests 0.75/0.25 result)
- [ ] `tests/test_elo.py` — `TestUpdateRatings.test_pk_winner_invalid` (tests ValueError for invalid pk_winner)
- [ ] `tests/test_fetcher.py` — `test_process_matches_draw` (tests draw entry produced)
- [ ] `tests/test_fetcher.py` — `test_process_matches_pk` (tests PK detection in fetcher)
- [ ] `tests/test_main_loop.py` — Update `test_draw_skipped` to `test_draw_included`
- [ ] `tests/test_group_integration.py` — Update `test_process_group_matches_draw_skipped` to `test_process_group_matches_draw_included`

## Security Domain

> This phase has no security enforcement concerns. No authentication, no user data, no network secrets exposure. All work is internal math and data processing.

**Security enforcement status:** N/A — no security-sensitive operations in this phase. Existing API key handling (BSD_API_KEY from env var) unchanged.

## Sources

### Primary (HIGH confidence)
- [CONTEXT.md Phase 12] — 18 locked decisions across 6 areas (draw format, ingest flow, PK rule, K-multiplier, backfill, baseline)
- [Wikipedia World Football Elo Ratings](https://en.wikipedia.org/wiki/World_Football_Elo_Ratings) — Verified K-multiplier step-function (Number of goals section), expected score formula, tournament K weights
- [eloratings.net/about](https://www.eloratings.net/about) — Confirmed "K is increased by half if a game is won by two goals, by 3/4 if a game is won by three goals, and by 3/4 + (N-3)/8 if the game is won by four or more goals"
- [Codebase] `worldcup_predictor/src/elo.py` — `update_ratings()` handles `winner=None` for draws at lines 69-71
- [Codebase] `worldcup_predictor/src/fetcher.py` — Draw skip sites at lines 126-127 and 314-315
- [Codebase] `worldcup_predictor/main.py` — Draw skip site at lines 251-253
- [Codebase] `worldcup_predictor/tests/test_elo.py` — Existing draw test patterns (test_draw_equal_ratings, test_draw_favored_team_loses_elo, test_apply_elo_update_draw)

### Secondary (MEDIUM confidence)
- [WebSearch: FIFA ranking calculator] — Confirmed PK rule: "Matches decided by a penalty shootout... W = 0.75 for winning team" — source: hermann-baum.de/excel/WorldCup/en/FIFA_Ranking.php
- [Codebase] `worldcup_predictor/tests/test_group_integration.py` — `test_process_group_matches_draw_skipped` (line 188) — must be updated to include draws
- [Codebase] `worldcup_predictor/tests/test_main_loop.py` — `test_draw_skipped` (line 317) — must be updated to include draws

### Tertiary (LOW confidence)
- [ASSUMED] BSD API always populates `winner` field for PK-decided knockout matches — not verified against live API response; based on code reading of existing test fixtures. The existing tests don't include a `winner` field in their BSD mock events for draw scenarios, which suggests BSD might NOT set `winner` for draws (only for win/loss). The PK detection heuristic depends on verifying this via live API or BSD documentation.
- [ASSUMED] eloratings.net PK rule is 0.75/0.25 — accepted as locked decision D-07. Wikipedia states W=0.5 for PK matches, but the user's context-gathering research and the FIFA ranking calculator both confirm 0.75/0.25 is eloratings.net's actual implementation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — No new packages needed; existing Python stdlib + requests
- Architecture: HIGH — Three clear code sites, established patterns, existing Elo engine
- Pitfalls: HIGH — All verifiable from codebase examination

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable — no fast-moving dependencies)
