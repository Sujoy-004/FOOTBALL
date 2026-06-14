# World Cup Dynamic Prediction – Backend Schema Document (Backend_Schema.md)

Note: All numeric values (poll interval, simulation count, K‑factor, Elo ratings, etc.) are example defaults. In code, define them in constants.py or environment variables.

## 1. Document Purpose

This document defines the **backend data structures, file schemas, API contracts, and module interfaces** for the MVP. It serves as the single source of truth for how data is stored, validated, and passed between components.

---

## 2. File‑Based Storage Schema

The MVP uses **JSON files** for persistence. No database.

### 2.1 `teams.json` – Team data and current Elo ratings

Example Elo values shown below — actual values will differ based on live match results.

```json
{
  "Argentina": {
    "elo": 2112,
    "group": "C",
    "eliminated": false,
    "fifa_rank": 1
  },
  "France": {
    "elo": 2075,
    "group": "D",
    "eliminated": false,
    "fifa_rank": 2
  }
}
```

**Schema rules:**
- Key = team name (string, matches API naming after mapping).
- `elo`: integer (starting 1400–2200 range, updated after each match).
- `group`: string (A–H, only for possible future group stage).
- `eliminated`: boolean (false until knockout loss; once true, not used in simulation).
- `fifa_rank`: integer (1–32, optional, for future feature weighting).

### 2.2 `bracket.json` – Knockout stage structure

```json
{
  "round_of_16": [
    { "match_id": "R16_1", "team_a": "Argentina", "team_b": "Nigeria", "winner": null },
    { "match_id": "R16_2", "team_a": "France", "team_b": "Denmark", "winner": null },
    { "match_id": "R16_3", "team_a": "Spain", "team_b": "Japan", "winner": null },
    { "match_id": "R16_4", "team_a": "Brazil", "team_b": "Ghana", "winner": null },
    { "match_id": "R16_5", "team_a": "England", "team_b": "Senegal", "winner": null },
    { "match_id": "R16_6", "team_a": "Netherlands", "team_b": "USA", "winner": null },
    { "match_id": "R16_7", "team_a": "Portugal", "team_b": "Switzerland", "winner": null },
    { "match_id": "R16_8", "team_a": "Germany", "team_b": "Croatia", "winner": null }
  ],
  "quarterfinals": [
    { "match_id": "QF_1", "source_matches": ["R16_1", "R16_2"], "winner": null },
    { "match_id": "QF_2", "source_matches": ["R16_3", "R16_4"], "winner": null },
    { "match_id": "QF_3", "source_matches": ["R16_5", "R16_6"], "winner": null },
    { "match_id": "QF_4", "source_matches": ["R16_7", "R16_8"], "winner": null }
  ],
  "semifinals": [
    { "match_id": "SF_1", "source_matches": ["QF_1", "QF_2"], "winner": null },
    { "match_id": "SF_2", "source_matches": ["QF_3", "QF_4"], "winner": null }
  ],
  "final": {
    "match_id": "FINAL",
    "source_matches": ["SF_1", "SF_2"],
    "winner": null
  }
}
```

**Schema rules:**
- `match_id`: unique string.
- `team_a`, `team_b`: present only in round_of_16. For later rounds, teams are determined by `source_matches`.
- `winner`: null or team name string (set when real match completes).
- `source_matches`: array of match_ids whose winners feed into this match.

### 2.3 `played.json` – Record of completed real matches

```json
{
  "R16_1": {
    "winner": "Argentina",
    "home_score": 2,
    "away_score": 1,
    "timestamp": "2026-06-15T22:03:00Z"
  },
  "R16_2": {
    "winner": "France",
    "home_score": 3,
    "away_score": 0,
    "timestamp": "2026-06-15T22:05:00Z"
  }
}
```

**Schema rules:**
- Key = `match_id`.
- `winner`: string (must match a team name in `teams.json`).
- `home_score`, `away_score`: integers (optional for MVP, useful for future xG).
- `timestamp`: ISO 8601 UTC (when match was recorded).

### 2.4 `api_id_mapping.json` – Map external API match IDs to internal match IDs

