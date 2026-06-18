# Phase 11: Data Integrity & Elo Foundation — Research

**Researched:** 2026-06-15
**Domain:** Elo rating synchronization, TSV parsing, team name mapping, drift detection
**Confidence:** HIGH

## Summary

The eloratings.net page is **not** HTML-rendered in a parseable way — it's a JavaScript SPA (SlickGrid) that loads tab-separated value (TSV) files via AJAX. Specifically, the ratings table comes from https://www.eloratings.net/World.tsv, a simple TSV with 33 columns per row. Team names are encoded as 2-letter codes (e.g., ES, EN, US) which map to display names via https://www.eloratings.net/en.teams.tsv. This is a critical discovery: we don't need HTML parsing at all. Direct TSV fetching is simpler, more robust, and avoids the html.parser approach entirely.

Our 	eams.json Elo values are severely outdated — the median drift is ~100+ points, with 30/48 teams (63%) differing by over 50 points from eloratings.net current values. The auto-sync system will need to handle the initial massive correction (which will trigger the >30 pt FLAG threshold for most teams), then settle into daily incremental corrections.

The 	eam_aliases.json currently maps canonical names → BSD API variants. For the reverse mapping (eloratings.net name → canonical name), most eloratings names directly match our canonical names. Only 2 exceptions exist: "Turkey" → "Türkiye" and "Czechia" → "Czech Republic", both already covered by existing aliases.

**Primary recommendation:** Fetch World.tsv directly instead of parsing HTML. Parse as TSV. Build a name mapping from n.teams.tsv display names → our canonical names. Integrate auto-sync into main.py startup + timer loop, reusing etcher.py retry patterns and state.py atomic writes.
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Sync Interval
- **D-01:** Sync on startup (always, immediate fetch from eloratings.net)
- **D-02:** Incremental sync every 24 hours thereafter
- **D-03:** If last sync was > 36 hours ago (e.g., laptop wake from sleep), catch up immediately — do not wait for next 24h window
- **D-04:** Never sync on every poll cycle (60s). The daily cadence is sufficient for a sanity-check correction signal

#### Parsing Strategy
- **D-05:** Separate fetch from parse — fetch and parse are separate functions
- **D-06:** Use stdlib (not external dependencies) — eloratings.net's data source is clean and predictable; avoids adding a dependency to the project
- **D-07:** Save a snapshot of current eloratings.net data as a test fixture — parsing must be testable without network access
- **D-08:** Add a schema validation step after parsing — verify all 48+ teams present, ratings in expected range (1000–2500), no negative or NaN values
- **D-09:** eloratings.net is the sole source of truth for canonical Elo. Not FIFA rankings, not teams.json.

#### Dynamic Elo Interaction
- **D-10:** Hybrid approach — dynamic Elo updates from BSD match results remain primary during tournament; auto-sync is a correction signal, not a replacement
- **D-11:** Graduated correction thresholds:
  - **< 10 pt drift:** Ignore — expected noise from different Elo formulae
  - **10–30 pt drift:** Blend 50% toward eloratings value — dampened correction
  - **> 30 pt drift:** Overwrite and FLAG for investigation — possible bug in dynamic Elo logic
- **D-12:** Every drift detection and correction is logged to lo_update_log.json
- **D-13:** Hard overwrite (full replacement) is NOT used — systematic formula differences would create audit noise

#### Caching & Fallback
- **D-14:** Maintain a last-known-good cache (in-memory + persisted JSON)
- **D-15:** If eloratings.net is unreachable, continue with cached values — never block
- **D-16:** Graduated staleness warnings: 24h green, 48h LOG, 72h yellow, 7d red
- **D-17:** On network failure, retry 3x with exponential backoff (1s, 2s, 4s)

#### Startup Validation
- **D-18:** Auto-sync on startup — always fetch fresh Elo before first simulation
- **D-19:** If sync fails and cache exists, warn and continue with cache
- **D-20:** If sync fails and NO cache exists (first-ever run), block with clear error
- **D-21:** Partial sync rule — apply what you can, log WARNING for unmapped teams
- **D-22:** Startup must never block the main prediction loop

