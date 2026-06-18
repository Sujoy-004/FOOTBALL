# Phase 10: Integration, Tests & BSD Verification - Research

**Researched:** 2026-06-14
**Domain:** BSD API group match ingestion, state persistence, console group standings, E2E testing
**Confidence:** HIGH

## Summary

Phase 10 connects the live BSD API data into the group stage simulation pipeline. Currently, `process_matches()` in `fetcher.py` processes only knockout matches (where `group_name` is null). Phase 10 adds `process_group_matches()` that handles BSD events with a non-null `group_name` field, persists them in a new `played_groups.json`, displays all 12 group standings with box-drawing characters and a third-place bubble cutoff indicator, and fixes two pre-existing test failures.

The existing codebase provides strong patterns to follow: `_atomic_write_json()` in `state.py:98` for file persistence, `MockResponse` in `test_fetcher.py:11` for API mocking, `_build_alias_lookup()` in `fetcher.py:129` for team normalization, and `_find_bracket_match()` in `fetcher.py:150` for slot resolution (mirror for group match lookup). The main integration point is `main.py:_run_iteration()` at line 82, which must load `played_groups`, pass it through `run_full_simulation()`, and call the new group standings display.

**Primary recommendation:** Implement as 4 plans: (1) Group match ingestion + `played_groups.json` persistence, (2) Group standings console display + third-place bubble, (3) Test fixes + E2E tests, (4) SOT batch update. The `simulate_group_matches()` function in `groups.py` currently does NOT skip played matches — it must be modified to accept a `played_groups` parameter and use real results instead of simulating them for matches in that dict.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Group match ingestion: post-fetch split by group_name field, 3-key resolution (group_name + round_number + team pair)
- Single BSD API call for all matches, played_groups.json persistence
- Group standings: all 12 groups every cycle, cols=Pos/Team/Pts/GD/GS, box-drawing chars
- Third-place bubble: show 8th+9th + cutoff margin
- Keep Elo proxy (close D-16)
- Two test fixes: "Fetched"→"Polling" and expected_goals cap assertion
- played_groups.json entry structure with match_id, team_a, team_b, winner, home_score, away_score, completed_at
- Dedup via BSD event `id` (in-memory set)
- Failure handling: log+skip for unmatchable teams, unfindable slots, invalid group_name, draws
- run_full_simulation() accepts played_groups param; simulate_group_matches() skips matches in it
- New load/save functions in state.py following _atomic_write_json pattern
- Initial played_groups.json created empty {} if not present
- Show ALL 12 groups every cycle
- Columns: Position, Team, Pts, GD, GS (no fair-play/Elo)
- Box-drawing characters for group table borders
- Compact 4-line block per group, 12 groups stacked vertically
- Third-place bubble showing 8th and 9th teams
- New matches re-print standings; hourly auto-refresh re-prints; heartbeat skips; startup placeholder
- New functions in output.py: print_group_standings(), print_third_place_bubble()
- New function in fetcher.py: process_group_matches()
- main.py _run_iteration() integration: load played_groups, pass to run_full_simulation

### the agent's Discretion
- Exact box-drawing character set (single vs double lines)
- Whether process_group_matches() lives in fetcher.py or new module (prefer fetcher.py)
- Exact ANSI color codes for third-place bubble (ADVANCES green, OUT red)
- Whether played_bsd_event_ids set is persisted across restarts (likely not needed)