```json
{
  "123456": "R16_1",
  "123457": "R16_2",
  "123458": "R16_3",
  "123459": "R16_4"
}
```

**Why needed:** The external API uses numeric IDs. Our bracket uses human‑readable IDs. This mapping bridges them.

### 2.5 `played_groups.json` – Record of completed group stage matches

```json
{
  "GS_A_01": {
    "match_id": "GS_A_01",
    "team_a": "Mexico",
    "team_b": "South Africa",
    "winner": "Mexico",
    "home_score": 2,
    "away_score": 1,
    "completed_at": "2026-06-14T17:00:00Z"
  },
  "GS_A_02": {
    "match_id": "GS_A_02",
    "team_a": "Italy",
    "team_b": "Chile",
    "winner": null,
    "home_score": 1,
    "away_score": 1,
    "completed_at": "2026-06-14T17:00:00Z"
  }
}
```

**Schema rules:**
- Key = `match_id` from `groups.json` (e.g., `GS_A_01`, `GS_L_06`).
- `winner`: string or null (null for draws — group matches can end in draws).
- `home_score`, `away_score`: integers.
- `completed_at`: ISO 8601 UTC timestamp.
- Initial state: empty `{}` on first run (graceful bootstrap).

### 2.6 `constants.py` – Hardcoded parameters (no JSON)

```python
# constants.py — example defaults, override as needed
K_FACTOR = 60          # typical range 20–100
POLL_INTERVAL_SECONDS = 60
SIMULATION_COUNT = 50000
API_URL = "https://sports.bzzoiro.com/api/events/?status=finished&league_id=27"
API_KEY_ENV_VAR = "BSD_API_KEY"
DEFAULT_ELO_START = 2000  # default for new teams
GROUP_COUNT = 12
MATCHES_PER_GROUP = 6
```

---

## 3. In‑Memory Data Structures (Python)

These are used at runtime, derived from JSON files.

### 3.1 Teams dict
```python
teams: dict[str, dict] = {
    "Argentina": {"elo": 2112, "eliminated": False}
}
```

### 3.2 Bracket tree (nested dicts/lists)
```python
bracket = {
    "R16": [
        {"match_id": "R16_1", "team_a": "Argentina", "team_b": "Nigeria", "winner": None}
    ],
    "QF": [...],
    "SF": [...],
    "F": {"match_id": "FINAL", "source": ["SF_1", "SF_2"], "winner": None}
}
```

### 3.3 Played matches set and dict
```python
played_set: set[str] = {"R16_1", "R16_2"}  # quick lookup
played_details: dict[str, dict] = { ... }  # full details
```

### 3.4 Simulation result
```python
probabilities: dict[str, float] = {
    "Argentina": 0.341,
    "France": 0.275,
    "Brazil": 0.149
}
```

---

## 4. API Contract (External)

**Endpoint:**  
`GET https://sports.bzzoiro.com/api/events/?status=finished&league_id=27`

**Headers:**
```
Authorization: Token <your_api_key>
```

**Response schema (relevant subset):**
```json
{
  "count": 200,
  "next": "https://sports.bzzoiro.com/api/events/?page=2&status=finished&league_id=27",
  "previous": null,
  "results": [
    {
      "id": 123456,
      "status": "finished",
      "home_team": "Argentina",
      "away_team": "Nigeria",
      "home_score": 2,
      "away_score": 1,
      "event_date": "2026-06-15T22:00:00Z",
      "group_name": null,
      "round_number": 1,
      "round_name": "Round of 16"
    },
    {
      "id": 123457,
      "status": "finished",
      "home_team": "Mexico",
      "away_team": "South Africa",
      "home_score": 2,
      "away_score": 1,
      "event_date": "2026-06-14T17:00:00Z",
      "group_name": "Group A",
      "round_number": 1,
      "round_name": "Group Stage"
    }
  ]
}
```

**Field mapping:**
- `group_name` discrimination:
  - Non-null (e.g., `"Group A"`) → group match → routed to `process_group_matches()`
  - Null → knockout match → mapped via `api_id_mapping.json` to `match_id` (e.g., `R16_1`)