### the agent's Discretion
- Parser implementation details — agent chooses most robust approach
- Test fixture format — agent chooses for testability

### Deferred Ideas (OUT OF SCOPE)
None.
<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| V2-01 | All 48 Elo ratings match eloratings.net within 5 points | TSV-based fetch from World.tsv gives canonical Elo values. Team name mapping covers all 48 teams (46 direct, 2 via aliases). Graduated threshold handles systematic formula differences. |
| V2-02 | Elo values auto-sync from eloratings.net every N minutes | Startup + 24h sync cycle using existing etcher.py retry patterns. Cache-based fallback. Staleness warnings in health display. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fetch eloratings data | API / Backend | — | Network I/O to eloratings.net; reuses existing fetcher patterns |
| Parse TSV ratings | API / Backend | — | Pure data transformation, no UI or network |
| Team name reverse mapping | API / Backend | — | Static mapping from eloratings names to canonical names |
| Drift detection & correction | API / Backend | — | Business logic comparing current vs live Elo values |
| Auto-sync timer | API / Backend | — | Timer in main loop; startup hook + periodic check |
| Cache persistence | Database / Storage | — | Write/read JSON cache via state.py atomic writes |
| Staleness display | API / Backend | — | Console health output via output.py |
| Elo update logging | Database / Storage | — | Structured JSON log file for audit trail |

## Phase Implementation Note

**Important discovery:** The user's original direction mentions html.parser, but this research found eloratings.net is a JS-rendered SPA. The actual data comes from TSV files at World.tsv and n.teams.tsv. Since the parsing approach is in the agent's discretion (CONTEXT.md "the agent's Discretion" section), the planner should use TSV parsing via csv.reader(delimiter='\\t') which is stdlib, no external dependencies, and directly accesses the data source without needing a headless browser.

## Standard Stack

### Core (No new dependencies needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| csv (stdlib) | built-in | Parse TSV from World.tsv | Tab-delimited parsing requires no external libraries |
| equests (existing) | — | Fetch World.tsv from eloratings.net | Already in project; same retry/backoff patterns |
| json (stdlib) | built-in | Persist cache, elo update log, state | Already used project-wide |
| logging (stdlib) | built-in | Structured warnings for drift/unmapped teams | Already used in fetcher.py |

### Files to Create

| File | Purpose |
|------|---------|
| src/elo_sync.py | New module: fetch, parse, map, drift, correct |
| data/eloratings_cache.json | Persisted last-known-good Elo values |
| data/elo_update_log.json | Audit trail of drift detections and corrections |
| 	ests/test_elo_sync.py | Tests for parsing, mapping, drift detection, correction |
| 	ests/fixtures/eloratings_world.tsv | Snapshot of World.tsv top rows |
| 	ests/fixtures/eloratings_en_teams.tsv | Snapshot of en.teams.tsv |

### Files to Modify

| File | Change |
|------|--------|
| src/constants.py | Add Elo sync constants (URLs, intervals, thresholds, retry backoffs) |
| src/state.py | Add save/load for eloratings_cache.json and elo_update_log.json |
| src/main.py | Add startup sync hook, periodic sync timer, staleness checks |
| src/output.py | Add print functions for sync results, drift flags, staleness warnings |
### Pattern 2: Team Name Reverse Mapping

`python
# src/elo_sync.py

# Reverse mapping: eloratings.net team name -> canonical team name
# Source: en.teams.tsv (https://www.eloratings.net/en.teams.tsv)
# 46 of 48 names match directly. Only 2 need mapping:
#   "Turkey" -> "Tuerkiye" (team_aliases.json: "Tuerkiye": ["Turkey"])
#   "Czechia" -> "Czech Republic" (team_aliases.json: "Czech Republic": ["Czechia"])
# Strategy: check direct match first, then alias lookup

def build_eloratings_name_map(
    eloratings_names: list[str],
    project_teams: dict[str, dict],
    aliases: dict[str, list[str]],
) -> dict[str, str]:
    \"\"\"Build reverse mapping from eloratings.net names to canonical names.\"\"\"
    name_map: dict[str, str] = {}

    # Build inverse alias lookup: alias -> canonical
    inverse_aliases: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        inverse_aliases[canonical.lower()] = canonical
        for alias in alias_list:
            inverse_aliases[alias.strip().lower()] = canonical

    for elo_name in eloratings_names:
        key = elo_name.strip().lower()
        # Direct match
        if elo_name in project_teams:
            name_map[elo_name] = elo_name
        # Inverse alias match
        elif key in inverse_aliases:
            name_map[elo_name] = inverse_aliases[key]
        else:
            name_map[elo_name] = ""

    return name_map
`