### Deferred Ideas (OUT OF SCOPE)
- Real FIFA ranking data source (D-16 closed, Elo proxy kept)
- Historical fair play calibration per confederation
- Live WebSocket subscription
- BSD MCP server integration
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INTG-01 | BSD API polling detects and ingests group match results | `fetcher.py` has full pagination + retry pattern; `process_group_matches()` new function discriminates via `group_name` field; `_build_alias_lookup()` includes group team names; slot lookup mirrors `_find_bracket_match()` |
| INTG-02 | Group match results stored in separate `played_groups.json` | `state.py` `_atomic_write_json()` at line 98 provides reusable atomic write; `load_played_groups()`/`save_played_groups()` follow same pattern as `load_played()`/`save_played()` |
| INTG-03 | Console output displays 12 group standings tables | `output.py` has ANSI helper functions (`_bold_cyan`, `_green`, `_red`); `compute_standings()` in `groups.py:534` provides data; existing box-drawing at line 67 shows `─` works |
| INTG-04 | Console output shows third-place bubble | `rank_third_placed()` in `groups.py:642` provides the sorted list; display picks indices 7 and 8 (8th and 9th) |
| INTG-05 | Console header updated for 48-team format | `print_header()` in `output.py:125` needs group count, third-place count added to banner |
| INTG-06 | All test fixtures updated for 48-team bracket | `conftest.py` fixtures are minimal and reusable; new `test_group_integration.py` needed |
| INTG-07 | E2E test with mock data through full 104-match pipeline | `test_fetcher.py:11` MockResponse pattern; `test_main_loop.py:14` `_runner_code()` subprocess pattern; `test_integration.py:17` tmp_path persistence pattern |
| INTG-08 | Live BSD smoke test with `--once` returning valid predictions | `main.py` `--once` at line 217 already supports this; `validate_api_key()` at line 158 validates BSD key; mark as manual test |
| INTG-09 | Fix two pre-existing test failures | `test_main_loop.py:122` change "Fetched"→"Polling"; `test_groups.py:59` change `> 10.0`→`== 8.0` |
| INTG-10 | All 7 SOTs batch-updated | SOTs at `SOTs/PRD.md`, `SOTs/TRD.md`, `SOTs/MVP.md`, `SOTs/Appflow.md`, `SOTs/Backend_Schema.md`, `SOTs/UI_UX_Design.md`, `SOTs/Implementation_plan.md` — plus `.planning/PROJECT.md`, `REQUIREMENTS.md`, `STATE.md`, `ROADMAP.md` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| BSD API fetch + pagination | API/Backend (fetcher.py) | — | HTTP calls, pagination loop already implemented |
| Group match discrimination | API/Backend (fetcher.py) | — | Post-fetch split by `group_name` field, no browser involved |
| Team name normalization | API/Backend (fetcher.py) | Data (aliases) | `_build_alias_lookup()` uses `team_aliases.json` + group team names |
| Group match slot resolution | API/Backend (fetcher.py) | Data (groups.json) | Lookup matches against groups.json structure |
| played_groups.json persistence | Database/Storage (state.py) | API/Backend | File I/O via `_atomic_write_json()`, same pattern as `played.json` |
| Group standings computation | Backend (groups.py) | — | `compute_standings()` + `rank_third_placed()` — pure computation |
| Group standings display | Console/CLI (output.py) | — | ANSI codes, box-drawing, terminal output |
| Third-place bubble display | Console/CLI (output.py) | Backend (groups.py) | Consumes `rank_third_placed()` output, highlights cutoff |
| Full pipeline orchestration | API/Backend (knockout.py) | — | `run_full_simulation()` orchestrates group→Annex C→knockout |
| E2E test infrastructure | Test | — | `MockResponse` + `_runner_code()` + `tmp_path` patterns |
| SOT batch update | Documentation | — | 7 SOT files + 4 .planning docs |

## Standard Stack

No new packages required for Phase 10. Everything uses the existing stack:

### Existing Stack
| Library | Version | Purpose |
|---------|---------|---------|
| Python | 3.11.8 | Runtime environment (verified) |
| pytest | 9.0.2 | Test framework (verified) |
| requests | (stdlib) | HTTP client for BSD API calls |
| python-dotenv | 1.x | API key loading from `.env` |

**No new installations needed.** Phase 10 is entirely code additions to existing modules.

## Architectural Patterns

### System Architecture Diagram

```
BSD API (GET /api/events/?status=finished&league_id=27)
    │
    ▼
fetch_raw_matches()  ──── pagination via next URL ────→ list of all finished events
    │
    ├── group_name is non-null ──→ process_group_matches()
    │       │                          │
    │       │                          ├── normalize teams (alias_lookup + group team names)
    │       │                          ├── resolve group letter (extract from group_name)
    │       │                          ├── resolve match slot (team pair match in groups.json)
    │       │                          ├── dedup check (BSD event id in-memory set + match_id in played_groups)
    │       │                          └── create entry {match_id, team_a, team_b, winner, ...}
    │       │
    │       ▼
    │   played_groups.json ←── state.save_played_groups()
    │
    └── group_name is null ──→ process_matches() (existing knockout flow)
                                    │
                                    ▼
                                played.json ←── state.save_played()
                                                    │
                                                    ▼
main.py: _run_iteration()
    │
    ├── load_played_groups() + load_played()
    ├── run_full_simulation(teams, groups, bracket, annex_c, played, played_groups)
    │       │
    │       ├── simulate_group_matches(groups, ..., played_groups=played_groups)
    │       │       │  (skips matches in played_groups, uses real results instead)
    │       │       ▼
    │       │   group match results dict
    │       │
    │       ├── compute_standings(results, elo_ratings)
    │       ├── rank_third_placed(standings)
    │       ├── select_advancers(standings, third_ranked)
    │       ├── resolve_r32_matchups(...)
    │       ├── _simulate_r32_resolved(...)  (played for knockout)
    │       └── _simulate_knockout rounds...
    │
    ├── print_group_standings(standings, third_place_rankings)       [NEW]
    │       └── box-drawing table, all 12 groups, compact 4-line blocks
    │
    ├── print_third_place_bubble(third_place_rankings)               [NEW]
    │       └── "8. Ghana 3 pts GD +0 ADVANCES  9. Panama 3 pts GD -2 OUT"
    │
    ├── print_probability_table(probs, prev_probs)
    └── print_delta_summary(probs, prev_probs)

Refresh behavior decision tree:
    ┌─ New group match ingested ──→ print full standings + bubble
    ├─ Hourly auto-refresh ───────→ print full standings + bubble
    ├─ Regular heartbeat ─────────→ skip (no output change)
    └─ First startup, 0 played ───→ print "(no group matches played yet)"
```