- `home_team` and `away_team` → normalized via `team_aliases.json` lookup
- `winner` → not directly provided by BSD; determined from `home_score` vs `away_score`

---

## 5. Module Interfaces (Function Signatures)

### 5.1 `fetcher.py`

```python
def fetch_new_results(last_known_ids: set[str]) -> list[dict]:
    """
    Poll API and return list of newly finished knockout matches.
    Each match dict: {
        "match_id": str,
        "team_a": str,
        "team_b": str,
        "winner": str,   # team name
        "home_score": int,
        "away_score": int
    }
    """

def process_group_matches(raw_matches: list[dict], teams: dict, groups: dict,
                           aliases: dict, played_group_ids: set[str],
                           played_bsd_event_ids: set[int]) -> list[dict]:
    """
    Process BSD API response entries with non-null group_name.
    Routes each match to the correct group slot in groups.json.
    Returns list of group match dicts for played_groups.json.
    Each entry: {
        "match_id": str,     # e.g. "GS_A_01"
        "team_a": str,
        "team_b": str,
        "winner": str|None,  # None for draws
        "home_score": int,
        "away_score": int,
        "completed_at": str  # ISO 8601
    }
    """
```

### 5.2 `elo.py`

```python
def update_ratings(team_a: str, team_b: str, winner: str, 
                   current_elos: dict[str, float],
                   K: int = 60) -> dict[str, float]:  # K is an example default (range 20–100)
    """
    Returns new elo dict (only for the two teams changed).
    """
```

### 5.3 `simulator.py`

```python
def simulate_match(team_a: str, team_b: str, elo_a: float, elo_b: float) -> str:
    """Returns winner (team name)."""

def run_single_tournament(elos: dict, bracket: dict, played: set[str]) -> str:
    """Returns champion name."""

def run_monte_carlo(elos: dict, bracket: dict, played: set[str], 
                    n: int = 50000) -> dict[str, float]:  # example default
    """Returns {team: probability}."""
```

### 5.4 `state.py`

```python
def load_teams() -> dict:
    """Loads teams.json."""

def load_bracket() -> dict:
    """Loads bracket.json."""

def load_played_matches() -> tuple[set[str], dict]:
    """Returns (played_set, played_details)."""

def save_teams(teams_data: dict) -> None:
    """Writes to teams.json atomically."""

def save_played_matches(played_details: dict) -> None:
    """Writes to played.json."""

def load_api_id_mapping() -> dict:
    """Loads api_id_mapping.json."""

def load_played_groups() -> dict:
    """Loads played_groups.json. Returns empty dict if not found."""

def save_played_groups(played_groups: dict) -> None:
    """Writes to played_groups.json atomically."""
```

### 5.5 `output.py`

```python
def print_initial_header() -> None:
    """Prints startup banner."""

def print_probabilities(probs: dict[str, float], timestamp: str, 
                        deltas: dict[str, float] = None) -> None:
    """Formats and prints probabilities with optional deltas."""

def print_match_update(match: dict, elo_changes: dict) -> None:
    """Prints new match and Elo updates."""

def print_error(msg: str) -> None:
    """Prints error message in red (if color enabled)."""
```

---

## 6. Validation Rules (Data Integrity)

| Data                    | Rule                                                                 |
|-------------------------|----------------------------------------------------------------------|
| Team names              | Must match exactly between `teams.json`, `bracket.json`, and API mapping. |
| Elo ratings             | Must be positive integers; updates must not produce negative values. |
| `played.json` winner    | Must exist in `teams.json`.                                          |
| Bracket consistency     | Every `source_matches` list must contain valid `match_id`s.          |
| API mapping             | Every external `id` maps to exactly one internal `match_id`.         |
| Simulation probabilities| Must sum to 1.0 (±0.001 floating tolerance).                         |

---

## 7. Schema Evolution Plan (Post‑MVP)

Already implemented:
- ✅ **Group stage** (`groups.json`, `annex_c.json`, `team_aliases.json`, `played_groups.json`)
- ✅ **48-team dataset** with Elo ratings, group assignments
- ✅ **BSD API integration** replacing Football-Data.org

