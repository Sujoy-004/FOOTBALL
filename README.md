<!-- generated-by: gsd-doc-writer -->
# FOOTBALL Monte Carlo Prediction Engine

A Python Monte Carlo simulation engine that predicts football tournament outcomes — knockout probabilities, group standings, and championship odds — across three major competitions. The sole interface is a **FastAPI web dashboard** (`python -m web.server`) with a retro terminal-emulator aesthetic.

| Competition | Route | Status | Tests |
|---|---|---|---|
| **World Cup 2026** | `/worldcup` | Active — live polling via BSD API | 614 |
| **UCL 2025/26** | `/ucl` | Active — single-run Monte Carlo | 438 |
| **Euro 2024** | `/euro` | Dormant — stub | — |
| **football_core** | Shared library | — | 109 |

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd FOOTBALL

# 2. Install Python dependencies
pip install -r competitions/worldcup/requirements.txt
pip install requests numpy fastapi uvicorn

# 3. Configure data provider
cp .env.example .env  # or edit .env directly
# Edit .env and set FOOTBALL_DATA_ORG_KEY (free key from https://www.football-data.org/client/register)
# The default DATA_PROVIDER=football-data uses this key for match results.
# BSD API key is optional — set DATA_PROVIDER=bsd and BSD_API_KEY if available.

# 4. Start the web dashboard
python -m web.server