### Code Surface by Module

```
src/fetcher.py:
  + process_group_matches(raw_matches, teams, groups, aliases, played_group_ids, played_bsd_event_ids)
  + _build_group_alias_lookup(aliases, groups) — or extend existing _build_alias_lookup()
  + _find_group_match(home_norm, away_norm, group_letter, groups) — mirror _find_bracket_match()

src/state.py:
  + load_played_groups(data_dir) → dict  (bootstrap empty {} if FileNotFoundError)
  + save_played_groups(played_groups, data_dir) → None

src/output.py:
  + print_group_standings(standings, third_place_rankings) → None
  + print_third_place_bubble(third_place_rankings) → None

src/knockout.py:
  ~ run_full_simulation(..., played_groups={})  — add played_groups param

src/groups.py:
  ~ simulate_group_matches(..., played_groups={})  — add played_groups param, skip/inject

src/main.py:
  ~ _run_iteration() — load played_groups, pass to run_full_simulation, call display
  ~ main() — load played_groups initial state
  ~ print_header() — update for 48-team counts

tests/test_main_loop.py:
  ~ test_main_loop_runs_iterations — "Fetched" → "Polling"

tests/test_groups.py:
  ~ TestExpectedGoals.test_expected_goals_very_strong_dominates — fix assertion

tests/test_group_integration.py [NEW]:
  + test_process_group_matches_basic
  + test_process_group_matches_dedup
  + test_process_group_matches_unmatchable_team
  + test_played_groups_roundtrip
  + test_compute_standings_output_format
  + test_full_pipeline_with_group_matches
  + test_third_place_bubble_calculation
```

### Pattern 1: Group match slot resolution (mirror `_find_bracket_match`)
**What:** Look up which group match slot a BSD event corresponds to, using normalized team pair.
**When to use:** Every BSD event with a non-null `group_name` during ingestion.
**Example (code pattern to follow):**
```python
# Mirror of _find_bracket_match() at fetcher.py:150
def _find_group_match(home_norm: str, away_norm: str, group_letter: str, groups: dict) -> str | None:
    groups_data = groups.get("groups", groups)
    if group_letter not in groups_data:
        return None
    for match in groups_data[group_letter]["matches"]:
        if {match["team_a"], match["team_b"]} == {home_norm, away_norm}:
            return match["match_id"]
    return None
```
[ASSUMED] — follows established pattern in `fetcher.py:150-156`

### Pattern 2: State persistence with atomic write
**What:** Write JSON file atomically using tempfile + os.replace.
**When to use:** Every time `played_groups.json` is updated.
**Example (source: `state.py:98-131`):**
```python
def save_played_groups(played_groups: dict[str, dict], data_dir=None) -> None:
    path = _resolve_data_dir(data_dir) / "played_groups.json"
    _atomic_write_json(played_groups, path)
```
[VERIFIED: code at state.py:98-131]

### Pattern 3: Console group standings with box-drawing
**What:** Display all 12 groups in a compact table using ANSI + Unicode box-drawing.
**When to use:** After simulation, when new group matches ingested or hourly refresh.
**Example (data structure from `groups.py:534-636`):**
```python
# standings dict structure (from compute_standings):
# {"A": [{"team": "Mexico", "position": 1, "pts": 7, "gd": 3, "gs": 5}, ...], ...}

# Box-drawing table output:
# ┌─────────┬────────────────────┬───┬─────┬──────┐
# │ Group A │ Mexico (1)        │ 7 │  +3 │    5 │
# │         │ South Korea (2)   │ 7 │  +3 │    4 │
# │         │ South Africa (3)  │ 3 │  -2 │    2 │
# │         │ Czech Republic(4) │ 0 │  -4 │    1 │
# ├─────────┼────────────────────┼───┼─────┼──────┤
# ...
# └─────────┴────────────────────┴───┴─────┴──────┘
```
[ASSUMED] — user-approved layout from CONTEXT.md specifics section

### Anti-Patterns to Avoid
- **Mutating groups.json during simulation:** `simulate_group_matches()` must NOT modify the input `groups` dict. The current code (line 255-286) already avoids mutation by building a new `results` dict. Maintain this.
- **Blocking the poll loop on display:** Group standings display should be fast (pure string formatting, no I/O beyond print). Don't add API calls or file reads inside the display path.
- **Re-simulating played matches:** When `played_groups` has entries, `simulate_group_matches()` must skip those matches or inject real results — don't simulate then discard.

### State Flow Diagram