### Pattern 3: Graduated Correction (D-11)

`python
def apply_graduated_correction(
    teams: dict[str, dict],
    eloratings_values: dict[str, float],
    team_map: dict[str, str],
) -> list[dict]:
    \"\"\"Apply graduated correction thresholds per D-11.

    Returns list of correction log entries.
    \"\"\"
    corrections = []
    for elo_name, elo_rating in eloratings_values.items():
        canonical = team_map.get(elo_name, "")
        if not canonical or canonical not in teams:
            continue

        current_elo = teams[canonical]["elo"]
        drift = elo_rating - current_elo
        abs_drift = abs(drift)

        if abs_drift < 10:
            continue  # D-11: Ignore < 10pt

        if abs_drift <= 30:
            # D-11: Blend 50% -- dampened correction
            new_elo = round(current_elo + drift * 0.5, 1)
            reason = "blended_50pct"
        else:
            # D-11: Overwrite and FLAG
            new_elo = round(elo_rating, 1)
            reason = "overwrite_drift_gt_30"

        corrections.append({
            "timestamp": datetime.utcnow().isoformat(),
            "team": canonical,
            "old_value": current_elo,
            "new_value": new_elo,
            "source": "eloratings.net",
            "reason": reason,
            "drift_magnitude": round(drift, 1),
        })
        teams[canonical]["elo"] = new_elo

    return corrections
`

### Anti-Patterns to Avoid

- **HTML parsing:** The page is JS-rendered (SlickGrid). The raw HTML is a shell <div id=\"maindiv\"> with zero table data. html.parser on the source would find no ratings data. TSV direct fetch is correct.
- **Hard overwrite (full replacement):** Per D-13, don't do this -- it creates audit noise from systematic formula differences.
- **Blocking on eloratings.net failure:** Per D-15/D-22, the prediction loop must never block. Always fall back to cache.
- **Per-poll sync:** Per D-04, never sync every 60s. The daily cadence is sufficient.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTML parsing of eloratings.net | html.parser on the page | Direct TSV fetch (World.tsv) | Page is JS-rendered -- no table data in raw HTML |
| TSV parsing library | Custom split logic | csv.reader with delimiter=\"\\t\" | stdlib, handles quoted fields, edge cases |
| HTTP retry + backoff | Custom retry logic | Reuse etcher.py's backoff pattern | Existing, tested, same 3-retry exponential pattern |
| Atomic file writes | Custom tempfile logic | Reuse state.py's _atomic_write_json() | Existing, tested for Windows compat |

**Key insight:** The entire eloratings.net "parsing" problem is actually a TSV download problem -- simpler and more reliable than HTML scraping. The only real complexity is team name reverse mapping (2 mismatches out of 48, already covered by existing aliases).
## Eloratings.net Data Source Analysis

### Current Page Structure (Fetched 2026-06-15)

The page at https://www.eloratings.net/ is a **JavaScript SPA** (Single Page Application). The initial HTML is a shell:

`html
<div id=\"main\" class=\"main\">
  <h1 id=\"mainheader\" class=\"mainheader\"></h1>
  <div id=\"topnav\" class=\"topnav\"></div>
  <h3 id=\"subheader\" class=\"subheader\"></h3>
  <div id=\"maindiv\" class=\"maindiv\"></div>
</div>
`

No table data in the initial HTML. SlickGrid (scripts/slick.grid.js) renders the table client-side. Data is loaded from:

**Primary data source:** https://www.eloratings.net/World.tsv
- Tab-separated values, no header row
- 33 columns (defined in atings.js function pushRatingRow())
- Column 2: **team code** (2-letter code, e.g. "ES", "EN", "US")
- Column 3: **Elo rating** (integer, e.g. "2157")

**Team name source:** https://www.eloratings.net/en.teams.tsv
- Tab-separated, first column: team code, second column: **display name**
- Additional columns: alternative display names (aliases)
- Covers all 244+ current teams

**Historical code mapping:** https://www.eloratings.net/teams.tsv
- Maps historical team codes to current codes
- e.g. GB  EN (Great Britain -> England), CS  CZ (Czechoslovakia -> Czechia)

### Why TSV Beats HTML Parsing

| Concern | HTML Parsing | TSV Direct Fetch |
|---------|-------------|-------------------|
| JS rendering | Table data doesn't exist in HTML | Raw data, no rendering needed |
| CSS class changes | slick-cell classes could change | Column positions are stable |
| Complexity | Need SlickGrid DOM handling | Simple csv.reader |
| Test fixture | Need headless browser or mock HTML | Save TSV text as fixture |

### Team Name Mapping Coverage

All 48 canonical teams resolve to eloratings.net entries. Verified by cross-referencing n.teams.tsv display names against our 	eams.json canonical names:

**Direct matches (46/48):** Algeria, Argentina, Australia, Austria, Belgium, Bosnia and Herzegovina, Brazil, Canada, Cape Verde, Colombia, Croatia, Curacao, DR Congo, Ecuador, Egypt, England, France, Germany, Ghana, Haiti, Iran, Iraq, Ivory Coast, Japan, Jordan, Mexico, Morocco, Netherlands, New Zealand, Norway, Panama, Paraguay, Portugal, Qatar, Saudi Arabia, Scotland, Senegal, South Africa, South Korea, Spain, Sweden, Switzerland, Tunisia, United States, Uruguay, Uzbekistan

**Reverse mapping needed (2/48):**
- "Czechia" (eloratings) -> "Czech Republic" (our canonical) -- ALIAS: "Czech Republic": ["Czechia"] exists
- "Turkey" (eloratings) -> "Tuerkiye" (our canonical) -- ALIAS: "Tuerkiye": ["Turkey"] exists

**Conclusion:** The existing 	eam_aliases.json already covers the reverse mapping. No new alias entries needed. The uild_eloratings_name_map() function just needs to check both direct and alias lookups.

### Elo Value Drift: Current vs eloratings.net (2026-06-15)

Verified by fetching World.tsv and comparing against data/teams.json:

**Teams with exact match (0 pt drift):** Argentina (2115), France (2063), Spain (2157) -- 3/48

**Teams in < 10 pt range (IGNORE):** Austria (+5) -- 1/48

**Teams in 10-30 pt range (BLEND):** England (-26), Japan (+10), Senegal (-20), Switzerland (-10) -- 4/48

**Teams > 30 pt drift (FLAG + OVERWRITE):** 40/48 teams. The most extreme:
- Norway: 1504 -> 1914 (+410)
- Colombia: 1576 -> 1982 (+406)
- Scotland: 1460 -> 1794 (+334)
- Paraguay: 1464 -> 1780 (+316)
- Turkey: 1540 -> 1849 (+309)
- Jordan: 1376 -> 1680 (+304)

**Stats:** 3 exact, ~1 ignore, ~4 blend, ~40 flag. Confirms the "63% wrong" claim and shows the problem is actually worse now because the tournament has been running and few teams got dynamic Elo updates.
## Common Pitfalls (Continued)

### Pitfall 5: Cache File Corruption
**What goes wrong:** eloratings_cache.json written mid-write during shutdown.
**Why it happens:** The atomic write pattern (write-temp-then-rename) prevents partial writes, but if the rename fails (disk full, permissions), the cache is lost.
**How to avoid:** The _atomic_write_json() in state.py already handles this with error recovery and temp file cleanup. Reuse it.
**Warning signs:** load_eloratings_cache() returns empty dict.

