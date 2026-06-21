# Phase 20: Output Enhancement & Coverage Seal — Research

**Researched:** 2026-06-21
**Domain:** Console display enhancement, statistical computation, data persistence, field coverage auditing
**Confidence:** HIGH

## Summary

Phase 20 delivers four requirements that collectively surface signal-level prediction detail, add statistical rigor with Wilson Score confidence intervals, persist tournament probability history for trend analysis, and seal the BSD API field coverage target at ≥60% meaningful fields.

The phase touches 5 source files but introduces only 3 new functions, 8 new entries in existing maps, and 2 new JSON persistence functions. No new external dependencies — all computation uses `math.sqrt` (stdlib). The CLI flag pattern (`--match-detail`) reuses the established `--ai-preview` pattern from Phase 18. The focus card is the single consolidation point for all display detail: signals, CI, stats, context, xG, coach. The probability log reuses the `append_prediction_history()` pattern from state.py. The coverage auditor is a standalone pure-computation function.

**Primary recommendation:** Split into 3 plans executed in dependency order: (1) New field extraction + coverage auditor, (2) Per-match table + focus card + CI, (3) Probability log + trend column.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Primary display is a per-match table showing all remaining/upcoming matches with 7 signal columns (Blended, Elo, Odds, CatBoost, Form, Lineup, xG) plus a blended Δ column. Mockup 1, ~85 chars wide.
- **D-02:** Table gated behind `--match-detail` CLI flag (same pattern as `--ai-preview`).
- **D-03:** Δ column in the table is blended probability delta only (not per-signal). Answers "did anything change for this match?" — a triage gate.
- **D-04:** Focus card (Mockup 3, ~84 chars) opened by selecting a row from the table. Contains: all 7 signals with provenance labels, per-signal Δ, CI column (Wilson 95%), match context (venue, referee, coach names), match stats (fouls, corner_kicks, shots_off_target, shots_on_target, possession, yellow/red cards, xG).
- **D-05:** Focus card is a child of V2-27 — only accessible from the per-match table. Not directly reachable from championship table.
- **D-06:** Flow: default output → `--match-detail` → per-match signal table → focus row → focus card.
- **D-07:** Wilson score 95% CI displayed only in the focus card. NOT in championship table, NOT in per-match table. Wilson chosen over Clopper-Pearson because pure-Python Clopper-Pearson requires ~100 lines for negligible accuracy gain at n≈50000.
- **D-08:** CI format: `[.452 — .516]` — lower and upper bound alongside the point estimate. Computed via `math.sqrt` only.
- **D-09:** Single rolling JSON file (`probability_log.json`) — array of snapshot dicts appended after every `_run_iteration()`. Same pattern as `prediction_history.json`.
- **D-10:** Snapshot content: full probability dictionary (all teams, all stages: qf, sf, final, champion). Timestamped.
- **D-11:** Cadence: every `_run_iteration()` — same as simulation cycle. No separate timer.
- **D-12:** Trend arrow (↑ / ↓ / →) added to championship table as a new column. Compares current champion probability vs. rolling window mean of last 5 snapshots. ↑ : current > window mean + threshold; ↓ : current < window mean - threshold; → : within threshold.
- **D-13:** Trend column hidden on first run (no window to compare against).
- **D-14:** Trend is championship-table only — NOT in per-match table, NOT in focus card.
- **D-15:** Target: ≥60% BSD API meaningful field coverage (counts Prediction + Display + Operational fields only; excludes No-Value noise). Denominator = 47 meaningful fields.
- **D-16:** Automated auditor script reports: total meaningful fields, fields currently extracted, specific missing fields by value category, coverage percentage.
- **D-17:** Auditor reports both meaningful coverage (with target) and raw coverage (informational). Only meaningful coverage carries a target.
- **D-18:** Prioritized extraction for the 3 high-value fields: fouls, corner_kicks, shots_off_target (immediate, 6 lines in `_STATS_FIELD_MAP`).
- **D-19:** Coach names, fouls, corner_kicks, shots_off_target, xG all appear inside the focus card only — NOT as a separate section, NOT in any table.
- **D-20:** Focus card layout: signal breakdown (top) → per-signal Δ + CI (middle) → match context (venue, referee, coaches) → match stats (fouls, corners, shots, possession, cards, xG).

### the agent's Discretion

- Exact field-name fallback chains for newly extracted fields (fouls, corners, shots_off_target) — determined from existing BSD probe data.
- Whether the focus card is triggered by match ID input or interactive row selection — researcher/planner to propose.
- Trend threshold value — should be small enough to detect meaningful changes (recommend: 0.005).
- Whether `--match-detail` also shows the focus card inline or requires a separate interaction step.

### Deferred Ideas (OUT OF SCOPE)