```
Startup:
  played_groups.json ─→ load_played_groups() ─→ dict (empty {} initially)

Each poll cycle:
  BSD API response
    → process_group_matches() filters group_name != null
    → resolves team names via alias_lookup + group team names
    → dedup: BSD event ID in-memory set + match_id in played_groups
    → new entries appended to played_groups dict
    → save_played_groups() writes atomically

Simulation:
  run_full_simulation(played_groups={...})
    → simulate_group_matches(played_groups={...})
    → for each match: if mid in played_groups, use real result; else simulate
    → compute_standings() consumes results (real + simulated together)

Display:
  print_group_standings(standings, third_place_rankings)
    → reads compute_standings output → formats box-drawing table
  print_third_place_bubble(third_place_rankings)
    → reads rank_third_placed() output → formats cutoff indicator
```

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| BSD API fetch + pagination | API/Backend (fetcher.py) | — | HTTP calls, pagination loop already implemented |
| Group match discrimination | API/Backend (fetcher.py) | — | Post-fetch split by `group_name` field |
| Team name normalization | API/Backend (fetcher.py) | Data (aliases) | `_build_alias_lookup()` + group team names |
| Group match slot resolution | API/Backend (fetcher.py) | Data (groups.json) | Lookup matches against groups.json structure |
| played_groups.json persistence | Database/Storage (state.py) | API/Backend | File I/O via `_atomic_write_json()`, same pattern as `played.json` |
| Group standings computation | Backend (groups.py) | — | `compute_standings()` + `rank_third_placed()` |
| Group standings display | Console/CLI (output.py) | — | ANSI codes, box-drawing, terminal output |
| Third-place bubble display | Console/CLI (output.py) | Backend (groups.py) | Consumes `rank_third_placed()` output |
| Full pipeline orchestration | Backend (knockout.py) | — | `run_full_simulation()` orchestrator |
| Integration testing | Test | — | `MockResponse` + `_runner_code()` + `tmp_path` |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON file write safety | Custom file.write() | `state.py:_atomic_write_json()` | Handles tempfile mkstemp, os.replace atomicity, Windows compatibility, cleanup on failure — full battle-tested pattern at `state.py:98-131` |
| Team name normalization | Custom normalization per phase | `fetcher.py:_normalize_team()` + `_build_alias_lookup()` | Already handles canonical→alias mapping, case-insensitive lookup, strip whitespace |
| HTTP retry + pagination | Custom retry logic | `fetcher.py:fetch_raw_matches()` | 3-attempt exponential backoff, pagination via next URL, 401/JSON error handling — exists and works |
| Poisson match simulation | Custom Monte Carlo | `groups.py:simulate_group_matches()` | Optimized with inverse-CDF tables, precomputed lambdas, 12.66s at 50K iterations |
| Bracket validation | Custom DAG checker | `state.py:validate_bracket()` | 3-color DFS cycle detection, reference integrity, uniqueness — reusable |

**Key insight:** Every non-trivial pattern Phase 10 needs already exists in the codebase. The implementation is primarily wiring — connecting existing infrastructure (fetch, persist, simulate, display) for group matches, which currently only supports knockout matches.

## Common Pitfalls

### Pitfall 1: `simulate_group_matches()` doesn't skip played matches
**What goes wrong:** The current `simulate_group_matches()` (groups.py:187-287) simulates ALL 72 matches every time, every iteration. It has NO `played_groups` parameter and NO logic to skip or override matches. If you inject `played_groups` at the `run_full_simulation()` level but don't forward it into `simulate_group_matches()`, the real group match results will be ignored.
**Root cause:** The existing code was built for pure simulation (no live data input) — it's an intentional omission that Phase 10 must fix.
**How to avoid:** Add `played_groups: dict[str, dict] = None` param to `simulate_group_matches()`. In the match loop (line 230-285), check `if played_groups and mid in played_groups: group_results[mid] = played_groups[mid]` (use real result) before the simulation block.
**Warning signs:** After ingesting a group match, the standings table doesn't show the correct result.

### Pitfall 2: Team alias lookup missing group team names
**What goes wrong:** `_build_alias_lookup()` at `fetcher.py:129` builds aliases from the bracket (knockout matches) and `team_aliases.json`. It does NOT include team names from groups.json. If a team appears only in the group stage (e.g., "South Africa"), its canonical name from `groups.json` might not be in the alias lookup.
**How to avoid:** Either (a) pass group team names into a modified `_build_alias_lookup()`, or (b) build a separate alias lookup in `process_group_matches()` that also includes `groups["groups"][letter]["teams"]` entries. Option (b) is cleaner — it keeps the existing knockout path untouched.
**Warning signs:** Group matches with unmatchable team names repeatedly logged as warnings despite the team being in `team_aliases.json`.

