# Technology Stack

**Analysis Date:** 2026-06-13

## Languages

**Primary:**
- Python 3.10+ - Core application language for all modules (fetcher, Elo updater, simulation engine, state manager, console output)

**Secondary:**
- JSON - Data persistence format (no database)

## Runtime

**Environment:**
- Python 3.10+ (CPython)
- Cross-platform: Windows, macOS, Linux (NFR5 per `SOTs/PRD.md`)

**Package Manager:**
- `pip` via `python -m venv`
- Lockfile: `requirements.txt` (planned, initially containing `requests` and later `pytest`)

## Frameworks

**Core:**
- None — pure Python standard library for MVP. No web framework, no ORM, no database client.

**Testing:**
- `pytest` (planned in `SOTs/Implementation_plan.md` Phase 2+) — for unit and integration tests

**Build/Dev:**
- `python -m venv` — virtual environment management
- No build tooling (pure interpreter, no compilation step)

## Key Dependencies

**Critical:**
- `requests` (planned) — HTTP client for polling the Football-Data.org API at `SOTs/TRD.md` + `SOTs/MVP.md`. Only external package for MVP.

**Infrastructure:**
- None for MVP — all persistence uses Python's built-in `json` module and file I/O. No database, no cache service, no message queue.

**Optional (noted for post-MVP):**
- `colorama` — for Windows ANSI color support (`SOTs/Implementation_plan.md` Phase 6)
- `tqdm` — progress bar for Monte Carlo simulation (`SOTs/UI_UX_Design.md` v1.1)
- `Flask` + `Chart.js` — planned web dashboard (post-MVP per `SOTs/PRD.md`)

## Configuration

**Environment:**
- API key from [Football-Data.org](https://www.football-data.org/) read via `os.environ.get("FOOTBALL_API_KEY")` at `SOTs/Backend_Schema.md` §9
- No `.env` files for MVP; key set directly as environment variable
- All numeric parameters (K-factor, poll interval, simulation count) are hardcoded in `constants.py` as example defaults; no config file for MVP

**Build:**
- `requirements.txt` — dependency manifest
- `.gitignore` — must include `.env` and `__pycache__/` as noted in `SOTs/Implementation_plan.md`

## Platform Requirements

**Development:**
- Python 3.10+ installed
- `pip` for package installation
- Internet connection for API polling
- Free API key from Football-Data.org
- One command to start: `python main.py`

**Production:**
- No deployment target for MVP — runs as a local terminal script
- Post-MVP possibilities: Docker container, cloud VM with persistent terminal (`SOTs/Implementation_plan.md`)

## Application Architecture (Planned)

**Pattern:** Modular single-script pipeline — 5 Python modules + 1 entry point:

```
worldcup_predictor/
├── data/
│   ├── teams.json            # Team Elo ratings and metadata
│   ├── bracket.json          # Knockout bracket tree structure
│   ├── played.json            # Completed match records
│   └── api_id_mapping.json   # External API ID -> internal match_id
├── src/
│   ├── __init__.py
│   ├── constants.py          # Configurable defaults (K=60, poll=60s, sim=50000)
│   ├── state.py              # JSON persistence layer (load/save atomic writes)
│   ├── elo.py                # Elo rating formula implementation
│   ├── simulator.py          # Match + tournament + Monte Carlo simulation
│   ├── fetcher.py            # Football-Data.org API client + match processing
│   └── output.py             # Console formatting with ANSI colors
├── tests/
│   ├── test_state.py         # JSON roundtrip tests
│   ├── test_elo.py           # Elo formula verification
│   ├── test_simulator.py     # Simulation correctness
│   └── integration_test.py   # Mock API end-to-end test
├── main.py                   # Entry point — infinite polling loop
└── requirements.txt          # pip dependencies
```

**Data Flow:** External API → Fetcher → State Manager (JSON persistence) → Elo Updater → Simulation Engine → Console Output — all orchestrated by `main.py` synchronous loop.

---

*Stack analysis: 2026-06-13*