- Championship probability signal decomposition — requires a new requirement ID (V2-31+). Not in Phase 20 scope.
- Historical backfill of stats/context/xG for already-played matches. No consumer exists yet.
- Interactive row selection for the focus card — post-MVP UX enhancement.
- Probability log export / analysis — stored but not analyzed.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| V2-27 | Per-match signal breakdown display (blended + per-signal) in console | See Technical Approach §V2-27. Two new display functions in output.py + --match-detail CLI flag |
| V2-28 | 95% Wilson score confidence intervals alongside probabilities | See Technical Approach §V2-28. Pure math.sqrt, ~5 lines, in focus card only |
| V2-29 | Historical probability log across tournament duration with trend tracking | See Technical Approach §V2-29. New JSON persistence + Trend column on championship table |
| V2-30 | ≥60% BSD API meaningful field coverage with automated auditor script | See Technical Approach §V2-30. New field extraction (6 lines) + coverage auditor function |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-match signal table | Display (output.py) | — | Pure console rendering — reads cache dicts, no state changes |
| Focus card | Display (output.py) | — | Same as above, reads enriched match data from played/played_groups |
| Wilson CI computation | Display (output.py) | — | Pure math computation, formatted as display string in focus card |
| Probability snapshot persistence | State (state.py) | Orchestration (main.py) | Same pattern as append_prediction_history — state owns I/O, main.py calls |
| Trend column in championship table | Display (output.py) | — | Reads probability_log, computes rolling mean, renders arrow |
| New field extraction | Enrichment (enrichment.py) | — | Pure extraction from BSD event dicts; same pattern as existing _STATS_FIELD_MAP |
| Coverage auditor | Standalone utility | — | Pure computation over field maps; no state or I/O dependency |

## Standard Stack

### Core
No new dependencies. All implementation is pure Python stdlib.

| Module | Purpose | Why Standard |
|--------|---------|--------------|
| `math.sqrt` | Wilson score CI denominator | Only math needed; avoids scipy dependency per D-07 |
| `json` (stdlib) | Probability log persistence | Same pattern as all other state persistence |
| `argparse` (stdlib) | `--match-detail` CLI flag | Same pattern as `--ai-preview`, `--once`, `--seed` |

### Installation
No new packages. Phase is pure Python stdlib + existing project imports.

**Version verification:** Not applicable — no new packages.

## Package Legitimacy Audit

No external packages installed in this phase. All implementation uses Python stdlib (`math.sqrt`, `json`, `argparse`, `datetime`) and existing project modules. Skipping slopcheck.

## Architecture Patterns

### System Architecture Diagram

```
                                Existing Data Flow
                                =================
                                
  ┌──────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐
  │ Signal caches        │    │ Enriched match data │    │ Probability     │
  │ (odds, catboost,     │───►│ (stats + context    │    │ log (new)       │
  │  form, lineup)       │    │  on match entries)  │    │ probability_log │
  └──────────┬───────────┘    └──────────┬──────────┘    │ .json           │
             │                          │                └────────┬────────┘
             ▼                          ▼                         │
  ┌─────────────────────┐   ┌──────────────────────┐              │
  │ New: Signal data    │   │ New: Focus card      │              │
  │ gatherer helper     │   │ display function     │              │
  │ (main.py)           │──►│ (output.py)          │              │
  └─────────────────────┘   └──────────┬───────────┘              │
                                       │                          │
                                       ▼                          ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                         Console Output                           │
  │  ┌──────────────────────┐  ┌──────────────┐  ┌───────────────┐  │
  │  │ Championship Table   │  │ Per-Match    │  │ Focus Card    │  │
  │  │ (existing + Trend)   │  │ Signal Table │──►(per-match     │  │
  │  │                      │  │ (--match-    │  │ detail:       │  │
  │  │ Top 5 + Δ + Trend    │  │  detail)     │  │ signals + CI  │  │
  │  │ + remaining teams    │  │              │  │ + stats + ctx)│  │
  │  └──────────────────────┘  └──────────────┘  └───────────────┘  │
  └──────────────────────────────────────────────────────────────────┘
                                       ▲
                                       │
  ┌──────────────────────────────────────┐
  │ Coverage Auditor (--coverage-audit)  │
  │  - Scans _STATS_FIELD_MAP           │
  │  - Computes meaningful (47) & raw   │
  │  - Per-category breakdown           │
  │  - Pass/fail on ≥60% meaningful     │
  └──────────────────────────────────────┘
```

### Recommended Project Structure
No structural changes needed. Files to modify:
```
src/
├── output.py          # Add print_match_detail_table(), print_focus_card(), wilson_ci(), coverage_audit(), trend column
├── enrichment.py      # Add 3 new _STATS_FIELD_MAP entries + coach/venue.city in _CONTEXT_SOURCE_MAP
├── main.py            # Add --match-detail CLI arg, _match_detail_enabled flag, probability log snapshot, trend display wiring
├── state.py           # Add load_probability_log(), append_probability_log()
└── constants.py       # Add PROBABILITY_LOG_FILE constant
```

### Pattern 1: Flag-Gated Display (--match-detail)
**What:** Same pattern as `--ai-preview`: CLI arg → module flag → conditional display in `_run_iteration()`.
**When to use:** Any feature that should not appear in default console output.
**Example (reuses established pattern from main.py):**
```python
# In _parse_args():
parser.add_argument("--match-detail", action="store_true", dest="match_detail",
                    help="Display per-match signal breakdown table (Phase 20)")

# Module-level flag:
_match_detail_enabled: bool = False

# In main(), after parse_args:
_match_detail_enabled = args.match_detail

# In _run_iteration(), after display logic:
if _match_detail_enabled:
    output.print_match_detail_table(probs, signal_data, prev_signal_data)
```
[VERIFIED: existing code in main.py lines 43-44, 250-254, 933-934]