### Pitfall 3: Windows UTF-8 console encoding for box-drawing characters
**What goes wrong:** The box-drawing characters (`│ ─ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼`) are Unicode U+2500-U+2530 range. On Windows, the console defaults to cp437/cp850 which cannot render these. Python reconfigures stdout at `output.py:14-15` (`sys.stdout.reconfigure(encoding="utf-8")`), but the Windows Console Host also requires `os.system("")` at `main.py:195` for ANSI escape processing.
**How to avoid:** The existing setup at `main.py:194-195` already calls `os.system("")` on Windows to enable ANSI processing. The `sys.stdout.reconfigure(encoding="utf-8")` at `output.py:14-15` handles encoding. Also set the codepage explicitly for box-drawing: `subprocess.run(["chcp", "65001"], shell=True)` or rely on Python 3.11+'s improved UTF-8 console support. Test on Windows Terminal (most reliable) and legacy Console Host (may show placeholder chars).
**Warning signs:** Console shows `|`, `-`, `+` instead of `│`, `─`, `┼` — indicates the codepage doesn't support Unicode box-drawing.

### Pitfall 4: Hourly re-sim path bypasses group match ingestion
**What goes wrong:** The hourly auto-refresh path at `main.py:108-112` calls `run_full_simulation()` directly without fetching from the BSD API. If new group matches were played but undetected (e.g., API was down during the last poll), the hourly refresh won't catch them because it never calls `fetch_raw_matches()`.
**How to avoid:** The hourly re-sim should at minimum use the current `played_groups` data — which it will, since `run_full_simulation()` will receive the current `played_groups` dict. No API call is made, but already-ingested group matches are still included. Document that hourly re-sim only uses data already in `played_groups.json` — it's a re-simulation, not a catch-up fetch.
**Warning signs:** Old group standings displayed during hourly refresh despite matches finishing while the script was in heartbeat mode.