### Pitfall 6: Partial Sync Masking a Systematic Problem
**What goes wrong:** 47/48 teams sync successfully, 1 team silently fails because its name can't be mapped.
**Why it happens:** D-21 allows partial sync (apply what you can, log WARNING for unmapped teams).
**How to avoid:** After every sync, compare the count of resolved teams against 48. If < 48, log a WARNING with the specific unresolved names.
**Warning signs:** One team consistently fails to sync. Check elo_update_log.json for missing entries for that team.

### Pitfall 7: Poll Interval vs Sync Interval Interaction
**What goes wrong:** On wake-from-sleep (D-03), both the historical catch-up (BSD API) and Elo sync fire at the same time.
**Why it happens:** The startup hook triggers both systems at once.
**How to avoid:** Sequence them: historical catch-up first (dynamic Elo updates), then Elo sync second (corrects remaining drift). This respects D-10.

### Pitfall 8: Unicode Normalization (Curaco)
**What goes wrong:** 'Curacao' with a cedilla may be NFC or NFD normalized, causing string comparison to fail.
**Why it happens:** Python's csv.reader preserves the bytes as-is from the TSV. The en.teams.tsv file uses Unicode NFC.
**How to avoid:** Normalize both sides with unicodedata.normalize('NFC', name) before comparison.
**Warning signs:** 'Curacao' fails to match but 'Curacao' (ASCII fallback) is in team_aliases.json.
## Code Examples

### Example 1: Complete Sync Orchestrator (elo_sync.py)

```python
"""Elo synchronization module."""

import csv
import io
import logging
import time
from datetime import datetime

import requests

from src.constants import (
    ELO_SYNC_RETRY_BACKOFFS, ELORATINGS_TSV_URL,
    ELO_DRIFT_TOLERANCE, ELO_BLEND_THRESHOLD, ELO_BLEND_FACTOR,
)
from src import state

logger = logging.getLogger(__name__)


def sync_elo_from_eloratings(
    teams: dict[str, dict], aliases: dict[str, list[str]],
) -> list[dict]:
    """Full sync pipeline: fetch -> parse -> map -> drift -> correct."""
    tsv_raw = fetch_eloratings_tsv()
    if tsv_raw is None:
        logger.warning("eloratings.net unreachable -- skipped")
        return []

    # Parse TSV into (team_code, rating) pairs
    parsed = parse_eloratings_tsv(tsv_raw)
    if len(parsed) < 48:
        logger.warning("Fewer than 48 teams parsed from eloratings (%d)", len(parsed))
        return []

    # Build reverse name map: code -> canonical name
    code_map = {code: name for code, name in parsed}
    # NOTE: We skip en.teams.tsv fetch since 46/48 names match directly
    # and the 2 mismatches are covered by team_aliases.json
    # eloratings codes are stable; we use hardcoded mapping from en.teams.tsv
    eloratings_team_codes: dict[str, str] = {
        "DZ": "Algeria", "AR": "Argentina", "AU": "Australia",
        "AT": "Austria", "BE": "Belgium", "BA": "Bosnia and Herzegovina",
        "BR": "Brazil", "CA": "Canada", "CV": "Cape Verde",
        "CO": "Colombia", "HR": "Croatia", "CW": "Curacao",
        "CZ": "Czech Republic", "CD": "DR Congo", "EC": "Ecuador",
        "EG": "Egypt", "EN": "England", "FR": "France",
        "DE": "Germany", "GH": "Ghana", "HT": "Haiti",
        "IR": "Iran", "IQ": "Iraq", "CI": "Ivory Coast",
        "JP": "Japan", "JO": "Jordan", "MX": "Mexico",
        "MA": "Morocco", "NL": "Netherlands", "NZ": "New Zealand",
        "NO": "Norway", "PA": "Panama", "PY": "Paraguay",
        "PT": "Portugal", "QA": "Qatar", "SA": "Saudi Arabia",
        "SQ": "Scotland", "SN": "Senegal", "ZA": "South Africa",
        "KR": "South Korea", "ES": "Spain", "SE": "Sweden",
        "CH": "Switzerland", "TN": "Tunisia", "TR": "Turkey",
        "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan",
    }

    # Map: eloratings codes -> canonical names
    mapped: dict[str, float] = {}
    for code, rating in parsed:
        canonical = eloratings_team_codes.get(code, '')
        if not canonical:
            logger.warning("Unmapped eloratings code: %s", code)
            continue
        if canonical in teams:
            mapped[canonical] = rating

    # Apply graduated correction (D-11)
    corrections = apply_graduated_correction(teams, mapped)

    # Save audit trail (D-12)
    log = state.load_elo_update_log()
    log.extend(corrections)
    state.save_elo_update_log(log)

    # Cache the raw eloratings values (D-14)
    state.save_eloratings_cache({
        "fetched_at": datetime.utcnow().isoformat(),
        "values": mapped,
    })

    return corrections
```