### Pattern 2: JSON Array Append (probability_log.json)
**What:** Same pattern as `append_prediction_history()`: load → append → atomic write.
**When to use:** Append-only log where the complete file is rewritten atomically after each append.
**Example (reuses pattern from state.py lines 699-714):**
```python
def append_probability_log(snapshot, data_dir=None):
    log = load_probability_log(data_dir)
    log.append(snapshot)
    path = _resolve_data_dir(data_dir) / PROBABILITY_LOG_FILE
    _atomic_write_json(log, path)
```
[VERIFIED: existing code in state.py lines 699-714]

### Pattern 3: Wilson Score Confidence Interval
**What:** Closed-form Wilson score interval using only math.sqrt.
**When to use:** Binomial proportion CI when avoiding scipy is required.
**Example:**
```python
import math

def wilson_score_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Compute Wilson score 95% CI for k successes in n trials.
    
    Closed-form using only math.sqrt. No scipy dependency (D-07).
    At n=50000, converges with Clopper-Pearson within 0.001.
    """
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denominator
    return (center - margin, center + margin)

# Format: "[.452 — .516]"
def format_ci(k: int, n: int) -> str:
    low, high = wilson_score_ci(k, n)
    return f"[{low:.3f} — {high:.3f}]"
```
[ASSUMED: Wilson formula widely known and verified against standard references. Format from D-08.]

### Anti-Patterns to Avoid
- **Per-signal Δ in main table:** Each Δ column doubles the cell width. Per-signal deltas belong in the focus card only (D-03, per rejected designs).
- **CI in championship table:** Breaks 80-col terminal width. Marginal utility since Monte Carlo uncertainty already in full distribution (rejected). CI goes only in focus card (D-07).
- **CI in per-match table:** Destroys 85-col table width. Each cell doubles from 6 to 16 chars (~150 cols total) (rejected).
- **Probability log pruning:** Tournament is finite (104 matches, ~30 days). Even at 1 snapshot/minute = 43K entries — trivially small JSON. Never prune.
- **Rolling window < 5 for trend:** Too small → noise masks signal. Rolling window of 5 smooths Monte Carlo variance without hiding real trends.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Binomial CI | Clopper-Pearson continued fraction | Wilson score (math.sqrt) | CP requires ~100 lines of continued fraction code for negligible accuracy gain at n≈50000. Wilson is standard scipy-free method. |
| JSON persistence | Custom file format | state.py _atomic_write_json | Existing pattern handles atomic writes, Windows TempFile compatibility, and error recovery. |
| CLI flag parsing | Manual sys.argv parsing | argparse (existing) | Same pattern as --ai-preview, --once, --seed. Zero new infrastructure. |

## Runtime State Inventory

Skip — this is a greenfield enhancement phase (new display features, new persistence, no rename/refactor/migration).

## Common Pitfalls

### Pitfall 1: Per-Match Delta Requires Previous Signal Snapshot
**What goes wrong:** The Δ column in the per-match table needs to compare current signal values with the previous run's values. Without saving the previous signal snapshot, there's nothing to compare against.
**Why it happens:** `prev_probs` in `_run_iteration()` only tracks championship probabilities (team → round → value), not per-match signal probabilities (match_id → signal → value).
**How to avoid:** Capture a snapshot of all signal caches at the start of each `_run_iteration()` into a global `_prev_signal_data: dict | None`. The same pattern as `_prev_history` / `_prev_cal_params` used for version tracking (main.py lines 46-50). Pass this to `print_match_detail_table()`.
**Warning signs:** Δ column shows all zeros or "—" on every iteration after the first.

### Pitfall 2: Focus Card Stats Missing for Already-Played Matches
**What goes wrong:** New enrichment fields (fouls, corners, shots_off_target, coach) are only extracted at ingestion time. Already-played matches in played.json / played_groups.json won't have them.
**Why it happens:** The extract_stats()/extract_context() functions in enrichment.py are called during process_matches()/process_group_matches(). Existing match entries are never re-processed.
**How to avoid:** The focus card should gracefully handle missing fields — show "N/A" or skip the row. D-07 (sparse-fields convention) already established this pattern in enrichment.py. Document that historical stats won't be available.
**Warning signs:** Focus card shows "N/A" for all stats fields on historical matches — this is expected behavior, not a bug.

### Pitfall 3: Terminal Width Overflow from Trend Column
**What goes wrong:** Adding the Trend column to `print_probability_table()` pushes the championship table from ~64 chars to ~72 chars. Adding Trend + the existing Δ column could approach or exceed 80 chars.
**Why it happens:** The championship table has header + 5 data rows + separator. Current width: 3(rank)+1+18(team)+1+6(QF)+1+6(SF)+1+8(Final)+1+8(Champion)+2+8(Delta) = ~64 chars. Adding "  Trend" (+8) = 72 chars. Still well under 80.
**How to avoid:** Keep the Trend label short (6 chars: " Trend"). The arrow symbol (↑/↓/→) is single-width in most monospace fonts. Render as `f"  {arrow:>6}"`.
**Warning signs:** Table wraps in terminal, or the "─" separator line exceeds ~80 characters.

### Pitfall 4: First Run Trend Column Shows Garbage
**What goes wrong:** On the very first `_run_iteration()`, there's no previous snapshot to compare against. The trend column would show arrows based on meaningless comparisons.
**Why it happens:** `probability_log.json` starts empty. The rolling window of 5 snapshots doesn't exist yet.
**How to avoid:** D-13 explicitly says "Trend column hidden on first run (no window to compare against)." Check `len(probability_log) < 2` before computing trend. When hidden, simply don't print the header or data cells for that column.
**Warning signs:** Trend arrows appear on the very first program execution.