### Pitfall 5: played_groups.json bootstrap on first run
**What goes wrong:** If `load_played_groups()` raises `FileNotFoundError` on first startup (file doesn't exist yet), the script crashes before any matches are played.
**How to avoid:** Follow D-09: catch `FileNotFoundError` and return empty dict `{}`. Pattern is already used implicitly — just wrap the `open()` in a try/except or use `path.exists()` check: `return json.load(f) if path.exists() else {}`.
**Warning signs:** Script crashes on first startup with `FileNotFoundError: played_groups.json`.

## Code Examples

### Group match ingestion (process_group_matches implementation pattern)
```python
# Pattern for process_group_matches() in fetcher.py
# Source: derived from process_matches() at fetcher.py:73-126

def process_group_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    groups: dict,
    aliases: dict[str, list[str]],
    played_group_ids: set[str],
    played_bsd_event_ids: set[str],
) -> list[dict]:
    # Build alias lookup that also includes all group team names
    alias_lookup = _build_alias_lookup(aliases, [])  # empty bracket for knockout
    groups_data = groups.get("groups", groups)
    for group_data in groups_data.values():
        for team in group_data["teams"]:
            alias_lookup[team.strip().lower()] = team
    
    results: list[dict] = []
    
    for match in raw_matches:
        if match.get("status") != "finished":
            continue
        
        group_name = match.get("group_name")
        if group_name is None:
            continue  # knockout match, handled by process_matches()
        
        # Dedup by BSD event id (session-level)
        bsd_id = str(match.get("id", ""))
        if bsd_id in played_bsd_event_ids:
            continue
        played_bsd_event_ids.add(bsd_id)
        
        # Extract group letter from "Group A" → "A"
        group_letter = _extract_group_letter(group_name)
        if group_letter is None:
            logger.warning("Invalid group_name: %r", group_name)
            continue
        
        # Normalize team names
        home_name = match.get("home_team", "")
        away_name = match.get("away_team", "")
        home_norm = _normalize_team(home_name, alias_lookup)
        away_norm = _normalize_team(away_name, alias_lookup)
        
        if home_norm is None or away_norm is None:
            logger.warning("Unmatchable team names: home=%r, away=%r", home_name, away_name)
            continue
        
        # Find group match slot
        match_id = _find_group_match(home_norm, away_norm, group_letter, groups)
        if match_id is None:
            logger.warning("No group match found for %s vs %s in group %s", home_norm, away_norm, group_letter)
            continue
        
        # Dedup by match_id (cross-restart)
        if match_id in played_group_ids:
            continue
        
        # Check for winner
        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)
        if home_score > away_score:
            winner = home_norm
        elif away_score > home_score:
            winner = away_norm
        else:
            continue  # Draw — skip (no winner)
        
        results.append({
            "match_id": match_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "home_score": home_score,
            "away_score": away_score,
            "completed_at": match.get("event_date", ""),
        })
    
    return results


def _extract_group_letter(group_name: str) -> str | None:
    """Extract group letter from 'Group A' → 'A'. Returns None if invalid."""
    if not group_name or not group_name.startswith("Group "):
        return None
    letter = group_name[6:7]  # "Group A" → "A"
    if letter not in "ABCDEFGHIJKL":
        return None
    return letter


def _find_group_match(home_norm: str, away_norm: str, group_letter: str, groups: dict) -> str | None:
    """Find group match_id by team pair. Mirror of _find_bracket_match() at fetcher.py:150."""
    groups_data = groups.get("groups", groups)
    if group_letter not in groups_data:
        return None
    for match in groups_data[group_letter]["matches"]:
        if {match["team_a"], match["team_b"]} == {home_norm, away_norm}:
            return match["match_id"]
    return None
```
[ASSUMED] — follows established patterns at `fetcher.py:73-126` and `fetcher.py:150-156`

### State persistence pattern
```python
# In state.py — follow load_played() at line 77 and _atomic_write_json() at line 98

def load_played_groups(data_dir: Path | str | None = None) -> dict[str, dict]:
    """Load played group matches from played_groups.json.
    Returns empty dict if file doesn't exist (graceful bootstrap)."""
    path = _resolve_data_dir(data_dir) / "played_groups.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_played_groups(played_groups: dict[str, dict], data_dir=None) -> None:
    """Save played group matches to played_groups.json atomically."""
    path = _resolve_data_dir(data_dir) / "played_groups.json"
    _atomic_write_json(played_groups, path)
```
[VERIFIED: code at state.py:77-92 and state.py:98-131]

### Simulate_group_matches modification
```python
# Modify simulate_group_matches() at groups.py:187 to accept played_groups

def simulate_group_matches(
    groups: dict,
    teams: dict[str, dict],
    elo_ratings: dict[str, float],
    rng: random.Random,
    fair_play: bool = True,
    matchup_lambdas: dict[str, tuple[float, float]] | None = None,
    played_groups: dict[str, dict] | None = None,  # NEW PARAM
) -> dict[str, dict[str, dict]]:
    # ... existing setup code ...
    played_groups = played_groups or {}
    
    results: dict[str, dict[str, dict]] = {}
    for group_letter, group_data in groups_data.items():
        group_results: dict[str, dict] = {}
        for match in group_data["matches"]:
            mid = match["match_id"]
            
            # NEW: Skip simulation for played matches
            if mid in played_groups:
                group_results[mid] = {
                    "team_a": played_groups[mid]["team_a"],
                    "team_b": played_groups[mid]["team_b"],
                    "score_a": played_groups[mid]["home_score"],
                    "score_b": played_groups[mid]["away_score"],
                    "winner": played_groups[mid]["winner"],
                    "yellow_cards_a": 0,
                    "red_cards_a": 0,
                    "yellow_cards_b": 0,
                    "red_cards_b": 0,
                }
                continue
            
            # ... existing simulation code ...
            # (lines 232-285 unchanged)
```
[ASSUMED] — parameter injection follows the same pattern as knockout's `_simulate_r32_resolved()` at `knockout.py:34-49`

### Group standings display
```python
# In output.py — pattern for box-drawing table

def print_group_standings(standings: dict, third_place_rankings: list) -> None:
    """Print all 12 group standings tables with box-drawing characters."""
    from src.constants import GROUP_COUNT  # = 12
    
    if not any(standings.values()):  # No groups have data yet
        print(f"{_timestamp()} {_bold_cyan('Group Standings:')}")
        print(f"  (no group matches played yet)")
        print()
        return
    
    print(f"{_timestamp()} {_bold_cyan(f'GROUP STANDINGS — {GROUP_COUNT} groups, best 8 third-placed advance')}")
    
    for i, group_letter in enumerate("ABCDEFGHIJKL"):
        if group_letter not in standings:
            continue
        
        group = standings[group_letter]
        
        # Group header row
        print(f"┌─────────┬────────────────────┬───┬─────┬──────┐")
        
        for entry in group:
            pos = entry["position"]
            team = entry["team"]
            pts = entry["pts"]
            gd = entry["gd"]
            gs = entry["gs"]
            gd_str = f"+{gd}" if gd > 0 else str(gd)
            
            if pos == 1:
                print(f"│ Group {group_letter} │ {team:<18} │ {pts:>1} │ {gd_str:>3} │ {gs:>3}  │")
            else:
                print(f"│         │ {team:<18} │ {pts:>1} │ {gd_str:>3} │ {gs:>3}  │")
        
        if i < GROUP_COUNT - 1:
            print(f"├─────────┼────────────────────┼───┼─────┼──────┤")
        else:
            print(f"└─────────┴────────────────────┴───┴─────┴──────┘")
    
    print()


def print_third_place_bubble(third_place_rankings: list) -> None:
    """Print third-place bubble showing 8th/9th cutoff."""
    if not third_place_rankings:
        return
    
    print(f"{_timestamp()} Third-place bubble:")
    
    # Index 7 = 8th place (0-indexed), Index 8 = 9th place
    # We show both plus the cutoff margin
    for rank, entry in enumerate(third_place_rankings, 1):
        gd_str = f"+{entry['gd']}" if entry['gd'] > 0 else str(entry['gd'])
        status = "ADVANCES" if rank <= 8 else "OUT"
        color_fn = _green if rank <= 8 else _red
        
        if rank == 8 or rank == 9:
            print(f"  {rank}. {entry['team']:<20} {entry['pts']} pts  GD {gd_str:>3}  {color_fn(status)}")
    
    # Cutoff margin
    if len(third_place_rankings) >= 9:
        eighth = third_place_rankings[7]
        ninth = third_place_rankings[8]
        # Determine deciding metric
        if eighth["pts"] != ninth["pts"]:
            margin = f"Pts = {eighth['pts'] - ninth['pts']}"
        elif eighth["gd"] != ninth["gd"]:
            margin = f"GD = {eighth['gd'] - ninth['gd']}"
        else:
            margin = f"GS = {eighth['gs'] - ninth['gs']}"
        print(f"  Cutoff margin: {margin}")
    
    print()
```
[ASSUMED] — follows user-approved layout from CONTEXT.md specifics section; ANSI patterns from `output.py`

### Test fixture pattern for group integration tests
```python
# In tests/test_group_integration.py
# Source: derived from test_fetcher.py:11-29 (MockResponse) and test_integration.py:17-84 (tmp_path)

import json
import pytest
from src.fetcher import process_group_matches
from src.state import load_played_groups, save_played_groups

GROUP_MATCH_EVENTS = [
    {
        "id": 10001,
        "status": "finished",
        "group_name": "Group A",
        "home_team": "Mexico",
        "away_team": "South Africa",
        "home_score": 2,
        "away_score": 1,
        "event_date": "2026-06-14T17:00:00Z",
    },
    {
        "id": 10002,
        "status": "finished",
        "group_name": "Group A",
        "home_team": "South Korea",
        "away_team": "Czech Republic",
        "home_score": 1,
        "away_score": 0,
        "event_date": "2026-06-14T19:00:00Z",
    },
]

def test_process_group_matches_basic(groups_fixture):
    """Verify basic group match ingestion produces correct entries."""
    from src.state import load_aliases
    aliases = load_aliases()
    result = process_group_matches(
        GROUP_MATCH_EVENTS, {}, groups_fixture, aliases,
        played_group_ids=set(), played_bsd_event_ids=set(),
    )
    assert len(result) == 2
    assert result[0]["match_id"] == "GS_A_01"
    assert result[0]["winner"] == "Mexico"
    assert result[0]["home_score"] == 2

def test_played_groups_roundtrip(tmp_path):
    """Verify save → load → verify roundtrip for played_groups.json."""
    played = {
        "GS_A_01": {
            "match_id": "GS_A_01",
            "team_a": "Mexico",
            "team_b": "South Africa",
            "winner": "Mexico",
            "home_score": 2,
            "away_score": 1,
            "completed_at": "2026-06-14T17:00:00Z",
        }
    }
    save_played_groups(played, data_dir=tmp_path)
    loaded = load_played_groups(data_dir=tmp_path)
    assert loaded == played
```
[ASSUMED] — follows patterns from `test_fetcher.py:11-29` and `test_integration.py:17-84`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| All group matches simulated from scratch | Real results injected via `played_groups` | Phase 10 | Group standings reflect actual tournament results |
| No `process_group_matches()` function | New function in fetcher.py | Phase 10 | Group match ingestion follows same pattern as knockout |
| No `played_groups.json` | New persistence file | Phase 10 | Group match results survive restarts (separate from knockout) |
| No group standings display | 12-group box-drawing table | Phase 10 | Users can see live group standings |
| No third-place bubble | Cutoff indicator at 8th/9th | Phase 10 | Users see advancing vs eliminated margin |
| Two failing tests | Both fixed | Phase 10 | 192 tests all pass |

**Deprecated/outdated:**
- `process_matches()` in `fetcher.py:73` — should NOT receive group matches (unchanged, but its callers must pre-filter)
- `print_header()` in `output.py:125` — will need group count and third-place team count added to its banner

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `_build_alias_lookup()` does not include group team names from `groups.json` | Pattern 1 | Group matches may fail to resolve team names if the team name from BSD matches the `groups.json` name but isn't in `team_aliases.json` — mitigation: include group team names in the alias lookup |
| A2 | Box-drawing characters render correctly on Windows Terminal | Pitfall 3 | Characters may show as `?` or `□` on legacy Console Host — mitigation: test on both Windows Terminal and Console Host, add `chcp 65001` if needed |
| A3 | `simulate_group_matches()` currently has no played-match skipping | Pitfall 1 | The code at `groups.py:187-287` unconditionally simulates all matches — MUST add `played_groups` param for correct behavior |
| A4 | `_extract_group_letter()` logic: `group_name.startswith("Group ")` and letter at index 6 is always valid | Pattern 1 | BSD API format may change; if `group_name` is "Group A" but without the space, extraction fails — but RESPONSE.md confirms "Group A" format |
| A5 | The `played_bsd_event_ids` in-memory set doesn't need persistence across restarts | Dedup | On restart, previously-ingested BSD events might be re-processed until their match_id hits the `played_group_ids` dedup check — acceptable for MVP |
| A6 | `main.py:_run_iteration()` currently only processes group matches OR nothing on hourly refresh | Pitfall 4 | The hourly refresh path at line 108-112 calls `run_full_simulation()` with existing `played_groups` data — no fetch, but existing data is used |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none (pytest defaults; tests autodiscovered) |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INTG-01 | process_group_matches() ingests BSD events | unit | `python -m pytest tests/test_group_integration.py::test_process_group_matches_basic -x` | ❌ Wave 0 |
| INTG-01 | Dedup prevents re-ingestion | unit | `python -m pytest tests/test_group_integration.py::test_process_group_matches_dedup -x` | ❌ Wave 0 |
| INTG-01 | Unmatchable teams skipped gracefully | unit | `python -m pytest tests/test_group_integration.py::test_process_group_matches_unmatchable -x` | ❌ Wave 0 |
| INTG-02 | played_groups.json save→load roundtrip | integration | `python -m pytest tests/test_group_integration.py::test_played_groups_roundtrip -x` | ❌ Wave 0 |
| INTG-03 | compute_standings() output matches display format | unit | `python -m pytest tests/test_group_integration.py::test_compute_standings_output_format -x` | ❌ Wave 0 |
| INTG-04 | Third-place bubble calculation | unit | `python -m pytest tests/test_group_integration.py::test_third_place_bubble_calculation -x` | ❌ Wave 0 |
| INTG-06/07 | Full pipeline with mock group matches | integration | `python -m pytest tests/test_group_integration.py::test_full_pipeline_with_group_matches -x` | ❌ Wave 0 |
| INTG-08 | Live smoke test | manual | `python -m pytest tests/test_live_smoke.py -x` (requires BSD_API_KEY) | ❌ Wave 0 |
| INTG-09 | test_main_loop: "Fetched"→"Polling" | fix | `python -m pytest tests/test_main_loop.py::test_main_loop_runs_iterations -x` | ✅ existing |
| INTG-09 | test_expected_goals: cap assertion | fix | `python -m pytest tests/test_groups.py::TestExpectedGoals -x` | ✅ existing |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_group_integration.py` — new file with 6+ tests covering INTG-01 through INTG-07
- [ ] `tests/test_live_smoke.py` — optional, marks INTG-08 as manual

## Security Domain

> `security_enforcement` is absent from config.json — treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | BSD API key via `Authorization: Token` header (implemented at `fetcher.py:20`) |
| V5 Input Validation | yes | Team name normalization filters out unmatchable teams (skip, not crash) |
| V7 Cryptography | no | No encryption needed for local JSON storage |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key leakage in error logs | Information Disclosure | `logger.warning("HTTP 401")` does NOT log the key (confirmed at `fetcher.py:27-29`) |
| JSON injection via API response | Tampering | `json.load()` parses API response; all field values are validated (team names, scores, group letters) before use |
| Temp file race condition | Tampering | `_atomic_write_json()` uses `os.replace()` (atomic on same filesystem); temp file prefix uses the target filename stem |
| BSD API key hardcoded | Information Disclosure | Retrieved from `os.environ.get("BSD_API_KEY")` at `main.py:166` — never committed to git |

## Sources

### Primary (HIGH confidence)
- `state.py:98-131` — `_atomic_write_json()` pattern
- `state.py:77-92` — `load_played()` / `save_played()` pattern
- `fetcher.py:73-156` — `process_matches()`, `_build_alias_lookup()`, `_normalize_team()`, `_find_bracket_match()`
- `groups.py:534-636` — `compute_standings()` data structure
- `groups.py:642-702` — `rank_third_placed()` data structure
- `knockout.py:129-199` — `run_full_simulation()` orchestration
- `output.py:13-209` — ANSI helpers, print patterns
- `main.py:82-155` — `_run_iteration()` integration point
- `main.py:189-272` — `main()` startup flow
- `test_fetcher.py:11-29` — `MockResponse` test pattern
- `test_main_loop.py:14-42` — `_runner_code()` subprocess pattern
- `test_integration.py:17-84` — tmp_path roundtrip pattern
- `conftest.py:1-144` — shared fixtures
- `team_aliases.json:1-78` — alias data for normalization
- `groups.json:1-700` — group match slot definitions
- `constants.py:15-16` — `API_URL` with BSD endpoint

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all verified in codebase; no new packages
- Architecture: HIGH — all patterns confirmed by reading existing code
- Pitfalls: HIGH — all derived from code analysis (simulate_group_matches has no played param)
- Code examples: MEDIUM — derived from verified patterns but not yet tested at runtime

**Research date:** 2026-06-14
**Valid until:** 2026-07-14 (stable — existing codebase won't change)