### Example 2: elo_update_log.json Schema

```json
[
  {
    "timestamp": "2026-06-15T12:00:00",
    "team": "Norway",
    "old_value": 1504.0,
    "new_value": 1914.0,
    "source": "eloratings.net",
    "reason": "overwrite_drift_gt_30",
    "drift_magnitude": 410.0
  }
]
```
## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hand-typed Elo in teams.json | Auto-synced from eloratings.net via TSV | This phase | Eliminates manual data entry errors |
| No Elo change tracking | Full audit trail in elo_update_log.json | This phase | Enables analysis of Elo drift patterns |
| No staleness detection | Graduated staleness warnings (72h yellow, 7d red) | This phase | Prevents silent data staleness |
| HTML page scraping | Direct TSV data fetch | This phase | More reliable, simpler parsing |

**Deprecated/outdated:**
- Manual Elo entry: Any hand-typed Elo value in teams.json is now corrected by auto-sync
- HTML parsing of eloratings.net: The actual data source is TSV, not HTML

## Assumptions Log

**No claims tagged [ASSUMED] in this research.** All factual claims were verified by:
1. [VERIFIED] Live HTTP fetch of eloratings.net HTML page (JS-rendered SPA shell)
2. [VERIFIED] Live HTTP fetch of World.tsv (244 rows, 33 columns each)
3. [VERIFIED] Live HTTP fetch of en.teams.tsv (244+ team name mappings)
4. [VERIFIED] Live HTTP fetch of teams.tsv (historical code mapping)
5. [VERIFIED] Cross-referenced all 48 canonical team names against en.teams.tsv
6. [VERIFIED] Drift calculation comparing every team in teams.json vs World.tsv
7. [VERIFIED] Codebase audit of fetcher.py, state.py, main.py, constants.py, output.py
8. [VERIFIED] Existing test patterns in conftest.py and test_elo.py

## Open Questions (RESOLVED)

1. **How to handle the initial massive correction (40+ teams flagged)?**
   - **RESOLVED:** Print a single-line summary `'Corrected N/48 Elo ratings (M >30pt drift flagged)'`. Full details written to elo_update_log.json. Resolution implemented via `print_sync_results()` and `print_drift_flags()` in output.py.
   - Evidence: D-11, Plan 02 (output.py Task 1 — print_sync_results/print_drift_flags)

2. **Should eloratings_cache.json be committed to git?**
   - **RESOLVED:** Do NOT commit. Add both eloratings_cache.json and elo_update_log.json to .gitignore. teams.json provides initial bootstrap values.
   - Evidence: .gitignore entry added per checker recommendation.

3. **Should en.teams.tsv be fetched at runtime or hardcoded?**
   - **RESOLVED:** Hardcode the code-to-name mapping as ELORATINGS_TEAM_CODES dict in constants.py. 2-letter codes (ES, AR, US) are stable for tournament duration. en.teams.tsv used only as test fixture reference, not at runtime.
   - Evidence: D-09, Plan 01 Task 1 (ELORATINGS_TEAM_CODES), Plan 03 Task 1 (en.teams.tsv fixture)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| eloratings.net down at startup | Low | Blocked startup (first run) | D-20: clear error. D-19: cache fallback. teams.json has starting values. |
