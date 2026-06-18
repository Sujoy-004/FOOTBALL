# Technology Stack

**Analysis Date:** 2026-06-16

## Languages

- **Python 3.10+** — Core application language for all 11 src modules (fetcher, Elo updater, groups engine, knockout simulation, state manager, console output, Elo sync, evaluation)
- **JSON** — Data persistence format (no database)

## Runtime

- Python 3.10+ (CPython) — cross-platform: Windows, macOS, Linux
- Package manager: `pip` via `python -m venv`
- Lockfile: `requirements.txt`

## Frameworks

- **Core:** None — pure Python standard library. No web framework, no ORM, no database client.
- **Testing:** `pytest >= 9.0` — unit and integration tests (329 tests across 16 test files)
- **Coverage:** `pytest-cov >= 7.1`
- **Build/Dev:** No build tooling (pure interpreter)

## Key Dependencies

**Runtime:**
- `requests` (implicit, not in requirements.txt) — HTTP client for BSD Sports Data API and eloratings.net. Only external runtime package.
- `python-dotenv >= 1.0` — `.env` file loading

**Test:**
- `pytest >= 9.0`
- `pytest-cov >= 7.1`

**Stdlib (no install needed):**
- `json` — state persistence
- `random` — Monte Carlo PRNG (deterministic via `random.seed()`)
- `math` — Elo formula, Poisson model
- `collections` — `defaultdict`, `Counter` for aggregations
- `itertools` — group round-robin pairings
- `enum` — round identifiers, group labels (not currently used)
- `dataclasses` — structured models (minimal use)
- `os`, `sys`, `time`, `tempfile`, `pathlib`, `csv`, `io`, `logging`, `copy`, `functools`

## Configuration

- **Environment:** API key from BSD Sports Data via `os.environ.get("BSD_API_KEY")`
- **Override:** `POLL_INTERVAL` configurable via environment variable
- **Hardcoded:** K-factor, simulation count, default Elo, API URL, group constants in `constants.py`
- **`.env.example`:** Provided with BSD_API_KEY placeholder

## Platform Requirements

- Python 3.10+ installed
- Internet connection for BSD API polling
- Free API key from BSD (Bzzoiro Sports Data)
- One command to start: `python main.py`

## Application Architecture (3-layer)

```
External API Layer          │ BSD Sports Data │ Eloratings.net
                            │                 │
Integration Layer           │ fetcher.py      │ elo_sync.py
                            │                 │
State/Persistence Layer     │ state.py        │
                            │                 │
Core Logic Layer            │ elo.py │ groups.py │ knockout.py │ simulation.py
                            │        │ evaluation.py                        │
Output/Presentation Layer   │ output.py                                      │
                            │                                                  │
Orchestration Layer         │ main.py (entry point)                            │
```

## Requirements.txt (current)
```
pytest>=9.0
pytest-cov>=7.1
python-dotenv>=1.0
```

Note: `requests` is imported by `fetcher.py` and `elo_sync.py` but not listed in `requirements.txt` — installed as transitive or system-level dependency.

---

*Stack analysis: 2026-06-16*