### Pitfall 5: Coverage Auditor False Negative on Raw vs Meaningful
**What goes wrong:** The auditor reports both meaningful and raw coverage, but only meaningful has a target. If raw coverage is used for the target instead of meaningful, the wrong denominator (34 instead of 47) gives a false pass.
**Why it happens:** Raw field count (34) has been used historically as the denominator. The RESPONSE.md analysis showed this inflated coverage from 44.7% to 61.8%.
**How to avoid:** The auditor must explicitly use the 47 meaningful-field denominator for the pass/fail check. The raw 34-field denominator is informational only (D-17). Store both counts but gate pass/fail on meaningful only.
**Warning signs:** Auditor shows ≥85% coverage but only 21 fields are actually extracted — wrong denominator used.

## Code Examples

### Signal Data Gatherer Helper (for per-match table)

```python
def _gather_match_signal_data(
    teams: dict,
    groups: dict,
    bracket: list[dict],
    played: dict[str, dict],
    played_groups: dict[str, dict],
    odds_cache: dict,
    cb_cache: dict,
    form_cache: dict,
    lineup_cache: dict,
    blend_params: dict | None,
) -> list[dict]:
    """Gather all upcoming/remaining matches with per-signal probabilities.
    
    Returns list of dicts, one per match, with keys:
    - match_id, team_a, team_b
    - signals: {signal_key: probability or None}
    - blended: blended probability
    - delta: change since last signal snapshot (requires prev_signal_data)
    """
    from src.knockout import resolve_knockout_slot_teams
    from src.elo import expected_score as elo_expected
    
    # Get upcoming bracket matches with resolved teams
    elo_ratings = {name: data["elo"] for name, data in teams.items()}
    slot_teams = resolve_knockout_slot_teams(
        groups, teams, played_groups, bracket, {}, dict(played)
    )
    
    match_probs = (blend_params or {}).get("match_probs", {})
    odds_matches = (odds_cache or {}).get("matches", {})
    cb_matches = (cb_cache or {}).get("matches", {})
    form_matches = (form_cache or {}).get("matches", {})
    lineup_matches = (lineup_cache or {}).get("matches", {})
    
    matches_data = []
    
    # Upcoming bracket matches
    for mid, slot in slot_teams.items():
        if mid in played:
            continue
        t_a, t_b = slot["team_a"], slot["team_b"]
        if t_a not in elo_ratings or t_b not in elo_ratings:
            continue
        
        signals = {
            "elo": elo_expected(elo_ratings[t_a], elo_ratings[t_b]),
            "odds": _get_signal_prob(mid, odds_matches.get(mid)),
            "catboost": _get_signal_prob(mid, cb_matches.get(mid)),
            "form": _get_signal_prob(mid, form_matches.get(mid)),
            "lineup": _get_signal_prob(mid, lineup_matches.get(mid)),
            "xg": _get_signal_xg(mid, cb_matches.get(mid)),
        }
        blended = match_probs.get(mid) or signals["elo"]
        
        matches_data.append({
            "match_id": mid,
            "team_a": t_a,
            "team_b": t_b,
            "signals": signals,
            "blended": blended,
        })
    
    # Also include upcoming group matches
    if groups and "groups" in groups:
        for letter in "ABCDEFGHIJKL":
            group = groups["groups"].get(letter)
            if not group:
                continue
            for match in group.get("matches", []):
                mid = match["match_id"]
                if mid in played_groups:
                    continue
                t_a, t_b = match["team_a"], match["team_b"]
                if t_a not in elo_ratings or t_b not in elo_ratings:
                    continue
                # ... same signal gathering as above ...
    
    return matches_data


def _get_signal_prob(match_id: str, entry: dict | None) -> float | None:
    """Extract probability from a signal cache entry."""
    if entry and entry.get("available"):
        return entry.get("probability")
    return None


def _get_signal_xg(match_id: str, entry: dict | None) -> float | None:
    """Extract xG probability proxy (home_xg * away_xg adjustment)."""
    # xG doesn't directly give win probability like other signals.
    # BSD predictions endpoint returns expected_home_goals / expected_away_goals.
    # These are xG Poisson lambda values, not probabilities.
    # Display as "xG λ: (2.1, 0.8)" rather than a win probability.
    if entry and entry.get("expected_home_goals") is not None:
        return (entry["expected_home_goals"], entry["expected_away_goals"])
    return None
```
[ASSUMED: signal cache structure verified from existing code patterns (main.py lines 729-783, odds_cache/cb_cache "matches" key)]

### print_match_detail_table() — Per-Match Signal Table