If we later add:
- **Player data** → `players.json` with individual Elo (advanced).
- **Historical logs** → `history/` folder with timestamped snapshots of probabilities.

These schemas remain frozen for future versions.

---

## 8. Example End‑to‑End Data Flow (Annotated)

1. **Start:**  
   `teams.json` loaded → in‑memory `teams` dict.  
   `bracket.json` loaded → in‑memory `bracket` tree.  
   `played.json` loaded → `played_set` and `played_details`.

2. **API returns:**  
   `{"id": 123456, "homeTeam": {"name": "Argentina"}, "awayTeam": {"name": "Nigeria"}, "winner": "HOME_TEAM"}`

3. **Mapping:**  
   `api_id_mapping.json["123456"]` → `"R16_1"`

4. **Check against `played_set`:**  
   `"R16_1"` not present → new match.

5. **Construct match dict:**  
   `match = {"match_id": "R16_1", "team_a": "Argentina", "team_b": "Nigeria", "winner": "Argentina", "home_score": 2, "away_score": 1}`

6. **Elo update:**  
   `update_ratings("Argentina", "Nigeria", "Argentina", current_elos)` → returns new elos.

7. **Merge into `teams` dict:**  
   `teams["Argentina"]["elo"] = 2112`, `teams["Nigeria"]["elo"] = 1838`.

8. **Save:**  
   `save_teams(teams)`, `save_played_matches(played_details)`.

9. **Simulation:**  
   `run_monte_carlo(teams, bracket, played_set)` → probabilities.

10. **Output:**  
    Formatted table printed.

---

## 9. Security & Secrets

- API key **never** stored in JSON files.  
- Read from environment variable `BSD_API_KEY`.  
- Example in `main.py`:
  ```python
  import os
  API_KEY = os.environ.get("BSD_API_KEY")
  if not API_KEY:
      raise ValueError("Set BSD_API_KEY environment variable")
  ```

---

## 10. Backend Schema Diagram (Textual)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌───────────────────┐
│   teams.json    │     │  bracket.json   │     │  played.json    │     │ played_groups.json│
│ ┌─────────────┐ │     │ ┌─────────────┐ │     │ ┌─────────────┐ │     │ ┌───────────────┐ │
│ │Argentina:   │ │     │ │R16_1:       │ │     │ │R16_1:       │ │     │ │GS_A_01:      │ │
│ │  elo: 2112  │ │     │ │  Arg vs Nig │ │     │ │  winner: Arg│ │     │ │  Mexico 2-1  │ │
│ │  eliminated:│ │     │ │  winner:null│ │     │ │  scores     │ │     │ │  S.Africa     │ │
│ │  false      │ │     │ └─────────────┘ │     │ └─────────────┘ │     │ └───────────────┘ │
│ └─────────────┘ │     │ ┌─────────────┐ │     │                 │     │                   │
│ ┌─────────────┐ │     │ │QF_1:        │ │     │                 │     │ ┌───────────────┐ │
│ │France:      │ │     │ │  src:R16_1, │ │     │                 │     │ │GS_A_02:      │ │
│ │  elo: 2075  │ │     │ │  R16_2      │ │     │                 │     │ │  Italy 1-1   │ │
│ └─────────────┘ │     │ └─────────────┘ │     │                 │     │ │  Chile       │ │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └───────────────────┘
         ▲                       ▲                       ▲                       ▲
         │                       │                       │                       │
         └───────────────────────┼───────────────────────┼───────────────────────┘
                                 │                       │
                         ┌───────┴───────────────────────┴───────┐
                         │            main.py                     │
                         │    groups → Annex C → bracket          │
                         │    (in‑memory structures)               │
                         └────────────────────────────────────────┘
                                 │
                                 ▼
                         ┌───────────────┐
                         │  console      │
                         │  output       │
                         │  + standings  │
                         └───────────────┘
```

---

**Approval (for your own sign‑off):**

- [ ] All JSON schemas defined with examples.
- [ ] Module function signatures specified.
- [ ] API contract documented.
- [ ] Validation rules listed.
- [ ] Security (API key via env var) addressed.
```