# 5. Open in browser: http://127.0.0.1:8080
```

## Web Dashboard

The dashboard is a **vanilla JS SPA** served from `web/static/` over a unified FastAPI server on port 8080. No bundler, no build step — edit and reload.

| Path | Competition | Description |
|---|---|---|
| `/` | Landing page | Competition selector |
| `/worldcup` | World Cup 2026 | Dashboard, bracket, standings, what-if, terminal |
| `/worldcup/api/*` | WC backend | REST API |
| `/ucl` | UCL 2025/26 | Overview, league table, bracket, odds, terminal |
| `/ucl/api/*` | UCL backend | REST API |
| `/euro` | Euro 2028 | Stub (`{"status": "coming_soon"}`) |

### CLI-Vibe Terminal UX

The dashboard greets you with a **retro terminal** as the default tab. Type `help` to see available commands. The terminal supports:

- **Commands:** `simulate`, `validate`, `calibrate`, `what-if`, `export`, `standings`, `bracket`, `odds`, `elo`, `signals`, `clear`, `help`, and more
- **Inline progress bars:** `[====>    ] 60%` during long operations
- **Sparklines:** `▁▂▃▄▅▆▇█` in result cells
- **Animated spinner:** `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` during API calls
- **Collapsible drawer:** Press `` Ctrl+` `` or click the status-bar toggle to open the terminal from any tab (slides up 300px)
- **Color-coded output:** Warm earth tones for WC, bluish for UCL

### API Endpoints

**World Cup** (`/worldcup/api`): `data`, `standings`, `bracket`, `bracket/full`, `evaluation`, `governance`, `signals`, `signal/{name}`, `blend`, `refresh` (async), `simulate` (async), `what-if`, `match/insight`, `validation`, `report`, `calibrate` (async)

**UCL** (`/ucl/api`): `data`, `standings`, `bracket`, `odds`, `signals`, `simulate` (async), `reset`, `mode`, `what-if`, `match/insight`, `validation`, `report`, `calibrate` (async)

Long operations (simulate, calibrate, refresh) use an async task + polling pattern — POST returns a `task_id`, then GET `progress/{task_id}` until complete.

### Running the Web Server

```bash
# Standard start
python -m web.server

# Development with hot reload
uvicorn web.server:asgi_app --reload --host 127.0.0.1 --port 8080
```

## World Cup 2026

48 teams, 12 groups (A–L), 104 total matches (72 group + 32 knockout), annex C routing for the 8 best third-placed teams. Fetches live match data from the BSD API, updates Elo ratings, refreshes signal caches, blends 8 prediction signals (Elo, market odds, CatBoost, form, lineup, availability, defensive quality, manager effect), and runs 50,000 Monte Carlo iterations per cycle.

Accessible at `http://127.0.0.1:8080/worldcup`.

## UCL 2025/26

36-team Swiss-system league phase (8 matchdays), playoff round (positions 9–24), seeded R16 bracket with top-4 protection, two-legged knockout ties with extra time and penalties. Uses a 5-signal ensemble (RefinedElo, MarketOdds, RollingForm, SquadValue, RestDays) via `EnsembleEngine`.

Accessible at `http://127.0.0.1:8080/ucl`.

## Euro 2024 (dormant)

Continuous polling predictor for UEFA Euro 2024. Shares architecture with the World Cup predictor but is currently in a dormant state. The `/euro` route returns a "coming soon" stub.

## Project Structure

```
FOOTBALL/
├── football_core/              ← Shared engine library
│   ├── elo.py                  Elo rating math
│   ├── elo_fetcher.py          Elo rating fetch from external sources
│   ├── elo_sync.py             Elo sync from eloratings.net
│   ├── fetcher.py              BSD API fetch + match dedup
│   ├── groups.py               Poisson simulation + FIFA tiebreaker chain
│   ├── knockout.py             Generic round simulation primitive
│   ├── blender.py              Signal blending and weighting
│   ├── enrichment.py           Match data enrichment pipeline
│   ├── evaluation.py           Brier score, log loss, calibration, ECE
│   ├── state.py                JSON persistence layer
│   ├── glicko.py               Glicko-1 Bayesian rating with uncertainty
│   ├── math_utils.py           Sigmoid and other math helpers
│   ├── constants.py            Shared configuration constants
│   ├── signal.py               Signal computation framework
│   ├── provider.py             Data provider protocols (DataProvider, FixtureProvider)
│   ├── result_provider.py      Result data provider
│   ├── data_providers/         Data provider implementations
│   │   ├── bsd_provider.py     BSD API provider (sports.bzzoiro.com)
│   │   └── football_data_org_provider.py  football-data.org v4 provider
│   ├── providers/              BSD data providers (legacy wrappers)
│   │   ├── manager.py          Manager profile fetcher & parser
│   │   ├── player.py           Player profile fetcher & parser
│   │   └── team.py             Team ID-to-name mapping
│   ├── predictors/             Signal ingestion pipeline
│   │   ├── odds.py             Market odds fetcher
│   │   └── catboost.py         CatBoost prediction fetcher
│   ├── signals/                11 prediction signal implementations
│   └── tests/                  6 modules, 109 tests
│
├── competitions/
│   ├── worldcup/               ← World Cup 2026 (active)
│   │   ├── requirements.txt
│   │   ├── .env.example
│   │   ├── config.json         League ID (27)
│   │   ├── src/                WC-specific modules
│   │   │   ├── elo.py, elo_sync.py, fetcher.py, state.py
│   │   │   ├── groups.py, knockout.py
│   │   │   ├── evaluation.py, blender.py, governance.py
│   │   │   ├── engine.py, analysis.py
│   │   │   └── predictors/     Signal ingestion
│   │   ├── tests/              26 modules, 614 tests
│   │   ├── data/               JSON state files
│   │   └── .github/workflows/  CI pipeline
│   │
│   ├── ucl/                    ← UCL 2025/26 (active)
│   │   ├── result.py           SimulationResult contract
│   │   ├── report.py           Structured JSON report builder
│   │   ├── config/             Signal weights and calibration JSON
│   │   ├── src/                UCL-specific modules
│   │   │   ├── simulation.py, knockout.py, groups.py
│   │   │   ├── orchestrator.py, analysis.py
│   │   │   ├── fetcher.py, elo_fetcher.py, provider.py
│   │   │   ├── validation.py, validation_suite.py
│   │   │   └── calibrate.py
│   │   ├── tests/              23 modules, 438 tests
│   │   ├── benchmarks/         Performance benchmarks
│   │   └── data/               Fixture data, bracket rules
│   │
│   └── euro/                   ← Euro 2024 (dormant)
│       ├── config.py           Competition configuration
│       ├── simulation.py       Euro-specific simulation logic
│       └── data/               Teams, groups, bracket data
│
├── web/                        ← FastAPI web dashboard (port 8080)
│   ├── server.py               Parent FastAPI — mounts sub-apps, serves static
│   ├── common.py               Shared backend utilities
│   ├── wc_app.py               WC sub-app (mounted at /worldcup)
│   ├── ucl_app.py              UCL sub-app (mounted at /ucl)
│   ├── insight.py              WC match insight engine
│   ├── whatif_engine.py        Shared what-if scenario engine
│   ├── cache.json              Web data cache (auto-generated)
│   └── static/
│       ├── index.html           SPA shell
│       ├── shared.css           Design system CSS
│       ├── shared.js            Router, terminal, modal, tabs
│       ├── wc.js                WC dashboard views
│       └── ucl.js               UCL dashboard views
│
└── docs/
    ├── ARCHITECTURE.md
    ├── CONFIGURATION.md
    ├── DEVELOPMENT.md
    ├── GETTING-STARTED.md
    ├── TESTING.md
    ├── WEB_LAYER.md
    ├── FOOTBALL_ENGINE_ARCHITECTURE.md
    ├── ARCHITECTURE_RESEARCH.md
    └── COMMONALITY_REPORT.md
```

## Data Provider Architecture

The engine uses a pluggable provider system to fetch external data. Two providers are available:

| Provider | Source | Match Results | Predictions | Managers | Players |
|---|---|---|---|---|---|
| **FootballDataOrg** | `api.football-data.org/v4` | ✅ (WC, CL, ...) | ❌ | ❌ | ❌ |
| **BSD** | `sports.bzzoiro.com` | ✅ (requires key) | ✅ | ✅ | ✅ |

Selection is driven by the `DATA_PROVIDER` env var in `.env`:
- `football-data` (default) — match results from football-data.org; BSD-only signals degrade gracefully
- `bsd` — all data from BSD API (requires non-blocked network + `BSD_API_KEY`)

When a provider cannot return data (network blocked, missing key, rate-limited), the corresponding signals are marked `available: false` in the UI and weighted at zero by the blender. The Monte Carlo simulation still runs on the remaining active signals (Elo, form, lineup, squad value).

### Protocol

All providers implement `football_core.provider.DataProvider`:

```python
class DataProvider(Protocol):
    def fetch_matches(self, competition_id: str, **kwargs) -> list[dict]: ...
    def fetch_predictions(self, competition_id: str, **kwargs) -> list[dict]: ...
    def fetch_managers(self, competition_id: str, **kwargs) -> list[dict]: ...
    def fetch_players(self, competition_id: str, **kwargs) -> list[dict]: ...
```

New providers can be added by implementing this protocol and registering in the `_get_data_provider()` factory in `web/wc_app.py`.

## Requirements

- **Python:** 3.10, 3.11, or 3.12
- **Dependencies:** pytest, pytest-cov, python-dotenv, requests, numpy, fastapi, uvicorn
- **API key (recommended):** A free [football-data.org key](https://www.football-data.org/client/register) for live match results. Set `DATA_PROVIDER=football-data` and `FOOTBALL_DATA_ORG_KEY` in `.env`.
- **BSD API key (optional):** A free [BSD API key](https://sports.bzzoiro.com/register/) for market odds, CatBoost predictions, manager profiles, and player availability. Set `DATA_PROVIDER=bsd` and `BSD_API_KEY` in `.env`. BSD-dependent signals degrade gracefully when unavailable.

## License

No license — this project is not open source.