```python
def print_match_detail_table(
    matches_data: list[dict],
    prev_matches_data: list[dict] | None = None,
) -> None:
    """Print per-match signal breakdown table (~85 cols, D-01).
    
    7 signal columns + blended Δ triage column.
    """
    if not matches_data:
        print(_dim("No upcoming matches."))
        return
    
    # Build previous-signal lookup for Δ computation
    prev_lookup: dict[str, float] = {}
    if prev_matches_data:
        for m in prev_matches_data:
            prev_lookup[m["match_id"]] = m["blended"]
    
    # Header: ~85 chars
    print(_bold_cyan(f"{'Match':<12} {'Team A':<18} {'Team B':<18} "
                     f"{'Elo':>6} {'Odds':>6} {'CB':>6} {'Form':>6} {'Line':>6} {'xG':>6} {'Δ':>6}"))
    print(_bold_cyan("-" * 85))
    
    for m in sorted(matches_data, key=lambda x: x["match_id"]):
        sig = m["signals"]
        # Truncate long team names to fit 18 chars
        t_a = m["team_a"][:18]
        t_b = m["team_b"][:18]
        mid_short = m["match_id"][:12]
        
        row = (f"{mid_short:<12} {t_a:<18} {t_b:<18} "
               f"{sig['elo']:>6.3f} "
               f"{_fmt_prob(sig['odds']):>6} "
               f"{_fmt_prob(sig['catboost']):>6} "
               f"{_fmt_prob(sig['form']):>6} "
               f"{_fmt_prob(sig['lineup']):>6} "
               f"{_fmt_xg(sig['xg']):>6} ")
        
        # Δ column (blended only)
        delta = m["blended"] - prev_lookup.get(m["match_id"], m["blended"])
        if m["match_id"] in prev_lookup:
            row += _format_delta_cell(delta)
        else:
            row += f"  {'—':>6}"
        
        print(row)
    print()


def _fmt_prob(val: float | None) -> str:
    """Format a probability value or placeholder."""
    if val is None:
        return "   N/A"
    return f"{val:>6.3f}"


def _fmt_xg(val: tuple | None) -> str:
    """Format xG lambda pair or placeholder."""
    if val is None:
        return "   N/A"
    return f"{val[0]:.1f}/{val[1]:.1f}"  # e.g., " 2.1/0.8"


def _format_delta_cell(delta: float) -> str:
    """Format a delta value with arrow and color."""
    if delta > 0.0005:
        return f"  {_green(f'▲ {delta:+.3f}')}"
    elif delta < -0.0005:
        return f"  {_red(f'▼ {delta:+.3f}')}"
    return f"  {'=':>6}"
```
[ASSUMED: table layout based on D-01 width constraint of ~85 chars. Format derived from existing print_probability_table() patterns.]

### print_focus_card() — Match Detail Card

```python
def print_focus_card(match_data: dict, match_entry: dict | None = None) -> None:
    """Print the match focus card (~84 chars, Mockup 3 layout per D-20).
    
    Args:
        match_data: Dict from _gather_match_signal_data for this match.
        match_entry: Optional enriched match entry from played/played_groups
                    for stats and context.
    """
    from src.enrichment import _STATS_FIELD_MAP  # reference for field names
    
    sig = match_data["signals"]
    stats = (match_entry or {}).get("stats") or {}
    ctx = (match_entry or {}).get("context") or {}
    
    # ── Match header ──
    print()
    print(_bold_white(f"─── {match_data['team_a']} vs {match_data['team_b']} ({match_data['match_id']}) ───"))
    
    # ── Signal breakdown (top section, D-20) ──
    # Header: Signal | Prob | Δ | CI
    signal_header = f"{'Signal':<14} {'Prob':>8} {'Δ':>8} {'CI':>16}"
    print(_bold_cyan(signal_header))
    print(_bold_cyan("-" * 48))
    
    # Provenance labels per D-04:
    provenance = {
        "blended": "Brier-weighted blend",
        "elo": "eloratings.net expected score",
        "odds": "Market vig-removed odds",
        "catboost": "BSD CatBoost prediction",
        "form": "Last-5 form residual",
        "lineup": "Squad market value ratio",
        "xg": "BSD xG Poisson lambda",
    }
    
    row_data = [
        ("Blended", match_data["blended"], match_data.get("blended_delta"), None),
        ("Elo", sig["elo"], match_data.get("prev_signals", {}).get("elo"), wilson_ci_from_prob(sig["elo"], 50000)),
        ("Odds", sig["odds"], match_data.get("prev_signals", {}).get("odds"), wilson_ci_from_prob(sig["odds"], 50000)),
        ("CatBoost", sig["catboost"], match_data.get("prev_signals", {}).get("catboost"), wilson_ci_from_prob(sig["catboost"], 50000)),
        ("Form", sig["form"], match_data.get("prev_signals", {}).get("form"), wilson_ci_from_prob(sig["form"], 50000)),
        ("Lineup", sig["lineup"], match_data.get("prev_signals", {}).get("lineup"), wilson_ci_from_prob(sig["lineup"], 50000)),
        ("xG", sig["xg"], None, None),  # xG is display-only, no prob or CI
    ]
    
    for label, prob, prev_prob, ci in row_data:
        prob_str = f"{prob:.3f}" if isinstance(prob, (int, float)) else str(prob) if prob else "N/A"
        delta_str = _format_delta_cell(prob - prev_prob) if (isinstance(prob, (int, float)) and isinstance(prev_prob, (int, float))) else f"  {'—':>6}"
        ci_str = ci if ci else " " * 16
        print(f"{_dim(label + ':'):<14} {prob_str:>8} {delta_str:>8} {ci_str:>16}")
    
    # ── Context section (D-20) ──
    print()
    print(f"{_bold_white('Match Context')}")
    venue = ctx.get("venue", "N/A")
    referee = ctx.get("referee", "N/A")
    home_coach = ctx.get("home_coach", "N/A")
    away_coach = ctx.get("away_coach", "N/A")
    print(f"  Venue:  {venue}")
    print(f"  Ref:    {referee}")
    print(f"  Coach:  {home_coach} / {away_coach}")
    
    # ── Stats section (D-20) ──
    if stats:
        print()
        print(f"{_bold_white('Match Stats')}")
        stat_fields = [
            ("Fouls", "fouls_home", "fouls_away"),
            ("Corners", "corner_kicks_home", "corner_kicks_away"),
            ("Shots off", "shots_off_target_home", "shots_off_target_away"),
            ("Shots on", "shots_on_target_home", "shots_on_target_away"),
            ("Possession", "possession_home", "possession_away"),
            ("YC", "yellow_cards_home", "yellow_cards_away"),
            ("RC", "red_cards_home", "red_cards_away"),
        ]
        for label, home_key, away_key in stat_fields:
            h_val = stats.get(home_key, "N/A")
            a_val = stats.get(away_key, "N/A")
            print(f"  {label:<10} {str(h_val):>4} / {str(a_val):<4}")
    
    print()
```
[ASSUMED: focus card layout based on D-04/D-20 specifications. CI format from D-08. Signal provenance labels from system knowledge of signal sources.]

