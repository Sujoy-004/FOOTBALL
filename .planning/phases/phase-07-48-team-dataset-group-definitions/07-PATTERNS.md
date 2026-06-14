# Phase 7: 48-Team Dataset & Group Definitions — Pattern Map

**Mapped:** 2026-06-14
**Files analyzed:** 6 (2 new, 2 extended, 2 maybe-extended)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `data/teams.json` | data (config) | file-I/O | `data/teams.json` (current, self) | exact |
| `data/groups.json` | data (config) | file-I/O | `data/bracket.json` (JSON array-of-objects pattern) | role-match |
| `data/annex_c.json` | data (config) | file-I/O | `data/team_aliases.json` (JSON dict pattern) | role-match |
| `data/team_aliases.json` | data (config) | file-I/O | `data/team_aliases.json` (current, self) | exact |
| `src/state.py` | service | file-I/O | `src/state.py` (existing load_teams, load_bracket, validate_bracket) | exact |
| `src/constants.py` | config | static | `src/constants.py` (current) | exact |

---

## Pattern Assignments

### `data/teams.json` (data/config, file-I/O — EXTENDED 32→48)

**Analog:** `worldcup_predictor/data/teams.json` (self, lines 1–98)

**Structure pattern** (lines 1–97): Object keyed by team name, each value is `{"elo": <number>}`.
```json
{
  "Argentina": {
    "elo": 2115
  },
  "France": {
    "elo": 2063
  }
}
```

**Add 16 new teams** following the same pattern. No structural change — only append new entries. Example new teams (from FIFA-qualified nations for 2026):
```json
  "Costa Rica": {
    "elo": 1760
  },
  "Morocco": {
    "elo": 1910
  }
```

**Key constraints to preserve:**
- Team names are the canonical display names (used as keys throughout codebase)
- Names must match `data/team_aliases.json` canonical keys
- Names must match team references in `data/groups.json`

---

### `data/team_aliases.json` (data/config, file-I/O — EXTENDED)

**Analog:** `worldcup_predictor/data/team_aliases.json` (self, lines 1–12)

**Structure pattern** (lines 1–11): Object keyed by canonical team name, values are arrays of alias strings.
```json
{
  "United States": ["USA", "United States of America"],
  "Iran": ["IR Iran", "Islamic Republic of Iran"],
  "South Korea": ["Korea Republic"],
  "Czech Republic": ["Czechia"]
}
```

**Extend pattern:** Add alias entries for all 16 new teams, plus any missing aliases for existing 32 teams. Each key must match a team name in `teams.json`. The aliases are used by the fetcher to match BSD API team names to canonical names.

**Key naming rule:** The canonical name (key) is the name used in `teams.json`, `groups.json`, and throughout all Python code. Aliases are alternative spellings used by the BSD API.

---

### `data/groups.json` (data/config, file-I/O — NEW, no direct analog)

**Analog:** `worldcup_predictor/data/bracket.json` (lines 1–25) for JSON match-list pattern, plus RESEARCH.md specification.

**Structure pattern** (JSON object, not array — per ARCHITECTURE.md section 1.1):

```json
{
  "groups": {
    "A": {
      "teams": ["Mexico", "South Africa", "South Korea", "Czechia"],
      "matches": [
        {"match_id": "GS_A_01", "team_a": "Mexico", "team_b": "South Korea", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_02", "team_a": "South Africa", "team_b": "Czechia", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_03", "team_a": "Mexico", "team_b": "Czechia", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_04", "team_a": "South Korea", "team_b": "South Africa", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_05", "team_a": "Mexico", "team_b": "South Africa", "winner": null, "score_a": null, "score_b": null},
        {"match_id": "GS_A_06", "team_a": "South Korea", "team_b": "Czechia", "winner": null, "score_a": null, "score_b": null}
      ]
    }
  }
}
```

