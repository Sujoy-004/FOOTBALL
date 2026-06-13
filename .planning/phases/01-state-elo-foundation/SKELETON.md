# Walking Skeleton — World Cup Dynamic Prediction

> **Phase 1: State & Elo Foundation**
> **Decision:** This skeleton is produced once and frozen. Subsequent phases build on it without renegotiating these architectural choices.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   main.py                            │
│         (entry point — loads state, records          │
│          matches, drives Phase 1 flow)               │
└────────────┬──────────────────────────┬──────────────┘
             │                          │
    ┌────────▼────────┐       ┌─────────▼─────────┐
    │   src/state.py   │       │    src/elo.py      │
    │  (persistence)   │       │  (core logic)      │
    │  6 load/save     │       │ expected_score()   │
    │  functions +     │       │ update_ratings()   │
    │  validate_       │       │                    │
    │  bracket()       │       │                    │
    └────────┬─────────┘       └────────────────────┘
             │
             ▼
    ┌──────────────────────────────────┐
    │        data/ directory            │
    │  teams.json  bracket.json         │
    │  played.json  team_aliases.json   │
    └──────────────────────────────────┘
```

## Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Language** | Python 3.10+ (3.11.8 available) | Cross-platform, fast prototyping, rich stdlib |
| **Package structure** | `worldcup_predictor/src/` with `__init__.py` | Scales through all 6 phases (D-02) |
| **Data storage** | JSON files in `worldcup_predictor/data/` | No database setup, human-readable, atomic writes (D-03) |
| **Testing** | `pytest` 9.0.2 + `pytest-cov` 7.1.0 | Industry standard, `tmp_path` fixture for file I/O tests (D-15) |
| **Elo formula** | Standard World Football Elo: `Rn = Ro + K × (W - We)` | Verified from eloratings.net, K=60 for World Cup finals |
| **Atomic writes** | `tempfile.mkstemp()` + `os.replace()` + `os.fsync()` | `mkstemp` avoids Windows lock issues (vs NamedTemporaryFile) |
| **Bracket format** | Flat match list array (not nested rounds) | Easier validation, traversal, lookup (D-07) |
| **Runtime deps** | None — Python stdlib only | `requests` not needed until Phase 3 (API integration) |

## Directory Structure

```
worldcup_predictor/
├── src/
│   ├── __init__.py          # Package marker
│   ├── constants.py         # K_FACTOR=60, DEFAULT_ELO=1500, DATA_DIR
│   ├── state.py             # load/save/validate functions
│   └── elo.py               # expected_score(), update_ratings()
├── data/
│   ├── teams.json           # 32 teams with Elo ratings
│   ├── bracket.json         # Flat bracket (16 R16 → 4 QF → 2 SF → 1 FINAL)
│   ├── played.json          # Empty dict (seed), grows with match records
│   └── team_aliases.json    # Reference aliases (Phase 3 use, created now)
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures (sample teams, bracket)
│   ├── test_elo.py          # Elo formula tests (9 cases)
│   └── test_state.py        # Persistence + validation tests (11 cases)
├── main.py                  # Entry point
└── requirements.txt         # pytest, pytest-cov
```

## Key Contracts / Interfaces

These are the types and function signatures that downstream phases build against.

### `src/constants.py`

```python
K_FACTOR: int = 60               # Default K-factor for World Cup finals
DEFAULT_ELO: int = 1500          # Starting Elo for new teams (if needed)
DATA_DIR: Path                   # Resolved to worldcup_predictor/data/
```

### `src/state.py`

```python
def load_teams(data_dir: Path | None = None) -> dict[str, dict]: ...
def load_bracket(data_dir: Path | None = None) -> list[dict]: ...
def load_played(data_dir: Path | None = None) -> dict[str, dict]: ...
def validate_bracket(matches: list[dict]) -> None: ...
def save_teams(teams: dict[str, dict], data_dir: Path | None = None) -> None: ...
def save_bracket(bracket: list[dict], data_dir: Path | None = None) -> None: ...
def save_played(played: dict[str, dict], data_dir: Path | None = None) -> None: ...
```

### `src/elo.py`

```python
def expected_score(rating_a: float, rating_b: float, home_advantage: int = 0) -> float: ...
def update_ratings(
    team_a: str, team_b: str, winner: str,
    current_elos: dict[str, float],
    K: int = 60
) -> dict[str, float]: ...
```

### Data Schema: `data/teams.json`

```json
{
  "Argentina": {"elo": 2115},
  "France": {"elo": 2063}
}
```

### Data Schema: `data/bracket.json` (flat list)

```json
[
  {"match_id": "R16_1", "round": "R16", "team_a": "Argentina", "team_b": "Nigeria", "source_matches": null, "winner": null},
  {"match_id": "QF_1", "round": "QF", "team_a": null, "team_b": null, "source_matches": ["R16_1", "R16_2"], "winner": null}
]
```

### Data Schema: `data/played.json`

```json
{
  "R16_1": {
    "team_a": "Argentina", "team_b": "Mexico",
    "winner": "Argentina", "home_score": 2, "away_score": 1,
    "completed_at": "2026-06-15T22:05:01Z"
  }
}
```

### Data Schema: `data/team_aliases.json`

```json
{
  "United States": ["USA", "United States of America"],
  "Iran": ["IR Iran", "Islamic Republic of Iran"],
  "South Korea": ["Korea Republic"]
}
```

## Data Flow (Phase 1)

1. **Startup:** `main.py` calls `state.load_teams()`, `state.load_bracket()`, `state.load_played()`
2. **Validation:** `state.validate_bracket()` runs inside `load_bracket()` — rejects bad bracket data
3. **Match recording:** `--record-match <id> <winner> <score_a> <score_b>` triggers:
   - `elo.update_ratings()` → computes new ratings
   - `state.save_teams()` → atomically writes teams.json
   - `state.save_played()` → atomically writes played.json
4. **Persistence guarantee:** All writes use tempfile + os.replace + os.fsync (no partial/corrupt files)

## How to Run

```bash
# Setup
cd worldcup_predictor
pip install -r requirements.txt

# Run (load & validate only)
python main.py

# Record a match result
python main.py --record-match R16_1 Argentina 2 1

# Run tests
python -m pytest tests/ -v
```

## Boundaries / What This Skeleton Does NOT Cover

| Not Included | Where It Goes | Why |
|-------------|---------------|-----|
| API integration (polling) | Phase 3 | No `requests` dependency yet |
| Monte Carlo simulation | Phase 2 | Needs state layer and Elo to build on |
| Console output formatting | Phase 5 | Rich ANSI tables and delta tracking |
| Infinite main loop | Phase 4 | Ctrl+C handling and polling cycle |
| Team name normalization | Phase 3 (DATA-04) | Placeholder file created, logic deferred |
| api_id_mapping.json | Phase 3 | Not created in Phase 1 (D-09) |
| NumPy optimization | Phase 2 | Performance gate, not Phase 1 |

## Build Order (Waves)

| Wave | Plans | Description |
|------|-------|-------------|
| 1 | 01 | Project scaffold, state loading, bracket validation, seed data, main.py entry |
| 2 | 02 | Elo engine, state persistence (atomic writes), match recording in main.py |

---

*Skeleton frozen: 2026-06-13 for Phase 1 of World Cup Dynamic Prediction*