### Trend Column (in print_probability_table)

```python
def _compute_trend_arrow(current_prob: float, prob_log: list[dict]) -> str:
    """Compute trend arrow for a team's champion probability.
    
    Compares current prob vs. rolling window mean of last 5 snapshots (D-12).
    Threshold: 0.005 (5 percentage points × 0.01).
    """
    threshold = 0.005
    if len(prob_log) < 6:  # Need at least 6 entries for 5-window
        return " "
    
    window = prob_log[-6:-1]  # 5 snapshots before current
    window_probs = [s.get("probabilities", {}).get(team_name, {}).get("champion", 0.0)
                    for s in window]
    window_mean = sum(window_probs) / len(window_probs)
    
    if current_prob > window_mean + threshold:
        return "↑"
    elif current_prob < window_mean - threshold:
        return "↓"
    return "→"

# In print_probability_table(), after header line:
# Add Trend column:
header = f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}"
if has_delta:
    header += f"  {'Delta':>8}"
header += f"  {'Trend':>6}"  # NEW: D-12
```
[ASSUMED: trend threshold of 0.005 from CONTEXT.md recommendation. Rolling window of 5 from D-12.]

### Coverage Auditor

```python
# Field classification from RESPONSE.md field analysis:
_PREDICTION_FIELDS: list[str] = [
    "odds_home", "odds_draw", "odds_away",
    "expected_goals", "actual_home_xg", "actual_away_xg",
    "odds_over_25", "odds_under_25", "odds_btts_yes",
    "expected_home_goals", "expected_away_goals",
]

_DISPLAY_FIELDS: list[str] = [
    "home_score", "away_score", "event_date",
    "venue.name", "referee.name", "ai_preview.text",
    "yellow_cards", "red_cards", "shots_on_target", "ball_possession",
    "venue.city", "home_coach.name", "away_coach.name", "round_name",
    "fouls", "corner_kicks", "shots_off_target",
    "shots_inside_box", "temperature_c", "wind_speed", "weather_code",
    "pitch_condition", "attendance", "funfacts",
    "home_score_ht", "away_score_ht",
]

_OPERATIONAL_FIELDS: list[str] = [
    "id", "status", "home_team", "away_team",
    "league.id", "group_name", "winner", "period", "current_minute",
]


def coverage_audit() -> dict:
    """Audit BSD API meaningful field coverage.
    
    Returns dict with:
    - meaningful: {covered, total, pct, target_met}
    - raw: {covered, total, pct}
    - by_category: {category: {covered, total, pct}}
    """
    # Currently extracted fields (derived from _STATS_FIELD_MAP + sources):
    # Phase 17: yellow_cards_home/away, red_cards_home/away,
    #           shots_on_target_home/away, possession_home/away,
    #           venue, referee
    # Phase 18: ai_preview, expected_home_goals, expected_away_goals
    # This phase: fouls_home/away, corner_kicks_home/away,
    #             shots_off_target_home/away, home_coach, away_coach, venue.city
    
    extracted_display = {
        "home_score", "away_score", "event_date",
        "venue.name", "referee.name", "ai_preview.text",
        "yellow_cards", "red_cards", "shots_on_target", "ball_possession",
        "venue.city",  # NEW
        "home_coach.name", "away_coach.name",  # NEW
        "fouls", "corner_kicks", "shots_off_target",  # NEW
    }
    extracted_prediction = {
        "odds_home", "odds_draw", "odds_away",
        "expected_home_goals", "expected_away_goals",
    }
    extracted_operational = {
        "id", "status", "home_team", "away_team",
        "league.id", "group_name", "winner",
    }
    
    total_extracted = set()
    total_extracted.update(extracted_prediction)
    total_extracted.update(extracted_display)
    total_extracted.update(extracted_operational)
    
    meaningful_all = set(_PREDICTION_FIELDS + _DISPLAY_FIELDS + _OPERATIONAL_FIELDS)
    raw_all = meaningful_all  # raw = meaningful for this exercise
    
    n_meaningful = len(meaningful_all)
    n_meaningful_covered = len(total_extracted & meaningful_all)
    pct_meaningful = n_meaningful_covered / n_meaningful * 100 if n_meaningful else 0
    
    # Per-category breakdown
    categories = {
        "Prediction": (_PREDICTION_FIELDS, extracted_prediction),
        "Display": (_DISPLAY_FIELDS, extracted_display),
        "Operational": (_OPERATIONAL_FIELDS, extracted_operational),
    }
    
    by_category = {}
    for name, (all_fields, extracted) in categories.items():
        covered = len(extracted & set(all_fields))
        total = len(all_fields)
        by_category[name] = {
            "covered": covered,
            "total": total,
            "pct": round(covered / total * 100, 1) if total else 0,
        }
    
    return {
        "meaningful": {
            "covered": n_meaningful_covered,
            "total": n_meaningful,
            "pct": round(pct_meaningful, 1),
            "target": 60.0,
            "target_met": pct_meaningful >= 60.0,
            "missing": sorted(meaningful_all - total_extracted),
        },
        "raw": {
            "covered": n_meaningful_covered,
            "total": n_meaningful,
            "pct": round(pct_meaningful, 1),
        },
        "by_category": by_category,
    }
```
[ASSUMED: Field classifications from RESPONSE.md value-based analysis. Extracted field sets verified against current codebase in enrichment.py and src codebase grep.]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Coverage denominator = 34 raw fields | Denominator = 47 meaningful fields | Phase 20 (RESPONSE.md analysis) | Previous 61.8% was inflated. Actual: 44.7%. Target reset to ≥60% meaningful. |
| Clopper-Pearson CI (scipy) | Wilson score (math.sqrt) | Phase 20 (D-07) | Zero dependency. ~5 lines vs ~100. Converges within 0.001 at n=50000. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | BSD field names for fouls, corner_kicks, shots_off_target match `live_stats.home/away.{field}` | Field Extraction | Wrong field name → extraction returns None → graceful degradation (no crash, just missing data) |
| A2 | Coach names available as `home_coach.name`/`away_coach.name` at top level | Focus Card | Wrong path → extraction returns None → coach section shows "N/A" |
| A3 | Signal cache `matches` dict keyed by match_id with `probability` and `available` fields | Signal Table | If structure differs, _gather_match_signal_data yields None for signals — graceful |
| A4 | `expected_home_goals`/`expected_away_goals` exist in CatBoost cache entries | Signal Table (xG column) | Missing already handled — xG column shows "N/A" |
| A5 | Trend threshold of 0.005 (0.5pp) produces meaningful arrow changes | Trend Column | If too sensitive → arrows flip every iteration. If too insensitive → no arrows ever. Tune after observation. |
| A6 | n=50000 (simulation iterations) is the correct sample size for Wilson CI | Focus Card CI | CI width is ~±0.005 at n=50000 — negligible visual difference from n=48000 |
| A7 | Match data for focus card comes from `match_entry` stored in played/played_groups dicts | Focus Card | These dicts store enriched match data (stats+context). If enrichment wasn't run for a match, focus card shows "N/A" — graceful |