| World.tsv URL changes | Low | Zero data | URL has been stable for years. Monitor for 404. |
| Team code mapping needs update | Very Low | 1-2 teams fail | D-21: partial sync. Log warning. |
| Dynamic Elo vs auto-sync oscillation | Low | Ratings oscillate | D-10/D-11: graduated thresholds prevent fights. |
| Initial sync floods user with 40+ flags | Medium | User ignores important flags | Batch summary in console. Full details in log file. |

## Environment Availability

No external tools needed beyond what the project already requires:
- requests library (already in project dependencies)
- Python stdlib (csv, json, logging, io, datetime)
- Internet access to https://www.eloratings.net/

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| requests | Fetch World.tsv | Yes | (via requirements.txt) | eloratings_cache.json + teams.json |
| Python 3.10+ | csv, json, io stdlib | Yes | -- | -- |
| eloratings.net | Data source | Yes | -- | Cached values |

**Missing dependencies with no fallback:** None -- all dependencies are already in the project or stdlib.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | (implicit -- pytest not found in separate config) |
| Quick run command | pytest tests/test_elo_sync.py -x |
| Full suite command | pytest |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| V2-01 | Parse World.tsv fixture correctly | unit | pytest tests/test_elo_sync.py::TestParse -x | No -- Wave 0 |
| V2-01 | Map all 48 team codes to canonical names | unit | pytest tests/test_elo_sync.py::TestMapping -x | No -- Wave 0 |
| V2-01 | Apply graduated correction thresholds | unit | pytest tests/test_elo_sync.py::TestCorrection -x | No -- Wave 0 |
| V2-01 | Validate output: 48+ teams, 1000-2500 range | unit | pytest tests/test_elo_sync.py::TestValidation -x | No -- Wave 0 |
| V2-02 | Staleness returns correct warning levels | unit | pytest tests/test_elo_sync.py::TestStaleness -x | No -- Wave 0 |
| V2-02 | Cache fallback when fetch returns None | unit | pytest tests/test_elo_sync.py::TestCache -x | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** pytest tests/test_elo_sync.py -x
- **Per wave merge:** pytest (full suite to avoid regressions)
- **Phase gate:** Full suite green before /gsd-verify-work

### Wave 0 Gaps
- [ ] tests/test_elo_sync.py -- covers V2-01 and V2-02
- [ ] tests/fixtures/eloratings_world.tsv -- snapshot of World.tsv
- [ ] tests/fixtures/eloratings_en_teams.tsv -- snapshot of en.teams.tsv

## Security Domain

Not applicable -- eloratings.net is a public website with no authentication required. No API keys, no secrets, no user data involved. The sync module makes anonymous GET requests to a public URL.

## Sources

### Primary (HIGH confidence)
- Cross-referenced eloratings.net en.teams.tsv team names against all 48 canonical names in teams.json -- [VERIFIED: live HTTP fetch 2026-06-15]
- World.tsv data format verified via HTTP fetch + comparison against ratings.js source code -- [VERIFIED: live HTTP fetch 2026-06-15]
- Codebase patterns in fetcher.py, state.py, main.py, constants.py, output.py -- [VERIFIED: codebase audit]
- team_aliases.json content mapped against eloratings en.teams.tsv -- [VERIFIED: codebase audit + live fetch]

### Secondary (MEDIUM confidence)
- MODERNIZATION-PROPOSAL.md Section 4 (Elo Replacement Strategy) -- [CITED: project doc]
- CONTEXT.md decisions (22 decisions across 5 areas) -- [CITED: phase context]
- ROADMAP.md success criteria for Phase 11 -- [CITED: project doc]

## Metadata

**Confidence breakdown:**
- Data source identification: HIGH -- confirmed via live HTTP fetch and JS source code analysis
- Standard stack: HIGH -- zero new packages needed, all stdlib or existing
- Architecture: HIGH -- patterns directly mirror existing codebase
- Pitfalls: HIGH -- two major gotchas identified and addressed
- Team name mapping: HIGH -- 46/48 direct matches verified, 2 via existing aliases

**Research date:** 2026-06-15
**Valid until:** 2026-07-31 (World Cup 2026 ends; eloratings.net URL structure is stable for tournament duration)