**Match object keys** (compare with bracket.json pattern lines 2–17):
- Same `team_a`, `team_b`, `winner` fields as bracket matches
- Same `null` initial values for unplayed matches
- **Added:** `score_a`, `score_b` (integers, for goal difference tracking)
- **Added:** Match ID prefix `GS_<GROUP>_<NN>` (distinct from bracket's `R16_1`, `QF_1`, etc.)
- **No `source_matches` field** — group matches do not feed into other matches directly

**Bracket.json match pattern** (reference for field conventions, lines 2–4):
```json
{"match_id": "R16_1", "round": "R16", "team_a": "Argentina", "team_b": "Nigeria", "source_matches": null, "winner": null}
```

**Validation rules** (implemented in state.py's `validate_groups()`):
1. Exactly 12 groups (A–L)
2. Each group has exactly 4 teams (no duplicates across groups)
3. Each group has exactly 6 matches with unique `match_id` within format `GS_{letter}_{NN}`
4. All team names in matches reference valid team names in `teams.json`
5. No circular match references (trivial — no `source_matches` in group stage)

---

### `data/annex_c.json` (data/config, file-I/O — NEW, no direct analog)

**Analog:** `worldcup_predictor/data/team_aliases.json` (lines 1–12) for JSON dict-of-strings pattern.

**Structure pattern** (JSON object with sorted-key mapping per ARCHITECTURE.md section 1.3):

```json
{
  "_meta": {
    "source": "FIFA 2026 Competition Regulations Annex C",
    "verified_against": "tournamental packages/bracket-engine/data/fifa-2026-annex-c-assignments.json",
    "combinations": 495
  },
  "A,B,C,D,E,F,G,H": {
    "1A": "3H", "1B": "3G", "1D": "3B", "1E": "3C",
    "1G": "3A", "1I": "3F", "1K": "3D", "1L": "3E"
  },
  "A,B,C,D,E,F,G,I": {
    "1A": "3H", "1B": "3G", "1D": "3F", "1E": "3C",
    "1G": "3D", "1I": "3B", "1K": "3A", "1L": "3E"
  }
}
```

**`team_aliases.json` dict reference pattern** (lines 1–5):
```json
{
  "United States": ["USA", "United States of America"],
  "Iran": ["IR Iran", "Islamic Republic of Iran"]
}
```

**Key naming conventions:**
- Keys are comma-separated, **sorted** group letters of the 8 advancing third-place groups
- Example: `"C,D,E,F,G,H,I,J"` means third-place teams from groups C, D, E, F, G, H, I, J advance
- Value keys: `"1A"`, `"1B"`, `"1D"`, `"1E"`, `"1G"`, `"1I"`, `"1K"`, `"1L"` (the 8 group winners who host third-place teams)
- Value values: `"3H"` means "third-place team from group H"

**Validation rules** (implemented in state.py's `validate_annex_c()`):
1. Exactly 495 keys (entries)
2. Every key contains exactly 8 comma-separated group letters, sorted ascending, from A–L
3. Every value has exactly 8 entries with keys `1A, 1B, 1D, 1E, 1G, 1I, 1K, 1L`
4. No self-references (e.g., `"1A"` never maps to `"3A"`)
5. No value references a group letter not in the key

---

### `src/state.py` (service, file-I/O — EXTENDED)

**Analog:** `worldcup_predictor/src/state.py` (self, lines 1–240) — existing load/validate patterns.

**Load function pattern** (copy from `load_teams`, lines 38–53):

```python
def load_teams(data_dir: Path | str | None = None) -> dict[str, dict]:
    """Load teams from teams.json.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        dict[str, dict]: Mapping of team name to team data (e.g. {"elo": 2100}).

    Raises:
        FileNotFoundError: If teams.json does not exist.
        json.JSONDecodeError: If teams.json contains invalid JSON.
    """
    path = _resolve_data_dir(data_dir) / "teams.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)
```

**To add — `load_groups()`** (same pattern, return type `dict`):
```python
def load_groups(data_dir: Path | str | None = None) -> dict:
    """Load group definitions from groups.json and validate structure.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        dict: The groups object with "groups" key mapping to A–L entries.

    Raises:
        FileNotFoundError: If groups.json does not exist.
        json.JSONDecodeError: If groups.json contains invalid JSON.
        ValueError: If group validation fails.
    """
    path = _resolve_data_dir(data_dir) / "groups.json"
    with open(path, encoding="utf-8") as f:
        groups: dict = json.load(f)
    validate_groups(groups)
    return groups
```

**To add — `load_annex_c()`** (same pattern, return type `dict`):
```python
def load_annex_c(data_dir: Path | str | None = None) -> dict:
    """Load Annex C lookup table from annex_c.json and validate.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        dict: The Annex C table (495 entries).

    Raises:
        FileNotFoundError: If annex_c.json does not exist.
        json.JSONDecodeError: If annex_c.json contains invalid JSON.
        ValueError: If Annex C validation fails.
    """
    path = _resolve_data_dir(data_dir) / "annex_c.json"
    with open(path, encoding="utf-8") as f:
        annex_c: dict = json.load(f)
    validate_annex_c(annex_c)
    return annex_c
```

**Validation pattern** (copy from `validate_bracket`, lines 170–228):

`validate_bracket()` uses this pattern:
```python
def validate_bracket(matches: list[dict[str, Any]]) -> None:
    """Validate bracket structure. Raises ValueError on failure.

    Validates:
    1. All match_ids are unique.
    2. Every source_matches reference exists as a match_id.
    3. No circular dependencies in source_matches (should be a DAG).

    Args:
        matches: List of match objects from bracket.json.

    Raises:
        ValueError: If any validation check fails, with a descriptive message.
    """
    # Step 1: Uniqueness check
    match_ids: set[str] = set()
    for match in matches:
        mid = match["match_id"]
        if mid in match_ids:
            raise ValueError(f"Duplicate match_id: {mid}")
        match_ids.add(mid)

    # Step 2: Reference integrity
    for match in matches:
        sources = match.get("source_matches")
        if sources:
            for src in sources:
                if src not in match_ids:
                    raise ValueError(
                        f"Match '{match['match_id']}' references "
                        f"non-existent source_match '{src}'"
                    )
```

**To add — `validate_groups()`** (same pattern, sequential checks):
```python
def validate_groups(groups: dict) -> None:
    """Validate groups.json structure. Raises ValueError on failure.

    Validates:
    1. Exactly 12 groups (A–L).
    2. Each group has 'teams' and 'matches' keys.
    3. Each group has exactly 4 teams (no duplicates across groups).
    4. Each group has exactly 6 matches.
    5. Match IDs follow pattern GS_{letter}_{NN} and are unique.
    6. All team names in matches reference valid teams in teams.json.
    """
    # Step 1: Group count check
    group_keys = groups.get("groups", {})
    if len(group_keys) != 12:
        raise ValueError(f"Expected 12 groups (A–L), got {len(group_keys)}")

    # Step 2: Validate each group
    for letter, group in group_keys.items():
        if "teams" not in group or "matches" not in group:
            raise ValueError(f"Group {letter}: missing 'teams' or 'matches' key")
        if len(group["teams"]) != 4:
            raise ValueError(f"Group {letter}: expected 4 teams, got {len(group['teams'])}")
        if len(group["matches"]) != 6:
            raise ValueError(f"Group {letter}: expected 6 matches, got {len(group['matches'])}")

    # Step 3: Match ID uniqueness across all groups
    match_ids: set[str] = set()
    expected_prefixes = {f"GS_{l}_" for l in group_keys}
    for letter, group in group_keys.items():
        for match in group["matches"]:
            mid = match["match_id"]
            if mid in match_ids:
                raise ValueError(f"Duplicate match_id across groups: {mid}")
            match_ids.add(mid)
```

**To add — `validate_annex_c()`**:
```python
def validate_annex_c(annex_c: dict) -> None:
    """Validate annex_c.json structure. Raises ValueError on failure.

    Validates:
    1. Exactly 495 entries.
    2. Every key contains 8 sorted, comma-separated group letters (A–L).
    3. Every value has exactly 8 entries: 1A, 1B, 1D, 1E, 1G, 1I, 1K, 1L.
    4. No self-references.
    5. No value references a group not in the key.

    Raises:
        ValueError: If any validation check fails.
    """
    expected_keys = {"1A", "1B", "1D", "1E", "1G", "1I", "1K", "1L"}
    valid_groups = set("ABCDEFGHIJKL")

    if len(annex_c) != 495:
        raise ValueError(f"Expected 495 Annex C entries, got {len(annex_c)}")

    for key, value in annex_c.items():
        groups_in_key = set(key.split(","))
        if len(groups_in_key) != 8:
            raise ValueError(f"Annex C key '{key}': expected 8 groups")
        if not groups_in_key.issubset(valid_groups):
            raise ValueError(f"Annex C key '{key}': invalid group letters")
        if set(value.keys()) != expected_keys:
            raise ValueError(f"Annex C entry '{key}': missing or extra assignment keys")
        for v in value.values():
            ref_group = v.replace("3", "")
            if ref_group not in groups_in_key:
                raise ValueError(f"Annex C entry '{key}': references group {ref_group} not in key")
```

**Naming conventions to follow:**
- Functions: `load_groups()`, `load_annex_c()`, `validate_groups()`, `validate_annex_c()`
- All use `data_dir: Path | str | None = None` parameter
- All call `_resolve_data_dir(data_dir)` for path resolution (lines 234–240)
- Load functions call their corresponding validate function before returning (same as `load_bracket` calls `validate_bracket`, line 73)

---

### `src/constants.py` (config, static — MAYBE EXTENDED)

**Analog:** `worldcup_predictor/src/constants.py` (self, lines 1–22)

**Current pattern:**
```python
"""Constants for the World Cup predictor."""

import os
from pathlib import Path

K_FACTOR: int = 60
DEFAULT_ELO: int = 1500
DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
API_URL: str = "https://sports.bzzoiro.com/api/events/?status=finished&league_id=27&limit=200"
API_TIMEOUT: int = 10
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "60"))
```

**Proposed additions:**
```python
GROUP_COUNT: int = 12
"""Number of groups in the 48-team format (A–L)."""

TEAMS_PER_GROUP: int = 4
"""Number of teams in each group."""

MATCHES_PER_GROUP: int = 6
"""Number of round-robin matches per group (n*(n-1)/2 for n=4)."""

ANNEX_C_ENTRIES: int = 495
"""Number of entries in Annex C third-place lookup table = C(12,8)."""

ANNEX_C_WINNER_GROUPS: tuple[str, ...] = ("A", "B", "D", "E", "G", "I", "K", "L")
"""Group winners that host third-place teams (not C, F, H, J)."""
```

**NOTE:** Per ARCHITECTURE.md Anti-Pattern 4, `ANNEX_C_WINNER_GROUPS` should ideally be **derived from data** rather than hardcoded. Include it here for convenience with a comment noting it derives from Annex C structure.

---

## Shared Patterns

### Load → Validate → Return pattern (all state.py load functions)

**Source:** `worldcup_predictor/src/state.py`, `load_bracket()` (lines 56–74)

Applied to all new load functions in state.py:
```python
def load_*(data_dir: Path | str | None = None) -> <return_type>:
    """Docstring with Args/Returns/Raises."""
    path = _resolve_data_dir(data_dir) / "<filename>.json"
    with open(path, encoding="utf-8") as f:
        data: <type> = json.load(f)
    validate_*(data)                    # validate BEFORE return
    return data
```

### Sequential validation checks pattern

**Source:** `worldcup_predictor/src/state.py`, `validate_bracket()` (lines 170–228)

Applied to all new validate functions:
1. Check 1: Count/structure assertions → raise `ValueError` with descriptive message
2. Check 2: Cross-reference integrity → raise `ValueError`
3. Check 3: Domain-specific rules → raise `ValueError`
4. No return value — raises on failure, passes silently on success

### Load function error handling

**Source:** `worldcup_predictor/main.py` (lines 255–263)

All load functions raise standard exceptions caught by main.py:
```python
except ValueError as e:
    output.print_error(f"Data error: {e}")
    sys.exit(1)
except FileNotFoundError as e:
    output.print_error(f"File not found: {e}. Run with valid state files.")
    sys.exit(1)
except json.JSONDecodeError as e:
    output.print_error(f"Corrupt JSON file: {e}. Check data/ directory.")
    sys.exit(1)
```

### JSON file structure conventions

**Source:** All files in `worldcup_predictor/data/`

| Convention | Example | Notes |
|---|---|---|
| UTF-8 encoding | `encoding="utf-8"` | Always |
| 2-space indent | `json.dump(data, f, indent=2)` | In `_atomic_write_json` |
| Null for unset fields | `"winner": null` | Unplayed matches have null winner |
| Team names as string keys | `"Argentina": {"elo": 2115}` | Canonical names throughout |

---

## No Analog Found

**All files have exact or role-match analogs.** No files without coverage.

| File | Role | Data Flow | Reason for Confidence |
|---|---|---|---|
| `data/groups.json` | data (config) | file-I/O | Pattern from bracket.json + ARCHITECTURE.md section 1.1 specification |
| `data/annex_c.json` | data (config) | file-I/O | Pattern from team_aliases.json + ARCHITECTURE.md section 1.3 specification |
| `src/state.py` extensions | service | file-I/O | Direct pattern copy from existing load_teams(), validate_bracket() |

---

## Metadata

**Analog search scope:** `worldcup_predictor/data/`, `worldcup_predictor/src/`, `worldcup_predictor/tests/`
**Files scanned:** 12 (teams.json, team_aliases.json, bracket.json, state.py, constants.py, simulation.py, output.py, main.py, conftest.py, test_state.py, test_state_load.py, __init__.py)
**Pattern extraction date:** 2026-06-14