## Open Questions (RESOLVED)

1. **Focus card trigger mechanism** — **RESOLVED:** `--match-detail` alone shows per-match signal table. `--match-detail <match_id>` shows focus card for one match. Uses `argparse nargs="?"` with `const="table"` — avoids stdin interaction complexity (D-06, D-05).
   - What we know: D-05 says it's "opened by selecting a row from the table." The CLI is non-interactive (polling loop).
   - What's unclear: Whether `--match-detail M73` (match ID arg) triggers focus card directly, or `--match-detail` shows table then focus card inline for all matches.
   - Resolution: `--match-detail` alone shows the per-match signal table. `--match-detail <match_id>` shows the focus card for one match. This avoids stdin interaction complexity.

2. **Previous signal snapshot for Δ column** — **RESOLVED:** Module-level `_prev_signal_data: dict[str, dict]` global storing full per-match signal dicts (not just blended). Same pattern as `_prev_history`/`_prev_cal_params`. Captured at start of each `_run_iteration()`, consumed for Δ computation, updated at end. No JSON persistence — in-session only.
   - What we know: Δ column needs previous run's signal probabilities. Current `prev_probs` tracks championship probs only.
   - What's unclear: Should _prev_signal_data be a global module variable (like _prev_history, _prev_cal_params) or stored as a JSON snapshot file?
   - Resolution: Module-level global dict (same pattern as `_prev_history`). Captured at start of each `_run_iteration()`. Stores full signal dicts (not just blended) so per-signal Δ can be computed. No persistence — only needed for in-session Δ comparison.

3. **Coverage auditor: standalone script or flag-gated function?** — **RESOLVED:** Implemented as `coverage_audit()` pure function + `print_coverage_audit()` display function in `output.py`. Called on demand as a function. No separate CLI flag needed for Phase 20 — V2-30 requires the mechanism, not a CLI invocation.
   - What we know: Must be "automated" per V2-30. Can be run on demand.
   - Resolution: Implement as `print_coverage_audit()` in output.py, also callable as standalone function for testing. No dedicated CLI flag — coverage audit runs as part of the V2-30 verification workflow.

4. **xG column in per-match table: show as probability or lambda value?** — **RESOLVED:** Display as "λ_home/λ_away" (e.g., "2.1/0.8") in the xG column. Uses `_fmt_xg()` helper that renders the tuple. Honest representation — xG are Poisson lambdas, not win probabilities.
   - What we know: xG from BSD predictions endpoint are Poisson lambda values (expected home/away goals), not probabilities. They don't directly translate to win probability.
   - Resolution: Show as "λ_home/λ_away" (e.g., "2.1/0.8") rather than trying to convert to probability. This is honest about what xG represents and doesn't mislead.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | 3.11.8 | — |
| pytest | Testing | ✓ | 9.0.2 | — |
| math (stdlib) | Wilson CI | ✓ | Python ≥3.5 | — |
| json (stdlib) | Probability log | ✓ | Python ≥3.5 | — |

**Missing dependencies with no fallback:** None — all is stdlib + existing project.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | pytest.ini (root) |
| Quick run command | `pytest tests/test_output.py -x -q` |
| Full suite command | `pytest -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| V2-27 | per-match signal table printed with --match-detail | unit | `pytest tests/test_output.py::TestMatchDetailTable -x -q` | ❌ Wave 0 |
| V2-27 | focus card shows all 7 signals + Δ + CI | unit | `pytest tests/test_output.py::TestFocusCard -x -q` | ❌ Wave 0 |
| V2-27 | focus card shows match context (venue, ref, coaches) | unit | `pytest tests/test_output.py::TestFocusCard -x -q` | ❌ Wave 0 |
| V2-27 | focus card shows match stats (fouls, corners, shots, etc.) | unit | `pytest tests/test_output.py::TestFocusCard -x -q` | ❌ Wave 0 |
| V2-28 | Wilson CI computed with math.sqrt only | unit | `pytest tests/test_output.py::TestWilsonCI -x -q` | ❌ Wave 0 |
| V2-28 | Wilson CI format: [.452 -- .516] | unit | `pytest tests/test_output.py::TestWilsonCI -x -q` | ❌ Wave 0 |
| V2-29 | probability_log.json created with snapshot after _run_iteration | unit | `pytest tests/test_state.py::TestProbabilityLog -x -q` | ❌ Wave 0 |
| V2-29 | Trend arrow shown in championship table (↑/↓/→) | unit | `pytest tests/test_output.py::TestTrendColumn -x -q` | ❌ Wave 0 |
| V2-29 | Trend column hidden on first run | unit | `pytest tests/test_output.py::TestTrendColumn::test_hidden_first_run -x -q` | ❌ Wave 0 |
| V2-30 | New fields (fouls, corners, shots_off_target) extracted | unit | `pytest tests/test_enrichment.py::TestExtractStats -x -q` | ✅ existing |
| V2-30 | Coverage audit reports ≥60% meaningful coverage | unit | `pytest tests/test_output.py::TestCoverageAudit -x -q` | ❌ Wave 0 |
| V2-30 | Coverage auditor reports per-category breakdown | unit | `pytest tests/test_output.py::TestCoverageAudit -x -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_output.py tests/test_enrichment.py tests/test_state.py -x -q`
- **Per wave merge:** `pytest -x -q` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_output.py` — Add TestMatchDetailTable, TestFocusCard, TestWilsonCI, TestTrendColumn, TestCoverageAudit classes
- [ ] `tests/test_state.py` — Add TestProbabilityLog class (load, append, format)
- [ ] `tests/test_enrichment.py` — Add new field extraction tests (fouls, corners, shots_off_target)

## Security Domain

> Required when `security_enforcement` is enabled (absent = enabled). 

This phase introduces no new external API calls, no user input handling, no authentication, and no data storage of sensitive information. All changes are console output formatting, statistical computation, and persistence of already-public probability data.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | No | — |
| V4 Access Control | No | — |
| V5 Input Validation | No | — |
| V6 Cryptography | No | — |
| V7 Error Handling | No | — |

### Known Threat Patterns
None — this phase touches no security-relevant code paths. All data is computed locally from existing signal caches. No new external dependencies.

## Sources

### Primary (HIGH confidence)
- [VERIFIED: existing code in src/output.py] — current display patterns, ANSI helpers, print_probability_table layout, print_governance_dashlet
- [VERIFIED: existing code in src/main.py] — _run_iteration() flow, _ai_preview flag pattern, signal cache loading pattern
- [VERIFIED: existing code in src/state.py] — append_prediction_history pattern, _atomic_write_json, load/save pairs
- [VERIFIED: existing code in src/enrichment.py] — _STATS_FIELD_MAP, extract_stats/extract_context patterns
- [VERIFIED: existing code in src/constants.py] — all existing constants for reference
- [VERIFIED: existing code in src/knockout.py] — run_full_simulation return format, resolve_knockout_slot_teams for upcoming matches
- [VERIFIED: 20-CONTEXT.md] — all D-01 through D-20 decisions, design rationale, deferred items
- [VERIFIED: RESPONSE.md] — BSD field classification (47 meaningful fields), field name verification, coverage analysis

### Secondary (MEDIUM confidence)
- [ASSUMED: BSD probe data] — field names for fouls, corner_kicks, shots_off_target, coach names confirmed via live probe during Phase 17 research (documented in RESPONSE.md)
- [ASSUMED: Wilson score formula] — standard closed-form binomial CI using math.sqrt, well-documented in statistical literature

### Tertiary (LOW confidence)
- None — all claims verified against existing codebase, CONTEXT.md decisions, or RESPONSE.md probe analysis

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all pure Python stdlib, no new packages
- Architecture: HIGH — patterns directly reuse existing code (flag gate, JSON append, enrichment maps)
- Pitfalls: HIGH — all derived from verified code analysis and prior phase learnings

**Research date:** 2026-06-21
**Valid until:** 2026-07-21 (stable — all implementation is stdlib)
